<p align="center"><img src="docs/icon.png" width="128" alt="Lighthouse Beacon icon"></p>

# Lighthouse Beacon

Daily progressive headlines for **[The Shelby Lighthouse](https://shelbylight.house)** sign. Every
morning Beacon reads US national political news and has an AI write several witty, profanity-free
one-liners per issue. It puts them in a dark-mode web dashboard, where you edit, approve or decline
each one. Approved issues become silent 1080p title-card videos that go to your Anthias playlist and
your YouTube channel.

- 📰 **Daily news run.** RSS feeds (NPR, Guardian, MS NOW, Politico and more), optionally plus web search, every morning or on demand
- ✍️ **AI writer.** Claude, or a local model through Ollama, writes 5 one-liners per issue: one straight headline, the rest jokes. English and Spanish for issues like immigration
- 🗂️ **Review dashboard.** Every line is an editable text box. Pick lines, reorder them, preview the actual card, set the video length
- 🎬 **Title-card videos.** White Arial Black on black, 1920×1080 H.264 MP4, no sound, sized to read from 50 ft on a 50″ TV. Long lines split onto extra cards automatically
- 📺 **Anthias.** New videos join the playlist at the end without disturbing your order
- ▶️ **YouTube.** Public uploads with title, tags, description and sources
- 🏠 **Proxmox one-liner.** Creates and sets up its own LXC container

> Lighthouse Beacon is a community project. It isn't affiliated with or endorsed by Screenly/Anthias,
> YouTube/Google, Anthropic or Ollama.

## Install on Proxmox

In the Proxmox host shell (as root), run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/CaliMiller/lighthouse-beacon/main/install/proxmox-lxc.sh)"
```

It asks for a container ID, CPU, RAM, disk, storage, bridge and IP; press Enter for the defaults
(2 cores, 2 GB RAM, 8 GB disk, DHCP). It creates an unprivileged Debian 13 container, or Debian 12
on Proxmox versions before 9 (force one with `DEBIAN_VERSION=12`). It then installs ffmpeg, Python,
the Microsoft core fonts (for Arial Black) and Beacon, and prints the web address,
`http://<container-ip>:8080`.

**Plain VM or existing LXC** (Debian 12/13), as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/CaliMiller/lighthouse-beacon/main/install/install.sh)"
```

**Updating**, from the Proxmox host (replace `<CTID>` with the container's ID):

```bash
pct exec <CTID> -- bash -c 'cd /root/lighthouse-beacon-src && git pull && bash install/install.sh'
```

Your settings and data stay in `/var/lib/lighthouse-beacon`. The version number appears next to the
name at the top of the dashboard.

**Password.** Set `BEACON_PASSWORD=` in `/etc/default/lighthouse-beacon`, then run
`systemctl restart lighthouse-beacon`. Any username works.

**iPad / iPhone.** In Safari, use Share → **Add to Home Screen** to get a Beacon app icon.

## First-time setup (Settings tab)

1. **AI writer.** Choose a provider, then pick a model from the **Model** dropdown. It lists the
   models installed on your server, plus any names you've typed before. Click **Test AI connection**.
   - **Claude:** paste an API key from console.anthropic.com. "Search the web too" lets Claude
     look beyond your RSS feeds, at extra cost.
   - **Ollama or another OpenAI-compatible server:** choose `openai` and set the Base URL to
     `http://<ollama-host>:11434/v1`. Leave the API key blank. See [Using Ollama](#using-ollama).
2. **Feeds and topics.** These are prefilled with national politics feeds and a topic list based
   on shelbylight.house. Add one feed per line, and put `#` in front of a line to switch that feed
   off.
3. **Schedule.** The default is 06:00 Indianapolis time. **Fetch news now** works at any time.
4. **Anthias.** Enter the player address (for example `http://192.168.1.60`), plus the username
   and password if you turned on Anthias's login. Check **Send approved videos to Anthias**, then
   click **Test connection**. Videos stay in the playlist for 7 days by default.
5. **YouTube.** See below.

## YouTube setup (one time, about 15 minutes)

1. In <https://console.cloud.google.com>, create a project and enable **YouTube Data API v3**.
2. Under **Google Auth Platform → Audience** (older menus: **OAuth consent screen**), choose
   External, then click **Publish app** so the status is **In production**. In "Testing" mode your
   sign-in only works if you're listed as a tester, and it expires every 7 days.
3. Go to **Credentials → Create OAuth client ID** and choose **Desktop app**. The "Web
   application" type won't work. Download the JSON file.
4. In Beacon, go to Settings → YouTube and click **Upload client_secret.json**.
5. Click **Authorize with Google** and pick the Shelby Lighthouse channel (or its brand account).
   On the "Google hasn't verified this app" screen, click **Advanced → Go to (app name)**.
