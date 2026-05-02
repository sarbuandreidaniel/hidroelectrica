"""Custom integration for Hidroelectrica Romania."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "number", "button"]

type HidroelectricaConfigEntry = ConfigEntry[HidroelectricaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HidroelectricaConfigEntry) -> bool:
    """Set up Hidroelectrica from a config entry."""
    _LOGGER.debug("Setting up Hidroelectrica config entry: %s", entry.title)

    coordinator = HidroelectricaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HidroelectricaConfigEntry) -> bool:
    """Unload a Hidroelectrica config entry."""
    _LOGGER.debug("Unloading Hidroelectrica config entry: %s", entry.title)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await entry.runtime_data.async_close()

    return unload_ok
