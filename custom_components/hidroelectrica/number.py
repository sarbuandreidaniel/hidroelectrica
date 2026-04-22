"""Number platform for Hidroelectrica integration — meter index input staging."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)

# Registers we expose for user input
_REGISTER_KEYS = {
    "1.8.0": "consumed",
    "1.8.0_P": "produced",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidroelectrica number entities."""
    coordinator: HidroelectricaCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]

    def build_entities_for_contract(
        contract: dict, readings: list[dict]
    ) -> list[NumberEntity]:
        return [
            HidroelectricaEnergyIndexNumber(coordinator, config_entry, reading, contract)
            for reading in readings
            if reading.get("Registers") in _REGISTER_KEYS
        ]

    # Track (uan, register) pairs to avoid duplicates
    known_registers: set[tuple[str, str]] = set()
    entities: list[NumberEntity] = []

    for contract in (coordinator.data or {}).get("contracts", []):
        uan = contract["utility_account_number"]
        readings = (coordinator.data or {}).get(uan, {}).get("meter_readings", [])
        entities += build_entities_for_contract(contract, readings)
        known_registers.update((uan, r.get("Registers", "")) for r in readings)

    async_add_entities(entities)

    @callback
    def async_add_new_entities() -> None:
        for contract in (coordinator.data or {}).get("contracts", []):
            uan = contract["utility_account_number"]
            current = (coordinator.data or {}).get(uan, {}).get("meter_readings", [])
            new = [
                r for r in current
                if (uan, r.get("Registers", "")) not in known_registers
            ]
            if not new:
                continue
            async_add_entities(build_entities_for_contract(contract, new))
            known_registers.update((uan, r.get("Registers", "")) for r in new)

    config_entry.async_on_unload(
        coordinator.async_add_listener(async_add_new_entities)
    )


class HidroelectricaEnergyIndexNumber(CoordinatorEntity, NumberEntity):
    """Number entity for staging a new electricity meter index before submission."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_native_max_value = 9999999
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        config_entry: ConfigEntry,
        meter_reading: dict,
        contract: dict,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._register = meter_reading.get("Registers", "")
        self._pod = meter_reading.get("POD", "")
        self._uan = contract["utility_account_number"]
        self._contract = contract

        suffix = _REGISTER_KEYS.get(self._register, slugify(self._register))
        self._attr_translation_key = f"meter_index_{suffix}_input"

        uan_slug = slugify(self._uan) or "meter"
        object_id = f"{DOMAIN}_{uan_slug}_meter_index_{suffix}_input"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id

    @property
    def _current_reading(self) -> dict:
        """Return the current raw meter reading for this register."""
        for r in (self.coordinator.data or {}).get(self._uan, {}).get("meter_readings", []):
            if r.get("Registers") == self._register:
                return r
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._uan)},
            name=f"{self._contract['name']}",  # already includes UAN e.g. "Casuta Noastra (8000863947)"
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type="service",
        )

    @property
    def native_min_value(self) -> float:
        """Minimum is the last confirmed index reported by the distributor."""
        try:
            return float(self._current_reading.get("PrevMRResult", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def native_value(self) -> float | None:
        """Return the staged value, or the portal's estimated current index as default.

        The portal pre-fills its inputs with the estimated value (from GetMeterValue),
        not with PrevMRResult. We mirror that behaviour so the displayed value stays
        fresh after submission (once the coordinator refreshes).
        """
        pending = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get("pending_meter_index", {})
            .get(self._uan, {})
        )
        if self._register in pending:
            return float(pending[self._register])
        # Use the portal's estimate, fall back to last confirmed index
        estimate = (
            (self.coordinator.data or {})
            .get(self._uan, {})
            .get("meter_estimates", {})
            .get(self._register)
        )
        if estimate is not None:
            try:
                return float(estimate)
            except (TypeError, ValueError):
                pass
        try:
            return float(self._current_reading.get("PrevMRResult", 0) or 0)
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        """Available when we have meter reading data for this register."""
        return bool(self._current_reading)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the expected read date and register description."""
        reading = self._current_reading
        attrs: dict = {}
        calendar = reading.get("Calendar")
        if calendar:
            attrs["read_date"] = calendar
        desc = reading.get("Registersdesc")
        if desc:
            attrs["register_description"] = desc
        serial = reading.get("SerialNumber")
        if serial:
            attrs["serial_number"] = serial
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Stage the index value. Press Submit to send it to the portal."""
        pending_all = self.hass.data[DOMAIN][self.config_entry.entry_id][
            "pending_meter_index"
        ]
        pending_all.setdefault(self._uan, {})[self._register] = int(value)
        self.async_write_ha_state()
