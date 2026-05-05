"""Config flow for Shutters Management.

Architecture (v0.4.0):

* The integration is a *hub*: a single ``ShuttersManagementConfigFlow``
  entry whose ``data`` carries the **shared** notification settings.
* Each shutter schedule (Bureau, RDC, ...) is a ``ConfigSubentry`` of
  type ``instance`` attached to the hub. Subentries are created and
  edited through ``ShuttersInstanceSubentryFlow``.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_ARC,
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_LUX_ENTITY,
    CONF_MIN_ELEVATION,
    CONF_MIN_UV,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_ONLY_WHEN_AWAY,
    CONF_ORIENTATION,
    CONF_SEQUENTIAL_COVERS,
    CONF_TARGET_POSITION,
    CONF_TEMP_INDOOR_ENTITY,
    CONF_TEMP_OUTDOOR_ENTITY,
    CONF_TTS_ENGINE,
    CONF_UV_ENTITY,
    CONF_TTS_MODE,
    CONF_TTS_TARGETS,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_TYPE,
    DAYS,
    DEFAULT_ARC,
    DEFAULT_CLOSE_MODE,
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_CLOSE_TIME,
    DEFAULT_DAYS,
    DEFAULT_LUX_ENTITY,
    DEFAULT_MIN_ELEVATION,
    DEFAULT_MIN_UV,
    DEFAULT_NOTIFY_MODE,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_ONLY_WHEN_AWAY,
    DEFAULT_ORIENTATION,
    DEFAULT_SEQUENTIAL_COVERS,
    DEFAULT_TARGET_POSITION,
    DEFAULT_TEMP_INDOOR_ENTITY,
    DEFAULT_TEMP_OUTDOOR_ENTITY,
    DEFAULT_TTS_MODE,
    DEFAULT_UV_ENTITY,
    DEFAULT_TTS_TARGETS,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DEFAULT_OPEN_TIME,
    DEFAULT_RANDOMIZE,
    DEFAULT_RANDOM_MAX_MINUTES,
    MODE_ALWAYS,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    MODE_HOME_ONLY,
    NOTIFY_MODES,
    TTS_MODES,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    OFFSET_MAX_MINUTES,
    OFFSET_MIN_MINUTES,
    ORIENTATION_CARDINALS,
    SUBENTRY_TYPE_INSTANCE,
    SUBENTRY_TYPE_PRESENCE_SIM,
    SUBENTRY_TYPE_SUN_PROTECTION,
    TRIGGER_MODES,
    TYPE_HUB,
)

SECTION_OPEN = "open"
SECTION_CLOSE = "close"
SECTION_COVERS = "shutters"
SECTION_SCHEDULE_DAYS = "schedule_days"
SECTION_RANDOMIZATION = "randomization"
SECTION_PRESENCE = "presence"
SECTION_ORIENTATION = "orientation"
SECTION_THRESHOLDS = "thresholds"
SECTION_ROOM_SENSOR = "room_sensor"
SECTION_NOTIFICATIONS = "notifications"
SECTION_VOICE_ANNOUNCEMENT = "voice_announcement"
SECTION_SUN_PROTECTION_SENSORS = "sun_protection_sensors"
SECTION_PRESENCE_HUB = "presence_hub"

_HUB_SECTIONS = (
    SECTION_NOTIFICATIONS,
    SECTION_VOICE_ANNOUNCEMENT,
    SECTION_SUN_PROTECTION_SENSORS,
    SECTION_PRESENCE_HUB,
)


def _available_notify_services(hass: HomeAssistant | None) -> list[str]:
    """Return ``notify.<svc>`` strings discovered on this hass instance."""
    if hass is None:
        return []
    notify_services = hass.services.async_services().get("notify", {})
    return sorted(f"notify.{name}" for name in notify_services)


def _build_hub_schema(
    hass: HomeAssistant | None, defaults: dict[str, Any]
) -> vol.Schema:
    """Schema for the hub: scheduler option + shared channels + presence.

    Layout (top → bottom):

    1. ``sequential_covers`` (top-level toggle, scheduler behaviour).
    2. Section ``notifications`` — push services only. The per-action
       mode (disabled / always / away_only) lives on each subentry.
    3. Section ``voice_announcement`` — TTS engine + speakers only.
    4. Section ``sun_protection_sensors`` — shared environmental sensors.
    5. Section ``presence_hub`` — shared presence entity used by every
       subentry's mode evaluation and by the presence-simulation gate.

    The ``defaults`` dict can be **either** flat (e.g. fresh ``user_input``
    from a previous validation pass) **or** already nested under the
    section keys (e.g. when re-rendering after the user opened a section).
    ``_section_default`` handles both shapes transparently.
    """

    notifications_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_NOTIFY_SERVICES,
                    default=_section_default(
                        defaults,
                        SECTION_NOTIFICATIONS,
                        CONF_NOTIFY_SERVICES,
                        DEFAULT_NOTIFY_SERVICES,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_available_notify_services(hass),
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        ),
        {"collapsed": True},
    )

    tts_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_TTS_ENGINE,
                    description={
                        "suggested_value": _section_default(
                            defaults,
                            SECTION_VOICE_ANNOUNCEMENT,
                            CONF_TTS_ENGINE,
                            "",
                        )
                        or None
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="tts")
                ),
                vol.Optional(
                    CONF_TTS_TARGETS,
                    default=_section_default(
                        defaults,
                        SECTION_VOICE_ANNOUNCEMENT,
                        CONF_TTS_TARGETS,
                        DEFAULT_TTS_TARGETS,
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="media_player", multiple=True
                    )
                ),
            }
        ),
        {"collapsed": True},
    )

    presence_hub_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_PRESENCE_ENTITY,
                    description={
                        "suggested_value": _section_default(
                            defaults,
                            SECTION_PRESENCE_HUB,
                            CONF_PRESENCE_ENTITY,
                            "",
                        )
                        or None
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["person", "group"]
                    )
                ),
            }
        ),
        {"collapsed": True},
    )

    sun_protection_sensors_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_LUX_ENTITY,
                    description={
                        "suggested_value": _section_default(
                            defaults,
                            SECTION_SUN_PROTECTION_SENSORS,
                            CONF_LUX_ENTITY,
                            DEFAULT_LUX_ENTITY,
                        )
                        or None
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_UV_ENTITY,
                    description={
                        "suggested_value": _section_default(
                            defaults,
                            SECTION_SUN_PROTECTION_SENSORS,
                            CONF_UV_ENTITY,
                            DEFAULT_UV_ENTITY,
                        )
                        or None
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_TEMP_OUTDOOR_ENTITY,
                    description={
                        "suggested_value": _section_default(
                            defaults,
                            SECTION_SUN_PROTECTION_SENSORS,
                            CONF_TEMP_OUTDOOR_ENTITY,
                            DEFAULT_TEMP_OUTDOOR_ENTITY,
                        )
                        or None
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        ),
        {"collapsed": True},
    )

    return vol.Schema(
        {
            vol.Required(
                CONF_SEQUENTIAL_COVERS,
                default=defaults.get(
                    CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS
                ),
            ): selector.BooleanSelector(),
            vol.Required(SECTION_NOTIFICATIONS): notifications_section,
            vol.Required(SECTION_VOICE_ANNOUNCEMENT): tts_section,
            vol.Required(
                SECTION_SUN_PROTECTION_SENSORS
            ): sun_protection_sensors_section,
            vol.Required(SECTION_PRESENCE_HUB): presence_hub_section,
        }
    )


def _section_default(
    defaults: dict[str, Any], section: str, key: str, fallback: Any
) -> Any:
    """Read a nested section value with a flat-fallback.

    Accepts both shapes so we can render the schema from either:

    * Newly-built defaults (already nested by section).
    * Legacy flat data (e.g. a hub entry created in v0.4.3 or earlier
      where every field sat at the top level of ``entry.data``).
    """
    section_block = defaults.get(section)
    if isinstance(section_block, dict) and key in section_block:
        return section_block[key]
    if key in defaults:
        return defaults[key]
    return fallback


def _build_instance_schema(
    defaults: dict[str, Any],
    *,
    include_name: bool = True,
    include_simulation: bool = False,
) -> vol.Schema:
    """Schema for a schedule subentry.

    When ``include_simulation`` is True, the four presence-simulation
    fields (``randomize``, ``random_max_minutes``, ``only_when_away``,
    ``presence_entity``) are appended. They are reserved for the
    ``presence_simulation`` subentry type; the plain ``instance``
    (Planification) flow keeps the deterministic fields only.
    """
    mode_selector = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=TRIGGER_MODES,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="trigger_modes",
        )
    )
    offset_selector = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=OFFSET_MIN_MINUTES,
            max=OFFSET_MAX_MINUTES,
            step=1,
            unit_of_measurement="min",
            mode=selector.NumberSelectorMode.BOX,
        )
    )

    open_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_OPEN_MODE,
                    default=defaults.get(CONF_OPEN_MODE, DEFAULT_OPEN_MODE),
                ): mode_selector,
                vol.Required(
                    CONF_OPEN_TIME,
                    default=defaults.get(CONF_OPEN_TIME, DEFAULT_OPEN_TIME),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_OPEN_OFFSET,
                    default=defaults.get(CONF_OPEN_OFFSET, DEFAULT_OPEN_OFFSET),
                ): offset_selector,
            }
        ),
        {"collapsed": True},
    )
    close_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_CLOSE_MODE,
                    default=defaults.get(CONF_CLOSE_MODE, DEFAULT_CLOSE_MODE),
                ): mode_selector,
                vol.Required(
                    CONF_CLOSE_TIME,
                    default=defaults.get(CONF_CLOSE_TIME, DEFAULT_CLOSE_TIME),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_CLOSE_OFFSET,
                    default=defaults.get(
                        CONF_CLOSE_OFFSET, DEFAULT_CLOSE_OFFSET
                    ),
                ): offset_selector,
            }
        ),
        {"collapsed": True},
    )

    covers_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_COVERS,
                    default=defaults.get(CONF_COVERS, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="cover", multiple=True)
                ),
            }
        ),
        {"collapsed": True},
    )

    schedule_days_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_DAYS,
                    default=defaults.get(CONF_DAYS, DEFAULT_DAYS),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DAYS,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="days",
                    )
                ),
            }
        ),
        {"collapsed": True},
    )

    notifications_section = _build_notifications_section(defaults)
    voice_announcement_section = _build_voice_announcement_section(defaults)

    fields: dict[Any, Any] = {}
    if include_name:
        fields[
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, ""))
        ] = selector.TextSelector(selector.TextSelectorConfig())
    fields.update(
        {
            vol.Required(SECTION_COVERS): covers_section,
            vol.Required(SECTION_OPEN): open_section,
            vol.Required(SECTION_CLOSE): close_section,
            vol.Required(SECTION_SCHEDULE_DAYS): schedule_days_section,
        }
    )
    if include_simulation:
        randomization_section = data_entry_flow.section(
            vol.Schema(
                {
                    vol.Required(
                        CONF_RANDOMIZE,
                        default=defaults.get(CONF_RANDOMIZE, DEFAULT_RANDOMIZE),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_RANDOM_MAX_MINUTES,
                        default=defaults.get(
                            CONF_RANDOM_MAX_MINUTES, DEFAULT_RANDOM_MAX_MINUTES
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=240,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            {"collapsed": True},
        )
        presence_section = data_entry_flow.section(
            vol.Schema(
                {
                    vol.Required(
                        CONF_ONLY_WHEN_AWAY,
                        default=defaults.get(
                            CONF_ONLY_WHEN_AWAY, DEFAULT_ONLY_WHEN_AWAY
                        ),
                    ): selector.BooleanSelector(),
                }
            ),
            {"collapsed": True},
        )
        fields.update(
            {
                vol.Required(SECTION_RANDOMIZATION): randomization_section,
                vol.Required(SECTION_PRESENCE): presence_section,
            }
        )
    fields.update(
        {
            vol.Required(SECTION_NOTIFICATIONS): notifications_section,
            vol.Required(SECTION_VOICE_ANNOUNCEMENT): voice_announcement_section,
        }
    )
    return vol.Schema(fields)


def _build_notifications_section(defaults: dict[str, Any]):
    """Subentry-level notifications section with the notify_mode selector."""
    return data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_NOTIFY_MODE,
                    default=_section_default(
                        defaults,
                        SECTION_NOTIFICATIONS,
                        CONF_NOTIFY_MODE,
                        DEFAULT_NOTIFY_MODE,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(NOTIFY_MODES),
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="notification_mode",
                    )
                ),
            }
        ),
        {"collapsed": True},
    )


def _build_voice_announcement_section(defaults: dict[str, Any]):
    """Subentry-level voice announcement section with the tts_mode selector."""
    return data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_TTS_MODE,
                    default=_section_default(
                        defaults,
                        SECTION_VOICE_ANNOUNCEMENT,
                        CONF_TTS_MODE,
                        DEFAULT_TTS_MODE,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(TTS_MODES),
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="voice_mode",
                    )
                ),
            }
        ),
        {"collapsed": True},
    )


def _strip_name(data: dict[str, Any]) -> dict[str, Any]:
    """Drop CONF_NAME from a payload destined to ``ConfigSubentry.data``.

    The instance name lives in the subentry title; storing it in
    ``data`` as well would leave a stale duplicate after a rename.
    """
    return {k: v for k, v in data.items() if k != CONF_NAME}


def _normalize_instance(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten section sub-dicts, cast types, drop empties."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in (
            SECTION_OPEN,
            SECTION_CLOSE,
            SECTION_COVERS,
            SECTION_SCHEDULE_DAYS,
            SECTION_RANDOMIZATION,
            SECTION_PRESENCE,
            SECTION_NOTIFICATIONS,
            SECTION_VOICE_ANNOUNCEMENT,
        ) and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    if CONF_RANDOM_MAX_MINUTES in flat:
        flat[CONF_RANDOM_MAX_MINUTES] = int(flat[CONF_RANDOM_MAX_MINUTES])
    # presence_entity now lives at the hub level — drop any stale value.
    flat.pop(CONF_PRESENCE_ENTITY, None)
    flat.setdefault(CONF_NOTIFY_MODE, DEFAULT_NOTIFY_MODE)
    flat.setdefault(CONF_TTS_MODE, DEFAULT_TTS_MODE)
    return flat


def _normalize_hub(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten section sub-dicts and harden multi-value fields.

    The hub form ships its two channel blocks (``notifications`` and
    ``voice_announcement``) inside HA ``data_entry_flow.section``
    containers. After submission they come back as
    ``{section_key: {field: value}, ...}``; we flatten them so the rest
    of the integration keeps reading flat ``hub_entry.data`` keys
    (``CONF_NOTIFY_SERVICES``, ``CONF_TTS_ENGINE``, ...).

    ``notify_services`` and ``tts_targets`` are multi-selects but their
    selectors (with ``custom_value=True``) may, in edge cases, deliver
    a single string rather than a list. Wrap that case explicitly to
    avoid the silent bug where ``list("notify.iphone")`` would expand
    into a list of characters.
    """
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in _HUB_SECTIONS and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value

    services = flat.get(CONF_NOTIFY_SERVICES)
    if not services:
        flat[CONF_NOTIFY_SERVICES] = []
    elif isinstance(services, str):
        flat[CONF_NOTIFY_SERVICES] = [services]
    else:
        flat[CONF_NOTIFY_SERVICES] = list(services)
    flat.setdefault(CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS)

    tts_engine = flat.get(CONF_TTS_ENGINE)
    flat[CONF_TTS_ENGINE] = tts_engine or None
    targets = flat.get(CONF_TTS_TARGETS)
    if not targets:
        flat[CONF_TTS_TARGETS] = []
    elif isinstance(targets, str):
        flat[CONF_TTS_TARGETS] = [targets]
    else:
        flat[CONF_TTS_TARGETS] = list(targets)

    flat[CONF_LUX_ENTITY] = flat.get(CONF_LUX_ENTITY) or ""
    flat[CONF_TEMP_OUTDOOR_ENTITY] = flat.get(CONF_TEMP_OUTDOOR_ENTITY) or ""
    flat[CONF_UV_ENTITY] = flat.get(CONF_UV_ENTITY) or ""
    flat[CONF_PRESENCE_ENTITY] = flat.get(CONF_PRESENCE_ENTITY) or ""
    # Mode keys are no longer hub-wide as of v0.7.0; drop any stale value.
    flat.pop(CONF_NOTIFY_MODE, None)
    flat.pop(CONF_TTS_MODE, None)
    return flat


