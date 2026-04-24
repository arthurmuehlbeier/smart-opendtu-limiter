"""CLI entry point for Smart OpenDTU Limiter."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

from .api import OpenDTUClient
from .config import Config, ConfigError
from .controller import calculate_new_limit, string_limit
from .smoother import Smoother

__version__ = "0.2.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("smart_opendtu_limiter")


def pct_to_watt(pct: float, cfg: Config) -> float:
    """Convert limit percentage to watts."""
    return pct / 100.0 * cfg.inverter_max_watt


def count_strings_at_cap(
    reading: Any,
    cfg: Config,
    limit_pct: float,
) -> int:
    """Count strings at cap for logging."""
    str_limit = string_limit(limit_pct, cfg.inverter_max_watt, cfg.num_strings)
    cap_threshold = str_limit * cfg.string_cap_ratio
    return sum(1 for p in reading.dc_powers if p >= cap_threshold)


def log_reading(reading: Any, cfg: Config, current_pct: float) -> None:
    """Log current inverter state."""
    ac = reading.ac_power
    dc = reading.dc_powers
    lim_w = pct_to_watt(current_pct, cfg)
    str_w = string_limit(current_pct, cfg.inverter_max_watt, cfg.num_strings)
    at_cap = count_strings_at_cap(reading, cfg, current_pct)
    util = (ac / cfg.target_w) * 100

    log.info(
        "AC: %6.1fW / %dW (%4.1f%%) │ Limit: %5.1f%% (%.0fW, Str: %.0fW) │ "
        "DC: %s = %.0fW │ At cap: %d/%d",
        ac,
        cfg.target_w,
        util,
        current_pct,
        lim_w,
        str_w,
        " + ".join(f"{p:5.1f}" for p in dc),
        reading.dc_total,
        at_cap,
        cfg.num_strings,
    )


def run_once(
    client: OpenDTUClient,
    cfg: Config,
    smoother: Smoother,
    current_limit_pct: float,
    dry_run: bool,
) -> float:
    """Execute one control cycle."""
    reading = client.fetch_inverter_data()
    if not reading:
        return current_limit_pct

    if current_limit_pct is None:
        current_limit_pct = reading.limit_relative

    log_reading(reading, cfg, current_limit_pct)

    if not reading.reachable:
        log.warning("Inverter unreachable — skipping")
        return current_limit_pct

    if not reading.producing:
        log.info("Inverter not producing — nothing to regulate")
        return current_limit_pct

    new_limit = calculate_new_limit(reading, current_limit_pct, cfg, smoother)

    if new_limit is None:
        log.info("-> Limit unchanged")
        return current_limit_pct

    old_pct = current_limit_pct
    direction = "UP" if new_limit > old_pct else "DOWN"
    log.info(
        "-> Limit %s %.0f%% -> %.0f%% (%.0fW -> %.0fW)",
        direction,
        old_pct,
        new_limit,
        pct_to_watt(old_pct, cfg),
        pct_to_watt(new_limit, cfg),
    )

    success = client.set_limit(new_limit, dry_run=dry_run)
    return new_limit if success else current_limit_pct


def run(cfg: Config, *, once: bool = False, dry_run: bool = False) -> None:
    """Run the main control loop."""
    log.info("=" * 60)
    log.info("Smart Power Limiter started")
    log.info("  OpenDTU:        %s", cfg.opendtu_url)
    log.info("  Inverter:       %s", cfg.inverter_serial)
    log.info("  Target:         %dW AC", cfg.target_w)
    log.info("  Limit range:    %d%% - %d%%", cfg.min_limit_pct, cfg.max_limit_pct)
    log.info("  Interval:       %ds", cfg.interval_s)
    log.info(
        "  Smoother:       %d increases per %ds",
        cfg.smoother_max_increases,
        cfg.smoother_window_s,
    )
    log.info("  Dry-Run:        %s", dry_run)
    log.info("=" * 60)

    client = OpenDTUClient(cfg)
    smoother = Smoother(cfg.smoother_max_increases, cfg.smoother_window_s)

    running = True

    def shutdown(_signum: int | None, _frame: Any | None) -> None:
        nonlocal running
        log.info("Shutdown signal received")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    current_limit_pct: float | None = None
    limit_status = client.fetch_limit_status()
    if limit_status:
        current_limit_pct = limit_status.get("limit_relative", cfg.min_limit_pct)
        log.info("Current limit from OpenDTU: %.1f%%", current_limit_pct)
    else:
        log.info("Starting at %d%%", cfg.min_limit_pct)
        client.set_limit(cfg.min_limit_pct, dry_run=dry_run)

    while running:
        try:
            current_limit_pct = run_once(
                client, cfg, smoother, current_limit_pct, dry_run
            )
        except Exception as exc:
            log.error("Unexpected error: %s", exc, exc_info=True)

        if once:
            break

        time.sleep(cfg.interval_s)

    log.info("Smart Power Limiter stopped.")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Smart Power Limiter for Hoymiles inverters with OpenDTU",
    )
    parser.add_argument("--once", action="store_true", help="Run single cycle")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without applying"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug output")
    parser.add_argument(
        "--version", action="version", version=f"smart-opendtu-limiter {__version__}"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    env_path = Path(__file__).parent.parent / ".env"
    try:
        config = Config.from_env(env_path)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    run(config, once=args.once, dry_run=args.dry_run)
