#!/usr/bin/env python3
"""Pulse collector — auto-start on the SER10 Max and POST heartbeats."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PULSE_URL = os.environ.get("PULSE_URL", "").rstrip("/")
PULSE_TOKEN = os.environ.get("PULSE_TOKEN", "")
INTERVAL = int(os.environ.get("PULSE_INTERVAL", "15"))
HOSTNAME = os.environ.get("PULSE_HOSTNAME") or socket.gethostname()

FEATURED = ("openclaw", "talktrack", "llama", "ollama", "tailscale", "pulse", "qwen")
SYSTEM = (
    "ssh",
    "sshd",
    "systemd-resolved",
    "NetworkManager",
    "cron",
    "docker",
    "ufw",
    "systemd-timesyncd",
    "bluetooth",
    "tailscaled",
)


def run(cmd, timeout=4):
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return ""


def meminfo():
    info = {}
    for line in read_text("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        info[k] = v.strip()

    def kb(key):
        try:
            return int(info.get(key, "0").split()[0])
        except Exception:
            return 0

    total = kb("MemTotal") // 1024
    avail = kb("MemAvailable") // 1024
    swap_t = kb("SwapTotal") // 1024
    swap_f = kb("SwapFree") // 1024
    return {
        "ramTotalMb": total,
        "ramUsedMb": max(0, total - avail),
        "swapUsedMb": max(0, swap_t - swap_f),
    }


def cpu_percent(sample=0.15):
    def snap():
        parts = read_text("/proc/stat").splitlines()[0].split()[1:]
        nums = [int(x) for x in parts]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return idle, sum(nums)

    i1, t1 = snap()
    time.sleep(sample)
    i2, t2 = snap()
    dt = max(1, t2 - t1)
    return round(max(0, min(100, (1 - (i2 - i1) / dt) * 100)), 1)


def disk():
    code, out, _ = run(["df", "-B1G", "/"])
    if code != 0:
        return {"diskTotalGb": 0, "diskUsedGb": 0}
    lines = [ln for ln in out.splitlines() if ln.startswith("/")]
    if not lines and len(out.splitlines()) > 1:
        lines = out.splitlines()[1:]
    cols = lines[0].split() if lines else []
    try:
        return {"diskTotalGb": int(cols[1]), "diskUsedGb": int(cols[2])}
    except Exception:
        return {"diskTotalGb": 0, "diskUsedGb": 0}


def cpu_temp():
    best = None
    for p in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            v = int(p.read_text().strip()) / 1000.0
            if 20 < v < 120:
                best = v if best is None else max(best, v)
        except Exception:
            continue
    if best is None:
        code, out, _ = run(["sensors", "-j"], timeout=3)
        if code == 0 and out:
            try:
                data = json.loads(out)
                for node in data.values():
                    if not isinstance(node, dict):
                        continue
                    for k, v in node.items():
                        if isinstance(v, dict) and "temp1_input" in v:
                            best = float(v["temp1_input"])
            except Exception:
                pass
    return round(best or 0)


def uptime_seconds():
    try:
        return int(float(read_text("/proc/uptime").split()[0]))
    except Exception:
        return 0


def os_info():
    pretty = ""
    for line in read_text("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty = line.split("=", 1)[1].strip().strip('"')
    kernel = read_text("/proc/version").split(" ")[2] if read_text("/proc/version") else ""
    return pretty, kernel


def listening_ports():
    ports = {}
    code, out, _ = run(["ss", "-tlnp"], timeout=3)
    if code != 0:
        return ports
    for line in out.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 4:
            continue
        local = cols[3]
        if ":" not in local:
            continue
        try:
            port = int(local.rsplit(":", 1)[-1])
        except Exception:
            continue
        proc = ""
        if "users:" in line:
            proc = line.split("users:(")[-1][:80]
        ports[port] = proc
    return ports


def unit_status(unit):
    code, out, _ = run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "MainPID", "-p", "SubState", "-p", "Description", "-p", "ActiveEnterTimestampMonotonic"])
    fields = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v
    active = fields.get("ActiveState", "unknown")
    pid = int(fields.get("MainPID") or 0)
    status = "healthy" if active == "active" else ("degraded" if active == "activating" else "down")
    return {
        "unit": unit,
        "status": status,
        "pid": pid or None,
        "detail": fields.get("SubState") or active,
        "name": fields.get("Description") or unit.replace(".service", ""),
    }


def discover_units():
    code, out, _ = run(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager"], timeout=6)
    names = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0] if parts[0] != "●" else (parts[1] if len(parts) > 1 else "")
        if unit.endswith(".service"):
            names.append(unit)
    return names


def classify(unit):
    n = unit.lower()
    if any(p in n for p in FEATURED):
        return "featured"
    if any(p in n for p in (s.lower() for s in SYSTEM)):
        return "system"
    return None


def health_probe(port, path="/"):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, True
    except Exception:
        return 0, False


LOG_NOISE = (
    "drmmodeatomiccommit",
    "cursor update failed",
    "xdg-desktop-portal",
    "gsd-color",
    "gsd-power",
    "pipewire",
    "wireplumber",
    "meta_window",
    "stack_position",
    "gnome-shell",
    "mutter",
    "at-spi2",
)


def _journal_noise(ident: str, msg: str) -> bool:
    blob = f"{ident} {msg}".lower()
    return any(n in blob for n in LOG_NOISE)


def journal_errors():
    logs = []
    cmds = (
        ["journalctl", "--user", "-p", "warning", "--since", "15 min ago", "-n", "40", "-o", "json", "--no-pager"],
        ["journalctl", "-p", "err", "--since", "15 min ago", "-n", "30", "-o", "json", "--no-pager"],
    )
    out = ""
    for cmd in cmds:
        code, out, _ = run(cmd, timeout=5)
        if code == 0 and out.strip():
            break
        out = ""
    if not out:
        return logs
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = str(obj.get("MESSAGE") or "")[:500]
        ident = str(obj.get("SYSLOG_IDENTIFIER") or obj.get("_SYSTEMD_UNIT") or "journal")
        if _journal_noise(ident, msg):
            continue
        ts = obj.get("__REALTIME_TIMESTAMP")
        iso = datetime.now(timezone.utc).isoformat()
        if ts:
            try:
                iso = datetime.fromtimestamp(int(ts) / 1_000_000, tz=timezone.utc).isoformat()
            except Exception:
                pass
        logs.append({"ts": iso, "service": ident.replace(".service", "")[:80], "level": "error", "message": msg})
    return logs


def tailscale():
    if not shutil.which("tailscale"):
        return None
    code, out, _ = run(["tailscale", "status", "--json"], timeout=4)
    if code != 0:
        return {"status": "down"}
    try:
        data = json.loads(out)
    except Exception:
        return {"status": "unknown"}
    self = data.get("Self") or {}
    addrs = self.get("TailscaleIPs") or []
    return {
        "status": "up" if data.get("BackendState") == "Running" else str(data.get("BackendState") or "down").lower(),
        "ip": addrs[0] if addrs else None,
        "hostname": self.get("HostName") or HOSTNAME,
        "relay": "direct" if not self.get("Relay") else self.get("Relay"),
    }


def gpu_percent():
    # AMD iGPU via sysfs busy percent when present (Ryzen AI 9 HX).
    for p in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
        try:
            v = float(p.read_text().strip())
            if 0 <= v <= 100:
                return round(v, 1)
        except Exception:
            continue
    return 0


def npu_percent():
    for p in Path("/sys/class/accel").glob("accel*/device/npu_busy_percent"):
        try:
            v = float(p.read_text().strip())
            if 0 <= v <= 100:
                return round(v, 1)
        except Exception:
            continue
    return 0


KNOWN_PORTS = (
    ("openclaw-gateway", "OpenClaw Gateway", (18789, 18790)),
    ("talktrack", "TalkTrack", (443, 8765, 8443)),
    ("llama-cpp", "Local LLM", (8088,)),
    ("ollama", "Ollama", (11434,)),
    ("qwen", "Qwen", (8000, 8001)),
)


def already_named(services, sid):
    key = sid.lower()
    for s in services:
        blob = f"{s.get('id','')} {s.get('name','')}".lower()
        if key in blob:
            return True
    return False


def ensure_known_ports(services, seen, ports):
    """Surface featured stacks that listen but have no matching systemd unit."""
    for sid, name, candidates in KNOWN_PORTS:
        if already_named(services, sid):
            continue
        port = next((p for p in candidates if p in ports), None)
        if port is None:
            continue
        _code, ok = health_probe(port, "/")
        services.append({
            "id": sid,
            "name": name,
            "kind": "featured",
            "status": "healthy" if ok else "down",
            "port": port,
            "detail": "listening" if ok else "port bound but health probe timed out",
        })
        seen.add(sid)


def collect():
    ports = listening_ports()
    units = discover_units()
    services = []
    seen = set()
    for unit in units:
        kind = classify(unit)
        if not kind:
            continue
        st = unit_status(unit)
        sid = unit.replace(".service", "")
        if sid in seen:
            continue
        seen.add(sid)
        port = None
        for p, proc in ports.items():
            if sid.split("-")[0] in proc.lower() or sid.lower() in proc.lower():
                port = p
                break
        # Known ports
        if "openclaw" in sid and 18789 in ports:
            port = 18789
        if "talktrack" in sid and 8765 in ports:
            port = 8765
        detail = st["detail"]
        status = st["status"]
        if "openclaw" in sid and port:
            code, ok = health_probe(port, "/")
            if not ok:
                status = "down"
                detail = "port bound but health probe timed out"
        services.append({
            "id": sid,
            "name": st["name"],
            "kind": kind,
            "status": status,
            "unit": unit,
            "pid": st["pid"],
            "port": port,
            "detail": detail,
        })

    ts = tailscale()
    if ts and "tailscale" not in seen and "tailscaled" not in seen:
        services.append({
            "id": "tailscale",
            "name": "Tailscale",
            "kind": "featured",
            "status": "healthy" if ts.get("status") == "up" else "down",
            "unit": "tailscaled.service",
            "detail": ts.get("ip") or ts.get("status"),
        })

    ensure_known_ports(services, seen, ports)

    pretty, kernel = os_info()
    hw = {
        "model": os.environ.get("PULSE_MODEL", "Beelink SER10 MAX"),
        "cpu": os.environ.get("PULSE_CPU", "AMD Ryzen AI 9 HX 470"),
        "npuTops": int(os.environ.get("PULSE_NPU_TOPS", "50")),
        "cpuPercent": cpu_percent(),
        "npuPercent": npu_percent(),
        "gpuPercent": gpu_percent(),
        "cpuTempC": cpu_temp(),
        **meminfo(),
        **disk(),
    }
    return {
        "hostname": HOSTNAME,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "uptimeSeconds": uptime_seconds(),
        "os": pretty,
        "kernel": kernel,
        "hardware": hw,
        "tailscale": ts,
        "services": services,
        "logs": journal_errors(),
    }


def vulkan_report():
    info = {"ok": False, "device": "", "detail": ""}
    if shutil.which("vulkaninfo"):
        code, out, err = run(["vulkaninfo", "--summary"], timeout=8)
        blob = f"{out}\n{err}"
        info["detail"] = blob[:800]
        low = blob.lower()
        if "amd" in low or "radv" in low or "890m" in low or "gfx1" in low:
            info["ok"] = True
            for ln in blob.splitlines():
                if any(k in ln.lower() for k in ("device name", "gpu", "890m", "radeon")):
                    info["device"] = ln.strip()[:120]
                    break
            if not info["device"]:
                info["device"] = "AMD Vulkan"
        elif code == 0:
            info["ok"] = True
            info["device"] = "Vulkan present"
        return info
    code, out, _ = run(["lspci"], timeout=5)
    if "890m" in (out or "").lower() or "radeon" in (out or "").lower():
        info["ok"] = True
        info["device"] = "Radeon (vulkaninfo not installed)"
        info["detail"] = "Install mesa-vulkan-drivers vulkan-tools for a full probe."
        return info
    info["detail"] = "vulkaninfo not found; install mesa-vulkan-drivers vulkan-tools"
    return info


def _pid_unit(pid: str):
    for user in (True, False):
        cmd = ["systemctl"] + (["--user"] if user else []) + ["status", pid, "--no-pager"]
        code, out, _ = run(cmd, timeout=5)
        if code != 0 or "Loaded:" not in out:
            continue
        for ln in out.splitlines():
            if ".service" in ln and ("loaded" in ln.lower() or ln.strip().startswith("●") or ln.strip()[0:1].isdigit()):
                for tok in ln.replace("●", " ").split():
                    if tok.endswith(".service"):
                        return {"unit": tok, "user": user}
        # first line often: "● qwen.service - ..."
        head = out.splitlines()[0] if out.splitlines() else ""
        for tok in head.replace("●", " ").split():
            if tok.endswith(".service"):
                return {"unit": tok, "user": user}
    return None


def _units_from_ports():
    extra = []
    code, out, _ = run(["ss", "-lntp"], timeout=6)
    if code != 0:
        code, out, _ = run(["ss", "-ltnp"], timeout=6)
    for ln in (out or "").splitlines():
        if not any(p in ln for p in (":8000", ":8001", ":8080", ":8088")):
            continue
        # users:(("llama-server",pid=2144,fd=3))
        if "pid=" not in ln:
            continue
        pid = ln.split("pid=", 1)[1].split(",", 1)[0].split(")", 1)[0]
        mapped = _pid_unit(pid)
        if mapped:
            extra.append(mapped)
    return extra


def _llm_units():
    found = []
    keys = ("llama", "qwen", "llamacpp", "llama-server", "llama.cpp")
    for user in (True, False):
        cmd = ["systemctl"] + (["--user"] if user else []) + [
            "list-units", "--type=service", "--all", "--no-legend", "--no-pager",
        ]
        code, out, _ = run(cmd, timeout=6)
        if code != 0:
            continue
        for line in out.splitlines():
            parts = line.split()
            if not parts:
                continue
            unit = parts[0] if parts[0] != "●" else (parts[1] if len(parts) > 1 else "")
            if not unit.endswith(".service"):
                continue
            low = unit.lower()
            if any(k in low for k in keys):
                found.append({"unit": unit, "user": user})
    found.extend(_units_from_ports())
    seen = set()
    uniq = []
    for row in found:
        k = (row["unit"], row["user"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(row)
    return uniq


def _exec_argv(exec_start: str) -> list[str]:
    marker = "argv[]="
    if marker not in exec_start:
        return []
    raw = exec_start.split(marker, 1)[1]
    raw = raw.split(" ;", 1)[0].strip()
    # systemd wraps { path=... ; argv[]=... }
    parts = []
    buf = ""
    q = None
    for ch in raw:
        if q:
            if ch == q:
                q = None
            else:
                buf += ch
            continue
        if ch in ('"', "'"):
            q = ch
            continue
        if ch.isspace():
            if buf:
                parts.append(buf)
                buf = ""
            continue
        buf += ch
    if buf:
        parts.append(buf)
    return parts


def _write_dropin(unit: str, argv: list[str], user: bool) -> Path:
    home = Path(os.environ.get("HOME") or str(Path.home()))
    if user:
        d = home / ".config/systemd/user" / f"{unit}.d"
    else:
        raise PermissionError("system unit needs root")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "890m.conf"
    cmd = " ".join(shlex_quote(p) for p in argv)
    path.write_text(
        "[Service]\n"
        "Environment=GGML_VULKAN_DEVICE=0\n"
        "Environment=GGML_VK_VISIBLE_DEVICES=0\n"
        "Environment=LLAMA_ARG_N_GPU_LAYERS=99\n"
        "ExecStart=\n"
        f"ExecStart={cmd}\n",
        encoding="utf-8",
    )
    return path


def shlex_quote(s: str) -> str:
    if not s:
        return "''"
    if all(c.isalnum() or c in ".-_/=:@+," for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def tune_local_llm():
    """Offload llama.cpp Qwen onto the Radeon 890M via Vulkan."""
    report = {"ok": False, "vulkan": vulkan_report(), "units": [], "notes": []}
    units = _llm_units()
    if not units:
        report["notes"].append("No llama.cpp / Qwen systemd unit found. Start the inference server, then re-run.")
        return report
    for row in units:
        unit, user = row["unit"], row["user"]
        entry = {"unit": unit, "user": user, "patched": False}
        cmd = ["systemctl"] + (["--user"] if user else []) + [
            "show", unit, "-p", "ExecStart", "-p", "FragmentPath", "--no-pager",
        ]
        code, out, err = run(cmd, timeout=6)
        entry["show"] = out[:400]
        argv = _exec_argv(out)
        if not argv:
            entry["error"] = "could not parse ExecStart"
            report["units"].append(entry)
            continue
        if not user:
            entry["error"] = "system-owned unit — ask the operator to add -ngl 99; not patched"
            report["units"].append(entry)
            report["notes"].append(f"{unit} is system-owned.")
            continue
        if not any(a in ("-ngl", "--n-gpu-layers") or a.startswith("--n-gpu-layers=") for a in argv):
            argv += ["-ngl", "99"]
        try:
            drop = _write_dropin(unit, argv, user=True)
            entry["dropin"] = str(drop)
            entry["patched"] = True
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
            report["units"].append(entry)
            continue
        run(["systemctl", "--user", "daemon-reload"], timeout=8)
        rcode, _, rerr = run(["systemctl", "--user", "restart", unit], timeout=20)
        entry["restart"] = rcode == 0
        if rcode:
            entry["error"] = rerr or "restart failed"
        report["units"].append(entry)
    report["ok"] = any(u.get("patched") for u in report["units"])
    if not report["vulkan"].get("ok"):
        report["notes"].append(
            "Install GPU ICD: sudo apt-get install -y mesa-vulkan-drivers vulkan-tools"
        )
    return report
    if not PULSE_URL or not PULSE_TOKEN:
        raise SystemExit("PULSE_URL and PULSE_TOKEN are required")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        PULSE_URL if PULSE_URL.endswith("/ingest") else PULSE_URL + "/api/ingest",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {PULSE_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "pulse-agent/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.status


def main():
    if "--tune-gpu" in sys.argv:
        print(json.dumps(tune_local_llm(), default=str, indent=2))
        return
    if not PULSE_URL or not PULSE_TOKEN:
        raise SystemExit("Set PULSE_URL and PULSE_TOKEN")
    while True:
        try:
            payload = collect()
            status = post(payload)
            print(f"{datetime.now(timezone.utc).isoformat()} posted {status} services={len(payload.get('services') or [])}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"{datetime.now(timezone.utc).isoformat()} error {exc}", flush=True)
        time.sleep(max(5, INTERVAL))


if __name__ == "__main__":
    main()
