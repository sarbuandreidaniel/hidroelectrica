"""Sensor platform for Hidroelectrica integration."""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import HidroelectricaConfigEntry
from .const import DOMAIN
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)

CURRENCY_RON = "RON"
INVOICE_TYPE_PRODUCED = "Report energie produsă"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_ron(value: Any) -> float | None:
    """Parse a Romanian-formatted RON value like '67,34' to float."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _days_until(date_str: str | None) -> int | None:
    """Return days until a date formatted as DD/MM/YYYY."""
    parsed = _to_date(date_str)
    return (parsed - date.today()).days if parsed is not None else None


def _to_date(date_str: str | None) -> date | None:
    """Parse DD/MM/YYYY to a Python date object."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        if len(parts) != 3:
            return None
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        return None


def _fmt_date(value: Any) -> str | None:
    """Parse any common date format and return DD/MM/YYYY, stripping time if present."""
    if not value:
        return None
    s = str(value).strip().split(" ")[0].split("T")[0]  # drop time component
    # Try ISO: YYYY-MM-DD
    if len(s) == 10 and s[4] == "-":
        try:
            d = date.fromisoformat(s)
            return d.strftime("%d/%m/%Y")
        except ValueError:
            pass
    # Try DD/MM/YYYY or M/DD/YYYY (detect by checking which part exceeds 12)
    try:
        parts = s.split("/")
        if len(parts) == 3:
            a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
            # If b > 12, must be M/DD/YYYY (a=month, b=day, c=year)
            if b > 12:
                d = date(c, a, b)
            else:
                d = date(c, b, a)
            return d.strftime("%d/%m/%Y")
    except (ValueError, IndexError):
        pass
    # Try DD.MM.YYYY
    try:
        parts = s.split(".")
        if len(parts) == 3:
            d = date(int(parts[2]), int(parts[1]), int(parts[0]))
            return d.strftime("%d/%m/%Y")
    except (ValueError, IndexError):
        pass
    return str(value)





# ------------------------------------------------------------------
# Sensor descriptions
# ------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class HidroelectricaSensorEntityDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a coordinator-data extractor."""

    value_fn: Callable[[dict], Any] = lambda _: None


SENSOR_DESCRIPTIONS: tuple[HidroelectricaSensorEntityDescription, ...] = (
    # ── Billing ───────────────────────────────────────────────────────
    HidroelectricaSensorEntityDescription(
        key="balance",
        translation_key="balance",
        icon="mdi:cash",
        native_unit_of_measurement=CURRENCY_RON,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _parse_ron(d.get("billing", {}).get("ToTalBalance")),
    ),
    # ── Meter ─────────────────────────────────────────────────────────
    HidroelectricaSensorEntityDescription(
        key="meter_consumed",
        translation_key="meter_consumed",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.get("meter", {}).get("consumed_index"),
    ),
    HidroelectricaSensorEntityDescription(
        key="meter_produced",
        translation_key="meter_produced",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.get("meter", {}).get("produced_index"),
    ),
    HidroelectricaSensorEntityDescription(
        key="last_reading_date",
        translation_key="last_reading_date",
        icon="mdi:calendar-today",
        value_fn=lambda d: _fmt_date(d.get("meter", {}).get("reading_date")),
    ),
    HidroelectricaSensorEntityDescription(
        key="meter_serial",
        translation_key="meter_serial",
        icon="mdi:counter",
        value_fn=lambda d: d.get("meter", {}).get("serial_number"),
    ),
    HidroelectricaSensorEntityDescription(
        key="pod",
        translation_key="pod",
        icon="mdi:map-marker",
        value_fn=lambda d: d.get("meter", {}).get("pod"),
    ),
    # ── Usage ─────────────────────────────────────────────────────────
    HidroelectricaSensorEntityDescription(
        key="last_month_kwh",
        translation_key="last_month_kwh",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda d: d.get("usage", {}).get("last_month_kwh"),
    ),
)


