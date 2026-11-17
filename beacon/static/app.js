const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let view = "pending";

async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body && typeof o.body !== "string" && !(o.body instanceof FormData)) {
    o.body = JSON.stringify(o.body); o.headers["content-type"] = "application/json";
  }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { const t = await r.text(); try { const j = JSON.parse(t); msg = j.detail || j.message || msg; } catch { if (t) msg = `${r.status} ${t.slice(0, 200)}`; } } catch {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}

function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms);
}

// ---------- status bar ----------
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const last = s.runs[0];
    const parts = [];
    if (s.fetching) parts.push("⏳ Fetching news…");
    if (s.next_fetch) parts.push(`Next fetch: ${new Date(s.next_fetch).toLocaleString()}`);
    if (last) parts.push(`Last run ${new Date(last.started).toLocaleString()}: ${last.ok ? "✅" : "❌"} ${esc(last.message)} · <a href="/api/last-reply" target="_blank" style="color:var(--accent)">last AI reply</a>`);
    if (s.queue) parts.push(`${s.queue} video(s) in queue`);
    if (!s.font) parts.push("⚠️ Arial Black font not found — see Settings");
    $("#statusbar").innerHTML = parts.join(" &nbsp;·&nbsp; ");
    $("#fetchBtn").disabled = s.fetching;
    return s;
  } catch (e) { $("#statusbar").textContent = "Can't reach server: " + e.message; }
}

// ---------- issue cards ----------
function lineHTML(c, bilingual) {
  return `<div class="line ${c.selected ? "on" : ""}">
    <input type="checkbox" class="sel" ${c.selected ? "checked" : ""} title="Put this line on the video">
    <div class="texts">
      <textarea class="en" rows="2" placeholder="English">${esc(c.text_en)}</textarea>
      <textarea class="es ${bilingual || c.text_es ? "" : "hidden"}" rows="2" placeholder="Español (optional)">${esc(c.text_es)}</textarea>
    </div>
    <div class="tools">
      <button class="pv" title="Preview card">👁</button>
      <button class="up" title="Move up">↑</button>
      <button class="rm danger" title="Remove line">✕</button>
    </div></div>`;
}

function issueHTML(it) {
  const editable = it.status === "pending";
  const srcs = (it.sources || []).map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">source ${i + 1}</a>`).join("");
  const video = it.video_path && ["rendered", "done", "error"].includes(it.status)
    ? `<video controls preload="none" src="/api/issues/${it.id}/video"></video>` : "";
  const ytLink = it.youtube_id ? `<a href="https://youtu.be/${esc(it.youtube_id)}" target="_blank" rel="noopener">YouTube ↗</a>` : "";
  let foot;
  if (editable) foot = `
      <button class="primary approve">✔ Approve &amp; publish</button>
      <button class="save">Save</button>
      <button class="add ghost">+ Add line</button>
      <span class="spacer"></span>
      <button class="decline danger">✕ Decline</button>`;
  else if (it.status === "declined") foot = `
      <button class="restore">↩ Back to review</button><span class="spacer"></span>
      <button class="delete danger">Delete</button>`;
  else foot = `
      <button class="restore">✎ Edit &amp; redo</button>
      <button class="retry" ${["queued", "rendering"].includes(it.status) ? "disabled" : ""}>↻ Re-run publish</button>
      ${it.video_path ? `<button class="toAnthias" title="Upload this video to Anthias only — doesn't re-post to YouTube">📺 Send to Anthias</button>` : ""}
      ${it.video_path ? `<a href="/api/issues/${it.id}/video" download><button>⬇ MP4</button></a>` : ""}
      ${ytLink}<span class="spacer"></span>
      <button class="delete danger">Delete</button>`;

  return `<article class="card" data-id="${it.id}">
    <div class="card-head">
      <input class="topic" value="${esc(it.topic)}" ${editable ? "" : "readonly"}>
      <span class="badge ${esc(it.status)}">${esc(it.status)}</span>
    </div>
    ${it.summary ? `<div class="summary">${esc(it.summary)}</div>` : ""}
    <div class="sources">${srcs}</div>
    <div class="lines">${it.cards.map(c => lineHTML(c, it.bilingual)).join("")}</div>
    <div class="row">
      <div><label>Length (seconds)</label><input type="number" class="duration" min="5" max="600" value="${it.duration}" ${editable ? "" : "readonly"}>
        <div class="hint rec"></div></div>
      <div><label>YouTube title</label><input class="yt_title" value="${esc(it.yt_title)}" ${editable ? "" : "readonly"}></div>
      <div><label>YouTube tags (comma separated)</label><input class="yt_tags" value="${esc((it.yt_tags || []).join(", "))}" ${editable ? "" : "readonly"}></div>
    </div>
    <div class="foot">
      ${editable ? `<label class="toggle"><input type="checkbox" class="bilingual" ${it.bilingual ? "checked" : ""}> English + Spanish</label>` : ""}
      ${foot}
    </div>
    ${video}
    ${it.log ? `<pre class="log">${esc(it.log)}</pre>` : ""}
  </article>`;
}

