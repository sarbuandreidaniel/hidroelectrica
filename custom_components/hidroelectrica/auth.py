"""Authentication for the Hidroelectrica iHidro portal.

Login flow
----------
The portal login is handled entirely by JavaScript AJAX calls, not a form POST.

1. GET the login page to obtain the session cookie (``ASP.NET_SessionId``).
2. POST to ``default.aspx/updateState`` (empty JSON body) to initialise the
   server-side session state — this is required before the login call.
3. POST to ``default.aspx/validateLogin`` with a JSON payload containing
   ``username``, ``password``, and other fields.
   A successful response has a ``d`` value whose decoded JSON contains
   ``[0].DashboardOption`` (not ``dtException``).
4. GET Dashboard.aspx and extract the hidden field ``ctl00$hdnCSRFToken``
   that must be sent as the ``csrftoken`` header on every subsequent XHR call.
"""

import json
import logging
import re

import aiohttp

from .const import CSRF_FIELD_NAME, DASHBOARD_URL, LOGIN_URL, PORTAL_BASE

_LOGGER = logging.getLogger(__name__)


class HidroelectricaServerError(Exception):
    """Raised when the iHidro server returns a transient error.

    Distinct from wrong-credential failures so the coordinator can
    raise ``UpdateFailed`` (retry next poll) instead of
    ``ConfigEntryAuthFailed`` (locks the entry until user action).
    """


