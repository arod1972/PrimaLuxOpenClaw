#!/usr/bin/env python3
"""Cora answer gaps — queue for Pulse triage (FAQ / library promote)."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("HOME") or Path.home())
STATE = Path(os.environ.get("PULSE_STATE", str(HOME / ".local/share/primalux-pulse")))
GAPS_DIR = STATE / "cora-gaps"
INDEX = GAPS_DIR / "index.json"

REASONS = (
    "faq_miss",
    "library_hedge",
    "out_of_scope",
    "empty_reply",
    "upstream_fail",
    "user_downvote",
)

_REDACT = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._\-]+|(authorization:\s*)\S+|(token[\"']?\s*[:=]\s*[\"']?)[a-z0-9\-._]+"
)


def ensure() -> None:
    GAPS_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX.exists():
        INDEX.write_text("[]\n", encoding="utf-8")


def _load() -> list[dict]:
    ensure()
    try:
        raw = json.loads(INDEX.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    ensure()
    INDEX.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def redact(text: str, limit: int = 4000) -> str:
    s = _REDACT.sub(r"\1[redacted]", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def add_gap(body: dict[str, Any]) -> dict:
    """Record a Cora miss for founder triage. Loopback / tailnet Pulse only."""
    question = redact(str(body.get("question") or body.get("message") or ""), 2000)
    if not question:
        return {"ok": False, "error": "question required"}

    reason = str(body.get("reason") or "faq_miss").strip().lower()
    if reason not in REASONS:
        reason = "faq_miss"

    host = str(body.get("host") or "unknown").strip().lower()[:32]
    if host not in ("navigator", "erp", "assessment", "unknown"):
        host = "unknown"

    gap_id = str(body.get("id") or uuid.uuid4().hex[:16])
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    item = {
        "id": gap_id,
        "ts": now,
        "host": host,
        "sessionId": str(body.get("sessionId") or body.get("session_id") or "")[:80],
        "requestId": str(body.get("requestId") or body.get("request_id") or "")[:64],
        "question": question,
        "replySnippet": redact(str(body.get("replySnippet") or body.get("reply") or ""), 1200),
        "reason": reason,
        "faqId": (str(body.get("faqId") or "")[:64] or None),
        "source": str(body.get("source") or "")[:32] or None,
        "status": "open",  # open | dismissed | promoted_faq | promoted_library
        "notes": "",
    }

    items = _load()
    # Dedupe: same host+normalized question open within 24h → bump count
    qn = question.lower()
    for existing in items:
        if (
            existing.get("status") == "open"
            and existing.get("host") == host
            and str(existing.get("question") or "").lower() == qn
        ):
            existing["count"] = int(existing.get("count") or 1) + 1
            existing["ts"] = now
            existing["replySnippet"] = item["replySnippet"] or existing.get("replySnippet")
            existing["reason"] = reason
            existing["requestId"] = item["requestId"] or existing.get("requestId")
            _save(items)
            return {"ok": True, "gap": existing, "deduped": True}

    item["count"] = 1
    items.insert(0, item)
    # Cap store
    if len(items) > 500:
        items = items[:500]
    _save(items)
    return {"ok": True, "gap": item, "deduped": False}


def list_gaps(status: str | None = "open", limit: int = 100) -> dict:
    items = _load()
    if status and status != "all":
        items = [g for g in items if g.get("status") == status]
    limit = max(1, min(int(limit or 100), 500))
    open_n = sum(1 for g in _load() if g.get("status") == "open")
    return {"ok": True, "gaps": items[:limit], "openCount": open_n, "total": len(_load())}


def get_gap(gap_id: str) -> dict:
    for g in _load():
        if g.get("id") == gap_id:
            return {"ok": True, "gap": g}
    return {"ok": False, "error": "not_found"}


def patch_gap(gap_id: str, body: dict[str, Any]) -> dict:
    items = _load()
    for g in items:
        if g.get("id") != gap_id:
            continue
        if "status" in body:
            st = str(body.get("status") or "").strip().lower()
            if st in ("open", "dismissed", "promoted_faq", "promoted_library"):
                g["status"] = st
        if "notes" in body:
            g["notes"] = redact(str(body.get("notes") or ""), 2000)
        g["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save(items)
        return {"ok": True, "gap": g}
    return {"ok": False, "error": "not_found"}


def dismiss(gap_id: str) -> dict:
    return patch_gap(gap_id, {"status": "dismissed"})


def promote_library(gap_id: str) -> dict:
    """Create a Standing library note from the gap for human review / sync."""
    found = get_gap(gap_id)
    if not found.get("ok"):
        return found
    g = found["gap"]
    try:
        import library as lib  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"library unavailable: {exc}"}

    title = f"Cora gap — {g.get('question', '')[:80]}"
    body = (
        f"# Cora gap (auto)\n\n"
        f"- Host: `{g.get('host')}`\n"
        f"- Reason: `{g.get('reason')}`\n"
        f"- Count: {g.get('count', 1)}\n"
        f"- Captured: {g.get('ts')}\n\n"
        f"## Question\n\n{g.get('question')}\n\n"
        f"## Reply snippet\n\n{g.get('replySnippet') or '(none)'}\n\n"
        f"## Next\n\nDraft a Journey FAQ answer or library note, then Sync to Cora.\n"
    )
    added = lib.add_text(
        title,
        body,
        destination="standing",
        collection="standing",
        audience="own",
        trusted=False,
        tags=["cora-gap", str(g.get("host") or ""), str(g.get("reason") or "")],
    )
    patched = patch_gap(gap_id, {"status": "promoted_library"})
    return {"ok": True, "gap": patched.get("gap"), "library": added}
