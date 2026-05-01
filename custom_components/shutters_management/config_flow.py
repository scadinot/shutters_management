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
    CONF_CLOSE_MODE,
    CONF_CLOSE_OFFSET,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_WHEN_AWAY_ONLY,
    CONF_ONLY_WHEN_AWAY,
    CONF_SEQUENTIAL_COVERS,
    CONF_TTS_ENGINE,
    CONF_TTS_TARGETS,
    CONF_TTS_WHEN_AWAY_ONLY,
    CONF_OPEN_MODE,
    CONF_OPEN_OFFSET,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    CONF_TYPE,
    DAYS,
    DEFAULT_CLOSE_MODE,
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_CLOSE_TIME,
    DEFAULT_DAYS,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_NOTIFY_WHEN_AWAY_ONLY,
    DEFAULT_ONLY_WHEN_AWAY,
    DEFAULT_SEQUENTIAL_COVERS,
    DEFAULT_TTS_TARGETS,
    DEFAULT_TTS_WHEN_AWAY_ONLY,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DEFAULT_OPEN_TIME,
    DEFAULT_RANDOMIZE,
    DEFAULT_RANDOM_MAX_MINUTES,
    DOMAIN,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    OFFSET_MAX_MINUTES,
    OFFSET_MIN_MINUTES,
    SUBENTRY_TYPE_INSTANCE,
    TRIGGER_MODES,
    TYPE_HUB,
)

SECTION_OPEN = "open"
SECTION_CLOSE = "close"


def _available_notify_services(hass: HomeAssistant | None) -> list[str]:
    """Return ``notify.<svc>`` strings discovered on this hass instance."""
    if hass is None:
        return []
    notify_services = hass.services.async_services().get("notify", {})
    return sorted(f"notify.{name}" for name in notify_services)


def _build_hub_schema(
    hass: HomeAssistant | None, defaults: dict[str, Any]
) -> vol.Schema:
    """Schema for the hub: shared notification settings only."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_NOTIFY_SERVICES,
                default=defaults.get(
                    CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_available_notify_services(hass),
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_NOTIFY_WHEN_AWAY_ONLY,
                default=defaults.get(
                    CONF_NOTIFY_WHEN_AWAY_ONLY, DEFAULT_NOTIFY_WHEN_AWAY_ONLY
                ),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SEQUENTIAL_COVERS,
                default=defaults.get(
                    CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_TTS_ENGINE,
                description={
                    "suggested_value": defaults.get(CONF_TTS_ENGINE, "")
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="tts")
            ),
            vol.Optional(
                CONF_TTS_TARGETS,
                default=defaults.get(CONF_TTS_TARGETS, DEFAULT_TTS_TARGETS),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player", multiple=True
                )
            ),
            vol.Required(
                CONF_TTS_WHEN_AWAY_ONLY,
                default=defaults.get(
                    CONF_TTS_WHEN_AWAY_ONLY, DEFAULT_TTS_WHEN_AWAY_ONLY
                ),
            ): selector.BooleanSelector(),
        }
    )


def _build_instance_schema(
    defaults: dict[str, Any], *, include_name: bool = True
) -> vol.Schema:
    """Schema for an instance subentry: scheduling + presence config."""
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

    fields: dict[Any, Any] = {}
    if include_name:
        fields[
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, ""))
        ] = selector.TextSelector(selector.TextSelectorConfig())
    fields.update(
        {
            vol.Required(
                CONF_COVERS,
                default=defaults.get(CONF_COVERS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover", multiple=True)
            ),
            vol.Required(SECTION_OPEN): open_section,
            vol.Required(SECTION_CLOSE): close_section,
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
            vol.Required(
                CONF_ONLY_WHEN_AWAY,
                default=defaults.get(CONF_ONLY_WHEN_AWAY, DEFAULT_ONLY_WHEN_AWAY),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_PRESENCE_ENTITY,
                description={
                    "suggested_value": defaults.get(CONF_PRESENCE_ENTITY, "")
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["person", "group"])
            ),
        }
    )
    return vol.Schema(fields)


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
        if key in (SECTION_OPEN, SECTION_CLOSE) and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    if CONF_RANDOM_MAX_MINUTES in flat:
        flat[CONF_RANDOM_MAX_MINUTES] = int(flat[CONF_RANDOM_MAX_MINUTES])
    if not flat.get(CONF_PRESENCE_ENTITY):
        flat.pop(CONF_PRESENCE_ENTITY, None)
    return flat


def _normalize_hub(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize hub user input.

    ``notify_services`` is a multi-select but the selector with
    ``custom_value=True`` may, in edge cases, deliver a single string
    rather than a list. Wrap that case explicitly to avoid the silent
    bug where ``list("notify.iphone")`` would expand to a list of
    characters.
    """
    flat = dict(user_input)
    services = flat.get(CONF_NOTIFY_SERVICES)
    if not services:
        flat[CONF_NOTIFY_SERVICES] = []
    elif isinstance(services, str):
        flat[CONF_NOTIFY_SERVICES] = [services]
    else:
        flat[CONF_NOTIFY_SERVICES] = list(services)
    flat.setdefault(CONF_NOTIFY_WHEN_AWAY_ONLY, DEFAULT_NOTIFY_WHEN_AWAY_ONLY)
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
    flat.setdefault(CONF_TTS_WHEN_AWAY_ONLY, DEFAULT_TTS_WHEN_AWAY_ONLY)
    return flat


def _needs_presence_warning(hass: HomeAssistant, data: dict[str, Any]) -> bool:
    """Return True when only_when_away has no presence source available."""
    if not data.get(CONF_ONLY_WHEN_AWAY):
        return False
    if data.get(CONF_PRESENCE_ENTITY):
        return False
    return not hass.states.async_all("person")


class ShuttersManagementConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for the *hub* entry (singleton).

    Each Shutters Management installation has exactly one hub entry that
    holds the shared notification settings. Individual schedules
    (Bureau, RDC, ...) are added as subentries via
    :class:`ShuttersInstanceSubentryFlow`.
    """

    VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the hub. Only one hub may exist (singleton)."""
        await self.async_set_unique_id(HUB_UNIQUE_ID)
        self._abort_if_unique_id_configured()

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
        return {SUBENTRY_TYPE_INSTANCE: ShuttersInstanceSubentryFlow}

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
            CONF_NOTIFY_WHEN_AWAY_ONLY: self.config_entry.data.get(
                CONF_NOTIFY_WHEN_AWAY_ONLY, DEFAULT_NOTIFY_WHEN_AWAY_ONLY
            ),
            CONF_SEQUENTIAL_COVERS: self.config_entry.data.get(
                CONF_SEQUENTIAL_COVERS, DEFAULT_SEQUENTIAL_COVERS
            ),
            CONF_TTS_ENGINE: self.config_entry.data.get(CONF_TTS_ENGINE) or "",
            CONF_TTS_TARGETS: self.config_entry.data.get(
                CONF_TTS_TARGETS, DEFAULT_TTS_TARGETS
            ),
            CONF_TTS_WHEN_AWAY_ONLY: self.config_entry.data.get(
                CONF_TTS_WHEN_AWAY_ONLY, DEFAULT_TTS_WHEN_AWAY_ONLY
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_build_hub_schema(self.hass, defaults),
        )


class ShuttersInstanceSubentryFlow(ConfigSubentryFlow):
    """Create or edit an *instance* subentry (one shutter schedule)."""

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
                if _needs_presence_warning(self.hass, data):
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
            data_schema=_build_instance_schema(defaults),
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
