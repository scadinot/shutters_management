"""Runtime state persisted across Home Assistant restarts.

Pause flags, sun-protection switches, the "sun mode" snapshot (positions
to restore) and the manual override only live on the manager objects.
Without persistence a restart silently resumed a paused schedule,
re-enabled a disabled sun protection and lost the positions to restore
once the sun leaves the façade.

One JSON document (``.storage/shutters_management.state``) maps each
subentry_id to a flat dict owned by its manager.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_SAVE_DELAY, STORAGE_VERSION


class ShuttersStateStore:
    """Thin wrapper around ``Store`` keyed by subentry_id."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load the persisted document, ignoring malformed entries."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        self._data = {
            key: dict(value)
            for key, value in stored.items()
            if isinstance(value, dict)
        }

    def all(self) -> dict[str, dict[str, Any]]:
        """Return a copy of every subentry's saved state."""
        return {key: dict(value) for key, value in self._data.items()}

    def get(self, subentry_id: str) -> dict[str, Any]:
        """Return a copy of the state saved for ``subentry_id`` (empty if none)."""
        return dict(self._data.get(subentry_id, {}))

    @callback
    def async_set(self, subentry_id: str, state: dict[str, Any]) -> None:
        """Record ``state`` for ``subentry_id`` and schedule a debounced save.

        Pending saves are flushed by ``Store`` on Home Assistant's final
        write, so a shutdown inside the debounce window loses nothing.
        """
        if self._data.get(subentry_id) == state:
            return
        self._data[subentry_id] = state
        self._async_schedule_save()

    @callback
    def async_prune(self, keep: Iterable[str]) -> None:
        """Drop the state of subentries that no longer exist."""
        keep_ids = set(keep)
        stale = [key for key in self._data if key not in keep_ids]
        if not stale:
            return
        for key in stale:
            del self._data[key]
        self._async_schedule_save()

    async def async_remove(self) -> None:
        """Delete the persisted document (hub entry removed)."""
        self._data = {}
        await self._store.async_remove()

    @callback
    def _async_schedule_save(self) -> None:
        self._store.async_delay_save(lambda: self._data, STORAGE_SAVE_DELAY)
