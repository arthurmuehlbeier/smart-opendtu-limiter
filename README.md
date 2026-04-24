# Smart Power Limiter

Dynamic feedback controller for Hoymiles HMS inverters with
OpenDTU. Adjusts the inverter limit in real-time so partially
shaded panels don't waste headroom on sunny ones, without
exceeding the legal feed-in limit.

## Problem

A static limit distributes power evenly across all strings.
When some panels are shaded, they're capped below their potential
while remaining strings could still produce more. The surplus
capacity is lost.

## Solution

The script monitors DC power per string via the OpenDTU API
and raises the global limit when strings show usable power.
In edge cases (partial shade, clouds), the algorithm **prefers
5% more power over 5% less** to capture available solar energy.

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
| `SMOOTHER_MAX_INCREASES` | `3` | Max increases per window (prevents oscillation) |
| `SMOOTHER_WINDOW_S` | `120` | Smoother time window in seconds |

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
WorkingDirectory=/home/pi/smart-opendtu-limiter
ExecStart=/home/pi/smart-opendtu-limiter/venv/bin/python smart_opendtu_limiter.py
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
2. **Overproduction (AC > target)**: decrease limit by `STEP_PCT`
   (2x if overshoot > 50W)
3. **Underproduction (AC < hysteresis_low)**:
   - If any string is usable (above shade threshold) → increase limit
   - If no strings usable → no change (panels blocked by clouds/shade)
4. **Within hysteresis band**: no change
5. Increases are rate-limited to prevent oscillation

The algorithm prefers conservative decreases and aggressive increases
in edge cases — capturing more solar at slight risk of minor overproduction.

## Architecture

```
src/
├── __init__.py       # Package exports
├── config.py         # Configuration dataclass + .env parsing
├── inverter.py       # InverterReading dataclass + parsing
├── api.py            # OpenDTU HTTP client
├── smoother.py       # Rate-limiter for limit increases
├── controller.py     # Pure functions for power limiting logic
└── cli.py            # Main entry point

smart_opendtu_limiter.py  # Backwards-compatible wrapper

tests/
├── __init__.py
├── test_config.py
├── test_controller.py
└── test_smoother.py
```

### Module responsibilities

| Module | Responsibility |
| --- | --- |
| `config.py` | Load and validate .env settings |
| `inverter.py` | Inverter state data model |
| `api.py` | OpenDTU HTTP communication |
| `smoother.py` | Rate-limit limit increases |
| `controller.py` | Pure algorithm functions (testable) |
| `cli.py` | Wire everything together |

## Development

```bash
# install dependencies
source venv/bin/activate
pip install pytest requests

# run tests
python -m pytest tests/ -v

# lint + format check
ruff check src/ tests/ smart_opendtu_limiter.py
ruff format --check src/ tests/ smart_opendtu_limiter.py

# auto-fix
ruff check --fix src/ tests/ smart_opendtu_limiter.py
ruff format src/ tests/ smart_opendtu_limiter.py

# lint commit messages
commitlint --from=HEAD~1

# lint markdown
npx markdownlint README.md
```

## License

[MIT](LICENSE) — free to use, modify, and distribute