"""Daily news run and the render → Anthias → YouTube pipeline."""
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import anthias, db, news, render, writer, youtube

log = logging.getLogger("beacon.jobs")
_q: "queue.Queue[int]" = queue.Queue()
_fetch_lock = threading.Lock()
scheduler = BackgroundScheduler(timezone="UTC")  # jobs carry their own tz


# ---------- daily news run ----------
def run_fetch():
    if not _fetch_lock.acquire(blocking=False):
        return "A fetch is already running"
    started = db.now()
    try:
        s = db.get_settings()
        if not s.get("llm_api_key") and s["llm_provider"] == "anthropic":
            raise RuntimeError("No LLM API key set (Settings → AI)")
        heads = news.fetch_headlines(s["feeds"].splitlines())
        issues = writer.generate(s, heads, db.recent_topics())
        for it in issues:
            db.add_issue(it)
        msg = f"{len(heads)} headlines → {len(issues)} topic{'' if len(issues) == 1 else 's'}"
        ok = bool(issues)
        if not issues:
            msg += " — the AI's reply had no usable topics (see 'last AI reply' link)"
        db.log_run(started, ok, msg)
        return msg
    except Exception as e:
        log.exception("fetch failed")
        db.log_run(started, False, str(e)[:500])
        return f"Failed: {e}"
    finally:
        _fetch_lock.release()


def schedule():
    s = db.get_settings()
    hh, mm = (s.get("fetch_time") or "06:00").split(":")
    scheduler.remove_all_jobs()
    scheduler.add_job(run_fetch, "cron", hour=int(hh), minute=int(mm),
                      timezone=s.get("timezone") or "America/Indiana/Indianapolis", id="daily_fetch")
    scheduler.add_job(cleanup, "cron", hour=3, minute=17, id="cleanup")


def cleanup():
    days = int(db.get_setting("keep_days") or 30)
    cutoff = time.time() - days * 86400
    for f in os.listdir(db.VIDEO_DIR):
        p = os.path.join(db.VIDEO_DIR, f)
        if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
            os.remove(p)


# ---------- render / publish pipeline ----------
def enqueue(issue_id):
    """Render and publish everywhere (used by Approve)."""
    db.update_issue(issue_id, status="queued", log="")
    _q.put(("full", issue_id))


TARGET_NAMES = {"anthias": "Anthias", "youtube": "YouTube"}


def enqueue_republish(issue_id, target):
    """Send an already-published topic to one destination again (bulk actions)."""
    db.update_issue(issue_id, status="publishing")
    db.append_log(issue_id, f"Queued: republish to {TARGET_NAMES[target]}")
    _q.put((target, issue_id))


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:50] or "topic"


def process(issue_id):
    s = db.get_settings()
    issue = db.get_issue(issue_id)
    db.update_issue(issue_id, status="rendering")
    font = render.find_font(s.get("font_path", ""))
    texts = render.card_texts(issue)
    out = os.path.join(db.VIDEO_DIR, f"{datetime.now():%Y%m%d}-{issue_id}-{_slug(issue['topic'])}.mp4")
    n, per = render.render_video(texts, issue["duration"], font, out)
    db.update_issue(issue_id, video_path=out, status="rendered")
    db.append_log(issue_id, f"Rendered {n} card(s), {per:.1f}s each → {os.path.basename(out)}")

    problems = []
    if s.get("anthias_enabled") == "1":
        if not send_to_anthias(issue_id, s, out, issue):
            problems.append("Anthias")
    else:
        db.append_log(issue_id, "Anthias: skipped — 'Send approved videos to Anthias' is off in Settings")

    if s.get("youtube_enabled") == "1":
        if not send_to_youtube(issue_id, s, out, issue):
            problems.append("YouTube")

    db.update_issue(issue_id, status="error" if problems else "done")


def ensure_video(issue_id):
    """Path to the topic's MP4, re-rendering it if it was cleaned up."""
    issue = db.get_issue(issue_id)
    if issue["video_path"] and os.path.isfile(issue["video_path"]):
        return issue["video_path"]
    s = db.get_settings()
    font = render.find_font(s.get("font_path", ""))
    out = os.path.join(db.VIDEO_DIR, f"{datetime.now():%Y%m%d}-{issue_id}-{_slug(issue['topic'])}.mp4")
    n, per = render.render_video(render.card_texts(issue), issue["duration"], font, out)
    db.update_issue(issue_id, video_path=out)
    db.append_log(issue_id, f"Video file was gone, so it was rendered again ({n} card(s))")
    return out


def republish(issue_id, target):
    s = db.get_settings()
    issue = db.get_issue(issue_id)
    path = ensure_video(issue_id)
    send = send_to_anthias if target == "anthias" else send_to_youtube
    ok = send(issue_id, s, path, issue)
    db.update_issue(issue_id, status="done" if ok else "error")


def send_to_youtube(issue_id, s, video_path, issue):
    try:
        texts = render.card_texts(issue)
        tags = list(dict.fromkeys(issue["yt_tags"] + [t.strip() for t in s.get("youtube_extra_tags", "").split(",") if t.strip()]))
        desc = "\n\n".join(x for x in [
            " / ".join(texts),
            issue.get("summary", ""),
            "Sources:\n" + "\n".join(issue["sources"]) if issue["sources"] else "",
            s.get("youtube_description", ""),
        ] if x)
        vid = youtube.upload(s, video_path, issue["yt_title"] or (texts[0] if texts else issue["topic"]), desc, tags)
        db.update_issue(issue_id, youtube_id=vid)
        db.append_log(issue_id, f"Uploaded to YouTube: https://youtu.be/{vid}")
        return True
    except Exception as e:
        db.append_log(issue_id, f"YouTube upload failed: {e}")
        return False


def send_to_anthias(issue_id, s, video_path, issue):
    try:
        aid = anthias.upload(s, video_path, f"Beacon: {issue['topic']}", issue["duration"],
                             log=lambda m: db.append_log(issue_id, m))
        db.update_issue(issue_id, anthias_id=aid)
        db.append_log(issue_id, f"Added to Anthias playlist (asset {aid})")
        return True
    except Exception as e:
        db.append_log(issue_id, f"Anthias upload failed: {e}")
        return False


def _worker():
    while True:
        kind, iid = _q.get()
        try:
            if not db.get_issue(iid):      # deleted while waiting in the queue
                continue
            if kind == "full":
                process(iid)
            else:
                republish(iid, kind)
        except Exception as e:
            log.exception("pipeline failed for %s", iid)
            db.update_issue(iid, status="error")
            db.append_log(iid, f"Failed: {e}")
        finally:
            _q.task_done()


def start():
    schedule()
    scheduler.start()
    threading.Thread(target=_worker, daemon=True).start()
    # resume anything interrupted by a restart
    for it in db.list_issues(["queued", "rendering"]):
        enqueue(it["id"])
    for it in db.list_issues(["publishing"]):
        db.update_issue(it["id"], status="error")
        db.append_log(it["id"], "Republish was interrupted by a restart — run it again")
