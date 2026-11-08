"""Services de l'intégration : run_now, pause et resume.

Extrait d'``__init__.py`` sans modification. Les trois services agissent sur
tous les planificateurs du hub ; leurs gestionnaires relisent
``hass.data[DOMAIN]`` à chaque appel plutôt que de capturer une liste à
l'enregistrement, afin qu'un rechargement de l'entrée ne les laisse pas piloter
des instances remplacées.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    callback,
)

from .scheduler import ShuttersScheduler
from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    ATTR_ACTION,
    DOMAIN,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SERVICE_RUN_NOW,
)
_LOGGER = logging.getLogger(__name__)


RUN_NOW_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ACTION): vol.In([ACTION_OPEN, ACTION_CLOSE])}
)


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_RUN_NOW):
        return

    def _schedulers() -> list[ShuttersScheduler]:
        return [
            m
            for m in hass.data.get(DOMAIN, {}).values()
            if isinstance(m, ShuttersScheduler)
        ]

    async def _handle_run_now(call: ServiceCall) -> None:
        action = call.data[ATTR_ACTION]
        for scheduler in _schedulers():
            await scheduler.async_run_now(action)

    async def _handle_pause(call: ServiceCall) -> None:
        for scheduler in _schedulers():
            await scheduler.async_set_paused(True)

    async def _handle_resume(call: ServiceCall) -> None:
        for scheduler in _schedulers():
            await scheduler.async_set_paused(False)

    hass.services.async_register(
        DOMAIN, SERVICE_RUN_NOW, _handle_run_now, schema=RUN_NOW_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_PAUSE, _handle_pause)
    hass.services.async_register(DOMAIN, SERVICE_RESUME, _handle_resume)


@callback
def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration-level services."""
    for service in (SERVICE_RUN_NOW, SERVICE_PAUSE, SERVICE_RESUME):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
