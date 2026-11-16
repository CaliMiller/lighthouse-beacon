"""Lighthouse Beacon web UI + JSON API."""
import base64
import json
import logging
import os
import secrets
import tempfile
import threading

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import anthias, db, jobs, render, writer, youtube

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
HERE = os.path.dirname(__file__)
SECRET_KEYS = {"llm_api_key", "anthias_password", "youtube_client_config", "youtube_token"}
HIDDEN_KEYS = {"youtube_pending_verifier"}
MASK = "••••••••"
PASSWORD = os.environ.get("BEACON_PASSWORD", "")

app = FastAPI(title="Lighthouse Beacon", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.exception_handler(Exception)
async def _any_error(request: Request, exc: Exception):
    logging.getLogger("beacon").exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if PASSWORD:
        hdr = request.headers.get("authorization", "")
        ok = False
        if hdr.startswith("Basic "):
            try:
                _, pw = base64.b64decode(hdr[6:]).decode().split(":", 1)
                ok = secrets.compare_digest(pw, PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Lighthouse Beacon"'})
    return await call_next(request)


@app.on_event("startup")
def _startup():
    db.init()
    jobs.start()


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "templates", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/favicon.ico")
def favicon():
    return FileResponse(os.path.join(HERE, "static", "favicon.svg"), media_type="image/svg+xml")


# ---------- issues ----------
VIEWS = {"pending": ["pending"], "published": ["queued", "rendering", "rendered", "done", "error"],
         "declined": ["declined"]}


@app.get("/api/issues")
def list_issues(view: str = "pending"):
    return db.list_issues(VIEWS.get(view, ["pending"]))


def _get(iid):
    it = db.get_issue(iid)
    if not it:
        raise HTTPException(404, "No such issue")
    return it


def _save(iid, data):
    _get(iid)
    fields = {}
    for k in ("topic", "summary", "yt_title"):
        if k in data:
            fields[k] = str(data[k])
    if "duration" in data:
        fields["duration"] = max(5, min(600, int(data["duration"])))
    if "yt_tags" in data:
        tags = data["yt_tags"]
        fields["yt_tags"] = [t.strip() for t in (tags.split(",") if isinstance(tags, str) else tags) if t.strip()]
    if "bilingual" in data:
        fields["bilingual"] = 1 if data["bilingual"] else 0
    db.update_issue(iid, **fields)
    if "cards" in data:
        db.replace_cards(iid, [c for c in data["cards"] if c.get("text_en", "").strip()])
    return db.get_issue(iid)


@app.post("/api/issues")
def create_issue(data: dict = Body(...)):
    iid = db.add_issue({"topic": data.get("topic") or "My message", "summary": "", "lines": [{"en": data.get("text", ""), "es": ""}],
                        "yt_title": data.get("text", "")[:100], "duration": 30})
    return db.get_issue(iid)


@app.put("/api/issues/{iid}")
def save_issue(iid: int, data: dict = Body(...)):
    return _save(iid, data)


@app.post("/api/issues/{iid}/approve")
def approve(iid: int, data: dict = Body(default={})):
    it = _save(iid, data) if data else _get(iid)
    if not render.card_texts(it):
        raise HTTPException(400, "Select at least one line to put on the video")
    jobs.enqueue(iid)
    return db.get_issue(iid)


@app.post("/api/issues/{iid}/decline")
def decline(iid: int):
    _get(iid)
    db.update_issue(iid, status="declined")
    return {"ok": True}


@app.post("/api/issues/{iid}/restore")
def restore(iid: int):
    _get(iid)
    db.update_issue(iid, status="pending")
    return db.get_issue(iid)


@app.delete("/api/issues/{iid}")
def delete(iid: int):
    it = _get(iid)
    with db.conn() as c:
        c.execute("DELETE FROM issues WHERE id=?", (iid,))
    if it["video_path"] and os.path.isfile(it["video_path"]):
        os.remove(it["video_path"])
    return {"ok": True}


@app.get("/api/issues/{iid}/video")
def video(iid: int):
    it = _get(iid)
    if not it["video_path"] or not os.path.isfile(it["video_path"]):
        raise HTTPException(404, "No video yet")
    return FileResponse(it["video_path"], media_type="video/mp4", filename=os.path.basename(it["video_path"]))


@app.get("/api/recommend")
def recommend(cards: int = 1):
    return {"seconds": writer.recommend_duration(cards)}


@app.post("/api/preview")
def preview(data: dict = Body(...)):
    s = db.get_settings()
    try:
        font = render.find_font(s.get("font_path", ""))
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    text = (data.get("text") or "").strip() or " "
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        n = render.preview_png(text, font, tmp.name)
    body = open(tmp.name, "rb").read()
    os.remove(tmp.name)
    return Response(body, media_type="image/png", headers={"X-Card-Count": str(n)})


@app.post("/api/card-count")
def card_count(data: dict = Body(...)):
    """How many on-screen cards the given texts expand to (long text auto-splits)."""
    s = db.get_settings()
    try:
        font = render.find_font(s.get("font_path", ""))
    except FileNotFoundError:
        n = len(data.get("texts", []))
        return {"cards": n, "recommended": writer.recommend_duration(n)}
    n = len(render.layout_cards(data.get("texts", []), font))
    return {"cards": n, "recommended": writer.recommend_duration(n)}


# ---------- runs ----------
@app.get("/api/last-reply")
def last_reply():
    p = writer.raw_path()
    if not os.path.isfile(p):
        raise HTTPException(404, "No AI reply saved yet")
    return FileResponse(p, media_type="text/plain; charset=utf-8")


@app.post("/api/fetch")
def fetch_now():
    threading.Thread(target=jobs.run_fetch, daemon=True).start()
    return {"ok": True}


@app.get("/api/status")
def status():
    nxt = jobs.scheduler.get_job("daily_fetch")
    try:
        font = render.find_font(db.get_setting("font_path"))
    except FileNotFoundError:
        font = ""
    return {"fetching": jobs._fetch_lock.locked(), "queue": jobs._q.qsize(), "runs": db.last_runs(),
            "next_fetch": nxt.next_run_time.isoformat() if nxt and nxt.next_run_time else None, "font": font}


# ---------- settings ----------
@app.get("/api/settings")
def get_settings():
    s = db.get_settings()
    return {k: (MASK if k in SECRET_KEYS and v else v) for k, v in s.items() if k not in HIDDEN_KEYS}


@app.put("/api/settings")
def put_settings(data: dict = Body(...)):
    clean = {k: v for k, v in data.items()
             if k in db.DEFAULT_SETTINGS and k not in HIDDEN_KEYS and not (k in SECRET_KEYS and v == MASK)}
    if clean.get("youtube_client_config", "").strip():
        try:
            clean["youtube_client_config"] = json.dumps(youtube.parse_client_config(clean["youtube_client_config"]))
        except ValueError as e:
            raise HTTPException(400, str(e))
    if "fetch_time" in clean:
        hh, mm = clean["fetch_time"].split(":")
        assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
    db.set_settings(clean)
    jobs.schedule()
    return get_settings()


@app.post("/api/settings/font")
async def upload_font(file: UploadFile = File(...)):
    os.makedirs(os.path.join(db.DATA_DIR, "fonts"), exist_ok=True)
    path = os.path.join(db.DATA_DIR, "fonts", "ArialBlack.ttf")
    with open(path, "wb") as f:
        f.write(await file.read())
    db.set_settings({"font_path": path})
    return {"font_path": path}


@app.post("/api/test/llm")
def test_llm():
    import time
    t = time.time()
    try:
        out = writer.test_connection(db.get_settings())
        return {"message": f"OK in {time.time() - t:.1f}s — model replied: {out}"}
    except Exception as e:
        return JSONResponse({"message": f"Failed: {type(e).__name__}: {e}"}, status_code=400)


@app.post("/api/test/anthias")
def test_anthias():
    try:
        return {"message": anthias.test(db.get_settings())}
    except Exception as e:
        return JSONResponse({"message": f"Failed: {e}"}, status_code=400)


@app.post("/api/youtube/client")
async def yt_client_upload(file: UploadFile = File(...)):
    try:
        cfg = youtube.parse_client_config((await file.read()).decode("utf-8", "replace"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.set_settings({"youtube_client_config": json.dumps(cfg), "youtube_token": ""})
    return {"ok": True, "client_id": (cfg.get("installed") or cfg.get("web"))["client_id"]}


@app.post("/api/youtube/auth-url")
def yt_auth_url():
    try:
        return {"url": youtube.auth_url(db.get_settings())}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/youtube/finish")
def yt_finish(data: dict = Body(...)):
    try:
        return youtube.finish_auth(db.get_settings(), data.get("url", ""))
    except Exception as e:
        raise HTTPException(400, f"Authorization failed: {e}")


@app.get("/api/youtube/status")
def yt_status():
    try:
        return {"connected": True, **youtube.channel_info(db.get_settings())}
    except Exception as e:
        return {"connected": False, "error": str(e)}


def main():
    import uvicorn
    uvicorn.run(app, host=os.environ.get("BEACON_HOST", "0.0.0.0"), port=int(os.environ.get("BEACON_PORT", "8080")))


if __name__ == "__main__":
    main()
