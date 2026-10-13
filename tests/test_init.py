"""Integration tests: operational behaviour inside Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.litter_box_monitor.const import (
    CONF_BAG_DOOR,
    CONF_CLEANING_TIMEOUT,
    CONF_MAIN_DOOR,
    DOMAIN,
    EVENT_CLEANING_COMPLETED,
    EVENT_FAULT_CLEARED,
    EVENT_FAULT_DETECTED,
)
from custom_components.litter_box_monitor.storage import storage_key

from .conftest import (
    AVG_DURATION,
    BAG,
    CLEANING_ACTIVE,
    CLEANING_EVENT,
    CLEANS_7D,
    CLEANS_TODAY,
    ERROR_REASON,
    FAULT_EVENT,
    LAST_CLEANING,
    LAST_DURATION,
    MAIN,
    PROBLEM,
    STATUS,
    TOTAL_CLEANS,
    make_entry,
    setup_entry,
    state,
)

START = datetime(2026, 10, 13, 15, 0, tzinfo=dt_util.UTC)


async def _set(hass: HomeAssistant, entity_id: str, value: str) -> None:
    hass.states.async_set(entity_id, value)
    await hass.async_block_till_done()


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _ready(hass: HomeAssistant, freezer: FrozenDateTimeFactory, **options):
    freezer.move_to(START)
    hass.states.async_set(MAIN, STATE_ON)
    hass.states.async_set(BAG, STATE_OFF)
    return await setup_entry(hass, make_entry(**options))


async def _clean(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 120
) -> None:
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(seconds=seconds))
    await _set(hass, MAIN, STATE_ON)


async def test_device_and_entities(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """One device groups every entity; defaults are sensible."""
    entry = await _ready(hass, freezer)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    assert device.name == "Litter Box"
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert all(e.device_id == device.id for e in entities)
    assert {e.unique_id for e in entities} >= {
        f"{entry.entry_id}_status",
        f"{entry.entry_id}_problem",
        f"{entry.entry_id}_cleaning",
    }
    current = er.async_get(hass).async_get(
        "sensor.litter_box_current_cleaning_duration"
    )
    assert current.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # No maintenance threshold configured -> no Maintenance Due entity.
    assert hass.states.get("binary_sensor.litter_box_maintenance_due") is None

    assert state(hass, STATUS) == "ready"
    assert state(hass, ERROR_REASON) == "none"
    assert state(hass, PROBLEM) == STATE_OFF
    assert state(hass, CLEANING_ACTIVE) == STATE_OFF
    assert state(hass, CLEANS_TODAY) == "0"
    assert state(hass, LAST_CLEANING) == STATE_UNKNOWN
    assert state(hass, "binary_sensor.litter_box_input_sensors") == STATE_ON


async def test_cleaning_cycle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Closed then open completes a counted cycle."""
    await _ready(hass, freezer)
    completed = async_capture_events(hass, EVENT_CLEANING_COMPLETED)

    await _set(hass, MAIN, STATE_OFF)
    assert state(hass, STATUS) == "cleaning"
    assert state(hass, CLEANING_ACTIVE) == STATE_ON

    await _advance(hass, freezer, timedelta(seconds=150))
    await _set(hass, MAIN, STATE_ON)
    assert state(hass, STATUS) == "ready"
    assert state(hass, CLEANS_TODAY) == "1"
    assert state(hass, CLEANS_7D) == "1"
    assert state(hass, TOTAL_CLEANS) == "1"
    assert state(hass, LAST_DURATION) == "150"
    assert state(hass, AVG_DURATION) == "150.0"
    assert dt_util.parse_datetime(state(hass, LAST_CLEANING)) == START + timedelta(
        seconds=150
    )
    assert len(completed) == 1
    assert completed[0].data["duration_seconds"] == 150
    assert completed[0].data["device_id"] is not None
    event_state = hass.states.get(CLEANING_EVENT)
    assert event_state.attributes["event_type"] == "cleaning_completed"


async def test_timeout_fault_and_recovery(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The timer fires without further state changes; one event per fault."""
    await _ready(hass, freezer)
    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    cleared = async_capture_events(hass, EVENT_FAULT_CLEARED)

    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=4, seconds=59))
    assert state(hass, STATUS) == "cleaning"

    await _advance(hass, freezer, timedelta(seconds=2))
    assert state(hass, STATUS) == "error"
    assert state(hass, PROBLEM) == STATE_ON
    assert state(hass, ERROR_REASON) == "main_door_stuck_closed"
    assert len(detected) == 1
    data = detected[0].data
    assert data["fault_type"] == "main_door_stuck_closed"
    assert data["reason"] == "Main door stuck closed"
    assert data["elapsed_seconds"] == 301
    assert data["cleaning_started_at"] == START.isoformat()
    assert hass.states.get(FAULT_EVENT).attributes["event_type"] == "fault_detected"

    # Reevaluation (time passing, duplicate deliveries) does not re-notify.
    await _advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(MAIN, STATE_OFF, force_update=True)
    await hass.async_block_till_done()
    assert len(detected) == 1

    await _set(hass, MAIN, STATE_ON)
    assert state(hass, STATUS) == "ready"
    assert state(hass, PROBLEM) == STATE_OFF
    assert len(cleared) == 1
    assert cleared[0].data["resolution"] == "main_door_opened"
    assert state(hass, TOTAL_CLEANS) == "0"


async def test_fault_events_can_be_disabled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With fault events off, the fault still shows but nothing is fired."""
    await _ready(hass, freezer, fault_events=False)
    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=6))
    assert state(hass, PROBLEM) == STATE_ON
    assert detected == []
    assert hass.states.get(FAULT_EVENT) is None


