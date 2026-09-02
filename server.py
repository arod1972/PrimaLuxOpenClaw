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

HERE = Path(__file__).resolve().parent
WWW = Path(os.environ.get("CLAWBOX_WWW", str(HERE / "www")))
ROSTER = Path(os.environ.get("CLAWBOX_ROSTER", str(HERE / "roster")))
HOME = Path(os.environ.get("HOME") or str(Path.home()))
OC_HOME = Path(os.environ.get("OPENCLAW_STATE_DIR", str(HOME / ".openclaw")))
PORT = int(os.environ.get("CLAWBOX_PORT", "18791"))
BIND = os.environ.get("CLAWBOX_BIND", "0.0.0.0")
MODEL = os.environ.get("CLAWBOX_MODEL", "local-qwen/qwen-9b-q4-local")
DEMO = os.environ.get("CLAWBOX_DEMO", "").lower() in ("1", "true", "yes")

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
}


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
            env={**os.environ, "PATH": f"{Path(OC).parent}:{os.environ.get('PATH','')}"},
        )
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "code": 127, "stdout": "", "stderr": "openclaw CLI not found"}
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
        # Fallback: filesystem
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
    # Enrich from disk
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
        files = {
            "soul": read_text(ws / "SOUL.md"),
            "agents": read_text(ws / "AGENTS.md"),
            "identity": read_text(ws / "IDENTITY.md"),
            "memory": read_text(ws / "MEMORY.md"),
        }
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
    for name in ("SOUL.md", "AGENTS.md", "IDENTITY.md"):
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
    # add is ok if it already exists
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
    # also try CLI in case schema differs
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
    global _demo_ids
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
        # copy config + identity only, not full agent sqlite dumps if huge
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

    # leftover default ken in config
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
        return {"ok": True, "lines": [
            f"{utcnow()} demo mode — no OpenClaw CLI on this box",
            "On the SER10 this panel tails `openclaw logs` and /tmp/openclaw/*.log",
        ]}
    r = oc("logs", "--plain", "--no-color", "--limit", str(limit), timeout=20)
    text = r["stdout"] or r["stderr"]
    if not text:
        latest = sorted((Path("/tmp/openclaw")).glob("openclaw-*.log")) if Path("/tmp/openclaw").exists() else []
        if latest:
            text = read_text(latest[-1], 80_000)
    lines = [ln for ln in text.splitlines() if ln.strip()][-limit:]
    return {"ok": r["ok"] or bool(lines), "lines": lines}


_demo_ids = None  # None → show legacy; after RESET → NEW_ROSTER


def is_demo():
    if DEMO:
        return True
    resolved = Path(OC) if OC != "openclaw" else Path(shutil.which("openclaw") or "")
    return not resolved.exists()


def _file_pack(aid):
    src = ROSTER / aid
    if src.exists():
        return {
            "soul": read_text(src / "SOUL.md"),
            "agents": read_text(src / "AGENTS.md"),
            "identity": read_text(src / "IDENTITY.md"),
            "memory": "",
        }
    return {
        "soul": f"# {aid}\n\nUnfinished seat. Replace via Roster reset.\n",
        "agents": "",
        "identity": f"name: {aid.title()}\n",
        "memory": "",
    }


def demo_agents():
    ids = _demo_ids if _demo_ids is not None else list(OLD_ROSTER)
    out = []
    for i, aid in enumerate(ids):
        planned = aid in NEW_ROSTER
        files = _file_pack(aid) if planned else _file_pack("vera")
        if not planned:
            files = {
                "soul": f"# {aid.title()}\n\nLeftover from the unfinished OpenClaw pass. Will be removed by roster reset.\n",
                "agents": "Do not use. Reset the roster.\n",
                "identity": f"name: {aid.title()}\n",
                "memory": "",
            }
        out.append({
            "id": aid,
            "name": aid.title(),
            "title": SEAT_TITLE.get(aid, "Unfinished seat"),
            "workspace": f"~/.openclaw/workspace-{aid}",
            "agentDir": f"~/.openclaw/agents/{aid}/agent",
            "model": MODEL,
            "default": aid == (ids[0] if not planned else "vera") and (aid == "ken" or aid == "vera"),
            "routingRules": 0,
            "identityFile": True,
            "files": files,
            "planned": planned,
            "legacy": aid in OLD_ROSTER,
        })
    if any(a["id"] == "vera" for a in out):
        for a in out:
            a["default"] = a["id"] == "vera"
    elif out:
        out[0]["default"] = True
    return out


