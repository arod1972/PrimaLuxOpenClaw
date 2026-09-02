# Clawbox

Local GUI for **OpenClaw** on the Beelink SER10 Max. Wraps the `openclaw` CLI so you do not have to live in it.

OpenClaw 2026.7.1-2, gateway on `127.0.0.1:18789` (user systemd). Clawbox listens on **18791**.

## Install on the Max

```bash
git clone https://github.com/arod1972/PrimaLuxOpenClaw.git
cd PrimaLuxOpenClaw
chmod +x install.sh uninstall.sh
./install.sh
```

Then open [http://127.0.0.1:18791/](http://127.0.0.1:18791/) (or the MagicDNS URL the installer prints).

Do **not** `sudo`. OpenClaw is a user service (`~/.config/systemd/user/openclaw-gateway.service`).

## Replace the old roster

The unfinished seats (Ken, Aria, Dex, Sol, Reggie, Cleo, Connie, Lex, Finn, Ollie, Mira) are replaced by six operating seats:

| Id | Seat |
|---|---|
| **vera** (default) | Chief of Staff |
| **scout** | Public research / Journey watch |
| **elena** | Marketing drafts (never posts) |
| **grant** | Finance — never invents balances |
| **marcus** | BD from a founder-dropped CSV |
| **lens** | Tech & framework research |

Coding stays in Grok Chat (Forge / Iris / Knox / Gage). Do not recreate those here.

In the UI: **Roster → type `RESET`**. Config is copied to `~/.openclaw-bak-<timestamp>` first. Gateway restarts. Model stays `local-qwen/qwen-9b-q4-local`.

## What the GUI does

- Gateway start / stop / restart / doctor
- Agent cards, SOUL.md / AGENTS.md / IDENTITY.md / MEMORY.md editor
- Make default, delete extra seats
- Tail `openclaw logs`
- One-shot roster reset

## Uninstall

```bash
./uninstall.sh
```

Leaves `~/.openclaw` and the gateway alone.
