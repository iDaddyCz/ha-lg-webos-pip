"""Constants for LG webOS PIP."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lg_webos_pip"

DEFAULT_APP_ID: Final = "io.github.idaddycz.lgwebospip"
WEBOSTV_DOMAIN: Final = "webostv"

# Config entry data / options
CONF_TV: Final = "tv"
CONF_APP_ID: Final = "app_id"
CONF_HA_URL: Final = "ha_url"
CONF_TOKEN: Final = "token"

# PIP display options (entry defaults, trigger overrides, action fields)
CONF_CAMERA: Final = "camera"
CONF_URL: Final = "url"
CONF_TITLE: Final = "title"
CONF_MODE: Final = "mode"
CONF_POSITION: Final = "position"
CONF_SIZE: Final = "size"
CONF_TIMEOUT: Final = "timeout"
CONF_MUTED: Final = "muted"

# Trigger subentries
SUBENTRY_TRIGGER: Final = "trigger"
CONF_TRIGGER_ENTITIES: Final = "trigger_entities"
CONF_TRIGGER_STATE: Final = "trigger_state"

MODES: Final = ["mjpeg", "snapshot", "hls", "webrtc"]
POSITIONS: Final = ["top-right", "top-left", "bottom-right", "bottom-left"]

DEFAULT_MODE: Final = "mjpeg"
DEFAULT_POSITION: Final = "top-right"
DEFAULT_SIZE: Final = 30
DEFAULT_TIMEOUT: Final = 30

# Without an explicit trigger state, these domains fire when they turn "on";
# everything else (e.g. event entities) fires on any state change.
ON_STATE_DOMAINS: Final = {"binary_sensor", "input_boolean", "switch", "light"}

SERVICE_SHOW: Final = "show"
SERVICE_CLOSE: Final = "close"
SERVICE_SEND_CONNECTION: Final = "send_connection"
