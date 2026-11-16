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
        msg = f"{len(heads)} headlines → {len(issues)} issues"
        db.log_run(started, True, msg)
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
    db.update_issue(issue_id, status="queued", log="")
    _q.put(issue_id)


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:50] or "issue"


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
        try:
            aid = anthias.upload(s, out, f"Beacon: {issue['topic']}", issue["duration"])
            db.update_issue(issue_id, anthias_id=aid)
            db.append_log(issue_id, f"Added to Anthias (asset {aid})")
        except Exception as e:
            problems.append("Anthias")
            db.append_log(issue_id, f"Anthias upload failed: {e}")

    if s.get("youtube_enabled") == "1":
        try:
            tags = list(dict.fromkeys(issue["yt_tags"] + [t.strip() for t in s.get("youtube_extra_tags", "").split(",") if t.strip()]))
            desc = "\n\n".join(x for x in [
                " / ".join(texts),
                issue.get("summary", ""),
                "Sources:\n" + "\n".join(issue["sources"]) if issue["sources"] else "",
                s.get("youtube_description", ""),
            ] if x)
            vid = youtube.upload(s, out, issue["yt_title"] or texts[0], desc, tags)
            db.update_issue(issue_id, youtube_id=vid)
            db.append_log(issue_id, f"Uploaded to YouTube: https://youtu.be/{vid}")
        except Exception as e:
            problems.append("YouTube")
            db.append_log(issue_id, f"YouTube upload failed: {e}")

    db.update_issue(issue_id, status="error" if problems else "done")


def _worker():
    while True:
        iid = _q.get()
        try:
            process(iid)
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
