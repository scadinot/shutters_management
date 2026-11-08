"""Tests for the static frontend resources of the custom Lovelace card.

`_async_register_frontend_resources` had no test before the `__init__.py` split,
although it is the only thing standing between a reload and the 3D card's
module being injected twice into every Home Assistant page. Removing a static
path or an extra JS module requires a restart, so a double registration cannot
be undone at runtime.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.shutters_management.frontend import (
    _CARD_URL,
    _FRONTEND_REGISTERED_FLAG,
    _async_register_frontend_resources,
)


async def test_frontend_resources_are_registered_once(
    hass: HomeAssistant,
) -> None:
    """A second call must return on the flag without registering again."""
    with patch(
        "homeassistant.components.frontend.add_extra_js_url"
    ) as add_js, patch.object(
        hass.http, "async_register_static_paths", AsyncMock()
    ) as static_paths:
        await _async_register_frontend_resources(hass)
        assert hass.data[_FRONTEND_REGISTERED_FLAG] is True

        await _async_register_frontend_resources(hass)

    static_paths.assert_awaited_once()
    add_js.assert_called_once()
    assert add_js.call_args.args[1] == _CARD_URL
