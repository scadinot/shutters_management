"""Moteur de protection solaire : un gestionnaire par groupe d'orientation.

Extrait d'``__init__.py`` sans modification. Contient le moteur de décision
(seuils de lux, UV et température, hystérésis, anti-rebond, dérogation
manuelle) et la restauration des positions mémorisées avant la descente.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import (
    CoreState,
    HassJob,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .notifications import _async_dispatch_notifications
from .state_store import ShuttersStateStore
from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_COVERS,
    ARC_HYSTERESIS_DEG,
    CONF_ARC,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    DEFAULT_MIN_UV,
    CONF_ORIENTATION,
    CONF_TARGET_POSITION,
    CONF_TEMP_INDOOR_ENTITY,
    CONF_TEMP_OUTDOOR_ENTITY,
    CONF_UV_ENTITY,
    DEFAULT_ARC,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_TARGET_POSITION,
    ELEVATION_HYSTERESIS_DEG,
    LUX_CLOSE_DEBOUNCE_SEC,
    LUX_HEATWAVE,
    LUX_MILD,
    LUX_OPEN_DEBOUNCE_SEC,
    UV_OPEN_DEBOUNCE_SEC,
    DEBOUNCE_RECHECK_MARGIN_SEC,
    POSITION_TOLERANCE_PCT,
    LUX_REOPEN,
    LUX_STANDARD,
    OVERRIDE_RESET_HOUR,
    SUN_ENTITY,
    T_INDOOR_MILD_MIN,
    T_INDOOR_REOPEN,
    T_INDOOR_STANDARD_MIN,
    T_OUTDOOR_HEATWAVE,
    T_OUTDOOR_NO_PROTECT,
    T_OUTDOOR_REOPEN,
    T_OUTDOOR_STANDARD,
    signal_state_update,
)
_LOGGER = logging.getLogger(__name__)


def _restored_positions(raw: Any) -> dict[str, int]:
    """Validate a persisted ``{entity_id: position}`` mapping."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(entity_id): int(position)
        for entity_id, position in raw.items()
        if isinstance(position, (int, float))
    }


def _position_matches(position: int | None, target: int | None) -> bool:
    """Whether a reported cover position counts as being at ``target``.

    Motorised covers rarely stop exactly on the requested percentage: a
    cover sent to 50 % commonly reports 49 or 51. A strict comparison
    made such a cover look manually moved, so it was never restored on
    sun-mode exit and later real manual moves went undetected.
    """
    return (
        position is not None
        and target is not None
        and abs(position - target) <= POSITION_TOLERANCE_PCT
    )


async def _async_restore_cover_positions(
    hass: HomeAssistant,
    snapshots: Mapping[str, int],
    applied_positions: Mapping[str, int],
) -> list[str]:
    """Send each snapshotted cover back to its position before sun mode.

    Iterates the snapshots rather than the configured covers, so a cover
    removed from the group while lowered is still restored. Covers moved
    away from the applied target since (by more than
    ``POSITION_TOLERANCE_PCT``: manual move) are left alone. A failing
    call is logged and skipped so one unreachable cover doesn't keep the
    others lowered. Returns the restored covers.
    """
    restored: list[str] = []
    for cover_id, snapshot in snapshots.items():
        state = hass.states.get(cover_id)
        current_pos = None
        if state is not None:
            raw = state.attributes.get("current_position")
            if raw is not None:
                current_pos = int(raw)
        if current_pos is not None and not _position_matches(
            current_pos, applied_positions.get(cover_id)
        ):
            continue
        try:
            await hass.services.async_call(
                "cover",
                "set_cover_position",
                {"entity_id": cover_id, "position": snapshot},
            )
        except Exception as err:  # noqa: BLE001 — restore the other covers
            _LOGGER.warning(
                "Failed to restore %s to position %s: %s",
                cover_id,
                snapshot,
                err,
            )
            continue
        restored.append(cover_id)
    return restored


