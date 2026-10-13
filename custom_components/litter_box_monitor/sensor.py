"""Sensors for Litter Box Monitor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import AVERAGE_WINDOW_DAYS, CONF_STATISTICS, CURRENT_DURATION_INTERVAL
from .coordinator import LitterBoxCoordinator
from .entity import LitterBoxEntity
from .state_machine import FaultType, OperationalState

if TYPE_CHECKING:
    from . import LitterBoxConfigEntry

PARALLEL_UPDATES = 0

ERROR_NONE = "none"


def _stats(c: LitterBoxCoordinator) -> bool:
    return bool(c.options[CONF_STATISTICS])


def _maintenance(c: LitterBoxCoordinator) -> bool:
    return c.bag_door_entity is not None


def _status_attrs(c: LitterBoxCoordinator) -> dict[str, Any]:
    cycle = c.machine.cycle
    return {
        "cleaning_started_at": cycle.started_at.isoformat() if cycle else None,
        "cycle_start_source": cycle.start_source.value if cycle else None,
        "cycle_verified": cycle.continuity_verified if cycle else None,
    }


def _fault_attrs(c: LitterBoxCoordinator) -> dict[str, Any]:
    fault = c.machine.fault
    if fault is None:
        return {}
    data = fault.as_dict()
    data.pop("reason")
    return data


@dataclass(frozen=True, kw_only=True)
class LitterBoxSensorDescription(SensorEntityDescription):
    """Describes a litter box sensor."""

    value_fn: Callable[[LitterBoxCoordinator], StateType | datetime]
    attrs_fn: Callable[[LitterBoxCoordinator], dict[str, Any]] | None = None
    available_fn: Callable[[LitterBoxCoordinator], bool] = lambda _: True
    exists_fn: Callable[[LitterBoxCoordinator], bool] = lambda _: True


SENSORS: tuple[LitterBoxSensorDescription, ...] = (
    LitterBoxSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in OperationalState],
        value_fn=lambda c: c.machine.status.value,
        attrs_fn=_status_attrs,
    ),
    LitterBoxSensorDescription(
        key="error_reason",
        translation_key="error_reason",
        device_class=SensorDeviceClass.ENUM,
        options=[ERROR_NONE, *(f.value for f in FaultType)],
        value_fn=lambda c: (
            c.machine.fault.fault_type.value if c.machine.fault else ERROR_NONE
        ),
        attrs_fn=_fault_attrs,
    ),
    LitterBoxSensorDescription(
        key="last_cleaning",
        translation_key="last_cleaning",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.machine.last_cleaning_at,
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="last_cleaning_duration",
        translation_key="last_cleaning_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.machine.last_cleaning_duration,
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="cleans_today",
        translation_key="cleans_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.machine.cleans_on(c.today),
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="cleans_yesterday",
        translation_key="cleans_yesterday",
        value_fn=lambda c: c.machine.cleans_on(c.today - timedelta(days=1)),
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="cleans_last_7_days",
        translation_key="cleans_last_7_days",
        value_fn=lambda c: c.machine.cleans_in_last_days(c.today, 7),
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="total_cleans",
        translation_key="total_cleans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.machine.total_cleans,
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="average_cleaning_duration",
        translation_key="average_cleaning_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.machine.average_duration(c.today, AVERAGE_WINDOW_DAYS),
        attrs_fn=lambda _: {"window_days": AVERAGE_WINDOW_DAYS},
        exists_fn=_stats,
    ),
    LitterBoxSensorDescription(
        key="current_cleaning_duration",
        translation_key="current_cleaning_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.machine.current_cycle_seconds(dt_util.utcnow()),
        available_fn=lambda c: c.machine.main.current is not None,
    ),
    LitterBoxSensorDescription(
        key="last_bag_door_opened",
        translation_key="last_bag_door_opened",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.machine.bag_door_opened_at,
        attrs_fn=lambda c: {
            "source": c.machine.bag_door_source.value
            if c.machine.bag_door_source
            else None
        },
        exists_fn=_maintenance,
    ),
    LitterBoxSensorDescription(
        key="days_since_bag_door_opened",
        translation_key="days_since_bag_door_opened",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda c: c.machine.days_since_bag_door_opened(c.today),
        exists_fn=_maintenance,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LitterBoxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        (
            CurrentDurationSensor
            if d.key == "current_cleaning_duration"
            else LitterBoxSensor
        )(coordinator, d)
        for d in SENSORS
        if d.exists_fn(coordinator)
    )


class LitterBoxSensor(LitterBoxEntity, SensorEntity):
    """A litter box sensor."""

    entity_description: LitterBoxSensorDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def available(self) -> bool:
        """Return availability."""
        return self.entity_description.available_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator)


class CurrentDurationSensor(LitterBoxSensor):
    """Elapsed time of the running cycle, refreshed periodically while cleaning."""

    _tick_unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Start ticking if a cycle is already running."""
        await super().async_added_to_hass()
        self.async_on_remove(self._stop_tick)
        self._sync_tick()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync_tick()
        super()._handle_coordinator_update()

    @callback
    def _sync_tick(self) -> None:
        if self.coordinator.machine.cycle is None:
            self._stop_tick()
        elif self._tick_unsub is None:
            self._tick_unsub = async_track_time_interval(
                self.hass, self._tick, CURRENT_DURATION_INTERVAL
            )

    @callback
    def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @callback
    def _stop_tick(self) -> None:
        if self._tick_unsub:
            self._tick_unsub()
            self._tick_unsub = None
