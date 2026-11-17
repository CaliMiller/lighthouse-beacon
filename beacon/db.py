"""SQLite storage for issues, cards and settings."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

DATA_DIR = os.environ.get("BEACON_DATA", "/var/lib/lighthouse-beacon")
DB_PATH = os.path.join(DATA_DIR, "beacon.db")
VIDEO_DIR = os.path.join(DATA_DIR, "videos")

_lock = threading.RLock()

DEFAULT_FEEDS = "\n".join([
    "https://feeds.npr.org/1014/rss.xml",
    "https://www.theguardian.com/us-news/us-politics/rss",
    "https://feeds.washingtonpost.com/rss/politics",
    "https://rss.politico.com/politics-news.xml",
    "https://thehill.com/homenews/feed/",
    "https://www.motherjones.com/politics/feed/",
    "https://www.democracynow.org/democracynow.rss",
    "https://news.google.com/rss/search?q=Democrats+OR+progressive+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Trump+administration+when:1d&hl=en-US&gl=US&ceid=US:en",
])

DEFAULT_FOCUS = (
    "Immigration and ICE; LGBTQ+ and trans rights; racial justice; healthcare and "
    "reproductive rights; climate and science/vaccines; democracy, voting rights and "
    "opposition to the Trump administration and authoritarianism; workers and the "
    "economy; religious tolerance, diversity and peace."
)

DEFAULT_SETTINGS = {
    "llm_provider": "anthropic",          # anthropic | openai
    "llm_api_key": "",
    "llm_model": "claude-sonnet-5-5",
    "llm_base_url": "",                   # only for openai-compatible (Ollama, LM Studio, OpenAI)
    "llm_web_search": "1",                # anthropic only: let the model search the web too
    "llm_saved_models": "",               # newline list of model names used before (for the dropdown)
    "feeds": DEFAULT_FEEDS,
    "focus_topics": DEFAULT_FOCUS,
    "issues_per_day": "8",
    "lines_per_issue": "5",
    "fetch_time": "06:00",
    "timezone": "America/Indiana/Indianapolis",
    "anthias_enabled": "0",
    "anthias_url": "http://anthias.local",
    "anthias_user": "",
    "anthias_password": "",
    "anthias_days": "7",                  # how long the asset stays scheduled
    "anthias_position": "end",            # end | start — where new videos go in the playlist
    "anthias_verify_tls": "0",
    "youtube_enabled": "0",
    "youtube_channel_id": "",
    "youtube_client_config": "",          # contents of client_secret.json
    "youtube_token": "",                  # OAuth token JSON (written by the app)
    "youtube_pending_verifier": "",
    "youtube_extra_tags": "progressive,politics,news,Shelby Lighthouse",
    "youtube_description": "From The Shelby Lighthouse — a shining beacon for democracy. https://shelbylight.house",
    "font_path": "",                      # override; otherwise auto-detect Arial Black
    "keep_days": "30",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init():
    os.makedirs(VIDEO_DIR, exist_ok=True)
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT, summary TEXT, sources TEXT DEFAULT '[]',
            bilingual INTEGER DEFAULT 0,
            yt_title TEXT DEFAULT '', yt_tags TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',   -- pending|declined|queued|rendering|rendered|done|error
            duration INTEGER DEFAULT 30,
            video_path TEXT DEFAULT '', anthias_id TEXT DEFAULT '', youtube_id TEXT DEFAULT '',
            log TEXT DEFAULT '', created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE,
            position INTEGER DEFAULT 0,
            text_en TEXT DEFAULT '', text_es TEXT DEFAULT '',
            selected INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT,
            ok INTEGER, message TEXT);
        """)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()


def get_settings():
    with conn() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings")}


def get_setting(key):
    return get_settings().get(key, DEFAULT_SETTINGS.get(key, ""))


def set_settings(values: dict):
    with conn() as c:
        for k, v in values.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (k, "" if v is None else str(v)))


def issue_dict(row, cards):
    d = dict(row)
    d["sources"] = json.loads(d["sources"] or "[]")
    d["yt_tags"] = json.loads(d["yt_tags"] or "[]")
    d["cards"] = [dict(x) for x in cards]
    return d


def get_issue(issue_id):
    with conn() as c:
        row = c.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if not row:
            return None
        cards = c.execute("SELECT * FROM cards WHERE issue_id=? ORDER BY position,id", (issue_id,)).fetchall()
        return issue_dict(row, cards)


def list_issues(statuses):
    q = ",".join("?" * len(statuses))
    with conn() as c:
        rows = c.execute(f"SELECT id FROM issues WHERE status IN ({q}) ORDER BY id DESC LIMIT 300", statuses).fetchall()
    return [get_issue(r["id"]) for r in rows]


def recent_topics(days=10):
    with conn() as c:
        rows = c.execute("SELECT topic FROM issues WHERE created >= datetime('now', ?) ORDER BY id DESC",
                         (f"-{int(days)} days",)).fetchall()
    return [r["topic"] for r in rows]


def add_issue(issue: dict):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO issues(topic,summary,sources,bilingual,yt_title,yt_tags,duration,created,updated) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (issue["topic"], issue.get("summary", ""), json.dumps(issue.get("sources", [])),
             1 if issue.get("bilingual") else 0, issue.get("yt_title", ""),
             json.dumps(issue.get("yt_tags", [])), int(issue.get("duration", 30)), now(), now()))
        iid = cur.lastrowid
        for i, line in enumerate(issue.get("lines", [])):
            c.execute("INSERT INTO cards(issue_id,position,text_en,text_es,selected) VALUES(?,?,?,?,?)",
                      (iid, i, line.get("en", ""), line.get("es", "") or "", 1 if i == 0 else 0))
        return iid


def update_issue(issue_id, **fields):
    if not fields:
        return
    fields["updated"] = now()
    for k in ("sources", "yt_tags"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    cols = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE issues SET {cols} WHERE id=?", (*fields.values(), issue_id))


def append_log(issue_id, msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    with conn() as c:
        c.execute("UPDATE issues SET log = log || ? WHERE id=?", (f"[{stamp}] {msg}\n", issue_id))


def replace_cards(issue_id, cards):
    with conn() as c:
        c.execute("DELETE FROM cards WHERE issue_id=?", (issue_id,))
        for i, cd in enumerate(cards):
            c.execute("INSERT INTO cards(issue_id,position,text_en,text_es,selected) VALUES(?,?,?,?,?)",
                      (issue_id, i, cd.get("text_en", "").strip(), (cd.get("text_es") or "").strip(),
                       1 if cd.get("selected") else 0))


def log_run(started, ok, message):
    with conn() as c:
        c.execute("INSERT INTO runs(started,finished,ok,message) VALUES(?,?,?,?)", (started, now(), 1 if ok else 0, message))


def last_runs(n=5):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,))]
