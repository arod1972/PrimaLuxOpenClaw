# Pulse · OpenClaw

One console on the Beelink SER10 Max: **host health (Pulse)** plus **OpenClaw seats**. User systemd. Do **not** `sudo`.

Gateway is loopback `127.0.0.1:18789`. This console listens on **18791** and is reachable on the tailnet.

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

Hard-refresh the browser (`Ctrl+Shift+R`). Host is `/`. Agents is `/#/agents`. Raw OpenClaw Control UI is `/openclaw/` (WebSocket is `ws://127.0.0.1:18789`, not 18791).

## First install

```bash
cd ~
git clone https://github.com/arod1972/PrimaLuxOpenClaw.git
cd PrimaLuxOpenClaw
chmod +x install.sh uninstall.sh
./install.sh
```

## Leftover Ken / Aria / Dex seats

They show as normal agent rows. **Delete leftover** on Host or Agents removes them. You do not need RESET.

- Per seat: open the profile → **Delete**
- All eleven: **Delete leftover**
- Optional bulk seed: **Seed Vera + five**, or type `RESET` only if you want wipe+seed in one shot

| Id | Seat |
|---|---|
| **vera** (default) | Chief of Staff |
| **scout** | Public research / Journey watch |
| **elena** | Marketing drafts (never posts) |
| **grant** | Finance — never invents balances |
| **marcus** | BD from a founder-dropped CSV |
| **lens** | Tech & framework research |

Coding stays in Grok Chat (Forge / Iris / Knox / Gage).

## What the GUI does

- Pulse host: uptime, CPU/RAM/NPU/temp/disk, featured units, Tailscale
- OpenClaw gateway start / stop / restart
- Portraits for leftover eleven and operating six
- Delete leftover without RESET (reassigns default if Ken is still default)
- Doctor scan and `doctor --repair --yes`
- Talk, bind, heartbeat, default, workspace files
- Raw OpenClaw Control UI at `/openclaw/`

## Uninstall

```bash
./uninstall.sh
```

Leaves `~/.openclaw` and the gateway alone.