# ------------------------------------------------------------------
# Platform setup
# ------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HidroelectricaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidroelectrica sensors from a config entry."""
    coordinator = entry.runtime_data
    current_year = date.today().year
    entities: list = []

    for contract in (coordinator.data or {}).get("contracts", []):
        uan = contract["utility_account_number"]
        device_name = contract["name"]  # already includes UAN e.g. "Casuta Noastra (8000863947)"
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                HidroelectricaSensor(coordinator, description, uan, device_name)
            )
        entities.append(
            HidroelectricaUnpaidInvoiceSensor(coordinator, uan, device_name)
        )
        entities += [
            HidroelectricaConsumptionHistorySensor(
                coordinator, current_year, uan, device_name
            ),
            HidroelectricaConsumptionHistorySensor(
                coordinator, current_year - 1, uan, device_name
            ),
        ]
        entities += [
            HidroelectricaInvoiceHistorySensor(
                coordinator, current_year, uan, device_name, produced=False
            ),
            HidroelectricaInvoiceHistorySensor(
                coordinator, current_year - 1, uan, device_name, produced=False
            ),
        ]
        entities += [
            HidroelectricaInvoiceHistorySensor(
                coordinator, current_year, uan, device_name, produced=True
            ),
            HidroelectricaInvoiceHistorySensor(
                coordinator, current_year - 1, uan, device_name, produced=True
            ),
        ]

    async_add_entities(entities)


# ------------------------------------------------------------------
# Entity
# ------------------------------------------------------------------


class HidroelectricaSensor(
    CoordinatorEntity[HidroelectricaCoordinator], SensorEntity
):
    """A single Hidroelectrica sensor backed by the coordinator."""

    entity_description: HidroelectricaSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        description: HidroelectricaSensorEntityDescription,
        uan: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._uan = uan
        uan_slug = slugify(uan)
        object_id = f"{DOMAIN}_{uan_slug}_{description.key}"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uan)},
            name=device_name,
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor's current value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(
            self.coordinator.data.get(self._uan, {})
        )

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


# ------------------------------------------------------------------
# Unpaid invoice sensor
# ------------------------------------------------------------------


class HidroelectricaUnpaidInvoiceSensor(
    CoordinatorEntity[HidroelectricaCoordinator], SensorEntity
):
    """Single sensor for the latest unpaid invoice; detail fields exposed as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "unpaid_invoice"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:file-document-alert"

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        uan: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._uan = uan
        uan_slug = slugify(uan)
        object_id = f"{DOMAIN}_{uan_slug}_unpaid_invoice"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uan)},
            name=device_name,
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return _parse_ron(
            self.coordinator.data.get(self._uan, {})
            .get("unpaid_invoices", {})
            .get("amount")
        )

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {"overdue": False}
        unpaid = self.coordinator.data.get(self._uan, {}).get("unpaid_invoices", {})
        due_date_raw = unpaid.get("dueDate")
        days = _days_until(due_date_raw) if due_date_raw else None
        overdue = unpaid.get("overdue") or (days is not None and days < 0)
        return {
            "due_date": due_date_raw,
            "days_until_due": days,
            "overdue": bool(overdue),
        }


# ------------------------------------------------------------------
# Consumption history sensor (per-year)
# ------------------------------------------------------------------


class HidroelectricaConsumptionHistorySensor(
    CoordinatorEntity[HidroelectricaCoordinator], SensorEntity
):
    """Yearly electricity consumption history in kWh, with per-month attributes."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        year: int,
        uan: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._year = year
        self._uan = uan
        self._attr_translation_key = "consumption_history_year"
        self._attr_translation_placeholders = {"year": str(year)}
        uan_slug = slugify(uan)
        object_id = f"{DOMAIN}_{uan_slug}_consumption_history_{year}"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uan)},
            name=device_name,
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _get_year_entries(self) -> list[dict]:
        """Return list of {month_name, kwh} for this year from index history."""
        if not self.coordinator.data:
            return []
        index_history: dict = (
            self.coordinator.data.get(self._uan, {}).get("index_history", {})
        )
        entries = []
        for month_num in range(1, 13):
            kwh = index_history.get((self._year, month_num))
            if kwh is not None:
                try:
                    month_name = calendar.month_name[month_num]
                except IndexError:
                    month_name = str(month_num)
                entries.append({"month_num": month_num, "month_name": month_name, "kwh": kwh})
        return entries

    @property
    def available(self) -> bool:
        return super().available and bool(self._get_year_entries())

    @property
    def native_value(self) -> float | None:
        entries = self._get_year_entries()
        if not entries:
            return None
        return round(sum(e["kwh"] for e in entries), 1)

    @property
    def extra_state_attributes(self) -> dict:
        entries = self._get_year_entries()
        attrs: dict = {}
        total = 0.0
        for e in entries:
            attrs[e["month_name"]] = round(e["kwh"], 1)
            total += e["kwh"]
        count = len(entries)
        days_in_year = 366 if calendar.isleap(self._year) else 365
        attrs["total_kwh"] = round(total, 1)
        attrs["average_monthly_kwh"] = round(total / count, 1) if count else 0.0
        attrs["average_daily_kwh"] = round(total / days_in_year, 2)
        return attrs


