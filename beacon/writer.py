"""Turn raw headlines into sign-ready issues and one-liners with an LLM."""
import json
import logging
import re

import httpx

log = logging.getLogger("beacon.writer")

SYSTEM = """You write copy for "The Shelby Lighthouse", a digital sign on the front of a private home in \
Shelby County, Indiana. The sign is "a shining beacon for democracy and the resistance": openly progressive, \
pro-democracy, anti-fascist political and social commentary, balanced with warm, unifying values like \
"Trans rights are human rights" and "Be excellent to each other."

Your job: read today's US national political news and pick the stories that matter most to progressives, \
Democrats and anti-fascists. For each one, write short title-card lines for the sign.

Rules for every line:
- One sentence, ideally under 15 words. Plain, everyday English a passing driver gets instantly.
- Take the progressive stance. Be creative: witty one-liners, wordplay, irony and jokes are encouraged.
- No profanity, no slurs. Innuendo and cheeky double meanings are fine.
- Punch up, not down: mock powerful people, policies and institutions, never vulnerable groups.
- Stay grounded in the facts in the provided stories. Never invent quotes, numbers or events. Jokes must read \
as opinion or satire, not as a factual claim.
- No calls for violence or harassment, and nothing about private individuals.
- No hashtags, emojis or URLs.

For issues that especially affect Spanish-speaking neighbors (immigration, ICE, deportations, etc.) set \
"bilingual": true and give a natural Spanish translation ("es") for every line. Otherwise "es" is "".

Respond with ONLY a JSON object, no prose, in exactly this shape:
{"issues": [{
  "topic": "short neutral topic label",
  "summary": "1-2 sentence factual summary of the news",
  "sources": ["url", ...],
  "bilingual": false,
  "lines": [{"en": "...", "es": ""}, ...],
  "yt_title": "YouTube title, under 90 characters",
  "yt_tags": ["tag", ...]
}]}"""


def build_prompt(headlines, focus, n_issues, n_lines, recent):
    lines = [f"- [{h['source']}] {h['title']} — {h['summary']} ({h['link']})" for h in headlines[:250]]
    recent_txt = "\n".join(f"- {t}" for t in recent[:60]) or "(none)"
    return f"""Today's headlines:
{chr(10).join(lines) if lines else "(no feed headlines — use web search to find today's US national political news)"}

Topics this sign cares about most: {focus}

Already covered recently (skip unless there is a major new development):
{recent_txt}

Pick up to {n_issues} distinct issues. Write {n_lines} different one-liners for each issue \
(variety: one straight headline, the rest witty). Return the JSON now."""


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)   # reasoning models
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find the largest parseable {...} or [...] block
    dec = json.JSONDecoder()
    best = None
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                obj, end = dec.raw_decode(text, i)
            except json.JSONDecodeError:
                continue
            if best is None or end - i > best[0]:
                best = (end - i, obj)
    if best is None:
        raise ValueError("model did not return JSON")
    return best[1]


