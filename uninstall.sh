#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now clawbox.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/clawbox.service"
rm -f "${HOME}/.local/bin/clawbox"
rm -f "${HOME}/.local/share/applications/clawbox.desktop"
rm -rf "${HOME}/.local/lib/clawbox"
systemctl --user daemon-reload
echo "Clawbox removed. OpenClaw itself was not touched."
