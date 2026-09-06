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
    {"id": "ncua-ai", "title": "NCUA AI Hub", "url": "https://ncua.gov/regulation-supervision/regulatory-compliance-resources/artificial-intelligence-resources", "summary": "NCUA artificial intelligence resources for credit unions — supervision and compliance guidance."},
    {"id": "cfpb-circulars", "title": "CFPB Circulars", "url": "https://www.consumerfinance.gov/compliance/circulars/", "summary": "CFPB Consumer Financial Protection Circulars — interpretive guidance for supervised institutions."},
    {"id": "nist-ai-100-1", "title": "NIST AI 100-1", "url": "https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10", "summary": "NIST AI RMF 1.0 (AI 100-1) — framework for managing risks of AI systems."},
]
BUNDLED = Path(__file__).resolve().parent / "knowledge"

# TalkTrack-inspired destinations / collections.
# Core: always sync to BA. Standing: review queue (trusted:false) before promote.
# Working: current Pulse KNOWLEDGE sync set. Engagement: imported from engagement library.
COLLECTIONS = ("core", "standing", "working", "engagement")
DEST_ALIASES = {
    "core": "core",
    "standing": "standing",
    "working": "working",
    "call": "working",
    "express": "working",
    "engagement": "engagement",
}
ENGAGEMENT_DEFAULT = HOME / "primalux-engagement" / "library"
# Optional Docling / markitdown venv for future engagement re-compile (not wired in this PR):
#   PULSE_ENGAGEMENT_VENV=/opt/primalux-engagement/venv
#   or default /opt/primalux-engagement/venv when present.


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


def resolve_collection(destination: str = "", collection: str = "") -> str:
    raw = (collection or destination or "working").strip().lower()
    return DEST_ALIASES.get(raw, raw if raw in COLLECTIONS else "working")


def normalize_item(it: dict) -> dict:
    """Apply v2 defaults for older index rows (backward compatible)."""
    if not isinstance(it, dict):
        return it
    it.setdefault("collection", "working")
    if it.get("collection") not in COLLECTIONS:
        it["collection"] = "working"
    if "trusted" not in it:
        # Standing enters review queue; everything else trusted by default.
        it["trusted"] = it.get("collection") != "standing"
    it.setdefault("tier", "")
    it.setdefault("license", "")
    it.setdefault("domain", "")
    it.setdefault("audience", "public" if it.get("collection") == "engagement" else "own")
    it.setdefault("obe", False)
    it.setdefault("tags", [])
    if not isinstance(it.get("tags"), list):
        it["tags"] = list(it.get("tags") or []) if it.get("tags") else []
    it.setdefault("source", it.get("source") or "url")
    return it


def meta_for_destination(destination: str = "", collection: str = "", **extra) -> dict:
    coll = resolve_collection(destination, collection)
    trusted = True if coll != "standing" else False
    if "trusted" in extra and extra["trusted"] is not None:
        trusted = bool(extra.pop("trusted"))
    meta = {
        "collection": coll,
        "trusted": trusted,
        "tier": str(extra.pop("tier", "") or ""),
        "license": str(extra.pop("license", "") or ""),
        "domain": str(extra.pop("domain", "") or ""),
        "audience": str(extra.pop("audience", "") or ("own" if coll != "engagement" else "public")),
        "obe": bool(extra.pop("obe", False)),
        "tags": list(extra.pop("tags", []) or []),
    }
    return meta


def engagement_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    env = (os.environ.get("PULSE_ENGAGEMENT_LIBRARY") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return ENGAGEMENT_DEFAULT.expanduser().resolve()


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
    normalize_item(item)
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


def add_url(url: str, title: str = "", destination: str = "", collection: str = "", **meta) -> dict:
    dest_meta = meta_for_destination(destination, collection, **meta)
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
            **dest_meta,
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
        **dest_meta,
    }
    upsert(item, got["body"])
    item["ok"] = True
    if got.get("via") == "archive":
        item["warning"] = "Live site blocked fetch; ingested via Internet Archive."
    return item


