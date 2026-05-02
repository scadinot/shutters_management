"""Constants for the Shutters Management integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "shutters_management"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.BINARY_SENSOR]

# Hub + subentry architecture (v0.4.0).
TYPE_HUB = "hub"
SUBENTRY_TYPE_INSTANCE = "instance"
SUBENTRY_TYPE_SUN_PROTECTION = "sun_protection"
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

# Sun protection (v0.4.6)
CONF_UV_ENTITY = "uv_entity"
CONF_ORIENTATION = "orientation"
CONF_ARC = "arc"
CONF_MIN_ELEVATION = "min_elevation"
CONF_MIN_UV = "min_uv"
CONF_TARGET_POSITION = "target_position"

ORIENTATION_CARDINALS: dict[str, int] = {
    "n": 0, "ne": 45, "e": 90, "se": 135,
    "s": 180, "sw": 225, "w": 270, "nw": 315,
}

DEFAULT_UV_ENTITY: str = ""
DEFAULT_ORIENTATION = 180  # South
DEFAULT_ARC = 60
DEFAULT_MIN_ELEVATION = 15
DEFAULT_MIN_UV = 3
DEFAULT_TARGET_POSITION = 50

SUN_ENTITY = "sun.sun"

CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_WHEN_AWAY_ONLY = "notify_when_away_only"  # kept for v3→v4 migration
CONF_NOTIFY_MODE = "notify_mode"
CONF_SEQUENTIAL_COVERS = "sequential_covers"
CONF_TTS_ENGINE = "tts_engine"
CONF_TTS_TARGETS = "tts_targets"
CONF_TTS_WHEN_AWAY_ONLY = "tts_when_away_only"  # kept for v3→v4 migration
CONF_TTS_MODE = "tts_mode"

# Three-state notification mode (replaces the boolean away_only flags from v0.4.4).
MODE_DISABLED = "disabled"   # channel never fires
MODE_ALWAYS = "always"       # channel fires on every action
MODE_AWAY_ONLY = "away_only" # channel fires only when presence is detected away

DEFAULT_OPEN_TIME = "08:00:00"
DEFAULT_CLOSE_TIME = "21:00:00"
DEFAULT_RANDOMIZE = True
DEFAULT_RANDOM_MAX_MINUTES = 30
DEFAULT_ONLY_WHEN_AWAY = False
DEFAULT_NOTIFY_SERVICES: list[str] = []
DEFAULT_NOTIFY_MODE = MODE_ALWAYS
DEFAULT_SEQUENTIAL_COVERS = False
DEFAULT_TTS_ENGINE: str | None = None
DEFAULT_TTS_TARGETS: list[str] = []
DEFAULT_TTS_MODE = MODE_DISABLED

# Hard cap for waiting on a cover to reach its target state in
# sequential mode. Most motorised shutters take 20–40 s; 90 s covers
# slow models and prevents a stuck cover from blocking the queue.
COVER_ACTION_TIMEOUT_SECONDS = 90

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
