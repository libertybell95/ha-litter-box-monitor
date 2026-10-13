"""Home Assistant glue around the litter box state machine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_entity_registry_updated_event,
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAG_DOOR,
    CONF_CLEANING_TIMEOUT,
    CONF_FAULT_EVENTS,
    CONF_FAULT_MONITORING,
    CONF_HISTORY_RETENTION,
    CONF_INITIAL_BAG_DOOR_OPENED,
    CONF_INITIALIZE_BAG_DOOR_NOW,
    CONF_MAIN_DOOR,
    CONF_MAINTENANCE_THRESHOLD,
    CONF_MAINTENANCE_TRACKING,
    CONF_STATISTICS,
    DEFAULT_OPTIONS,
    DOMAIN,
    ISSUE_ENTITY_MISSING,
    ISSUE_ENTITY_UNAVAILABLE,
    OBSERVATION_GRACE,
    STORAGE_SAVE_DELAY,
    TRANSITION_LOG_SIZE,
    UNAVAILABLE_REPAIR_DELAY,
    VERSION,
)
from .state_machine import (
    DoorState,
    EventType,
    LitterBoxStateMachine,
    MachineConfig,
    MachineEvent,
    MaintenanceSource,
)
from .storage import LitterBoxStore

if TYPE_CHECKING:
    from . import LitterBoxConfigEntry

_LOGGER = logging.getLogger(__name__)

# Earliest timestamp accepted for imported/manual values.
_MIN_TIMESTAMP = datetime(2000, 1, 1, tzinfo=dt_util.UTC)
# Values above this are interpreted as Unix milliseconds (Node-RED Date.getTime()).
_MS_THRESHOLD = 1e11

_FAULT_EVENTS = {EventType.FAULT_DETECTED, EventType.FAULT_CLEARED}


def parse_timestamp(value: Any, now: datetime | None = None) -> datetime:
    """Parse an ISO 8601 string, Unix seconds/milliseconds or datetime.

    Naive values are interpreted in Home Assistant's time zone. Raises
    ValueError for unparsable, pre-2000 or future values.
    """
    now = now or dt_util.utcnow()
    result: datetime | None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = _from_unix(float(value))
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            result = _from_unix(float(text))
        except ValueError:
            result = dt_util.parse_datetime(text)
    else:
        result = None
    if result is None:
        raise ValueError("unrecognized timestamp")
    if result.tzinfo is None:
        result = result.replace(tzinfo=dt_util.get_default_time_zone())
    result = dt_util.as_utc(result)
    if result < _MIN_TIMESTAMP or result > now + timedelta(minutes=5):
        raise ValueError("timestamp out of range")
    return result


def _from_unix(number: float) -> datetime:
    if not math.isfinite(number):
        raise ValueError("invalid number")
    if number > _MS_THRESHOLD:
        number /= 1000
    try:
        return dt_util.utc_from_timestamp(number)
    except (OverflowError, OSError) as err:
        raise ValueError("timestamp out of range") from err


def door_state_from(state: State | None) -> DoorState | None:
    """Map a binary sensor state to a door state (None = unknown)."""
    if state is None:
        return None
    if state.state == STATE_ON:
        return DoorState.OPEN
    if state.state == STATE_OFF:
        return DoorState.CLOSED
    return None


def local_date(value: datetime) -> date:
    """Local calendar date in Home Assistant's configured time zone."""
    return dt_util.as_local(value).date()


