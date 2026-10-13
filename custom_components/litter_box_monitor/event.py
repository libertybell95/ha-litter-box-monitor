"""Event entities for Litter Box Monitor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_FAULT_EVENTS, CONF_FAULT_MONITORING
from .coordinator import LitterBoxCoordinator
from .entity import LitterBoxEntity
from .state_machine import EventType, MachineEvent

if TYPE_CHECKING:
    from . import LitterBoxConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LitterBoxEventDescription(EventEntityDescription):
    """Describes a litter box event entity."""

    exists_fn: Callable[[LitterBoxCoordinator], bool] = lambda _: True


EVENTS: tuple[LitterBoxEventDescription, ...] = (
    LitterBoxEventDescription(
        key="cleaning",
        translation_key="cleaning",
        event_types=[EventType.CLEANING_COMPLETED.value],
    ),
    LitterBoxEventDescription(
        key="fault",
        translation_key="fault",
        event_types=[EventType.FAULT_DETECTED.value, EventType.FAULT_CLEARED.value],
        exists_fn=lambda c: bool(
            c.options[CONF_FAULT_MONITORING] and c.options[CONF_FAULT_EVENTS]
        ),
    ),
    LitterBoxEventDescription(
        key="bag_door",
        translation_key="bag_door",
        event_types=[EventType.BAG_DOOR_OPENED.value],
        exists_fn=lambda c: c.bag_door_entity is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LitterBoxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up event entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        LitterBoxEvent(coordinator, d) for d in EVENTS if d.exists_fn(coordinator)
    )


class LitterBoxEvent(LitterBoxEntity, EventEntity):
    """Event entity relaying state machine events."""

    entity_description: LitterBoxEventDescription

    async def async_added_to_hass(self) -> None:
        """Subscribe to domain events (state updates are not needed)."""
        self.async_on_remove(
            self.coordinator.async_add_event_listener(self._handle_machine_event)
        )

    @callback
    def _handle_machine_event(self, machine_event: MachineEvent) -> None:
        if machine_event.type.value not in self.event_types:
            return
        self._trigger_event(
            machine_event.type.value,
            {"device_id": self.coordinator.device_id, **machine_event.data},
        )
        self.async_write_ha_state()