def oc_json(*args, timeout=30):
    r = oc(*args, timeout=timeout)
    data = parse_json(r["stdout"])
    return r, data


def skills_list():
    if is_demo():
        return {"ok": True, "demo": True, "skills": [
            {"name": "web_fetch", "eligible": True},
            {"name": "exec", "eligible": True},
            {"name": "browser", "eligible": False},
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
        return {"ok": True, "demo": True, "channels": [{"id": "telegram", "status": "not configured"}]}
    r, data = oc_json("channels", "status", "--json", timeout=25)
    return {"ok": r["ok"], "data": data if data is not None else r["stdout"][:3000], "stderr": r["stderr"][:1000]}


def cron_list():
    if is_demo():
        return {"ok": True, "demo": True, "jobs": []}
    r, data = oc_json("cron", "list", "--json", timeout=25)
    jobs = data if isinstance(data, list) else (data or {}).get("jobs") if isinstance(data, dict) else []
    return {"ok": r["ok"], "jobs": jobs or [], "raw": r["stdout"][:2000] if not jobs else ""}


def talk(aid: str, message: str):
    if is_demo():
        return {
            "ok": True,
            "demo": True,
            "reply": f"[demo] {aid} would answer here on the Max via `openclaw agent --agent {aid}`.\n\nYou said: {message}",
        }
    r = oc("agent", "--agent", aid, message, timeout=90)
    if not r["ok"] and "unknown" in (r["stderr"] + r["stdout"]).lower():
        r = oc("message", "send", "--agent", aid, "--message", message, timeout=90)
    return {
        "ok": r["ok"],
        "reply": (r["stdout"] or r["stderr"] or "")[:8000],
        "code": r["code"],
    }


def snapshot():
    demo = is_demo()
    agents = demo_agents() if demo else list_agents()
    gw = {
        "ok": True,
        "Runtime": "demo (no CLI)",
        "Listening": "preview",
        "_cliOk": True,
    } if demo else gateway_status()
    return {
        "ok": True,
        "ts": utcnow(),
        "cli": OC,
        "home": str(OC_HOME),
        "model": MODEL,
        "gateway": gw,
        "agents": agents,
        "planned": list(NEW_ROSTER),
        "legacy": list(OLD_ROSTER),
        "titles": SEAT_TITLE,
        "demo": demo,
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
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str))

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
        if path in ("/", "/index.html"):
            html = (WWW / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self._json(snapshot())
            return
        if path == "/api/doctor":
            if is_demo():
                self._json({"ok": True, "demo": True, "findings": [
                    {"severity": "warning", "message": "Demo preview — doctor runs on the SER10 against the real gateway."}
                ]})
                return
            self._json(doctor())
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
        if path.startswith("/api/agents/") and path.endswith("/files"):
            aid = path.split("/")[3]
            ws = OC_HOME / f"workspace-{aid}"
            self._json({
                "id": aid,
                "soul": read_text(ws / "SOUL.md"),
                "agents": read_text(ws / "AGENTS.md"),
                "identity": read_text(ws / "IDENTITY.md"),
                "memory": read_text(ws / "MEMORY.md"),
            })
            return
        # static
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
            self._send(200, fp.read_bytes(), ctype)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
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
                self._json({"ok": True, "stdout": "demo doctor --fix"})
                return
            self._json(oc("doctor", "--fix", "--yes", timeout=90))
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
            self._json(seed_agent(aid) | {"id": aid})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] == "default":
            set_default(parts[2])
            self._json({"ok": True, "default": parts[2], "agents": list_agents()})
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "agents" and parts[3] == "files":
            aid = parts[2]
            ws = OC_HOME / f"workspace-{aid}"
            mapping = {"soul": "SOUL.md", "agents": "AGENTS.md", "identity": "IDENTITY.md", "memory": "MEMORY.md"}
            saved = []
            for key, fname in mapping.items():
                if key in body and isinstance(body[key], str):
                    write_text(ws / fname, body[key])
                    saved.append(fname)
            if "identity" in body:
                oc("agents", "set-identity", "--agent", aid, "--from-identity", timeout=20)
            self._json({"ok": True, "saved": saved})
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
    log(f"cli={OC} home={OC_HOME} www={WWW}")
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