async def test_invalid_and_unavailable_states(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Unknown/unavailable/garbage never count as transitions."""
    await _ready(hass, freezer)
    for value in (STATE_UNAVAILABLE, STATE_UNKNOWN, "jammed"):
        await _set(hass, MAIN, value)
        assert state(hass, STATUS) == "sensor_unavailable"
        assert state(hass, CLEANING_ACTIVE) == STATE_UNAVAILABLE
        assert state(hass, "binary_sensor.litter_box_input_sensors") == STATE_OFF
    await _advance(hass, freezer, timedelta(minutes=10))
    await _set(hass, MAIN, STATE_ON)
    assert state(hass, STATUS) == "ready"
    assert state(hass, TOTAL_CLEANS) == "0"


async def test_temporary_unavailability_during_cycle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A short dropout keeps the cycle and the original timeout deadline."""
    await _ready(hass, freezer)
    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=2))
    await _set(hass, MAIN, STATE_UNAVAILABLE)
    await _advance(hass, freezer, timedelta(seconds=30))
    await _set(hass, MAIN, STATE_OFF)
    # Deadline is still START + 5 min, not reconnect + 5 min.
    await _advance(hass, freezer, timedelta(minutes=2, seconds=31))
    assert len(detected) == 1


async def test_delayed_sensor_availability(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Inputs that load after the integration are reconciled, not counted."""
    freezer.move_to(START)
    await setup_entry(hass, make_entry())
    completed = async_capture_events(hass, EVENT_CLEANING_COMPLETED)
    assert state(hass, STATUS) == "sensor_unavailable"
    await _advance(hass, freezer, timedelta(seconds=20))
    await _set(hass, MAIN, STATE_ON)
    await _set(hass, BAG, STATE_ON)
    assert state(hass, STATUS) == "ready"
    assert completed == []
    assert state(hass, "sensor.litter_box_last_bag_door_opened") == STATE_UNKNOWN


async def test_restart_during_cleaning(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage
) -> None:
    """Cycle start survives a restart; the timer is not restarted from zero."""
    entry = await _ready(hass, freezer)
    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=1))

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage[storage_key(entry.entry_id)]["data"]["machine"]
    assert stored["cycle"]["started_at"] == START.isoformat()

    # Restart takes 30s; the sensor integration re-creates its state, which
    # resets last_changed to "now".
    await _advance(hass, freezer, timedelta(seconds=30))
    hass.states.async_remove(MAIN)
    hass.states.async_set(MAIN, STATE_OFF)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, STATUS) == "cleaning"
    attrs = hass.states.get(STATUS).attributes
    assert attrs["cleaning_started_at"] == START.isoformat()
    assert attrs["cycle_verified"] is True

    # Fault fires at START + 5 min (3.5 min from now), not 5 min from now.
    await _advance(hass, freezer, timedelta(minutes=3, seconds=31))
    assert len(detected) == 1


async def test_restart_with_expired_timeout(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """If the timeout expired while down, the fault is reported promptly."""
    entry = await _ready(hass, freezer)
    await _set(hass, MAIN, STATE_OFF)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await _advance(hass, freezer, timedelta(minutes=10))

    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, STATUS) == "error"
    assert len(detected) == 1
    assert detected[0].data["elapsed_seconds"] == 600


async def test_restart_with_active_fault_no_duplicate(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A persisted fault is restored silently."""
    entry = await _ready(hass, freezer)
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=6))
    assert state(hass, PROBLEM) == STATE_ON

    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, PROBLEM) == STATE_ON
    await _advance(hass, freezer, timedelta(minutes=10))
    assert detected == []


async def test_restart_no_persistent_data_door_closed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without history the cycle start is estimated and never counted."""
    freezer.move_to(START)
    hass.states.async_set(MAIN, STATE_OFF)
    await setup_entry(hass, make_entry())
    completed = async_capture_events(hass, EVENT_CLEANING_COMPLETED)
    assert state(hass, STATUS) == "cleaning"
    assert hass.states.get(STATUS).attributes["cycle_start_source"] == "estimated"
    await _advance(hass, freezer, timedelta(minutes=1))
    await _set(hass, MAIN, STATE_ON)
    assert completed == []
    assert state(hass, TOTAL_CLEANS) == "0"


async def test_statistics_persist(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Counts and timestamps survive reloads."""
    entry = await _ready(hass, freezer)
    await _clean(hass, freezer, 100)
    await _clean(hass, freezer, 200)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, TOTAL_CLEANS) == "2"
    assert state(hass, CLEANS_TODAY) == "2"
    assert state(hass, LAST_DURATION) == "200"
    assert state(hass, AVG_DURATION) == "150.0"


