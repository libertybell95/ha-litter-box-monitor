"""Persistent storage for a litter box (one file per config entry)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION


class LitterBoxStore(Store[dict[str, Any]]):
    """Store backed by ``.storage/litter_box_monitor.<entry_id>``."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        super().__init__(
            hass,
            STORAGE_VERSION,
            storage_key(entry_id),
            atomic_writes=True,
        )


def storage_key(entry_id: str) -> str:
    """Return the storage key for a config entry."""
    return f"{DOMAIN}.{entry_id}"
