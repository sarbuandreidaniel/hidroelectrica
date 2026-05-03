"""Button platform for Hidroelectrica integration — meter index submission."""

import logging
from datetime import date

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import HidroelectricaConfigEntry
from .const import DOMAIN
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HidroelectricaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidroelectrica button entities."""
    coordinator = config_entry.runtime_data
    entities = [
        HidroelectricaSubmitMeterReadingButton(coordinator, contract)
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
        contract: dict,
    ) -> None:
        super().__init__(coordinator)
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
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Available when meter reading data is loaded and inside a submission window."""
        meter_readings: list[dict] = (
            (self.coordinator.data or {}).get(self._uan, {}).get("meter_readings") or []
        )
        if not meter_readings:
            return False
        return self._is_in_submission_period(meter_readings)

    def _parse_date(self, date_str: str | None) -> date | None:
        """Parse a DD/MM/YYYY date string, returning None on failure."""
        if not date_str:
            return None
        try:
            parts = date_str.strip().split("/")
            if len(parts) != 3:
                return None
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            return None

    def _is_in_submission_period(self, meter_readings: list[dict]) -> bool:
        """Return True when today falls inside the submission window.

        The authoritative window is provided by the portal via the hidden
        ``hdnopendate`` and ``hdnclosedate`` fields on the SelfMeterReading
        page, scraped and stored in coordinator data each refresh.
        """
        today = date.today()
        window = (self.coordinator.data or {}).get("meter_reading_window", {})
        open_date = self._parse_date(window.get("open_date"))
        close_date = self._parse_date(window.get("close_date"))
        if open_date is None or close_date is None:
            return True  # window dates unavailable — don't restrict
        return open_date <= today <= close_date

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

        pod_info = coordinator.get_pod_info(uan)
        if not pod_info:
            raise HomeAssistantError("Cannot submit: POD info not available")

        installation = pod_info.get("installation", "")
        pod = pod_info.get("pod", "")

        pending: dict = coordinator.pending_meter_index.setdefault(uan, {})

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
