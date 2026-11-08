"""Notifications push et annonces vocales pour une action sur les volets.

Extrait d'``__init__.py`` sans modification. ``_async_dispatch_notifications``
est le point d'entrée unique : il consulte les modes de la sous-entrée et
l'état de présence du foyer, puis alimente indépendamment les deux canaux —
l'échec de l'un ne fait jamais taire l'autre.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from .const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_SERVICES,
    CONF_TTS_ENGINE,
    CONF_TTS_MODE,
    CONF_TTS_TARGETS,
    DEFAULT_NOTIFY_MODE,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_TTS_MODE,
    DEFAULT_TTS_TARGETS,
    MODE_AWAY_ONLY,
    MODE_DISABLED,
    MODE_HOME_ONLY,
)
from .presence import _is_away_for

_LOGGER = logging.getLogger(__name__)


_NOTIFY_HEADERS: dict[str, dict[str, str]] = {
    "fr": {
        ACTION_OPEN: "Volets ouverts :",
        ACTION_CLOSE: "Volets fermés :",
    },
    "en": {
        ACTION_OPEN: "Shutters opened:",
        ACTION_CLOSE: "Shutters closed:",
    },
}


_TTS_HEADERS: dict[str, dict[str, str]] = {
    "fr": {
        # French typography: space before the colon.
        ACTION_OPEN: "Volets ouverts : ",
        ACTION_CLOSE: "Volets fermés : ",
    },
    "en": {
        ACTION_OPEN: "Shutters opened: ",
        ACTION_CLOSE: "Shutters closed: ",
    },
}


def _cover_display_name(hass: HomeAssistant, entity_id: str) -> str:
    """Friendly_name for ``entity_id`` when known, raw entity_id otherwise."""
    state = hass.states.get(entity_id)
    if state is None:
        return entity_id
    return state.attributes.get("friendly_name") or entity_id


def _notify_message(
    hass: HomeAssistant, language: str, action: str, processed_covers: list[str]
) -> str:
    """Build the localized notification body.

    The body lists each cover in **processing order** — i.e. the order
    in which the scheduler actually fired ``cover.<service>`` (the
    shuffled order in sequential mode, the configuration order in
    batched mode). Each cover is rendered using its ``friendly_name``
    when available, with the ``entity_id`` as a fallback.
    """
    bucket = _NOTIFY_HEADERS.get(language, _NOTIFY_HEADERS["en"])
    header = bucket.get(action, _NOTIFY_HEADERS["en"][action])
    lines = [header]
    for entity_id in processed_covers:
        lines.append(_cover_display_name(hass, entity_id))
    return "\n".join(lines)


def _tts_message(
    hass: HomeAssistant, language: str, action: str, processed_covers: list[str]
) -> str:
    """Build the spoken-announcement body for ``tts.speak``.

    Same content as ``_notify_message`` but joined with commas instead
    of newlines, so a smart speaker reads a natural sentence rather
    than a string of awkward pauses on each line break:
    ``"Shutters opened: Living Room, Kitchen, Bedroom."``. The header
    already carries its own ``: `` (or `` : `` in French) so the join
    is unconditional.
    """
    bucket = _TTS_HEADERS.get(language, _TTS_HEADERS["en"])
    header = bucket.get(action, _TTS_HEADERS["en"][action])
    names = [_cover_display_name(hass, entity_id) for entity_id in processed_covers]
    return f"{header}{', '.join(names)}."


async def _async_dispatch_notifications(
    hass: HomeAssistant,
    hub_entry: ConfigEntry,
    subentry: ConfigSubentry,
    action: str,
    processed_covers: list[str],
) -> None:
    """Dispatch a cover action to push + TTS channels.

    Channels (notify services, TTS engine, speakers) and the presence
    entity live on the hub. Each subentry carries its own ``notify_mode``
    and ``tts_mode``: callers don't need to gate themselves — this
    helper consults both modes and short-circuits when the relevant
    channel is disabled or out of scope (e.g. ``home_only`` while away).

    Push and TTS are independent branches; a failure in one never
    silences the other.
    """
    hub_data = hub_entry.data
    sub_data = subentry.data
    is_away = _is_away_for(hass, hub_data)
    language = hass.config.language

    await _async_send_push(
        hass, hub_data, sub_data, subentry, action, language, is_away,
        processed_covers,
    )
    await _async_send_tts(
        hass, hub_data, sub_data, action, language, is_away,
        processed_covers,
    )


async def _async_send_push(
    hass: HomeAssistant,
    hub_data: Mapping[str, Any],
    sub_data: Mapping[str, Any],
    subentry: ConfigSubentry,
    action: str,
    language: str,
    is_away: bool,
    processed_covers: list[str],
) -> None:
    """Send a push notification through every configured ``notify.*`` service."""
    notify_mode = sub_data.get(CONF_NOTIFY_MODE, DEFAULT_NOTIFY_MODE)
    if notify_mode == MODE_DISABLED:
        return
    if notify_mode == MODE_AWAY_ONLY and not is_away:
        return
    targets: list[str] = list(
        hub_data.get(CONF_NOTIFY_SERVICES, DEFAULT_NOTIFY_SERVICES)
    )
    if not targets:
        return

    title = subentry.title
    message = _notify_message(hass, language, action, processed_covers)

    for target in targets:
        if "." not in target:
            _LOGGER.warning("Invalid notify target: %s", target)
            continue
        domain, service_name = target.split(".", 1)
        if domain != "notify":
            _LOGGER.warning(
                "Notify target not in notify domain: %s", target
            )
            continue
        try:
            await hass.services.async_call(
                "notify",
                service_name,
                {"title": title, "message": message},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 — never break the cover action
            _LOGGER.exception(
                "Failed to send notification via %s", target
            )


async def _async_send_tts(
    hass: HomeAssistant,
    hub_data: Mapping[str, Any],
    sub_data: Mapping[str, Any],
    action: str,
    language: str,
    is_away: bool,
    processed_covers: list[str],
) -> None:
    """Speak the action on every configured ``media_player.*`` via ``tts.speak``."""
    tts_mode = sub_data.get(CONF_TTS_MODE, DEFAULT_TTS_MODE)
    if tts_mode == MODE_DISABLED:
        return
    if tts_mode == MODE_HOME_ONLY and is_away:
        return
    engine = hub_data.get(CONF_TTS_ENGINE)
    targets: list[str] = list(
        hub_data.get(CONF_TTS_TARGETS, DEFAULT_TTS_TARGETS)
    )
    if not engine or not targets:
        return

    message = _tts_message(hass, language, action, processed_covers)
    try:
        await hass.services.async_call(
            "tts",
            "speak",
            {
                "entity_id": engine,
                "media_player_entity_id": targets,
                "message": message,
            },
            blocking=False,
        )
    except Exception:  # noqa: BLE001 — never break the cover action
        _LOGGER.exception(
            "Failed to broadcast TTS announcement via %s", engine
        )
