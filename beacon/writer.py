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
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("model did not return JSON")
    return json.loads(text[start:end + 1])


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


def _call_openai(s, prompt, system=SYSTEM, max_tokens=None):
    base = (s.get("llm_base_url") or "https://api.openai.com/v1").rstrip("/")
    headers = {"content-type": "application/json"}
    if s.get("llm_api_key"):
        headers["authorization"] = f"Bearer {s['llm_api_key']}"
    body = {"model": s["llm_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.9}
    if max_tokens:
        body["max_tokens"] = max_tokens
    last = None
    for attempt in range(2):  # local servers sometimes drop the first request while loading a model
        try:
            r = httpx.post(base + "/chat/completions", headers=headers, json=body,
                           timeout=httpx.Timeout(900, connect=15))
            if r.status_code >= 400:
                raise RuntimeError(f"AI server returned {r.status_code}: {r.text[:300]}")
            return r.json()["choices"][0]["message"]["content"]
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
    call = _call_openai if settings["llm_provider"] == "openai" else _call_anthropic
    raw = call(settings, prompt)
    data = _extract_json(raw)
    out = []
    for it in data.get("issues", []):
        lines = [{"en": clean_line(l.get("en", "")), "es": clean_line(l.get("es", "") or "")}
                 for l in it.get("lines", []) if l.get("en")]
        if not lines:
            continue
        out.append({
            "topic": it.get("topic", "Untitled")[:200],
            "summary": it.get("summary", ""),
            "sources": it.get("sources", [])[:6],
            "bilingual": bool(it.get("bilingual")),
            "lines": lines,
            "yt_title": (it.get("yt_title") or lines[0]["en"])[:100],
            "yt_tags": it.get("yt_tags", [])[:15],
            "duration": 30,
        })
    return out
