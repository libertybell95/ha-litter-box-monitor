"""Daily rollover, DST and maintenance tracking inside Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.litter_box_monitor.const import (
    CONF_BAG_DOOR,
    CONF_INITIAL_BAG_DOOR_OPENED,
    CONF_INITIALIZE_BAG_DOOR_NOW,
    CONF_MAIN_DOOR,
    DOMAIN,
    EVENT_BAG_DOOR_OPENED,
    SERVICE_SET_BAG_DOOR_OPENED,
)

from .conftest import (
    BAG,
    BAG_EVENT,
    CLEANS_7D,
    CLEANS_TODAY,
    CLEANS_YESTERDAY,
    DAYS_SINCE_BAG,
    LAST_BAG,
    MAIN,
    TOTAL_CLEANS,
    make_entry,
    setup_entry,
    state,
)

TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
MAINTENANCE_DUE = "binary_sensor.litter_box_maintenance_due"


async def _start(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    local: datetime,
    entry_data: dict | None = None,
    **options,
):
    await hass.config.async_set_time_zone(TZ_NAME)
    freezer.move_to(local.replace(tzinfo=TZ))
    hass.states.async_set(MAIN, STATE_ON)
    hass.states.async_set(BAG, STATE_OFF)
    data = {CONF_MAIN_DOOR: MAIN, CONF_BAG_DOOR: BAG, **(entry_data or {})}
    return await setup_entry(hass, make_entry(data, **options))


async def _move(hass: HomeAssistant, freezer: FrozenDateTimeFactory, local: datetime):
    freezer.move_to(local.replace(tzinfo=TZ))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _set(hass: HomeAssistant, entity_id: str, value: str) -> None:
    hass.states.async_set(entity_id, value)
    await hass.async_block_till_done()


async def _clean_at(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, local: datetime
) -> None:
    await _move(hass, freezer, local)
    await _set(hass, MAIN, STATE_OFF)
    await _move(hass, freezer, local + timedelta(minutes=2))
    await _set(hass, MAIN, STATE_ON)


async def test_daily_reset_at_local_midnight_without_events(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Counters roll over at local midnight with no door activity."""
    await _start(hass, freezer, datetime(2026, 10, 13, 9, 0))
    await _clean_at(hass, freezer, datetime(2026, 10, 13, 10, 0))
    await _clean_at(hass, freezer, datetime(2026, 10, 13, 20, 0))
    assert state(hass, CLEANS_TODAY) == "2"

    await _move(hass, freezer, datetime(2026, 10, 13, 23, 59, 59))
    assert state(hass, CLEANS_TODAY) == "2"
    await _move(hass, freezer, datetime(2026, 10, 14, 0, 0, 1))
    assert state(hass, CLEANS_TODAY) == "0"
    assert state(hass, CLEANS_YESTERDAY) == "2"
    assert state(hass, CLEANS_7D) == "2"
    assert state(hass, TOTAL_CLEANS) == "2"

    # And keeps rolling on following nights.
    await _move(hass, freezer, datetime(2026, 10, 15, 0, 0, 1))
    assert state(hass, CLEANS_YESTERDAY) == "0"
    assert state(hass, CLEANS_7D) == "2"


async def test_cycle_crossing_midnight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A cycle is assigned to the date on which it completes."""
    await _start(hass, freezer, datetime(2026, 10, 13, 23, 0))
    await _move(hass, freezer, datetime(2026, 10, 13, 23, 59))
    await _set(hass, MAIN, STATE_OFF)
    await _move(hass, freezer, datetime(2026, 10, 14, 0, 1))
    await _set(hass, MAIN, STATE_ON)
    assert state(hass, CLEANS_TODAY) == "1"
    assert state(hass, CLEANS_YESTERDAY) == "0"


@pytest.mark.parametrize(
    ("clean_local", "before_midnight", "after_midnight"),
    [
        # DST ends 2026-11-01 02:00 CDT -> 01:00 CST (25-hour day).
        (
            datetime(2026, 11, 1, 1, 30, fold=1),
            datetime(2026, 11, 1, 23, 59),
            datetime(2026, 11, 2, 0, 0, 1),
        ),
        # DST starts 2026-03-08 02:00 CST -> 03:00 CDT (23-hour day).
        (
            datetime(2026, 3, 8, 3, 30),
            datetime(2026, 3, 8, 23, 59),
            datetime(2026, 3, 9, 0, 0, 1),
        ),
    ],
)
async def test_dst_transitions(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    clean_local: datetime,
    before_midnight: datetime,
    after_midnight: datetime,
) -> None:
    """Midnight is tracked in local time on 23- and 25-hour days."""
    start = clean_local.replace(hour=0, minute=30, fold=0)
    await _start(hass, freezer, start)
    await _clean_at(hass, freezer, clean_local)
    assert state(hass, CLEANS_TODAY) == "1"
    await _move(hass, freezer, before_midnight)
    assert state(hass, CLEANS_TODAY) == "1"
    await _move(hass, freezer, after_midnight)
    assert state(hass, CLEANS_TODAY) == "0"
    assert state(hass, CLEANS_YESTERDAY) == "1"


async def test_bag_door_opened(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A real closed->open transition records maintenance."""
    await _start(hass, freezer, datetime(2026, 10, 13, 9, 0))
    events = async_capture_events(hass, EVENT_BAG_DOOR_OPENED)
    assert state(hass, LAST_BAG) == STATE_UNKNOWN
    assert state(hass, DAYS_SINCE_BAG) == STATE_UNKNOWN

    await _move(hass, freezer, datetime(2026, 10, 13, 18, 0))
    await _set(hass, BAG, STATE_ON)
    opened = datetime(2026, 10, 13, 18, 0, tzinfo=TZ)
    assert dt_util.parse_datetime(state(hass, LAST_BAG)) == opened
    assert hass.states.get(LAST_BAG).attributes["source"] == "observed"
    assert state(hass, DAYS_SINCE_BAG) == "0"
    assert len(events) == 1
    assert events[0].data["opened_at"] == dt_util.as_utc(opened).isoformat()
    assert hass.states.get(BAG_EVENT).attributes["event_type"] == "bag_door_opened"

    # Closing and duplicate "on" deliveries do not record anything.
    hass.states.async_set(BAG, STATE_ON, force_update=True)
    await hass.async_block_till_done()
    assert len(events) == 1

    # Day count rolls over at local midnight, not after 24 hours.
    await _move(hass, freezer, datetime(2026, 10, 14, 0, 0, 1))
    assert state(hass, DAYS_SINCE_BAG) == "1"
    await _move(hass, freezer, datetime(2026, 10, 16, 0, 0, 1))
    assert state(hass, DAYS_SINCE_BAG) == "3"