function collect(card) {
  return {
    topic: $(".topic", card).value,
    duration: +$(".duration", card).value || 30,
    yt_title: $(".yt_title", card).value,
    yt_tags: $(".yt_tags", card).value,
    bilingual: $(".bilingual", card)?.checked || false,
    cards: $$(".line", card).map(l => ({
      text_en: $(".en", l).value, text_es: $(".es", l).classList.contains("hidden") ? "" : $(".es", l).value,
      selected: $(".sel", l).checked,
    })),
  };
}

let recTimer;
function updateRecommend(card) {
  clearTimeout(recTimer);
  recTimer = setTimeout(async () => {
    const d = collect(card);
    const texts = [];
    d.cards.filter(c => c.selected && c.text_en.trim()).forEach(c => { texts.push(c.text_en); if (c.text_es.trim()) texts.push(c.text_es); });
    if (!texts.length) { $(".rec", card).textContent = "No lines selected"; return; }
    const r = await api("/api/card-count", { method: "POST", body: { texts } });
    const dur = $(".duration", card);
    if (!dur.dataset.touched) dur.value = r.recommended;
    $(".rec", card).textContent = `${r.cards} card${r.cards > 1 ? "s" : ""} · recommended ${r.recommended}s · ${(+dur.value / r.cards).toFixed(1)}s per card`;
  }, 350);
}

function wire(card) {
  const id = card.dataset.id;
  const editable = !!$(".approve", card);
  card.addEventListener("input", e => {
    if (e.target.classList.contains("duration")) e.target.dataset.touched = "1";
    if (editable) updateRecommend(card);
  });
  card.addEventListener("change", e => {
    if (e.target.classList.contains("sel")) e.target.closest(".line").classList.toggle("on", e.target.checked);
    if (e.target.classList.contains("bilingual")) $$(".es", card).forEach(t => t.classList.toggle("hidden", !e.target.checked && !t.value));
    if (editable) updateRecommend(card);
  });
  card.addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b) return;
    const line = b.closest(".line");
    try {
      if (b.classList.contains("pv")) {
        const ta = $(".es:not(.hidden)", line);
        const text = e.shiftKey && ta ? ta.value : $(".en", line).value;
        const r = await api("/api/preview", { method: "POST", body: { text } });
        $("#previewImg").src = URL.createObjectURL(await r.blob());
        const n = +r.headers.get("X-Card-Count");
        $("#previewNote").textContent = n > 1 ? `This line is long — it will be split across ${n} cards (first shown).` : "Shift-click 👁 to preview the Spanish line.";
        $("#modal").classList.remove("hidden");
      } else if (b.classList.contains("up") && line.previousElementSibling) {
        line.parentNode.insertBefore(line, line.previousElementSibling); updateRecommend(card);
      } else if (b.classList.contains("rm")) { line.remove(); updateRecommend(card); }
      else if (b.classList.contains("add")) {
        $(".lines", card).insertAdjacentHTML("beforeend", lineHTML({ text_en: "", text_es: "", selected: true }, $(".bilingual", card)?.checked));
        $(".lines .line:last-child .en", card).focus();
      } else if (b.classList.contains("save")) { await api(`/api/issues/${id}`, { method: "PUT", body: collect(card) }); toast("Saved"); }
      else if (b.classList.contains("approve")) {
        await api(`/api/issues/${id}/approve`, { method: "POST", body: collect(card) });
        toast("Approved — rendering and publishing in the background"); card.remove(); emptyCheck();
      } else if (b.classList.contains("decline")) { await api(`/api/issues/${id}/decline`, { method: "POST" }); card.remove(); emptyCheck(); }
      else if (b.classList.contains("restore")) { await api(`/api/issues/${id}/restore`, { method: "POST" }); card.remove(); toast("Moved back to Review"); emptyCheck(); }
      else if (b.classList.contains("toAnthias")) {
        b.disabled = true; toast("Sending to Anthias…", 60000);
        try { await api(`/api/issues/${id}/anthias`, { method: "POST" }); toast("Added to the Anthias playlist ✅"); }
        finally { load(); }
      }
      else if (b.classList.contains("retry")) {
        if (!confirm("Re-render and publish again? This re-uploads to YouTube too, which can create a duplicate. To fix only Anthias, use “Send to Anthias” instead.")) return;
        await api(`/api/issues/${id}/approve`, { method: "POST" }); load();
      } else if (b.classList.contains("delete")) {
        if (!confirm("Delete this topic and its video file? (Doesn't remove it from Anthias or YouTube.)")) return;
        await api(`/api/issues/${id}`, { method: "DELETE" }); card.remove(); emptyCheck();
      }
    } catch (err) { toast("⚠️ " + err.message, 6000); }
  });
  if (editable) updateRecommend(card);
}

