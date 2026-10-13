"""The Litter Box Monitor integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_TIMESTAMP,
    DOMAIN,
    SERVICE_SET_BAG_DOOR_OPENED,
    VERSION,
)
from .coordinator import LitterBoxCoordinator, parse_timestamp
from .storage import LitterBoxStore

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type LitterBoxConfigEntry = ConfigEntry[LitterBoxCoordinator]

SET_BAG_DOOR_OPENED_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_TIMESTAMP): vol.Any(cv.string, vol.Coerce(float)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""

    @callback
    def _set_bag_door_opened(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"name": entry.title},
            )
        coordinator: LitterBoxCoordinator = entry.runtime_data
        if coordinator.bag_door_entity is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="maintenance_disabled",
                translation_placeholders={"name": entry.title},
            )
        raw = call.data.get(ATTR_TIMESTAMP)
        try:
            at = parse_timestamp(raw) if raw not in (None, "") else None
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_timestamp",
                translation_placeholders={"value": str(raw)},
            ) from err
        coordinator.async_set_bag_door_opened(at or dt_util.utcnow())

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BAG_DOOR_OPENED,
        _set_bag_door_opened,
        schema=SET_BAG_DOOR_OPENED_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LitterBoxConfigEntry) -> bool:
    """Set up a litter box from a config entry."""
    coordinator = LitterBoxCoordinator(hass, entry)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Litter Box Monitor",
        model="Virtual litter box appliance",
        sw_version=VERSION,
    )
    coordinator.device_id = device.id
    await coordinator.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Start only once entities exist so restored faults/events reach them.
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LitterBoxConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop timers and listeners first so nothing fires into unloading entities.
    await entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: LitterBoxConfigEntry) -> None:
    """Delete stored history and repair issues when an entry is removed."""
    await LitterBoxStore(hass, entry.entry_id).async_remove()
    for issue in list(ir.async_get(hass).issues.values()):
        if issue.domain == DOMAIN and entry.entry_id in issue.issue_id:
            ir.async_delete_issue(hass, DOMAIN, issue.issue_id)
