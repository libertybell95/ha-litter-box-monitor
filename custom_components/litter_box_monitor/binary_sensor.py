"""Binary sensors for Litter Box Monitor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LitterBoxCoordinator
from .entity import LitterBoxEntity

if TYPE_CHECKING:
    from . import LitterBoxConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LitterBoxBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a litter box binary sensor."""

    is_on_fn: Callable[[LitterBoxCoordinator], bool | None]
    attrs_fn: Callable[[LitterBoxCoordinator], dict[str, Any]] | None = None
    available_fn: Callable[[LitterBoxCoordinator], bool] = lambda _: True
    exists_fn: Callable[[LitterBoxCoordinator], bool] = lambda _: True


def _fault_attrs(c: LitterBoxCoordinator) -> dict[str, Any]:
    return c.machine.fault.as_dict() if c.machine.fault else {}


def _input_attrs(c: LitterBoxCoordinator) -> dict[str, Any]:
    trackers = {"main_door": c.machine.main, "bag_door": c.machine.bag}
    return {
        f"{role}_available": trackers[role].current is not None
        for role in c.input_entities
    }


BINARY_SENSORS: tuple[LitterBoxBinarySensorDescription, ...] = (
    LitterBoxBinarySensorDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda c: c.machine.fault is not None,
        attrs_fn=_fault_attrs,
    ),
    LitterBoxBinarySensorDescription(
        key="cleaning_active",
        translation_key="cleaning_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda c: c.machine.cycle is not None,
        available_fn=lambda c: c.machine.main.current is not None,
    ),
    LitterBoxBinarySensorDescription(
        key="maintenance_due",
        translation_key="maintenance_due",
        is_on_fn=lambda c: c.maintenance_due,
        attrs_fn=lambda c: {"threshold_days": c.maintenance_threshold},
        exists_fn=lambda c: (
            c.bag_door_entity is not None and c.maintenance_threshold > 0
        ),
    ),
    LitterBoxBinarySensorDescription(
        key="input_sensors",
        translation_key="input_sensors",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: c.inputs_available,
        attrs_fn=_input_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LitterBoxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        LitterBoxBinarySensor(coordinator, d)
        for d in BINARY_SENSORS
        if d.exists_fn(coordinator)
    )


class LitterBoxBinarySensor(LitterBoxEntity, BinarySensorEntity):
    """A litter box binary sensor."""

    entity_description: LitterBoxBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.is_on_fn(self.coordinator)

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
