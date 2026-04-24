"""Inverter data models and parsing for Smart OpenDTU Limiter.

Contains the InverterReading dataclass that represents a snapshot of
inverter state, plus parsing logic to extract data from OpenDTU API responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class InverterReading:
    """Snapshot of inverter state from OpenDTU API.

    Attributes:
        ac_power: Current AC power output in watts.
        dc_powers: List of DC string power values in watts (one per string).
        reachable: Whether the inverter is reachable (responds to commands).
        producing: Whether the inverter is currently producing power.
        limit_relative: Current power limit as percentage (0-100).
        limit_absolute: Current absolute power limit in watts.
    """

    ac_power: float
    dc_powers: list[float]
    reachable: bool
    producing: bool
    limit_relative: float
    limit_absolute: float

    @property
    def dc_total(self) -> float:
        """Total DC power from all strings."""
        return sum(self.dc_powers)

    def parse_api_response(data: dict[str, Any], num_strings: int) -> InverterReading | None:
        """Parse an inverter data dict from OpenDTU's livedata/status API.

        Args:
            data: Raw inverter dict from the API response.
            num_strings: Number of DC strings expected (used to parse DC arrays).

        Returns:
            InverterReading instance, or None if parsing fails.
        """
        try:
            ac_power = data["AC"]["0"]["Power"]["v"]
            dc_powers = [data["DC"][str(i)]["Power"]["v"] for i in range(num_strings)]

            return InverterReading(
                ac_power=ac_power,
                dc_powers=dc_powers,
                reachable=data.get("reachable", False),
                producing=data.get("producing", False),
                limit_relative=data.get("limit_relative", 0),
                limit_absolute=data.get("limit_absolute", 0),
            )
        except (KeyError, IndexError, TypeError):
            return None
