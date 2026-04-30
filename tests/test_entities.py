"""Tests for shutters_management entity helpers."""
from unittest.mock import MagicMock

import pytest

from custom_components.shutters_management.entities import _build_entity_id


class TestBuildEntityId:
    """Coverage for the language-agnostic entity_id helper."""

    def test_returns_none_when_entry_is_none(self):
        """Without a ConfigEntry there is nothing to anchor a prefix on."""

        assert _build_entity_id("sensor", None, "next_open") is None

    def test_uses_entry_unique_id_when_set(self):
        """unique_id is the stable slug computed at config flow time."""

        entry = MagicMock(unique_id="bureau", title="Bureau")

        result = _build_entity_id("sensor", entry, "next_open")

        assert result == "sensor.bureau_next_open"

    def test_unique_id_remains_after_title_rename(self):
        """Renaming the entry must not shift the prefix used for new entities."""

        entry = MagicMock(unique_id="bureau", title="Renamed By User")

        result = _build_entity_id("button", entry, "test_close")

        assert result == "button.bureau_test_close"

    @pytest.mark.parametrize("falsy", [None, ""])
    def test_falls_back_to_slugified_title_when_no_unique_id(self, falsy):
        """Legacy entries without a unique_id fall back to the title slug."""

        entry = MagicMock(unique_id=falsy, title="Mon Bureau")

        result = _build_entity_id("switch", entry, "simulation_active")

        assert result == "switch.mon_bureau_simulation_active"

    def test_platform_prefix_is_respected(self):
        """The platform argument drives the final domain of the entity_id."""

        entry = MagicMock(unique_id="bureau", title="Bureau")

        assert (
            _build_entity_id("sensor", entry, "next_open")
            == "sensor.bureau_next_open"
        )
        assert (
            _build_entity_id("button", entry, "test_open")
            == "button.bureau_test_open"
        )
        assert (
            _build_entity_id("switch", entry, "simulation_active")
            == "switch.bureau_simulation_active"
        )
