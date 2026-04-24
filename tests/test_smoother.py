"""Tests for the Smoother rate-limiter."""


from src.smoother import Smoother


class TestSmoother:
    def test_initial_state_allows_increases(self):
        """New smoother should allow increases."""
        smooth = Smoother(max_increases=3, window_s=60)
        assert smooth.can_increase(1000.0) is True

    def test_records_increase(self):
        """record_increase should track timestamps."""
        smooth = Smoother(max_increases=3, window_s=60)
        smooth.record_increase(1000.0)
        assert len(smooth._timestamps) == 1

    def test_max_increases_enforced(self):
        """Should block after max_increases is reached."""
        smooth = Smoother(max_increases=2, window_s=60)

        assert smooth.can_increase(1000.0) is True
        smooth.record_increase(1000.0)

        assert smooth.can_increase(1000.0) is True
        smooth.record_increase(1000.0)

        # Now at limit
        assert smooth.can_increase(1000.0) is False

    def test_old_timestamps_pruned(self):
        """Timestamps outside window should be pruned."""
        smooth = Smoother(max_increases=2, window_s=30)

        smooth.record_increase(1000.0)
        smooth.record_increase(1001.0)

        assert len(smooth._timestamps) == 2

        # Check at time 1032 (> 30s after first)
        assert smooth.can_increase(1032.0) is True
        assert len(smooth._timestamps) == 0  # All pruned

    def test_apply_passes_decreases(self):
        """apply() should return proposed value if lower (decrease)."""
        smooth = Smoother(max_increases=1, window_s=60)
        result = smooth.apply(80.0, 75.0, 1000.0)
        assert result == 75.0

    def test_apply_passes_increases_when_allowed(self):
        """apply() should return proposed value if increase is allowed."""
        smooth = Smoother(max_increases=1, window_s=60)
        result = smooth.apply(80.0, 85.0, 1000.0)
        assert result == 85.0

    def test_apply_blocks_increases_when_rate_limited(self):
        """apply() should return current if rate-limited."""
        smooth = Smoother(max_increases=1, window_s=60)
        smooth.record_increase(1000.0)

        result = smooth.apply(80.0, 85.0, 1001.0)
        assert result == 80.0  # Unchanged

    def test_reset_clears_timestamps(self):
        """reset() should clear all recorded timestamps."""
        smooth = Smoother(max_increases=2, window_s=60)
        smooth.record_increase(1000.0)
        smooth.record_increase(1001.0)

        smooth.reset()

        assert len(smooth._timestamps) == 0
        assert smooth.can_increase(2000.0) is True

    def test_no_timestamp_defaults_to_now(self):
        """can_increase() with no timestamp should use time.time()."""
        import time
        smooth = Smoother(max_increases=1, window_s=60)
        smooth.record_increase(time.time() - 120)  # Old timestamp

        # Should be pruned automatically
        assert smooth.can_increase() is True
