#!/usr/bin/env bash
# NUT NOTIFYCMD helper — log UPS events and nudge OpenClaw ops (no Slack).
# Set in upsmon.conf: NOTIFYCMD /home/<user>/.local/bin/nut-notify-openclaw.sh
set -euo pipefail

NOTIFYTYPE="${NOTIFYTYPE:-UNKNOWN}"
UPSNAME="${UPSNAME:-cyberpower@localhost}"
HOST="$(hostname -s 2>/dev/null || hostname || echo unknown)"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/primalux-pulse"
EVENT_LOG="${STATE_DIR}/ups-events.jsonl"
mkdir -p "${STATE_DIR}"

# Minimal JSON line (no secrets). Escape quotes in fields.
json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}
printf '{"ts":"%s","host":"%s","ups":"%s","notifyType":"%s"}\n' \
  "$(json_escape "$TS")" \
  "$(json_escape "$HOST")" \
  "$(json_escape "$UPSNAME")" \
  "$(json_escape "$NOTIFYTYPE")" >> "${EVENT_LOG}"

MSG="UPS ${UPSNAME} on ${HOST}: ${NOTIFYTYPE}"

notify_ok=0

# Prefer openclaw CLI → Quinn (ops) when available.
if command -v openclaw >/dev/null 2>&1; then
  if openclaw agent --agent quinn --message "${MSG}" --timeout 30 >/dev/null 2>&1 \
    || openclaw agent --agent quinn --message "${MSG}" >/dev/null 2>&1; then
    notify_ok=1
  fi
fi

# Fallback: workspace flag file for Quinn heartbeat / ops pickup.
if [[ "${notify_ok}" -eq 0 ]]; then
  FLAG_DIR="${HOME}/.openclaw/workspace-quinn"
  if [[ -d "${HOME}/.openclaw" ]]; then
    mkdir -p "${FLAG_DIR}"
    FLAG="${FLAG_DIR}/heartbeat-ups.md"
    {
      echo "# UPS alert"
      echo
      echo "- ts: ${TS}"
      echo "- host: ${HOST}"
      echo "- ups: ${UPSNAME}"
      echo "- notifyType: ${NOTIFYTYPE}"
      echo
      echo "${MSG}"
    } > "${FLAG}"
    notify_ok=1
  fi
fi

# Last resort: syslog via logger.
if [[ "${notify_ok}" -eq 0 ]]; then
  if command -v logger >/dev/null 2>&1; then
    logger -t nut-notify-openclaw "${MSG}"
  else
    echo "${MSG}" >&2
  fi
fi

exit 0
