"""Power limiting controller algorithm for Smart OpenDTU Limiter.

This module contains pure functions for the power limiting decision logic.
No I/O, no external state — fully testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .inverter import InverterReading
    from .smoother import Smoother


def pct_to_watt(pct: float, inverter_max_watt: int) -> float:
    """Convert limit percentage to watts."""
    return pct / 100.0 * inverter_max_watt


def string_limit(pct: float, inverter_max_watt: int, num_strings: int) -> float:
    """Calculate per-string power limit in watts."""
    return pct_to_watt(pct, inverter_max_watt) / num_strings


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))


def count_strings_at_cap(
    reading: InverterReading, cfg: Config, limit_pct: float
) -> int:
    """Count how many DC strings are at their power cap."""
    str_limit = string_limit(limit_pct, cfg.inverter_max_watt, cfg.num_strings)
    cap_threshold = str_limit * cfg.string_cap_ratio
    return sum(1 for p in reading.dc_powers if p >= cap_threshold)


def count_usable_strings(
    reading: InverterReading, cfg: Config, limit_pct: float
) -> int:
    """Count how many DC strings are producing usable power."""
    str_limit = string_limit(limit_pct, cfg.inverter_max_watt, cfg.num_strings)
    shade_threshold = str_limit * cfg.string_shade_ratio
    return sum(1 for p in reading.dc_powers if p >= shade_threshold)


def calculate_new_limit(
    reading: InverterReading,
    current_pct: float,
    cfg: Config,
    smoother: Smoother | None = None,
    now: float | None = None,
) -> float | None:
    """Calculate a new power limit based on current conditions.

    The algorithm prefers capturing more solar (5%% more) over strict
    underproduction in edge cases (partial shade, clouds):

    - Night mode: if AC < threshold, no change
    - Overproduction (AC > target): decrease limit
    - Underproduction (AC < hysteresis_low): increase if any usable strings
    - Rate-limit increases to prevent oscillation
    """
    if reading.ac_power < cfg.night_threshold_w:
        return None

    if reading.ac_power > cfg.target_w:
        overshoot = reading.ac_power - cfg.target_w
        step = cfg.step_pct * 2 if overshoot > 50 else cfg.step_pct
        new_pct = current_pct - step
        new_pct = clamp(new_pct, cfg.min_limit_pct, cfg.max_limit_pct)
        return new_pct if abs(new_pct - current_pct) >= 0.5 else None

    if reading.ac_power < cfg.hysteresis_low:
        usable = count_usable_strings(reading, cfg, current_pct)
        if usable == 0:
            return None

        if usable == cfg.num_strings:
            new_pct = current_pct + cfg.step_pct
        else:
            # Some strings blocked — still increase by at least step_pct
            new_pct = current_pct + max(cfg.step_pct, cfg.step_pct)

        new_pct = clamp(new_pct, cfg.min_limit_pct, cfg.max_limit_pct)

        if smoother is not None and new_pct > current_pct:
            new_pct = smoother.apply(current_pct, new_pct, now)

        return new_pct if abs(new_pct - current_pct) >= 0.5 else None

    return None


# Alias for backwards compatibility
calculate_limit_change = calculate_new_limit
