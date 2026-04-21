#!/usr/bin/env python3
"""
Debug script for Hidroelectrica iHidro authentication and API.
Run this to test authentication and all endpoints outside of Home Assistant.

Usage:
    python3 scripts/test.py
    HIDRO_USERNAME=user HIDRO_PASSWORD=pass python3 scripts/test.py
"""

import asyncio
import json
import logging
import os
import re
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()

# Portal constants
PORTAL_BASE = "https://ihidro.ro/portal"
LOGIN_URL = f"{PORTAL_BASE}/"
DASHBOARD_URL = f"{PORTAL_BASE}/Dashboard.aspx"
BILL_DASHBOARD_URL = f"{PORTAL_BASE}/BillDashboard.aspx"
BILLING_HISTORY_URL = f"{PORTAL_BASE}/BillingHistory.aspx"
INDEX_HISTORY_URL = f"{PORTAL_BASE}/IndexHistory.aspx"
SELF_METER_URL = f"{PORTAL_BASE}/SelfMeterReading.aspx"
USAGES_URL = f"{PORTAL_BASE}/Usages.aspx"
CSRF_FIELD_NAME = "ctl00$hdnCSRFToken"

logging.basicConfig(level=logging.WARNING)
_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def login(session: aiohttp.ClientSession, username: str, password: str) -> str | None:
    """Log in and return the CSRF token, or None on failure."""
    ajax_base = {
        "Content-Type": "application/json; charset=utf-8",
        "x-requested-with": "XMLHttpRequest",
    }

    # Step 1 – establish session cookie
    async with session.get(LOGIN_URL) as resp:
        await resp.read()

    # Step 2 – init server-side session state
    async with session.post(
        f"{PORTAL_BASE}/default.aspx/updateState",
        json={},
        headers=ajax_base,
    ) as resp:
        await resp.read()

    # Step 3 – validateLogin
    payload = {
        "username": username,
        "password": password,
        "rememberme": False,
        "calledFrom": "LN",
        "ExternalLoginId": "",
        "LoginMode": "1",
        "utilityAcountNumber": "",
        "token": None,
        "isEdgeBrowser": False,
    }
    async with session.post(
        f"{PORTAL_BASE}/default.aspx/validateLogin",
        json=payload,
        headers=ajax_base,
    ) as resp:
        raw = await resp.text()

    try:
        outer = json.loads(raw)
        result = json.loads(outer.get("d", "null"))
    except (json.JSONDecodeError, TypeError):
        result = None

    if result is None:
        print("❌ validateLogin returned unparseable response")
        return None

    if isinstance(result, dict) and "dtException" in result:
        exc = result["dtException"]
        msg = exc[0].get("MessageInformation", "") if isinstance(exc, list) and exc else ""
        print(f"❌ Server error: {msg}")
        return None

    if isinstance(result, dict) and "dtResponse" in result:
        resp_list = result["dtResponse"]
        msg = resp_list[0].get("Message", "") if isinstance(resp_list, list) and resp_list else ""
        print(f"❌ Login failed: {msg}")
        return None

    # Step 4 – extract CSRF token from Dashboard page
    async with session.get(DASHBOARD_URL) as resp:
        html = await resp.text()

    m = re.search(
        r'<input[^>]+name="' + re.escape(CSRF_FIELD_NAME) + r'"[^>]+value="([^"]*)"',
        html,
        re.IGNORECASE,
    ) or re.search(
        r'<input[^>]+value="([^"]*)"[^>]+name="' + re.escape(CSRF_FIELD_NAME) + r'"',
        html,
        re.IGNORECASE,
    ) or re.search(
        r'<input[^>]+id="' + re.escape(CSRF_FIELD_NAME) + r'"[^>]+value="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    if not m:
        print("❌ CSRF token not found in Dashboard page")
        return None

    return m.group(1)


def ajax_headers(csrf_token: str) -> dict:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "x-requested-with": "XMLHttpRequest",
        "isajax": "1",
        "csrftoken": csrf_token,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def post(
    session: aiohttp.ClientSession,
    csrf_token: str,
    url: str,
    payload: dict,
) -> object:
    """POST and return the decoded ``d`` value."""
    async with session.post(
        url,
        json=payload,
        headers=ajax_headers(csrf_token),
    ) as resp:
        resp.raise_for_status()
        envelope = await resp.json(content_type=None)
        d = envelope.get("d")
        if isinstance(d, str):
            try:
                return json.loads(d)
            except json.JSONDecodeError:
                return d
        return d


def _print(label: str, data: object) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(repr(data))


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------

async def run_tests(session: aiohttp.ClientSession, username: str, password: str) -> None:
    print("\n🔐 Logging in...")
    csrf_token = await login(session, username, password)
    if not csrf_token:
        print("Login FAILED — aborting.")
        return
    print(f"✅ Login OK  |  CSRF: {csrf_token[:12]}…\n")

    # ----------------------------------------------------------------
    # 1. Billing
    # ----------------------------------------------------------------
    print("─" * 50)
    print("📡 BillDashboard / LoadBilling")
    try:
        data = await post(session, csrf_token, f"{BILL_DASHBOARD_URL}/LoadBilling", {"IsDashboard": 1})
        print("✅ OK")
        _print("   ", data)
    except Exception as e:
        print(f"❌ {e}")

    print("\n📡 BillDashboard / BindUnpaidInvoicesdetailsinGrid")
    try:
        data = await post(session, csrf_token, f"{BILL_DASHBOARD_URL}/BindUnpaidInvoicesdetailsinGrid", {})
        print("✅ OK")
        _print("   ", data)
    except Exception as e:
        print(f"❌ {e}")

    # ----------------------------------------------------------------
    # 2. Invoice history
    # ----------------------------------------------------------------
    print("\n📡 BillingHistory / LoadW2UIGridData")
    try:
        data = await post(
            session, csrf_token,
            f"{BILLING_HISTORY_URL}/LoadW2UIGridData",
            {"tabType": "menu1", "fromDate": "", "toDate": "", "invoiceType": ""},
        )
        print("✅ OK")
        if isinstance(data, list):
            print(f"   {len(data)} invoice(s) returned")
            if data:
                # Show unique invoice types
                types = sorted({inv.get("invoiceType", "?") for inv in data if isinstance(inv, dict)})
                print(f"   Invoice types: {types}")
                _print("   First invoice: ", data[0])
        else:
            _print("   ", data)
    except Exception as e:
        print(f"❌ {e}")

    # ----------------------------------------------------------------
    # 3. Meter / POD
    # ----------------------------------------------------------------
    print("\n📡 IndexHistory / GetAllPODBind")
    installation = None
    pod = None
    meter_entity = None
    try:
        data = await post(session, csrf_token, f"{INDEX_HISTORY_URL}/GetAllPODBind", {})
        print("✅ OK")
        _print("   ", data)
        if isinstance(data, dict):
            pods = data.get("Data", [])
            if pods:
                first = pods[0]
                installation = (
                    first.get("InstallationNumber")
                    or first.get("Installation")
                    or first.get("installation")
                )
                pod = (
                    first.get("POD")
                    or first.get("Pod")
                    or first.get("pod")
                )
                print(f"   → installation={installation}, pod={pod}")
    except Exception as e:
        print(f"❌ {e}")

    if installation and pod:
        print(f"\n📡 SelfMeterReading / LoadW2UIGridData  (installation={installation}, pod={pod})")
        try:
            data = await post(
                session, csrf_token,
                f"{SELF_METER_URL}/LoadW2UIGridData",
                {"installation": installation, "podvalue": pod},
            )
            print("✅ OK")
            _print("   ", data)
            if isinstance(data, list) and data:
                meter_entity = data[0]
        except Exception as e:
            print(f"❌ {e}")

        if meter_entity:
            from datetime import date as _date
            today = _date.today().strftime("%d/%m/%Y")
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
                            "UtilityAccountNumber": meter_entity.get("UtilityAccountNumber", ""),
                            "prevMRResult": meter_entity.get("PrevMRResult", ""),
                            "newmeterread": "0",
                        }
                    ]
                },
                "installation_number": installation,
                "pod_value": meter_entity.get("POD", ""),
            }
            print("\n📡 SelfMeterReading / GetMeterValue  (estimated index probe)")
            try:
                data = await post(session, csrf_token, f"{SELF_METER_URL}/GetMeterValue", payload)
                print("✅ OK")
                _print("   Estimated value: ", data)
            except Exception as e:
                print(f"❌ {e}")

    # ----------------------------------------------------------------
    # 4. Usage
    # ----------------------------------------------------------------
    for test_year in ["", "2025", "2026"]:
        label = f"usageyear={test_year!r}" if test_year else "usageyear='' (default/rolling)"
        print(f"\n📡 Usages / LoadUsage  [{label}]")
        try:
            data = await post(
                session, csrf_token,
                f"{USAGES_URL}/LoadUsage",
                {
                    "UsageOrGeneration": "1",
                    "Type": "D",
                    "Mode": "M",
                    "strDate": "",
                    "hourlyType": "H",
                    "SeasonId": "",
                    "weatherOverlay": 0,
                    "usageyear": test_year,
                    "MeterNumber": "",
                    "DateFromDaily": "",
                    "DateToDaily": "",
                    "IsNonAmi": True,
                },
            )
            print("✅ OK")
            if isinstance(data, dict):
                series = data.get("objUsageGenerationResultSetTwo", [])
                months = [(e.get("Month"), e.get("Year"), e.get("value")) for e in series]
                print(f"   Series ({len(series)} entries): {months}")
            else:
                _print("   ", data)
        except Exception as e:
            print(f"❌ {e}")

    # ----------------------------------------------------------------
    # 5. Index history — find correct payload for LoadW2UIGridData
    # ----------------------------------------------------------------
    print("\n─" * 50)
    print("📡 IndexHistory — scraping page JS for endpoint clues")
    try:
        async with session.get(f"{INDEX_HISTORY_URL}") as resp:
            page_html = await resp.text()
        # Find all WebMethod-style JS calls (PageMethods.xxx or $.ajax url patterns)
        import re as _re
        calls = _re_findall = _re.findall(
            r'IndexHistory\.aspx/(\w+)|PageMethods\.(\w+)|\.ajax\([^)]*url[^)]*IndexHistory[^)]*\)',
            page_html,
        )
        method_names = [m for pair in calls for m in pair if m]
        print(f"   Found JS method references: {sorted(set(method_names))}")
        # Also look for payload field names
        fields = _re.findall(r'"(installation|pod|podvalue|Installation|POD|Pod|contractAccountID|accountID)"', page_html)
        print(f"   Found payload field names: {sorted(set(fields))}")
    except Exception as e:
        print(f"❌ {e}")

    print("\n📡 IndexHistory / LoadW2UIGridData — probing payload variants")
    pod_info = {"installation": installation or "", "pod": pod or ""}
    payloads_to_try = [
        {"installation": installation or "", "podvalue": pod or ""},
        {"installation": installation or "", "pod": pod or ""},
        {"Installation": installation or "", "POD": pod or ""},
        {"installation": installation or "", "podvalue": pod or "", "fromDate": "", "toDate": ""},
        {"installation": installation or "", "pod": pod or "", "fromDate": "", "toDate": ""},
        {"contractAccountID": "8000863947", "installation": installation or "", "pod": pod or ""},
    ]
    for payload in payloads_to_try:
        try:
            data = await post(session, csrf_token, f"{INDEX_HISTORY_URL}/LoadW2UIGridData", payload)
            count = len(data) if isinstance(data, list) else ("dict" if isinstance(data, dict) else type(data).__name__)
            print(f"   payload={list(payload.keys())} → {count} items")
            if isinstance(data, list) and data:
                _print("   First: ", data[0])
                break
            elif isinstance(data, dict) and data:
                _print("   ", data)
                break
        except Exception as e:
            print(f"   payload={list(payload.keys())} → ❌ {e}")

    print("\n✅ All tests complete.")


async def main() -> None:
    print("Hidroelectrica iHidro — Debug Tool")
    print("=" * 40)

    env_user = os.getenv("HIDRO_USERNAME", "").strip()
    env_pass = os.getenv("HIDRO_PASSWORD", "")
    username = env_user or input("Username: ").strip()
    password = env_pass or input("Password: ")

    if not username or not password:
        print("❌ Username and password are required")
        sys.exit(1)

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await run_tests(session, username, password)


if __name__ == "__main__":
    asyncio.run(main())
