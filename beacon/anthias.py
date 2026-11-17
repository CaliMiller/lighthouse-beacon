"""Push a video into the Anthias playlist (API v2)."""
import os
from datetime import datetime, timedelta, timezone

import httpx


def _client(s):
    auth = (s["anthias_user"], s["anthias_password"]) if s.get("anthias_user") else None
    # No automatic redirects: a redirected POST silently turns into a GET, which hides the real problem.
    return httpx.Client(base_url=s["anthias_url"].rstrip("/"), auth=auth, timeout=300,
                        verify=s.get("anthias_verify_tls") == "1", follow_redirects=False)


def _check(r, step):
    """Turn a failed Anthias response into a message that says what to fix."""
    if r.is_redirect:
        loc = r.headers.get("location", "")
        if "login" in loc:
            raise RuntimeError(f"{step}: Anthias asked for a login. Enter the Anthias username and "
                               "password in Settings (the ones you use for its web page).")
        raise RuntimeError(f"{step}: Anthias redirected to {loc}. Put that address in Settings → Anthias URL "
                           "(for example https:// instead of http://).")
    if r.status_code >= 400:
        hint = {401: " Check the Anthias username/password in Settings.",
                403: " Check the Anthias username/password in Settings.",
                413: " The video is too big for the web server in front of Anthias.",
                507: " The Anthias device is out of disk space."}.get(r.status_code, "")
        raise RuntimeError(f"{step}: Anthias returned {r.status_code}: {r.text[:300]}{hint}")
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"{step}: Anthias sent back a web page instead of data "
                           f"(status {r.status_code}). Is the Anthias URL correct?")


def _current_order(c):
    """Active asset ids in the order the player actually shows them."""
    assets = _check(c.get("/api/v2/assets"), "Reading the playlist")
    active = [a for a in assets if a.get("is_active", a.get("is_enabled"))]
    active.sort(key=lambda a: (a.get("play_order") or 0))
    return [a["asset_id"] for a in active if a.get("asset_id")]


def upload(s, video_path, name, duration, log=lambda m: None):
    with _client(s) as c:
        # Anthias renumbers the whole playlist in creation order whenever an asset is added,
        # so remember the real order first and put it back afterwards.
        order = _current_order(c)
        size_mb = os.path.getsize(video_path) / 1_048_576
        log(f"Anthias: uploading {os.path.basename(video_path)} ({size_mb:.1f} MB)…")
        with open(video_path, "rb") as f:
            r = c.post("/api/v2/file_asset",
                       files={"file_upload": (os.path.basename(video_path), f, "video/mp4")})
        staged = _check(r, "Uploading the file")
        if "uri" not in staged:
            raise RuntimeError(f"Uploading the file: unexpected reply from Anthias: {str(staged)[:200]}")
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=int(s.get("anthias_days") or 7))
        r = c.post("/api/v2/assets", json={
            "name": name[:120],
            "uri": staged["uri"],
            "ext": staged.get("ext", ".mp4"),
            "mimetype": "video",
            # Anthias rejects any other value for videos: it reads the real length from the file.
            "duration": 0,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "is_enabled": True,
            "nocache": False,
            "skip_asset_check": False,
            "play_order": len(order) if s.get("anthias_position", "end") != "start" else 0,
        })
        created = _check(r, "Adding it to the playlist")
        new_id = created.get("asset_id", "")
        if new_id:
            ids = [i for i in order if i != new_id]
            ids = [new_id] + ids if s.get("anthias_position") == "start" else ids + [new_id]
            try:
                r = c.post("/api/v2/assets/order", json={"ids": ",".join(ids)})
                if r.status_code >= 400:
                    raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
                where = "top" if s.get("anthias_position") == "start" else "end"
                log(f"Anthias: kept your playlist order and put the new video at the {where} ({len(ids)} items)")
            except Exception as e:
                log(f"Anthias: video added, but restoring the playlist order failed ({e}); "
                    "check the order in Anthias")
        return new_id


def test(s):
    with _client(s) as c:
        r = c.get("/api/v2/assets")
        assets = _check(r, "Reading the playlist")
        return f"OK — {len(assets)} assets on the player"
