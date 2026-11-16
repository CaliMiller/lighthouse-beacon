"""Push a video into the Anthias playlist (API v2)."""
import os
from datetime import datetime, timedelta, timezone

import httpx


def _client(s):
    auth = (s["anthias_user"], s["anthias_password"]) if s.get("anthias_user") else None
    return httpx.Client(base_url=s["anthias_url"].rstrip("/"), auth=auth, timeout=300,
                        verify=s.get("anthias_verify_tls") == "1", follow_redirects=True)


def upload(s, video_path, name, duration):
    with _client(s) as c:
        with open(video_path, "rb") as f:
            r = c.post("/api/v2/file_asset",
                       files={"file_upload": (os.path.basename(video_path), f, "video/mp4")})
        r.raise_for_status()
        staged = r.json()
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
        r.raise_for_status()
        return r.json().get("asset_id", "")


def test(s):
    with _client(s) as c:
        r = c.get("/api/v2/assets")
        r.raise_for_status()
        return f"OK — {len(r.json())} assets on the player"