async def test_unload_during_active_timer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Unloading cancels the stuck-door timer and all listeners."""
    entry = await _ready(hass, freezer)
    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    await _set(hass, MAIN, STATE_OFF)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    await _advance(hass, freezer, timedelta(minutes=10))
    await _set(hass, MAIN, STATE_ON)
    assert detected == []


async def test_multiple_litter_boxes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Two entries keep independent state, devices and entities."""
    freezer.move_to(START)
    for entity_id in (MAIN, BAG, "binary_sensor.box2_main", "binary_sensor.box2_bag"):
        hass.states.async_set(entity_id, STATE_ON)
    await setup_entry(hass, make_entry())
    second = await setup_entry(
        hass,
        make_entry(
            {
                CONF_MAIN_DOOR: "binary_sensor.box2_main",
                CONF_BAG_DOOR: "binary_sensor.box2_bag",
            },
            title="Upstairs Box",
        ),
    )
    await _set(hass, "binary_sensor.box2_main", STATE_OFF)
    assert state(hass, "sensor.upstairs_box_status") == "cleaning"
    assert state(hass, STATUS) == "ready"
    assert (
        len(dr.async_entries_for_config_entry(dr.async_get(hass), second.entry_id)) == 1
    )


async def test_options_change_keeps_history(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Changing options reloads the entry and keeps statistics."""
    entry = await _ready(hass, freezer)
    await _clean(hass, freezer, 100)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**entry.options, CONF_CLEANING_TIMEOUT: 10},
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_CLEANING_TIMEOUT] == 10
    assert state(hass, TOTAL_CLEANS) == "1"

    detected = async_capture_events(hass, EVENT_FAULT_DETECTED)
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=6))
    assert detected == []
    await _advance(hass, freezer, timedelta(minutes=5))
    assert len(detected) == 1


async def test_disabling_fault_monitoring_clears_fault(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Turning off fault monitoring resolves an active fault."""
    entry = await _ready(hass, freezer)
    await _set(hass, MAIN, STATE_OFF)
    await _advance(hass, freezer, timedelta(minutes=6))
    cleared = async_capture_events(hass, EVENT_FAULT_CLEARED)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "fault_monitoring": False}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, PROBLEM) == STATE_OFF
    # Event entity is removed with fault events disabled, but bus event fires.
    assert len(cleared) == 1


async def test_input_entity_renamed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Renaming an input entity updates the entry and keeps working."""
    freezer.move_to(START)
    registry = er.async_get(hass)
    source = registry.async_get_or_create("binary_sensor", "zigbee", "door1")
    hass.states.async_set(source.entity_id, STATE_ON)
    hass.states.async_set(BAG, STATE_OFF)
    entry = await setup_entry(
        hass, make_entry({CONF_MAIN_DOOR: source.entity_id, CONF_BAG_DOOR: BAG})
    )
    registry.async_update_entity(
        source.entity_id, new_entity_id="binary_sensor.renamed"
    )
    hass.states.async_set("binary_sensor.renamed", STATE_ON)
    await hass.async_block_till_done()
    assert entry.data[CONF_MAIN_DOOR] == "binary_sensor.renamed"
    await _set(hass, "binary_sensor.renamed", STATE_OFF)
    assert state(hass, STATUS) == "cleaning"


async def test_repair_issue_for_missing_and_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Prolonged unavailability raises a repair issue that clears itself."""
    entry = await _ready(hass, freezer)
    issues = ir.async_get(hass)
    await _set(hass, MAIN, STATE_UNAVAILABLE)
    await _advance(hass, freezer, timedelta(minutes=29))
    assert not issues.issues
    await _advance(hass, freezer, timedelta(minutes=2))
    issue_id = f"entity_unavailable_{entry.entry_id}_main_door"
    assert issues.async_get_issue(DOMAIN, issue_id)

    await _set(hass, MAIN, STATE_ON)
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    hass.states.async_remove(BAG)
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(minutes=31))
    assert issues.async_get_issue(DOMAIN, f"entity_missing_{entry.entry_id}_bag_door")


async def test_diagnostics(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Diagnostics expose state, timers and transitions."""
    from custom_components.litter_box_monitor.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _ready(hass, freezer)
    await _set(hass, MAIN, STATE_OFF)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    coordinator = diag["coordinator"]
    assert coordinator["status"] == "cleaning"
    assert (
        coordinator["timers"]["timeout_at"]
        == (START + timedelta(minutes=5)).isoformat()
    )
    assert coordinator["inputs"]["main_door"]["state"] == STATE_OFF
    assert coordinator["recent_transitions"][-1]["event"] == "cycle_started"
    assert diag["entry"]["options"][CONF_CLEANING_TIMEOUT] == 5


async def test_remove_entry_deletes_storage(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage
) -> None:
    """Removing the entry removes its storage file."""
    entry = await _ready(hass, freezer)
    await _clean(hass, freezer)
    await hass.config_entries.async_unload(entry.entry_id)
    assert storage_key(entry.entry_id) in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert storage_key(entry.entry_id) not in hass_storage
