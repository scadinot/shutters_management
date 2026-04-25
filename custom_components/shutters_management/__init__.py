"""Shutters Management integration."""
from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import (
    AWAY_STATES,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    DAYS,
    DEFAULT_RANDOM_MAX_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: str | time) -> time:
    """Parse a HH:MM(:SS) string into a time object."""
    if isinstance(value, time):
        return value
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shutters Management from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    manager = ShuttersScheduler(hass, entry)
    manager.async_schedule()

    hass.data[DOMAIN][entry.entry_id] = manager

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager: ShuttersScheduler | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if manager is not None:
        manager.async_unschedule()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration on options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class ShuttersScheduler:
    """Schedule open/close actions for the configured covers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsubs: list[Callable[[], None]] = []
        self._pending_unsubs: list[Callable[[], None]] = []

    @property
    def _settings(self) -> dict[str, Any]:
        data = {**self.entry.data, **self.entry.options}
        return data

    @callback
    def async_schedule(self) -> None:
        """Register the time triggers."""
        settings = self._settings

        open_t = _parse_time(settings[CONF_OPEN_TIME])
        close_t = _parse_time(settings[CONF_CLOSE_TIME])

        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._make_handler(SERVICE_OPEN_COVER),
                hour=open_t.hour,
                minute=open_t.minute,
                second=open_t.second,
            )
        )
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._make_handler(SERVICE_CLOSE_COVER),
                hour=close_t.hour,
                minute=close_t.minute,
                second=close_t.second,
            )
        )

        _LOGGER.debug(
            "Scheduled covers %s: open=%s close=%s",
            settings.get(CONF_COVERS),
            open_t,
            close_t,
        )

    @callback
    def async_unschedule(self) -> None:
        """Cancel pending listeners and any deferred callbacks."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._pending_unsubs:
            unsub()
        self._pending_unsubs.clear()

    def _make_handler(self, service: str):
        @callback
        def _handle(now: datetime) -> None:
            self.hass.async_create_task(self._async_trigger(service, now))

        return _handle

    async def _async_trigger(self, service: str, now: datetime) -> None:
        """Decide whether to run the service for this trigger."""
        if not self._conditions_met(service, now):
            return

        delay_seconds = self._compute_delay(now)

        if delay_seconds <= 0:
            await self._async_call(service)
            return

        _LOGGER.debug(
            "Delaying %s by %s seconds (randomized)", service, delay_seconds
        )

        unsub_ref: Callable[[], None] | None = None

        @callback
        def _deferred(_fire_at: datetime) -> None:
            if unsub_ref is not None and unsub_ref in self._pending_unsubs:
                self._pending_unsubs.remove(unsub_ref)
            self.hass.async_create_task(self._async_deferred_call(service))

        unsub_ref = async_call_later(self.hass, delay_seconds, _deferred)
        self._pending_unsubs.append(unsub_ref)

    def _compute_delay(self, now: datetime) -> int:
        """Pick a random delay, capped so it stays in the current day."""
        settings = self._settings
        if not settings.get(CONF_RANDOMIZE):
            return 0
        max_minutes = int(
            settings.get(CONF_RANDOM_MAX_MINUTES, DEFAULT_RANDOM_MAX_MINUTES)
        )
        if max_minutes <= 0:
            return 0

        local_now = dt_util.as_local(now)
        end_of_day = (local_now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        seconds_until_midnight = max(
            0, int((end_of_day - local_now).total_seconds()) - 1
        )
        upper = min(max_minutes * 60, seconds_until_midnight)
        if upper <= 0:
            return 0
        return random.randint(0, upper)

    def _conditions_met(self, service: str, now: datetime) -> bool:
        """Check active day and presence conditions for the given moment."""
        settings = self._settings
        local_now = dt_util.as_local(now)
        active_days: list[str] = settings.get(CONF_DAYS, DAYS)
        weekday_key = DAYS[local_now.weekday()]
        if weekday_key not in active_days:
            _LOGGER.debug("Skipping %s: %s not in active days", service, weekday_key)
            return False
        if settings.get(CONF_ONLY_WHEN_AWAY) and not self._is_away(settings):
            _LOGGER.debug("Skipping %s: presence detected at home", service)
            return False
        return True

    async def _async_deferred_call(self, service: str) -> None:
        """Re-check conditions before firing a delayed action."""
        if self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id) is not self:
            return
        if not self._conditions_met(service, dt_util.utcnow()):
            return
        await self._async_call(service)

    async def _async_call(self, service: str) -> None:
        """Invoke the cover service for all configured entities."""
        covers = self._settings.get(CONF_COVERS, [])
        if not covers:
            return

        await self.hass.services.async_call(
            "cover",
            service,
            {ATTR_ENTITY_ID: covers},
            blocking=False,
        )
        _LOGGER.info("Called cover.%s on %s", service, covers)

    def _is_away(self, settings: dict[str, Any]) -> bool:
        """Return True when the configured presence entity reports away."""
        entity_id = settings.get(CONF_PRESENCE_ENTITY)
        if not entity_id:
            return self._all_persons_away()

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Presence entity %s is unavailable", entity_id)
            return False
        return state.state in AWAY_STATES

    def _all_persons_away(self) -> bool:
        """Fallback presence check across all person entities."""
        persons = self.hass.states.async_all("person")
        if not persons:
            _LOGGER.warning(
                "only_when_away is enabled but no presence entity is "
                "configured and no person.* exists; assuming away so the "
                "simulation can run"
            )
            return True
        return all(p.state in AWAY_STATES for p in persons)
