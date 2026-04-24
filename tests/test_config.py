"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest

from src.config import Config, ConfigError


class TestConfigFromEnv:
    def test_missing_file_raises(self):
        """Missing .env should raise ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            Config.from_env(Path("/nonexistent/.env"))

    def test_required_fields(self):
        """Missing required fields should raise ConfigError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OPENDTU_URL=http://localhost\n")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigError, match="missing required key"):
                Config.from_env(path)
        finally:
            path.unlink()

    def test_invalid_integer_raises(self):
        """Non-integer for integer field should raise ConfigError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OPENDTU_URL=http://localhost\n")
            f.write("OPENDTU_USER=admin\n")
            f.write("OPENDTU_PASS=secret\n")
            f.write("INVERTER_SERIAL=1234567890\n")
            f.write("INVERTER_MAX_WATT=not_a_number\n")  # Invalid
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(ConfigError, match="not an integer"):
                Config.from_env(path)
        finally:
            path.unlink()

    def test_valid_env_loaded(self):
        """Valid .env should create Config with defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OPENDTU_URL=http://192.168.1.100\n")
            f.write("OPENDTU_USER=admin\n")
            f.write("OPENDTU_PASS=secret123\n")
            f.write("INVERTER_SERIAL=112233445566\n")
            f.flush()
            path = Path(f.name)

        try:
            cfg = Config.from_env(path)
            assert cfg.opendtu_url == "http://192.168.1.100"
            assert cfg.inverter_serial == "112233445566"
            assert cfg.target_w == 800  # Default
            assert cfg.step_pct == 5  # Default
        finally:
            path.unlink()

    def test_custom_values_overridden(self):
        """Custom values should override defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OPENDTU_URL=http://localhost\n")
            f.write("OPENDTU_USER=admin\n")
            f.write("OPENDTU_PASS=secret\n")
            f.write("INVERTER_SERIAL=1234567890\n")
            f.write("TARGET_W=1000\n")
            f.write("STEP_PCT=10\n")
            f.write("SMOOTHER_MAX_INCREASES=5\n")
            f.flush()
            path = Path(f.name)

        try:
            cfg = Config.from_env(path)
            assert cfg.target_w == 1000
            assert cfg.step_pct == 10
            assert cfg.smoother_max_increases == 5
        finally:
            path.unlink()

    def test_comments_ignored(self):
        """Comments (#) should be ignored."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("OPENDTU_URL=http://localhost\n")
            f.write("# Another comment\n")
            f.write("OPENDTU_USER=admin\n")
            f.write("OPENDTU_PASS=secret\n")
            f.write("INVERTER_SERIAL=1234567890\n")
            f.flush()
            path = Path(f.name)

        try:
            cfg = Config.from_env(path)
            assert cfg.opendtu_url == "http://localhost"
        finally:
            path.unlink()


class TestConfigProperties:
    def test_num_strings(self):
        """num_strings should calculate based on inverter_max_watt."""
        cfg = Config(
            opendtu_url="http://localhost",
            opendtu_user="admin",
            opendtu_pass="secret",
            inverter_serial="1234567890",
            inverter_max_watt=1600,
        )
        assert cfg.num_strings == 4  # 1600 / 400

        cfg2 = cfg.__class__(
            opendtu_url="http://localhost",
            opendtu_user="admin",
            opendtu_pass="secret",
            inverter_serial="1234567890",
            inverter_max_watt=800,
        )
        assert cfg2.num_strings == 2

    def test_hysteresis_low(self):
        """hysteresis_low should be target - hysteresis."""
        cfg = Config(
            opendtu_url="http://localhost",
            opendtu_user="admin",
            opendtu_pass="secret",
            inverter_serial="1234567890",
            target_w=800,
            hysteresis_w=20,
        )
        assert cfg.hysteresis_low == 780
