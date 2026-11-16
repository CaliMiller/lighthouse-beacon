# Lighthouse Beacon

Daily progressive headlines for **The Shelby Lighthouse** sign. Every morning it reads US national
political news, has an AI write several witty, profanity-free one-liners per issue (with Spanish
versions for issues like immigration), and puts them in a dark-mode web dashboard. You edit, approve
or decline. Approved issues become a silent 1920×1080 H.264 MP4 title card (white Arial Black on black),
which is pushed to your Anthias playlist and uploaded to YouTube as a public video.

## Install on Proxmox

In the Proxmox host shell (as root), run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/CaliMiller/lighthouse-beacon/main/install/proxmox-lxc.sh)"
```

It asks for CT ID, RAM, disk, storage, bridge and IP (Enter takes the defaults: 2 cores, 2 GB RAM,
8 GB disk, DHCP). It creates an unprivileged Debian 13 container (or Debian 12 on Proxmox versions before 9 — force one with `DEBIAN_VERSION=12`), installs
ffmpeg, Python, the Microsoft core fonts (for Arial Black) and the app, and prints the URL —
`http://<container-ip>:8080`.

**Plain VM or existing LXC** (Debian 12/13), as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/CaliMiller/lighthouse-beacon/main/install/install.sh)"
```

**Updating:** re-run the same `install.sh` one-liner inside the container (or
`pct exec <CTID> -- bash -c 'cd /root/lighthouse-beacon-src && git pull && bash install/install.sh'`
from the host). Your settings and data stay in `/var/lib/lighthouse-beacon`.

**Password:** set `BEACON_PASSWORD=` in `/etc/default/lighthouse-beacon`, then
`systemctl restart lighthouse-beacon`. Any username works.

## First-time setup (Settings tab)

1. **AI writer.** Paste an Anthropic API key (console.anthropic.com). The default model is
   `claude-sonnet-5-5`, and "search the web too" lets it look past the RSS feeds. To keep everything
   local, choose provider `openai` and point the Base URL at Ollama (`http://<host>:11434/v1`) or
   LM Studio. Smaller local models write noticeably weaker jokes.
2. **Feeds and topics.** These are prefilled with NPR, Guardian US, WaPo, Politico, The Hill,
   Mother Jones, Democracy Now and Google News searches. The topic list is based on
   shelbylight.house. Edit either one freely.
3. **Schedule.** The default is 06:00 Indianapolis time. You can also click **Fetch news now**
   at any time.
4. **Anthias.** Enter the player URL (for example `http://192.168.1.60`) and a login if you
   turned auth on. Click **Test connection**. Videos stay in the playlist for 7 days by default.
5. **YouTube.** See below.

## YouTube setup (one time, about 15 minutes)

1. In <https://console.cloud.google.com>, create a project and enable **YouTube Data API v3**.
2. Set up the **OAuth consent screen**: External, add yourself as a user, then set
   **Publishing status → In production**. In "Testing" mode your login expires every 7 days.
   You'll see an "unverified app" warning when you sign in. Click *Advanced → Continue*.
3. Go to **Credentials → Create OAuth client ID → Desktop app** and download the JSON.
4. Paste the JSON into Settings → YouTube → *client_secret.json* and **Save**.
5. Click **Authorize with Google** and choose the Shelby Lighthouse channel (or its brand
   account). Google then sends you to a `localhost` page that fails to load. That's expected.
   Copy that page's full URL into the box and click **Connect**.
6. Put your channel ID (`UC…`) in *Channel ID*. Uploads are refused if you authorize the wrong
   channel.

### ⚠️ Two YouTube limits the app can't get around

- **Unaudited API projects upload as private.** Google locks every video uploaded by a new,
  unaudited API project to *private*, even when the app asks for public. To get public uploads,
  submit the free **YouTube API Services audit/quota extension form** for your project. Until it's
  approved, the app's videos land as private and you'd flip them to public in YouTube Studio.
- **The API can't turn comments off.** Set it channel-wide instead: YouTube Studio → Settings →
  **Upload defaults → Advanced settings → Comments → Disable comments**. That default should apply
  to these uploads too. Check it on the first upload.

Each upload uses a large share of the default daily API quota, so a handful of uploads per day is
fine. Dozens per day are not.

## Using it

- **Review** lists today's issues. Each one-liner is an editable text box.
  - ☑ picks which lines go on the video. Use ↑ to reorder and 👁 to preview the actual card
    (Shift-click 👁 previews the Spanish line).
  - Toggle **English + Spanish** to add or edit translations. Each Spanish card plays right after
    its English card.
  - **Length:** the app recommends 30 s for one card and up to 120 s for several. You can set any
    length. Each card gets an equal share.
  - **Approve & publish** renders the video, then sends it to Anthias and YouTube in the
    background. **Decline** hides the issue.
- **Published** shows progress, a log, the video player, an MP4 download, the YouTube link and
  **Re-run publish**.
- **+ My own message** makes a card from your own text, without the AI.

### Readability at 50 feet

A 50″ TV shows about 44 px per inch. The renderer picks the largest Arial Black size that fits
(up to 230 px) and never goes below 120 px. That keeps capital letters at least about 2″ tall,
which is the usual signage rule for reading at 50 ft. If a line can't fit at 120 px, the app
splits it at a sentence or clause break onto extra cards. The preview tells you when that will
happen.

## Files

```
beacon/app.py        web UI + API (FastAPI)       beacon/render.py   cards + ffmpeg
beacon/news.py       RSS fetching                 beacon/anthias.py  Anthias API v2 upload
beacon/writer.py     AI prompt + parsing          beacon/youtube.py  OAuth + upload
beacon/jobs.py       daily schedule + publish queue
install/install.sh   Debian installer             install/proxmox-lxc.sh  PVE host helper
```

Logs: `journalctl -u lighthouse-beacon -f`. Data and videos: `/var/lib/lighthouse-beacon`. Local
MP4s are deleted after 30 days. Copies in Anthias and on YouTube are not affected.
