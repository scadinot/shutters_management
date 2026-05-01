"""Tests for the v0.4.1 sequential / random-order cover mode."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import SERVICE_CLOSE_COVER, SERVICE_OPEN_COVER
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.shutters_management.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    CONF_COVERS,
    CONF_SEQUENTIAL_COVERS,
    DOMAIN,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


COVERS = ["cover.bureau_left", "cover.bureau_right", "cover.bureau_back"]


async def _setup(
    hass: HomeAssistant,
    base_config: dict,
    *,
    sequential: bool,
    covers: list[str] | None = None,
):
    """Build a hub with sequential_covers set, return its only scheduler."""
    base_config[CONF_COVERS] = covers if covers is not None else list(COVERS)
    entry = build_hub_with_instance(
        instance_data=base_config,
        hub_data={CONF_SEQUENTIAL_COVERS: sequential},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][get_only_subentry_id(entry)]


def _set_all(hass: HomeAssistant, covers: list[str], state: str) -> None:
    for c in covers:
        hass.states.async_set(c, state)


async def test_default_mode_keeps_batched_call(
    hass: HomeAssistant, base_config
) -> None:
    """With sequential_covers OFF, the integration keeps the batched call.

    This locks in backwards-compatible behavior for users who upgrade
    from v0.4.0 and never touch the new toggle.
    """
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    scheduler = await _setup(hass, base_config, sequential=False)

    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == COVERS


async def test_sequential_mode_one_call_per_cover(
    hass: HomeAssistant, base_config
) -> None:
    """With sequential_covers ON, each cover gets its own service call."""
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    _set_all(hass, COVERS, "open")  # already at target → no waiting needed

    scheduler = await _setup(hass, base_config, sequential=True)
    await scheduler.async_run_now(ACTION_OPEN)
    await hass.async_block_till_done()

    assert len(calls) == len(COVERS)
    targeted = [call.data["entity_id"] for call in calls]
    assert sorted(targeted) == sorted(COVERS)
    # Each call must target exactly one cover, not the full list.
    for entity_id in targeted:
        assert isinstance(entity_id, str)


async def test_sequential_mode_uses_random_shuffle(
    hass: HomeAssistant, base_config
) -> None:
    """The cover list is shuffled before being walked through.

    We patch ``random.shuffle`` to a deterministic permutation so the
    test stays repeatable but still proves the call site is wired up.
    """
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    _set_all(hass, COVERS, "open")

    def _reverse(seq):
        seq.reverse()

    scheduler = await _setup(hass, base_config, sequential=True)
    with patch(
        "custom_components.shutters_management.random.shuffle",
        side_effect=_reverse,
    ) as mock_shuffle:
        await scheduler.async_run_now(ACTION_OPEN)
        await hass.async_block_till_done()

    mock_shuffle.assert_called_once()
    targeted = [call.data["entity_id"] for call in calls]
    assert targeted == list(reversed(COVERS))


async def test_sequential_mode_waits_for_target_state(
    hass: HomeAssistant, base_config
) -> None:
    """A cover whose state hasn't yet flipped is awaited before the next runs.

    Strategy: pre-set the first cover to 'closed' (still moving) and
    the rest to 'open'. Kick the run, give the loop one tick, and
    assert we're stuck on the first call. Then flip the first cover
    to 'open' and let the queue drain.
    """
    import asyncio

    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    # Force a deterministic order to make the first call predictable.
    ordered = list(COVERS)
    hass.states.async_set(ordered[0], "closed")
    hass.states.async_set(ordered[1], "open")
    hass.states.async_set(ordered[2], "open")

    scheduler = await _setup(hass, base_config, sequential=True)
    with patch(
        "custom_components.shutters_management.random.shuffle",
        side_effect=lambda seq: None,  # keep insertion order
    ):
        task = hass.async_create_task(scheduler.async_run_now(ACTION_OPEN))

        # Give the event loop a few ticks: the first call should fire,
        # then the wait blocks because cover[0] is still 'closed'.
        for _ in range(5):
            await asyncio.sleep(0)

        assert len(calls) == 1
        assert calls[0].data["entity_id"] == ordered[0]

        # Unblock the wait by flipping the cover to its target state.
        hass.states.async_set(ordered[0], "open")
        await task
        await hass.async_block_till_done()

    targeted = [call.data["entity_id"] for call in calls]
    assert targeted == ordered


async def test_sequential_mode_continues_past_timeout(
    hass: HomeAssistant, base_config
) -> None:
    """A stuck cover (state never flips) doesn't block the queue forever.

    We patch ``COVER_ACTION_TIMEOUT_SECONDS`` to a tiny value so the
    test stays fast; the rest of the queue must still drain after the
    first cover times out.
    """
    calls = async_mock_service(hass, "cover", SERVICE_OPEN_COVER)
    # First cover never reaches target; the others do.
    hass.states.async_set(COVERS[0], "closed")
    hass.states.async_set(COVERS[1], "open")
    hass.states.async_set(COVERS[2], "open")

    scheduler = await _setup(hass, base_config, sequential=True)
    with patch(
        "custom_components.shutters_management.random.shuffle",
        side_effect=lambda seq: None,
    ), patch(
        "custom_components.shutters_management.COVER_ACTION_TIMEOUT_SECONDS",
        0.05,
    ):
        await scheduler.async_run_now(ACTION_OPEN)
        await hass.async_block_till_done()

    targeted = [call.data["entity_id"] for call in calls]
    assert targeted == COVERS


async def test_sequential_mode_uses_close_target_state(
    hass: HomeAssistant, base_config
) -> None:
    """Closing waits on state == 'closed', not 'open'."""
    calls = async_mock_service(hass, "cover", SERVICE_CLOSE_COVER)
    _set_all(hass, COVERS, "closed")

    scheduler = await _setup(hass, base_config, sequential=True)
    await scheduler.async_run_now(ACTION_CLOSE)
    await hass.async_block_till_done()

    assert len(calls) == len(COVERS)
