#!/usr/bin/env python3
"""Clawbox — local GUI to manage OpenClaw on the SER10 Max."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
BIND = os.environ.get("CLAWBOX_BIND", "0.0.0.0")
MODEL = os.environ.get("CLAWBOX_MODEL", "local-qwen/qwen-9b-q4-local")
DEMO = os.environ.get("CLAWBOX_DEMO", "").lower() in ("1", "true", "yes")
VERSION = "1.2.0"
OC_VERSION = "2026.7.1-2"

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
    r = oc("gateway", "status", "--json", timeout=20)
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


def doctor():
    r = oc("doctor", "--json", timeout=60)
    data = parse_json(r["stdout"])
    if data is None:
        return {"ok": r["ok"], "raw": (r["stdout"] or r["stderr"])[:4000], "findings": []}
    return data


def doctor_repair():
    r = oc("doctor", "--repair", "--yes", "--non-interactive", timeout=120)
    if not r["ok"] and "unknown" in (r["stderr"] + r["stdout"]).lower():
        r = oc("doctor", "--fix", "--yes", timeout=120)
    return r


def list_agents():
    r = oc("agents", "list", "--bindings", "--json", timeout=20)
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
        files = {k: read_text(ws / fname) for k, fname in FILE_KEYS.items()}
        out.append({
            "id": aid,
            "name": a.get("name") or aid.title(),
            "title": SEAT_TITLE.get(aid, a.get("identity") or ""),
            "workspace": str(ws),
            "agentDir": str(a.get("agentDir") or OC_HOME / "agents" / aid / "agent"),
            "model": a.get("model") or a.get("Model") or MODEL,
            "default": bool(a.get("default") or a.get("isDefault")),
            "routingRules": a.get("routingRules") or a.get("bindings") or 0,
            "identityFile": True,
            "files": files,
            "planned": aid in NEW_ROSTER,
            "legacy": aid in OLD_ROSTER,
        })
    cfg = load_config()
    entries = ((cfg.get("agents") or {}).get("entries") or {})
    for a in out:
        ent = entries.get(a["id"]) or {}
        if ent.get("default"):
            a["default"] = True
        if ent.get("model"):
            if isinstance(ent["model"], str):
                a["model"] = ent["model"]
            elif isinstance(ent["model"], dict):
                a["model"] = ent["model"].get("primary") or a["model"]
    return out


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


def delete_agent(aid: str):
    global _demo_ids
    if is_demo():
        ids = list(_demo_ids if _demo_ids is not None else OLD_ROSTER)
        _demo_ids = [x for x in ids if x != aid]
        return {"ok": True, "stdout": "demo delete", "code": 0, "stderr": ""}
    r = oc("agents", "delete", aid, "--force", timeout=30)
    return r


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


def talk(aid: str, message: str):
    if is_demo():
        replies = {
            "vera": "Status: leftover roster still in place until you type RESET.\nDecision needed: replace Ken + ten with Vera (default) and five specialists.\nNext: Roster → type RESET. I will not send, post, or contact anyone.",
            "scout": "Public-source pack only. I will not scrape LinkedIn. Cite URLs or I will not state it as fact.",
            "elena": "Draft only. Founder posts. I will not publish to LinkedIn, Ghost, X, or the site.",
            "grant": "I will not invent a balance. Point me at a receipt, export, or Mercury paste.",
            "marcus": "I map from a founder-dropped CSV. I will not send outreach or invent a relationship.",
            "lens": "Framework / vendor memo. I will not write production code — that is Grok Chat.",
        }
        body = replies.get(aid, f"{aid} is a leftover seat. Reset the roster before using it.")
        return {"ok": True, "demo": True, "reply": f"{body}\n\nYou said: {message}"}
    r = oc("agent", "--agent", aid, message, timeout=90)
    if not r["ok"] and "unknown" in (r["stderr"] + r["stdout"]).lower():
        r = oc("message", "send", "--agent", aid, "--message", message, timeout=90)
    return {
        "ok": r["ok"],
        "reply": (r["stdout"] or r["stderr"] or "")[:8000],
        "code": r["code"],
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
        "planned": list(NEW_ROSTER),
        "legacy": list(OLD_ROSTER),
        "titles": SEAT_TITLE,
        "demo": demo,
        "serviceFile": "~/.config/systemd/user/openclaw-gateway.service",
        "logFile": "/tmp/openclaw/openclaw-2026-09-02.log",
        "dashboard": "http://127.0.0.1:18789/",
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
                "<p>OpenClaw dashboard is loopback-only. On the Max, Pulse reverse-proxies "
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
            self._json(talk(aid, msg))
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
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "agents":
            self._json(delete_agent(parts[2]) | {"id": parts[2]})
            return
        self._json({"error": "not found"}, 404)


def main():
    WWW.mkdir(parents=True, exist_ok=True)
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