async def test_bag_door_already_open_at_startup(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Starting with the bag door open records nothing."""
    await hass.config.async_set_time_zone(TZ_NAME)
    freezer.move_to(datetime(2026, 10, 13, 9, 0, tzinfo=TZ))
    hass.states.async_set(MAIN, STATE_ON)
    hass.states.async_set(BAG, STATE_ON)
    events = async_capture_events(hass, EVENT_BAG_DOOR_OPENED)
    await setup_entry(hass, make_entry())
    assert state(hass, LAST_BAG) == STATE_UNKNOWN
    assert events == []


async def test_initialize_now_option(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Legacy Node-RED initialization is applied once and labelled."""
    entry = await _start(
        hass,
        freezer,
        datetime(2026, 10, 13, 9, 0),
        {CONF_INITIALIZE_BAG_DOOR_NOW: True},
    )
    assert hass.states.get(LAST_BAG).attributes["source"] == "initialized"
    first = state(hass, LAST_BAG)
    await _move(hass, freezer, datetime(2026, 10, 14, 9, 0))
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, LAST_BAG) == first


async def test_initial_timestamp_from_node_red(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A Node-RED millisecond timestamp can seed the value."""
    opened = datetime(2026, 10, 10, 8, 0, tzinfo=TZ)
    await _start(
        hass,
        freezer,
        datetime(2026, 10, 13, 9, 0),
        {CONF_INITIAL_BAG_DOOR_OPENED: str(int(opened.timestamp() * 1000))},
    )
    assert dt_util.parse_datetime(state(hass, LAST_BAG)) == opened
    assert hass.states.get(LAST_BAG).attributes["source"] == "manual"
    assert state(hass, DAYS_SINCE_BAG) == "3"


async def test_set_bag_door_service(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The service accepts ISO and Unix values and validates input."""
    entry = await _start(hass, freezer, datetime(2026, 10, 13, 9, 0))
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_BAG_DOOR_OPENED,
        {"config_entry_id": entry.entry_id, "timestamp": "2026-10-11T07:00:00"},
        blocking=True,
    )
    assert dt_util.parse_datetime(state(hass, LAST_BAG)) == datetime(
        2026, 10, 11, 7, 0, tzinfo=TZ
    )
    assert state(hass, DAYS_SINCE_BAG) == "2"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_BAG_DOOR_OPENED,
        {"config_entry_id": entry.entry_id},
        blocking=True,
    )
    assert state(hass, DAYS_SINCE_BAG) == "0"

    for bad in ("yesterday", "2099-01-01T00:00:00", "12"):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_BAG_DOOR_OPENED,
                {"config_entry_id": entry.entry_id, "timestamp": bad},
                blocking=True,
            )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_BAG_DOOR_OPENED,
            {"config_entry_id": "nope"},
            blocking=True,
        )


async def test_maintenance_due(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The reminder turns on after the threshold in calendar days."""
    await _start(
        hass, freezer, datetime(2026, 10, 13, 9, 0), maintenance_threshold_days=2
    )
    assert state(hass, MAINTENANCE_DUE) == STATE_UNKNOWN
    await _set(hass, BAG, STATE_ON)
    assert state(hass, MAINTENANCE_DUE) == STATE_OFF
    await _move(hass, freezer, datetime(2026, 10, 15, 0, 0, 1))
    assert state(hass, MAINTENANCE_DUE) == STATE_ON


async def test_maintenance_disabled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """No maintenance entities without maintenance tracking."""
    await hass.config.async_set_time_zone(TZ_NAME)
    hass.states.async_set(MAIN, STATE_ON)
    entry = await setup_entry(
        hass, make_entry({CONF_MAIN_DOOR: MAIN}, maintenance_tracking=False)
    )
    assert hass.states.get(LAST_BAG) is None
    assert hass.states.get(BAG_EVENT) is None
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_BAG_DOOR_OPENED,
            {"config_entry_id": entry.entry_id},
            blocking=True,
        )
