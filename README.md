# Smart Power Limiter

Dynamic feedback controller for Hoymiles HMS inverters with
OpenDTU. Adjusts the inverter limit in real-time so partially
shaded panels don't waste headroom on sunny ones, without
exceeding the legal 800W feed-in limit.

## Problem

A static 800W limit (50% on HMS-1600) distributes power evenly
across all 4 strings. When some panels are shaded, they're
capped below their potential while remaining strings could
still produce more. The surplus capacity is lost.

## Solution

The script monitors DC power per string via the OpenDTU API
and raises the global limit when strings hit their individual
caps. The inverter distributes remaining headroom to
unconstrained strings, so shaded strings stay capped while
sunny ones fill the budget.

The controller only increases the limit when at least one string
is constrained AND another is below 50% of the string limit.

## Requirements

- Python 3.10+
- `requests` library
- OpenDTU instance with HMS/HM series inverter on firmware
  V1.0.x (V2.x has known persistent-limit incompatibilities)

## Setup

```bash
cp .env.example .env
# edit .env with your OpenDTU URL, credentials, inverter serial
```

### `.env` parameters

| Variable | Default | Description |
| --- | --- | --- |
| `OPENDTU_URL` | required | HTTP URL of your OpenDTU instance |
| `OPENDTU_USER` | `admin` | OpenDTU username |
| `OPENDTU_PASS` | required | OpenDTU password |
| `INVERTER_SERIAL` | required | Serial number of your inverter |
| `TARGET_W` | `800` | Target AC output in watts |
| `MIN_LIMIT_PCT` | `50` | Never go below this limit (%) |
| `MAX_LIMIT_PCT` | `100` | Never go above this limit (%) |
| `INTERVAL_S` | `30` | Seconds between adjustment cycles |
| `STEP_PCT` | `5` | Limit change per cycle in % points |

## Usage

```bash
# dry run - show what would happen, change nothing
python3 smart_opendtu_limiter.py --dry-run --once

# single live cycle
python3 smart_opendtu_limiter.py --once

# continuous daemon
python3 smart_opendtu_limiter.py
```

### Systemd service (Raspberry Pi / Linux)

```ini
[Unit]
Description=Smart Power Limiter
After=network.target

[Service]
Type=simple
User=pi
ExecStart=/usr/bin/python3 /home/pi/smart-opendtu-limiter/smart_opendtu_limiter.py
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now smart-limiter
journalctl -u smart-limiter -f   # watch logs
```

## How it works

Each cycle:

1. Fetch current AC power and per-string DC power from OpenDTU
2. Count how many strings are at their individual cap
   (90% of string limit)
3. If AC < target and at least one string is capped and another
   is shaded -> increase limit by `STEP_PCT` (up to 2x if
   multiple strings constrained)
4. If AC > target -> decrease limit by `STEP_PCT` (2x if
   overshoot > 50W)
5. Otherwise -> no change

The limit command uses `limit_type=1` (relative, non-persistent,
RAM-only), so there is zero flash wear on the inverter.

## Architecture

```text
Config (dataclass)          <- loaded from .env
InverterReading (dataclass) <- parsed from OpenDTU API
SmartLimiter                <- main controller class
  fetch_inverter_data()     <- GET /api/livedata/status
  fetch_limit_status()      <- GET /api/limit/status
  send_limit()              <- POST /api/limit/config (type=1)
  calculate_new_limit()     <- feedback controller logic
  log_reading()             <- formatted status output
  run_once() / run()        <- main loop
main()                      <- argparse CLI entrypoint
```

## Development

```bash
# lint + format check
ruff check smart_opendtu_limiter.py
ruff format --check smart_opendtu_limiter.py

# auto-fix
ruff check --fix smart_opendtu_limiter.py
ruff format smart_opendtu_limiter.py

# lint commit messages
commitlint --from=HEAD~1

# lint markdown
npx markdownlint README.md
```

## License

MIT
