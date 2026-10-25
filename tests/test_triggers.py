"""PIP triggers, entities and actions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.lg_webos_pip.const import CONF_TOKEN, DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import CAMERA, DOORBELL, TV, make_entry, setup_entry

EXPECTED_PIP = {
    "mode": "mjpeg",
    "position": "top-right",
    "size": 30,
    "timeout": 30,
    "camera": CAMERA,
    "title": "Front Door",
    "connect": {"url": "http://10.0.0.2:8123", "token": "secret"},
}


def launched(calls: list[ServiceCall]) -> list[dict]:
    assert all(c.data["command"] == "system.launcher/launch" for c in calls)
    assert all(c.data[ATTR_ENTITY_ID] == TV for c in calls)
    assert all(c.data["payload"]["id"] == "io.github.idaddycz.lgwebospip" for c in calls)
    return [c.data["payload"]["params"] for c in calls]


async def ring(hass: HomeAssistant, entity: str = DOORBELL, state: str = "on") -> None:
    hass.states.async_set(entity, state)
    await hass.async_block_till_done()


async def test_binary_sensor_on_shows_pip(hass: HomeAssistant, tv, webos_calls) -> None:
    await setup_entry(hass, make_entry())
    await ring(hass)
    assert launched(webos_calls) == [EXPECTED_PIP]

    # off, attribute-only changes and unavailable don't fire
    await ring(hass, state="off")
    hass.states.async_set(DOORBELL, "off", {"x": 1})
    await ring(hass, state="unavailable")
    await ring(hass, state="on")  # coming back from unavailable is not a ring
    assert len(webos_calls) == 1


async def test_tv_off_skips_triggers_and_actions(hass: HomeAssistant, tv, webos_calls) -> None:
    await setup_entry(hass, make_entry())
    hass.states.async_set(TV, "off")
    await ring(hass)
    # actions don't fail an automation, they just do nothing
    await hass.services.async_call(DOMAIN, "show", {"camera": CAMERA}, blocking=True)
    await hass.services.async_call(DOMAIN, "close", {}, blocking=True)
    assert webos_calls == []


async def test_tv_off_buttons_say_so(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())
    reg = er.async_get(hass)
    sub_id = next(iter(entry.subentries))
    hass.states.async_set(TV, "off")
    for unique_id in (f"{sub_id}_test", f"{entry.entry_id}_send_connection",
                      f"{entry.entry_id}_open_setup", f"{entry.entry_id}_close_pip"):
        button = reg.async_get_entity_id("button", DOMAIN, unique_id)
        with pytest.raises(HomeAssistantError, match="is off"):
            await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)
    assert webos_calls == []


def webos_tv_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Attach the TV entity to a webOS TV config entry, as the real integration does."""
    tv_entry = MockConfigEntry(domain="webostv", unique_id="tv-uuid")
    tv_entry.add_to_hass(hass)
    er.async_get(hass).async_update_entity(TV, config_entry_id=tv_entry.entry_id)
    return tv_entry


def set_screen(tv_entry: MockConfigEntry, on: bool) -> None:
    tv_entry.runtime_data = SimpleNamespace(client=SimpleNamespace(tv_state=SimpleNamespace(is_screen_on=on)))


async def test_screen_off_counts_as_off(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())
    tv_entry = webos_tv_entry(hass)
    set_screen(tv_entry, False)
    await ring(hass)
    await hass.services.async_call(DOMAIN, "show", {"camera": CAMERA}, blocking=True)
    reg = er.async_get(hass)
    for unique_id in (f"{next(iter(entry.subentries))}_test", f"{entry.entry_id}_send_connection",
                      f"{entry.entry_id}_open_setup"):
        button = reg.async_get_entity_id("button", DOMAIN, unique_id)
        with pytest.raises(HomeAssistantError, match="screen turned off"):
            await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)
    assert webos_calls == []

    # closing a PIP that is still open shows nothing, so it goes through
    await hass.services.async_call(DOMAIN, "close", {}, blocking=True)
    assert launched(webos_calls) == [{"close": True}]

    set_screen(tv_entry, True)
    await ring(hass, state="off")
    await ring(hass)
    assert launched(webos_calls)[1:] == [EXPECTED_PIP]