def _first(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return default


def _issue_list(data):
    """Find the list of issues wherever the model put it."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        v = _first(data, "issues", "stories", "topics", "items", "results", "news", "headlines")
        if isinstance(v, list):
            return v
        if any(k in data for k in ("lines", "one_liners", "oneliners", "headlines", "topic")):
            return [data]                       # a single issue at the top level
        for v in data.values():                 # e.g. {"response": {"issues": [...]}}
            if isinstance(v, (dict, list)):
                found = _issue_list(v)
                if found:
                    return found
    return []


def _norm_line(l):
    if isinstance(l, str):
        return {"en": l, "es": ""}
    if isinstance(l, dict):
        en = _first(l, "en", "english", "text", "line", "headline", "one_liner", "oneliner", default="")
        es = _first(l, "es", "spanish", "espanol", "español", default="")
        return {"en": str(en), "es": str(es or "")}
    return {"en": "", "es": ""}


def _call_anthropic(s, prompt):
    body = {
        "model": s["llm_model"] or "claude-sonnet-5-5",
        "max_tokens": 8000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    if s.get("llm_web_search") == "1":
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]
    r = httpx.post(
        (s.get("llm_base_url") or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
        headers={"x-api-key": s["llm_api_key"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json=body, timeout=300)
    r.raise_for_status()
    blocks = r.json().get("content", [])
    # with web search on, the answer is the last text block(s)
    texts = [b["text"] for b in blocks if b.get("type") == "text"]
    return texts[-1] if texts else ""


SCHEMA = {
    "type": "object",
    "properties": {"issues": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "topic": {"type": "string"}, "summary": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
            "bilingual": {"type": "boolean"},
            "lines": {"type": "array", "items": {"type": "object", "properties": {
                "en": {"type": "string"}, "es": {"type": "string"}}, "required": ["en", "es"]}},
            "yt_title": {"type": "string"},
            "yt_tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["topic", "summary", "sources", "bilingual", "lines", "yt_title", "yt_tags"]}}},
    "required": ["issues"],
}


def _call_openai(s, prompt, system=SYSTEM, max_tokens=None, json_mode=False):
    base = (s.get("llm_base_url") or "https://api.openai.com/v1").rstrip("/")
    headers = {"content-type": "application/json"}
    if s.get("llm_api_key"):
        headers["authorization"] = f"Bearer {s['llm_api_key']}"
    body = {"model": s["llm_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.9}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "issues", "schema": SCHEMA}}
    last = None
    for attempt in range(4):  # local servers sometimes drop the first request while loading a model
        try:
            r = httpx.post(base + "/chat/completions", headers=headers, json=body,
                           timeout=httpx.Timeout(900, connect=15))
            if r.status_code in (400, 422) and "response_format" in body:
                # server doesn't support schemas: fall back to plain JSON mode, then to none
                body["response_format"] = {"type": "json_object"} if body["response_format"]["type"] != "json_object" else None
                if body["response_format"] is None:
                    body.pop("response_format")
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"AI server returned {r.status_code}: {r.text[:300]}")
            return r.json()["choices"][0]["message"]["content"] or ""
        except (httpx.RemoteProtocolError, httpx.ReadError) as e:
            last = e
            log.warning("AI server dropped the connection (attempt %d): %s", attempt + 1, e)
    raise RuntimeError(
        f"The AI server at {base} hung up without answering ({last}). This usually means the model "
        "crashed or ran out of memory — check the server's log (journalctl -u ollama).")


def test_connection(s):
    """Tiny round-trip so Settings can show whether the AI is reachable and working."""
    if s["llm_provider"] == "openai":
        out = _call_openai(s, 'Reply with exactly: {"ok": true}', system="You are a test endpoint.", max_tokens=20)
    else:
        r = httpx.post((s.get("llm_base_url") or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
                       headers={"x-api-key": s["llm_api_key"], "anthropic-version": "2023-06-01"},
                       json={"model": s["llm_model"], "max_tokens": 20,
                             "messages": [{"role": "user", "content": 'Reply with exactly: {"ok": true}'}]},
                       timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic returned {r.status_code}: {r.text[:300]}")
        out = "".join(b.get("text", "") for b in r.json().get("content", []))
    return out.strip()[:200]


BANNED = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|asshole\w*|bastard\w*|cunt\w*|dick(head)?s?|piss\w*|damn\w*|goddamn\w*)\b", re.I)


def clean_line(text):
    return BANNED.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text.strip())


def recommend_duration(n_cards):
    if n_cards <= 1:
        return 30
    return min(120, max(30, n_cards * 15))


def generate(settings, headlines, recent):
    prompt = build_prompt(headlines, settings["focus_topics"], int(settings["issues_per_day"] or 8),
                          int(settings["lines_per_issue"] or 5), recent)
    if settings["llm_provider"] == "openai":
        raw = _call_openai(settings, prompt, json_mode=True)
    else:
        raw = _call_anthropic(settings, prompt)
    save_raw(raw)
    data = _extract_json(raw)
    out = []
    for it in _issue_list(data):
        if not isinstance(it, dict):
            continue
        raw_lines = _first(it, "lines", "one_liners", "oneliners", "headlines", "cards", "slogans", default=[])
        if isinstance(raw_lines, str):
            raw_lines = [raw_lines]
        lines = [_norm_line(l) for l in raw_lines]
        lines = [{"en": clean_line(l["en"]), "es": clean_line(l["es"])} for l in lines if l["en"].strip()]
        if not lines:
            continue
        sources = _first(it, "sources", "source_urls", "urls", "links", default=[])
        tags = _first(it, "yt_tags", "tags", "youtube_tags", default=[])
        out.append({
            "topic": str(_first(it, "topic", "title", "issue", "name", default="Untitled"))[:200],
            "summary": str(_first(it, "summary", "description", default="")),
            "sources": ([sources] if isinstance(sources, str) else list(sources))[:6],
            "bilingual": bool(it.get("bilingual")) or any(l["es"] for l in lines),
            "lines": lines,
            "yt_title": str(_first(it, "yt_title", "youtube_title", default=lines[0]["en"]))[:100],
            "yt_tags": ([t.strip() for t in tags.split(",")] if isinstance(tags, str) else list(tags))[:15],
            "duration": 30,
        })
    return out


def raw_path():
    import os
    from . import db
    return os.path.join(db.DATA_DIR, "last_ai_reply.txt")


def save_raw(raw):
    try:
        with open(raw_path(), "w", encoding="utf-8") as f:
            f.write(raw or "")
    except OSError:
        pass
