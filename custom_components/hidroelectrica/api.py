"""API client for the Hidroelectrica iHidro portal.

All portal endpoints follow the same pattern:
  POST <page>.aspx/<MethodName>
  Content-Type: application/json; charset=UTF-8
  Headers: csrftoken, isajax=1, x-requested-with=XMLHttpRequest

Every response is a JSON object ``{"d": <value>}`` where ``<value>`` is
either a native type (dict/list/int) or a JSON-encoded string that must be
decoded a second time.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import aiohttp

from .auth import HidroelectricaAuth
from .const import (
    BILL_DASHBOARD_URL,
    BILLING_HISTORY_URL,
    COMMON_URL,
    INDEX_HISTORY_URL,
    SELF_METER_URL,
    USAGES_URL,
)

_LOGGER = logging.getLogger(__name__)


class HidroelectricaAPI:
    """Makes authenticated AJAX requests to the iHidro portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: HidroelectricaAuth,
    ) -> None:
        self._session = session
        self._auth = auth

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------

    async def get_billing(self) -> dict:
        """Return balance (``ToTalBalance``) and due date (``BillDue``)."""
        result = await self._post(f"{BILL_DASHBOARD_URL}/LoadBilling", {"IsDashboard": 1})
        return result if isinstance(result, dict) else {}

    async def get_unpaid_invoices(self) -> list[dict]:
        """Return list of unpaid invoices."""
        result = await self._post(
            f"{BILL_DASHBOARD_URL}/BindUnpaidInvoicesdetailsinGrid", {}
        )
        return result if isinstance(result, list) else []

    async def get_invoice_history(self) -> list[dict]:
        """Return full invoice history (all paid and unpaid invoices)."""
        result = await self._post(
            f"{BILLING_HISTORY_URL}/LoadW2UIGridData",
            {"tabType": "menu1", "fromDate": "", "toDate": "", "invoiceType": ""},
        )
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Meter / POD
    # ------------------------------------------------------------------

    async def get_pod_info(self) -> dict | None:
        """Return the first POD/installation record for this account."""
        result = await self._post(f"{INDEX_HISTORY_URL}/GetAllPODBind", {})
        if not isinstance(result, dict):
            return None
        pods = result.get("Data", [])
        return pods[0] if pods else None

    async def get_index_history(self, installation: str, pod: str) -> list[dict]:
        """Return full meter index reading history for the given installation + POD."""
        result = await self._post(
            f"{INDEX_HISTORY_URL}/LoadW2UIGridData",
            {"installation": installation, "podvalue": pod},
        )
        return result if isinstance(result, list) else []

    async def get_meter_readings(self, installation: str, pod: str) -> list[dict]:
        """Return meter reading entities for the given installation + POD."""
        result = await self._post(
            f"{SELF_METER_URL}/LoadW2UIGridData",
            {"installation": installation, "podvalue": pod},
        )
        return result if isinstance(result, list) else []

    async def submit_meter_reading(
        self,
        meter_entities: list[dict],
        installation: str,
        pod: str,
    ) -> dict:
        """Submit meter readings for all registers to the iHidro portal.

        ``meter_entities`` is the same structure as ``UsageSelfMeterReadEntity``
        used by the page JS, with ``newmeterread`` set to the user's value.
        """
        payload = {
            "objSubmitMeterReadProxy": {
                "UsageSelfMeterReadEntity": meter_entities,
            },
            "installation_number": installation,
            "pod_value": pod,
        }
        result = await self._post(
            f"{SELF_METER_URL}/SubmitSelfMeterReading", payload
        )
        return result if isinstance(result, dict) else {"result": result}

    async def get_estimated_meter_value(
        self,
        meter_entity: dict,
        installation: str,
    ) -> int | None:
        """Return the portal's current estimated meter value (kWh).

        Sends a ``newmeterread=0`` probe which causes the server to compute
        and return its own estimate without submitting an actual reading.
        """
        today = date.today().strftime("%d/%m/%Y")
        payload = {
            "objMeterValueProxy": {
                "UsageSelfMeterReadEntity": [
                    {
                        "POD": meter_entity.get("POD", ""),
                        "SerialNumber": meter_entity.get("SerialNumber", ""),
                        "NewMeterReadDate": today,
                        "registerCat": meter_entity.get("Registers", ""),
                        "distributor": meter_entity.get("Distributor", ""),
                        "meterInterval": meter_entity.get("MeterInterval", ""),
                        "supplier": meter_entity.get("Supplier", ""),
                        "distCustomer": meter_entity.get("DistCustomer", ""),
                        "distCustomerId": meter_entity.get("DistCustomerId", ""),
                        "distContract": meter_entity.get("DistContract", ""),
                        "distContractDate": meter_entity.get("DistContractDate", ""),
                        "UtilityAccountNumber": meter_entity.get(
                            "UtilityAccountNumber", ""
                        ),
                        "prevMRResult": meter_entity.get("PrevMRResult", ""),
                        "newmeterread": "0",
                    }
                ]
            },
            "installation_number": installation,
            "pod_value": meter_entity.get("POD", ""),
        }
        result = await self._post(f"{SELF_METER_URL}/GetMeterValue", payload)
        # Server returns the estimated value as a bare integer
        try:
            return int(result)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Usage
    # ------------------------------------------------------------------

    async def get_usage(self) -> dict:
        """Return monthly usage chart data (rolling ~12-month window)."""
        result = await self._post(
            f"{USAGES_URL}/LoadUsage",
            {
                "UsageOrGeneration": "1",
                "Type": "D",
                "Mode": "M",
                "strDate": "",
                "hourlyType": "H",
                "SeasonId": "",
                "weatherOverlay": 0,
                "usageyear": "",
                "MeterNumber": "",
                "DateFromDaily": "",
                "DateToDaily": "",
                "IsNonAmi": True,
            },
        )
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Contract switching
    # ------------------------------------------------------------------

    async def switch_contract(self, address_id: str) -> None:
        """Switch the server-side session context to a different contract.

        The portal uses ``Common.aspx/HandleAddressDropDownChange`` (the same
        AJAX call the web page makes when the user selects a different entry in
        the "Selectați Cont Contract" dropdown) to update the active account in
        the server session.  All subsequent requests will return data for the
        newly selected contract until this is called again.
        """
        await self._post(
            f"{COMMON_URL}/HandleAddressDropDownChange",
            {"ddlAddressSelectedValue": address_id},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _post(self, url: str, payload: dict) -> Any:
        """POST *payload* as JSON and return the decoded ``d`` value."""
        async with self._session.post(
            url,
            json=payload,
            headers=self._auth.ajax_headers(),
        ) as resp:
            resp.raise_for_status()
            envelope = await resp.json(content_type=None)
            d = envelope.get("d")
            # Many endpoints double-encode: d is a JSON string
            if isinstance(d, str):
                try:
                    return json.loads(d)
                except json.JSONDecodeError:
                    return d
            return d
