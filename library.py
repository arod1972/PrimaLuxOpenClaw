#!/usr/bin/env python3
"""Working library — URLs and pasted Journey/regulator material for OpenClaw seats."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
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

PRESETS = [
    {"id": "ncua", "title": "NCUA", "url": "https://www.ncua.gov/", "summary": "National Credit Union Administration — chartering, supervision, and Share Insurance Fund."},
    {"id": "nist-ai-rmf", "title": "NIST AI Risk Management Framework", "url": "https://www.nist.gov/itl/ai-risk-management-framework", "summary": "NIST AI RMF — govern, map, measure, and manage AI risk for trustworthy systems."},
    {"id": "ffiec", "title": "FFIEC", "url": "https://www.ffiec.gov/", "summary": "Federal Financial Institutions Examination Council — interagency exam standards."},
    {"id": "ffiec-it", "title": "FFIEC IT Handbook", "url": "https://ithandbook.ffiec.gov/", "summary": "FFIEC IT Examination Handbook — info security, business continuity, development, and operations."},
    {"id": "cfpb", "title": "CFPB", "url": "https://www.consumerfinance.gov/", "summary": "Consumer Financial Protection Bureau — consumer rules, exams, and enforcement."},
    {"id": "frb", "title": "Federal Reserve", "url": "https://www.federalreserve.gov/", "summary": "Board of Governors — supervision, payments, and financial stability."},
    {"id": "fdic", "title": "FDIC", "url": "https://www.fdic.gov/", "summary": "Federal Deposit Insurance Corporation — deposit insurance and bank supervision."},
    {"id": "occ", "title": "OCC", "url": "https://www.occ.gov/", "summary": "Office of the Comptroller of the Currency — national bank and federal thrift supervision."},
]
BUNDLED = Path(__file__).resolve().parent / "knowledge"

MARKER_START = "<!-- pulse-library -->"
MARKER_END = "<!-- /pulse-library -->"
MAX_CHARS = 120_000


class _Text(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "form", "button", "template"}
    BANNER = (
        "usa-banner", "gov-banner", "skip-link", "skipnav", "skip-nav",
        "cookie", "usa-header", "usa-nav", "site-header", "global-header",
        "megamenu", "mobile-menu",
    )

    def __init__(self):
        super().__init__()
        self.skip = 0
        self.title_on = False
        self.title = ""
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self.in_main = 0
        self.saw_main = False
        self._skip_stack: list[bool] = []

    def handle_starttag(self, tag, attrs):
        ad = {str(k).lower(): str(v or "") for k, v in attrs}
        blob = f"{tag} {ad.get('id','')} {ad.get('class','')} {ad.get('role','')}".lower()
        banner = tag in self.SKIP_TAGS or any(b in blob for b in self.BANNER)
        self._skip_stack.append(banner)
        if banner:
            self.skip += 1
            return
        if tag == "title":
            self.title_on = True
        if tag in ("main", "article") or ad.get("role") == "main" or "main-content" in blob:
            self.in_main += 1
            self.saw_main = True
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr", "br", "section"):
            (self.main_parts if self.in_main else self.parts).append("\n")

    def handle_endtag(self, tag):
        banner = self._skip_stack.pop() if self._skip_stack else False
        if banner and self.skip:
            self.skip -= 1
        if tag == "title":
            self.title_on = False
        if tag in ("main", "article") and self.in_main:
            self.in_main -= 1

    def handle_data(self, data):
        if self.skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self.title_on:
            self.title = (self.title + " " + text).strip()
            return
        (self.main_parts if self.in_main else self.parts).append(text + " ")


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


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
FETCH_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


BOILER_RE = re.compile(
    r"^(skip to( main)? content|an official website of the united states|"
    r"here'?s how you know|official websites use \.gov|a \.gov website belongs|"
    r"secure \.gov websites use https|javascript (must be|is) enabled|"
    r"this website uses cookies|share this page|subscribe to|"
    r"menu|search|sign in|log in|español|espanol)\b",
    re.I,
)
DIRECTIVE_RE = re.compile(
    r"^\*\*(audience|voice|do not|corpus|hard stops|cite this file)\*\*",
    re.I,
)


def strip_boiler(text: str) -> str:
    kept = []
    for ln in (text or "").splitlines():
        s = re.sub(r"\s+", " ", ln).strip()
        if not s:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if BOILER_RE.match(s) or DIRECTIVE_RE.match(s):
            continue
        if s.lower() in ("skip to main content", "official website"):
            continue
        kept.append(s)
    blob = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    # Drop a leading USA banner paragraph if it still snuck in as one line.
    blob = re.sub(
        r"^(Skip to main content\s+)+",
        "",
        blob,
        flags=re.I,
    )
    blob = re.sub(
        r"An official website of the United States[^.]*\.\s*",
        "",
        blob,
        count=1,
        flags=re.I,
    )
    return blob.strip()


def extract(html: str, fallback: str) -> tuple[str, str]:
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    title = (p.title or fallback or "Untitled").strip()
    main = "".join(p.main_parts).strip()
    rest = "".join(p.parts).strip()
    raw = main if len(main) >= 240 else (main + "\n" + rest)
    body = strip_boiler(re.sub(r"\n{3,}", "\n\n", raw))
    if not body:
        body = strip_boiler(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))
    return title[:180], body[:MAX_CHARS]


def _looks_blocked(code: int, body: bytes) -> bool:
    if code in (401, 403, 429, 503):
        return True
    head = (body or b"")[:4000].decode("utf-8", errors="replace").lower()
    needles = (
        "access denied",
        "request unsuccessful",
        "errors.edgesuite.net",
        "attention required",
        "cf-mitigated",
        "akamai",
        "blocked",
    )
    return any(n in head for n in needles) and code != 200


def _curl_fetch(url: str) -> tuple[int, bytes, str]:
    if not shutil.which("curl"):
        raise FileNotFoundError("curl")
    p = subprocess.run(
        [
            "curl", "-sL", "--max-time", "25",
            "-A", BROWSER_UA,
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "Accept-Language: en-US,en;q=0.9",
            "-w", "\n__PULSE__%{http_code}__%{url_effective}",
            url,
        ],
        capture_output=True,
        timeout=32,
        check=False,
    )
    raw = p.stdout or b""
    marker = b"\n__PULSE__"
    if marker in raw:
        body, _, tail = raw.rpartition(marker)
        parts = tail.decode("utf-8", errors="replace").split("__", 1)
        code = int(parts[0]) if parts and parts[0].isdigit() else 0
        final = parts[1] if len(parts) > 1 else url
        return code, body, final
    return (0 if p.returncode else 200), raw, url


def _urllib_fetch(url: str) -> tuple[int, bytes, str]:
    req = Request(url, headers=FETCH_HEADERS)
    with urlopen(req, timeout=25) as resp:
        return int(getattr(resp, "status", 200) or 200), resp.read(1_500_000), (resp.geturl() or url)


def _archive_url(url: str) -> str:
    return "https://web.archive.org/web/2/" + url


def fetch_url(url: str) -> dict:
    url = (url or "").strip()
    if not url.startswith(("https://", "http://")):
        return {"ok": False, "error": "https URL required"}
    attempts = [url]
    last_err = "fetch failed"
    last_code = 0
    for target in attempts:
        code, raw, final = 0, b"", target
        try:
            code, raw, final = _curl_fetch(target)
        except Exception:
            try:
                code, raw, final = _urllib_fetch(target)
            except HTTPError as exc:
                last_code, last_err = int(exc.code), f"HTTP {exc.code}"
                raw = exc.read(4000) if hasattr(exc, "read") else b""
                if target == url and _looks_blocked(int(exc.code), raw):
                    attempts.append(_archive_url(url))
                continue
            except URLError as exc:
                last_err = str(exc.reason or exc)
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                continue
        if _looks_blocked(code, raw):
            last_code, last_err = code, f"HTTP {code or 403}"
            if target == url:
                attempts.append(_archive_url(url))
            continue
        if code and code >= 400:
            last_code, last_err = code, f"HTTP {code}"
            continue
        text = raw.decode("utf-8", errors="replace")
        if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")) or "html" in text[:200].lower():
            title, body = extract(text, url)
        else:
            title = url.rsplit("/", 1)[-1] or url
            body = text[:MAX_CHARS]
        via = "archive" if "web.archive.org" in (final or "") else "live"
        return {"ok": True, "url": url, "fetchedUrl": final, "title": title, "body": body, "via": via}
    return {"ok": False, "error": last_err, "url": url, "code": last_code}


def summarize(body: str, title: str = "", limit: int = 420) -> str:
    """Extractive blurb — skip .gov chrome and instruction headers."""
    skip = re.compile(r"^(source|fetched|status|summary)\s*:", re.I)
    parts = []
    for ln in strip_boiler(body or "").splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "<!--", "---", "```")):
            continue
        if skip.match(s) or s.startswith("**"):
            continue
        parts.append(s)
    blob = re.sub(r"\s+", " ", " ".join(parts)).strip()
    low = blob.lower()
    if "automated fetch was blocked" in low or "do not treat this stub" in low:
        return "Fetch blocked. Drop the official PDF or paste the text — this stub is not source material."
    if not blob:
        return (title or "No extractable summary.")[:limit]
    sentences = re.split(r"(?<=[.!?])\s+", blob)
    out = ""
    for sent in sentences:
        if BOILER_RE.match(sent):
            continue
        nxt = (out + " " + sent).strip() if out else sent
        if out and len(nxt) > limit:
            break
        out = nxt
        if len(out) >= 220:
            break
    return (out or blob)[:limit]


def upsert(item: dict, body: str) -> dict:
    ensure()
    items = load_index()
    aid = item["id"]
    path = LIB / f"{aid}.md"
    item["summary"] = summarize(body or "", item.get("title") or aid)
    header = (
        f"# {item.get('title') or aid}\n\n"
        f"Source: {item.get('url') or 'pasted'}\n"
        f"Fetched: {item.get('fetchedAt')}\n"
        f"Status: {item.get('status') or 'ready'}\n"
        f"Summary: {item['summary']}\n\n"
    )
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
        aid = slug(url, title or url)
        warning = (
            f"{got.get('error') or 'HTTP 403'}. This host blocks automated fetch "
            "(Akamai/WAF). Source URL is saved — drop the official PDF or paste text."
        )
        body = (
            f"Automated fetch was blocked ({got.get('error') or 'HTTP 403'}).\n\n"
            f"Canonical URL: {url}\n\n"
            "Open that URL in a browser, download the PDF or copy the text, then "
            "drop the file on Library or paste it. Do not treat this stub as the handbook.\n"
        )
        item = {
            "id": aid,
            "title": (title or url)[:180],
            "url": url,
            "source": "url",
            "fetchedAt": utcnow(),
            "status": "blocked",
        }
        upsert(item, body)
        item["ok"] = True
        item["blocked"] = True
        item["warning"] = warning
        return item
    aid = slug(got["url"], title or got["title"])
    item = {
        "id": aid,
        "title": (title or got["title"])[:180],
        "url": got["url"],
        "source": "url",
        "fetchedAt": utcnow(),
        "status": "ready",
        "via": got.get("via") or "live",
    }
    upsert(item, got["body"])
    item["ok"] = True
    if got.get("via") == "archive":
        item["warning"] = "Live site blocked fetch; ingested via Internet Archive."
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


def _pdf_text(data: bytes) -> str:
    try:
        import tempfile
        import subprocess
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            r = subprocess.run(["pdftotext", "-layout", "-nopgbrk", tmp.name, "-"], capture_output=True, timeout=20)
            if r.returncode == 0 and r.stdout:
                return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        import io
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _docx_text(data: bytes) -> str:
    try:
        import io
        import zipfile
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        parts = [t.text for t in root.findall(".//w:t", ns) if t.text]
        return "\n".join(parts)
    except Exception:
        return ""


def add_file(filename: str, data: bytes, mime: str = "") -> dict:
    name = Path(filename or "dropped").name
    if not data:
        return {"ok": False, "error": f"{name}: empty file"}
    if len(data) > 12_000_000:
        return {"ok": False, "error": f"{name}: over 12 MB"}
    ext = Path(name).suffix.lower()
    mime = (mime or "").lower()
    title = Path(name).stem.replace("_", " ").replace("-", " ")
    body = ""
    if ext == ".pdf" or "pdf" in mime:
        body = _pdf_text(data)
        if not body.strip():
            return {"ok": False, "error": f"{name}: could not extract PDF text"}
    elif ext == ".docx" or "wordprocessingml" in mime:
        body = _docx_text(data)
        if not body.strip():
            return {"ok": False, "error": f"{name}: could not extract Word text"}
    elif ext in (".html", ".htm") or "html" in mime:
        title2, body = extract(data.decode("utf-8", errors="replace"), title)
        title = title2 or title
    else:
        body = data.decode("utf-8", errors="replace")
    body = body.strip()[:MAX_CHARS]
    if not body:
        return {"ok": False, "error": f"{name}: no extractable text"}
    ensure()
    raw = LIB / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / name).write_bytes(data[:12_000_000])
    aid = slug(name, title + body[:80])
    item = {
        "id": aid,
        "title": title[:180],
        "url": name,
        "source": "file",
        "fetchedAt": utcnow(),
        "status": "ready",
    }
    upsert(item, body)
    item["ok"] = True
    return item


def seed_bundled() -> dict:
    """Install Journey markdown that ships next to library.py."""
    ensure()
    n = 0
    if BUNDLED.is_dir():
        for p in sorted(BUNDLED.glob("*.md")):
            body = p.read_text(encoding="utf-8", errors="replace").strip()
            if not body:
                continue
            aid = "bundled-" + p.stem[:40]
            item = {
                "id": aid,
                "title": p.stem.replace("-", " "),
                "url": p.name,
                "source": "bundled",
                "fetchedAt": utcnow(),
                "status": "ready",
            }
            upsert(item, body)
            n += 1
    synced = sync_seats()
    return {"ok": True, "seeded": n, **synced}


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
        note = "fetch blocked — drop PDF" if it.get("status") == "blocked" else (it.get("fetchedAt") or "")
        blurb = (it.get("summary") or "").strip()
        lines.append(f"- **{it.get('title') or it['id']}** — {src} ({note})")
        if blurb:
            lines.append(f"  {blurb}")
        lines.append(f"  File: `knowledge/{it['id']}.md`")
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
    items = enrich_index()
    synced = []
    workspaces = [p for p in OC_HOME.glob("workspace-*") if p.is_dir()] if OC_HOME.exists() else []
    for ws in workspaces:
        kdir = ws / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        for old in kdir.glob("*.md"):
            old.unlink()
        for it in items:
            src = LIB / f"{it['id']}.md"
            if src.exists():
                (kdir / f"{it['id']}.md").write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        (ws / "KNOWLEDGE.md").write_text(knowledge_md(items), encoding="utf-8")
        _patch_memory(ws)
        synced.append(ws.name.replace("workspace-", "", 1))
    return {"ok": True, "seats": synced, "sources": len(items)}


def enrich_index():
    items = load_index()
    changed = False
    for it in items:
        path = LIB / f"{it.get('id') or ''}.md"
        body = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        blurb = summarize(body, it.get("title") or "")
        if it.get("summary") != blurb:
            it["summary"] = blurb
            changed = True
    if changed:
        save_index(items)
    return items


def read_item(aid: str) -> dict:
    items = load_index()
    it = next((x for x in items if x.get("id") == aid), None)
    if not it:
        return {"ok": False, "error": "not found"}
    path = LIB / f"{aid}.md"
    body = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return {"ok": True, **it, "body": body, "summary": it.get("summary") or summarize(body, it.get("title") or "")}


def refresh_item(aid: str) -> dict:
    items = load_index()
    it = next((x for x in items if x.get("id") == aid), None)
    if not it:
        return {"ok": False, "error": "not found"}
    url = (it.get("url") or "").strip()
    if it.get("source") == "url" and url.startswith("http"):
        return add_url(url, it.get("title") or "")
    if it.get("source") == "bundled":
        return seed_bundled()
    path = LIB / f"{aid}.md"
    body = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    it["summary"] = summarize(body, it.get("title") or "")
    it["fetchedAt"] = utcnow()
    save_index(items)
    return {"ok": True, **it}


def snapshot():
    return {"ok": True, "items": enrich_index(), "presets": PRESETS, "dir": str(LIB)}
