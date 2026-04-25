"""Constants for the Shutters Management integration."""
from __future__ import annotations

DOMAIN = "shutters_management"

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
