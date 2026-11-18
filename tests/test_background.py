"""Starting the TV app in the background from the home screen."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .conftest import TV, make_entry, setup_entry

STANDBY = {"standby": True, "connect": {"url": "http://10.0.0.2:8123", "token": "secret"}}


async def settle(hass: HomeAssistant, seconds: int = 4) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def params(calls: list[ServiceCall]) -> list[dict]:
    return [c.data["payload"]["params"] for c in calls]


async def test_started_from_the_home_screen(hass: HomeAssistant, tv, webos_calls) -> None:
    hass.states.async_set(TV, "playing", {"source": "YouTube"})
    await setup_entry(hass, make_entry({"background": True}))
    await settle(hass)
    assert webos_calls == []  # never while an app is in front

    # back on the home screen, which has to settle first
    hass.states.async_set(TV, "on", {})
    await hass.async_block_till_done()
    assert webos_calls == []
    await settle(hass)
    assert params(webos_calls) == [STANDBY]

    # staying on the home screen (e.g. a volume change) doesn't start it again
    hass.states.async_set(TV, "on", {"volume_level": 0.2})
    await settle(hass)
    assert len(webos_calls) == 1


async def test_leaving_the_home_screen_cancels(hass: HomeAssistant, tv, webos_calls) -> None:
    hass.states.async_set(TV, "on", {})
    await setup_entry(hass, make_entry({"background": True, "token": None}))
    hass.states.async_set(TV, "on", {"source": "Netflix"})
    await settle(hass)
    assert webos_calls == []

    hass.states.async_set(TV, "on", {})
    await settle(hass)
    assert params(webos_calls) == [{"standby": True}]  # no token stored, so no connection


async def test_uses_the_tv_clients_app_id(hass: HomeAssistant, tv, webos_calls) -> None:
    """The webOS TV client knows the app in front, even one the media player can't name."""
    tv_entry = MockConfigEntry(domain="webostv", unique_id="tv-uuid")
    tv_entry.add_to_hass(hass)
    er.async_get(hass).async_update_entity(TV, config_entry_id=tv_entry.entry_id)
    tv_state = SimpleNamespace(is_screen_on=True, current_app_id="com.example.unlisted")
    tv_entry.runtime_data = SimpleNamespace(client=SimpleNamespace(tv_state=tv_state))

    await setup_entry(hass, make_entry({"background": True}))
    await settle(hass)
    assert webos_calls == []

    tv_state.current_app_id = "com.webos.app.home"
    hass.states.async_set(TV, "on", {"x": 1})
    await settle(hass)
    assert params(webos_calls) == [STANDBY]

    # never with the screen off
    tv_state.current_app_id = "youtube.leanback.v4"
    hass.states.async_set(TV, "on", {"x": 2})
    await hass.async_block_till_done()
    tv_state.current_app_id, tv_state.is_screen_on = "com.webos.app.home", False
    hass.states.async_set(TV, "on", {"x": 3})
    await settle(hass)
    assert len(webos_calls) == 1


async def test_option_off(hass: HomeAssistant, tv, webos_calls) -> None:
    await setup_entry(hass, make_entry())  # make_entry turns it off
    hass.states.async_set(TV, "off")
    hass.states.async_set(TV, "on", {})
    await settle(hass)
    assert webos_calls == []
