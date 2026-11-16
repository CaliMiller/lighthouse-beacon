#!/usr/bin/env bash
# Create a Debian LXC on a Proxmox VE host and install Lighthouse Beacon in it.
# Run on the Proxmox host shell as root:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/CaliMiller/lighthouse-beacon/main/install/proxmox-lxc.sh)"
# Override any default with env vars, e.g.:
#   CTID=150 STORAGE=local-zfs IP=192.168.1.50/24,gw=192.168.1.1 bash -c "$(curl -fsSL ...)"
# Force a Debian release with DEBIAN_VERSION=12 (default: try 13, fall back to 12).
# Developing locally? Run it from a checkout with LOCAL=1 to install that folder instead of GitHub.
set -euo pipefail

msg() { echo -e "\e[1;36m==>\e[0m $*"; }
die() { echo -e "\e[1;31m!!\e[0m $*"; exit 1; }
command -v pct >/dev/null || die "This must run on a Proxmox VE host."

REPO_URL="${REPO_URL:-https://github.com/CaliMiller/lighthouse-beacon.git}"
BRANCH="${BRANCH:-main}"
SRC=""
if [[ -n "${LOCAL:-}" && -f "${BASH_SOURCE[0]:-}" ]]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  [[ -d "$SRC/beacon" ]] || die "LOCAL=1 but no beacon/ folder next to this script."
fi
CTID="${CTID:-$(pvesh get /cluster/nextid)}"
HOSTNAME="${HOSTNAME_CT:-lighthouse-beacon}"
CORES="${CORES:-2}"
MEMORY="${MEMORY:-2048}"
DISK="${DISK:-8}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
PORT="${BEACON_PORT:-8080}"

if [[ -t 0 && -z "${NONINTERACTIVE:-}" ]]; then
  ask() { local v; read -rp "$1 [$2]: " v; echo "${v:-$2}"; }
  echo "Lighthouse Beacon — Proxmox LXC setup (Enter accepts defaults)"
  CTID=$(ask "Container ID" "$CTID")
  HOSTNAME=$(ask "Hostname" "$HOSTNAME")
  CORES=$(ask "CPU cores" "$CORES")
  MEMORY=$(ask "RAM (MB)" "$MEMORY")
  DISK=$(ask "Disk (GB)" "$DISK")
  STORAGE=$(ask "Root disk storage" "$STORAGE")
  BRIDGE=$(ask "Network bridge" "$BRIDGE")
  IP=$(ask "IPv4 (dhcp or 192.168.1.50/24,gw=192.168.1.1)" "$IP")
  PORT=$(ask "Web UI port" "$PORT")
fi
pct status "$CTID" >/dev/null 2>&1 && die "CT $CTID already exists."

# Debian version: DEBIAN_VERSION=12 or 13 forces one. Otherwise try 13 and fall back to 12,
# because older Proxmox releases (before PVE 9) refuse Debian 13 containers.
pveam update >/dev/null || true
template_for() {
  pveam available --section system | awk '{print $2}' | grep -E "^debian-$1-standard" | sort -V | tail -1 || true
}
ensure_template() {
  pveam list "$TEMPLATE_STORAGE" | grep -q "$1" || { msg "Downloading $1"; pveam download "$TEMPLATE_STORAGE" "$1"; }
}
NET="name=eth0,bridge=$BRIDGE,ip=$IP"
create_ct() {
  pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$1" \
    --hostname "$HOSTNAME" --cores "$CORES" --memory "$MEMORY" --swap 512 \
    --rootfs "$STORAGE:$DISK" --net0 "$NET" --unprivileged 1 --features nesting=1 \
    --onboot 1 --ostype debian --description "Lighthouse Beacon — progressive headlines for The Shelby Lighthouse"
}

VERSIONS="${DEBIAN_VERSION:-13 12}"
CREATED=""
for v in $VERSIONS; do
  TEMPLATE=$(template_for "$v")
  [[ -n "$TEMPLATE" ]] || { msg "No Debian $v template available, skipping"; continue; }
  ensure_template "$TEMPLATE"
  msg "Creating CT $CTID ($HOSTNAME) from $TEMPLATE"
  if out=$(create_ct "$TEMPLATE" 2>&1); then
    echo "$out"; CREATED=1; break
  fi
  echo "$out"
  if grep -qi "unsupported debian version" <<<"$out"; then
    msg "This Proxmox version doesn't support Debian $v containers — trying an older Debian."
    pct status "$CTID" >/dev/null 2>&1 && pct destroy "$CTID" --purge >/dev/null 2>&1 || true
    continue
  fi
  die "Container creation failed (see above)."
done
[[ -n "$CREATED" ]] || die "Couldn't create the container with Debian ${VERSIONS// / or }."
pct start "$CTID"

msg "Waiting for network"
for _ in $(seq 1 30); do
  pct exec "$CTID" -- bash -c 'getent hosts deb.debian.org >/dev/null' && break; sleep 2
done

if [[ -n "$SRC" ]]; then
  msg "Copying app into the container"
  tmp=$(mktemp); tar -C "$SRC" -czf "$tmp" beacon install requirements.txt $( [[ -f "$SRC/README.md" ]] && echo README.md )
  pct exec "$CTID" -- mkdir -p /root/lighthouse-beacon-src
  pct push "$CTID" "$tmp" /root/lighthouse-beacon-src.tgz; rm -f "$tmp"
  pct exec "$CTID" -- tar -xzf /root/lighthouse-beacon-src.tgz -C /root/lighthouse-beacon-src
  pct exec "$CTID" -- env BEACON_PORT="$PORT" bash /root/lighthouse-beacon-src/install/install.sh
else
  msg "Downloading Lighthouse Beacon from $REPO_URL ($BRANCH)"
  pct exec "$CTID" -- bash -c "apt-get update -q && apt-get install -y -q git curl ca-certificates"
  pct exec "$CTID" -- git clone --depth 1 --branch "$BRANCH" "$REPO_URL" /root/lighthouse-beacon-src
  pct exec "$CTID" -- env BEACON_PORT="$PORT" bash /root/lighthouse-beacon-src/install/install.sh
fi

CT_IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
msg "All set. Lighthouse Beacon is running in CT $CTID: http://${CT_IP}:${PORT}"
msg "To update later, run on this host: pct exec $CTID -- bash -c 'cd /root/lighthouse-beacon-src && git pull && bash install/install.sh'"
