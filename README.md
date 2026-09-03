# PrimaLux Pulse

One console on the Beelink SER10 Max: **host health** plus **OpenClaw seats**. User systemd. Do **not** `sudo`.

Gateway is loopback `127.0.0.1:18789`. PrimaLux Pulse listens on **18791** and is reachable on the tailnet.

v1.6.2: Retired seats re-activate from Cold standby (workspace kept). Library drag-and-drop. Hire / retire / fire.

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

Hard-refresh the browser (`Ctrl+Shift+R`). Host is `/`. Agents is `/#/agents`. Library is `/#/library`. Raw OpenClaw Control UI is `/openclaw/` (WebSocket is `ws://127.0.0.1:18789`, not 18791).

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
- Raw OpenClaw Control UI at `/openclaw/`

## Uninstall

```bash
./uninstall.sh
```

Leaves `~/.openclaw` and the gateway alone.