class LitterBoxCoordinator:
    """Owns the state machine, its persistence, timers and HA subscriptions."""

    def __init__(self, hass: HomeAssistant, entry: LitterBoxConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.options: dict[str, Any] = {**DEFAULT_OPTIONS, **entry.options}
        self.main_door_entity: str = entry.data[CONF_MAIN_DOOR]
        self.bag_door_entity: str | None = (
            entry.data.get(CONF_BAG_DOOR)
            if self.options[CONF_MAINTENANCE_TRACKING]
            else None
        )
        self.device_id: str | None = None
        self.machine = LitterBoxStateMachine(
            MachineConfig(
                cleaning_timeout=timedelta(minutes=self.options[CONF_CLEANING_TIMEOUT]),
                fault_monitoring=self.options[CONF_FAULT_MONITORING],
                statistics=self.options[CONF_STATISTICS],
                maintenance_tracking=self.options[CONF_MAINTENANCE_TRACKING],
                retention_days=int(self.options[CONF_HISTORY_RETENTION]),
                observation_grace=OBSERVATION_GRACE,
            ),
            local_date,
            TRANSITION_LOG_SIZE,
        )
        self.store = LitterBoxStore(hass, entry.entry_id)
        self._initial_maintenance_applied = False
        self._listeners: list[CALLBACK_TYPE] = []
        self._event_listeners: list[Callable[[MachineEvent], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timeout_unsub: CALLBACK_TYPE | None = None
        self._timeout_at: datetime | None = None
        self._midnight_unsub: CALLBACK_TYPE | None = None
        self._repair_timers: dict[str, CALLBACK_TYPE] = {}
        self._stop_unsub: CALLBACK_TYPE | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Device name."""
        return self.entry.title

    @property
    def maintenance_threshold(self) -> int:
        """Days after which maintenance is due (0 = disabled)."""
        return int(self.options[CONF_MAINTENANCE_THRESHOLD])

    @property
    def input_entities(self) -> dict[str, str]:
        """Configured inputs by role."""
        inputs = {"main_door": self.main_door_entity}
        if self.bag_door_entity:
            inputs["bag_door"] = self.bag_door_entity
        return inputs

    async def async_load(self) -> None:
        """Restore persisted data (before entities are added)."""
        stored = await self.store.async_load()
        if stored:
            self.machine.load(stored.get("machine") or {})
            self._initial_maintenance_applied = bool(
                stored.get("initial_maintenance_applied")
            )
        _LOGGER.debug(
            "%s: restored cycle=%s fault=%s main=%s bag=%s",
            self.name,
            self.machine.cycle,
            self.machine.fault,
            self.machine.main,
            self.machine.bag,
        )
        self._apply_initial_maintenance()
        self.machine.prune(self.today)

    @callback
    def async_start(self) -> None:
        """Subscribe to inputs and reconcile with their current states."""
        self._running = True
        inputs = list(self.input_entities.values())
        self._unsubs.append(
            async_track_state_change_event(self.hass, inputs, self._handle_state_event)
        )
        self._unsubs.append(
            async_track_entity_registry_updated_event(
                self.hass, inputs, self._handle_registry_event
            )
        )
        self._stop_unsub = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._handle_stop
        )
        events = self.machine.apply_config(dt_util.utcnow())
        for role, entity_id in self.input_entities.items():
            state = self.hass.states.get(entity_id)
            events += self._feed(role, state)
            self._update_repairs(role, entity_id, state)
        self._schedule_midnight()
        self._process(events)

    async def async_shutdown(self) -> None:
        """Cancel every callback and flush storage."""
        self._running = False
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None
        self._cancel_timeout()
        if self._midnight_unsub:
            self._midnight_unsub()
            self._midnight_unsub = None
        for unsub in self._repair_timers.values():
            unsub()
        self._repair_timers.clear()
        await self.store.async_save(self._data_to_save())

    # ------------------------------------------------------------------
    # Listener registration for entities
    # ------------------------------------------------------------------

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register a state update listener."""
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    @callback
    def async_add_event_listener(
        self, event_callback: Callable[[MachineEvent], None]
    ) -> CALLBACK_TYPE:
        """Register a domain event listener (event entities)."""
        self._event_listeners.append(event_callback)
        return lambda: self._event_listeners.remove(event_callback)

    # ------------------------------------------------------------------
    # Derived values for entities
    # ------------------------------------------------------------------

    @property
    def today(self) -> date:
        """Today's local date."""
        return dt_util.now().date()

    @property
    def inputs_available(self) -> bool:
        """Whether every configured input reports a valid state."""
        if self.machine.main.current is None:
            return False
        return self.bag_door_entity is None or self.machine.bag.current is not None

    @property
    def maintenance_due(self) -> bool | None:
        """Whether the maintenance threshold has been reached."""
        days = self.machine.days_since_bag_door_opened(self.today)
        if days is None:
            return None
        return days >= self.maintenance_threshold

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        if not self._running:
            return
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        for role, configured in self.input_entities.items():
            if configured == entity_id:
                events = self._feed(role, new_state)
                self._update_repairs(role, entity_id, new_state)
                self._process(events)

    @callback
    def _feed(self, role: str, state: State | None) -> list[MachineEvent]:
        door = door_state_from(state)
        if state is not None and door is None:
            _LOGGER.debug("%s: %s reported %s", self.name, role, state.state)
        now = dt_util.utcnow()
        changed_at = state.last_changed if state is not None else None
        if role == "main_door":
            return self.machine.handle_main_door(door, now, changed_at)
        return self.machine.handle_bag_door(door, now, changed_at)

    @callback
    def _handle_registry_event(
        self, event: Event[er.EventEntityRegistryUpdatedData]
    ) -> None:
        data = event.data
        if data["action"] == "remove":
            role = self._role_for(data["entity_id"])
            if role:
                self._create_issue(ISSUE_ENTITY_MISSING, role, data["entity_id"])
            return
        if data["action"] != "update" or "old_entity_id" not in data:
            return
        old, new = data["old_entity_id"], data["entity_id"]
        new_data = dict(self.entry.data)
        for key in (CONF_MAIN_DOOR, CONF_BAG_DOOR):
            if new_data.get(key) == old:
                new_data[key] = new
        _LOGGER.info("%s: input %s renamed to %s, reloading", self.name, old, new)
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    def _role_for(self, entity_id: str) -> str | None:
        for role, configured in self.input_entities.items():
            if configured == entity_id:
                return role
        return None

    @callback
    def _handle_stop(self, _event: Event) -> None:
        self._stop_unsub = None  # listen_once listeners remove themselves
        # Make sure observed_until is captured at shutdown so the restart gap
        # can be measured; the Store flushes this on final write.
        self.store.async_delay_save(self._data_to_save, STORAGE_SAVE_DELAY)

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    @callback
    def async_set_bag_door_opened(self, at: datetime) -> None:
        """Manually set the maintenance timestamp."""
        self.machine.set_bag_door_opened(at, MaintenanceSource.MANUAL)
        self._process([])

    def _apply_initial_maintenance(self) -> None:
        if self._initial_maintenance_applied:
            return
        self._initial_maintenance_applied = True
        if self.machine.bag_door_opened_at is not None:
            return
        data = self.entry.data
        if raw := data.get(CONF_INITIAL_BAG_DOOR_OPENED):
            try:
                at = parse_timestamp(raw)
            except ValueError:
                _LOGGER.warning(
                    "%s: ignoring invalid initial timestamp %r", self.name, raw
                )
            else:
                self.machine.set_bag_door_opened(at, MaintenanceSource.MANUAL)
        elif data.get(CONF_INITIALIZE_BAG_DOOR_NOW):
            self.machine.set_bag_door_opened(
                dt_util.utcnow(), MaintenanceSource.INITIALIZED
            )
        self.store.async_delay_save(self._data_to_save, 0)

    # ------------------------------------------------------------------
    # Output processing
    # ------------------------------------------------------------------

    @callback
    def _process(self, events: list[MachineEvent]) -> None:
        for machine_event in events:
            self._emit(machine_event)
        delay = 0 if self.machine.consume_critical_change() else STORAGE_SAVE_DELAY
        self.store.async_delay_save(self._data_to_save, delay)
        self._sync_timeout()
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def _emit(self, machine_event: MachineEvent) -> None:
        if machine_event.type in _FAULT_EVENTS and not self.options[CONF_FAULT_EVENTS]:
            return
        _LOGGER.debug("%s: %s %s", self.name, machine_event.type, machine_event.data)
        self.hass.bus.async_fire(
            f"{DOMAIN}_{machine_event.type}",
            {
                "config_entry_id": self.entry.entry_id,
                "device_id": self.device_id,
                "name": self.name,
                **machine_event.data,
            },
        )
        for event_callback in list(self._event_listeners):
            event_callback(machine_event)

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "machine": self.machine.as_dict(dt_util.utcnow()),
            "initial_maintenance_applied": self._initial_maintenance_applied,
        }

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    @callback
    def _sync_timeout(self) -> None:
        deadline = self.machine.timeout_deadline if self._running else None
        if deadline == self._timeout_at:
            return
        self._cancel_timeout()
        if deadline is None:
            return
        self._timeout_at = deadline
        self._timeout_unsub = async_track_point_in_utc_time(
            self.hass, self._handle_timeout, deadline
        )
        _LOGGER.debug("%s: stuck-door timeout scheduled for %s", self.name, deadline)

    @callback
    def _cancel_timeout(self) -> None:
        if self._timeout_unsub:
            self._timeout_unsub()
        self._timeout_unsub = None
        self._timeout_at = None

    @callback
    def _handle_timeout(self, _now: datetime) -> None:
        self._timeout_unsub = None
        self._timeout_at = None
        if not self._running:
            return
        self._process(self.machine.check_timeout(dt_util.utcnow()))

    @callback
    def _schedule_midnight(self) -> None:
        tomorrow = dt_util.now().date() + timedelta(days=1)
        midnight = dt_util.start_of_local_day(tomorrow)
        self._midnight_unsub = async_track_point_in_utc_time(
            self.hass, self._handle_midnight, dt_util.as_utc(midnight)
        )

    @callback
    def _handle_midnight(self, _now: datetime) -> None:
        self._midnight_unsub = None
        if not self._running:
            return
        self.machine.prune(self.today)
        self._schedule_midnight()
        self._process([])

    # ------------------------------------------------------------------
    # Repairs
    # ------------------------------------------------------------------

    @callback
    def _update_repairs(self, role: str, entity_id: str, state: State | None) -> None:
        if door_state_from(state) is not None:
            if unsub := self._repair_timers.pop(role, None):
                unsub()
            for issue in (ISSUE_ENTITY_MISSING, ISSUE_ENTITY_UNAVAILABLE):
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(issue, role))
            return
        if role in self._repair_timers:
            return

        @callback
        def _check(_now: datetime) -> None:
            self._repair_timers.pop(role, None)
            if not self._running or door_state_from(self.hass.states.get(entity_id)):
                return
            missing = (
                self.hass.states.get(entity_id) is None
                and er.async_get(self.hass).async_get(entity_id) is None
            )
            self._create_issue(
                ISSUE_ENTITY_MISSING if missing else ISSUE_ENTITY_UNAVAILABLE,
                role,
                entity_id,
            )

        self._repair_timers[role] = async_call_later(
            self.hass, UNAVAILABLE_REPAIR_DELAY, _check
        )

    def _issue_id(self, issue: str, role: str) -> str:
        return f"{issue}_{self.entry.entry_id}_{role}"

    @callback
    def _create_issue(self, issue: str, role: str, entity_id: str) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(issue, role),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR
            if issue == ISSUE_ENTITY_MISSING
            else ir.IssueSeverity.WARNING,
            translation_key=issue,
            translation_placeholders={
                "name": self.name,
                "entity_id": entity_id,
                "role": role.replace("_", " "),
            },
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """Snapshot for the diagnostics download."""
        machine = self.machine
        return {
            "version": VERSION,
            "status": machine.status,
            "inputs": {
                role: {
                    "entity_id": entity_id,
                    "state": (
                        s.state if (s := self.hass.states.get(entity_id)) else None
                    ),
                    "last_changed": s.last_changed.isoformat() if s else None,
                }
                for role, entity_id in self.input_entities.items()
            },
            "timers": {
                "timeout_at": self._timeout_at.isoformat()
                if self._timeout_at
                else None,
                "midnight_scheduled": self._midnight_unsub is not None,
                "repair_checks": sorted(self._repair_timers),
            },
            "stored": machine.as_dict(dt_util.utcnow()),
            "recent_transitions": list(machine.transitions),
        }
