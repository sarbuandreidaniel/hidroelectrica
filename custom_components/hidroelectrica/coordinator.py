"""Data update coordinator for Hidroelectrica integration."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HidroelectricaAPI
from .auth import HidroelectricaAuth
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HidroelectricaCoordinator(DataUpdateCoordinator):
    """Fetches and caches data from the iHidro portal."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )
        self._username = username
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._auth: HidroelectricaAuth | None = None
        self._api: HidroelectricaAPI | None = None
        # POD info is stable — fetch once per session
        self._pod_info: dict | None = None

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Fetch all data from the iHidro portal."""
        try:
            await self._ensure_authenticated()
            return await self._fetch_all()
        except ConfigEntryAuthFailed:
            raise
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                # Invalidate token so the next poll triggers a full re-login
                if self._auth:
                    self._auth.csrf_token = ""
                raise UpdateFailed(f"Session expired (HTTP {err.status})") from err
            raise UpdateFailed(f"HTTP error {err.status}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Unexpected Hidroelectrica update error: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._auth = None
        self._api = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_authenticated(self) -> None:
        """Create the session and log in if needed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
            self._auth = HidroelectricaAuth(
                self._session, self._username, self._password
            )
            self._api = HidroelectricaAPI(self._session, self._auth)
            self._pod_info = None  # reset cache for new session

        if not self._auth.csrf_token:
            ok = await self._auth.async_login()
            if not ok:
                raise ConfigEntryAuthFailed(
                    "Could not log in to iHidro — check username and password"
                )

    async def _fetch_all(self) -> dict:
        """Collect data from every relevant API endpoint."""
        assert self._api is not None  # guaranteed by _ensure_authenticated

        # POD / installation info — stable, fetch once
        if self._pod_info is None:
            self._pod_info = await self._api.get_pod_info()

        data: dict = {}

        # Billing
        try:
            data["billing"] = await self._api.get_billing()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not fetch billing data: %s", err)
            data["billing"] = {}

        # Unpaid invoices
        try:
            invoices = await self._api.get_unpaid_invoices()
            data["unpaid_invoices"] = invoices[0] if invoices else {}
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not fetch unpaid invoices: %s", err)
            data["unpaid_invoices"] = {}

        # Meter readings + estimated current value
        if self._pod_info:
            installation = self._pod_info.get("installation", "")
            pod = self._pod_info.get("pod", "")
            try:
                readings = await self._api.get_meter_readings(installation, pod)
                data["meter"] = _parse_meter_readings(readings)
                consumed_entity = next(
                    (r for r in readings if r.get("Registers") == "1.8.0"),
                    None,
                )
                if consumed_entity:
                    estimated = await self._api.get_estimated_meter_value(
                        consumed_entity, installation
                    )
                    data["meter"]["estimated_value"] = estimated
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Could not fetch meter data: %s", err)
                data["meter"] = {}

            # Index history — full meter readings for consumption history sensors
            try:
                index_readings = await self._api.get_index_history(installation, pod)
                data["index_history"] = _parse_index_history(index_readings)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Could not fetch index history: %s", err)
                data["index_history"] = {}
        else:
            data["meter"] = {}
            data["index_history"] = {}

        # Usage — rolling 12-month window (usageyear parameter is ignored by the API)
        try:
            usage_raw = await self._api.get_usage()
            data["usage"] = _parse_usage(usage_raw)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not fetch usage data: %s", err)
            data["usage"] = {}

        # Invoice history
        try:
            data["invoice_history"] = await self._api.get_invoice_history()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not fetch invoice history: %s", err)
            data["invoice_history"] = []

        return data


# ------------------------------------------------------------------
# Data-parsing helpers
# ------------------------------------------------------------------


def _parse_index_history(readings: list[dict]) -> dict:
    """Build a dict of {(year, month): kwh} from raw index readings.

    Each reading has a cumulative ``Index`` (kWh).  Monthly consumption is
    derived as the delta between the first and last reading within each
    calendar month (sorted by date), using only ``Registers == '1.8.0'``
    (consumed energy).
    """
    from datetime import datetime as _dt

    # Keep only consumed-energy readings with a parseable date
    entries: list[tuple[_dt, int]] = []
    for r in readings:
        if r.get("Registers") != "1.8.0":
            continue
        date_str = r.get("Date", "")
        index_val = r.get("Index")
        if not date_str or index_val is None:
            continue
        try:
            parts = date_str.strip().split("/")
            if len(parts) == 3:
                d = _dt(int(parts[2]), int(parts[1]), int(parts[0]))
                entries.append((d, int(index_val)))
        except (ValueError, TypeError):
            continue

    if not entries:
        return {}

    entries.sort(key=lambda x: x[0])

    # Group by (year, month), keep min/max index
    from collections import defaultdict
    by_month: dict[tuple[int, int], list[int]] = defaultdict(list)
    for dt, idx in entries:
        by_month[(dt.year, dt.month)].append(idx)

    # Consumption in a month = last index of month − last index of previous month
    sorted_months = sorted(by_month.keys())
    result: dict[tuple[int, int], float] = {}
    for i, ym in enumerate(sorted_months):
        if i == 0:
            # First month: delta within the month itself
            vals = by_month[ym]
            result[ym] = float(max(vals) - min(vals))
        else:
            prev_ym = sorted_months[i - 1]
            prev_last = max(by_month[prev_ym])
            curr_last = max(by_month[ym])
            result[ym] = float(max(0.0, curr_last - prev_last))

    return result


def _parse_meter_readings(readings: list[dict]) -> dict:
    """Flatten the per-register reading list into a single dict."""
    result: dict = {}
    for r in readings:
        register = r.get("Registers", "")
        if register == "1.8.0":
            result["consumed_index"] = _safe_int(r.get("PrevMRResult"))
            result["reading_date"] = r.get("prevMRDate", "")
            result["serial_number"] = r.get("SerialNumber", "")
            result["pod"] = r.get("POD", "")
            result["distributor"] = r.get("Distributor", "")
        elif register == "1.8.0_P":
            result["produced_index"] = _safe_int(r.get("PrevMRResult"))
    return result


def _parse_usage(raw: dict) -> dict:
    """Extract last-month stats and long-term averages from the usage payload."""
    result: dict = {}
    series = raw.get("objUsageGenerationResultSetTwo", [])
    if series:
        last = series[-1]
        result["last_month_cost"] = _safe_float(last.get("UsageValue"))
        result["last_month_kwh"] = _safe_float(last.get("value"))
        result["last_month_label"] = (
            f"{last.get('Month', '')}/{last.get('Year', '')}"
        )

    tentative = raw.get("getTentativeData", [])
    if tentative:
        t = tentative[0]
        result["monthly_avg_cost"] = _safe_float(t.get("Average"))
        result["monthly_max_cost"] = _safe_float(t.get("Highest"))

    return result


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
