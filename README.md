# PrimaLux Pulse

One console on the Beelink SER10 Max: **host health** plus **OpenClaw seats**. User systemd. Do **not** `sudo`.

Gateway is loopback `127.0.0.1:18789`. PrimaLux Pulse is loopback **18791**. Other devices use **HTTPS** via Tailscale named services (`https://primalux-pulse.<tailnet>/` and `https://prima.<tailnet>/`). Funnel stays off. Never open `http://…:18791` or `http://…:18789` on the tailnet. The Control UI hostname is `prima`, not `openclaw`.

v1.8.9: Edit agent display name and role on the profile. IDENTITY.md is the source of truth.

## Update (directory already exists)

`git clone` will fail with *destination path already exists*. Pull, then reinstall:

```bash
cd ~/PrimaLuxOpenClaw
git fetch origin
git checkout main
git pull --ff-only origin main
chmod +x install.sh uninstall.sh
./install.sh
```

Hard-refresh the browser (`Ctrl+Shift+R`). Host is `/`. Agents is `/#/agents`. Library is `/#/library`. Control UI is `http://127.0.0.1:18789/` locally, or `https://prima.<tailnet>/` on the tailnet. Do not use Pulse `/openclaw/` — that proxy cannot carry the Control UI WebSocket.

Vera (Command) uses Grok 4.20 non-reasoning. Cora stays on Grok 4.3. Other internal seats stay on local Qwen 9B, offloaded to the Radeon 890M (`-ngl 99`).

## First install

```bash
cd ~
git clone https://github.com/arod1972/PrimaLuxOpenClaw.git
cd PrimaLuxOpenClaw
chmod +x install.sh uninstall.sh
./install.sh
```

## Roster

Agents is generic maintenance. **Hire** adds a seat. **Retire** parks it on cold standby (`~/.local/share/primalux-pulse/standby/`). **Restore** puts it back. **Fire** deletes it.

Starter templates still exist under `roster/` if you hire those ids (vera, scout, elena, grant, marcus, lens). Coding stays in Grok Chat.

## What the GUI does

- PrimaLux Pulse host: uptime, CPU/RAM/NPU/temp/disk, load history, featured units (OpenClaw, TalkTrack, local LLM, Tailscale), journal errors, usage-cost
- Agents: hire, retire (cold standby), restore, fire
- Library: drag-and-drop PDFs / Markdown / Word / folders / URLs, plus NCUA–OCC presets and paste; **Sync to seats** writes `KNOWLEDGE.md` + `knowledge/`
- Doctor scan and `doctor --repair --yes`
- Talk, bind, heartbeat, default, workspace files
- OpenClaw Control UI at `http://127.0.0.1:18789/` (HTTPS named service `svc:prima` on the tailnet)

## Uninstall

```bash
./uninstall.sh
```

Leaves `~/.openclaw` and the gateway alone.