6. Google then sends you to a `localhost` page that fails to load. That's expected: copy that page's
   full address into Beacon and click **Connect**.
7. Put your channel ID (`UC…`) in **Channel ID**. Beacon refuses to upload if you authorized a
   different channel.

### ⚠️ Two YouTube limits Beacon can't get around

- **New API projects upload as private.** Google locks videos uploaded by a new, unaudited API
  project to *private*, even when Beacon asks for public. Submit the free **YouTube API Services
  audit / quota extension form** for your project. Until it's approved, switch videos to public in
  YouTube Studio.
- **The API can't turn comments off.** Set it channel-wide instead: YouTube Studio → Settings →
  **Upload defaults → Advanced settings → Comments → Disable comments**.

Each upload uses a large share of the default daily API quota. A handful of uploads per day is
fine; dozens per day are not.

## Using Ollama

Beacon works with a local model through Ollama's OpenAI-compatible API. For local models, Beacon
splits the job into small requests: one picks the topics, then one per topic writes the lines.
Small models handle that far more reliably than one huge request.

- **Hardware.** A GPU with 16 GB of memory runs 12–20B models well (for example `qwen3:14b`,
  `gemma3:12b` or `gpt-oss:20b`). CPU-only works, but expect weaker jokes and much slower runs.
- **Context length.** Set `OLLAMA_CONTEXT_LENGTH=16384` (or more) in Ollama's service settings.
  Beacon sends 10,000+ tokens of headlines, and Ollama's default silently cuts most of them off.
- **Network.** Set `OLLAMA_HOST=0.0.0.0:11434` so Beacon's container can reach Ollama.
- **Check the GPU.** `ollama ps` should show `100% GPU`. If it says CPU, the GPU driver isn't
  working inside that VM or container.

## Using it

- **Review** lists today's issues. Each one-liner is an editable text box.
  - ☑ picks which lines go on the video, ↑ moves a line up, and 👁 previews the actual card.
    Shift-click 👁 to preview the Spanish line.
  - **English + Spanish** adds a translation box under each line. Each Spanish card plays right
    after its English card.
  - **Length:** Beacon recommends 30 s for one card and up to 120 s for several. You can set any
    length, and each card gets an equal share.
  - **Approve & publish** renders the video, then sends it to Anthias and YouTube in the
    background. **Decline** hides the issue.
- **Published** shows each video's progress, log, player, MP4 download and YouTube link.
  - **📺 Send to Anthias** re-sends that video to Anthias only.
  - **↻ Re-run publish** renders again and re-uploads everywhere, YouTube included.
- **+ My own message** makes a card from your own text, without the AI.

### Readability at 50 feet

A 50″ TV shows about 44 px per inch. Beacon uses the largest Arial Black size that fits (up to
230 px) and never goes below 120 px. That keeps capital letters at least about 2″ tall, the usual
signage rule for reading at 50 ft. If a line can't fit at 120 px, Beacon splits it at a sentence or
clause break onto an extra card, and the preview warns you when that will happen.

## Troubleshooting

| Symptom | Where to look |
|---|---|
| A news run finds 0 issues | Open the **last AI reply** link in the status bar to see exactly what the AI returned |
| "The AI server hung up" | The model crashed or ran out of memory. On the Ollama host, check `journalctl -u ollama` and `ollama ps` |
| A video didn't reach Anthias | Read that video's log on the **Published** tab. It says whether Anthias was off in Settings, asked for a login, redirected to another address, or rejected the file |
| The Anthias playlist order changed | Beacon puts your order back after each upload; set where new videos go in Settings → Anthias. Other tools that add assets through the Anthias API hit [Anthias #3455](https://github.com/Screenly/Anthias/issues/3455) |
| YouTube sign-in errors | `redirect_uri_mismatch` means the client type is wrong (use Desktop app). `access_denied` means the app is still in Testing (publish it) |
| The page looks out of date after an update | Reload with Ctrl+Shift+R (⌘+Shift+R on a Mac) |

Logs: `journalctl -u lighthouse-beacon -f`. Data and videos: `/var/lib/lighthouse-beacon`. Local
MP4s are deleted after 30 days; copies in Anthias and on YouTube aren't affected.

## Files

```
beacon/app.py        web UI + API (FastAPI)          beacon/render.py   cards + ffmpeg
beacon/news.py       RSS fetching                    beacon/anthias.py  Anthias API v2 upload
beacon/writer.py     AI prompts + reply parsing      beacon/youtube.py  OAuth + upload
beacon/jobs.py       daily schedule + publish queue  beacon/db.py       SQLite storage
install/install.sh   Debian installer                install/proxmox-lxc.sh  Proxmox host helper
```

## License

MIT. See [LICENSE.md](LICENSE.md).

## Credits

Code and design developed in collaboration with Claude (Anthropic).
