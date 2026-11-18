"""Launches the HA PIP app on an LG webOS TV and fires PIP triggers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    BACKGROUND_DELAY,
    CONF_APP_ID,
    CONF_BACKGROUND,
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
    DEFAULT_BACKGROUND,
    DEFAULT_MODE,
    DEFAULT_POSITION,
    DEFAULT_SIZE,
    DEFAULT_TIMEOUT,
    HOME_APP_ID,
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
        self._unsub_tv: CALLBACK_TYPE | None = None
        self._background_timer: CALLBACK_TYPE | None = None
        self._was_on_home_screen = False

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
        """The webOS TV media player is `playing`, `paused` or `idle` while an app plays media."""
        state = self.hass.states.get(self.tv_entity_id)
        return state is not None and state.state not in (STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN)

    def _tv_entry(self) -> ConfigEntry | None:
        """The webOS TV integration's config entry for this TV."""
        tv = er.async_get(self.hass).async_get(self.tv_entity_id)
        if tv is None or tv.config_entry_id is None:
            return None
        return self.hass.config_entries.async_get_entry(tv.config_entry_id)

    @staticmethod
    def _tv_state(tv_entry: ConfigEntry) -> Any:
        """The state the webOS TV integration's client tracks (aiowebostv TvState), if reachable."""
        client = getattr(getattr(tv_entry, "runtime_data", None), "client", None)
        return getattr(client, "tv_state", None)

    @property
    def screen_is_off(self) -> bool:
        """True in the TV's screen-off mode: the TV is on, but the picture is off."""
        tv_entry = self._tv_entry()
        if tv_entry is None:
            return False
        # The webOS TV integration tracks it on its client...
        is_screen_on = getattr(self._tv_state(tv_entry), "is_screen_on", None)
        if is_screen_on is not None:
            return not is_screen_on
        # ...and shows it as a screen switch (disabled by default).
        registry = er.async_get(self.hass)
        switch = registry.async_get_entity_id("switch", WEBOSTV_DOMAIN, f"{tv_entry.unique_id}_screen")
        state = self.hass.states.get(switch) if switch else None
        return state is not None and state.state == STATE_OFF

    @property
    def on_home_screen(self) -> bool:
        """True while the TV shows its home screen, where launching an app interrupts nothing."""
        state = self.hass.states.get(self.tv_entity_id)
        if state is None or state.state != STATE_ON or self.screen_is_off:
            return False
        tv_entry = self._tv_entry()
        app_id = getattr(self._tv_state(tv_entry), "current_app_id", None) if tv_entry else None
        if app_id is not None:
            return app_id == HOME_APP_ID
        # Without the client: the media player names no source on the home screen.
        return not state.attributes.get("source")

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

    async def _launch(self, params: dict[str, Any], *, raise_if_off: bool, screen_off_ok: bool = False) -> None:
        """Launch the app, but only while the TV is on and its screen is too.

        Triggers and actions skip quietly when it's off; buttons pressed by a
        user raise so the UI says why nothing happened. `screen_off_ok` lets
        commands that show nothing (close) through in screen-off mode.
        """
        if not self.hass.services.has_service(WEBOSTV_DOMAIN, "command"):
            raise HomeAssistantError("The LG webOS TV integration is not set up")
        if not self.tv_is_on:
            reason = "is off"
        elif not screen_off_ok and self.screen_is_off:
            reason = "has its screen turned off"
        else:
            reason = None
        if reason:
            if raise_if_off:
                raise HomeAssistantError(f"{self.tv_entity_id} {reason}")
            _LOGGER.debug("Not launching on %s: the TV %s", self.tv_entity_id, reason)
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
        await self._launch({"close": True}, raise_if_off=raise_if_off, screen_off_ok=True)

    async def async_send_connection(self) -> None:
        connection = self._connection()
        if connection is None:
            raise HomeAssistantError("Set the Home Assistant URL and access token in the integration options first")
        await self._launch({"connect": connection}, raise_if_off=True)

    async def async_open_setup(self) -> None:
        await self._launch({"settings": True}, raise_if_off=True)

    # ---------- the TV app in the background ----------
    #
    # Launching an app makes webOS stop the one in front (YouTube unloads its
    # video); relaunching a running app doesn't. So the TV app is started in
    # the background whenever the TV sits on its home screen, and later PIPs
    # are relaunches. See webos-app/app/js/window.js.

    @callback
    def async_start_background(self) -> None:
        if not self._config.get(CONF_BACKGROUND, DEFAULT_BACKGROUND):
            return
        self._unsub_tv = async_track_state_change_event(self.hass, [self.tv_entity_id], self._handle_tv_change)
        self._update_background()

    @callback
    def async_stop_background(self) -> None:
        if self._unsub_tv:
            self._unsub_tv()
            self._unsub_tv = None
        self._cancel_background_timer()

    @callback
    def _cancel_background_timer(self) -> None:
        if self._background_timer:
            self._background_timer()
            self._background_timer = None

    @callback
    def _handle_tv_change(self, event: Event[EventStateChangedData]) -> None:
        self._update_background()

    @callback
    def _update_background(self) -> None:
        """Start the app once the TV has been on its home screen for a moment."""
        on_home = self.on_home_screen
        if on_home and not self._was_on_home_screen:
            self._cancel_background_timer()
            self._background_timer = async_call_later(self.hass, BACKGROUND_DELAY, self._background_due)
        elif not on_home:
            self._cancel_background_timer()
        self._was_on_home_screen = on_home

    @callback
    def _background_due(self, _now: Any) -> None:
        self._background_timer = None
        if self.on_home_screen:
            self.hass.async_create_task(self.async_start_in_background(), f"Start {self.app_id} in the background")

    async def async_start_in_background(self) -> None:
        params: dict[str, Any] = {"standby": True}
        if connection := self._connection():
            params["connect"] = connection
        try:
            await self._launch(params, raise_if_off=False)
        except HomeAssistantError as err:
            _LOGGER.debug("Could not start %s in the background: %s", self.app_id, err)

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
