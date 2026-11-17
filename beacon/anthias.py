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


def upload(s, video_path, name, duration, log=lambda m: None):
    with _client(s) as c:
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
            "duration": int(round(duration)),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "is_enabled": True,
            "nocache": False,
            "skip_asset_check": False,
        })
        created = _check(r, "Adding it to the playlist")
        return created.get("asset_id", "")


def test(s):
    with _client(s) as c:
        r = c.get("/api/v2/assets")
        assets = _check(r, "Reading the playlist")
        return f"OK — {len(assets)} assets on the player"
