#!/usr/bin/env bash
# Clawbox — OpenClaw GUI for the SER10 Max (user systemd, not root).
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

mkdir -p "${PREFIX}/www" "${PREFIX}/roster" "${UNIT_DIR}" "${APP_DIR}" "${HOME}/.local/bin"
cp -a "${SCRIPT_DIR}/server.py" "${PREFIX}/server.py"
cp -a "${SCRIPT_DIR}/www/index.html" "${PREFIX}/www/index.html"
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
Description=Clawbox OpenClaw console
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
Name=Clawbox
Comment=Manage OpenClaw agents
Exec=xdg-open http://127.0.0.1:${PORT}/
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;System;
EOF

systemctl --user daemon-reload
systemctl --user enable --now clawbox.service
sleep 1
systemctl --user --no-pager --full status clawbox.service || true

echo
echo "Clawbox is running."
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
echo "Open Roster in the UI and type RESET to replace Ken/Aria/Dex/… with Vera + five."
echo "Or: python3 ${PREFIX}/server.py  is already the service."
echo "Logs: journalctl --user -u clawbox -f"
