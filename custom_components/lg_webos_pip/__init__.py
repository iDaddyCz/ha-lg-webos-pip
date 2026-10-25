"""LG webOS PIP: show Home Assistant cameras as picture-in-picture on LG webOS TVs."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CAMERA,
    CONF_MODE,
    CONF_MUTED,
    CONF_POSITION,
    CONF_SIZE,
    CONF_TIMEOUT,
    CONF_TITLE,
    CONF_TV,
    CONF_URL,
    DOMAIN,
    MODES,
    POSITIONS,
    SERVICE_CLOSE,
    SERVICE_SEND_CONNECTION,
    SERVICE_SHOW,
)
from .controller import PipController

PLATFORMS = [Platform.BUTTON, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type LgWebosPipConfigEntry = ConfigEntry[PipController]

TV_SCHEMA = {vol.Optional(CONF_TV): cv.entity_id}
SHOW_SCHEMA = vol.Schema(
    vol.All(
        {
            **TV_SCHEMA,
            vol.Exclusive(CONF_CAMERA, "source"): cv.entity_id,
            vol.Exclusive(CONF_URL, "source"): cv.string,
            vol.Optional(CONF_TITLE): cv.string,
            vol.Optional(CONF_MODE): vol.In(MODES),
            vol.Optional(CONF_POSITION): vol.In(POSITIONS),
            vol.Optional(CONF_SIZE): vol.All(vol.Coerce(int), vol.Range(min=10, max=100)),
            vol.Optional(CONF_TIMEOUT): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
            vol.Optional(CONF_MUTED): cv.boolean,
        },
        cv.has_at_least_one_key(CONF_CAMERA, CONF_URL),
    )
)


def _controller(hass: HomeAssistant, call: ServiceCall) -> PipController:
    """The controller for the TV named in the call, or the only configured TV."""
    entries: list[LgWebosPipConfigEntry] = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    if tv := call.data.get(CONF_TV):
        entries = [e for e in entries if e.runtime_data.tv_entity_id == tv]
        if not entries:
            raise ServiceValidationError(f"{tv} is not set up in LG webOS PIP")
    if not entries:
        raise ServiceValidationError("No TV is set up in LG webOS PIP")
    if len(entries) > 1:
        raise ServiceValidationError("Several TVs are set up: choose one with the 'tv' field")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def show(call: ServiceCall) -> None:
        await _controller(hass, call).async_show(dict(call.data))

    async def close(call: ServiceCall) -> None:
        await _controller(hass, call).async_close()

    async def send_connection(call: ServiceCall) -> None:
        await _controller(hass, call).async_send_connection()

    hass.services.async_register(DOMAIN, SERVICE_SHOW, show, schema=SHOW_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLOSE, close, schema=vol.Schema(TV_SCHEMA))
    hass.services.async_register(DOMAIN, SERVICE_SEND_CONNECTION, send_connection, schema=vol.Schema(TV_SCHEMA))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LgWebosPipConfigEntry) -> bool:
    controller = PipController(hass, entry)
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Started only after the switches have restored each trigger's enabled state.
    controller.async_start_triggers()
    entry.async_on_unload(controller.async_stop_triggers)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LgWebosPipConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: LgWebosPipConfigEntry) -> None:
    """Options or triggers changed."""
    await hass.config_entries.async_reload(entry.entry_id)
