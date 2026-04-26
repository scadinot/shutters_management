"""Config flow for Shutters Management."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_CLOSE_TIME,
    CONF_COVERS,
    CONF_DAYS,
    CONF_ONLY_WHEN_AWAY,
    CONF_OPEN_TIME,
    CONF_PRESENCE_ENTITY,
    CONF_RANDOMIZE,
    CONF_RANDOM_MAX_MINUTES,
    DAYS,
    DEFAULT_CLOSE_TIME,
    DEFAULT_DAYS,
    DEFAULT_ONLY_WHEN_AWAY,
    DEFAULT_OPEN_TIME,
    DEFAULT_RANDOMIZE,
    DEFAULT_RANDOM_MAX_MINUTES,
    DOMAIN,
)


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the form schema, prefilled with defaults."""
    return vol.Schema(
        {
            vol.Required(
                CONF_COVERS,
                default=defaults.get(CONF_COVERS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover", multiple=True)
            ),
            vol.Required(
                CONF_OPEN_TIME,
                default=defaults.get(CONF_OPEN_TIME, DEFAULT_OPEN_TIME),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_CLOSE_TIME,
                default=defaults.get(CONF_CLOSE_TIME, DEFAULT_CLOSE_TIME),
            ): selector.TimeSelector(),
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


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize user input (cast types, drop empties)."""
    data = dict(user_input)
    if CONF_RANDOM_MAX_MINUTES in data:
        data[CONF_RANDOM_MAX_MINUTES] = int(data[CONF_RANDOM_MAX_MINUTES])
    if not data.get(CONF_PRESENCE_ENTITY):
        data.pop(CONF_PRESENCE_ENTITY, None)
    return data


def _needs_presence_warning(hass, data: dict[str, Any]) -> bool:
    """Return True when only_when_away has no presence source available."""
    if not data.get(CONF_ONLY_WHEN_AWAY):
        return False
    if data.get(CONF_PRESENCE_ENTITY):
        return False
    return not hass.states.async_all("person")


class ShuttersManagementConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial UI configuration."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._pending_data: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step user form."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _normalize(user_input)
            if not data.get(CONF_COVERS):
                errors[CONF_COVERS] = "no_covers"
            elif not data.get(CONF_DAYS):
                errors[CONF_DAYS] = "no_days"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                if _needs_presence_warning(self.hass, data):
                    self._pending_data = data
                    return await self.async_step_confirm_no_presence()
                return self.async_create_entry(
                    title="Shutters Management", data=data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}),
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
            return self.async_create_entry(title="Shutters Management", data=data)

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
        """Top-level menu: configure or trigger an immediate action."""
        scheduler = self._get_scheduler()
        toggle_option = (
            "resume_simulation" if (scheduler and scheduler.paused) else "pause_simulation"
        )
        return self.async_show_menu(
            step_id="init",
            menu_options=["configure", "run_open", "run_close", toggle_option],
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the saved configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _normalize(user_input)
            if not data.get(CONF_COVERS):
                errors[CONF_COVERS] = "no_covers"
            elif not data.get(CONF_DAYS):
                errors[CONF_DAYS] = "no_days"
            else:
                if _needs_presence_warning(self.hass, data):
                    self._pending_data = data
                    return await self.async_step_confirm_no_presence()
                return self.async_create_entry(title="", data=data)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="configure",
            data_schema=_build_schema(defaults),
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
            return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="confirm_no_presence",
            data_schema=vol.Schema({}),
        )

    async def async_step_run_open(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Trigger an immediate opening."""
        scheduler = self._get_scheduler()
        if scheduler is not None:
            await scheduler.async_run_now(ACTION_OPEN)
        return self.async_abort(reason="action_run")

    async def async_step_run_close(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Trigger an immediate closing."""
        scheduler = self._get_scheduler()
        if scheduler is not None:
            await scheduler.async_run_now(ACTION_CLOSE)
        return self.async_abort(reason="action_run")

    async def async_step_pause_simulation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pause the simulation."""
        scheduler = self._get_scheduler()
        if scheduler is not None:
            await scheduler.async_set_paused(True)
        return self.async_abort(reason="simulation_paused")

    async def async_step_resume_simulation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Resume the simulation."""
        scheduler = self._get_scheduler()
        if scheduler is not None:
            await scheduler.async_set_paused(False)
        return self.async_abort(reason="simulation_resumed")

    def _get_scheduler(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
