# Clawbox

Local GUI for **OpenClaw 2026.7.1-2** on the Beelink SER10 Max. Wraps the `openclaw` CLI so you do not have to live in it.

Gateway is a **user systemd** service on `127.0.0.1:18789`. Clawbox listens on **18791**. Do **not** `sudo`.

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

Hard-refresh the browser (`Ctrl+Shift+R`). Then open [http://127.0.0.1:18791/](http://127.0.0.1:18791/) or the MagicDNS URL the installer prints.

## First install on the Max

```bash
cd ~
git clone https://github.com/arod1972/PrimaLuxOpenClaw.git
cd PrimaLuxOpenClaw
chmod +x install.sh uninstall.sh
./install.sh
```

## Replace the unfinished roster

Ken, Aria, Dex, Sol, Reggie, Cleo, Connie, Lex, Finn, Ollie, Mira are leftover from the unfinished pass. In the UI: **Roster → type `RESET`**.

That copies `~/.openclaw/openclaw.json` to `~/.openclaw-bak-<timestamp>`, seeds six operating seats (SOUL, AGENTS, IDENTITY, USER, TOOLS, HEARTBEAT, MEMORY), deletes the eleven leftovers, sets **vera** default, and restarts the gateway. Model stays `local-qwen/qwen-9b-q4-local`.

| Id | Seat |
|---|---|
| **vera** (default) | Chief of Staff |
| **scout** | Public research / Journey watch |
| **elena** | Marketing drafts (never posts) |
| **grant** | Finance — never invents balances |
| **marcus** | BD from a founder-dropped CSV |
| **lens** | Tech & framework research |

Coding stays in Grok Chat (Forge / Iris / Knox / Gage). Do not recreate those here.

## What the GUI does

- Portraits for the leftover eleven and the operating six
- Gateway start / stop / restart
- Doctor scan and `doctor --repair --yes` (nvm PATH / stale user unit)
- Agent cards: Open, Talk, Heartbeat, Bind, Default, Delete
- Edit SOUL / AGENTS / IDENTITY / USER / TOOLS / HEARTBEAT / MEMORY
- Talk to a seat through local Qwen 9B
- Skills / channels / cron
- Config (redacted `openclaw.json`) and heartbeat
- Raw OpenClaw Control UI at `/openclaw/` (proxied to `127.0.0.1:18789`)
- Tail `openclaw logs` and `/tmp/openclaw/*.log`
- One-shot roster reset

## Doctor notes on this host

Typical findings while Ken is still default:

- Service config looks out of date or non-standard
- Gateway service PATH includes nvm (`~/.nvm/versions/node/v24.18.0/bin`)
- Gateway uses Node from a version manager
- Loopback-only bind (leave it; reach Clawbox over Tailscale if needed)

**Doctor → Repair** runs `openclaw doctor --repair --yes` as the user.

## Uninstall

```bash
./uninstall.sh
```

Leaves `~/.openclaw` and the gateway alone.
