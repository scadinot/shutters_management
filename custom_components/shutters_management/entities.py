"""Shared entity helpers for the Shutters Management integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import slugify


def _build_suggested_object_id(
    entry: ConfigEntry | None, translation_key: str
) -> str | None:
    """Force a stable, language-agnostic object_id for new entities.

    Without this, HA derives the object_id from the translated entity name
    in the language active at creation time, which produces identifiers
    like ``button.bureau_tester_l_ouverture`` when HA is in French even
    though the translation_key is the English ``test_open``.

    The per-instance prefix is taken from ``entry.unique_id`` (already a
    slug, set once at config flow time and never modified), with a
    fallback to ``slugify(entry.title)`` for legacy entries that may not
    have a unique_id yet. This keeps the prefix stable even if the user
    later renames the config entry through the UI.
    """

    if entry is None:
        return None

    prefix = entry.unique_id if entry.unique_id else slugify(entry.title)
    return f"{prefix}_{translation_key}"
