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
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

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


def _device_slug(data: dict | None) -> str:
    """Return a stable device slug for entity and unique IDs."""
    meter = data.get("meter", {}) if isinstance(data, dict) else {}
    pod = meter.get("pod") if isinstance(meter, dict) else None
    serial_number = meter.get("serial_number") if isinstance(meter, dict) else None
    slug = slugify(str(pod or serial_number or "account"))
    return slug or "account"


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
    HidroelectricaSensorEntityDescription(
        key="bill_due_date",
        translation_key="bill_due_date",
        icon="mdi:calendar-clock",
        value_fn=lambda d: d.get("billing", {}).get("BillDue"),
    ),
    HidroelectricaSensorEntityDescription(
        key="days_until_due",
        translation_key="days_until_due",
        icon="mdi:calendar-range",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _days_until(d.get("billing", {}).get("BillDue")),
    ),
    # ── Latest unpaid invoice ─────────────────────────────────────────
    HidroelectricaSensorEntityDescription(
        key="invoice_amount",
        translation_key="invoice_amount",
        icon="mdi:file-document",
        native_unit_of_measurement=CURRENCY_RON,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: _parse_ron(d.get("unpaid_invoices", {}).get("amount")),
    ),
    HidroelectricaSensorEntityDescription(
        key="invoice_due_date",
        translation_key="invoice_due_date",
        icon="mdi:calendar-check",
        value_fn=lambda d: d.get("unpaid_invoices", {}).get("dueDate"),
    ),
    HidroelectricaSensorEntityDescription(
        key="invoice_overdue",
        translation_key="invoice_overdue",
        icon="mdi:alert-circle",
        value_fn=lambda d: bool(d.get("unpaid_invoices", {}).get("overdue", "")),
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
        value_fn=lambda d: d.get("meter", {}).get("produced_index"),
    ),
    HidroelectricaSensorEntityDescription(
        key="meter_estimated",
        translation_key="meter_estimated",
        icon="mdi:gauge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("meter", {}).get("estimated_value"),
    ),
    HidroelectricaSensorEntityDescription(
        key="last_reading_date",
        translation_key="last_reading_date",
        icon="mdi:calendar-today",
        value_fn=lambda d: d.get("meter", {}).get("reading_date"),
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
    HidroelectricaSensorEntityDescription(
        key="last_month_cost",
        translation_key="last_month_cost",
        icon="mdi:cash",
        native_unit_of_measurement=CURRENCY_RON,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("usage", {}).get("last_month_cost"),
    ),
    HidroelectricaSensorEntityDescription(
        key="monthly_avg_cost",
        translation_key="monthly_avg_cost",
        icon="mdi:chart-bar",
        native_unit_of_measurement=CURRENCY_RON,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("usage", {}).get("monthly_avg_cost"),
    ),
    HidroelectricaSensorEntityDescription(
        key="monthly_max_cost",
        translation_key="monthly_max_cost",
        icon="mdi:chart-areaspline",
        native_unit_of_measurement=CURRENCY_RON,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("usage", {}).get("monthly_max_cost"),
    ),
)


# ------------------------------------------------------------------
# Platform setup
# ------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hidroelectrica sensors from a config entry."""
    coordinator: HidroelectricaCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    current_year = date.today().year
    entities: list = [
        HidroelectricaSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    # Consumed energy billing history (excludes produced-energy reports)
    entities += [
        HidroelectricaInvoiceHistorySensor(coordinator, entry, current_year, produced=False),
        HidroelectricaInvoiceHistorySensor(coordinator, entry, current_year - 1, produced=False),
    ]
    # Produced energy billing history (fotovoltaic)
    entities += [
        HidroelectricaInvoiceHistorySensor(coordinator, entry, current_year, produced=True),
        HidroelectricaInvoiceHistorySensor(coordinator, entry, current_year - 1, produced=True),
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
        entry: ConfigEntry,
        description: HidroelectricaSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        object_id = f"{DOMAIN}_{_device_slug(coordinator.data)}_{description.key}"
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Hidroelectrica",
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type="service",
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor's current value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


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
        entry: ConfigEntry,
        year: int,
        produced: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self._year = year
        self._produced = produced
        suffix = "produced" if produced else "consumed"
        object_id = (
            f"{DOMAIN}_{_device_slug(coordinator.data)}_invoice_history_{suffix}_{year}"
        )
        self._attr_unique_id = object_id
        self._attr_suggested_object_id = object_id
        self._attr_translation_key = (
            "invoice_history_produced" if produced else "invoice_history"
        )
        self._attr_translation_placeholders = {"year": str(year)}
        self._attr_icon = "mdi:solar-power" if produced else "mdi:file-document-multiple"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Hidroelectrica",
            manufacturer="Hidroelectrica S.A.",
            model="iHidro Portal",
            entry_type="service",
        )

    def _get_year_invoices(self) -> list[dict]:
        """Return invoices for this sensor's year, sorted chronologically."""
        if not self.coordinator.data:
            return []
        history = self.coordinator.data.get("invoice_history", [])
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
