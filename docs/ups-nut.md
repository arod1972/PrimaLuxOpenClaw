# CyberPower UPS + NUT on SER10 Max

Pulse collects UPS state via `upsc` (featured service **CyberPower UPS**). NUT itself is installed separately on Max; this repo only monitors and notifies.

USB device: CyberPower `0764:0501` (EC850LCD; often enumerates as **CP1500 AVR**). Default UPS name: `cyberpower`.

## Pulse collection

- Helper: `ups_status()` in `agent.py` runs `upsc ${UPS_NAME:-cyberpower@localhost}`.
- Status map: `OL*` → healthy, `OB*` → degraded, `LB*` / `COMM*` → down; missing `upsc` → down/unknown.
- Featured detail example: `OL CHRG charge=97% runtime=42m load=22% in=121V`.
- Optional `hardware.ups`: `status`, `charge`, `runtimeSec`, `load`, `inputVoltage`.

Override name:

```bash
export UPS_NAME=cyberpower@localhost
```

## NUT config snippets (Max)

`/etc/nut/ups.conf` (driver runs as root/system; Pulse does not):

```ini
[cyberpower]
  driver = usbhid-ups
  port = auto
  desc = "CyberPower EC850LCD / CP1500 AVR"
  vendorid = 0764
  productid = 0501
```

`/etc/nut/upsmon.conf` — monitor + NOTIFYCMD (adjust user home):

```ini
MONITOR cyberpower@localhost 1 upsmon pass master

NOTIFYCMD /home/primaluxadvisory/.local/bin/nut-notify-openclaw.sh

NOTIFYFLAG ONLINE   SYSLOG+EXEC
NOTIFYFLAG ONBATT   SYSLOG+EXEC
NOTIFYFLAG LOWBATT  SYSLOG+EXEC
NOTIFYFLAG COMMOK   SYSLOG+EXEC
NOTIFYFLAG COMMBAD  SYSLOG+EXEC
NOTIFYFLAG SHUTDOWN SYSLOG+EXEC
NOTIFYFLAG REPLBATT SYSLOG+EXEC
NOTIFYFLAG NOCOMM   SYSLOG+EXEC
NOTIFYFLAG FSD      SYSLOG+EXEC
```

After `./install.sh`, the helper is installed to `~/.local/bin/nut-notify-openclaw.sh`. Point `NOTIFYCMD` at that path (or the repo copy under `scripts/`).

## Notify helper behavior

`scripts/nut-notify-openclaw.sh`:

1. Appends a JSON line to `~/.local/share/primalux-pulse/ups-events.jsonl`.
2. Tries `openclaw agent --agent quinn --message "…"` (no Slack).
3. Else writes `~/.openclaw/workspace-quinn/heartbeat-ups.md`.
4. Else `logger -t nut-notify-openclaw`.

NUT sets `$NOTIFYTYPE` (and usually `$UPSNAME`) when invoking NOTIFYCMD.

## Quick checks

```bash
upsc cyberpower@localhost
# sample keys: ups.status, battery.charge, battery.runtime, ups.load, input.voltage

NOTIFYTYPE=ONBATT UPSNAME=cyberpower@localhost ~/.local/bin/nut-notify-openclaw.sh
tail -1 ~/.local/share/primalux-pulse/ups-events.jsonl
```
