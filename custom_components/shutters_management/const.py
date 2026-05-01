"""Constants for the Shutters Management integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "shutters_management"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]

# Hub + subentry architecture (v0.4.0).
TYPE_HUB = "hub"
SUBENTRY_TYPE_INSTANCE = "instance"
HUB_UNIQUE_ID = "_global"
HUB_TITLE = "Shutters Management"
CONF_TYPE = "type"

CONF_COVERS = "covers"
CONF_OPEN_TIME = "open_time"
CONF_CLOSE_TIME = "close_time"
CONF_OPEN_MODE = "open_mode"
CONF_CLOSE_MODE = "close_mode"
CONF_OPEN_OFFSET = "open_offset"
CONF_CLOSE_OFFSET = "close_offset"
CONF_DAYS = "days"
CONF_RANDOMIZE = "randomize"
CONF_RANDOM_MAX_MINUTES = "random_max_minutes"
CONF_ONLY_WHEN_AWAY = "only_when_away"
CONF_PRESENCE_ENTITY = "presence_entity"

CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_WHEN_AWAY_ONLY = "notify_when_away_only"

DEFAULT_OPEN_TIME = "08:00:00"
DEFAULT_CLOSE_TIME = "21:00:00"
DEFAULT_RANDOMIZE = True
DEFAULT_RANDOM_MAX_MINUTES = 30
DEFAULT_ONLY_WHEN_AWAY = False
DEFAULT_NOTIFY_SERVICES: list[str] = []
DEFAULT_NOTIFY_WHEN_AWAY_ONLY = False

MODE_FIXED = "fixed"
MODE_SUNRISE = "sunrise"
MODE_SUNSET = "sunset"
TRIGGER_MODES = [MODE_FIXED, MODE_SUNRISE, MODE_SUNSET]

DEFAULT_OPEN_MODE = MODE_FIXED
DEFAULT_CLOSE_MODE = MODE_FIXED
DEFAULT_OPEN_OFFSET = 0
DEFAULT_CLOSE_OFFSET = 0
OFFSET_MIN_MINUTES = -360
OFFSET_MAX_MINUTES = 360

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


def signal_state_update(scope_id: str) -> str:
    """Return the dispatcher signal name scoped to a subentry (or entry)."""
    return f"{SIGNAL_STATE_UPDATE_PREFIX}_{scope_id}"