def add_text(title: str, text: str, destination: str = "", collection: str = "", **meta) -> dict:
    title = (title or "Pasted note").strip()[:180]
    body = (text or "").strip()[:MAX_CHARS]
    if not body:
        return {"ok": False, "error": "empty body"}
    aid = slug("", title + body[:80])
    dest_meta = meta_for_destination(destination, collection, **meta)
    item = {
        "id": aid,
        "title": title,
        "url": "",
        "source": "paste",
        "fetchedAt": utcnow(),
        "status": "ready",
        **dest_meta,
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


def add_file(filename: str, data: bytes, mime: str = "", destination: str = "", collection: str = "", **meta) -> dict:
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
    dest_meta = meta_for_destination(destination, collection, **meta)
    item = {
        "id": aid,
        "title": title[:180],
        "url": name,
        "source": "file",
        "fetchedAt": utcnow(),
        "status": "ready",
        **dest_meta,
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
                **meta_for_destination("core"),
            }
            upsert(item, body)
            n += 1
    synced = sync_seats()
    return {"ok": True, "seeded": n, **synced}


def add_preset(pid: str, destination: str = "", collection: str = "", **meta) -> dict:
    preset = next((p for p in PRESETS if p["id"] == pid), None)
    if not preset:
        return {"ok": False, "error": f"unknown preset {pid}"}
    # Regulator presets default to Core (always available to BA).
    dest = destination or collection or "core"
    return add_url(preset["url"], preset["title"], destination=dest, collection=collection or dest, **meta)


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


def _seat_audience(ws: Path) -> str:
    pulse = ws / ".pulse.json"
    if pulse.exists():
        try:
            data = json.loads(pulse.read_text(encoding="utf-8"))
            aud = str(data.get("audience") or "internal").strip().lower()
            if aud in ("customer", "navigator", "external"):
                return "customer"
            return "internal"
        except Exception:
            pass
    # Cora is the customer-facing BA seat by convention.
    sid = ws.name.replace("workspace-", "", 1)
    if sid == "cora":
        return "customer"
    return "internal"


def _tag_match(it: dict, tag_filter) -> bool:
    if not tag_filter:
        return True
    tags = {str(t).lower() for t in (it.get("tags") or [])}
    wanted = tag_filter if isinstance(tag_filter, (list, tuple, set)) else [tag_filter]
    wanted = {str(t).lower() for t in wanted if t}
    return bool(wanted & tags) if wanted else True


def item_visible_for_seat(it: dict, seat_audience: str, collection=None, tag_filter=None, audience=None) -> bool:
    """Who gets what: OBE never; Standing only when trusted; no Gartner→customer."""
    it = normalize_item(dict(it))
    if it.get("obe"):
        return False
    coll = it.get("collection") or "working"
    if collection:
        want = resolve_collection("", str(collection))
        if coll != want:
            return False
    if audience:
        # Filter items by their own audience field when requested.
        if str(it.get("audience") or "").lower() != str(audience).lower():
            return False
    if not _tag_match(it, tag_filter):
        return False
    if coll == "standing" and not it.get("trusted"):
        return False
    lic = str(it.get("license") or "").strip().lower()
    if seat_audience == "customer" and lic == "gartner":
        return False
    if coll == "engagement":
        eng_aud = str(it.get("audience") or "public").strip().lower()
        if seat_audience == "customer":
            # Customer seats: public engagement only (never gartner — already gated).
            return eng_aud == "public"
        # BA / internal: core path includes engagement public|own.
        return eng_aud in ("public", "own", "")
    # core + working (+ trusted standing already passed) for all seats (customer still gartner-gated).
    if coll in ("core", "working", "standing"):
        return True
    return False


def filter_items_for_seat(items, seat_audience: str, collection=None, tag_filter=None, audience=None):
    out = []
    for it in items:
        if item_visible_for_seat(it, seat_audience, collection=collection, tag_filter=tag_filter, audience=audience):
            out.append(normalize_item(dict(it)))
    return out


def sync_seats(seat_ids=None, collection=None, tag_filter=None, audience=None) -> dict:
    """Sync library markdown into OpenClaw seat workspaces.

    Defaults: Core + Working + trusted Standing + Engagement(public|own for BA).
    Never sync license=gartner to audience=customer seats. OBE quarantine is skipped.
    """
    items = enrich_index()
    synced = []
    per_seat = {}
    workspaces = [p for p in OC_HOME.glob("workspace-*") if p.is_dir()] if OC_HOME.exists() else []
    want_ids = None
    if seat_ids:
        if isinstance(seat_ids, str):
            seat_ids = [s.strip() for s in seat_ids.split(",") if s.strip()]
        want_ids = {str(s).strip() for s in seat_ids if str(s).strip()}
    for ws in workspaces:
        sid = ws.name.replace("workspace-", "", 1)
        if want_ids is not None and sid not in want_ids:
            continue
        seat_aud = _seat_audience(ws)
        # Optional audience filter selects which seats to touch.
        if audience and str(audience).lower() in ("customer", "internal"):
            if seat_aud != str(audience).lower():
                continue
        selected = filter_items_for_seat(
            items, seat_aud, collection=collection, tag_filter=tag_filter, audience=None
        )
        # BA (internal) always gets core + engagement(public|own) even if collection filter omitted.
        # When a collection filter is set, respect it strictly via filter_items_for_seat.
        kdir = ws / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        for old in kdir.glob("*.md"):
            old.unlink()
        for it in selected:
            src = LIB / f"{it['id']}.md"
            if src.exists():
                (kdir / f"{it['id']}.md").write_text(
                    src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
                )
        (ws / "KNOWLEDGE.md").write_text(knowledge_md(selected), encoding="utf-8")
        _patch_memory(ws)
        synced.append(sid)
        per_seat[sid] = {"audience": seat_aud, "sources": len(selected)}
    return {"ok": True, "seats": synced, "sources": len(items), "perSeat": per_seat}


def enrich_index():
    items = load_index()
    changed = False
    for it in items:
        before = json.dumps(it, sort_keys=True)
        normalize_item(it)
        path = LIB / f"{it.get('id') or ''}.md"
        body = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        blurb = summarize(body, it.get("title") or "")
        if it.get("summary") != blurb:
            it["summary"] = blurb
        if json.dumps(it, sort_keys=True) != before:
            changed = True
    if changed:
        save_index(items)
    return items


def patch_item(aid: str, **fields) -> dict:
    """Patch tags / promote / demote / OBE / metadata on an index row."""
    items = load_index()
    it = next((x for x in items if x.get("id") == aid), None)
    if not it:
        return {"ok": False, "error": "not found"}
    normalize_item(it)
    # Convenience verbs
    action = str(fields.pop("action", "") or "").strip().lower()
    if action == "promote":
        it["collection"] = "core"
        it["trusted"] = True
        it["obe"] = False
    elif action == "demote":
        it["collection"] = "standing"
        it["trusted"] = False
    elif action in ("obe", "quarantine"):
        it["obe"] = True
        it["trusted"] = False
    elif action in ("unobe", "restore"):
        it["obe"] = False
    allowed = {
        "title", "tags", "collection", "trusted", "tier", "license",
        "domain", "audience", "obe", "summary", "status",
    }
    for key, val in list(fields.items()):
        if key == "destination":
            it["collection"] = resolve_collection(str(val), "")
            if it["collection"] == "standing" and "trusted" not in fields:
                it["trusted"] = False
            elif it["collection"] == "core" and "trusted" not in fields:
                it["trusted"] = True
            continue
        if key not in allowed:
            continue
        if key == "collection":
            it["collection"] = resolve_collection("", str(val))
        elif key == "tags":
            if isinstance(val, str):
                it["tags"] = [t.strip() for t in val.split(",") if t.strip()]
            elif isinstance(val, list):
                it["tags"] = [str(t) for t in val]
            else:
                it["tags"] = []
        elif key in ("trusted", "obe"):
            it[key] = bool(val)
        else:
            it[key] = val
    it["updatedAt"] = utcnow()
    save_index(items)
    return {"ok": True, **normalize_item(dict(it))}


def _load_engagement_manifests(root: Path) -> dict:
    """Map relative .md out paths → manifest row (tags, source, license, …)."""
    meta = root / "meta"
    by_out = {}
    if not meta.is_dir():
        return by_out
    for mf in sorted(meta.glob("*_ingest_manifest.jsonl")):
        try:
            for ln in mf.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    row = json.loads(ln)
                except Exception:
                    continue
                out = str(row.get("out") or row.get("path") or "").strip()
                if out:
                    by_out[out.replace("\\", "/")] = row
                    by_out[Path(out).name] = row
        except Exception:
            continue
    return by_out


def import_engagement(path: str | Path | None = None, dry_run: bool = False) -> dict:
    """Import markdown from engagement library (drive/ + web/) into Pulse library.

    Env PULSE_ENGAGEMENT_LIBRARY or default ~/primalux-engagement/library.
    Skips full Docling wiring; optional venv hook at /opt/primalux-engagement/venv
    via PULSE_ENGAGEMENT_VENV for future re-compile.
    """
    root = engagement_root(path)
    if not root.is_dir():
        return {"ok": False, "error": f"engagement library not found: {root}", "imported": 0}
    manifests = _load_engagement_manifests(root)
    imported = []
    skipped = []
    ensure()
    items = {x.get("id"): x for x in load_index()}
    for sub, default_aud in (("drive", "own"), ("web", "public")):
        base = root / sub
        if not base.is_dir():
            continue
        for md in sorted(base.rglob("*.md")):
            rel = str(md.relative_to(root)).replace("\\", "/")
            rel_under = str(md.relative_to(base)).replace("\\", "/")
            body = md.read_text(encoding="utf-8", errors="replace").strip()
            if not body:
                skipped.append({"path": rel, "reason": "empty"})
                continue
            row = manifests.get(rel_under) or manifests.get(md.name) or manifests.get(rel) or {}
            title = (row.get("title") or md.stem.replace("_", " ").replace("-", " "))[:180]
            tags = list(row.get("tags") or [])
            if sub not in tags:
                tags = [sub] + tags
            domain = str(row.get("domain") or "")
            license_ = str(row.get("license") or "")
            # Heuristic: Gartner materials stay license-tagged so customer sync blocks them.
            blob_l = (title + " " + body[:400]).lower()
            if "gartner" in blob_l and not license_:
                license_ = "gartner"
            aid = "eng-" + slug(rel, title)
            meta = meta_for_destination(
                "engagement",
                audience=str(row.get("audience") or default_aud),
                trusted=True,
                tier=str(row.get("tier") or ""),
                license=license_,
                domain=domain,
                tags=tags,
            )
            item = {
                "id": aid,
                "title": title,
                "url": str(row.get("source") or rel),
                "source": "engagement",
                "fetchedAt": utcnow(),
                "status": "ready",
                "engagementPath": rel,
                **meta,
            }
            if dry_run:
                imported.append({"id": aid, "title": title, "path": rel, "audience": meta["audience"], "license": license_})
                continue
            upsert(item, body[:MAX_CHARS])
            imported.append({"id": aid, "title": title, "path": rel})
            items[aid] = item
    venv = (os.environ.get("PULSE_ENGAGEMENT_VENV") or "/opt/primalux-engagement/venv").strip()
    return {
        "ok": True,
        "root": str(root),
        "imported": len(imported),
        "skipped": len(skipped),
        "dryRun": bool(dry_run),
        "items": imported[:50],
        "doclingVenv": venv if Path(venv).exists() else None,
        # Docling / markitdown re-compile not invoked in this PR — venv path recorded for operators.
    }


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
    items = [normalize_item(dict(x)) for x in enrich_index()]
    review = [x for x in items if not x.get("trusted") and not x.get("obe")]
    obe = [x for x in items if x.get("obe")]
    return {
        "ok": True,
        "items": items,
        "presets": PRESETS,
        "dir": str(LIB),
        "collections": list(COLLECTIONS),
        "reviewQueue": review,
        "obe": obe,
        "engagementRoot": str(engagement_root()),
    }
