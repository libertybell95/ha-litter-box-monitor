"""Shared fixtures for Litter Box Monitor tests."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.litter_box_monitor.const import (
    CONF_BAG_DOOR,
    CONF_MAIN_DOOR,
    DEFAULT_OPTIONS,
    DOMAIN,
)

MAIN = "binary_sensor.cat_litter_box_main_door"
BAG = "binary_sensor.cat_litter_box_bag_door"

STATUS = "sensor.litter_box_status"
ERROR_REASON = "sensor.litter_box_error_reason"
PROBLEM = "binary_sensor.litter_box_problem"
CLEANING_ACTIVE = "binary_sensor.litter_box_cleaning_active"
CLEANS_TODAY = "sensor.litter_box_cleans_today"
CLEANS_YESTERDAY = "sensor.litter_box_cleans_yesterday"
CLEANS_7D = "sensor.litter_box_cleans_last_7_days"
TOTAL_CLEANS = "sensor.litter_box_total_cleans"
LAST_CLEANING = "sensor.litter_box_last_cleaning"
LAST_DURATION = "sensor.litter_box_last_cleaning_duration"
AVG_DURATION = "sensor.litter_box_average_cleaning_duration"
LAST_BAG = "sensor.litter_box_last_bag_door_opened"
DAYS_SINCE_BAG = "sensor.litter_box_days_since_bag_door_opened"
FAULT_EVENT = "event.litter_box_fault"
CLEANING_EVENT = "event.litter_box_cleaning"
BAG_EVENT = "event.litter_box_bag_door"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in every test."""


def make_entry(
    data: dict[str, Any] | None = None,
    title: str = "Litter Box",
    **options: Any,
) -> MockConfigEntry:
    """Build a config entry with defaults."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data=data if data is not None else {CONF_MAIN_DOOR: MAIN, CONF_BAG_DOOR: BAG},
        options={**DEFAULT_OPTIONS, **options},
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add and set up an entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass: HomeAssistant, entity_id: str) -> str:
    """Return an entity's state string."""
    current = hass.states.get(entity_id)
    assert current is not None, f"{entity_id} missing"
    return current.state
