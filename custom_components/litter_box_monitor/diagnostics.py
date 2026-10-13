"""Diagnostics for Litter Box Monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import LitterBoxConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LitterBoxConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The integration handles no credentials, so nothing needs redacting beyond
    what Home Assistant already strips; entity ids are kept because they are
    essential for troubleshooting.
    """
    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": entry.runtime_data.diagnostics(),
    }
