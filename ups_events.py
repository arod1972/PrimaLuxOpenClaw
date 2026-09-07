#!/usr/bin/env python3
"""UPS NUT NOTIFYCMD event log — read-only for Pulse UI / API."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("HOME") or Path.home())
STATE = Path(os.environ.get("PULSE_STATE", str(HOME / ".local/share/primalux-pulse")))

DEFAULT_SYSTEM = Path("/var/lib/primalux-pulse/ups-events/events.jsonl")
DEFAULT_USER = STATE / "ups-events.jsonl"


def resolve_path() -> tuple[Path | None, str | None]:
    """Prefer UPS_EVENTS_PATH / system path; fall back to user share if unreadable."""
    env = (os.environ.get("UPS_EVENTS_PATH") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(DEFAULT_SYSTEM)
    # Also accept events under the dir if someone used a directory env.
    candidates.append(DEFAULT_USER)
    # Alternate under state: ups-events/events.jsonl
    candidates.append(STATE / "ups-events" / "events.jsonl")

    seen: set[str] = set()
    last_hint = None
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        try:
            if p.is_file() and os.access(p, os.R_OK):
                return p, None
            if p.exists() and not os.access(p, os.R_OK):
                last_hint = f"unreadable: {p}"
            elif not p.exists():
                last_hint = last_hint or f"missing: {p}"
        except OSError as exc:
            last_hint = f"{p}: {exc}"
    # Prefer reporting the primary expected path in the hint.
    primary = candidates[0] if candidates else DEFAULT_SYSTEM
    return None, last_hint or f"no readable UPS events log (tried {primary})"


def _normalize(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    nt = str(row.get("notifyType") or row.get("notify_type") or "").strip()
    if not nt and not row.get("ts"):
        return None
    return {
        "ts": str(row.get("ts") or ""),
        "host": str(row.get("host") or ""),
        "ups": str(row.get("ups") or ""),
        "notifyType": nt or "UNKNOWN",
        "detail": str(row.get("detail") or row.get("message") or ""),
    }


def read_events(limit: int = 100) -> dict[str, Any]:
    """Return newest-first events from the JSONL log. Never raises for IO."""
    limit = max(1, min(int(limit or 100), 500))
    path, hint = resolve_path()
    if path is None:
        return {
            "ok": True,
            "path": None,
            "hint": hint,
            "events": [],
        }

    events: list[dict[str, Any]] = []
    try:
        # Tail-ish: read whole file (logs stay small); keep last N after parse.
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "ok": True,
            "path": str(path),
            "hint": f"unreadable: {exc}",
            "events": [],
        }

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = _normalize(raw)
        if item:
            events.append(item)

    # Newest-first: prefer ts desc; stable so append order wins when ts ties.
    events.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    events = events[:limit]
    return {
        "ok": True,
        "path": str(path),
        "hint": None,
        "events": events,
    }


def recent(limit: int = 10) -> list[dict[str, Any]]:
    return read_events(limit=limit).get("events") or []
