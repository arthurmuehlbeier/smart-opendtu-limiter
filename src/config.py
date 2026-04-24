"""Configuration management for Smart OpenDTU Limiter.

Loads runtime configuration from a `.env` file and provides typed access
to all settings used by the power limiting controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ConfigError(Exception):
    """Raised when .env configuration is invalid or missing."""


@dataclass
class Config:
    """Runtime configuration loaded from .env file.

    Attributes:
        opendtu_url: Base URL of the OpenDTU instance (e.g., http://192.168.1.100).
        opendtu_user: OpenDTU username for HTTP Basic Auth.
        opendtu_pass: OpenDTU password for HTTP Basic Auth.
        inverter_serial: Serial number of the Hoymiles inverter to control.
        inverter_max_watt: Maximum rated power of the inverter in watts (default 1600).
        target_w: Target AC power output in watts (default 800).
        min_limit_pct: Minimum power limit as percentage of max (default 50).
        max_limit_pct: Maximum power limit as percentage of max (default 100).
        interval_s: Polling interval in seconds (default 30).
        step_pct: Power limit step size in percentage points (default 5).
        hysteresis_w: Hysteresis band around target power (default 20W).
        night_threshold_w: AC power below which we consider it nighttime (default 10W).
        string_cap_ratio: Threshold ratio for considering a string "at capacity" (default 0.90).
        string_shade_ratio: Threshold ratio for considering a string "usable" (default 0.50).
        smoother_max_increases: Max limit increases per smoother window (default 3).
        smoother_window_s: Time window for smoother rate limiting in seconds (default 120).
    """

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

    # Advanced tuning
    string_cap_ratio: float = 0.90
    string_shade_ratio: float = 0.50

    # Smoother settings
    smoother_max_increases: int = 3
    smoother_window_s: int = 120

    @property
    def num_strings(self) -> int:
        """Number of DC strings on this inverter.

        Assumes 400W per string (Hoymiles typical).
        """
        return self.inverter_max_watt // 400

    @property
    def hysteresis_low(self) -> float:
        """Lower bound of the hysteresis band around target power."""
        return self.target_w - self.hysteresis_w

    @classmethod
    def from_env(cls, env_path: Path) -> Config:
        """Load configuration from a .env file.

        Args:
            env_path: Path to the .env file.

        Returns:
            Config instance populated from the env file.

        Raises:
            ConfigError: If the file is missing or contains invalid values.
        """
        if not env_path.exists():
            raise ConfigError(
                f".env not found: {env_path}\n"
                "Create one: cp .env.example .env  (then edit values)"
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

        def float_(key: str, default: str) -> float:
            try:
                return float(env.get(key, default))
            except ValueError:
                val = env.get(key)
                raise ConfigError(f".env value for {key} is not a number: {val}") from None

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
            # Advanced tuning (optional)
            string_cap_ratio=float_("STRING_CAP_RATIO", "0.90"),
            string_shade_ratio=float_("STRING_SHADE_RATIO", "0.50"),
            smoother_max_increases=integer("SMOOTHER_MAX_INCREASES", "3"),
            smoother_window_s=integer("SMOOTHER_WINDOW_S", "120"),
        )