def _needs_presence_warning(
    hass: HomeAssistant,
    data: dict[str, Any],
    hub_entry: ConfigEntry,
) -> bool:
    """Return True when only_when_away has no presence source available.

    Since v0.7.0 the presence entity lives on the hub, so the warning is
    triggered when the hub has no presence entity configured AND no
    ``person.*`` entity exists to fall back on.
    """
    if not data.get(CONF_ONLY_WHEN_AWAY):
        return False
    if hub_entry.data.get(CONF_PRESENCE_ENTITY):
        return False
    return not hass.states.async_all("person")


class ShuttersManagementConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for the *hub* entry (singleton).

    Each Shutters Management installation has exactly one hub entry that
    holds the shared notification settings. Individual schedules
    (Bureau, RDC, ...) are added as subentries via
    :class:`ShuttersInstanceSubentryFlow`.
    """

    VERSION = 7

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the hub. Only one hub may exist (singleton)."""
        await self.async_set_unique_id(HUB_UNIQUE_ID)

        if user_input is not None:
            normalized = _normalize_hub(user_input)
            data = {CONF_TYPE: TYPE_HUB, **normalized}
            return self.async_create_entry(title=HUB_TITLE, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_hub_schema(self.hass, {}),
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {
            SUBENTRY_TYPE_INSTANCE: ShuttersInstanceSubentryFlow,
            SUBENTRY_TYPE_PRESENCE_SIM: ShuttersPresenceSimulationSubentryFlow,
            SUBENTRY_TYPE_SUN_PROTECTION: ShuttersSunProtectionSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return ShuttersHubOptionsFlow()


class ShuttersHubOptionsFlow(OptionsFlow):
    """Edit the hub: notification services + away-only toggle."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            normalized = _normalize_hub(user_input)
            new_data = {CONF_TYPE: TYPE_HUB, **normalized}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        defaults = {
            CONF_NOTIFY_SERVICES: self.config_entry.data.get(
                CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES
            ),
            CONF_SEQUENTIAL_COVERS: self.config_entry.data.get(
                CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS
            ),
            CONF_TTS_ENGINE: self.config_entry.data.get(CONF_TTS_ENGINE) or "",
            CONF_TTS_TARGETS: self.config_entry.data.get(
                CONF_TTS_TARGETS, DEFAULT_TTS_TARGETS
            ),
            CONF_LUX_ENTITY: self.config_entry.data.get(
                CONF_LUX_ENTITY, DEFAULT_LUX_ENTITY
            ),
            CONF_TEMP_OUTDOOR_ENTITY: self.config_entry.data.get(
                CONF_TEMP_OUTDOOR_ENTITY, DEFAULT_TEMP_OUTDOOR_ENTITY
            ),
            CONF_UV_ENTITY: self.config_entry.data.get(
                CONF_UV_ENTITY, DEFAULT_UV_ENTITY
            ),
            CONF_PRESENCE_ENTITY: self.config_entry.data.get(
                CONF_PRESENCE_ENTITY, ""
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_build_hub_schema(self.hass, defaults),
        )


class ShuttersInstanceSubentryFlow(ConfigSubentryFlow):
    """Create or edit an *instance* subentry (deterministic schedule)."""

    # Subclasses set this to True to expose the four presence-simulation
    # fields. Plain Planification keeps it False.
    INCLUDE_SIMULATION: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._pending_data: dict[str, Any] | None = None
        self._pending_name: str | None = None
        self._pending_edit_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new instance subentry."""
        return await self._async_handle(user_input, edit_subentry_id=None)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing instance subentry."""
        return await self._async_handle(
            user_input, edit_subentry_id=self._reconfigure_subentry_id
        )

    async def _async_handle(
        self,
        user_input: dict[str, Any] | None,
        *,
        edit_subentry_id: str | None,
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_entry()

        if user_input is not None:
            data = _normalize_instance(user_input)
            name = (data.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif not data.get(CONF_COVERS):
                errors[CONF_COVERS] = "no_covers"
            elif not data.get(CONF_DAYS):
                errors[CONF_DAYS] = "no_days"
            else:
                data[CONF_NAME] = name
                if self.INCLUDE_SIMULATION and _needs_presence_warning(
                    self.hass, data, entry
                ):
                    self._pending_data = data
                    self._pending_name = name
                    self._pending_edit_id = edit_subentry_id
                    return await self.async_step_confirm_no_presence()
                return self._async_persist(
                    name, data, entry, edit_subentry_id=edit_subentry_id
                )

        defaults: dict[str, Any]
        if edit_subentry_id is not None:
            subentry = entry.subentries[edit_subentry_id]
            defaults = {**subentry.data, CONF_NAME: subentry.title}
        else:
            defaults = _normalize_instance(user_input or {})

        step_id = "reconfigure" if edit_subentry_id is not None else "user"
        return self.async_show_form(
            step_id=step_id,
            data_schema=_build_instance_schema(
                defaults, include_simulation=self.INCLUDE_SIMULATION
            ),
            errors=errors,
        )

    async def async_step_confirm_no_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Confirm save when only_when_away has no presence source."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm_no_presence",
                data_schema=vol.Schema({}),
            )

        assert self._pending_data is not None and self._pending_name is not None
        data = self._pending_data
        name = self._pending_name
        edit_id = self._pending_edit_id
        self._pending_data = None
        self._pending_name = None
        self._pending_edit_id = None

        return self._async_persist(
            name, data, self._get_entry(), edit_subentry_id=edit_id
        )

    @callback
    def _async_persist(
        self,
        name: str,
        data: dict[str, Any],
        entry: ConfigEntry,
        *,
        edit_subentry_id: str | None,
    ) -> SubentryFlowResult:
        """Create or update the subentry, then finish the flow.

        Both unique_id and the visible title are checked for collisions.
        unique_id is the primary key (set at creation, immutable on
        rename) but a user could rename ``Bureau`` to ``Étage`` and
        then create a brand-new ``Étage`` whose slugified unique_id
        wouldn't collide; the title check catches that case so the
        device list stays unambiguous.
        """
        payload = _strip_name(data)
        unique_id = slugify(name)
        normalized_title = name.casefold()

        for sub_id, existing in entry.subentries.items():
            if sub_id == edit_subentry_id:
                continue
            if existing.unique_id == unique_id:
                return self.async_abort(reason="already_configured")
            if existing.title.casefold() == normalized_title:
                return self.async_abort(reason="already_configured")

        if edit_subentry_id is not None:
            subentry = entry.subentries[edit_subentry_id]
            return self.async_update_and_abort(
                entry,
                subentry,
                title=name,
                data=payload,
            )

        return self.async_create_entry(
            title=name,
            data=payload,
            unique_id=unique_id,
        )


class ShuttersPresenceSimulationSubentryFlow(ShuttersInstanceSubentryFlow):
    """Create or edit a *presence_simulation* subentry.

    Same scheduling form as Planification, with the four presence-simulation
    fields (``randomize`` / ``random_max_minutes`` / ``only_when_away``
    / ``presence_entity``) appended to the schema.
    """

    INCLUDE_SIMULATION = True


# ---------------------------------------------------------------------------
# Sun protection subentry
# ---------------------------------------------------------------------------

def _degrees_to_cardinal(degrees: int) -> str:
    """Return the nearest cardinal key for a degree value."""
    return min(ORIENTATION_CARDINALS, key=lambda k: abs(ORIENTATION_CARDINALS[k] - degrees))


def _build_sun_protection_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Schema for a sun-protection group subentry."""
    current_orientation = defaults.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)
    if isinstance(current_orientation, int):
        current_orientation = _degrees_to_cardinal(current_orientation)

    sun_covers_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_COVERS,
                    default=defaults.get(CONF_COVERS, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="cover", multiple=True)
                ),
            }
        ),
        {"collapsed": True},
    )

    orientation_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_ORIENTATION,
                    default=current_orientation,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(ORIENTATION_CARDINALS.keys()),
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="orientation",
                    )
                ),
                vol.Required(
                    CONF_ARC,
                    default=defaults.get(CONF_ARC, DEFAULT_ARC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=120,
                        step=5,
                        unit_of_measurement="°",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        ),
        {"collapsed": True},
    )

    thresholds_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Required(
                    CONF_MIN_ELEVATION,
                    default=defaults.get(CONF_MIN_ELEVATION, DEFAULT_MIN_ELEVATION),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=60,
                        step=1,
                        unit_of_measurement="°",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_UV,
                    default=defaults.get(CONF_MIN_UV, DEFAULT_MIN_UV),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=11,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_TARGET_POSITION,
                    default=defaults.get(CONF_TARGET_POSITION, DEFAULT_TARGET_POSITION),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        step=5,
                        unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        ),
        {"collapsed": True},
    )

    room_sensor_section = data_entry_flow.section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_TEMP_INDOOR_ENTITY,
                    description={
                        "suggested_value": defaults.get(
                            CONF_TEMP_INDOOR_ENTITY, DEFAULT_TEMP_INDOOR_ENTITY
                        )
                        or None
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        ),
        {"collapsed": True},
    )

    notifications_section = _build_notifications_section(defaults)
    voice_announcement_section = _build_voice_announcement_section(defaults)

    return vol.Schema(
        {
            vol.Required(
                CONF_NAME,
                default=defaults.get(CONF_NAME, ""),
            ): selector.TextSelector(selector.TextSelectorConfig()),
            vol.Required(SECTION_COVERS): sun_covers_section,
            vol.Required(SECTION_ORIENTATION): orientation_section,
            vol.Required(SECTION_THRESHOLDS): thresholds_section,
            vol.Required(SECTION_ROOM_SENSOR): room_sensor_section,
            vol.Required(SECTION_NOTIFICATIONS): notifications_section,
            vol.Required(SECTION_VOICE_ANNOUNCEMENT): voice_announcement_section,
        }
    )


