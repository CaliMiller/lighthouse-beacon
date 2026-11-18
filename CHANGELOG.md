# Changelog

## Unreleased

### Added
- Bulk actions. A checkbox on every topic, plus **Select all** / **Select none** bars at the top
  and bottom of the Review, Declined and Published lists.
  - Review: decline selected topics.
  - Declined: move selected topics back to Review, or delete them.
  - Published: delete, republish to Anthias only, or republish to YouTube only. If a video's MP4
    was cleaned up after 30 days, it's rendered again first.

## v1.0.1 — 2026-11-17

### Changed
- Says "topic" instead of "issue" everywhere you see it: the dashboard, settings, status line,
  logs, video file names, AI prompts, README and changelog. "Issues" sounded like problems with
  the app. Internal names are unchanged, so existing installs and data keep working.

## v1.0.0 — 2026-11-17

First release.

### Features
- Daily news run from RSS feeds at a set time, plus **Fetch news now** at any time.
- AI writer: Claude, with optional web search, or any OpenAI-compatible server such as Ollama.
  Writes several one-liners per topic in plain, profanity-free English, with Spanish versions for
  topics like immigration.
- Dark-mode review dashboard: editable lines, line picking and reordering, card preview,
  recommended video length (30 s for one card, up to 120 s for several), approve or decline.
- Title-card renderer: white Arial Black on black, 1920×1080 H.264 MP4, no audio, auto-sized for
  reading from 50 ft. Long lines split onto extra cards.
- Anthias: uploads approved videos and keeps the existing playlist order, with new videos at the
  end or the start.
- YouTube: public uploads with title, tags, description and sources, with a check that the
  authorized channel is the right one.
- Proxmox helper script that creates a Debian LXC and installs Beacon from GitHub, plus an
  installer for any Debian 12/13 VM or container.

### Settings and tools
- A model dropdown that lists the models installed on Ollama or available from Claude, and
  remembers names you type.
- **Test AI connection** and **Test connection** (Anthias) buttons.
- A **last AI reply** link for diagnosing runs that produce no topics.
- **Send to Anthias** on each published video, to retry Anthias without re-uploading to YouTube.
- An upload button for YouTube's `client_secret.json`, with clear errors for the wrong file or
  client type.
- App icons for browsers and iPad/iPhone home screens, plus a web app manifest.

### Fixes made during testing
- Falls back to Debian 12 on Proxmox versions that reject Debian 13 containers.
- Works around Anthias resetting the playlist order when assets are added
  ([Anthias #3455](https://github.com/Screenly/Anthias/issues/3455)).
- Sends `duration: 0` for videos, as Anthias requires.
- Reads local-model replies that don't exactly match the requested JSON format.
- Makes browsers load the new page code after updates.
