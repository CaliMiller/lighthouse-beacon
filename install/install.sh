#!/usr/bin/env bash
# Lighthouse Beacon installer for Debian 12/13 (LXC or VM). Run as root.
#   bash install/install.sh            # install or update from this source tree
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/CaliMiller/lighthouse-beacon/main/install/install.sh)"
#                                      # install straight from GitHub
set -euo pipefail

APP=lighthouse-beacon
APP_DIR=/opt/$APP
DATA_DIR=/var/lib/$APP
PORT="${BEACON_PORT:-8080}"
REPO_URL="${REPO_URL:-https://github.com/CaliMiller/lighthouse-beacon.git}"
BRANCH="${BRANCH:-main}"
SRC=""
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  [[ -d "$d/beacon" ]] && SRC="$d"
fi

msg() { echo -e "\e[1;36m==>\e[0m $*"; }
[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }
command -v apt-get >/dev/null || { echo "Debian/Ubuntu only"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

msg "Enabling the 'contrib' repo (needed for Microsoft core fonts / Arial Black)"
if [[ -f /etc/apt/sources.list.d/debian.sources ]]; then
  sed -i -E '/^Components:/{/contrib/!s/$/ contrib/}' /etc/apt/sources.list.d/debian.sources
fi
if [[ -f /etc/apt/sources.list ]]; then
  sed -i -E '/^deb .*debian/{/contrib/!s/ main/ main contrib/}' /etc/apt/sources.list
fi
echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections

msg "Installing packages"
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip ffmpeg fontconfig ca-certificates curl git
apt-get install -y -q ttf-mscorefonts-installer || echo "!! Core fonts failed to install — upload ariblk.ttf in Settings later."
fc-cache -f >/dev/null 2>&1 || true

msg "Installing app to $APP_DIR"
id -u beacon >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin beacon
mkdir -p "$APP_DIR" "$DATA_DIR"
if [[ -n "$SRC" ]]; then
  cp -a "$SRC/beacon" "$SRC/requirements.txt" "$SRC/install" "$APP_DIR/"
  [[ -f "$SRC/README.md" ]] && cp "$SRC/README.md" "$APP_DIR/"
else
  tmp=$(mktemp -d); git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$tmp/src"
  cp -a "$tmp/src/beacon" "$tmp/src/requirements.txt" "$tmp/src/install" "$APP_DIR/"; rm -rf "$tmp"
fi
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
chown -R beacon:beacon "$DATA_DIR"

if [[ ! -f /etc/default/$APP ]]; then
  cat > /etc/default/$APP <<EOF
# Lighthouse Beacon settings (restart after editing: systemctl restart $APP)
BEACON_PORT=$PORT
BEACON_DATA=$DATA_DIR
# Set a password to require login on the web UI (any username works):
BEACON_PASSWORD=
EOF
fi

cat > /etc/systemd/system/$APP.service <<EOF
[Unit]
Description=Lighthouse Beacon
After=network-online.target
Wants=network-online.target

[Service]
User=beacon
EnvironmentFile=/etc/default/$APP
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -m beacon.app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now $APP
systemctl restart $APP

IP=$(hostname -I | awk '{print $1}')
VER=$(grep -oP '__version__ = "\K[^"]+' "$APP_DIR/beacon/__init__.py" || echo "?")
msg "Lighthouse Beacon v${VER} is running. Open http://${IP}:${PORT} and fill in Settings."
fc-list | grep -qi "arial black" && msg "Arial Black: installed" || echo "!! Arial Black not found — upload ariblk.ttf in Settings → Video font."