async def test_screen_off_from_screen_switch(hass: HomeAssistant, tv, webos_calls) -> None:
    """Without the client's state (older HA), the webOS TV screen switch decides."""
    await setup_entry(hass, make_entry())
    webos_tv_entry(hass)
    er.async_get(hass).async_get_or_create("switch", "webostv", "tv-uuid_screen", suggested_object_id="lg_g4_screen")
    hass.states.async_set("switch.lg_g4_screen", "off")
    await ring(hass)
    assert webos_calls == []

    hass.states.async_set("switch.lg_g4_screen", "unavailable")
    await ring(hass, state="off")
    await ring(hass)
    assert launched(webos_calls) == [EXPECTED_PIP]


async def test_event_entity_fires_on_each_event(hass: HomeAssistant, tv, webos_calls) -> None:
    event = "event.doorbell_ring"
    hass.states.async_set(event, "unknown")
    await setup_entry(hass, make_entry(trigger_entities=[event], size=40, position="bottom-left", title="Ring!"))
    await ring(hass, event, "2026-10-25T18:00:00.000+00:00")
    await ring(hass, event, "2026-10-25T18:00:05.000+00:00")
    params = launched(webos_calls)
    assert len(params) == 2
    assert params[0] | {"size": 40, "position": "bottom-left", "title": "Ring!"} == params[0]


async def test_custom_trigger_state(hass: HomeAssistant, tv, webos_calls) -> None:
    sensor = "sensor.gate"
    hass.states.async_set(sensor, "closed")
    await setup_entry(hass, make_entry(trigger_entities=[sensor], trigger_state="open"))
    await ring(hass, sensor, "opening")
    await ring(hass, sensor, "open")
    assert len(webos_calls) == 1


async def test_url_source_and_no_token(hass: HomeAssistant, tv, webos_calls) -> None:
    await setup_entry(hass, make_entry({CONF_TOKEN: None}, camera=None, url="/media/local/clip.mp4"))
    await ring(hass)
    (params,) = launched(webos_calls)
    assert params["url"] == "/media/local/clip.mp4"
    assert "camera" not in params and "connect" not in params and "title" not in params


async def test_enabled_switch(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())
    sub_id = next(iter(entry.subentries))
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{sub_id}_enabled")
    assert hass.states.get(switch).state == "on"

    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: switch}, blocking=True)
    await ring(hass)
    assert webos_calls == []

    await ring(hass, state="off")
    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True)
    await ring(hass)
    assert len(webos_calls) == 1


async def test_buttons(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())
    reg = er.async_get(hass)
    sub_id = next(iter(entry.subentries))

    for unique_id in (f"{sub_id}_test", f"{entry.entry_id}_send_connection",
                      f"{entry.entry_id}_open_setup", f"{entry.entry_id}_close_pip"):
        button = reg.async_get_entity_id("button", DOMAIN, unique_id)
        assert button, unique_id
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)

    assert launched(webos_calls) == [
        EXPECTED_PIP,
        {"connect": EXPECTED_PIP["connect"]},
        {"settings": True},
        {"close": True},
    ]
    # trigger entities live on their own device, linked to the subentry
    assert reg.async_get(reg.async_get_entity_id("button", DOMAIN, f"{sub_id}_test")).config_subentry_id == sub_id


async def test_show_and_close_actions(hass: HomeAssistant, tv, webos_calls) -> None:
    await setup_entry(hass, make_entry())
    await hass.services.async_call(
        DOMAIN, "show", {"camera": CAMERA, "position": "top-left", "timeout": 0, "muted": False}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "close", {"tv": TV}, blocking=True)
    assert launched(webos_calls) == [
        EXPECTED_PIP | {"position": "top-left", "timeout": 0, "muted": False},
        {"close": True},
    ]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "close", {"tv": "media_player.other"}, blocking=True)


async def test_send_connection_needs_token(hass: HomeAssistant, tv, webos_calls) -> None:
    await setup_entry(hass, make_entry({CONF_TOKEN: None}))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_connection", {}, blocking=True)
    assert webos_calls == []


async def test_missing_webostv_service(hass: HomeAssistant, tv) -> None:
    await setup_entry(hass, make_entry())
    with pytest.raises(HomeAssistantError, match="LG webOS TV integration"):
        await hass.services.async_call(DOMAIN, "show", {"camera": CAMERA}, blocking=True)
