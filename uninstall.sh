#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now clawbox.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/clawbox.service"
rm -f "${HOME}/.local/bin/clawbox"
rm -f "${HOME}/.local/share/applications/clawbox.desktop"
rm -rf "${HOME}/.local/lib/clawbox"
if command -v tailscale >/dev/null 2>&1; then
  tailscale serve --https=443 localhost:18791 off >/dev/null 2>&1 || true
  tailscale serve --https=8443 localhost:18791 off >/dev/null 2>&1 || true
fi
systemctl --user daemon-reload
echo "PrimaLux Pulse removed. OpenClaw and Tailscale Funnel were not touched."