function emptyCheck() {
  if (!$$("#main .card").length) $("#main").innerHTML = `<div class="empty">${view === "pending" ? "Nothing to review. Hit “Fetch news now” or wait for the morning run." : "Nothing here yet."}</div>`;
}

async function load() {
  if (view === "settings") return loadSettings();
  const items = await api(`/api/issues?view=${view}`);
  $("#main").innerHTML = items.map(issueHTML).join("");
  $$("#main .card").forEach(wire);
  emptyCheck();
}

// ---------- settings ----------
const F = (key, label, type = "text", extra = "") => {
  if (type === "textarea") return `<div class="${extra}"><label>${label}</label><textarea name="${key}" rows="5"></textarea></div>`;
  if (type === "check") return `<div class="${extra}"><label class="toggle"><input type="checkbox" name="${key}"> ${label}</label></div>`;
  if (type.startsWith("select:")) return `<div class="${extra}"><label>${label}</label><select name="${key}">${type.slice(7).split("|").map(o => `<option>${o}</option>`).join("")}</select></div>`;
  return `<div class="${extra}"><label>${label}</label><input name="${key}" type="${type}"></div>`;
};

async function loadSettings() {
  const s = await api("/api/settings");
  $("#main").innerHTML = `<form class="settings" id="sform">
    <section><h2>AI writer</h2><div class="grid">
      ${F("llm_provider", "Provider", "select:anthropic|openai")}
      <div><label>Model</label>
        <div style="display:flex;gap:6px"><select id="modelSelect"><option>Loading…</option></select>
          <button type="button" id="modelRefresh" title="Reload the model list">↻</button>
          <button type="button" id="modelForget" title="Remove this name from your saved list">✕</button></div>
        <input name="llm_model" id="modelCustom" class="hidden" placeholder="Type a model name, e.g. qwen3:14b" style="margin-top:6px">
        <div class="hint" id="modelHint"></div></div>
      ${F("llm_api_key", "API key", "password")}
      ${F("llm_base_url", "Base URL (OpenAI-compatible only — e.g. http://ollama:11434/v1)")}
      ${F("llm_web_search", "Let the AI search the web too (Anthropic only)", "check", "full")}
      <div class="full"><button type="button" id="testLlm">Test AI connection</button>
        <span class="hint">Save settings first. The first test can take a minute while a local model loads.</span></div>
      ${F("issues_per_day", "Topics per day", "number")}
      ${F("lines_per_issue", "One-liners per topic", "number")}
      ${F("focus_topics", "Topics to prioritize", "textarea", "full")}
      ${F("feeds", "News feeds (RSS/Atom, one per line, # to disable)", "textarea", "full")}
    </div></section>
    <section><h2>Schedule</h2><div class="grid">
      ${F("fetch_time", "Daily fetch time (24h)", "time")}
      ${F("timezone", "Time zone (IANA)")}
      ${F("keep_days", "Delete local MP4s after (days)", "number")}
    </div></section>
    <section><h2>Anthias</h2><div class="grid">
      ${F("anthias_enabled", "Send approved videos to Anthias", "check", "full")}
      ${F("anthias_url", "Anthias URL")}
      ${F("anthias_days", "Keep in playlist for (days)", "number")}
      ${F("anthias_position", "Where new videos go in the playlist", "select:end|start")}
      ${F("anthias_user", "Username (if auth enabled)")}
      ${F("anthias_password", "Password", "password")}
      ${F("anthias_verify_tls", "Verify HTTPS certificate", "check")}
      <div><button type="button" id="testAnthias">Test connection</button></div>
    </div></section>
    <section><h2>YouTube</h2><div class="grid">
      ${F("youtube_enabled", "Upload approved videos to YouTube (public)", "check", "full")}
      ${F("youtube_channel_id", "Channel ID to upload to (UC…) — uploads are refused if the authorized channel differs")}
      ${F("youtube_extra_tags", "Tags added to every video")}
      ${F("youtube_description", "Description footer", "textarea", "full")}
      <div class="full"><label>OAuth client_secret.json (Desktop app type)</label>
        <input type="file" id="ytClientFile" accept=".json,application/json">
        <div class="hint">Uploading is safest. Or paste the file's contents below and click Save settings.</div></div>
      ${F("youtube_client_config", "…or paste contents", "textarea", "full")}
      <div class="full"><div id="ytStatus" class="hint">Checking…</div>
        <div class="foot"><button type="button" id="ytAuth">1. Authorize with Google</button></div>
        <label>2. After signing in, your browser lands on a localhost page that fails to load. Paste that page's full URL here:</label>
        <div class="foot"><input id="ytPaste" placeholder="http://localhost:8765/?state=…&code=…"><button type="button" id="ytFinish">Connect</button></div>
      </div>
    </div></section>
    <section><h2>Video font</h2><div class="grid">
      ${F("font_path", "Font file path (blank = auto-detect Arial Black)")}
      <div><label>…or upload ariblk.ttf</label><input type="file" id="fontFile" accept=".ttf,.otf"></div>
    </div></section>
    <div class="foot"><button class="primary" type="submit">Save settings</button></div>
  </form>`;
  const form = $("#sform");
  for (const [k, v] of Object.entries(s)) {
    const el = form.elements[k]; if (!el) continue;
    if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
  }
  form.onsubmit = async e => {
    e.preventDefault();
    const out = {};
    [...form.elements].forEach(el => { if (!el.name) return; out[el.name] = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value; });
    try { await api("/api/settings", { method: "PUT", body: out }); toast("Settings saved"); refreshStatus(); loadModels(); }
    catch (err) { toast("⚠️ " + err.message, 6000); }
  };
  const OTHER = "__other__";
  async function loadModels() {
    const sel = $("#modelSelect"), custom = $("#modelCustom"), hint = $("#modelHint");
    const current = custom.value.trim();
    sel.disabled = true; hint.textContent = "Checking the AI server for models…";
    let r;
    try {
      r = await api("/api/models", { method: "POST", body: {
        llm_provider: form.elements.llm_provider.value, llm_base_url: form.elements.llm_base_url.value,
        llm_api_key: form.elements.llm_api_key.value } });
    } catch (err) { r = { installed: [], saved: [], error: err.message }; }
    const installed = r.installed, saved = r.saved.filter(m => !installed.includes(m));
    if (current && !installed.includes(current) && !saved.includes(current)) saved.unshift(current);
    const opt = m => `<option value="${esc(m)}">${esc(m)}</option>`;
    sel.innerHTML =
      (installed.length ? `<optgroup label="Installed on the AI server">${installed.map(opt).join("")}</optgroup>` : "") +
      (saved.length ? `<optgroup label="Saved names">${saved.map(opt).join("")}</optgroup>` : "") +
      `<option value="${OTHER}">Other — type a name…</option>`;
    sel.value = current || installed[0] || OTHER;
    if (!current && sel.value !== OTHER) custom.value = sel.value;
    custom.classList.toggle("hidden", sel.value !== OTHER);
    $("#modelForget").disabled = !saved.includes(sel.value);
    sel.disabled = false;
    hint.textContent = r.error || (installed.length
      ? `${installed.length} model(s) found on the server. Pick one and click Save settings.`
      : "No models found on the server.");
  }
  $("#modelSelect").onchange = e => {
    const v = e.target.value, custom = $("#modelCustom");
    custom.classList.toggle("hidden", v !== OTHER);
    if (v === OTHER) { custom.value = ""; custom.focus(); } else custom.value = v;
    $("#modelForget").disabled = !$(`#modelSelect optgroup[label="Saved names"] option[value="${CSS.escape(v)}"]`);
  };
  $("#modelRefresh").onclick = loadModels;
  $("#modelForget").onclick = async () => {
    const v = $("#modelSelect").value; if (!v || v === OTHER) return;
    await api(`/api/models/saved?name=${encodeURIComponent(v)}`, { method: "DELETE" });
    if ($("#modelCustom").value === v) $("#modelCustom").value = "";
    toast(`Forgot “${v}”`); loadModels();
  };
  form.elements.llm_provider.addEventListener("change", () => { $("#modelCustom").value = ""; loadModels(); });
  form.elements.llm_base_url.addEventListener("change", loadModels);
  loadModels();
  $("#testLlm").onclick = async e => {
    e.target.disabled = true; toast("Testing the AI… (local models can take a minute to load)", 60000);
    try { toast((await api("/api/test/llm", { method: "POST" })).message, 10000); }
    catch (err) { toast("⚠️ " + err.message, 15000); }
    finally { e.target.disabled = false; }
  };
  $("#testAnthias").onclick = async () => {
    try { toast((await api("/api/test/anthias", { method: "POST" })).message); } catch (err) { toast("⚠️ " + err.message, 6000); }
  };
  $("#ytAuth").onclick = async () => {
    try { const r = await api("/api/youtube/auth-url", { method: "POST" }); window.open(r.url, "_blank"); }
    catch (err) { toast("⚠️ " + err.message, 6000); }
  };
  $("#ytFinish").onclick = async () => {
    try { const r = await api("/api/youtube/finish", { method: "POST", body: { url: $("#ytPaste").value } }); toast(`Connected to ${r.title}`); ytStatus(); }
    catch (err) { toast("⚠️ " + err.message, 8000); }
  };
  $("#ytClientFile").onchange = async e => {
    const fd = new FormData(); fd.append("file", e.target.files[0]);
    try {
      const r = await api("/api/youtube/client", { method: "POST", body: fd });
      form.elements.youtube_client_config.value = "••••••••";
      toast(`Client file loaded (${r.client_id.split("-")[0]}…). Now click “Authorize with Google”.`, 6000);
    } catch (err) { toast("⚠️ " + err.message, 9000); }
  };
  $("#fontFile").onchange = async e => {
    const fd = new FormData(); fd.append("file", e.target.files[0]);
    try { const r = await api("/api/settings/font", { method: "POST", body: fd }); form.elements.font_path.value = r.font_path; toast("Font uploaded"); refreshStatus(); }
    catch (err) { toast("⚠️ " + err.message, 6000); }
  };
  ytStatus();
}