class ShuttersSunProtectionManager:
    """Manage sun-position-based shutter lowering for one orientation group.

    Activation logic combines four sources:

    * **Sun position** (azimuth + elevation) — geometric pre-condition.
    * **Outdoor lux** (mandatory hub sensor) — arbiter of "is the sun
      actually shining". Adaptive threshold: tighter when it is hot.
    * **Outdoor temperature** (optional hub sensor) — protects solar gain
      below ``T_OUTDOOR_NO_PROTECT`` (mid-season / winter).
    * **Indoor temperature** (optional per-group sensor) — final comfort
      gate; bypassed in heatwave so we can pre-protect.

    Hysteresis (``ARC_HYSTERESIS_DEG`` / ``LUX_REOPEN`` / ...) and
    debouncing (``LUX_*_DEBOUNCE_SEC``) prevent yo-yo behaviour at the
    boundaries and through passing clouds. Manual moves on a controlled
    cover trigger a per-façade override that pauses the automation
    until the next ``OVERRIDE_RESET_HOUR`` (default 04:00 local time).
    """

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
        self._enabled = True
        self._in_sun_mode = False
        self._snapshots: dict[str, int] = {}
        self._applied_positions: dict[str, int] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._override_until: datetime | None = None
        self._lux_above_since: datetime | None = None
        self._lux_below_since: datetime | None = None
        self._uv_below_since: datetime | None = None
        self._debounce_job = HassJob(
            self._async_on_debounce_expired,
            "shutters_management sun protection debounce",
            cancel_on_shutdown=True,
        )
        self._debounce_unsub: Callable[[], None] | None = None
        self._last_status: str = "disabled"
        self._restore_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _restore_state(self) -> None:
        """Reload switch, sun-mode snapshot and override saved before a restart."""
        saved = self._state_store.get(self.subentry_id)
        self._enabled = bool(saved.get("enabled", True))
        self._in_sun_mode = bool(saved.get("in_sun_mode", False))
        self._snapshots = _restored_positions(saved.get("snapshots"))
        self._applied_positions = _restored_positions(
            saved.get("applied_positions")
        )
        override = saved.get("override_until")
        self._override_until = (
            dt_util.parse_datetime(override)
            if isinstance(override, str)
            else None
        )

    @callback
    def _async_persist_state(self) -> None:
        """Save the state that must survive a restart."""
        self._state_store.async_set(
            self.subentry_id,
            {
                "enabled": self._enabled,
                "in_sun_mode": self._in_sun_mode,
                "snapshots": dict(self._snapshots),
                "applied_positions": dict(self._applied_positions),
                "override_until": (
                    self._override_until.isoformat()
                    if self._override_until is not None
                    else None
                ),
            },
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def subentry_id(self) -> str:
        return self.subentry.subentry_id

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_active(self) -> bool:
        return self._in_sun_mode and self._enabled

    @property
    def status(self) -> str:
        return self._last_status

    @property
    def override_until(self) -> datetime | None:
        return self._override_until

    # ------------------------------------------------------------------
    # Sensor readers (public so binary_sensor / tests can introspect)
    # ------------------------------------------------------------------
    def _read_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", None):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @property
    def lux(self) -> float | None:
        return self._read_float(
            self.hub_entry.data.get(CONF_LUX_ENTITY) or None
        )

    @property
    def temp_outdoor(self) -> float | None:
        return self._read_float(
            self.hub_entry.data.get(CONF_TEMP_OUTDOOR_ENTITY) or None
        )

    @property
    def temp_indoor(self) -> float | None:
        return self._read_float(
            self.subentry.data.get(CONF_TEMP_INDOOR_ENTITY) or None
        )

    @property
    def uv(self) -> float | None:
        return self._read_float(
            self.hub_entry.data.get(CONF_UV_ENTITY) or None
        )

    # ------------------------------------------------------------------
    # Diagnostic readers (no decision impact, surfaced by sensor entities)
    # ------------------------------------------------------------------
    @property
    def azimuth(self) -> float | None:
        """Sun azimuth in degrees, or ``None`` when sun.sun is missing."""
        state = self.hass.states.get(SUN_ENTITY)
        if state is None:
            return None
        raw = state.attributes.get("azimuth")
        try:
            return float(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def elevation(self) -> float | None:
        """Sun elevation in degrees, or ``None`` when sun.sun is missing."""
        state = self.hass.states.get(SUN_ENTITY)
        if state is None:
            return None
        raw = state.attributes.get("elevation")
        try:
            return float(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    @property
    def azimuth_diff(self) -> float | None:
        """Absolute angular distance from configured orientation, or ``None``.

        Positive ``float`` in ``[0, 180]``. Compared against ``CONF_ARC`` to
        decide whether the sun is in front of the façade.
        """
        az = self.azimuth
        if az is None:
            return None
        orientation = self.subentry.data.get(CONF_ORIENTATION, 180)
        return abs((az - orientation + 180) % 360 - 180)

    @property
    def is_sun_facing(self) -> bool:
        """Geometric only: in arc AND above ``min_elevation``.

        Independent of lux / UV / temperature / override / switch — useful
        as a "would I close *if* it were bright enough?" indicator that
        helps users calibrate ``arc`` and ``min_elevation``.
        """
        diff = self.azimuth_diff
        elev = self.elevation
        if diff is None or elev is None:
            return False
        arc = self.subentry.data.get(CONF_ARC, DEFAULT_ARC)
        min_el = self.subentry.data.get(
            CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION
        )
        return diff <= arc and elev >= min_el

    @property
    def lux_close_threshold(self) -> int | None:
        """Effective adaptive lux threshold for the current ``T_ext``.

        ``None`` when no lux gate applies — either because no lux sensor is
        configured at the hub or because outdoor is below
        ``T_OUTDOOR_NO_PROTECT``.
        """
        if not (self.hub_entry.data.get(CONF_LUX_ENTITY) or ""):
            return None
        return self._close_lux_threshold(self.temp_outdoor)

    @property
    def pending_seconds(self) -> int:
        """Remaining seconds in the active debounce, 0 when none.

        Either the close-debounce (lux above threshold, waiting for
        ``LUX_CLOSE_DEBOUNCE_SEC``) or the open-debounces (lux below
        ``LUX_REOPEN`` for ``LUX_OPEN_DEBOUNCE_SEC``, UV below ``min_uv``
        for ``UV_OPEN_DEBOUNCE_SEC``). Close and open debounces cannot
        run at the same time; when both open debounces run, the first
        one to expire ends sun mode, so its remaining time is surfaced.
        """
        now = dt_util.now()
        if self._lux_above_since is not None:
            elapsed = (now - self._lux_above_since).total_seconds()
            return max(0, int(LUX_CLOSE_DEBOUNCE_SEC - elapsed))
        remaining = [
            max(0, int(delay - (now - since).total_seconds()))
            for since, delay in (
                (self._lux_below_since, LUX_OPEN_DEBOUNCE_SEC),
                (self._uv_below_since, UV_OPEN_DEBOUNCE_SEC),
            )
            if since is not None
        ]
        return min(remaining, default=0)

    # ------------------------------------------------------------------
    # Adaptive thresholds (close)
    # ------------------------------------------------------------------
    @staticmethod
    def _close_lux_threshold(t_ext: float | None) -> int | None:
        """Return the lux threshold required to close at this T_ext.

        ``None`` means the outdoor temperature is below
        ``T_OUTDOOR_NO_PROTECT`` and we want to keep solar gain.
        ``T_ext`` itself missing falls back to the standard threshold so
        the feature still works without an outdoor sensor.
        """
        if t_ext is None:
            return LUX_STANDARD
        if t_ext < T_OUTDOOR_NO_PROTECT:
            return None
        if t_ext < T_OUTDOOR_STANDARD:
            return LUX_MILD
        if t_ext < T_OUTDOOR_HEATWAVE:
            return LUX_STANDARD
        return LUX_HEATWAVE

    @staticmethod
    def _close_indoor_min(t_ext: float | None) -> int | None:
        """Indoor temperature required to close at this T_ext.

        ``None`` means the indoor check is bypassed:

        * no outdoor sensor → we don't know the temperature bracket,
          fall back to lux-only gating (no comfort gate).
        * heatwave bracket → pre-protect even with a cool room.
        """
        if t_ext is None:
            return None
        if t_ext < T_OUTDOOR_NO_PROTECT:
            return None
        if t_ext < T_OUTDOOR_STANDARD:
            return T_INDOOR_MILD_MIN
        if t_ext < T_OUTDOOR_HEATWAVE:
            return T_INDOOR_STANDARD_MIN
        return None  # heatwave: ignore indoor temperature

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------
    async def async_setup(self) -> None:
        """Subscribe to sun, lux, temp and cover state changes."""
        watched = [SUN_ENTITY]
        for key, src in (
            (CONF_LUX_ENTITY, self.hub_entry.data),
            (CONF_UV_ENTITY, self.hub_entry.data),
            (CONF_TEMP_OUTDOOR_ENTITY, self.hub_entry.data),
            (CONF_TEMP_INDOOR_ENTITY, self.subentry.data),
        ):
            entity_id = src.get(key) or ""
            if entity_id:
                watched.append(entity_id)
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, watched, self._async_on_state_change
            )
        )
        covers = list(self.subentry.data.get(CONF_COVERS, []))
        if covers:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, covers, self._async_on_cover_state_change
                )
            )
        # Daily reset of the manual override.
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._async_daily_reset,
                hour=OVERRIDE_RESET_HOUR,
                minute=0,
                second=0,
            )
        )
        # At boot, wait for Home Assistant to be fully started: sun.sun
        # and the light / temperature sensors may not have reported yet,
        # and a restored sun mode would otherwise be exited (covers
        # reopened) on a transient "unavailable".
        #
        # When already running (reload, tests) run the initial evaluate
        # inline so callers can rely on the manager's status / decision
        # state being up-to-date right after ``async_setup`` returns.
        # (``async_call_later(0, …)`` was previously used here, but that
        # path is not deterministic under ``freezegun`` in tests.)
        if self.hass.state is CoreState.running:
            await self.async_evaluate()
        else:
            self._unsubs.append(
                async_at_started(self.hass, self._async_on_started)
            )

    async def async_unload(self, *, restore_covers: bool) -> None:
        """Cancel subscriptions; exit sun mode only when asked to.

        On a plain reload the sun mode and the positions to restore are
        already persisted: the manager created on setup picks them up and
        the covers stay where they are.
        """
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._async_cancel_debounce_check()
        if restore_covers and self._in_sun_mode:
            await self._async_exit_sun_mode()

    async def _async_on_started(self, _hass: HomeAssistant) -> None:
        await self.async_evaluate()

    async def _async_on_state_change(self, event: Any) -> None:
        await self.async_evaluate()

    async def _async_on_debounce_expired(self, _now: datetime) -> None:
        self._debounce_unsub = None
        await self.async_evaluate()

    @callback
    def _async_schedule_debounce_check(self, now: datetime) -> None:
        """Re-evaluate when the earliest running debounce expires.

        The engine otherwise only reacts to state changes of the watched
        entities: a debounce reaching its term while sensors stay steady
        (constant lux, UV sensor still unavailable) would wait for the
        next unrelated update before closing or reopening.
        """
        self._async_cancel_debounce_check()
        deadlines = [
            since + timedelta(seconds=delay)
            for since, delay in (
                (self._lux_above_since, LUX_CLOSE_DEBOUNCE_SEC),
                (self._lux_below_since, LUX_OPEN_DEBOUNCE_SEC),
                (self._uv_below_since, UV_OPEN_DEBOUNCE_SEC),
            )
            if since is not None
        ]
        if not deadlines:
            return
        delay = (
            max(0.0, (min(deadlines) - now).total_seconds())
            + DEBOUNCE_RECHECK_MARGIN_SEC
        )
        self._debounce_unsub = async_call_later(
            self.hass, delay, self._debounce_job
        )

    @callback
    def _async_cancel_debounce_check(self) -> None:
        if self._debounce_unsub is not None:
            self._debounce_unsub()
            self._debounce_unsub = None

    async def _async_daily_reset(self, _now: datetime) -> None:
        if self._override_until is not None:
            _LOGGER.debug(
                "Sun protection %s: override expired at daily reset",
                self.subentry_id,
            )
            self._override_until = None
            self._async_persist_state()
            await self.async_evaluate()

    # ------------------------------------------------------------------
    # Override helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _next_reset_time(now: datetime) -> datetime:
        """Next ``OVERRIDE_RESET_HOUR`` strictly after ``now`` (local TZ)."""
        target = now.replace(
            hour=OVERRIDE_RESET_HOUR, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return target

    def _override_active(self, now: datetime) -> bool:
        return self._override_until is not None and self._override_until > now

    # ------------------------------------------------------------------
    # Decision engine
    # ------------------------------------------------------------------
    async def async_evaluate(self) -> None:
        """Recompute whether sun protection should be active and act."""
        if self.hass.state is not CoreState.running:
            # Startup (sensors not ready yet) or shutdown (sensors going
            # unavailable): never drive covers from a partial picture.
            # ``_async_on_started`` runs the first evaluation at boot.
            return
        now = dt_util.now()
        new_status, want_close, want_open = self._compute_decision(now)
        self._last_status = new_status
        self._async_schedule_debounce_check(now)

        if want_close and not self._in_sun_mode:
            await self._async_enter_sun_mode()
        elif want_open and self._in_sun_mode:
            await self._async_exit_sun_mode()

        async_dispatcher_send(
            self.hass, signal_state_update(self.subentry_id)
        )

    def _compute_decision(
        self, now: datetime
    ) -> tuple[str, bool, bool]:
        """Pure decision: returns (status, want_close, want_open).

        ``want_close`` and ``want_open`` are mutually exclusive (only one
        — at most — is True). The status string is exposed by the
        binary_sensor and is informational; it does not gate behaviour.
        Every early-return branch clears the debounce timestamps so the
        ``pending_seconds`` diagnostic never advertises a phantom
        countdown when no debounce is in flight.
        """
        if not self._enabled:
            self._lux_above_since = None
            self._lux_below_since = None
            self._uv_below_since = None
            return ("disabled", False, self._in_sun_mode)

        if self._override_active(now):
            self._lux_above_since = None
            self._lux_below_since = None
            self._uv_below_since = None
            return ("override", False, False)

        lux_entity = self.hub_entry.data.get(CONF_LUX_ENTITY) or ""
        uv_entity = self.hub_entry.data.get(CONF_UV_ENTITY) or ""
        if not lux_entity and not uv_entity:
            # Neither light sensor configured: feature is OFF. Combined
            # with the per-group switch this gives users a reliable kill
            # switch — without a brightness signal we cannot tell if it
            # is actually sunny vs. just geometrically aligned.
            self._lux_above_since = None
            self._lux_below_since = None
            self._uv_below_since = None
            return ("no_sensor", False, self._in_sun_mode)

        sun_state = self.hass.states.get(SUN_ENTITY)
        if sun_state is None:
            # HA startup race or sun integration absent. Treat as
            # "no sun": clear debounce timers and request an exit if we
            # were left in sun mode, so the covers don't stay lowered
            # indefinitely.
            self._lux_above_since = None
            self._lux_below_since = None
            self._uv_below_since = None
            return ("below_horizon", False, self._in_sun_mode)

        elevation = float(sun_state.attributes.get("elevation", 0) or 0)
        azimuth = float(sun_state.attributes.get("azimuth", 0) or 0)
        data = self.subentry.data
        min_elevation = data.get(CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION)
        orientation = data.get(CONF_ORIENTATION, 180)
        arc = data.get(CONF_ARC, DEFAULT_ARC)
        diff = abs((azimuth - orientation + 180) % 360 - 180)

        t_ext = self.temp_outdoor
        t_indoor = self.temp_indoor
        lux = self.lux
        uv = self.uv
        min_uv = int(data.get(CONF_MIN_UV, DEFAULT_MIN_UV))

        # ------------------------------------------------------------------
        # Already in sun mode: only the OPEN path applies (with hysteresis).
        # The close-debounce timer is irrelevant here, clear it once.
        # ------------------------------------------------------------------
        if self._in_sun_mode:
            self._lux_above_since = None
            if elevation < min_elevation - ELEVATION_HYSTERESIS_DEG:
                self._lux_below_since = None
                self._uv_below_since = None
                return ("below_horizon", False, True)
            if diff > arc + ARC_HYSTERESIS_DEG:
                self._lux_below_since = None
                self._uv_below_since = None
                return ("out_of_arc", False, True)
            # Lux exit (debounced) — also fires when the configured lux
            # sensor goes unknown/unavailable, so we don't stay stuck
            # closed indefinitely with no way to re-evaluate light.
            if lux_entity:
                if lux is None or lux < LUX_REOPEN:
                    if self._lux_below_since is None:
                        self._lux_below_since = now
                    if (
                        now - self._lux_below_since
                    ).total_seconds() >= LUX_OPEN_DEBOUNCE_SEC:
                        self._lux_below_since = None
                        self._uv_below_since = None
                        return ("lux_too_low", False, True)
                else:
                    self._lux_below_since = None
            else:
                # No lux gate at all — the timer must not linger.
                self._lux_below_since = None
            # UV exit (debounced like lux). A missing reading (sensor
            # unknown/unavailable) counts as "too low" so a lost sensor
            # still ends sun mode instead of freezing closed, but only
            # once it has lasted UV_OPEN_DEBOUNCE_SEC: a transient dropout
            # or an index hovering around min_uv no longer reopens.
            if uv_entity and (uv is None or uv < min_uv):
                if self._uv_below_since is None:
                    self._uv_below_since = now
                if (
                    now - self._uv_below_since
                ).total_seconds() >= UV_OPEN_DEBOUNCE_SEC:
                    self._lux_below_since = None
                    self._uv_below_since = None
                    return ("uv_too_low", False, True)
            else:
                self._uv_below_since = None
            # Comfort exit: room cool AND outdoor cool together.
            if (
                t_indoor is not None
                and t_indoor < T_INDOOR_REOPEN
                and t_ext is not None
                and t_ext < T_OUTDOOR_REOPEN
            ):
                self._lux_below_since = None
                self._uv_below_since = None
                return ("room_too_cool", False, True)
            return ("active", False, False)

        # ------------------------------------------------------------------
        # Not in sun mode: evaluate the CLOSE path. The open-debounce
        # timer is irrelevant here, clear it once.
        # ------------------------------------------------------------------
        self._lux_below_since = None
        self._uv_below_since = None
        if elevation < min_elevation:
            self._lux_above_since = None
            return ("below_horizon", False, False)
        if diff > arc:
            self._lux_above_since = None
            return ("out_of_arc", False, False)

        # Universal: outdoor too cold → keep the solar gain.
        if t_ext is not None and t_ext < T_OUTDOOR_NO_PROTECT:
            self._lux_above_since = None
            return ("temp_too_cold", False, False)

        # Lux gate (only when configured).
        if lux_entity:
            # ``_close_lux_threshold`` returns ``None`` only for the
            # too-cold branch we already handled above, so we coalesce
            # to the standard threshold defensively.
            close_lux = self._close_lux_threshold(t_ext) or LUX_STANDARD
            if lux is None or lux < close_lux:
                self._lux_above_since = None
                return ("lux_too_low", False, False)

        # UV gate (only when configured).
        if uv_entity and (uv is None or uv < min_uv):
            self._lux_above_since = None
            return ("uv_too_low", False, False)

        # Indoor comfort gate. If the user has wired an indoor sensor
        # and we are in a temperature bracket where it matters, a
        # missing reading must block the close — closing despite an
        # invisible room temperature would defeat the comfort guarantee.
        indoor_min = self._close_indoor_min(t_ext)
        indoor_entity = (
            self.subentry.data.get(CONF_TEMP_INDOOR_ENTITY) or ""
        )
        if indoor_min is not None and indoor_entity:
            if t_indoor is None or t_indoor < indoor_min:
                self._lux_above_since = None
                return ("room_too_cool", False, False)

        # All instantaneous conditions met. Debounce sustained sunshine
        # only when lux is the gating signal — UV moves slowly enough on
        # its own and a UV-only setup should react immediately.
        if lux_entity:
            if self._lux_above_since is None:
                self._lux_above_since = now
            elapsed = (now - self._lux_above_since).total_seconds()
            if elapsed < LUX_CLOSE_DEBOUNCE_SEC:
                return ("pending_close", False, False)

        self._lux_above_since = None
        return ("active", True, False)

    # ------------------------------------------------------------------
    # Cover commands
    # ------------------------------------------------------------------
    async def _async_enter_sun_mode(self) -> None:
        """Snapshot current positions and lower covers to target."""
        covers = list(self.subentry.data.get(CONF_COVERS, []))
        target = self.subentry.data.get(
            CONF_TARGET_POSITION, DEFAULT_TARGET_POSITION
        )

        processed: list[str] = []
        for cover_id in covers:
            state = self.hass.states.get(cover_id)
            if state is not None:
                pos = state.attributes.get("current_position")
                if pos is not None:
                    self._snapshots[cover_id] = int(pos)
            await self.hass.services.async_call(
                "cover",
                "set_cover_position",
                {"entity_id": cover_id, "position": target},
            )
            self._applied_positions[cover_id] = target
            processed.append(cover_id)

        self._in_sun_mode = True
        self._async_persist_state()
        _LOGGER.debug(
            "Sun protection %s: entered sun mode (target=%s%%)",
            self.subentry_id,
            target,
        )

        if processed:
            await _async_dispatch_notifications(
                self.hass,
                self.hub_entry,
                self.subentry,
                ACTION_CLOSE,
                processed,
            )

    async def _async_exit_sun_mode(self) -> None:
        """Restore cover positions, skipping any that were manually moved."""
        processed = await _async_restore_cover_positions(
            self.hass, self._snapshots, self._applied_positions
        )

        self._in_sun_mode = False
        self._snapshots.clear()
        self._applied_positions.clear()
        self._async_persist_state()
        _LOGGER.debug("Sun protection %s: exited sun mode", self.subentry_id)

        if processed:
            await _async_dispatch_notifications(
                self.hass,
                self.hub_entry,
                self.subentry,
                ACTION_OPEN,
                processed,
            )

    async def _async_on_cover_state_change(self, event: Any) -> None:
        """Detect external cover moves and arm the manual override.

        While the cover is transiting toward the applied target the
        registry replays intermediate positions in the
        ``[snapshot, applied]`` range; these must be ignored. A move is
        "manual" if either:

        * the cover has already **settled at the applied target** (its
          previous ``current_position`` was within
          ``POSITION_TOLERANCE_PCT`` of ``applied``) and now moved beyond
          that tolerance — it could only move because the user pressed a
          remote / app button, OR
        * the new position lands **outside the transit range**, widened
          by the same tolerance (the cover is e.g. opening past
          ``snapshot`` or closing past ``applied``).

        The tolerance absorbs covers that stop a point or two away from
        the requested percentage and the small jitter they report once
        settled.

        In either case we arm the per-façade override until the next
        ``OVERRIDE_RESET_HOUR`` and exit sun mode without re-driving the
        covers (the user just expressed a preference).
        """
        if not self._in_sun_mode or self.hass.state is not CoreState.running:
            # Cover states flicker while integrations load or unload:
            # never read those transitions as manual moves.
            return
        cover_id = event.data.get("entity_id")
        if cover_id not in self._applied_positions:
            return
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        new_pos = new_state.attributes.get("current_position")
        if new_pos is None:
            return
        new_pos_int = int(new_pos)
        applied = self._applied_positions.get(cover_id)
        snapshot = self._snapshots.get(cover_id)

        old_state = event.data.get("old_state")
        old_pos: int | None = None
        if old_state is not None:
            raw_old = old_state.attributes.get("current_position")
            if raw_old is not None:
                old_pos = int(raw_old)

        # Settled-at-target heuristic: if the cover was at the applied
        # target (within tolerance) and now clearly isn't, it's a manual
        # change.
        settled_then_moved = _position_matches(
            old_pos, applied
        ) and not _position_matches(new_pos_int, applied)
        out_of_transit = (
            applied is not None
            and snapshot is not None
            and not (
                min(snapshot, applied) - POSITION_TOLERANCE_PCT
                <= new_pos_int
                <= max(snapshot, applied) + POSITION_TOLERANCE_PCT
            )
        )

        if not (settled_then_moved or out_of_transit):
            return  # transit position; nothing to do.

        now = dt_util.now()
        self._override_until = self._next_reset_time(now)
        self._in_sun_mode = False
        self._snapshots.clear()
        self._applied_positions.clear()
        self._lux_above_since = None
        self._lux_below_since = None
        self._uv_below_since = None
        self._async_cancel_debounce_check()
        self._last_status = "override"
        self._async_persist_state()
        _LOGGER.debug(
            "Sun protection %s: manual move detected, override until %s",
            self.subentry_id,
            self._override_until.isoformat(),
        )
        async_dispatcher_send(
            self.hass, signal_state_update(self.subentry_id)
        )

    def set_enabled(self, enabled: bool) -> None:
        """Toggle the group on/off (called by the switch entity)."""
        self._enabled = enabled
        self._async_persist_state()
        self.hass.async_create_task(self.async_evaluate())
