#!/usr/bin/env bash
# PrimaLux Pulse — OpenClaw + host console for the SER10 Max (user systemd, not root).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${HOME}/.local/lib/clawbox"
UNIT_DIR="${HOME}/.config/systemd/user"
APP_DIR="${HOME}/.local/share/applications"
PORT="${CLAWBOX_PORT:-18791}"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not run as root. OpenClaw is a user service — install as primaluxadvisory." >&2
  exit 1
fi

mkdir -p "${PREFIX}/www/avatars" "${PREFIX}/roster" "${UNIT_DIR}" "${APP_DIR}" "${HOME}/.local/bin"
cp -a "${SCRIPT_DIR}/server.py" "${PREFIX}/server.py"
if [[ -f "${SCRIPT_DIR}/agent.py" ]]; then
  cp -a "${SCRIPT_DIR}/agent.py" "${PREFIX}/agent.py"
fi
if [[ -f "${SCRIPT_DIR}/library.py" ]]; then
  cp -a "${SCRIPT_DIR}/library.py" "${PREFIX}/library.py"
fi
if [[ -d "${SCRIPT_DIR}/knowledge" ]]; then
  mkdir -p "${PREFIX}/knowledge"
  cp -a "${SCRIPT_DIR}/knowledge/." "${PREFIX}/knowledge/"
fi
cp -a "${SCRIPT_DIR}/www/index.html" "${PREFIX}/www/index.html"
if [[ -d "${SCRIPT_DIR}/www/avatars" ]]; then
  cp -a "${SCRIPT_DIR}/www/avatars/." "${PREFIX}/www/avatars/"
fi
if [[ -f "${SCRIPT_DIR}/www/favicon.svg" ]]; then
  cp -a "${SCRIPT_DIR}/www/favicon.svg" "${PREFIX}/www/favicon.svg"
fi
cp -a "${SCRIPT_DIR}/roster/." "${PREFIX}/roster/"
chmod +x "${PREFIX}/server.py"

cat > "${HOME}/.local/bin/clawbox" <<EOF
#!/usr/bin/env bash
exec python3 "${PREFIX}/server.py" "\$@"
EOF
chmod +x "${HOME}/.local/bin/clawbox"

NODE_BIN="$(dirname "$(command -v openclaw || true)" || true)"
if [[ -z "${NODE_BIN}" ]]; then
  NODE_BIN="${HOME}/.nvm/versions/node/$(ls -1 "${HOME}/.nvm/versions/node" 2>/dev/null | tail -1)/bin"
fi

cat > "${UNIT_DIR}/clawbox.service" <<EOF
[Unit]
Description=PrimaLux Pulse
After=openclaw-gateway.service network-online.target
Wants=openclaw-gateway.service

[Service]
Type=simple
WorkingDirectory=${PREFIX}
Environment=HOME=${HOME}
Environment=CLAWBOX_PORT=${PORT}
Environment=CLAWBOX_BIND=127.0.0.1
Environment=CLAWBOX_WWW=${PREFIX}/www
Environment=CLAWBOX_ROSTER=${PREFIX}/roster
Environment=PULSE_STATE=${HOME}/.local/share/primalux-pulse
Environment=PATH=${NODE_BIN}:/usr/bin:/bin
ExecStart=/usr/bin/python3 ${PREFIX}/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat > "${APP_DIR}/clawbox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PrimaLux Pulse
Comment=SER10 host health and OpenClaw
Exec=xdg-open http://127.0.0.1:${PORT}/
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;System;
EOF

systemctl --user daemon-reload
systemctl --user enable --now clawbox.service
systemctl --user restart clawbox.service
sleep 1
systemctl --user --no-pager --full status clawbox.service || true

ensure_cora() {
  echo "Ensuring Cora (Navigator CRM · Grok · Library only)…"
  PATH="${NODE_BIN}:${PATH}" python3 "${PREFIX}/server.py" --ensure-cora || true
}
ensure_cora
echo "Pinning Vera to Grok 4.20 (other seats stay local Qwen)…"
PATH="${NODE_BIN}:${PATH}" python3 "${PREFIX}/server.py" --pin-vera || true
echo "Local Qwen context → 128k (native max 262k); disable compaction memory-flush…"
PATH="${NODE_BIN}:${PATH}" python3 "${PREFIX}/server.py" --pin-runtime || true
echo "Offloading local Qwen onto the Radeon 890M (sudo — llama-server.service is system-owned)…"
sudo python3 "${PREFIX}/agent.py" --tune-gpu || python3 "${PREFIX}/agent.py" --tune-gpu || true

STATE_DIR="${HOME}/.local/share/primalux-pulse"
mkdir -p "${STATE_DIR}"

publish_named() {
  local svc="$1" port="$2" outfile="$3" label="$4"
  local dns="" tailnet="" url=""
  dns="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys
try:
 d=json.load(sys.stdin); print((d.get("Self") or {}).get("DNSName","").rstrip("."))
except Exception:
 print("")' || true)"
  if [[ -n "${dns}" && "${dns}" == *.* ]]; then
    tailnet="${dns#*.}"
  fi
  if tailscale serve --bg --service="svc:${svc}" --https=443 "127.0.0.1:${port}" >/dev/null 2>&1 \
     || tailscale serve --bg --service="svc:${svc}" --https=443 "localhost:${port}" >/dev/null 2>&1; then
    if [[ -n "${tailnet}" ]]; then
      url="https://${svc}.${tailnet}"
    fi
  fi
  if [[ -n "${url}" ]]; then
    printf '%s\n' "${url}" > "${STATE_DIR}/${outfile}"
    echo "  ${label}:   ${url}/"
  else
    echo "  Named Service svc:${svc} not advertised (operator or tags)."
    echo "  sudo tailscale set --operator=\"${USER}\""
    echo "  sudo tailscale set --advertise-tags=tag:ser10"
    echo "  tailscale serve --bg --service=svc:${svc} --https=443 127.0.0.1:${port}"
    if [[ -f "${STATE_DIR}/${outfile}" ]]; then
      echo "  Last ${label} URL:  $(cat "${STATE_DIR}/${outfile}")"
    fi
  fi
}

publish_https() {
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale CLI not found. Pulse is loopback-only until you install it."
    return
  fi
  # Named Services only. Do not bind the machine MagicDNS — that resets TalkTrack/Pulse.
  publish_named "${PULSE_TS_SERVICE:-primalux-pulse}" "${PORT}" "public-url" "Pulse"
  publish_named "${OPENCLAW_TS_SERVICE:-prima}" "18789" "openclaw-url" "Control"
  echo "  (HTTPS via named services. Funnel is off. :${PORT} and :18789 are loopback only.)"
  echo "  ACL: autoApprovers.services.svc:prima = [tag:ser10]; grant members → svc:prima :443"
  echo "  If svc:openclaw was advertised: tailscale serve --service=svc:openclaw off"
}

echo
echo "PrimaLux Pulse is running."
echo "  Local:    http://127.0.0.1:${PORT}/   (this machine only)"
publish_https
echo
echo "Hard-refresh the browser (Ctrl+Shift+R)."
echo "Host is health. Agents is hire / retire / fire. Library is source ingest."
echo "OpenClaw Control UI (this machine): http://127.0.0.1:18789/"
echo "Do not use Pulse :${PORT}/openclaw — the Control UI WebSocket lives on :18789."
echo "Logs: journalctl --user -u clawbox -f"