def _normalize_sun_protection(user_input: dict[str, Any]) -> dict[str, Any]:
    """Cast types and convert cardinal string to degree integer."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in (
            SECTION_COVERS,
            SECTION_ORIENTATION,
            SECTION_THRESHOLDS,
            SECTION_ROOM_SENSOR,
            SECTION_NOTIFICATIONS,
            SECTION_VOICE_ANNOUNCEMENT,
        ) and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    flat.setdefault(CONF_NOTIFY_MODE, DEFAULT_NOTIFY_MODE)
    flat.setdefault(CONF_TTS_MODE, DEFAULT_TTS_MODE)
    orientation_str = flat.get(CONF_ORIENTATION, "S")
    flat[CONF_ORIENTATION] = ORIENTATION_CARDINALS.get(
        orientation_str, DEFAULT_ORIENTATION
    )
    for key in (CONF_ARC, CONF_MIN_ELEVATION, CONF_MIN_UV, CONF_TARGET_POSITION):
        if key in flat:
            flat[key] = int(flat[key])
    return flat


class ShuttersSunProtectionSubentryFlow(ConfigSubentryFlow):
    """Create or edit a *sun_protection* subentry (one orientation group)."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_handle(user_input, edit_subentry_id=None)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_handle(
            user_input, edit_subentry_id=self._reconfigure_subentry_id
        )

    async def _async_handle(
        self,
        user_input: dict[str, Any] | None,
        *,
        edit_subentry_id: str | None,
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_entry()

        if user_input is not None:
            data = _normalize_sun_protection(user_input)
            name = (data.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif not data.get(CONF_COVERS):
                errors[CONF_COVERS] = "no_covers"
            else:
                data[CONF_NAME] = name
                payload = _strip_name(data)
                unique_id = slugify(name)
                normalized_title = name.casefold()

                for sub_id, existing in entry.subentries.items():
                    if sub_id == edit_subentry_id:
                        continue
                    if existing.unique_id == unique_id:
                        return self.async_abort(reason="already_configured")
                    if existing.title.casefold() == normalized_title:
                        return self.async_abort(reason="already_configured")

                if edit_subentry_id is not None:
                    subentry = entry.subentries[edit_subentry_id]
                    return self.async_update_and_abort(
                        entry, subentry, title=name, data=payload
                    )
                return self.async_create_entry(
                    title=name, data=payload, unique_id=unique_id
                )

        if edit_subentry_id is not None:
            subentry = entry.subentries[edit_subentry_id]
            defaults = {**subentry.data, CONF_NAME: subentry.title}
        else:
            defaults = {}

        step_id = "reconfigure" if edit_subentry_id is not None else "user"
        return self.async_show_form(
            step_id=step_id,
            data_schema=_build_sun_protection_schema(defaults),
            errors=errors,
        )
