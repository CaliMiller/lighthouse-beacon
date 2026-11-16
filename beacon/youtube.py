"""YouTube upload via the Data API v3, with a headless-friendly OAuth flow.

Flow: create a "Desktop app" OAuth client in Google Cloud, paste its client_secret.json into
Settings, click Authorize, sign in. Google then redirects to http://localhost/... which won't
load on your machine — that's expected. Copy that URL from the address bar back into Settings.
"""
import json
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from . import db

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
REDIRECT = "http://localhost:8765/"


def parse_client_config(text):
    """Parse client_secret.json text, tolerating curly quotes and junk around the JSON."""
    t = (text or "").strip()
    for a, b in (("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'"), ("\u00a0", " ")):
        t = t.replace(a, b)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("That doesn't look like a client_secret.json file (no JSON found).")
    try:
        cfg = json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"client_secret.json isn't valid JSON ({e.msg} at line {e.lineno}). "
                         "Try the 'Upload client_secret.json' button instead of pasting.")
    if "installed" not in cfg and "web" not in cfg:
        if "type" in cfg and "private_key" in cfg:
            raise ValueError("That's a service-account key. YouTube needs an OAuth client ID "
                             "(Credentials → Create credentials → OAuth client ID → Desktop app).")
        raise ValueError("client_secret.json must come from an OAuth client ID (Desktop app type).")
    inner = cfg.get("installed") or cfg.get("web")
    for k in ("client_id", "client_secret"):
        if not inner.get(k):
            raise ValueError(f"client_secret.json is missing '{k}'.")
    inner.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    inner.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    return cfg


def _flow(s, verifier=None):
    if not s.get("youtube_client_config"):
        raise ValueError("Upload or paste your client_secret.json in Settings → YouTube and save first.")
    cfg = parse_client_config(s["youtube_client_config"])
    f = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=REDIRECT,
                                code_verifier=verifier, autogenerate_code_verifier=verifier is None)
    return f


def auth_url(s):
    f = _flow(s)
    url, _ = f.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    db.set_settings({"youtube_pending_verifier": f.code_verifier or ""})
    return url


def finish_auth(s, pasted):
    pasted = pasted.strip()
    code = parse_qs(urlparse(pasted).query).get("code", [None])[0] if pasted.startswith("http") else pasted
    if not code:
        raise ValueError("No ?code= found in that URL")
    f = _flow(s, verifier=s.get("youtube_pending_verifier") or None)
    f.fetch_token(code=code)
    db.set_settings({"youtube_token": f.credentials.to_json(), "youtube_pending_verifier": ""})
    return channel_info(db.get_settings())


def _creds(s):
    if not s.get("youtube_token"):
        raise RuntimeError("YouTube is not authorized yet (Settings → YouTube)")
    creds = Credentials.from_authorized_user_info(json.loads(s["youtube_token"]), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        db.set_settings({"youtube_token": creds.to_json()})
    return creds


def _svc(s):
    return build("youtube", "v3", credentials=_creds(s), cache_discovery=False)


def channel_info(s):
    resp = _svc(s).channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return {"id": "", "title": "(no channel on this account)"}
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}


def upload(s, video_path, title, description, tags):
    svc = _svc(s)
    want = (s.get("youtube_channel_id") or "").strip()
    if want:
        have = channel_info(s)["id"]
        if have != want:
            raise RuntimeError(f"Authorized channel {have} doesn't match configured channel {want}. "
                               "Re-authorize and pick the right channel/brand account.")
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": tags[:30], "categoryId": "25", "defaultLanguage": "en"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                   "embeddable": True, "license": "youtube"},
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = svc.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]
