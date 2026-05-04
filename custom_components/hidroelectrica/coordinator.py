"""Data update coordinator for Hidroelectrica integration."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HidroelectricaAPI
from .auth import HidroelectricaAuth, HidroelectricaServerError
from .const import CONF_PASSWORD, CONF_USERNAME, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HidroelectricaCoordinator(DataUpdateCoordinator[dict]):
    """Fetches and caches data from the iHidro portal."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )
        self._username: str = config_entry.data[CONF_USERNAME]
        self._password: str = config_entry.data[CONF_PASSWORD]
        self._session: aiohttp.ClientSession | None = None
        self._auth: HidroelectricaAuth | None = None
        self._api: HidroelectricaAPI | None = None
        # POD info is stable — cache per contract (keyed by utility_account_number)
        self._pod_info_cache: dict[str, dict | None] = {}
        # Staged meter values set by number entities, consumed by the submit button
        self.pending_meter_index: dict[str, dict[str, int]] = {}

    @property
    def api(self) -> "HidroelectricaAPI | None":
        """Expose the underlying API client (used by button entities)."""
        return self._api

    def get_pod_info(self, uan: str) -> dict | None:
        """Return cached POD info for the given utility account number."""
        return self._pod_info_cache.get(uan)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Fetch all data from the iHidro portal."""
        try:
            await self._ensure_authenticated()
            data = await self._fetch_all()

            # Detect silent server-side session expiry: when the ASP.NET session
            # cookie expires the portal returns {"d": null} for every AJAX call
            # (HTTP 200, valid JSON, no exception).  The symptom is all contracts
            # returning empty billing dicts.  When detected, close the stale
            # session and re-authenticate before returning.
            if self._session_likely_expired(data):
                _LOGGER.debug(
                    "Hidroelectrica: silent session expiry detected — re-authenticating"
                )
                await self.async_close()
                await self._ensure_authenticated()
                data = await self._fetch_all()

            return data
        except ConfigEntryAuthFailed:
            raise
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                # Invalidate token so the next poll triggers a full re-login
                if self._auth:
                    self._auth.csrf_token = ""
                raise ConfigEntryAuthFailed(f"Session expired (HTTP {err.status})") from err
            raise UpdateFailed(f"HTTP error {err.status}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Unexpected Hidroelectrica update error: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _session_likely_expired(self, data: dict) -> bool:
        """Return True when all contracts have empty billing data.

        When the server-side ASP.NET session expires the portal returns
        ``{"d": null}`` for every AJAX endpoint (HTTP 200, no exception).
        Billing data is always present for a healthy session, so an empty
        billing dict across all contracts is a reliable expiry signal.
        """
        contracts = data.get("contracts", [])
        if not contracts:
            return False
        for contract in contracts:
            uan = contract["utility_account_number"]
            if data.get(uan, {}).get("billing"):
                return False  # at least one contract has real data
        return True  # every contract returned empty billing

    async def async_close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._auth = None
        self._api = None
        self._pod_info_cache = {}

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
            self._pod_info_cache = {}  # reset cache for new session

        if not self._auth.csrf_token:
            try:
                ok = await self._auth.async_login()
            except HidroelectricaServerError as err:
                raise UpdateFailed(
                    f"Transient iHidro server error — will retry: {err}"
                ) from err
            except aiohttp.ClientError as err:
                raise UpdateFailed(f"Connection error during login: {err}") from err
            if not ok:
                raise ConfigEntryAuthFailed(
                    "Could not log in to iHidro — check username and password"
                )

    async def _fetch_all(self) -> dict:
        """Collect data from every relevant API endpoint for all contracts."""
        assert self._api is not None  # guaranteed by _ensure_authenticated
        assert self._auth is not None

        contracts = self._auth.contracts
        if not contracts:
            _LOGGER.warning("Hidroelectrica: no contracts found after login")
            return {"contracts": []}

        result: dict = {"contracts": contracts}

        # Fetch the submission window once per refresh (not per contract — it's
        # account-level and requires the SelfMeterReading page to be loaded).
        try:
            result["meter_reading_window"] = await self._api.get_meter_reading_window()
            _LOGGER.debug(
                "Hidroelectrica: meter reading window: %s", result["meter_reading_window"]
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch meter reading window: %s", err)
            result["meter_reading_window"] = {"open_date": None, "close_date": None}

        for contract in contracts:
            uan = contract["utility_account_number"]
            address_id = contract["address_id"]

            # Switch the server-side session to this contract
            try:
                await self._api.switch_contract(address_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not switch to contract %s (%s): %s", uan, contract["name"], err
                )
                result[uan] = {}
                continue

            result[uan] = await self._fetch_contract_data(uan)

        return result

    async def _fetch_contract_data(self, uan: str) -> dict:
        """Fetch all data for the currently active contract."""
        assert self._api is not None

        # POD / installation info — stable, cache per contract
        if uan not in self._pod_info_cache:
            self._pod_info_cache[uan] = await self._api.get_pod_info()

        pod_info = self._pod_info_cache[uan]
        data: dict = {"uan": uan}

        # Billing
        try:
            data["billing"] = await self._api.get_billing()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Could not fetch billing data: %s", uan, err)
            data["billing"] = {}

        # Unpaid invoices
        # NOTE: the portal's BindUnpaidInvoicesdetailsinGrid endpoint does not
        # respect the active contract switch — it returns the default contract's
        # invoices regardless.  Each invoice includes a ``contractAccountID``
        # field matching its UAN, so we filter client-side to avoid showing the
        # wrong contract's debt on every device.
        try:
            invoices = await self._api.get_unpaid_invoices()
            matching = [
                inv for inv in invoices
                if str(inv.get("contractAccountID", "")) == str(uan)
            ]
            data["unpaid_invoices"] = matching[0] if matching else {}
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Could not fetch unpaid invoices: %s", uan, err)
            data["unpaid_invoices"] = {}

        # Meter readings + estimated current value
        if pod_info:
            installation = pod_info.get("installation", "")
            pod = pod_info.get("pod", "")
            try:
                readings = await self._api.get_meter_readings(installation, pod)
                data["meter"] = _parse_meter_readings(readings)
                data["meter_readings"] = readings  # raw list for number/button entities

                # Fetch the portal's estimated current value for each register
                estimates: dict[str, int | None] = {}
                for reading in readings:
                    try:
                        est = await self._api.get_estimated_meter_value(
                            reading, installation
                        )
                        estimates[reading.get("Registers", "")] = est
                    except Exception as est_err:  # noqa: BLE001
                        _LOGGER.debug(
                            "[%s] Could not fetch estimate for register %s: %s",
                            uan,
                            reading.get("Registers"),
                            est_err,
                        )
                data["meter_estimates"] = estimates
                data["meter"]["estimated_value"] = estimates.get("1.8.0")
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("[%s] Could not fetch meter data: %s", uan, err)
                data["meter"] = {}
                data["meter_readings"] = []
                data["meter_estimates"] = {}

            # Index history
            try:
                index_readings = await self._api.get_index_history(installation, pod)
                data["index_history"] = _parse_index_history(index_readings)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("[%s] Could not fetch index history: %s", uan, err)
                data["index_history"] = {}
        else:
            data["meter"] = {}
            data["meter_readings"] = []
            data["meter_estimates"] = {}
            data["index_history"] = {}

        # Usage
        try:
            usage_raw = await self._api.get_usage()
            data["usage"] = _parse_usage(usage_raw)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Could not fetch usage data: %s", uan, err)
            data["usage"] = {}

        # Invoice history
        try:
            data["invoice_history"] = await self._api.get_invoice_history()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Could not fetch invoice history: %s", uan, err)
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