# ------------------------------------------------------------------
# Invoice history sensor (per-year)
# ------------------------------------------------------------------


class HidroelectricaInvoiceHistorySensor(
    CoordinatorEntity[HidroelectricaCoordinator], SensorEntity
):
    """Yearly invoice history sensor for Hidroelectrica."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:file-document-multiple"
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        year: int,
        uan: str,
        device_name: str,
        produced: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self._year = year
        self._produced = produced
        self._uan = uan
        suffix = "produced" if produced else "consumed"
        uan_slug = slugify(uan)
        object_id = (
            f"{DOMAIN}_{uan_slug}_invoice_history_{suffix}_{year}"
        )
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_translation_key = (
            "invoice_history_produced" if produced else "invoice_history"
        )
        self._attr_translation_placeholders = {"year": str(year)}
        self._attr_icon = "mdi:solar-power" if produced else "mdi:file-document-multiple"
        if produced:
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uan)},
            name=device_name,
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _get_year_invoices(self) -> list[dict]:
        """Return invoices for this sensor's year, sorted chronologically."""
        if not self.coordinator.data:
            return []
        history = self.coordinator.data.get(self._uan, {}).get("invoice_history", [])
        filtered = [
            inv for inv in history
            if str(inv.get("Date", ""))[-4:] == str(self._year)
            and (
                inv.get("invoiceType") == INVOICE_TYPE_PRODUCED
                if self._produced
                else inv.get("invoiceType") != INVOICE_TYPE_PRODUCED
            )
        ]
        return sorted(
            filtered,
            key=lambda inv: _to_date(inv.get("Date")) or date.min,
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self._get_year_invoices())

    @property
    def native_value(self) -> float | None:
        """Return the total invoiced amount for the year."""
        invoices = self._get_year_invoices()
        if not invoices:
            return None
        try:
            total = sum(
                float(str(inv.get("Amount", 0)).replace(",", "."))
                for inv in invoices
                if inv.get("Amount") is not None
            )
            return round(total, 2)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-invoice breakdown and yearly summary."""
        invoices = self._get_year_invoices()
        if not invoices:
            return {
                "total_invoices": 0,
                "total_amount_paid": 0.0,
                "average_monthly_amount": 0.0,
                "average_daily_amount": 0.0,
            }

        attributes: dict = {}
        total_amount = 0.0

        for idx, inv in enumerate(invoices, 1):
            date_str = inv.get("Date", "unknown")
            try:
                amount = round(float(str(inv.get("Amount", 0)).replace(",", ".")), 2)
            except (ValueError, TypeError):
                amount = 0.0
            total_amount += amount
            attributes[f"Invoice {idx} {date_str}"] = amount

        invoice_count = len(invoices)
        days_in_year = 366 if calendar.isleap(self._year) else 365

        attributes["total_invoices"] = invoice_count
        attributes["total_amount_paid"] = round(total_amount, 2)
        attributes["average_monthly_amount"] = (
            round(total_amount / invoice_count, 2) if invoice_count else 0.0
        )
        attributes["average_daily_amount"] = round(total_amount / days_in_year, 2)

        return attributes
