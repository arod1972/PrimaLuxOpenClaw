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
Environment=CLAWBOX_BIND=0.0.0.0
Environment=CLAWBOX_WWW=${PREFIX}/www
Environment=CLAWBOX_ROSTER=${PREFIX}/roster
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

echo
echo "PrimaLux Pulse is running."
echo "  Local:    http://127.0.0.1:${PORT}/"
if command -v tailscale >/dev/null 2>&1; then
  dns="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys
try:
 d=json.load(sys.stdin); print((d.get("Self") or {}).get("DNSName","").rstrip("."))
except Exception:
 print("")' || true)"
  if [[ -n "${dns}" ]]; then
    echo "  Tailnet:  http://${dns}:${PORT}/"
  fi
fi
echo
echo "Hard-refresh the browser (Ctrl+Shift+R)."
echo "Host is health. Agents is hire / retire / fire. Library is source ingest."
echo "Raw OpenClaw Control UI: http://127.0.0.1:${PORT}/openclaw/"
echo "Logs: journalctl --user -u clawbox -f"
