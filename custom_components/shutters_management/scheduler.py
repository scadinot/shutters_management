"""Planification et exécution des ouvertures/fermetures d'une sous-entrée.

Extrait d'``__init__.py`` sans modification. Contient le calcul des
déclenchements (heure fixe ou événement solaire, décalage, jours actifs,
aléa), l'exécution groupée ou séquentielle sur les volets, et les capteurs de
prochaine ouverture / fermeture.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any


from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_UNAVAILABLE,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import (
    HomeAssistant,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_sunrise,
    async_track_sunset,
    async_track_time_change,
)
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.util import dt as dt_util

from .notifications import _async_dispatch_notifications
from .presence import _is_away_for
from .state_store import ShuttersStateStore
from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_SEQUENTIAL_COVERS,
    COVER_ACTION_TIMEOUT_SECONDS,
    COVER_SEQUENCE_TRIGGER_PERCENT,
    DAYS,
    DEFAULT_CLOSE_MODE,
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DEFAULT_RANDOM_MAX_MINUTES,
    DEFAULT_SEQUENTIAL_COVERS,
    DOMAIN,
    MODE_FIXED,
    MODE_NONE,
    MODE_SUNRISE,
    MODE_SUNSET,
    SUBENTRY_TYPE_INSTANCE,
    TRIGGER_MODES,
    signal_state_update,
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


def _next_datetime_for(
    local_now: datetime, time_value: time, days_keys: list[str]
) -> datetime | None:
    """Return the next datetime matching time_value on an active weekday."""
    candidate = local_now.replace(
        hour=time_value.hour,
        minute=time_value.minute,
        second=time_value.second,
        microsecond=0,
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    for _ in range(8):
        if DAYS[candidate.weekday()] in days_keys:
            return candidate
        candidate += timedelta(days=1)
    return None


class ShuttersScheduler:
    """Schedule open/close actions for one instance subentry."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub_entry: ConfigEntry,
        subentry: ConfigSubentry,
        state_store: ShuttersStateStore,
    ) -> None:
        self.hass = hass
        self.hub_entry = hub_entry
        self.subentry = subentry
        self._state_store = state_store
        self.paused = bool(
            state_store.get(subentry.subentry_id).get("paused", False)
        )
        self._unsubs: list[Callable[[], None]] = []
        self._pending_unsubs: list[Callable[[], None]] = []

    @property
    def subentry_id(self) -> str:
        return self.subentry.subentry_id

    @property
    def _settings(self) -> dict[str, Any]:
        data = dict(self.subentry.data)
        # Plain "Planification" (instance) ignores presence-simulation fields
        # even if leftover values exist in storage from a pre-v0.5.0 install.
        if self.subentry.subentry_type == SUBENTRY_TYPE_INSTANCE:
            for key in (
                CONF_RANDOMIZE,
                CONF_RANDOM_MAX_MINUTES,
                CONF_ONLY_WHEN_AWAY,
                CONF_PRESENCE_ENTITY,
            ):
                data.pop(key, None)
        return data

    @callback
    def async_schedule(self) -> None:
        """Register the time triggers based on each event's mode."""
        settings = self._settings

        open_mode = self._resolve_mode(
            settings.get(CONF_OPEN_MODE, DEFAULT_OPEN_MODE),
            DEFAULT_OPEN_MODE,
            f"{SERVICE_OPEN_COVER} mode",
        )
        close_mode = self._resolve_mode(
            settings.get(CONF_CLOSE_MODE, DEFAULT_CLOSE_MODE),
            DEFAULT_CLOSE_MODE,
            f"{SERVICE_CLOSE_COVER} mode",
        )

        self._unsubs.append(
            self._register_trigger(
                SERVICE_OPEN_COVER,
                open_mode,
                settings.get(CONF_OPEN_TIME),
                int(settings.get(CONF_OPEN_OFFSET, DEFAULT_OPEN_OFFSET)),
            )
        )
        self._unsubs.append(
            self._register_trigger(
                SERVICE_CLOSE_COVER,
                close_mode,
                settings.get(CONF_CLOSE_TIME),
                int(settings.get(CONF_CLOSE_OFFSET, DEFAULT_CLOSE_OFFSET)),
            )
        )

        _LOGGER.debug(
            "Scheduled covers %s: open=(%s) close=(%s)",
            settings.get(CONF_COVERS),
            open_mode,
            close_mode,
        )

    def _resolve_mode(
        self, mode: str, default_mode: str, context: str
    ) -> str:
        """Return a known trigger mode, defaulting + warning on unknown values."""
        if mode in TRIGGER_MODES:
            return mode
        _LOGGER.warning(
            "Unknown trigger mode %r for %s on subentry %s; falling back to %r",
            mode,
            context,
            self.subentry_id,
            default_mode,
        )
        return default_mode

    def _register_trigger(
        self,
        service: str,
        mode: str,
        time_value: str | None,
        offset_min: int,
    ) -> Callable[[], None]:
        """Register a single open/close trigger for the given mode."""
        if mode == MODE_NONE:
            return lambda: None
        handler = self._make_handler(service)
        if mode == MODE_FIXED:
            time_obj = _parse_time(time_value)
            return async_track_time_change(
                self.hass,
                handler,
                hour=time_obj.hour,
                minute=time_obj.minute,
                second=time_obj.second,
            )
        offset_td = timedelta(minutes=offset_min)
        if mode == MODE_SUNRISE:
            return async_track_sunrise(self.hass, handler, offset_td)
        if mode == MODE_SUNSET:
            return async_track_sunset(self.hass, handler, offset_td)
        raise ValueError(f"unexpected trigger mode {mode!r}")

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
        def _handle(now: datetime | None = None) -> None:
            current = now if now is not None else dt_util.utcnow()
            self.hass.async_create_task(self._async_trigger(service, current))

        return _handle

    async def _async_trigger(self, service: str, now: datetime) -> None:
        """Decide whether to run the service for this trigger.

        The trigger that just fired is now in the past, so the
        next-trigger sensors are refreshed first, whatever happens next.
        Otherwise a skipped trigger (inactive day, presence at home), a
        randomized delay or a deferred call dropped at re-check would
        leave them advertising a past datetime until the next action.
        """
        async_dispatcher_send(self.hass, signal_state_update(self.subentry_id))
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
        """Check active day, pause and presence conditions."""
        if self.paused:
            _LOGGER.debug("Skipping %s: simulation is paused", service)
            return False
        settings = self._settings
        local_now = dt_util.as_local(now)
        active_days: list[str] = settings.get(CONF_DAYS, DAYS)
        weekday_key = DAYS[local_now.weekday()]
        if weekday_key not in active_days:
            _LOGGER.debug("Skipping %s: %s not in active days", service, weekday_key)
            return False
        if settings.get(CONF_ONLY_WHEN_AWAY) and not _is_away_for(
            self.hass, self.hub_entry.data
        ):
            _LOGGER.debug("Skipping %s: presence detected at home", service)
            return False
        return True

    async def _async_deferred_call(self, service: str) -> None:
        """Re-check conditions before firing a delayed action."""
        if self.hass.data.get(DOMAIN, {}).get(self.subentry_id) is not self:
            return
        if not self._conditions_met(service, dt_util.utcnow()):
            return
        await self._async_call(service)

    async def _async_call(self, service: str) -> None:
        """Invoke the cover service on all configured entities.

        Two modes, gated by the hub-level ``sequential_covers`` toggle:

        * **Parallel** (default): one batched ``cover.<service>`` call on
          the available covers; HA dispatches immediately, no waiting.
        * **Sequential**: shuffle the list, then for each cover issue
          its own ``blocking=True`` call and wait for the cover to
          either report half its travel (``current_position`` past
          ``COVER_SEQUENCE_TRIGGER_PERCENT``) or reach the action's
          terminal state (``open`` / ``closed``) before moving on.
          Drivers that don't publish ``current_position`` fall back to
          waiting for the terminal state. A per-cover timeout
          (``COVER_ACTION_TIMEOUT_SECONDS``) prevents a stuck or
          stateless cover from blocking the queue indefinitely.

        In both modes, notifications fire **once** at the end (one
        message for the whole batch, not one per cover). In sequential
        mode a cover whose service call fails is skipped and left out of
        the notification; no notification is sent when every cover
        failed.
        """
        covers = self._settings.get(CONF_COVERS, [])
        if not covers:
            return

        sequential = self.hub_entry.data.get(
            CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS
        )

        if sequential:
            ordered = list(covers)
            random.shuffle(ordered)
            _LOGGER.debug(
                "Sequential cover.%s on %s (random order)", service, ordered
            )
            processed = await self._async_call_sequential(service, ordered)
        else:
            processed = [
                entity_id
                for entity_id in covers
                if self._is_actionable(entity_id)
            ]
            if processed:
                await self.hass.services.async_call(
                    "cover",
                    service,
                    {ATTR_ENTITY_ID: processed},
                    blocking=False,
                )
                _LOGGER.info("Called cover.%s on %s", service, processed)

        # If we got unloaded mid-call (sequential mode aborts on
        # subentry remove / HA shutdown), don't notify or signal: the
        # subentry is being torn down and the notification would list
        # covers that may not all have been actioned anyway.
        if self.hass.data.get(DOMAIN, {}).get(self.subentry_id) is not self:
            return

        if processed:
            await self._async_send_notifications(service, processed)
        async_dispatcher_send(self.hass, signal_state_update(self.subentry_id))

    def _is_actionable(self, entity_id: str) -> bool:
        """Tell whether Home Assistant can act on ``entity_id`` right now.

        Core's ``entity_service_call`` silently drops entities whose
        ``available`` is False: the call returns without raising *and*
        without moving anything. Checking first keeps two promises --
        the sequential queue never waits
        ``COVER_ACTION_TIMEOUT_SECONDS`` for a progress signal that
        cannot come, and the notification never names a cover that did
        not move.

        Only an explicit ``unavailable`` is rejected. Two states are
        deliberately left alone:

        * ``unknown`` -- such a cover is available and does accept the
          command; only its position is undetermined.
        * no state object at all -- the entity is absent from the state
          machine (deleted, renamed, or its integration not loaded
          yet). Core cannot serve it either, so the call is futile, but
          that is a stale-configuration problem of its own rather than
          an offline device, and reporting it belongs to a separate
          change.
        """
        state = self.hass.states.get(entity_id)
        if state is not None and state.state == STATE_UNAVAILABLE:
            _LOGGER.warning(
                "Cover %s is unavailable; not actioning it", entity_id
            )
            return False
        return True

    async def _async_call_sequential(
        self, service: str, ordered: list[str]
    ) -> list[str]:
        """Run ``cover.<service>`` on each cover in the given order, in turn.

        ``ordered`` is the already-shuffled list; the caller owns the
        shuffling. Returns the covers that were actionable and whose
        service call succeeded, in processing order, so the
        notification body only lists covers that were actually
        actioned.

        A failing call (``HomeAssistantError`` such as a device
        communication error, or any exception raised by the cover
        driver) is logged and the queue moves on to the next cover: one
        unreachable shutter must not leave the rest of the house
        untouched.
        """
        target_state = (
            STATE_OPEN if service == SERVICE_OPEN_COVER else STATE_CLOSED
        )
        actioned: list[str] = []
        for entity_id in ordered:
            # If the scheduler was unloaded mid-sequence (entry remove,
            # HA shutdown, ...), bail out cleanly.
            if self.hass.data.get(DOMAIN, {}).get(self.subentry_id) is not self:
                _LOGGER.debug(
                    "Aborting sequential cover sequence: scheduler unloaded"
                )
                return actioned
            if not self._is_actionable(entity_id):
                continue
            try:
                await self.hass.services.async_call(
                    "cover",
                    service,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 — never block the queue
                _LOGGER.warning(
                    "Failed to call cover.%s on %s: %s; "
                    "continuing with the next cover",
                    service,
                    entity_id,
                    err,
                )
                continue
            _LOGGER.info("Called cover.%s on %s", service, entity_id)
            actioned.append(entity_id)
            await self._async_wait_for_cover_progress(entity_id, target_state)
        return actioned

    async def _async_wait_for_cover_progress(
        self, entity_id: str, target_state: str
    ) -> None:
        """Wait until ``entity_id`` is far enough along to release the queue.

        Returns as soon as **either**:

        - the cover's state equals ``target_state`` (it finished its
          travel early, or it was already in position), or
        - the cover's ``current_position`` attribute has crossed
          ``COVER_SEQUENCE_TRIGGER_PERCENT`` in the direction of travel
          (``>=`` the threshold when opening, ``<=`` the threshold when
          closing).

        Drivers that never publish ``current_position`` fall back to
        the terminal-state condition transparently.

        Subscribes to state-change events first, *then* re-reads the
        current state. This ordering closes the (theoretical, on
        cooperative scheduling) race window where the cover could flip
        between the read and the subscribe.

        Times out after ``COVER_ACTION_TIMEOUT_SECONDS`` if the cover
        never publishes a usable progress signal (some minimalist
        drivers don't); the timeout is logged at warning level and the
        queue moves on to the next cover.
        """
        finished = asyncio.Event()

        def _position_threshold_reached(position) -> bool:
            if not isinstance(position, (int, float)):
                return False
            if target_state == STATE_OPEN:
                return position >= COVER_SEQUENCE_TRIGGER_PERCENT
            return position <= COVER_SEQUENCE_TRIGGER_PERCENT

        def _is_done(state_obj) -> bool:
            if state_obj is None:
                return False
            if state_obj.state == target_state:
                return True
            return _position_threshold_reached(
                state_obj.attributes.get("current_position")
            )

        @callback
        def _on_state_change(event) -> None:
            if _is_done(event.data.get("new_state")):
                finished.set()

        unsub = async_track_state_change_event(
            self.hass, [entity_id], _on_state_change
        )
        try:
            if _is_done(self.hass.states.get(entity_id)):
                return
            await asyncio.wait_for(
                finished.wait(), timeout=COVER_ACTION_TIMEOUT_SECONDS
            )
        except TimeoutError:
            _LOGGER.warning(
                "Cover %s did not report state %s or position past %s%% "
                "within %s seconds; continuing with the next cover",
                entity_id,
                target_state,
                COVER_SEQUENCE_TRIGGER_PERCENT,
                COVER_ACTION_TIMEOUT_SECONDS,
            )
        finally:
            unsub()

    async def _async_send_notifications(
        self, cover_service: str, processed_covers: list[str]
    ) -> None:
        """Dispatch the action to push notifiers and to TTS speakers."""
        action = ACTION_OPEN if cover_service == SERVICE_OPEN_COVER else ACTION_CLOSE
        await _async_dispatch_notifications(
            self.hass,
            self.hub_entry,
            self.subentry,
            action,
            processed_covers,
        )

    def next_open(self) -> datetime | None:
        """Return the next scheduled opening as a UTC datetime."""
        return self._next_for(
            CONF_OPEN_TIME, CONF_OPEN_MODE, CONF_OPEN_OFFSET, DEFAULT_OPEN_MODE
        )

    def next_close(self) -> datetime | None:
        """Return the next scheduled closing as a UTC datetime."""
        return self._next_for(
            CONF_CLOSE_TIME, CONF_CLOSE_MODE, CONF_CLOSE_OFFSET, DEFAULT_CLOSE_MODE
        )

    def _next_for(
        self,
        time_key: str,
        mode_key: str,
        offset_key: str,
        default_mode: str,
    ) -> datetime | None:
        """Compute the next trigger, dispatching on the configured mode."""
        if self.paused:
            return None
        settings = self._settings
        days_keys: list[str] = settings.get(CONF_DAYS, DAYS)
        if not days_keys:
            return None
        mode = self._resolve_mode(
            settings.get(mode_key, default_mode), default_mode, mode_key
        )
        if mode == MODE_NONE:
            return None
        if mode == MODE_FIXED:
            time_value = _parse_time(settings[time_key])
            local_now = dt_util.as_local(dt_util.utcnow())
            local_next = _next_datetime_for(local_now, time_value, days_keys)
            if local_next is None:
                return None
            return dt_util.as_utc(local_next)
        if mode == MODE_SUNRISE:
            event = SUN_EVENT_SUNRISE
        elif mode == MODE_SUNSET:
            event = SUN_EVENT_SUNSET
        else:  # pragma: no cover — _resolve_mode already enforces TRIGGER_MODES
            return None
        offset_min = int(settings.get(offset_key, 0))
        return self._next_sun(event, offset_min, days_keys)

    def _next_sun(
        self, event: str, offset_min: int, days_keys: list[str]
    ) -> datetime | None:
        """Find the next sunrise/sunset (with offset) on an active day."""
        offset_td = timedelta(minutes=offset_min)
        candidate = get_astral_event_next(
            self.hass, event, dt_util.utcnow(), offset_td
        )
        for _ in range(8):
            if candidate is None:
                return None
            local = dt_util.as_local(candidate)
            if DAYS[local.weekday()] in days_keys:
                return candidate
            candidate = get_astral_event_next(
                self.hass,
                event,
                candidate + timedelta(seconds=1),
                offset_td,
            )
        return None

    async def async_run_now(self, action: str) -> None:
        """Trigger an immediate open or close, bypassing all conditions."""
        service = SERVICE_OPEN_COVER if action == ACTION_OPEN else SERVICE_CLOSE_COVER
        _LOGGER.info("Manual run_now: %s", service)
        await self._async_call(service)

    async def async_set_paused(self, paused: bool) -> None:
        """Update the paused flag and notify listeners."""
        if self.paused == paused:
            return
        self.paused = paused
        self._state_store.async_set(self.subentry_id, {"paused": paused})
        _LOGGER.info("Simulation %s", "paused" if paused else "resumed")
        async_dispatcher_send(self.hass, signal_state_update(self.subentry_id))
