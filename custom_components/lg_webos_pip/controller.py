"""Launches the HA PIP app on an LG webOS TV and fires PIP triggers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_APP_ID,
    CONF_CAMERA,
    CONF_HA_URL,
    CONF_MODE,
    CONF_MUTED,
    CONF_POSITION,
    CONF_SIZE,
    CONF_TIMEOUT,
    CONF_TITLE,
    CONF_TOKEN,
    CONF_TRIGGER_ENTITIES,
    CONF_TRIGGER_STATE,
    CONF_TV,
    CONF_URL,
    DEFAULT_APP_ID,
    DEFAULT_MODE,
    DEFAULT_POSITION,
    DEFAULT_SIZE,
    DEFAULT_TIMEOUT,
    ON_STATE_DOMAINS,
    WEBOSTV_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DISPLAY_KEYS = (CONF_CAMERA, CONF_URL, CONF_TITLE, CONF_MODE, CONF_POSITION, CONF_SIZE, CONF_TIMEOUT, CONF_MUTED)


class PipController:
    """One TV: builds launch params and sends them through the webOS TV integration."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        # Created up front so the switch platform can restore `enabled` before they start.
        self.triggers: dict[str, PipTrigger] = {
            subentry_id: PipTrigger(self, subentry) for subentry_id, subentry in entry.subentries.items()
        }

    @property
    def _config(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def tv_entity_id(self) -> str:
        return self._config[CONF_TV]

    @property
    def app_id(self) -> str:
        return self._config.get(CONF_APP_ID) or DEFAULT_APP_ID

    @property
    def tv_is_on(self) -> bool:
        state = self.hass.states.get(self.tv_entity_id)
        return state is not None and state.state == STATE_ON

    def _connection(self) -> dict[str, str] | None:
        """URL + token for the TV app, if the user stored a token here."""
        cfg = self._config
        if cfg.get(CONF_HA_URL) and cfg.get(CONF_TOKEN):
            return {"url": cfg[CONF_HA_URL].rstrip("/"), "token": cfg[CONF_TOKEN]}
        return None

    def build_params(self, display: dict[str, Any]) -> dict[str, Any]:
        """Launch params: entry defaults, overridden by non-empty `display` values."""
        cfg = self._config
        params: dict[str, Any] = {
            CONF_MODE: cfg.get(CONF_MODE, DEFAULT_MODE),
            CONF_POSITION: cfg.get(CONF_POSITION, DEFAULT_POSITION),
            CONF_SIZE: int(cfg.get(CONF_SIZE, DEFAULT_SIZE)),
            CONF_TIMEOUT: int(cfg.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        }
        for key in DISPLAY_KEYS:
            value = display.get(key)
            if value not in (None, ""):
                params[key] = int(value) if key in (CONF_SIZE, CONF_TIMEOUT) else value
        if CONF_URL in params:
            params.pop(CONF_CAMERA, None)
        if (camera := params.get(CONF_CAMERA)) and CONF_TITLE not in params:
            if state := self.hass.states.get(camera):
                params[CONF_TITLE] = state.name
        if connection := self._connection():
            params["connect"] = connection
        return params

    async def _launch(self, params: dict[str, Any], *, raise_if_off: bool) -> None:
        """Launch the app, but only while the TV is on.

        Triggers and actions skip quietly when it's off; buttons pressed by a
        user raise so the UI says why nothing happened.
        """
        if not self.hass.services.has_service(WEBOSTV_DOMAIN, "command"):
            raise HomeAssistantError("The LG webOS TV integration is not set up")
        if not self.tv_is_on:
            if raise_if_off:
                raise HomeAssistantError(f"{self.tv_entity_id} is off")
            _LOGGER.debug("Not launching on %s: the TV is off", self.tv_entity_id)
            return
        _LOGGER.debug("Launching %s on %s with %s", self.app_id, self.tv_entity_id,
                      {k: v for k, v in params.items() if k != "connect"})
        await self.hass.services.async_call(
            WEBOSTV_DOMAIN,
            "command",
            {
                ATTR_ENTITY_ID: self.tv_entity_id,
                "command": "system.launcher/launch",
                "payload": {"id": self.app_id, "params": params},
            },
            blocking=True,
        )

    async def async_show(self, display: dict[str, Any], *, raise_if_off: bool = False) -> None:
        params = self.build_params(display)
        if not params.get(CONF_CAMERA) and not params.get(CONF_URL):
            raise HomeAssistantError("Choose a camera or a URL to show")
        await self._launch(params, raise_if_off=raise_if_off)

    async def async_close(self, *, raise_if_off: bool = False) -> None:
        await self._launch({"close": True}, raise_if_off=raise_if_off)

    async def async_send_connection(self) -> None:
        connection = self._connection()
        if connection is None:
            raise HomeAssistantError("Set the Home Assistant URL and access token in the integration options first")
        await self._launch({"connect": connection}, raise_if_off=True)

    async def async_open_setup(self) -> None:
        await self._launch({"settings": True}, raise_if_off=True)

    # ---------- triggers ----------

    @callback
    def async_start_triggers(self) -> None:
        for trigger in self.triggers.values():
            trigger.async_start()

    @callback
    def async_stop_triggers(self) -> None:
        for trigger in self.triggers.values():
            trigger.async_stop()


@dataclass
class PipTrigger:
    """Shows a PIP when one of the configured entities changes to the trigger state."""

    controller: PipController
    subentry: ConfigSubentry
    enabled: bool = True
    _unsub: Any = None

    @property
    def config(self) -> dict[str, Any]:
        return dict(self.subentry.data)

    @callback
    def async_start(self) -> None:
        entities = self.config.get(CONF_TRIGGER_ENTITIES) or []
        if entities:
            self._unsub = async_track_state_change_event(self.controller.hass, entities, self._handle)

    @callback
    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def matches(self, old_state: Any, new_state: Any) -> bool:
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        # Entity just added or coming back after a restart: not a real event.
        if old_state is None or old_state.state == STATE_UNAVAILABLE:
            return False
        if old_state.state == new_state.state:
            return False  # attribute-only change
        wanted = self.config.get(CONF_TRIGGER_STATE)
        if not wanted and new_state.domain in ON_STATE_DOMAINS:
            wanted = STATE_ON
        return not wanted or new_state.state == wanted

    @callback
    def _handle(self, event: Event[EventStateChangedData]) -> None:
        if not self.enabled or not self.matches(event.data["old_state"], event.data["new_state"]):
            return
        self.controller.hass.async_create_task(self.async_fire(), f"{self.subentry.title} PIP")

    async def async_fire(self) -> None:
        try:
            await self.controller.async_show(self.config)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not show PIP for %s: %s", self.subentry.title, err)
