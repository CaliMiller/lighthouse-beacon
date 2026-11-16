"""Pull today's political headlines from RSS feeds."""
import calendar
import logging
import re
import time

import feedparser
import httpx

log = logging.getLogger("beacon.news")
UA = "Mozilla/5.0 (X11; Linux x86_64) LighthouseBeacon/1.0"


def fetch_headlines(feed_urls, max_age_hours=36, per_feed=25):
    cutoff = time.time() - max_age_hours * 3600
    items, seen = [], set()
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for url in [u.strip() for u in feed_urls if u.strip() and not u.strip().startswith("#")]:
            try:
                r = client.get(url)
                r.raise_for_status()
                feed = feedparser.parse(r.content)
            except Exception as e:  # one dead feed shouldn't kill the run
                log.warning("feed failed %s: %s", url, e)
                continue
            source = feed.feed.get("title", url)
            for e in feed.entries[:per_feed]:
                ts = e.get("published_parsed") or e.get("updated_parsed")
                if ts and calendar.timegm(ts) < cutoff:
                    continue
                title = (e.get("title") or "").strip()
                key = title.lower()[:80]
                if not title or key in seen:
                    continue
                seen.add(key)
                summary = (e.get("summary") or "")
                # strip tags crudely; the LLM only needs the gist
                summary = re.sub(r"<[^>]+>", " ", summary)
                summary = re.sub(r"\s+", " ", summary).strip()[:300]
                items.append({"title": title, "summary": summary, "link": e.get("link", ""), "source": source})
    log.info("fetched %d headlines", len(items))
    return items
