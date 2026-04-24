"""Tests for the power limiting controller."""

import pytest

from src.config import Config
from src.controller import (
    calculate_new_limit,
    clamp,
    count_strings_at_cap,
    count_usable_strings,
    pct_to_watt,
    string_limit,
)
from src.inverter import InverterReading
from src.smoother import Smoother


@pytest.fixture
def cfg() -> Config:
    """Create a standard test configuration."""
    return Config(
        opendtu_url="http://localhost",
        opendtu_user="admin",
        opendtu_pass="password",
        inverter_serial="1234567890",
        inverter_max_watt=1600,
        target_w=800,
        min_limit_pct=50,
        max_limit_pct=100,
        step_pct=5,
        hysteresis_w=20,
        night_threshold_w=10,
        string_cap_ratio=0.90,
        string_shade_ratio=0.50,
        smoother_max_increases=3,
        smoother_window_s=120,
    )


def make_reading(
    ac_power: float,
    dc_powers: list[float],
    reachable: bool = True,
    producing: bool = True,
    limit_relative: float = 80.0,
    limit_absolute: float = 1280.0,
) -> InverterReading:
    """Helper to create an InverterReading."""
    return InverterReading(
        ac_power=ac_power,
        dc_powers=dc_powers,
        reachable=reachable,
        producing=producing,
        limit_relative=limit_relative,
        limit_absolute=limit_absolute,
    )


class TestClamp:
    def test_within_bounds(self):
        assert clamp(50.0, 0.0, 100.0) == 50.0

    def test_below_min(self):
        assert clamp(-10.0, 0.0, 100.0) == 0.0

    def test_above_max(self):
        assert clamp(150.0, 0.0, 100.0) == 100.0


class TestStringLimit:
    def test_pct_to_watt(self):
        assert pct_to_watt(50, 1600) == 800.0

    def test_string_limit_calc(self):
        assert string_limit(80, 1600, 4) == 320.0


class TestCountStringsAtCap:
    def test_all_at_cap(self, cfg: Config):
        reading = make_reading(
            ac_power=1200,
            dc_powers=[300.0, 310.0, 295.0, 305.0],
        )
        assert count_strings_at_cap(reading, cfg, 80.0) == 4

    def test_none_at_cap(self, cfg: Config):
        reading = make_reading(
            ac_power=200,
            dc_powers=[50.0, 60.0, 55.0, 65.0],
        )
        assert count_strings_at_cap(reading, cfg, 80.0) == 0

    def test_some_at_cap(self, cfg: Config):
        reading = make_reading(
            ac_power=900,
            dc_powers=[300.0, 200.0, 310.0, 100.0],
        )
        assert count_strings_at_cap(reading, cfg, 80.0) == 2


class TestCountUsableStrings:
    def test_all_usable(self, cfg: Config):
        reading = make_reading(
            ac_power=1100,
            dc_powers=[250.0, 260.0, 240.0, 230.0],
        )
        assert count_usable_strings(reading, cfg, 80.0) == 4

    def test_some_blocked(self, cfg: Config):
        reading = make_reading(
            ac_power=500,
            dc_powers=[250.0, 100.0, 240.0, 80.0],
        )
        assert count_usable_strings(reading, cfg, 80.0) == 2

    def test_all_blocked(self, cfg: Config):
        reading = make_reading(
            ac_power=50,
            dc_powers=[40.0, 30.0, 35.0, 25.0],
        )
        assert count_usable_strings(reading, cfg, 80.0) == 0


class TestCalculateNewLimit:
    def test_night_mode(self, cfg: Config):
        reading = make_reading(ac_power=5, dc_powers=[1, 1, 1, 1])
        assert calculate_new_limit(reading, 80.0, cfg) is None

    def test_overproduction_decrease(self, cfg: Config):
        reading = make_reading(ac_power=900, dc_powers=[220, 220, 220, 220])
        result = calculate_new_limit(reading, 80.0, cfg)
        assert result is not None
        assert result < 80.0

    def test_overproduction_decrease_aggressive(self, cfg: Config):
        reading = make_reading(ac_power=1200, dc_powers=[300, 300, 300, 300])
        result = calculate_new_limit(reading, 80.0, cfg)
        assert result is not None
        assert result <= 70.0

    def test_underproduction_increase_all_usable(self, cfg: Config):
        reading = make_reading(ac_power=600, dc_powers=[250, 260, 240, 230])
        result = calculate_new_limit(reading, 80.0, cfg)
        assert result is not None
        assert result == 85.0

    def test_underproduction_increase_partial(self, cfg: Config):
        reading = make_reading(ac_power=400, dc_powers=[250, 50, 240, 30])
        result = calculate_new_limit(reading, 80.0, cfg)
        assert result is not None
        assert result >= 85.0

    def test_underproduction_no_increase_all_blocked(self, cfg: Config):
        reading = make_reading(ac_power=50, dc_powers=[30, 25, 35, 20])
        assert calculate_new_limit(reading, 80.0, cfg) is None

    def test_within_hysteresis_no_change(self, cfg: Config):
        reading = make_reading(ac_power=790, dc_powers=[200, 200, 200, 200])
        assert calculate_new_limit(reading, 80.0, cfg) is None

    def test_clamp_at_min(self, cfg: Config):
        reading = make_reading(ac_power=900, dc_powers=[300, 300, 300, 300])
        result = calculate_new_limit(reading, 52.0, cfg)
        assert result is not None
        assert result >= cfg.min_limit_pct

    def test_clamp_at_max(self, cfg: Config):
        reading = make_reading(ac_power=400, dc_powers=[300, 300, 300, 300])
        result = calculate_new_limit(reading, 98.0, cfg)
        assert result is not None
        assert result <= cfg.max_limit_pct

    def test_insignificant_change(self, cfg: Config):
        reading = make_reading(ac_power=400, dc_powers=[300, 300, 300, 300])
        result = calculate_new_limit(reading, 99.6, cfg)
        assert result is None


class TestSmootherIntegration:
    def test_rate_limits_increases(self, cfg: Config):
        smoother = Smoother(max_increases=2, window_s=60)
        reading = make_reading(ac_power=400, dc_powers=[250, 260, 240, 230])
        now = 1000.0

        r1 = calculate_new_limit(reading, 80.0, cfg, smoother, now)
        assert r1 == 85.0

        r2 = calculate_new_limit(reading, 85.0, cfg, smoother, now + 1)
        assert r2 == 90.0

        r3 = calculate_new_limit(reading, 90.0, cfg, smoother, now + 2)
        assert r3 is None

    def test_decreases_not_rate_limited(self, cfg: Config):
        smoother = Smoother(max_increases=1, window_s=60)
        reading = make_reading(ac_power=1000, dc_powers=[250, 260, 240, 230])
        result = calculate_new_limit(reading, 80.0, cfg, smoother, 1000.0)
        assert result is not None
        assert result < 80.0

    def test_window_expiry_allows_increases(self, cfg: Config):
        smoother = Smoother(max_increases=1, window_s=30)
        reading = make_reading(ac_power=400, dc_powers=[250, 260, 240, 230])

        r1 = calculate_new_limit(reading, 80.0, cfg, smoother, 1000.0)
        assert r1 == 85.0

        r2 = calculate_new_limit(reading, 85.0, cfg, smoother, 1000.5)
        assert r2 is None

        r3 = calculate_new_limit(reading, 85.0, cfg, smoother, 1031.0)
        assert r3 == 90.0
