"""Button platform for Hidroelectrica integration — meter index submission."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidroelectrica button entities."""
    coordinator: HidroelectricaCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    async_add_entities(
        [HidroelectricaSubmitMeterReadingButton(coordinator, config_entry)]
    )


class HidroelectricaSubmitMeterReadingButton(CoordinatorEntity, ButtonEntity):
    """Button that submits all staged meter readings to the iHidro portal."""

    _attr_has_entity_name = True
    _attr_translation_key = "submit_meter_reading"
    _attr_icon = "mdi:send"

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry

        pod = (coordinator.data or {}).get("meter", {}).get("pod", "")
        pod_slug = slugify(pod) or "meter"
        object_id = f"{DOMAIN}_{pod_slug}_submit_meter_reading"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name="Hidroelectrica",
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type="service",
        )

    @property
    def available(self) -> bool:
        """Available when meter reading data is loaded."""
        return bool((self.coordinator.data or {}).get("meter_readings"))

    async def async_press(self) -> None:
        """Submit all staged meter readings to the portal."""
        coordinator = self.coordinator

        meter_readings: list[dict] = (coordinator.data or {}).get("meter_readings", [])
        if not meter_readings:
            raise HomeAssistantError(
                "Cannot submit: no meter reading data available"
            )

        pod_info = coordinator._pod_info  # noqa: SLF001
        if not pod_info:
            raise HomeAssistantError("Cannot submit: POD info not available")

        installation = pod_info.get("installation", "")
        pod = pod_info.get("pod", "")

        pending: dict = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get("pending_meter_index", {})
        )

        # Build the entity list expected by the portal, substituting staged values
        entities_to_submit = []
        for reading in meter_readings:
            register = reading.get("Registers", "")
            # Use the staged value if set; fall back to the last confirmed index
            new_value = pending.get(register, reading.get("PrevMRResult", "0"))
            entities_to_submit.append(
                {
                    "POD": reading.get("POD", ""),
                    "SerialNumber": reading.get("SerialNumber", ""),
                    "NewMeterReadDate": reading.get("Calendar", ""),
                    "registerCat": register,
                    "distributor": reading.get("Distributor", ""),
                    "meterInterval": reading.get("MeterInterval", ""),
                    "supplier": reading.get("Supplier", ""),
                    "distCustomer": reading.get("DistCustomer", ""),
                    "distCustomerId": reading.get("DistCustomerId", ""),
                    "distContract": reading.get("DistContract", ""),
                    "distContractDate": reading.get("DistContractDate", ""),
                    "UtilityAccountNumber": reading.get("UtilityAccountNumber", ""),
                    "prevMRResult": reading.get("PrevMRResult", ""),
                    "newmeterread": str(new_value),
                }
            )

        api = coordinator.api
        if not api:
            raise HomeAssistantError("Cannot submit: API not initialized")

        _LOGGER.debug(
            "Submitting meter readings for installation=%s pod=%s: %s",
            installation,
            pod,
            entities_to_submit,
        )

        result = await api.submit_meter_reading(entities_to_submit, installation, pod)
        _LOGGER.info("Meter reading submission result: %s", result)

        # Clear pending staged values after a successful call
        pending.clear()

        # Refresh coordinator so sensors reflect the new index
        await coordinator.async_request_refresh()
