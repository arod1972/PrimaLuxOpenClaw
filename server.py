#!/usr/bin/env python3
"""PrimaLux Pulse — host health and OpenClaw console on the SER10 Max."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

HERE = Path(__file__).resolve().parent
WWW = Path(os.environ.get("CLAWBOX_WWW", str(HERE / "www")))
ROSTER = Path(os.environ.get("CLAWBOX_ROSTER", str(HERE / "roster")))
HOME = Path(os.environ.get("HOME") or str(Path.home()))
OC_HOME = Path(os.environ.get("OPENCLAW_STATE_DIR", str(HOME / ".openclaw")))
PORT = int(os.environ.get("CLAWBOX_PORT", os.environ.get("PULSE_PORT", "18787")))
BIND = os.environ.get("CLAWBOX_BIND", "127.0.0.1")
MODEL = os.environ.get("CLAWBOX_MODEL", "local-qwen/qwen-9b-q4-local")
DEMO = os.environ.get("CLAWBOX_DEMO", "").lower() in ("1", "true", "yes")
VERSION = "1.9.5"
OC_VERSION = "2026.8.2"
STATE = Path(os.environ.get("PULSE_STATE", str(HOME / ".local/share/primalux-pulse")))
GROK_MODEL = os.environ.get("PULSE_GROK_MODEL", "xai/grok-4.3")
VERA_MODEL = os.environ.get("PULSE_VERA_MODEL", "xai/grok-4.20-0309-non-reasoning")
GROK_PREFER = (
    "xai/grok-4.3",
    "xai/grok-4.3-latest",
    "xai/grok-latest",
    "xai/grok-4.5",
    "xai/grok-4.6",
)
VERA_GROK_PREFER = (
    "xai/grok-4.20-0309-non-reasoning",
    "xai/grok-4.20-non-reasoning",
    "xai/grok-4.20",
    "xai/grok-4.2",
    "xai/grok-4.3",
)
CUSTOMER_DENY = (
    "web_search", "web_fetch", "x_search", "browser", "exec", "process",
    "message", "sessions_spawn", "gateway", "canvas", "cron", "skill_workshop",
)
CUSTOMER_ALLOW = ("read", "memory_search", "memory_get")

NEW_ROSTER = ("vera", "scout", "elena", "grant", "marcus", "lens")
OLD_ROSTER = (
    "ken", "aria", "dex", "sol", "reggie", "cleo",
    "connie", "lex", "finn", "ollie", "mira",
)
SEAT_TITLE = {
    "vera": "Chief of Staff",
    "scout": "Public research",
    "elena": "Marketing drafts",
    "grant": "Finance",
    "marcus": "Business development",
    "lens": "Technology research",
    "ken": "Default (unfinished)",
    "aria": "Unfinished",
    "dex": "Unfinished",
    "sol": "Unfinished — Chat owns architecture",
    "reggie": "Unfinished",
    "cleo": "Unfinished",
    "connie": "Unfinished",
    "lex": "Unfinished",
    "finn": "Unfinished",
    "ollie": "Unfinished",
    "mira": "Unfinished",
}
BOOTSTRAP = (
    "SOUL.md", "AGENTS.md", "IDENTITY.md", "USER.md",
    "TOOLS.md", "HEARTBEAT.md", "MEMORY.md",
)
FILE_KEYS = {
    "soul": "SOUL.md",
    "agents": "AGENTS.md",
    "identity": "IDENTITY.md",
    "user": "USER.md",
    "tools": "TOOLS.md",
    "heartbeat": "HEARTBEAT.md",
    "memory": "MEMORY.md",
}
SECRET_KEYS = ("token", "secret", "password", "passwd", "apikey", "api_key", "auth", "private", "credential")


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    print(f"[clawbox] {msg}", flush=True)


def which_openclaw():
    env = os.environ.get("OPENCLAW_BIN", "").strip()
    if env and Path(env).exists():
        return env
    found = shutil.which("openclaw")
    if found:
        return found
    nvm = HOME / ".nvm/versions/node"
    if nvm.exists():
        for p in sorted(nvm.glob("*/bin/openclaw"), reverse=True):
            return str(p)
    return "openclaw"


OC = which_openclaw()


def run(args, timeout=45, input_text=None):
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            input=input_text,
            env={**os.environ, "PATH": f"{Path(OC).parent}:{os.environ.get('PATH', '')}"},
        )
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "code": 127, "stdout": "", "stderr": f"{args[0]} not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": 124, "stdout": "", "stderr": "timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": 1, "stdout": "", "stderr": str(exc)}


def oc(*args, timeout=45):
    return run([OC, *args], timeout=timeout)


def parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        start_a = text.find("[")
        if start_a != -1 and (start == -1 or start_a < start):
            start = start_a
        if start == -1:
            return None
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return None


def read_text(path: Path, limit=120_000):
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        return data[:limit]
    except Exception:
        return ""


def write_text(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")


def load_config():
    p = OC_HOME / "openclaw.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    p = OC_HOME / "openclaw.json"
    bak = OC_HOME / f"openclaw.json.bak.clawbox.{int(time.time())}"
    if p.exists():
        shutil.copy2(p, bak)
    p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key = str(k).lower()
            if any(s in key for s in SECRET_KEYS):
                out[k] = "••••"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def config_backups():
    names = []
    if OC_HOME.exists():
        for p in sorted(OC_HOME.glob("openclaw.json*")):
            if p.name == "openclaw.json":
                continue
            names.append({"name": p.name, "bytes": p.stat().st_size, "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return names


def gateway_status():
    r = oc("gateway", "status", "--json", timeout=8)
    data = parse_json(r["stdout"]) or {}
    if not data:
        data = {
            "raw": r["stdout"][:2000],
            "stderr": r["stderr"][:1000],
            "ok": r["ok"],
        }
    data["_cliOk"] = r["ok"]
    data["_cli"] = OC
    data["_home"] = str(OC_HOME)
    data["_port"] = 18789
    return data


def _doctor_lane(f: dict) -> tuple[str, str]:
    blob = " ".join(str(f.get(k) or "") for k in ("checkId", "title", "message", "fixHint", "path")).lower()
    cid = str(f.get("checkId") or "").lower()
    if "loopback" in blob or "node-hosting-preconditions" in cid or "gateway is only bound" in blob:
        return (
            "expected",
            "By design. Pulse is the HTTPS edge (Tailscale Serve). The gateway stays on 127.0.0.1:18789.",
        )
    if "skill_workshop" in blob or "skill-workshop-tool-policy" in cid:
        return (
            "expected",
            "Customer seats are Library-only. skill_workshop is not granted.",
        )
    if "heartbeat.md" in blob or "heartbeat-scratch" in cid:
        return (
            "housekeeping",
            "OpenClaw wants HEARTBEAT.md in cron scratch. Repair can migrate; Pulse still edits the workspace file.",
        )
    if "tools.md" in blob or "tools-md-migration" in cid:
        return (
            "housekeeping",
            "OpenClaw wants TOOLS.md merged into AGENTS.md. Repair can migrate.",
        )
    if "plaintext" in blob or "secretref" in blob or "secret-bearing" in blob:
        return (
            "housekeeping",
            "Gateway token and the local-qwen dummy key live in openclaw.json on this box. SecretRefs is optional hardening, not an incident.",
        )
    if "drmmode" in blob or "cursor update failed" in blob:
        return ("noise", "Display compositor / Cursor IDE. Not Pulse.")
    return ("action", "")


def annotate_doctor(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"ok": False, "findings": [], "raw": str(data)[:4000]}
    findings = data.get("findings") or data.get("issues") or []
    if not findings and isinstance(data.get("report"), dict):
        findings = data["report"].get("findings") or data["report"].get("issues") or []
    if not isinstance(findings, list):
        findings = []
    lanes: dict[str, int] = {}
    out = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        if not f.get("message") and f.get("title"):
            f["message"] = f["title"]
        if not f.get("checkId"):
            f["checkId"] = f.get("code") or f.get("id") or ""
        lane, note = _doctor_lane(f)
        f["lane"] = lane
        if note:
            f["pulseNote"] = note
        lanes[lane] = lanes.get(lane, 0) + 1
        out.append(f)
    data["findings"] = out
    data["lanes"] = lanes
    return data


def doctor():
    r = oc("doctor", "--json", timeout=60)
    data = parse_json(r["stdout"])
    if data is None:
        return annotate_doctor({"ok": r["ok"], "raw": (r["stdout"] or r["stderr"])[:4000], "findings": []})
    data["ok"] = r["ok"] if "ok" not in data else data.get("ok")
    return annotate_doctor(data)


def doctor_repair():
    r = oc("doctor", "--repair", "--yes", "--non-interactive", timeout=120)
    if not r["ok"] and "unknown" in (r["stderr"] + r["stdout"]).lower():
        r = oc("doctor", "--fix", "--yes", timeout=120)
    return r


def clean_id(aid: str) -> str:
    return "".join(ch for ch in str(aid or "").lower() if ch.isalnum() or ch == "-")[:32]


def identity_fields(ws: Path) -> tuple[str, str]:
    name, title = "", ""
    ident = read_text(ws / "IDENTITY.md") if ws else ""
    for line in ident.splitlines():
        low = line.lower()
        if low.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif low.startswith("title:"):
            title = line.split(":", 1)[1].strip()
    return name, title


def upsert_ident_line(text: str, key: str, value: str) -> str:
    lines = (text or "").splitlines()
    found = False
    out = []
    prefix = key.lower() + ":"
    for line in lines:
        if line.lower().startswith(prefix):
            out.append(f"{key}: {value}")
            found = True
        else:
            out.append(line)
    if not found:
        if not out:
            out = ["# IDENTITY.md", ""]
        out.append(f"{key}: {value}")
    return "\n".join(out).rstrip() + "\n"


def title_for(aid: str, row: dict, ws: Path) -> str:
    title = SEAT_TITLE.get(aid, "")
    if title:
        return title
    ident = read_text(ws / "IDENTITY.md") if ws else ""
    for line in ident.splitlines():
        if line.lower().startswith("title:"):
            return line.split(":", 1)[1].strip()
    return str(row.get("identity") or row.get("title") or "")


def list_agents(include_files=False):
    r = oc("agents", "list", "--bindings", "--json", timeout=12)
    if not r.get("ok"):
        r = oc("agents", "list", "--json", timeout=12)
    data = parse_json(r["stdout"])
    agents = []
    if isinstance(data, list):
        agents = data
    elif isinstance(data, dict):
        agents = data.get("agents") or data.get("entries") or []
        if isinstance(agents, dict):
            agents = [{"id": k, **(v if isinstance(v, dict) else {"raw": v})} for k, v in agents.items()]
    if not agents:
        for ws in sorted(OC_HOME.glob("workspace-*")):
            aid = ws.name.replace("workspace-", "", 1)
            if aid == "attestations":
                continue
            ident = read_text(ws / "IDENTITY.md")
            name = aid
            for line in ident.splitlines():
                if line.lower().startswith("name:"):
                    name = line.split(":", 1)[1].strip() or aid
            agents.append({
                "id": aid,
                "name": name,
                "workspace": str(ws),
                "agentDir": str(OC_HOME / "agents" / aid / "agent"),
                "identityFile": bool(ident),
            })
    out = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or a.get("agentId") or a.get("name") or "").lower()
        if not aid:
            continue
        ws = Path(a.get("workspace") or OC_HOME / f"workspace-{aid}")
        if not ws.is_absolute():
            ws = OC_HOME / ws
        files = {k: read_text(ws / fname) for k, fname in FILE_KEYS.items()} if include_files else {}
        ident_name, ident_title = identity_fields(ws)
        cli_name = str(a.get("name") or a.get("identity") or "").strip()
        if ident_name:
            name = ident_name
        elif cli_name and cli_name.lower() != aid:
            name = cli_name
        else:
            name = aid.title()
        out.append({
            "id": aid,
            "name": name,
            "title": ident_title or title_for(aid, a, ws),
            "workspace": str(ws),
            "agentDir": str(a.get("agentDir") or OC_HOME / "agents" / aid / "agent"),
            "model": a.get("model") or a.get("Model") or MODEL,
            "default": bool(a.get("default") or a.get("isDefault")),
            "routingRules": a.get("routingRules") or a.get("bindings") or 0,
            "identityFile": True,
            "files": files,
            "status": "active",
            "audience": "internal",
        })
    cfg = load_config()
    entries = ((cfg.get("agents") or {}).get("entries") or {})
    for a in out:
        ent = entries.get(a["id"]) or {}
        if ent.get("default"):
            a["default"] = True
        if ent.get("model"):
            a["model"] = ent.get("model") if isinstance(ent.get("model"), str) else (ent.get("model") or {}).get("primary") or a["model"]
        tools = ent.get("tools") or {}
        if tools.get("deny") and "web_search" in (tools.get("deny") or []):
            a["audience"] = "customer"
        pp = Path(a["workspace"]) / ".pulse.json"
        if pp.exists():
            try:
                pulse = json.loads(pp.read_text(encoding="utf-8"))
                a["audience"] = pulse.get("audience") or a.get("audience") or "internal"
                if pulse.get("model"):
                    a["model"] = pulse.get("model")
            except Exception:
                pass
    return out


def update_identity(aid: str, name: str = "", title: str = ""):
    aid = clean_id(aid)
    if not aid:
        return {"ok": False, "error": "bad id"}
    name = (name or "").strip()[:80]
    title = (title or "").strip()[:120]
    if not name:
        return {"ok": False, "error": "name required"}
    if is_demo():
        SEAT_TITLE[aid] = title
        return {"ok": True, "id": aid, "name": name, "title": title, "demo": True}
    ws = OC_HOME / f"workspace-{aid}"
    ws.mkdir(parents=True, exist_ok=True)
    ident = ws / "IDENTITY.md"
    body = read_text(ident) if ident.exists() else "# IDENTITY.md\n\n"
    body = upsert_ident_line(body, "Name", name)
    body = upsert_ident_line(body, "Title", title)
    ident.write_text(body, encoding="utf-8")
    SEAT_TITLE[aid] = title
    oc("agents", "set-identity", "--agent", aid, "--from-identity", "--name", name, timeout=20)
    pulse = ws / ".pulse.json"
    meta = {}
    if pulse.exists():
        try:
            meta = json.loads(pulse.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    meta["id"] = aid
    meta["name"] = name
    meta["title"] = title
    pulse.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "id": aid, "name": name, "title": title}


def seed_agent(aid: str):
    src = ROSTER / aid
    ws = OC_HOME / f"workspace-{aid}"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    for name in BOOTSTRAP:
        fp = src / name
        if fp.exists():
            shutil.copy2(fp, ws / name)
    r = oc(
        "agents", "add", aid,
        "--workspace", str(ws),
        "--model", MODEL,
        "--non-interactive",
        timeout=60,
    )
    ident = oc("agents", "set-identity", "--agent", aid, "--from-identity", "--name", aid.title(), timeout=20)
    return {"add": r, "identity": ident, "workspace": str(ws)}


def set_default(aid: str):
    if is_demo():
        return True
    cfg = load_config()
    agents = cfg.setdefault("agents", {})
    entries = agents.setdefault("entries", {})
    for k, v in list(entries.items()):
        if not isinstance(v, dict):
            entries[k] = {}
            v = entries[k]
        v.pop("default", None)
        if k == aid:
            v["default"] = True
            v.setdefault("workspace", str(OC_HOME / f"workspace-{aid}"))
            if "model" not in v:
                v["model"] = MODEL
    if aid not in entries:
        entries[aid] = {
            "default": True,
            "workspace": str(OC_HOME / f"workspace-{aid}"),
            "model": MODEL,
        }
    save_config(cfg)
    oc("config", "set", f"agents.entries.{aid}.default", "true", timeout=15)
    return True


def _cli_ok(r: dict) -> bool:
    if r.get("ok") is True:
        return True
    code = r.get("code")
    if code in (0, "0", None) and not r.get("stderr"):
        return True
    err = (r.get("stderr") or r.get("error") or r.get("stdout") or "").lower()
    if "deleted" in err or "removed" in err:
        return True
    return code == 0


def delete_agent(aid: str):
    global _demo_ids
    aid = "".join(ch for ch in str(aid).lower() if ch.isalnum() or ch == "-")[:32]
    if not aid:
        return {"ok": False, "error": "bad id"}
    if is_demo():
        ids = list(_demo_ids if _demo_ids is not None else OLD_ROSTER)
        if aid not in ids:
            return {"ok": False, "error": f"{aid} not on disk", "id": aid}
        _demo_ids = [x for x in ids if x != aid]
        return {"ok": True, "stdout": f"demo delete {aid}", "code": 0, "stderr": "", "id": aid}
    live = list_agents()
    current = next((a for a in live if a["id"] == aid), None)
    if current and current.get("default"):
        fallback = next((a for a in live if a["id"] != aid and a["id"] in NEW_ROSTER), None)
        if not fallback:
            fallback = next((a for a in live if a["id"] != aid), None)
        if fallback:
            set_default(fallback["id"])
    r = oc("agents", "delete", aid, "--force", timeout=45)
    r["ok"] = _cli_ok(r)
    r["id"] = aid
    still = False
    try:
        still = aid in {a["id"] for a in list_agents()}
    except Exception:
        still = True
    if still:
        for p in (OC_HOME / f"workspace-{aid}", OC_HOME / "agents" / aid):
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
        cfg = load_config()
        entries = ((cfg.get("agents") or {}).get("entries") or {})
        if isinstance(entries, dict) and aid in entries:
            entries.pop(aid, None)
            save_config(cfg)
        r2 = oc("agents", "delete", aid, "--force", timeout=20)
        r["ok"] = True
        r["forced"] = True
        r["stderr"] = (r.get("stderr") or "") + "\n" + (r2.get("stderr") or "")
    if not r["ok"]:
        r["error"] = r.get("stderr") or r.get("stdout") or f"openclaw agents delete {aid} failed"
    return r


STANDBY = STATE / "standby"
_demo_standby: list = []


def load_standby():
    if is_demo():
        return list(_demo_standby)
    items = []
    if not STANDBY.exists():
        return items
    for p in sorted(STANDBY.iterdir()):
        if not p.is_dir():
            continue
        meta = {}
        mp = p / "meta.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        items.append({
            "id": p.name,
            "name": meta.get("name") or p.name,
            "title": meta.get("title") or "",
            "retiredAt": meta.get("retiredAt"),
            "status": "standby",
        })
    return items


def retire_agent(aid: str):
    global _demo_standby
    aid = clean_id(aid)
    if not aid:
        return {"ok": False, "error": "bad id"}
    live = next((a for a in (demo_agents() if is_demo() else list_agents()) if a["id"] == aid), None)
    if not live:
        return {"ok": False, "error": f"{aid} is not on the active roster"}
    if is_demo():
        delete_agent(aid)
        _demo_standby.append({
            "id": aid,
            "name": live.get("name") or aid,
            "title": live.get("title") or "",
            "retiredAt": utcnow(),
            "status": "standby",
        })
        return {"ok": True, "id": aid, "status": "standby"}
    dest = STANDBY / aid
    dest.mkdir(parents=True, exist_ok=True)
    ws = Path(live.get("workspace") or OC_HOME / f"workspace-{aid}")
    ad = OC_HOME / "agents" / aid
    if ws.exists():
        target = dest / "workspace"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(ws, target)
    if ad.exists():
        target = dest / "agent"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(ad, target)
    (dest / "meta.json").write_text(json.dumps({
        "id": aid,
        "name": live.get("name") or aid,
        "title": live.get("title") or "",
        "retiredAt": utcnow(),
    }, indent=2), encoding="utf-8")
    deleted = delete_agent(aid)
    return {"ok": True, "id": aid, "status": "standby", "delete": deleted}


def restore_agent(aid: str):
    global _demo_standby, _demo_ids
    aid = clean_id(aid)
    if not aid:
        return {"ok": False, "error": "bad id"}
    live_ids = {a["id"] for a in (demo_agents() if is_demo() else list_agents())}
    if aid in live_ids:
        return {"ok": False, "error": f"{aid} is already active"}
    if is_demo():
        row = next((x for x in _demo_standby if x["id"] == aid), None)
        if not row:
            return {"ok": False, "error": f"{aid} is not in standby"}
        _demo_standby = [x for x in _demo_standby if x["id"] != aid]
        ids = list(_demo_ids if _demo_ids is not None else NEW_ROSTER)
        if aid not in ids:
            ids.append(aid)
        _demo_ids = ids
        return {"ok": True, "id": aid, "status": "active"}
    src = STANDBY / aid
    if not src.exists():
        return {"ok": False, "error": f"{aid} is not in standby"}
    meta = {}
    mp = src / "meta.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    ws = OC_HOME / f"workspace-{aid}"
    if (src / "workspace").exists():
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
        shutil.copytree(src / "workspace", ws)
    else:
        ws.mkdir(parents=True, exist_ok=True)
    if (src / "agent").exists():
        ad = OC_HOME / "agents" / aid
        if ad.exists():
            shutil.rmtree(ad, ignore_errors=True)
        shutil.copytree(src / "agent", ad)
    added = oc(
        "agents", "add", aid,
        "--workspace", str(ws),
        "--model", MODEL,
        "--non-interactive",
        timeout=60,
    )
    err = (added.get("stderr") or added.get("stdout") or "").lower()
    if not _cli_ok(added) and "already" not in err and "exists" not in err:
        return {"ok": False, "error": added.get("stderr") or added.get("stdout") or "agents add failed — still on standby", "add": added, "status": "standby"}
    oc("agents", "set-identity", "--agent", aid, "--from-identity", "--name", str(meta.get("name") or aid.title()), timeout=20)
    shutil.rmtree(src, ignore_errors=True)
    return {"ok": True, "id": aid, "name": meta.get("name") or aid, "status": "active", "add": added}


def write_workspace(aid: str, name: str, title: str, soul: str = "", audience: str = "internal") -> Path:
    ws = OC_HOME / f"workspace-{aid}"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    src = ROSTER / aid
    if src.exists():
        for fname in BOOTSTRAP:
            fp = src / fname
            if fp.exists() and not (ws / fname).exists():
                shutil.copy2(fp, ws / fname)
    ident = ws / "IDENTITY.md"
    if not ident.exists():
        ident.write_text(f"# IDENTITY.md\n\nName: {name}\nTitle: {title}\nEmoji:\nAvatar:\n", encoding="utf-8")
    soul_p = ws / "SOUL.md"
    if audience == "customer":
        soul_p.write_text(customer_soul(name, title), encoding="utf-8")
        (ws / "TOOLS.md").write_text(customer_tools(), encoding="utf-8")
        (ws / "AGENTS.md").write_text(
            "# AGENTS.md\n\nSession start: read SOUL.md, USER.md, KNOWLEDGE.md, and knowledge/. If it is not in those files, you do not have it.\n",
            encoding="utf-8",
        )
    elif not soul_p.exists():
        body = f"# SOUL.md\n\nYou are {name}" + (f", {title}" if title else "") + ".\nDraft only. Do not send, post, or contact anyone without founder OK.\n"
        if soul:
            body += "\n" + soul.strip() + "\n"
        soul_p.write_text(body, encoding="utf-8")
    defaults = {
        "AGENTS.md": "# AGENTS.md\n\nSession start: read SOUL.md, USER.md, memory today+yesterday, MEMORY.md, and KNOWLEDGE.md if present.\n",
        "USER.md": "# USER.md\n\nThe human is the founder of PrimaLux Advisory LLC.\n",
        "TOOLS.md": "# TOOLS.md\n\n- Prefer the smallest tool that answers the brief.\n- Read KNOWLEDGE.md and knowledge/ before regulator or Journey answers.\n",
        "HEARTBEAT.md": "# HEARTBEAT.md\n\nIf nothing needs the founder, reply HEARTBEAT_OK.\n",
        "MEMORY.md": "# MEMORY.md\n\nDurable facts only.\n",
    }
    for fname, body in defaults.items():
        fp = ws / fname
        if not fp.exists():
            fp.write_text(body, encoding="utf-8")
    return ws


def _collect_model_ids(blob) -> list[str]:
    found: list[str] = []

    def walk(x):
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("grok-"):
                s = "xai/" + s
            if s.startswith("xai/") and s not in found:
                found.append(s)
        elif isinstance(x, dict):
            for k in ("id", "model", "key", "name", "primary"):
                if isinstance(x.get(k), str):
                    walk(x[k])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(blob)
    return found


def pick_grok_model(agent: str = "vera") -> str:
    customer = str(agent or "").lower() in ("cora",)
    prefer = GROK_PREFER if customer else VERA_GROK_PREFER
    forced = (GROK_MODEL if customer else VERA_MODEL).strip()
    collected: list[str] = []
    for who in (agent, "cora", "vera"):
        if not who:
            continue
        r = oc("models", "list", "--provider", "xai", "--agent", who, "--all", "--json", timeout=20)
        data = parse_json(r.get("stdout") or "") or parse_json(r.get("stderr") or "")
        collected.extend(_collect_model_ids(data))
        if not data:
            for ln in (r.get("stdout") or "").splitlines():
                low = ln.lower()
                if "grok" in low:
                    tok = ln.strip().split()[0].strip(",")
                    collected.extend(_collect_model_ids(tok))
        if collected:
            break
    usable = [m for m in collected if "auto" not in m.lower() and "imagine" not in m.lower()]
    if forced and "auto" not in forced.lower():
        if not usable or forced in usable or forced.startswith("xai/"):
            return forced
    for pref in prefer:
        if pref in usable:
            return pref
    return usable[0] if usable else (GROK_MODEL if customer else VERA_MODEL)


def _agent_sqlite(aid: str) -> Path:
    return OC_HOME / "agents" / aid / "agent" / "openclaw-agent.sqlite"


def _auth_json_files(aid: str) -> list[Path]:
    base = OC_HOME / "agents" / aid / "agent"
    return [
        base / "auth-profiles.json",
        base / "auth-state.json",
        base / "auth.json",
    ]


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def _row_mentions_xai(row) -> bool:
    blob = " ".join("" if x is None else str(x) for x in row).lower()
    return "xai" in blob or "grok" in blob


def _copy_xai_sqlite(src: Path, dest: Path) -> int:
    if not src.exists() or src.resolve() == dest.resolve():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=8)
    d = sqlite3.connect(str(dest), timeout=8)
    copied = 0
    try:
        for t in _sqlite_tables(s):
            if "auth" not in t.lower():
                continue
            create = s.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()
            if create and create[0]:
                d.execute(create[0].replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
            cols = [r[1] for r in s.execute(f'PRAGMA table_info("{t}")')]
            if not cols:
                continue
            coln = ",".join(f'"{c}"' for c in cols)
            ph = ",".join("?" * len(cols))
            for row in s.execute(f'SELECT {coln} FROM "{t}"'):
                if not _row_mentions_xai(row):
                    continue
                try:
                    d.execute(f'INSERT OR REPLACE INTO "{t}" ({coln}) VALUES ({ph})', tuple(row))
                    copied += 1
                except sqlite3.Error:
                    try:
                        d.execute(f'INSERT INTO "{t}" ({coln}) VALUES ({ph})', tuple(row))
                        copied += 1
                    except sqlite3.Error:
                        pass
        d.commit()
    finally:
        s.close()
        d.close()
    return copied


def share_xai_auth(dest: str) -> dict:
    dest = clean_id(dest)
    dest_db = _agent_sqlite(dest)
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    sources: list[Path] = []
    for aid in ("vera", "main", "default"):
        sources.append(_agent_sqlite(aid))
    agents_root = OC_HOME / "agents"
    if agents_root.exists():
        for p in sorted(agents_root.glob("*/agent/openclaw-agent.sqlite")):
            if p.parent.parent.name != dest:
                sources.append(p)
    sources.append(OC_HOME / "state" / "openclaw.sqlite")
    seen: set[str] = set()
    copied_sql = 0
    copied_json = 0
    used = []
    for src in sources:
        key = str(src)
        if key in seen or not src.exists():
            continue
        seen.add(key)
        n = _copy_xai_sqlite(src, dest_db)
        n2 = _copy_xai_sqlite(src, OC_HOME / "state" / "openclaw.sqlite")
        if n or n2:
            copied_sql += n + n2
            used.append(str(src))
        src_dir = src.parent
        for jf in ("auth-profiles.json", "auth-state.json", "auth.json"):
            sp = src_dir / jf
            if sp.exists():
                dp = dest_db.parent / jf
                if not dp.exists():
                    shutil.copy2(sp, dp)
                    copied_json += 1
    hint = (
        "xAI OAuth is per-agent. If Talk still says missing-provider-auth:\n"
        f"  openclaw models auth login --provider xai --method oauth --agent {dest}"
    )
    return {
        "ok": copied_sql > 0 or copied_json > 0,
        "dest": str(dest_db),
        "copiedRows": copied_sql,
        "copiedFiles": copied_json,
        "from": used,
        "hint": hint,
    }


def resolve_model(model: str, audience: str = "internal", aid: str = "") -> str:
    m = (model or "").strip()
    key = m.lower()
    who = "cora" if (audience == "customer" or aid == "cora") else "vera"
    if key in ("grok", "xai", "xai/auto", "xai-auto", "auto", "4.2", "4.20"):
        return pick_grok_model(who)
    if key in ("", "local", "qwen", "local-qwen", "local-qwen/qwen-9b-q4-local"):
        return MODEL
    if "auto" in key:
        return pick_grok_model(who)
    return m


def customer_soul(name: str, title: str) -> str:
    role = title or "Customer Relationship Manager"
    return (
        f"# {name} — {role}\n\n"
        f"You are {name}, {role} for PrimaLux Advisory LLC. You speak to credit-union operators through Navigator.\n"
        "You are not the Chief of Staff. You do not see internal pipeline, money, hiring, or other agents' work.\n\n"
        "## Corpus\n\n"
        "Answer only from `KNOWLEDGE.md` and `knowledge/` in this workspace (Library ingest: regulator sites and PrimaLux Journey material).\n"
        "If the file is not there, say you do not have it. Do not use training memory as a citation. Do not browse the web.\n\n"
        "## Voice\n\n"
        "Clear, calm, operator-facing. Cite the source filename or URL from the library. Separate fact vs. general practice.\n\n"
        "## Hard stops\n\n"
        "Invent a regulation, exam finding, or Journey phase. Speak as an internal seat. Discuss PrimaLux internals, other clients, or unreleased work. Send messages, run shell, or open a browser.\n"
    )


def customer_tools() -> str:
    return (
        "# TOOLS.md\n\n"
        "- Read `KNOWLEDGE.md` and `knowledge/` only.\n"
        "- Do not web_search, web_fetch, browse, exec, or message.\n"
        "- If the answer is not in those files, say so. Do not invent a cite.\n"
    )


def apply_seat_policy(aid: str, model: str, audience: str) -> None:
    cfg = load_config()
    agents = cfg.setdefault("agents", {})
    entries = agents.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        agents["entries"] = entries
    ent = entries.setdefault(aid, {})
    if not isinstance(ent, dict):
        ent = {}
        entries[aid] = ent
    ent["model"] = model
    if audience == "customer":
        ent["tools"] = {
            "allow": list(CUSTOMER_ALLOW),
            "deny": list(CUSTOMER_DENY),
        }
    save_config(cfg)
    oc("config", "set", f"agents.entries.{aid}.model", model, timeout=12)
    oc("config", "set", f"agents.entries.{aid}.model.primary", model, timeout=12)
    ws = OC_HOME / f"workspace-{aid}"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".pulse.json").write_text(json.dumps({
        "id": aid,
        "audience": audience,
        "model": model,
    }, indent=2) + "\n", encoding="utf-8")


def hire_agent(aid: str, name: str = "", title: str = "", soul: str = "", model: str = "", audience: str = ""):
    global _demo_ids
    aid = clean_id(aid)
    if not aid or len(aid) < 2:
        return {"ok": False, "error": "id must be 2–32 letters, numbers, or hyphens"}
    name = (name or aid).strip()[:80] or aid.title()
    title = (title or "").strip()[:120]
    audience = "customer" if str(audience).strip().lower() in ("customer", "navigator", "external") else "internal"
    model_id = resolve_model(model or ("grok" if audience == "customer" else "local"), audience, aid)
    live_ids = {a["id"] for a in (demo_agents() if is_demo() else list_agents())}
    if aid in live_ids:
        return {"ok": False, "error": f"{aid} is already active"}
    if is_demo():
        ids = list(_demo_ids if _demo_ids is not None else NEW_ROSTER)
        if aid not in ids:
            ids.append(aid)
        _demo_ids = ids
        SEAT_TITLE[aid] = title
        return {"ok": True, "id": aid, "name": name, "status": "active", "model": model_id, "audience": audience}
    standby = STANDBY / aid
    if standby.exists():
        return restore_agent(aid)
    ws = write_workspace(aid, name, title, soul, audience=audience)
    added = oc(
        "agents", "add", aid,
        "--workspace", str(ws),
        "--model", model_id,
        "--non-interactive",
        timeout=60,
    )
    oc("agents", "set-identity", "--agent", aid, "--from-identity", "--name", name, timeout=20)
    try:
        apply_seat_policy(aid, model_id, audience)
    except Exception:
        pass
    if str(model_id).startswith("xai") or "grok" in str(model_id).lower():
        try:
            share_xai_auth(aid)
        except Exception:
            pass
    try:
        lib_mod().sync_seats()
    except Exception:
        pass
    return {"ok": True, "id": aid, "name": name, "workspace": str(ws), "add": added, "status": "active", "model": model_id, "audience": audience}


def refresh_seat_files(aid: str):
    src = ROSTER / aid
    ws = OC_HOME / f"workspace-{aid}"
    ws.mkdir(parents=True, exist_ok=True)
    copied = []
    if src.is_dir():
        for name in BOOTSTRAP:
            fp = src / name
            if fp.exists():
                shutil.copy2(fp, ws / name)
                copied.append(name)
    return copied


def ensure_cora():
    try:
        oc("config", "set", "agents.defaults.systemAgent.agentId", "vera", timeout=12)
        oc("config", "set", "agents.defaults.heartbeat.agentId", "vera", timeout=12)
    except Exception:
        pass
    src_av = ROSTER / "cora" / "avatar.jpg"
    dst_av = WWW / "avatars" / "cora.jpg"
    if src_av.exists():
        dst_av.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_av, dst_av)
    live = []
    try:
        live = list_agents()
    except Exception:
        live = []
    mid = pick_grok_model("cora")
    files = refresh_seat_files("cora")
    if any(a.get("id") == "cora" for a in live):
        try:
            apply_seat_policy("cora", mid, "customer")
            share_xai_auth("cora")
        except Exception:
            pass
        seeded = {}
        try:
            import library as lib  # type: ignore
            seeded = lib.seed_bundled()
        except Exception as exc:  # noqa: BLE001
            seeded = {"ok": False, "error": str(exc)}
        return {
            "ok": True, "id": "cora", "status": "already", "model": mid,
            "audience": "customer", "library": seeded, "files": files,
        }
    hired = hire_agent("cora", "Cora", "Customer Relationship Manager", model="grok", audience="customer")
    try:
        import library as lib  # type: ignore
        hired["library"] = lib.seed_bundled()
    except Exception as exc:  # noqa: BLE001
        hired["library"] = {"ok": False, "error": str(exc)}
    return hired


def pin_vera():
    """Vera coordinates Command on Grok 4.20. Other internal seats stay local Qwen."""
    live = []
    try:
        live = list_agents()
    except Exception:
        live = []
    if not any(a.get("id") == "vera" for a in live):
        return {"ok": False, "error": "vera is not on the gateway"}
    mid = pick_grok_model("vera")
    try:
        apply_seat_policy("vera", mid, "internal")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "model": mid}
    try:
        share_xai_auth("vera")
    except Exception:
        pass
    try:
        oc("config", "set", "agents.defaults.systemAgent.agentId", "vera", timeout=12)
        oc("config", "set", "agents.defaults.heartbeat.agentId", "vera", timeout=12)
    except Exception:
        pass
    return {"ok": True, "id": "vera", "model": mid}


def fire_agent(aid: str):
    global _demo_standby
    aid = clean_id(aid)
    if not aid:
        return {"ok": False, "error": "bad id"}
    deleted = delete_agent(aid)
    if is_demo():
        _demo_standby = [x for x in _demo_standby if x["id"] != aid]
        return {"ok": True, "id": aid, "deleted": deleted, "status": "gone"}
    dest = STANDBY / aid
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    return {"ok": True, "id": aid, "deleted": deleted, "status": "gone"}


def wipe_leftover():
    live = demo_agents() if is_demo() else list_agents()
    live_ids = {a["id"] for a in live}
    deleted = []
    for aid in OLD_ROSTER:
        if aid not in live_ids:
            continue
        deleted.append(delete_agent(aid))
    remaining = [a["id"] for a in (demo_agents() if is_demo() else list_agents())]
    return {
        "ok": all(d.get("ok") for d in deleted) if deleted else True,
        "deleted": deleted,
        "remaining": remaining,
    }


def seed_operating():
    global _demo_ids
    if is_demo():
        ids = list(_demo_ids if _demo_ids is not None else OLD_ROSTER)
        for aid in NEW_ROSTER:
            if aid not in ids:
                ids.append(aid)
        _demo_ids = ids
        return {
            "ok": True,
            "created": [{"id": a} for a in NEW_ROSTER],
            "default": "vera",
            "restart": {"ok": True, "stdout": "demo"},
            "agents": demo_agents(),
        }
    created = []
    for aid in NEW_ROSTER:
        created.append({"id": aid, **seed_agent(aid)})
    set_default("vera")
    restart = oc("gateway", "restart", timeout=90)
    return {
        "ok": True,
        "created": created,
        "default": "vera",
        "restart": restart,
        "agents": list_agents(),
    }


def public_url():
    env = (os.environ.get("PULSE_PUBLIC_URL") or "").strip()
    if env.startswith("https://"):
        return env.rstrip("/")
    p = STATE / "public-url"
    if p.exists():
        val = p.read_text(encoding="utf-8").strip()
        if val.startswith("https://"):
            return val.rstrip("/")
    return ""


def openclaw_url():
    env = (os.environ.get("OPENCLAW_PUBLIC_URL") or "").strip()
    if env.startswith("https://"):
        return env.rstrip("/") + "/"
    p = STATE / "openclaw-url"
    if p.exists():
        val = p.read_text(encoding="utf-8").strip()
        if val.startswith("https://"):
            return val.rstrip("/") + "/"
    return "http://127.0.0.1:18789/"


def host_dashboard():
    err = ""
    try:
        import agent as pulse_agent  # type: ignore
        payload = pulse_agent.collect()
        source = "live"
    except Exception as exc:  # noqa: BLE001
        payload = None
        source = "error"
        err = str(exc)
    if not payload:
        return {
            "source": source,
            "overall": "unresponsive",
            "hostname": os.uname().nodename if hasattr(os, "uname") else "ser10",
            "deviceLabel": "Beelink SER10 MAX",
            "os": None,
            "uptimeSeconds": 0,
            "lastSeenAt": utcnow(),
            "heartbeatAgeMs": 0,
            "heartbeatTimeoutSec": 90,
            "stale": True,
            "hardware": {
                "model": "Beelink SER10 MAX",
                "cpu": "AMD Ryzen AI 9 HX 470",
                "npuTops": 50,
                "cpuPercent": 0,
                "npuPercent": 0,
                "ramUsedMb": 0,
                "ramTotalMb": 0,
                "diskUsedGb": 0,
                "diskTotalGb": 0,
                "cpuTempC": 0,
            },
            "tailscale": None,
            "services": [],
            "logs": [{"service": "pulse", "level": "warn", "message": err if payload is None else "no snapshot", "ts": utcnow()}],
            "history": [],
            "publicUrl": public_url(),
        }
    hw = payload.get("hardware") or {}
    services = payload.get("services") or []
    featured_bad = [s for s in services if s.get("kind") == "featured" and s.get("status") not in ("healthy", "ok", "active")]
    overall = "down" if featured_bad else "healthy"
    return {
        "source": "live",
        "overall": overall,
        "hostname": payload.get("hostname"),
        "deviceLabel": "Beelink SER10 MAX",
        "os": payload.get("os"),
        "kernel": payload.get("kernel"),
        "uptimeSeconds": payload.get("uptimeSeconds") or 0,
        "lastSeenAt": payload.get("collectedAt") or utcnow(),
        "heartbeatAgeMs": 0,
        "heartbeatTimeoutSec": 90,
        "stale": False,
        "hardware": hw,
        "tailscale": payload.get("tailscale"),
        "services": services,
        "logs": payload.get("logs") or [],
        "history": history_points(),
        "snapshotCount": len(history_points()),
        "publicUrl": public_url(),
    }


_history: list = []
_hist_lock = threading.Lock()
_recent_logs: list = []


def history_points():
    with _hist_lock:
        return list(_history)


def _load_history():
    global _history
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / "history.json"
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _history = data[-180:]
    except Exception:
        _history = []


def append_history(dash: dict):
    global _recent_logs
    hw = dash.get("hardware") or {}
    ram_t = float(hw.get("ramTotalMb") or 0)
    ram_p = ((hw.get("ramUsedMb") or 0) / ram_t * 100) if ram_t else 0
    point = {
        "t": dash.get("lastSeenAt") or utcnow(),
        "cpu": hw.get("cpuPercent") or 0,
        "ram": round(ram_p, 1),
        "npu": hw.get("npuPercent") or 0,
        "gpu": hw.get("gpuPercent") or 0,
        "temp": hw.get("cpuTempC") or 0,
    }
    with _hist_lock:
        _history.append(point)
        del _history[:-180]
        try:
            (STATE / "history.json").write_text(json.dumps(_history), encoding="utf-8")
        except Exception:
            pass
        logs = dash.get("logs") or []
        if logs:
            _recent_logs = (logs + _recent_logs)[:80]


def sample_once():
    d = host_dashboard()
    append_history(d)
    return d


def sampler_loop():
    while True:
        try:
            sample_once()
        except Exception as exc:  # noqa: BLE001
            log(f"sample {exc}")
        time.sleep(15)


def _usage_payload_bad(data, r=None):
    if r is not None and r.get("ok") is False and data is None:
        return True
    if not isinstance(data, dict):
        return data is None
    if data.get("ok") is False:
        return True
    err = data.get("error")
    if isinstance(err, dict) and (err.get("code") or err.get("message")):
        return True
    if isinstance(err, str) and "session key" in err.lower():
        return True
    return False


def _usage_num(data, *keys):
    blobs = [data]
    if isinstance(data, dict):
        for nested in (data.get("totals"), data.get("summary"), data.get("usage")):
            if isinstance(nested, dict):
                blobs.append(nested)
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        for k in keys:
            if blob.get(k) is None:
                continue
            try:
                return float(blob[k])
            except (TypeError, ValueError):
                continue
    return None


def _fmt_cost(n):
    if n is None:
        return "—"
    if abs(n) < 0.005:
        return "$0.00"
    return f"${n:,.2f}"


def _fmt_tokens(n):
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M tok"
    if n >= 1_000:
        return f"{n/1_000:.1f}k tok"
    return f"{int(n)} tok"


def _summarize_usage(data, aid=""):
    cost = _usage_num(data, "totalCost", "total_cost", "estimatedCost", "costUsd", "cost")
    tokens = _usage_num(data, "totalTokens", "tokens", "total_tokens")
    if tokens is None:
        inp = _usage_num(data, "inputTokens", "promptTokens", "input_tokens", "input")
        out = _usage_num(data, "outputTokens", "completionTokens", "output_tokens", "output")
        if inp is not None or out is not None:
            tokens = (inp or 0) + (out or 0)
    label = aid or "all"
    return {
        "id": label,
        "name": label,
        "cost": cost,
        "tokens": tokens,
        "costLabel": _fmt_cost(cost),
        "tokensLabel": _fmt_tokens(tokens),
        "line": f"{label} · {_fmt_cost(cost)} · {_fmt_tokens(tokens)}",
    }


def _usage_rows_from(data):
    rows = []
    if not isinstance(data, dict):
        return rows
    for key in ("agents", "byAgent", "perAgent", "breakdown"):
        val = data.get(key)
        if isinstance(val, list):
            for row in val:
                if isinstance(row, dict):
                    aid = str(row.get("id") or row.get("agent") or row.get("agentId") or "")
                    rows.append(_summarize_usage(row, aid))
        elif isinstance(val, dict):
            for aid, row in val.items():
                if isinstance(row, dict):
                    rows.append(_summarize_usage(row, str(aid)))
    return [r for r in rows if r.get("id")]


def _usage_for_agent(aid: str):
    for extra in (["--days", "7", "--json"], ["--json"]):
        rr = oc("gateway", "usage-cost", "--agent", aid, *extra, timeout=8)
        dd = parse_json(rr.get("stdout") or "") or parse_json(rr.get("stderr") or "")
        if _usage_payload_bad(dd, rr):
            continue
        got = _summarize_usage(dd, aid)
        got["ok"] = True
        return got
    return {
        "id": aid,
        "name": aid,
        "cost": None,
        "tokens": None,
        "costLabel": "—",
        "tokensLabel": "—",
        "line": f"{aid} · — · —",
        "ok": False,
    }


def usage_cost():
    if is_demo():
        seats = demo_agents()
        rows = [_summarize_usage({"cost": 0, "tokens": 0}, a["id"]) for a in seats]
        for r, a in zip(rows, seats):
            r["name"] = a.get("name") or a["id"]
            r["line"] = f"{r['name']} · {r['costLabel']} · {r['tokensLabel']}"
        return {"ok": True, "demo": True, "summary": "7 days · local Qwen · no cloud bill", "lines": [r["line"] for r in rows], "agents": rows, "days": 7}
    seats = []
    try:
        seats = list_agents()
    except Exception:
        seats = []
    by_id = {}
    r = oc("gateway", "usage-cost", "--all-agents", "--days", "7", "--json", timeout=20)
    data = parse_json(r.get("stdout") or "") or parse_json(r.get("stderr") or "")
    if not _usage_payload_bad(data, r):
        for row in _usage_rows_from(data):
            by_id[row["id"]] = row
    for a in seats:
        aid = a["id"]
        row = by_id.get(aid)
        if row is None or (row.get("cost") is None and row.get("tokens") is None):
            row = _usage_for_agent(aid)
        row["name"] = a.get("name") or aid
        row["model"] = a.get("model") or ""
        row["line"] = f"{row['name']} · {row.get('costLabel') or _fmt_cost(row.get('cost'))} · {row.get('tokensLabel') or _fmt_tokens(row.get('tokens'))}"
        by_id[aid] = row
    rows = [by_id[a["id"]] for a in seats if a["id"] in by_id]
    if not rows and seats:
        rows = [_usage_for_agent(a["id"]) for a in seats]
        for r0, a in zip(rows, seats):
            r0["name"] = a.get("name") or a["id"]
    if not rows:
        err = ""
        if isinstance(data, dict):
            err = ((data.get("error") or {}) if isinstance(data.get("error"), dict) else {}).get("message") or ""
        return {"ok": False, "summary": str(err or "usage-cost unavailable")[:240], "lines": [], "agents": [], "days": 7}

    cost_sum = sum(x["cost"] or 0 for x in rows)
    tok_sum = sum(x["tokens"] or 0 for x in rows)
    known = sum(1 for x in rows if x.get("cost") is not None or x.get("tokens") is not None)
    summary = f"7 days · {_fmt_cost(cost_sum)} · {_fmt_tokens(tok_sum)} · {len(rows)} seats"
    return {
        "ok": True,
        "summary": summary,
        "lines": [x["line"] for x in rows],
        "agents": rows,
        "days": 7,
        "seats": len(rows),
        "reported": known,
    }


USAGE_PERIODS = (("7d", 7), ("30d", 30), ("6m", 180), ("all", 3650))


def _usage_period(aid: str, days: int | None):
    cmd = ["gateway", "usage-cost", "--agent", aid]
    if days:
        cmd += ["--days", str(days)]
    cmd.append("--json")
    rr = oc(*cmd, timeout=10)
    dd = parse_json(rr.get("stdout") or "") or parse_json(rr.get("stderr") or "")
    if _usage_payload_bad(dd, rr):
        return None
    return dd


def _sessions_for(aid: str):
    r = oc("sessions", "--agent", aid, "--json", "--limit", "all", timeout=20)
    data = parse_json(r.get("stdout") or "") or parse_json(r.get("stderr") or "")
    if data is None:
        r = oc("sessions", "--agent", aid, "--json", timeout=20)
        data = parse_json(r.get("stdout") or "") or parse_json(r.get("stderr") or "")
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in ("sessions", "items", "rows", "data"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        if not items and (data.get("sessionKey") or data.get("key")):
            items = [data]
    threads = []
    for it in items:
        if not isinstance(it, dict):
            continue
        key = str(it.get("sessionKey") or it.get("key") or it.get("id") or "")
        if key.endswith(":main") and key.count(":") >= 2:
            # still a thread
            pass
        threads.append({
            "key": key,
            "updated": it.get("updatedAt") or it.get("updated") or it.get("lastActive") or it.get("mtime"),
            "messages": it.get("messageCount") or it.get("messages") or it.get("count"),
            "model": it.get("model") or "",
        })
    return threads


def agent_analytics(aid: str):
    aid = clean_id(aid)
    if not aid:
        return {"ok": False, "error": "bad id"}
    if is_demo():
        return {
            "ok": True,
            "id": aid,
            "periods": [
                {"label": "7d", "cost": 0, "tokens": 0, "costLabel": "$0.00", "tokensLabel": "0 tok"},
                {"label": "30d", "cost": 0, "tokens": 0, "costLabel": "$0.00", "tokensLabel": "0 tok"},
                {"label": "6m", "cost": 0, "tokens": 0, "costLabel": "$0.00", "tokensLabel": "0 tok"},
                {"label": "all", "cost": 0, "tokens": 0, "costLabel": "$0.00", "tokensLabel": "0 tok"},
            ],
            "threads": 0,
            "sessions": [],
            "demo": True,
        }
    periods = []
    for label, days in USAGE_PERIODS:
        data = _usage_period(aid, days)
        if data is None and label == "all":
            data = _usage_period(aid, None)
        row = _summarize_usage(data or {}, aid)
        periods.append({
            "label": label,
            "days": days,
            "cost": row.get("cost"),
            "tokens": row.get("tokens"),
            "costLabel": row.get("costLabel") or "—",
            "tokensLabel": row.get("tokensLabel") or "—",
        })
    sessions = _sessions_for(aid)
    last = ""
    if sessions:
        last = str(sessions[0].get("updated") or "")
    return {
        "ok": True,
        "id": aid,
        "periods": periods,
        "threads": len(sessions),
        "sessions": sessions[:40],
        "lastActive": last,
    }


def lib_mod():
    import library as lib  # type: ignore
    return lib


def reset_roster():
    global _demo_ids, _demo_repaired
    if is_demo():
        _demo_ids = list(NEW_ROSTER)
        return {
            "ok": True,
            "backup": "(demo — no files written)",
            "created": [{"id": a} for a in NEW_ROSTER],
            "deleted": [{"id": a} for a in OLD_ROSTER],
            "default": "vera",
            "restart": {"ok": True, "stdout": "demo"},
            "agents": demo_agents(),
        }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = HOME / f".openclaw-bak-{stamp}"
    if OC_HOME.exists():
        bak.mkdir(parents=True, exist_ok=True)
        for name in ("openclaw.json", "HEARTBEAT.md"):
            src = OC_HOME / name
            if src.exists():
                shutil.copy2(src, bak / name)
        log(f"config backup {bak}")

    created = []
    for aid in NEW_ROSTER:
        created.append({"id": aid, **seed_agent(aid)})

    set_default("vera")

    deleted = []
    for aid in OLD_ROSTER:
        deleted.append({"id": aid, **delete_agent(aid)})

    set_default("vera")
    gw = oc("gateway", "restart", timeout=90)
    return {
        "ok": True,
        "backup": str(bak),
        "created": created,
        "deleted": deleted,
        "default": "vera",
        "restart": gw,
        "agents": list_agents(),
    }


def logs(limit=120):
    if is_demo():
        ts = utcnow()
        return {"ok": True, "path": "/tmp/openclaw/openclaw-2026-09-02.log", "lines": [
            f"{ts} [gateway] OpenClaw {OC_VERSION} listening 127.0.0.1:18789",
            f"{ts} [gateway] systemd user openclaw-gateway.service active (pid 2144)",
            f"{ts} [agents] default=ken model={MODEL} routing=0",
            f"{ts} [doctor] PATH includes nvm; service config looks out of date",
            "On the SER10 this panel tails `openclaw logs` and /tmp/openclaw/*.log",
        ]}
    r = oc("logs", "--plain", "--no-color", "--limit", str(limit), timeout=20)
    text = r["stdout"] or r["stderr"]
    path = ""
    logdir = Path("/tmp/openclaw")
    if not text and logdir.exists():
        latest = sorted(logdir.glob("openclaw-*.log"))
        if latest:
            path = str(latest[-1])
            text = read_text(latest[-1], 80_000)
    lines = [ln for ln in text.splitlines() if ln.strip()][-limit:]
    return {"ok": r["ok"] or bool(lines), "path": path, "lines": lines}


_demo_ids = None  # None → show legacy; after RESET → NEW_ROSTER
_demo_repaired = False


def is_demo():
    if DEMO:
        return True
    resolved = Path(OC) if OC != "openclaw" else Path(shutil.which("openclaw") or "")
    return not resolved.exists()


def _file_pack(aid):
    src = ROSTER / aid
    if src.exists():
        return {k: read_text(src / fname) for k, fname in FILE_KEYS.items()}
    return {
        "soul": f"# {aid}\n\nUnfinished seat. Replace via Roster reset.\n",
        "agents": "Do not use. Reset the roster.\n",
        "identity": f"name: {aid.title()}\ntheme: graphite\nemoji:\n",
        "user": "",
        "tools": "",
        "heartbeat": "HEARTBEAT_OK\n",
        "memory": "",
    }


def demo_agents():
    ids = _demo_ids if _demo_ids is not None else list(OLD_ROSTER)
    out = []
    for aid in ids:
        planned = aid in NEW_ROSTER
        files = _file_pack(aid) if planned else {
            "soul": f"# {aid.title()}\n\nLeftover from the unfinished OpenClaw pass. Will be removed by roster reset.\n",
            "agents": "Do not use. Reset the roster.\n",
            "identity": f"name: {aid.title()}\ntheme: graphite\nemoji:\n",
            "user": "",
            "tools": "",
            "heartbeat": "",
            "memory": "",
        }
        out.append({
            "id": aid,
            "name": aid.title(),
            "title": SEAT_TITLE.get(aid, "Unfinished seat"),
            "workspace": f"~/.openclaw/workspace-{aid}",
            "agentDir": f"~/.openclaw/agents/{aid}/agent",
            "model": MODEL,
            "default": False,
            "routingRules": 0,
            "identityFile": True,
            "files": files,
            "planned": planned,
            "legacy": aid in OLD_ROSTER,
        })
    default_id = "vera" if any(a["id"] == "vera" for a in out) else (out[0]["id"] if out else None)
    for a in out:
        a["default"] = a["id"] == default_id
        a["avatar"] = f"/avatars/{a['id']}.jpg"
        a.setdefault("bindings", [])
    return out


def demo_gateway():
    running = True
    return {
        "ok": running,
        "version": OC_VERSION,
        "Service": "systemd user (enabled)",
        "Runtime": "running (pid 2144, state active, sub running, last exit 0)",
        "Listening": "127.0.0.1:18789, [::1]:18789",
        "Dashboard": "http://127.0.0.1:18789/",
        "Probe": "ok",
        "File logs": "/tmp/openclaw/openclaw-2026-09-02.log",
        "Config (cli)": "~/.openclaw/openclaw.json",
        "Bind": "loopback",
        "_cliOk": True,
        "_cli": "~/.nvm/versions/node/v24.18.0/bin/openclaw",
        "_home": "~/.openclaw",
        "_port": 18789,
        "_pid": 2144,
    }


def demo_doctor():
    findings = [
        {
            "severity": "warning",
            "checkId": "service/config",
            "message": "Service config looks out of date or non-standard.",
            "fixHint": "Run openclaw doctor --repair --yes (user systemd, no sudo).",
        },
        {
            "severity": "warning",
            "checkId": "service/path",
            "message": "Gateway service PATH includes version managers or package managers; recommend a minimal PATH.",
            "path": "/home/primaluxadvisory/.nvm/versions/node/v24.18.0/bin",
            "fixHint": "doctor --repair rewrites the user unit PATH. Do not sudo.",
        },
        {
            "severity": "warning",
            "checkId": "service/node",
            "message": "Gateway service uses Node from a version manager; it can break after upgrades.",
            "path": "/home/primaluxadvisory/.nvm/versions/node/v24.18.0/bin/node",
            "fixHint": "Keep nvm Node pinned, or let doctor --repair snapshot a stable bin path.",
        },
        {
            "severity": "info",
            "checkId": "gateway/bind",
            "message": "Loopback-only gateway; only local clients can connect.",
            "path": "127.0.0.1:18789",
            "fixHint": "Leave loopback. Reach Clawbox over Tailscale if you need another device.",
        },
        {
            "severity": "info",
            "checkId": "capability",
            "message": "Doctor probe is read-only until you run Repair.",
        },
    ]
    if _demo_repaired:
        for f in findings:
            if f["severity"] == "warning":
                f["severity"] = "info"
                f["message"] = "Repaired (demo): " + f["message"]
    return {
        "ok": True,
        "demo": True,
        "version": OC_VERSION,
        "checksRun": 5,
        "findings": findings,
        "recommendation": "openclaw doctor --repair --yes",
        "repaired": _demo_repaired,
    }


def demo_service():
    return {
        "ok": True,
        "demo": True,
        "unit": "openclaw-gateway.service",
        "scope": "user",
        "ActiveState": "active",
        "SubState": "running",
        "MainPID": "2144",
        "FragmentPath": "~/.config/systemd/user/openclaw-gateway.service",
        "Environment": "OPENCLAW_GATEWAY_PORT=18789",
        "ExecStart": "/home/primaluxadvisory/.nvm/versions/node/v24.18.0/bin/node … gateway --port 18789",
        "note": "Do not sudo. OpenClaw is a user systemd service.",
    }


def oc_json(*args, timeout=30):
    r = oc(*args, timeout=timeout)
    data = parse_json(r["stdout"])
    return r, data


def skills_list():
    if is_demo():
        return {"ok": True, "demo": True, "skills": [
            {"name": "web_fetch", "eligible": True, "note": "Public fetch — Scout"},
            {"name": "exec", "eligible": True, "note": "Host commands — founder-gated"},
            {"name": "browser", "eligible": False, "note": "Not configured"},
            {"name": "cron", "eligible": True, "note": "Propose only until founder OK"},
            {"name": "memory", "eligible": True, "note": "Workspace MEMORY.md"},
        ]}
    r, data = oc_json("skills", "list", "--json", timeout=25)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("skills") or data.get("items") or []
    else:
        items = []
    return {"ok": r["ok"], "skills": items, "raw": r["stdout"][:2000] if not items else ""}


def channels_status():
    if is_demo():
        return {"ok": True, "demo": True, "channels": [
            {"id": "telegram", "status": "not configured", "note": "Bind after roster reset if you want a channel per seat."},
            {"id": "whatsapp", "status": "not configured"},
            {"id": "discord", "status": "not configured"},
        ]}
    r, data = oc_json("channels", "status", "--json", timeout=25)
    if isinstance(data, list):
        ch = data
    elif isinstance(data, dict):
        ch = data.get("channels") or data.get("items") or data
    else:
        ch = r["stdout"][:3000]
    return {"ok": r["ok"], "channels": ch, "stderr": r["stderr"][:1000]}


def cron_list():
    if is_demo():
        return {"ok": True, "demo": True, "jobs": []}
    r, data = oc_json("cron", "list", "--json", timeout=25)
    jobs = data if isinstance(data, list) else (data or {}).get("jobs") if isinstance(data, dict) else []
    return {"ok": r["ok"], "jobs": jobs or [], "raw": r["stdout"][:2000] if not jobs else ""}


def _talk_text(r: dict) -> str:
    out = (r.get("stdout") or "").strip()
    err = (r.get("stderr") or "").strip()

    def from_obj(data) -> str:
        if not isinstance(data, dict):
            return ""
        for k in ("final", "text", "reply", "message", "content", "output"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        nested = data.get("result")
        if isinstance(nested, dict):
            got = from_obj(nested)
            if got:
                return got
        for key in ("payloads", "messages"):
            blob = data.get(key)
            if isinstance(blob, dict):
                got = from_obj(blob)
                if got:
                    return got
            if isinstance(blob, list):
                bits = []
                for p in blob:
                    if isinstance(p, str) and p.strip():
                        bits.append(p.strip())
                    elif isinstance(p, dict):
                        bit = p.get("text") or p.get("content") or p.get("final") or ""
                        if isinstance(bit, list):
                            bit = " ".join(
                                str(x.get("text") if isinstance(x, dict) else x).strip()
                                for x in bit
                            )
                        if str(bit).strip():
                            bits.append(str(bit).strip())
                joined = "\n".join(x for x in bits if x).strip()
                if joined:
                    return joined
        ed = data.get("error")
        if isinstance(ed, dict) and ed.get("message"):
            return str(ed["message"])
        if isinstance(ed, str) and ed.strip():
            return ed.strip()
        return ""

    blobs = []
    for raw in (out, err):
        if not raw:
            continue
        parsed = parse_json(raw)
        if parsed is not None:
            blobs.append(parsed)
        for ln in reversed(raw.splitlines()):
            ln = ln.strip()
            if ln.startswith("{") and ln.endswith("}"):
                parsed = parse_json(ln)
                if parsed is not None:
                    blobs.append(parsed)
                    break
    for data in blobs:
        got = from_obj(data)
        if got:
            return got
    text = out or err
    keep = []
    for ln in text.splitlines():
        low = ln.strip().lower()
        if low.startswith("openclaw 20") or low.startswith("docs.openclaw") or low in ("│", "◇", "│"):
            continue
        if "──" in ln and len(ln.strip()) < 8:
            continue
        keep.append(ln)
    return "\n".join(keep).strip() or text


def talk(aid: str, message: str, new_session: bool = False):
    aid = clean_id(aid)
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "empty message", "reply": ""}
    if is_demo():
        replies = {
            "vera": "I have the fleet. Ask a concrete status question.",
            "scout": "Public-source pack only. I will not scrape LinkedIn. Cite URLs or I will not state it as fact.",
            "elena": "Draft only. Founder posts. I will not publish to LinkedIn, Ghost, X, or the site.",
            "grant": "I will not invent a balance. Point me at a receipt, export, or Mercury paste.",
            "marcus": "I map from a founder-dropped CSV. I will not send outreach or invent a relationship.",
            "lens": "Framework / vendor memo. I will not write production code — that is Grok Chat.",
            "cora": "Library only. If it is not in KNOWLEDGE.md I will say so.",
        }
        body = replies.get(aid, f"{aid} is on the roster.")
        return {"ok": True, "demo": True, "reply": f"{body}\n\nYou said: {message}"}
    # Same session the OpenClaw Control UI uses (agent main) unless this is a fresh thread.
    prefix = ("--new-session",) if new_session else ()
    attempts = [
        ("agent", "--agent", aid, *prefix, "--message", message, "--json", "--timeout", "210"),
        ("agent", "--agent", aid, *prefix, "--message", message, "--timeout", "210"),
    ]
    if new_session:
        sid = f"pulse-{int(time.time())}"
        attempts.append(
            ("agent", "--agent", aid, "--session-id", sid, "--message", message, "--json", "--timeout", "210")
        )
    r = {"ok": False, "stdout": "", "stderr": "", "code": 1}
    last_txt = ""
    for args in attempts:
        r = oc(*args, timeout=230)
        txt = _talk_text(r)
        last_txt = txt or last_txt
        blob = (txt + "\n" + (r.get("stderr") or "") + "\n" + (r.get("stdout") or "")).lower()
        if txt and "has no command" not in blob and "unknown option" not in blob:
            if "invalid_request" in blob and "no explicit owner" in blob:
                continue
            if "unknown model" in blob:
                mid = pick_grok_model(aid)
                try:
                    apply_seat_policy(aid, mid, "customer" if aid == "cora" else "internal")
                except Exception:
                    pass
                r = oc(
                    "agent", "--agent", aid, "--model", mid,
                    "--message", message, "--json", "--timeout", "210",
                    timeout=230,
                )
                txt = _talk_text(r) or txt
                last_txt = txt
                blob = txt.lower()
            if "missing-provider-auth" in blob or "no api key found for provider" in blob:
                try:
                    share_xai_auth(aid)
                except Exception:
                    pass
                r = oc(
                    "agent", "--agent", aid, "--model", pick_grok_model(aid),
                    "--message", message, "--json", "--timeout", "210",
                    timeout=230,
                )
                txt = _talk_text(r) or txt
                last_txt = txt
                blob = txt.lower()
                if "no api key" in blob or "missing-provider-auth" in blob:
                    return {
                        "ok": False,
                        "reply": (
                            "xAI OAuth is on another seat, not this one. On the Max run:\n"
                            f"openclaw models auth login --provider xai --method oauth --agent {aid}"
                        ),
                        "code": r.get("code"),
                    }
            return {"ok": True, "reply": last_txt[:8000], "code": r.get("code")}
        if r.get("code") == 124 or "timed out" in (r.get("stderr") or "").lower():
            break
    reply = last_txt[:8000] or "No reply from the gateway. Local Qwen can take over a minute — try again."
    return {
        "ok": bool(last_txt),
        "reply": reply,
        "error": None if last_txt else reply,
        "code": r.get("code"),
    }


def service_status():
    if is_demo():
        return demo_service()
    show = run(
        ["systemctl", "--user", "show", "openclaw-gateway.service",
         "--property=Id,ActiveState,SubState,MainPID,FragmentPath,Description,Environment,ExecStart"],
        timeout=10,
    )
    facts = {}
    for line in (show["stdout"] or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            facts[k] = v
    unit = HOME / ".config/systemd/user/openclaw-gateway.service"
    return {
        "ok": show["ok"],
        "unit": "openclaw-gateway.service",
        "scope": "user",
        **facts,
        "unitText": read_text(unit, 8000) if unit.exists() else "",
        "note": "Do not sudo. OpenClaw is a user systemd service.",
    }


def config_snapshot():
    if is_demo():
        cfg = {
            "gateway": {"bind": "loopback", "port": 18789},
            "agents": {
                "defaults": {"model": MODEL, "workspace": "~/.openclaw/workspace"},
                "entries": {aid: {"workspace": f"~/.openclaw/workspace-{aid}", "model": MODEL, "default": aid == "ken"} for aid in (_demo_ids or OLD_ROSTER)},
            },
        }
        return {
            "ok": True,
            "demo": True,
            "path": "~/.openclaw/openclaw.json",
            "config": cfg,
            "backups": [
                {"name": "openclaw.json.last-good", "bytes": 10975, "mtime": "2026-09-02T11:26:00Z"},
                {"name": "openclaw.json.bak", "bytes": 6649, "mtime": "2026-07-29T11:37:00Z"},
            ],
            "heartbeat": "# HEARTBEAT.md\n\nIf nothing needs the founder, reply HEARTBEAT_OK.\n",
        }
    cfg = load_config()
    return {
        "ok": True,
        "path": str(OC_HOME / "openclaw.json"),
        "config": redact(cfg),
        "backups": config_backups(),
        "heartbeat": read_text(OC_HOME / "HEARTBEAT.md"),
    }


def snapshot():
    demo = is_demo()
    agents = demo_agents() if demo else list_agents()
    gw = demo_gateway() if demo else gateway_status()
    return {
        "ok": True,
        "ts": utcnow(),
        "version": VERSION,
        "openclawVersion": OC_VERSION,
        "cli": "~/.nvm/versions/node/v24.18.0/bin/openclaw" if demo else OC,
        "home": "~/.openclaw" if demo else str(OC_HOME),
        "model": MODEL,
        "gateway": gw,
        "agents": agents,
        "standby": load_standby(),
        "demo": demo,
        "serviceFile": "~/.config/systemd/user/openclaw-gateway.service",
        "logFile": "/tmp/openclaw/openclaw-2026-09-02.log",
        "dashboard": openclaw_url() if not demo else "http://127.0.0.1:18789/",
        "publicUrl": public_url(),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log(fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str))

    def _proxy_openclaw(self):
        u = urlparse(self.path)
        rest = u.path[len("/openclaw"):] or "/"
        if not rest.startswith("/"):
            rest = "/" + rest
        target = f"http://127.0.0.1:18789{rest}"
        if u.query:
            target += "?" + u.query
        if is_demo():
            html = (
                "<!doctype html><meta charset=utf-8><title>OpenClaw</title>"
                "<body style='background:#0c0d0c;color:#e7ebe4;font:14px/1.5 sans-serif;padding:2rem'>"
                "<p>OpenClaw dashboard is loopback-only. On the Max, PrimaLux Pulse reverse-proxies "
                "127.0.0.1:18789 at /openclaw/ so Tailscale can reach the raw UI.</p>"
            )
            self._send(200, html, "text/html; charset=utf-8")
            return
        try:
            req = Request(target, method=self.command)
            if self.command in ("POST", "PUT", "PATCH"):
                n = int(self.headers.get("Content-Length") or 0)
                req.data = self.rfile.read(n) if n else b""
            if self.headers.get("Content-Type"):
                req.add_header("Content-Type", self.headers.get("Content-Type"))
            with urlopen(req, timeout=20) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "text/html; charset=utf-8")
                self._send(resp.status, body, ctype)
        except HTTPError as exc:
            self._send(exc.code, exc.read() or b"", "text/plain; charset=utf-8")
        except URLError as exc:
            self._json({"ok": False, "error": f"OpenClaw gateway unreachable: {exc.reason}"}, 502)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 502)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 18_000_000:
            return {"error": "payload too large"}
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        if path in ("/openclaw", "/openclaw/") or path.startswith("/openclaw/"):
            self._proxy_openclaw()
            return
        if path in ("/", "/index.html"):
            html = (WWW / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path in ("/favicon.ico", "/favicon.svg"):
            svg = WWW / "favicon.svg"
            if svg.is_file():
                self._send(200, svg.read_bytes(), "image/svg+xml")
                return
        if path == "/api/status":
            self._json(snapshot())
            return
        if path == "/api/doctor":
            self._json(demo_doctor() if is_demo() else doctor())
            return
        if path == "/api/logs":
            limit = int((q.get("limit") or ["120"])[0])
            self._json(logs(max(20, min(limit, 500))))
            return
        if path == "/api/skills":
            self._json(skills_list())
            return
        if path == "/api/channels":
            self._json(channels_status())
            return
        if path == "/api/cron":
            self._json(cron_list())
            return
        if path == "/api/config":
            self._json(config_snapshot())
            return
        if path == "/api/service":
            self._json(service_status())
            return
        if path == "/api/dashboard":
            d = host_dashboard()
            if not d.get("logs"):
                d["logs"] = list(_recent_logs)
            self._json(d)
            return
        if path == "/api/usage":
            self._json(usage_cost())
            return
        if path == "/api/library":
            try:
                self._json(lib_mod().snapshot())
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc), "items": [], "presets": []}, 500)
            return
        if path.startswith("/api/agents/") and path.endswith("/analytics"):
            aid = path.split("/")[3]
            try:
                self._json(agent_analytics(aid))
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc), "id": aid, "periods": [], "threads": 0}, 500)
            return
        if path.startswith("/api/agents/") and path.endswith("/files"):
            aid = path.split("/")[3]
            if is_demo():
                a = next((x for x in demo_agents() if x["id"] == aid), None)
                self._json({"id": aid, **(a["files"] if a else {})})
                return
            ws = OC_HOME / f"workspace-{aid}"
            self._json({"id": aid, **{k: read_text(ws / fname) for k, fname in FILE_KEYS.items()}})
            return
        rel = path.lstrip("/")
        fp = (WWW / rel).resolve()
        if str(fp).startswith(str(WWW.resolve())) and fp.is_file():
            ctype = "text/plain"
            if fp.suffix == ".css":
                ctype = "text/css"
            elif fp.suffix == ".js":
                ctype = "application/javascript"
            elif fp.suffix == ".svg":
                ctype = "image/svg+xml"
            elif fp.suffix in (".jpg", ".jpeg"):
                ctype = "image/jpeg"
            elif fp.suffix == ".png":
                ctype = "image/png"
            self._send(200, fp.read_bytes(), ctype)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        global _demo_repaired
        u = urlparse(self.path)
        path = u.path
        body = self._read_json()
        if path == "/api/gateway/restart":
            if is_demo():
                self._json({"ok": True, "stdout": "demo restart"})
                return
            self._json(oc("gateway", "restart", timeout=90))
            return
        if path == "/api/gateway/start":
            if is_demo():
                self._json({"ok": True, "stdout": "demo start"})
                return
            self._json(oc("gateway", "start", timeout=40))
            return
        if path == "/api/gateway/stop":
            if is_demo():
                self._json({"ok": True, "stdout": "demo stop"})
                return
            self._json(oc("gateway", "stop", timeout=40))
            return
        if path == "/api/doctor/fix":
            if is_demo():
                _demo_repaired = True
                self._json({"ok": True, "stdout": "demo doctor --repair --yes", "repaired": True})
                return
            self._json(doctor_repair())
            return
        if path == "/api/heartbeat":
            text = str(body.get("heartbeat") or "")
            if is_demo():
                self._json({"ok": True, "demo": True})
                return
            write_text(OC_HOME / "HEARTBEAT.md", text)
            self._json({"ok": True})
            return
        if path == "/api/talk":
            aid = "".join(ch for ch in str(body.get("agent") or "").lower() if ch.isalnum() or ch == "-")[:32]
            msg = str(body.get("message") or "").strip()[:4000]
            if not aid or not msg:
                self._json({"ok": False, "error": "agent and message required"}, 400)
                return
            self._json(talk(aid, msg, bool(body.get("newSession") or body.get("new_session"))))
            return
        if path == "/api/library":
            try:
                lib = lib_mod()
                if body.get("filename") and (body.get("contentB64") or body.get("text") or body.get("body")):
                    import base64
                    raw = b""
                    if body.get("contentB64"):
                        raw = base64.b64decode(str(body.get("contentB64") or ""), validate=False)
                    else:
                        raw = str(body.get("text") or body.get("body") or "").encode("utf-8")
                    self._json(lib.add_file(str(body.get("filename") or "dropped"), raw, str(body.get("mime") or "")))
                    return
                if body.get("url"):
                    self._json(lib.add_url(str(body.get("url") or ""), str(body.get("title") or "")))
                    return
                if body.get("text") or body.get("body"):
                    self._json(lib.add_text(str(body.get("title") or "Journey / note"), str(body.get("text") or body.get("body") or "")))
                    return
                self._json({"ok": False, "error": "url or text required"}, 400)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/library/preset":
            try:
                self._json(lib_mod().add_preset(str(body.get("id") or "")))
            except Exception as ext:  # noqa: BLE001
                self._json({"ok": False, "error": str(ext)}, 500)
            return
        if path == "/api/library/sync":
            try:
                self._json(lib_mod().sync_seats())
            except Exception as ext:  # noqa: BLE001
                self._json({"ok": False, "error": str(ext)}, 500)
            return
        if path == "/api/roster/reset":
            if (body.get("confirm") or "") != "RESET":
                self._json({"ok": False, "error": "type RESET to confirm"}, 400)
                return
            try:
                self._json(reset_roster())
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/agents/leftover":
            self._json(wipe_leftover())
            return
        if path.startswith("/api/agents/") and path.endswith("/identity"):
            aid = path.split("/")[3]
            self._json(update_identity(aid, str(body.get("name") or ""), str(body.get("title") or "")))
            return
        if path == "/api/roster/hire":
            self._json(hire_agent(
                str(body.get("id") or ""),
                str(body.get("name") or ""),
                str(body.get("title") or ""),
                str(body.get("soul") or ""),
                str(body.get("model") or ""),
                str(body.get("audience") or ""),
            ))
            return
        if path == "/api/roster/retire":
            self._json(retire_agent(str(body.get("id") or "")))
            return
        if path == "/api/roster/restore":
            self._json(restore_agent(str(body.get("id") or "")))
            return
        if path == "/api/roster/fire":
            self._json(fire_agent(str(body.get("id") or "")))
            return
        if path == "/api/roster/seed":
            self._json(seed_operating())
            return
        if path == "/api/agents" and body.get("id"):
            aid = "".join(ch for ch in str(body["id"]).lower() if ch.isalnum() or ch == "-")[:32]
            if is_demo():
                self._json({"ok": True, "id": aid, "demo": True})
                return
            self._json(seed_agent(aid) | {"id": aid})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] == "default":
            set_default(parts[2])
            agents = demo_agents() if is_demo() else list_agents()
            if is_demo():
                for a in agents:
                    a["default"] = a["id"] == parts[2]
            self._json({"ok": True, "default": parts[2], "agents": agents})
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] == "files":
            aid = parts[2]
            if is_demo():
                self._json({"ok": True, "saved": [FILE_KEYS[k] for k in body if k in FILE_KEYS], "demo": True})
                return
            ws = OC_HOME / f"workspace-{aid}"
            saved = []
            for key, fname in FILE_KEYS.items():
                if key in body and isinstance(body[key], str):
                    write_text(ws / fname, body[key])
                    saved.append(fname)
            if "identity" in body:
                oc("agents", "set-identity", "--agent", aid, "--from-identity", timeout=20)
            self._json({"ok": True, "saved": saved})
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] == "bind":
            bind = str(body.get("bind") or "").strip()
            if not bind:
                self._json({"ok": False, "error": "bind required"}, 400)
                return
            if is_demo():
                self._json({"ok": True, "agent": parts[2], "bind": bind, "demo": True})
                return
            self._json(oc("agents", "bind", "--agent", parts[2], "--bind", bind, timeout=20))
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "library" and parts[3] in ("delete", "remove"):
            try:
                self._json(lib_mod().delete_item(parts[2]))
            except Exception as ext:  # noqa: BLE001
                self._json({"ok": False, "error": str(ext)}, 500)
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] in ("delete", "remove"):
            r = delete_agent(parts[2])
            self._json(r, 200 if r.get("ok") else 400)
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] == "unbind":
            bind = str(body.get("bind") or "").strip()
            if is_demo():
                self._json({"ok": True, "agent": parts[2], "unbind": bind, "demo": True})
                return
            self._json(oc("agents", "unbind", "--agent", parts[2], "--bind", bind, timeout=20))
            return
        if path == "/api/config/set":
            key = str(body.get("key") or "")
            val = str(body.get("value") or "")
            if is_demo():
                self._json({"ok": True, "demo": True, "key": key})
                return
            self._json(oc("config", "set", key, val, timeout=15))
            return
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "library":
            try:
                self._json(lib_mod().delete_item(parts[2]))
            except Exception as ext:  # noqa: BLE001
                self._json({"ok": False, "error": str(ext)}, 500)
            return
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "agents":
            r = delete_agent(parts[2])
            self._json(r, 200 if r.get("ok") else 400)
            return
        if u.path == "/api/agents/leftover":
            self._json(wipe_leftover())
            return
        self._json({"error": "not found"}, 404)


def main():
    if "--ensure-cora" in sys.argv:
        print(json.dumps(ensure_cora(), default=str))
        return
    if "--pin-vera" in sys.argv:
        print(json.dumps(pin_vera(), default=str))
        return
    WWW.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    _load_history()
    threading.Thread(target=sampler_loop, name="pulse-sample", daemon=True).start()
    log(f"cli={OC} home={OC_HOME} www={WWW} version={VERSION}")
    try:
        httpd = Server((BIND, PORT), Handler)
    except OSError as exc:
        log(f"cannot bind {BIND}:{PORT} — {exc}")
        raise SystemExit(1) from exc
    log(f"listening {BIND}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


if __name__ == "__main__":
    main()
