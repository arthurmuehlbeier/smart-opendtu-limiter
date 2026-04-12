#!/usr/bin/env python3
"""Smart Power Limiter for Hoymiles HMS inverters with OpenDTU.

Dynamic feedback controller that raises the inverter limit when partially
shaded panels leave headroom on sunny ones — without exceeding the legal
feed-in limit. Uses non-persistent (RAM-only) limit commands, so zero
flash wear on the inverter.

Requires a ``.env`` file next to this script. See ``.env.example``.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

__version__ = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("smart_opendtu_limiter")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when .env configuration is invalid or missing."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """Runtime configuration loaded from .env file."""

    opendtu_url: str
    opendtu_user: str
    opendtu_pass: str
    inverter_serial: str
    inverter_max_watt: int = 1600

    target_w: int = 800
    min_limit_pct: int = 50
    max_limit_pct: int = 100

    interval_s: int = 30
    step_pct: int = 5
    hysteresis_w: int = 20
    night_threshold_w: int = 10
    string_cap_ratio: float = 0.90
    string_shade_ratio: float = 0.50

    @property
    def num_strings(self) -> int:
        return self.inverter_max_watt // 400

    @property
    def hysteresis_low(self) -> float:
        return self.target_w - self.hysteresis_w

    @classmethod
    def from_env(cls, env_path: Path) -> Config:
        if not env_path.exists():
            raise ConfigError(
                f".env not found: {env_path}\nCreate one: cp .env.example .env  (then edit values)"
            )

        env: dict[str, str] = {}
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()

        def integer(key: str, default: str) -> int:
            try:
                return int(env.get(key, default))
            except ValueError:
                val = env.get(key)
                raise ConfigError(f".env value for {key} is not an integer: {val}") from None

        def required(key: str) -> str:
            if key not in env:
                raise ConfigError(f".env is missing required key: {key}")
            return env[key]

        return cls(
            opendtu_url=required("OPENDTU_URL"),
            opendtu_user=env.get("OPENDTU_USER", "admin"),
            opendtu_pass=required("OPENDTU_PASS"),
            inverter_serial=required("INVERTER_SERIAL"),
            inverter_max_watt=integer("INVERTER_MAX_WATT", "1600"),
            target_w=integer("TARGET_W", "800"),
            min_limit_pct=integer("MIN_LIMIT_PCT", "50"),
            max_limit_pct=integer("MAX_LIMIT_PCT", "100"),
            interval_s=integer("INTERVAL_S", "30"),
            step_pct=integer("STEP_PCT", "5"),
            hysteresis_w=integer("HYSTERESIS_W", "20"),
            night_threshold_w=integer("NIGHT_THRESHOLD_W", "10"),
        )


# ---------------------------------------------------------------------------
# Inverter data
# ---------------------------------------------------------------------------


@dataclass
class InverterReading:
    """Snapshot of inverter state from OpenDTU API."""

    ac_power: float
    dc_powers: list[float]
    reachable: bool
    producing: bool
    limit_relative: float
    limit_absolute: float

    @property
    def dc_total(self) -> float:
        return sum(self.dc_powers)


# ---------------------------------------------------------------------------
# Smart Limiter
# ---------------------------------------------------------------------------


class SmartLimiter:
    """Feedback controller that dynamically adjusts inverter power limit."""

    def __init__(self, config: Config, *, dry_run: bool = False) -> None:
        self.cfg = config
        self.dry_run = dry_run
        self.current_limit_pct: float | None = None
        self.running = True
        self.session = requests.Session()
        self.session.auth = (config.opendtu_user, config.opendtu_pass)
        self.session.timeout = 10

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, _signum: int | None, _frame: Any | None) -> None:
        log.info("Shutdown signal received")
        self.running = False

    # -- unit helpers -------------------------------------------------------

    def _pct_to_watt(self, pct: float) -> float:
        return pct / 100.0 * self.cfg.inverter_max_watt

    def _string_limit(self, pct: float) -> float:
        return self._pct_to_watt(pct) / self.cfg.num_strings

    # -- OpenDTU API --------------------------------------------------------

    def _api_url(self, path: str) -> str:
        return f"{self.cfg.opendtu_url}{path}"

    def fetch_inverter_data(self) -> InverterReading | None:
        try:
            resp = self.session.get(
                self._api_url("/api/livedata/status"),
                params={"inv": self.cfg.inverter_serial},
            )
            resp.raise_for_status()
            inverters = resp.json().get("inverters", [])
            if not inverters:
                log.warning("No inverter data received from OpenDTU")
                return None
            return self._parse_inverter(inverters[0])
        except requests.RequestException as exc:
            log.error("API error (livedata): %s", exc)
            return None

    def fetch_limit_status(self) -> dict[str, Any] | None:
        try:
            resp = self.session.get(self._api_url("/api/limit/status"))
            resp.raise_for_status()
            return resp.json().get(self.cfg.inverter_serial)
        except requests.RequestException as exc:
            log.error("API error (limit status): %s", exc)
            return None

    def send_limit(self, percent: float) -> bool:
        percent = round(max(self.cfg.min_limit_pct, min(self.cfg.max_limit_pct, percent)))

        if self.dry_run:
            log.info("[DRY-RUN] Would set limit to %d%%", percent)
            self.current_limit_pct = percent
            return True

        payload = json.dumps(
            {
                "serial": self.cfg.inverter_serial,
                "limit_type": 1,
                "limit_value": percent,
            }
        )
        try:
            resp = self.session.post(
                self._api_url("/api/limit/config"),
                data=f"data={payload}",
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("type") == "success":
                self.current_limit_pct = percent
                log.info("Limit set: %d%% (%.0fW)", percent, self._pct_to_watt(percent))
                return True
            log.warning("Limit rejected: %s", result)
            return False
        except requests.RequestException as exc:
            log.error("API error (limit config): %s", exc)
            return False

    # -- parsing ------------------------------------------------------------

    def _parse_inverter(self, data: dict[str, Any]) -> InverterReading | None:
        try:
            ac_power = data["AC"]["0"]["Power"]["v"]
            dc_powers = [data["DC"][str(i)]["Power"]["v"] for i in range(self.cfg.num_strings)]
            return InverterReading(
                ac_power=ac_power,
                dc_powers=dc_powers,
                reachable=data.get("reachable", False),
                producing=data.get("producing", False),
                limit_relative=data.get("limit_relative", 0),
                limit_absolute=data.get("limit_absolute", 0),
            )
        except (KeyError, IndexError, TypeError) as exc:
            log.error("Parse error: %s", exc)
            return None

    # -- controller logic ---------------------------------------------------

    def _count_strings_at_cap(self, reading: InverterReading) -> int:
        limit = self._string_limit(self.current_limit_pct or reading.limit_relative)
        return sum(1 for p in reading.dc_powers if p >= limit * self.cfg.string_cap_ratio)

    def _count_strings_shaded(self, reading: InverterReading) -> int:
        limit = self._string_limit(self.current_limit_pct or reading.limit_relative)
        return sum(1 for p in reading.dc_powers if p < limit * self.cfg.string_shade_ratio)

    def calculate_new_limit(self, reading: InverterReading) -> float | None:
        """Calculate new limit percentage, or None if no change needed."""
        ac = reading.ac_power
        current_pct = self.current_limit_pct or reading.limit_relative

        if ac < self.cfg.night_threshold_w:
            return None

        if ac > self.cfg.target_w:
            overshoot = ac - self.cfg.target_w
            step = self.cfg.step_pct * 2 if overshoot > 50 else self.cfg.step_pct
            new_pct = current_pct - step
        elif ac < self.cfg.hysteresis_low:
            constrained = self._count_strings_at_cap(reading)
            if constrained == 0:
                log.info("  (no string at limit — sun is bottleneck, not limit)")
                return None

            shaded = self._count_strings_shaded(reading)
            if shaded > 0:
                step = self.cfg.step_pct * min(2, constrained)
            else:
                step = self.cfg.step_pct
            new_pct = current_pct + step
        else:
            return None

        new_pct = max(self.cfg.min_limit_pct, min(self.cfg.max_limit_pct, new_pct))
        return new_pct if abs(new_pct - current_pct) >= 0.5 else None

    # -- logging ------------------------------------------------------------

    def log_reading(self, reading: InverterReading) -> None:
        ac = reading.ac_power
        dc = reading.dc_powers
        pct = self.current_limit_pct or reading.limit_relative
        lim_w = self._pct_to_watt(pct)
        str_w = self._string_limit(pct)
        at_cap = self._count_strings_at_cap(reading)
        util = (ac / self.cfg.target_w) * 100

        log.info(
            "AC: %6.1fW / %dW (%4.1f%%) │ Limit: %5.1f%% (%.0fW, Str: %.0fW) │ "
            "DC: %s = %.0fW │ At cap: %d/%d",
            ac,
            self.cfg.target_w,
            util,
            pct,
            lim_w,
            str_w,
            " + ".join(f"{p:5.1f}" for p in dc),
            reading.dc_total,
            at_cap,
            self.cfg.num_strings,
        )

    # -- main loop ----------------------------------------------------------

    def run_once(self) -> bool:
        reading = self.fetch_inverter_data()
        if not reading:
            return False

        if self.current_limit_pct is None:
            self.current_limit_pct = reading.limit_relative

        self.log_reading(reading)

        if not reading.reachable:
            log.warning("Inverter unreachable — skipping")
            return False
        if not reading.producing:
            log.info("Inverter not producing — nothing to regulate")
            return False

        new_limit = self.calculate_new_limit(reading)
        if new_limit is None:
            log.info("-> Limit unchanged")
            return True

        old_pct = self.current_limit_pct
        arrow = "UP" if new_limit > old_pct else "DOWN"
        log.info(
            "-> Limit %s %.0f%% -> %.0f%% (%.0fW -> %.0fW)",
            arrow,
            old_pct,
            new_limit,
            self._pct_to_watt(old_pct),
            self._pct_to_watt(new_limit),
        )
        return self.send_limit(new_limit)

    def run(self, *, once: bool = False) -> None:
        log.info("=" * 60)
        log.info("Smart Power Limiter started")
        log.info("  OpenDTU:        %s", self.cfg.opendtu_url)
        log.info("  Inverter:       %s", self.cfg.inverter_serial)
        log.info("  Target:         %dW AC", self.cfg.target_w)
        log.info("  Limit range:    %d%% - %d%%", self.cfg.min_limit_pct, self.cfg.max_limit_pct)
        log.info("  Interval:       %ds", self.cfg.interval_s)
        log.info("  Dry-Run:        %s", self.dry_run)
        log.info("=" * 60)

        limit_status = self.fetch_limit_status()
        if limit_status:
            self.current_limit_pct = limit_status.get("limit_relative", self.cfg.min_limit_pct)
            log.info("Current limit from OpenDTU: %.1f%%", self.current_limit_pct)
        else:
            log.info("Starting at %d%%", self.cfg.min_limit_pct)
            self.send_limit(self.cfg.min_limit_pct)

        while self.running:
            try:
                self.run_once()
            except Exception as exc:
                log.error("Unexpected error: %s", exc, exc_info=True)
            if once:
                break
            time.sleep(self.cfg.interval_s)

        log.info("Smart Power Limiter stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart Power Limiter for Hoymiles inverters with OpenDTU",
    )
    parser.add_argument("--once", action="store_true", help="Run single cycle")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug output")
    parser.add_argument(
        "--version",
        action="version",
        version=f"smart-opendtu-limiter {__version__}",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    env_path = Path(__file__).parent / ".env"
    try:
        config = Config.from_env(env_path)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    SmartLimiter(config, dry_run=args.dry_run).run(once=args.once)


if __name__ == "__main__":
    main()
