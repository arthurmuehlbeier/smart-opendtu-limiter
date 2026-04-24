"""OpenDTU HTTP client for Smart OpenDTU Limiter.

Handles all communication with the OpenDTU REST API including:
- Fetching inverter live data
- Querying current limit status
- Setting new power limits
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import requests

from .inverter import InverterReading

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger("opendtu_client")


class OpenDTUClient:
    """HTTP client for OpenDTU REST API.

    Provides methods to read inverter state and update power limits.
    Uses HTTP Basic Auth with configurable timeout.

    Attributes:
        base_url: Base URL of the OpenDTU instance.
        inverter_serial: Serial number of the inverter to control.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the OpenDTU client.

        Args:
            config: Config object with URL, credentials, and inverter serial.
        """
        self._config = config
        self._session = requests.Session()
        self._session.auth = (config.opendtu_user, config.opendtu_pass)
        self._session.timeout = 10

    def _url(self, path: str) -> str:
        """Build full URL for an API endpoint."""
        return f"{self._config.opendtu_url}{path}"

    def fetch_inverter_data(self) -> InverterReading | None:
        """Fetch current inverter state from OpenDTU.

        Returns:
            InverterReading with current AC/DC power and limit info,
            or None if the API call fails.
        """
        try:
            resp = self._session.get(
                self._url("/api/livedata/status"),
                params={"inv": self._config.inverter_serial},
            )
            resp.raise_for_status()
            inverters = resp.json().get("inverters", [])

            if not inverters:
                log.warning("No inverter data received from OpenDTU")
                return None

            return InverterReading.parse_api_response(
                inverters[0],
                self._config.num_strings,
            )
        except requests.RequestException as exc:
            log.error("API error (livedata): %s", exc)
            return None

    def fetch_limit_status(self) -> dict[str, Any] | None:
        """Fetch current limit status from OpenDTU.

        Returns:
            Dict with current limit_relative and limit_absolute values,
            or None if the API call fails.
        """
        try:
            resp = self._session.get(self._url("/api/limit/status"))
            resp.raise_for_status()
            return resp.json().get(self._config.inverter_serial)
        except requests.RequestException as exc:
            log.error("API error (limit status): %s", exc)
            return None

    def set_limit(self, percent: float, dry_run: bool = False) -> bool:
        """Set inverter power limit.

        Args:
            percent: Target power limit as percentage (0-100).
            dry_run: If True, log but don't actually send the command.

        Returns:
            True if limit was set successfully, False otherwise.
        """
        percent = round(
            max(self._config.min_limit_pct, min(self._config.max_limit_pct, percent))
        )

        if dry_run:
            log.info("[DRY-RUN] Would set limit to %d%%", percent)
            return True

        payload = json.dumps({
            "serial": self._config.inverter_serial,
            "limit_type": 1,
            "limit_value": percent,
        })

        try:
            resp = self._session.post(
                self._url("/api/limit/config"),
                data=f"data={payload}",
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("type") == "success":
                log.info("Limit set: %d%% (%dW)", percent, self._pct_to_watt(percent))
                return True

            log.warning("Limit rejected: %s", result)
            return False

        except requests.RequestException as exc:
            log.error("API error (limit config): %s", exc)
            return False

    def _pct_to_watt(self, pct: float) -> int:
        """Convert percentage to watts."""
        return int(pct / 100.0 * self._config.inverter_max_watt)
