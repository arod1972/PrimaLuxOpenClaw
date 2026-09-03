#!/usr/bin/env python3
"""Working library — URLs and pasted Journey/regulator material for OpenClaw seats."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOME = Path(os.environ.get("HOME") or str(Path.home()))
OC_HOME = Path(os.environ.get("OPENCLAW_STATE_DIR", str(HOME / ".openclaw")))
STATE = Path(os.environ.get("PULSE_STATE", str(HOME / ".local/share/primalux-pulse")))
LIB = STATE / "library"
INDEX = LIB / "index.json"
SEATS = ("vera", "scout", "elena", "grant", "marcus", "lens")

PRESETS = [
    {"id": "ncua", "title": "NCUA", "url": "https://www.ncua.gov/"},
    {"id": "nist-ai-rmf", "title": "NIST AI Risk Management Framework", "url": "https://www.nist.gov/itl/ai-risk-management-framework"},
    {"id": "ffiec", "title": "FFIEC", "url": "https://www.ffiec.gov/"},
    {"id": "ffiec-it", "title": "FFIEC IT Handbook", "url": "https://ithandbook.ffiec.gov/"},
    {"id": "cfpb", "title": "CFPB", "url": "https://www.consumerfinance.gov/"},
    {"id": "frb", "title": "Federal Reserve", "url": "https://www.federalreserve.gov/"},
    {"id": "fdic", "title": "FDIC", "url": "https://www.fdic.gov/"},
    {"id": "occ", "title": "OCC", "url": "https://www.occ.gov/"},
]

MARKER_START = "<!-- pulse-library -->"
MARKER_END = "<!-- /pulse-library -->"
MAX_CHARS = 120_000


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.title_on = False
        self.title = ""
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag == "title":
            self.title_on = True
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr", "br", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1
        if tag == "title":
            self.title_on = False

    def handle_data(self, data):
        if self.skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self.title_on:
            self.title = (self.title + " " + text).strip()
        else:
            self.parts.append(text + " ")


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure():
    LIB.mkdir(parents=True, exist_ok=True)
    if not INDEX.exists():
        INDEX.write_text("[]\n", encoding="utf-8")


def load_index():
    ensure()
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_index(items):
    ensure()
    INDEX.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def slug(url: str, title: str = "") -> str:
    host = re.sub(r"[^a-z0-9]+", "-", (url or title or "note").lower())[:48].strip("-")
    digest = hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:8]
    return (host or "src") + "-" + digest


def extract(html: str, fallback: str) -> tuple[str, str]:
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    title = (p.title or fallback or "Untitled").strip()
    body = re.sub(r"\n{3,}", "\n\n", "".join(p.parts)).strip()
    if not body:
        body = re.sub(r"<[^>]+>", " ", html)
        body = re.sub(r"\s+", " ", body).strip()
    return title[:180], body[:MAX_CHARS]


def fetch_url(url: str) -> dict:
    url = (url or "").strip()
    if not url.startswith(("https://", "http://")):
        return {"ok": False, "error": "https URL required"}
    req = Request(url, headers={"User-Agent": "PrimaLuxPulse/1.5 (+library ingest)"})
    try:
        with urlopen(req, timeout=25) as resp:
            raw = resp.read(1_500_000)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            final = resp.geturl() or url
    except HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}", "url": url}
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason or exc), "url": url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "url": url}
    text = raw.decode("utf-8", errors="replace")
    if "html" in ctype or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, body = extract(text, url)
    else:
        title = url.rsplit("/", 1)[-1] or url
        body = text[:MAX_CHARS]
    return {"ok": True, "url": final, "title": title, "body": body}


def upsert(item: dict, body: str) -> dict:
    ensure()
    items = load_index()
    aid = item["id"]
    path = LIB / f"{aid}.md"
    header = f"# {item.get('title') or aid}\n\nSource: {item.get('url') or 'pasted'}\nFetched: {item.get('fetchedAt')}\n\n"
    path.write_text(header + (body or "") + "\n", encoding="utf-8")
    item["bytes"] = path.stat().st_size
    item["path"] = str(path)
    found = False
    for i, row in enumerate(items):
        if row.get("id") == aid:
            items[i] = item
            found = True
            break
    if not found:
        items.append(item)
    save_index(items)
    return item


def add_url(url: str, title: str = "") -> dict:
    got = fetch_url(url)
    if not got.get("ok"):
        return got
    aid = slug(got["url"], title or got["title"])
    item = {
        "id": aid,
        "title": (title or got["title"])[:180],
        "url": got["url"],
        "source": "url",
        "fetchedAt": utcnow(),
        "status": "ready",
    }
    upsert(item, got["body"])
    item["ok"] = True
    return item


def add_text(title: str, text: str) -> dict:
    title = (title or "Pasted note").strip()[:180]
    body = (text or "").strip()[:MAX_CHARS]
    if not body:
        return {"ok": False, "error": "empty body"}
    aid = slug("", title + body[:80])
    item = {
        "id": aid,
        "title": title,
        "url": "",
        "source": "paste",
        "fetchedAt": utcnow(),
        "status": "ready",
    }
    upsert(item, body)
    item["ok"] = True
    return item


def add_preset(pid: str) -> dict:
    preset = next((p for p in PRESETS if p["id"] == pid), None)
    if not preset:
        return {"ok": False, "error": f"unknown preset {pid}"}
    return add_url(preset["url"], preset["title"])


def delete_item(aid: str) -> dict:
    items = [x for x in load_index() if x.get("id") != aid]
    save_index(items)
    p = LIB / f"{aid}.md"
    if p.exists():
        p.unlink()
    return {"ok": True, "id": aid}


def knowledge_md(items):
    lines = [
        "# Working library",
        "",
        "Consult `knowledge/*.md` before answering NCUA, NIST, FFIEC, CFPB, Federal Reserve, OCC, FDIC, or PrimaLux Journey questions.",
        "Cite the source URL. If a file is missing or stale, say so — do not invent a regulation.",
        "",
    ]
    if not items:
        lines.append("_No sources ingested yet._")
    for it in items:
        src = it.get("url") or "pasted"
        lines.append(f"- [{it.get('title') or it['id']}](knowledge/{it['id']}.md) — {src} ({it.get('fetchedAt') or ''})")
    lines.append("")
    return "\n".join(lines)


def _patch_memory(ws: Path):
    mem = ws / "MEMORY.md"
    existing = mem.read_text(encoding="utf-8", errors="replace") if mem.exists() else ""
    block = (
        f"{MARKER_START}\n"
        "Working library is in KNOWLEDGE.md and knowledge/. Read those before regulator or Journey answers.\n"
        f"{MARKER_END}\n"
    )
    if MARKER_START in existing and MARKER_END in existing:
        pre = existing.split(MARKER_START, 1)[0]
        post = existing.split(MARKER_END, 1)[1]
        existing = pre.rstrip() + "\n\n" + block + post.lstrip()
    else:
        existing = existing.rstrip() + "\n\n" + block
    mem.write_text(existing if existing.endswith("\n") else existing + "\n", encoding="utf-8")


def sync_seats() -> dict:
    items = [x for x in load_index() if x.get("status") == "ready"]
    synced = []
    for seat in SEATS:
        ws = OC_HOME / f"workspace-{seat}"
        if not ws.exists():
            continue
        kdir = ws / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        for old in kdir.glob("*.md"):
            old.unlink()
        for it in items:
            src = LIB / f"{it['id']}.md"
            if src.exists():
                shutil_copy = src.read_text(encoding="utf-8", errors="replace")
                (kdir / f"{it['id']}.md").write_text(shutil_copy, encoding="utf-8")
        (ws / "KNOWLEDGE.md").write_text(knowledge_md(items), encoding="utf-8")
        _patch_memory(ws)
        synced.append(seat)
    return {"ok": True, "seats": synced, "sources": len(items)}


def snapshot():
    return {"ok": True, "items": load_index(), "presets": PRESETS, "dir": str(LIB)}