class HidroelectricaAuth:
    """Manages session authentication for the iHidro portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self.csrf_token: str = ""
        self.contracts: list[dict] = []  # [{address_id, utility_account_number, name}]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def async_login(self) -> bool:
        """Log in and populate ``self.csrf_token``.

        Returns ``True`` on success, ``False`` when credentials are wrong
        or 2FA is required.

        Raises ``HidroelectricaServerError`` for transient server-side errors
        (maintenance pages, ``dtException`` responses, unparseable JSON) so the
        coordinator can convert them to ``UpdateFailed`` and retry next poll
        instead of locking the config entry.

        Raises ``aiohttp.ClientError`` for network/connection failures.
        """
        try:
            # ── Step 1: GET login page to establish the session cookie ──
            async with self._session.get(LOGIN_URL) as resp:
                await resp.read()  # consume body so the cookie is stored

            # ── Step 2: POST updateState (required to init server session) ──
            _ajax_base = {
                "Content-Type": "application/json; charset=utf-8",
                "x-requested-with": "XMLHttpRequest",
            }
            async with self._session.post(
                f"{PORTAL_BASE}/default.aspx/updateState",
                json={},
                headers=_ajax_base,
            ) as resp:
                await resp.read()

            # ── Step 3: POST validateLogin ──
            payload = {
                "username": self._username,
                "password": self._password,
                "rememberme": False,
                "calledFrom": "LN",
                "ExternalLoginId": "",
                "LoginMode": "1",
                "utilityAcountNumber": "",
                "token": None,  # null bypasses captcha check; empty string fails
                "isEdgeBrowser": False,
            }
            async with self._session.post(
                f"{PORTAL_BASE}/default.aspx/validateLogin",
                json=payload,
                headers=_ajax_base,
            ) as resp:
                raw = await resp.text()

            # Response: {"d": "<json-string>"}
            try:
                outer = json.loads(raw)
                result = json.loads(outer.get("d", "null"))
            except (json.JSONDecodeError, TypeError):
                result = None

            if result is None:
                _LOGGER.warning("Hidroelectrica validateLogin returned unparseable response")
                raise HidroelectricaServerError("Unparseable login response")

            # Failure indicator: {"dtException": [{"StatusCode": "0", ...}]}
            # This is a transient server-side error — raise so the coordinator
            # can convert it to UpdateFailed and retry at the next poll.
            if isinstance(result, dict) and "dtException" in result:
                msg = ""
                exc = result["dtException"]
                if isinstance(exc, list) and exc:
                    msg = exc[0].get("MessageInformation", "")
                _LOGGER.warning("Hidroelectrica login server error: %s", msg)
                raise HidroelectricaServerError(msg or "Server-side login error")

            # Auth failure: {"dtResponse": [{"Status": "0", "Message": "..."}]}
            if isinstance(result, dict) and "dtResponse" in result:
                msg = ""
                resp_list = result["dtResponse"]
                if isinstance(resp_list, list) and resp_list:
                    msg = resp_list[0].get("Message", "")
                _LOGGER.warning("Hidroelectrica login failed: %s", msg)
                return False

            # 2FA redirect: server returns Table with MaskedEmail/MaskedPhone
            if isinstance(result, dict) and "Table" in result:
                _LOGGER.error(
                    "Hidroelectrica login requires two-factor authentication "
                    "(OTP via email/SMS) — this is not supported"
                )
                return False

            # Success: result is a list where [0] has DashboardOption
            if not isinstance(result, list) or not result:
                _LOGGER.warning(
                    "Hidroelectrica validateLogin returned unexpected structure: %s",
                    str(result)[:200],
                )
                raise HidroelectricaServerError("Unexpected login response structure")

            # ── Step 4: Fetch Dashboard to extract CSRF token ──
            async with self._session.get(DASHBOARD_URL) as resp:
                dashboard_html = await resp.text()

            csrf = _extract_hidden(dashboard_html, CSRF_FIELD_NAME)
            if not csrf:
                _LOGGER.error(
                    "Logged in but could not find CSRF token in Dashboard HTML"
                )
                return False

            self.csrf_token = csrf
            self.contracts = _extract_contracts(dashboard_html)
            _LOGGER.debug(
                "Hidroelectrica login successful, CSRF token acquired, %d contract(s): %s",
                len(self.contracts),
                [c["name"] for c in self.contracts],
            )
            return True

        except HidroelectricaServerError:
            raise
        except aiohttp.ClientError:
            raise

    def ajax_headers(self) -> dict[str, str]:
        """Return the headers required for every AJAX/JSON request."""
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "csrftoken": self.csrf_token,
            "isajax": "1",
            "x-requested-with": "XMLHttpRequest",
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_hidden(html: str, name: str) -> str:
    """Return the *value* of a hidden ``<input>`` identified by *name* or *id*."""
    # name="..." comes first in most ASP.NET pages; fall back to id="..."
    match = re.search(
        r'<input[^>]+name="' + re.escape(name) + r'"[^>]+value="([^"]*)"',
        html,
        re.IGNORECASE,
    ) or re.search(
        r'<input[^>]+value="([^"]*)"[^>]+name="' + re.escape(name) + r'"',
        html,
        re.IGNORECASE,
    ) or re.search(
        r'<input[^>]+id="' + re.escape(name) + r'"[^>]+value="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _extract_contracts(html: str) -> list[dict]:
    """Parse the account/contract list from Dashboard.aspx HTML.

    The portal renders a custom dropdown as ``<li role='listitem' data-id=UAN Addressid=ADDR>``
    with the friendly name (including UAN) inside the ``<a>`` element.
    The hidden ``<select id="ddlAddress">`` options are also server-rendered and used as fallback.
    """
    contracts: list[dict] = []

    # Primary: parse <li> custom dropdown — server-rendered with friendly name, UAN, addressId
    for li_m in re.finditer(
        r"<li\b[^>]*\bdata-id=(\d+)\s+Addressid=(\d+)[^>]*>\s*<a[^>]*>([^<\n]+)",
        html,
        re.IGNORECASE,
    ):
        uan = li_m.group(1).strip()
        address_id = li_m.group(2).strip()
        name = li_m.group(3).strip()
        if uan and address_id:
            contracts.append({"address_id": address_id, "utility_account_number": uan, "name": name})

    if contracts:
        _LOGGER.debug(
            "_extract_contracts: found %d contract(s): %s",
            len(contracts),
            [c["name"] for c in contracts],
        )
        return contracts

    # Fallback: parse <option> elements in <select id="ddlAddress">
    # Value format: accountNumber:addressId:x:lat:lon:zipcode:utilityAccountNumber:...
    select_m = re.search(
        r'<select[^>]+\bid="ddlAddress"[^>]*>(.*?)</select>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not select_m:
        _LOGGER.debug(
            "_extract_contracts: neither <li data-id> nor <select id='ddlAddress'> found"
        )
        return contracts

    select_html = select_m.group(1)
    for option_m in re.finditer(
        r'<option([^>]*)>([^<]*)</option>',
        select_html,
        re.IGNORECASE,
    ):
        option_attrs = option_m.group(1)
        option_text = option_m.group(2).strip()

        val_m = re.search(r'\bvalue="([^"]+)"', option_attrs, re.IGNORECASE)
        if not val_m:
            continue

        parts = val_m.group(1).split(":")
        if len(parts) < 7:
            continue

        address_id = parts[1].strip()
        uan = parts[6].strip()

        if not address_id or not uan:
            continue

        name = re.sub(r"\s*\(Default\)", "", option_text, flags=re.IGNORECASE).strip()
        name = name or uan

        contracts.append({"address_id": address_id, "utility_account_number": uan, "name": name})

    _LOGGER.debug(
        "_extract_contracts: found %d contract(s) (fallback): %s",
        len(contracts),
        [c["name"] for c in contracts],
    )
    return contracts
