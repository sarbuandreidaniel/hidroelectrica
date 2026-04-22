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
    entities = [
        HidroelectricaSubmitMeterReadingButton(coordinator, config_entry, contract)
        for contract in (coordinator.data or {}).get("contracts", [])
    ]
    async_add_entities(entities)


class HidroelectricaSubmitMeterReadingButton(CoordinatorEntity, ButtonEntity):
    """Button that submits all staged meter readings to the iHidro portal."""

    _attr_has_entity_name = True
    _attr_translation_key = "submit_meter_reading"
    _attr_icon = "mdi:send"

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        config_entry: ConfigEntry,
        contract: dict,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._contract = contract
        self._uan = contract["utility_account_number"]
        self._device_name = contract["name"]  # already includes UAN e.g. "Casuta Noastra (8000863947)"

        uan_slug = slugify(self._uan) or "meter"
        object_id = f"{DOMAIN}_{uan_slug}_submit_meter_reading"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._uan)},
            name=self._device_name,
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type="service",
        )

    @property
    def available(self) -> bool:
        """Available when meter reading data is loaded for this contract."""
        return bool(
            (self.coordinator.data or {})
            .get(self._uan, {})
            .get("meter_readings")
        )

    async def async_press(self) -> None:
        """Submit all staged meter readings to the portal."""
        coordinator = self.coordinator
        uan = self._uan

        contract_data = (coordinator.data or {}).get(uan, {})
        meter_readings: list[dict] = contract_data.get("meter_readings", [])
        if not meter_readings:
            raise HomeAssistantError(
                "Cannot submit: no meter reading data available"
            )

        pod_info = coordinator._pod_info_cache.get(uan)  # noqa: SLF001
        if not pod_info:
            raise HomeAssistantError("Cannot submit: POD info not available")

        installation = pod_info.get("installation", "")
        pod = pod_info.get("pod", "")

        pending: dict = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get("pending_meter_index", {})
            .get(uan, {})
        )

        # Estimates mirror what the number entities display as their default value.
        # Use them as fallback so what's submitted matches what the user sees in HA.
        estimates: dict = (coordinator.data or {}).get(uan, {}).get("meter_estimates", {})

        # Build the entity list expected by the portal, substituting staged values
        entities_to_submit = []
        for reading in meter_readings:
            register = reading.get("Registers", "")
            if register in pending:
                new_value = pending[register]
            elif estimates.get(register) is not None:
                new_value = estimates[register]
            else:
                new_value = reading.get("PrevMRResult", "0") or "0"
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

        # Switch the server session to this contract before submitting
        await api.switch_contract(self._contract["address_id"])

        _LOGGER.debug(
            "Submitting meter readings for contract=%s installation=%s pod=%s: %s",
            uan,
            installation,
            pod,
            entities_to_submit,
        )

        result = await api.submit_meter_reading(entities_to_submit, installation, pod)
        _LOGGER.info("Meter reading submission result for %s: %s", uan, result)

        # Clear pending staged values after a successful call
        pending.clear()

        # Refresh coordinator so sensors reflect the new index
        await coordinator.async_request_refresh()