async function ytStatus() {
  const r = await api("/api/youtube/status");
  $("#ytStatus").textContent = r.connected ? `✅ Authorized as “${r.title}” (${r.id})` : `Not connected${r.error ? " — " + r.error : ""}`;
}

// ---------- top bar ----------
$$("nav button").forEach(b => b.onclick = () => {
  $$("nav button").forEach(x => x.classList.toggle("active", x === b));
  view = b.dataset.view; load();
});
$("#fetchBtn").onclick = async () => {
  await api("/api/fetch", { method: "POST" }); toast("Fetching today's news — new topics will show up here in a minute or two.");
  setTimeout(refreshStatus, 500);
};
$("#newBtn").onclick = async () => {
  const text = prompt("Your message for the sign:"); if (!text) return;
  await api("/api/issues", { method: "POST", body: { text, topic: text.slice(0, 60) } });
  $$("nav button")[0].click();
};
$("#closeModal").onclick = () => $("#modal").classList.add("hidden");
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); };

let wasFetching = false;
setInterval(async () => {
  const s = await refreshStatus();
  if (!s) return;
  if (wasFetching && !s.fetching && view === "pending") load();
  wasFetching = s.fetching;
  if (view === "published" && $$(".badge.queued, .badge.rendering").length) load();
}, 5000);
refreshStatus().then(s => { wasFetching = s?.fetching; });
load();
