"""Shared entity helpers for the Shutters Management integration."""
from __future__ import annotations

from typing import Protocol

from homeassistant.util import slugify


class _Slugifiable(Protocol):
    """Anything that exposes ``unique_id`` and ``title`` (ConfigEntry / ConfigSubentry)."""

    unique_id: str | None
    title: str


def _build_entity_id(
    platform: str,
    source: _Slugifiable | None,
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

    The per-instance prefix uses ``source.unique_id`` (already a slug,
    set once at config flow / subentry creation time and never modified)
    with a fallback to ``slugify(source.title)`` for legacy entries
    that may not have a unique_id yet.
    """

    if source is None:
        return None

    prefix = source.unique_id if source.unique_id else slugify(source.title)
    return f"{platform}.{prefix}_{translation_key}"
