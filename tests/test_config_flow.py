"""Config, reconfigure and options flow tests."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.litter_box_monitor.const import (
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
    DOMAIN,
)

from .conftest import BAG, MAIN, make_entry, setup_entry

OTHER = "binary_sensor.other_door"


@pytest.fixture(autouse=True)
def _sensors(hass: HomeAssistant) -> None:
    hass.states.async_set(MAIN, STATE_ON)
    hass.states.async_set(BAG, STATE_OFF)
    hass.states.async_set(OTHER, STATE_OFF)
    hass.states.async_set("sensor.not_binary", "1")


def _user_input(**overrides: Any) -> dict[str, Any]:
    return {
        CONF_NAME: "Litter Box",
        CONF_MAIN_DOOR: MAIN,
        CONF_BAG_DOOR: BAG,
        CONF_CLEANING_TIMEOUT: 5,
        CONF_FAULT_MONITORING: True,
        CONF_MAINTENANCE_TRACKING: True,
        CONF_STATISTICS: True,
        CONF_FAULT_EVENTS: True,
        **overrides,
    }


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_full_flow(hass: HomeAssistant) -> None:
    """User and maintenance steps create an entry."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(**{CONF_CLEANING_TIMEOUT: 7})
    )
    assert result["step_id"] == "maintenance"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MAINTENANCE_THRESHOLD: 14,
            CONF_INITIAL_BAG_DOOR_OPENED: "2026-01-01T08:00:00+00:00",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Litter Box"
    assert result["data"] == {
        CONF_MAIN_DOOR: MAIN,
        CONF_BAG_DOOR: BAG,
        CONF_INITIAL_BAG_DOOR_OPENED: "2026-01-01T08:00:00+00:00",
    }
    assert result["options"][CONF_CLEANING_TIMEOUT] == 7
    assert result["options"][CONF_MAINTENANCE_THRESHOLD] == 14
    assert result["options"][CONF_HISTORY_RETENTION] == 90


async def test_flow_without_maintenance(hass: HomeAssistant) -> None:
    """Maintenance tracking off skips the second step and the bag door."""
    result = await _start(hass)
    user_input = _user_input(**{CONF_MAINTENANCE_TRACKING: False})
    user_input.pop(CONF_BAG_DOOR)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MAIN_DOOR: MAIN}


@pytest.mark.parametrize(
    ("overrides", "field", "error"),
    [
        ({CONF_BAG_DOOR: MAIN}, CONF_BAG_DOOR, "same_entity"),
        ({CONF_MAIN_DOOR: "binary_sensor.ghost"}, CONF_MAIN_DOOR, "entity_not_found"),
        ({CONF_MAIN_DOOR: "sensor.not_binary"}, CONF_MAIN_DOOR, "not_binary_sensor"),
        ({CONF_BAG_DOOR: None}, CONF_BAG_DOOR, "bag_door_required"),
    ],
)
async def test_user_step_errors(
    hass: HomeAssistant, overrides: dict, field: str, error: str
) -> None:
    """Invalid input is rejected with a field error."""
    result = await _start(hass)
    user_input = _user_input(**overrides)
    if user_input[CONF_BAG_DOOR] is None:
        user_input.pop(CONF_BAG_DOOR)
    # Entity selectors only allow binary_sensor in the UI; bypass for coverage.
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    result = await flow.async_step_user(user_input)
    assert result["errors"] == {field: error}


@pytest.mark.parametrize(
    ("maintenance_input", "errors"),
    [
        (
            {CONF_INITIAL_BAG_DOOR_OPENED: "not a date"},
            {CONF_INITIAL_BAG_DOOR_OPENED: "invalid_timestamp"},
        ),
        (
            {
                CONF_INITIAL_BAG_DOOR_OPENED: "1700000000",
                CONF_INITIALIZE_BAG_DOOR_NOW: True,
            },
            {"base": "conflicting_initialization"},
        ),
    ],
)
async def test_maintenance_step_errors(
    hass: HomeAssistant, maintenance_input: dict, errors: dict
) -> None:
    """Initial timestamp validation."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MAINTENANCE_THRESHOLD: 0, **maintenance_input}
    )
    assert result["errors"] == errors


async def test_duplicate_main_door_aborts(hass: HomeAssistant) -> None:
    """The same main door cannot be configured twice."""
    make_entry().add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant) -> None:
    """Reconfigure swaps inputs and keeps the entry."""
    entry = await setup_entry(hass, make_entry())
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Basement Box", CONF_MAIN_DOOR: OTHER, CONF_BAG_DOOR: BAG},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_MAIN_DOOR] == OTHER
    assert entry.title == "Basement Box"


async def test_reconfigure_same_entity_error(hass: HomeAssistant) -> None:
    """Reconfigure validates inputs too."""
    entry = await setup_entry(hass, make_entry())
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Litter Box", CONF_MAIN_DOOR: BAG, CONF_BAG_DOOR: BAG},
    )
    assert result["errors"] == {CONF_BAG_DOOR: "same_entity"}


async def test_options_require_bag_door(hass: HomeAssistant) -> None:
    """Maintenance tracking cannot be enabled without a bag door sensor."""
    entry = await setup_entry(
        hass, make_entry({CONF_MAIN_DOOR: MAIN}, maintenance_tracking=False)
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CLEANING_TIMEOUT: 5,
            CONF_FAULT_MONITORING: True,
            CONF_MAINTENANCE_TRACKING: True,
            CONF_STATISTICS: True,
            CONF_FAULT_EVENTS: True,
            CONF_MAINTENANCE_THRESHOLD: 0,
            CONF_HISTORY_RETENTION: 90,
        },
    )
    assert result["errors"] == {CONF_MAINTENANCE_TRACKING: "bag_door_required"}
