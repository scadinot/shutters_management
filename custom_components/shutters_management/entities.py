"""Shared entity helpers for the Shutters Management integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import slugify


def _build_entity_id(
    platform: str,
    entry: ConfigEntry | None,
    translation_key: str,
) -> str | None:
    """Build a stable, language-agnostic entity_id.

    Without this, HA derives the object_id from the translated entity
    name in the language active at creation time, producing
    identifiers like ``button.bureau_tester_l_ouverture`` when HA is
    in French even though the translation_key is the English
    ``test_open``.

    Setting ``self.entity_id`` directly in ``__init__`` is the
    contract documented by ``entity_platform.py:823-845``: HA captures
    the value into ``internal_integration_suggested_object_id`` and
    sends it to the registry without re-prefixing nor re-translating
    it. ``_attr_suggested_object_id`` is *not* honored — that
    attribute is only consulted via the ``Entity.suggested_object_id``
    property which returns the translated name.

    The per-instance prefix uses ``entry.unique_id`` (already a slug,
    set once at config flow time and never modified) with a fallback
    to ``slugify(entry.title)`` for legacy entries that may not have
    a unique_id yet. When ``unique_id`` is set, the prefix stays
    rename-proof. When the helper falls back to the slugified title,
    a later rename of the entry *would* shift this computed value;
    in practice that does not affect already-registered entities,
    because HA stores the chosen ``entity_id`` in the registry at
    creation time and does not recompute it on subsequent reloads.
    """

    if entry is None:
        return None

    prefix = entry.unique_id if entry.unique_id else slugify(entry.title)
    return f"{platform}.{prefix}_{translation_key}"
