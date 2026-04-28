"""Config flow for Shutters Management."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, selector
from homeassistant.util import slugify

from .const import (
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
    DAYS,
    DEFAULT_CLOSE_MODE,
    DEFAULT_CLOSE_OFFSET,
    DEFAULT_CLOSE_TIME,
    DEFAULT_DAYS,
    DEFAULT_ONLY_WHEN_AWAY,
    DEFAULT_OPEN_MODE,
    DEFAULT_OPEN_OFFSET,
    DEFAULT_OPEN_TIME,
    DEFAULT_RANDOMIZE,
    DEFAULT_RANDOM_MAX_MINUTES,
    DOMAIN,
    OFFSET_MAX_MINUTES,
    OFFSET_MIN_MINUTES,
    TRIGGER_MODES,
)

SECTION_OPEN = "open"
SECTION_CLOSE = "close"


def _build_schema(
    defaults: dict[str, Any], *, include_name: bool = True
) -> vol.Schema:
    """Build the single-panel schema with two trigger sections."""
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
        {"collapsed": False},
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
        {"collapsed": False},
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
                    mode=selector.SelectSelectorMode.LIST,
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
    """Drop CONF_NAME from a payload destined for entry.options.

    The instance name lives in entry.data (and entry.title); keeping it
    out of entry.options avoids a stale duplicate after a rename.
    """
    return {k: v for k, v in data.items() if k != CONF_NAME}


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize user input: flatten section sub-dicts, cast types, drop empties."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            # data_entry_flow.section returns its inner schema as a sub-dict;
            # flatten it so the rest of the integration sees a flat payload.
            flat.update(value)
        else:
            flat[key] = value
    if CONF_RANDOM_MAX_MINUTES in flat:
        flat[CONF_RANDOM_MAX_MINUTES] = int(flat[CONF_RANDOM_MAX_MINUTES])
    if not flat.get(CONF_PRESENCE_ENTITY):
        flat.pop(CONF_PRESENCE_ENTITY, None)
    return flat


def _needs_presence_warning(hass: HomeAssistant, data: dict[str, Any]) -> bool:
    """Return True when only_when_away has no presence source available."""
    if not data.get(CONF_ONLY_WHEN_AWAY):
        return False
    if data.get(CONF_PRESENCE_ENTITY):
        return False
    return not hass.states.async_all("person")


class ShuttersManagementConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial UI configuration."""

    VERSION = 2

    def __init__(self) -> None:
        super().__init__()
        self._pending_data: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step user form with sectioned trigger groups."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _normalize(user_input)
            name = (data.get(CONF_NAME) or "").strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            elif not data.get(CONF_COVERS):
                errors[CONF_COVERS] = "no_covers"
            elif not data.get(CONF_DAYS):
                errors[CONF_DAYS] = "no_days"
            else:
                data[CONF_NAME] = name
                await self.async_set_unique_id(slugify(name))
                self._abort_if_unique_id_configured()
                if _needs_presence_warning(self.hass, data):
                    self._pending_data = data
                    return await self.async_step_confirm_no_presence()
                return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(_normalize(user_input or {})),
            errors=errors,
        )

    async def async_step_confirm_no_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm save when only_when_away has no presence source."""
        if user_input is not None:
            assert self._pending_data is not None
            data = self._pending_data
            self._pending_data = None
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="confirm_no_presence",
            data_schema=vol.Schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return ShuttersManagementOptionsFlow()


class ShuttersManagementOptionsFlow(OptionsFlow):
    """Allow editing the integration after creation."""

    def __init__(self) -> None:
        super().__init__()
        self._pending_data: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step options form with sectioned trigger groups."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _normalize(user_input)
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
                    return await self.async_step_confirm_no_presence()
                self._sync_name(name)
                return self.async_create_entry(title="", data=_strip_name(data))

        defaults = {
            **self.config_entry.data,
            **self.config_entry.options,
            CONF_NAME: self.config_entry.title,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(defaults),
            errors=errors,
        )

    def _sync_name(self, name: str) -> None:
        """Keep the instance name authoritative across data, title and device.

        Stored in entry.data[CONF_NAME] (single source of truth), mirrored
        on entry.title (what HA shows in the integrations list) and on the
        device.name (what the device card displays). entry.options never
        carries CONF_NAME; this avoids data/options/title drift after a
        rename. The unique_id (built from the original name's slug at
        creation) is left untouched intentionally — HA does not allow
        unique_id changes after creation.
        """
        current_data_name = self.config_entry.data.get(CONF_NAME)
        if (
            name == self.config_entry.title
            and current_data_name == name
        ):
            return
        new_data = {**self.config_entry.data, CONF_NAME: name}
        self.hass.config_entries.async_update_entry(
            self.config_entry, title=name, data=new_data
        )
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self.config_entry.entry_id)}
        )
        if device is not None:
            device_registry.async_update_device(device.id, name=name)

    async def async_step_confirm_no_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm save when only_when_away has no presence source."""
        if user_input is not None:
            assert self._pending_data is not None
            data = self._pending_data
            self._pending_data = None
            self._sync_name(data[CONF_NAME])
            return self.async_create_entry(title="", data=_strip_name(data))

        return self.async_show_form(
            step_id="confirm_no_presence",
            data_schema=vol.Schema({}),
        )
