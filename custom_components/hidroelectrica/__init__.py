"""Custom integration for Hidroelectrica Romania."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "number", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Hidroelectrica component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hidroelectrica from a config entry."""
    _LOGGER.debug("Setting up Hidroelectrica config entry: %s", entry.title)

    coordinator = HidroelectricaCoordinator(
        hass,
        username=entry.data["username"],
        password=entry.data["password"],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "pending_meter_index": {},
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Hidroelectrica config entry."""
    _LOGGER.debug("Unloading Hidroelectrica config entry: %s", entry.title)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator: HidroelectricaCoordinator = entry_data["coordinator"]
        await coordinator.async_close()

    return unload_ok
