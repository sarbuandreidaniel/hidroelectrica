"""Config flow for Hidroelectrica integration."""

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .auth import HidroelectricaAuth
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HidroelectricaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hidroelectrica."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            if not username:
                errors["base"] = "missing_username"
            elif not password:
                errors["base"] = "missing_password"
            else:
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_configured()

                valid, error_key = await self._validate_credentials(username, password)
                if valid:
                    return self.async_create_entry(
                        title=username,
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                        },
                    )
                errors["base"] = error_key

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def _validate_credentials(
        self, username: str, password: str
    ) -> tuple[bool, str]:
        """Validate credentials by attempting a real login."""
        try:
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar()
            ) as session:
                auth = HidroelectricaAuth(session, username, password)
                ok = await auth.async_login()
            if ok:
                return True, ""
            return False, "invalid_auth"
        except aiohttp.ClientError:
            return False, "cannot_connect"
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Unexpected error validating credentials: %s", err)
            return False, "unknown"
