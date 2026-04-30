"""Tests for shutters_management entity helpers."""
from unittest.mock import MagicMock

import pytest

from custom_components.shutters_management.entities import (
    _build_suggested_object_id,
)


class TestBuildSuggestedObjectId:
    """Coverage for the language-agnostic object_id helper."""

    def test_returns_none_when_entry_is_none(self):
        """Without a ConfigEntry there is nothing to anchor a prefix on."""

        assert _build_suggested_object_id(None, "next_open") is None

    def test_uses_entry_unique_id_when_set(self):
        """unique_id is the stable slug computed at config flow time."""

        entry = MagicMock(unique_id="bureau", title="Bureau")

        result = _build_suggested_object_id(entry, "next_open")

        assert result == "bureau_next_open"

    def test_unique_id_remains_after_title_rename(self):
        """Renaming the entry must not shift the prefix used for new entities."""

        entry = MagicMock(unique_id="bureau", title="Renamed By User")

        result = _build_suggested_object_id(entry, "test_close")

        assert result == "bureau_test_close"

    @pytest.mark.parametrize("falsy", [None, ""])
    def test_falls_back_to_slugified_title_when_no_unique_id(self, falsy):
        """Legacy entries without a unique_id fall back to the title slug."""

        entry = MagicMock(unique_id=falsy, title="Mon Bureau")

        result = _build_suggested_object_id(entry, "simulation_active")

        assert result == "mon_bureau_simulation_active"
