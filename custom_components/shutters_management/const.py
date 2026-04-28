"""Constants for the Shutters Management integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "shutters_management"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]

CONF_COVERS = "covers"
CONF_OPEN_TIME = "open_time"
CONF_CLOSE_TIME = "close_time"
CONF_DAYS = "days"
CONF_RANDOMIZE = "randomize"
CONF_RANDOM_MAX_MINUTES = "random_max_minutes"
CONF_ONLY_WHEN_AWAY = "only_when_away"
CONF_PRESENCE_ENTITY = "presence_entity"

DEFAULT_OPEN_TIME = "08:00:00"
DEFAULT_CLOSE_TIME = "21:00:00"
DEFAULT_RANDOMIZE = True
DEFAULT_RANDOM_MAX_MINUTES = 30
DEFAULT_ONLY_WHEN_AWAY = False

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_DAYS = DAYS

AWAY_STATES = {"not_home", "away"}

SERVICE_RUN_NOW = "run_now"
SERVICE_PAUSE = "pause"
SERVICE_RESUME = "resume"

ATTR_ACTION = "action"
ACTION_OPEN = "open"
ACTION_CLOSE = "close"

SIGNAL_STATE_UPDATE_PREFIX = "shutters_management_state_update"


def signal_state_update(entry_id: str) -> str:
    """Return the dispatcher signal name scoped to a config entry."""
    return f"{SIGNAL_STATE_UPDATE_PREFIX}_{entry_id}"
