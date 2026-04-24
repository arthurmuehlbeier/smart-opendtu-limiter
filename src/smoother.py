"""Rate-limiting smoother for power limit changes.

Prevents oscillation by limiting how often the limit can increase.
This is critical for edge cases where intermittent shading causes
rapid limit cycling.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Smoother:
    """Rate-limits power limit increases to prevent oscillation.

    Uses a sliding window approach: tracks timestamps of limit increases
    and prevents new increases if too many occurred recently.

    Attributes:
        max_increases: Maximum number of increases allowed per window.
        window_s: Duration of the rate-limiting window in seconds.

    Example:
        >>> smooth = Smoother(max_increases=3, window_s=120)
        >>> smooth.can_increase(time.time())
        True
        >>> smooth.record_increase(time.time())
        >>> smooth.can_increase(time.time())  # May be False if limit reached
        False
    """

    max_increases: int = 3
    window_s: int = 120

    _timestamps: list[float] = field(default_factory=list)

    def can_increase(self, now: float | None = None) -> bool:
        """Check if a new limit increase is allowed.

        Args:
            now: Current timestamp. Defaults to time.time() if None.

        Returns:
            True if increase is allowed, False if rate-limited.
        """
        if now is None:
            import time
            now = time.time()

        # Prune old timestamps outside the window
        self._timestamps = [t for t in self._timestamps if now - t < self.window_s]
        return len(self._timestamps) < self.max_increases

    def record_increase(self, now: float | None = None) -> None:
        """Record a limit increase for rate-limiting purposes.

        Call this after each successful limit increase.

        Args:
            now: Current timestamp. Defaults to time.time() if None.
        """
        if now is None:
            import time
            now = time.time()
        self._timestamps.append(now)

    def apply(self, current: float, proposed: float, now: float | None = None) -> float:
        """Apply rate-limiting to a proposed new limit.

        If the proposed limit is lower (decrease), return it unchanged.
        If higher (increase), only allow it if rate-limiting permits.

        Args:
            current: Current limit percentage.
            proposed: Proposed new limit percentage.
            now: Current timestamp for rate-limit checks.

        Returns:
            The allowed limit (may be same as current if rate-limited).
        """
        if proposed <= current:
            return proposed

        if self.can_increase(now):
            self.record_increase(now)
            return proposed

        return current

    def reset(self) -> None:
        """Clear all recorded increase timestamps.

        Useful for testing or when restarting the controller.
        """
        self._timestamps.clear()
