"""Config, options and PIP trigger flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lg_webos_pip.const import DOMAIN, SUBENTRY_TRIGGER

from .conftest import CAMERA, DOORBELL, TV, make_entry, setup_entry

OPTIONS = {"ha_url": "http://10.0.0.2:8123/", "token": "secret", "mode": "mjpeg",
           "position": "bottom-right", "size": 25.0, "timeout": 45.0, "app_id": "io.github.idaddycz.lgwebospip"}


async def test_user_flow(hass: HomeAssistant, tv) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"tv": TV, **OPTIONS})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PIP on LG G4"
    assert result["data"] == {"tv": TV}
    assert result["options"] == OPTIONS | {"ha_url": "http://10.0.0.2:8123", "size": 25, "timeout": 45}

    # one entry per TV
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"tv": TV, **OPTIONS})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_without_tv(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_tv"


async def test_options_flow(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    new = {**OPTIONS, "position": "top-left"}
    del new["token"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["position"] == "top-left"
    assert "token" not in entry.options


async def test_trigger_subentry_flow(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())

    result = await hass.config_entries.subentries.async_init((entry.entry_id, SUBENTRY_TRIGGER),
                                                             context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    # needs exactly one of camera / url
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Gate", "trigger_entities": ["binary_sensor.gate"]})
    assert result["errors"] == {"base": "camera_or_url"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Gate", "trigger_entities": ["binary_sensor.gate"], "camera": CAMERA, "size": 40.0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    gate = next(s for s in entry.subentries.values() if s.title == "Gate")
    assert dict(gate.data) == {"trigger_entities": ["binary_sensor.gate"], "camera": CAMERA, "size": 40}

    # the new trigger is live after the automatic reload
    hass.states.async_set("binary_sensor.gate", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    assert webos_calls[-1].data["payload"]["params"]["size"] == 40


async def test_trigger_reconfigure(hass: HomeAssistant, tv, webos_calls) -> None:
    entry = await setup_entry(hass, make_entry())
    sub = next(iter(entry.subentries.values()))

    result = await entry.start_subentry_reconfigure_flow(hass, sub.subentry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Front door", "trigger_entities": [DOORBELL], "url": "http://cam/stream.m3u8", "mode": "hls"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    sub = entry.subentries[sub.subentry_id]
    assert sub.title == "Front door"
    assert "camera" not in sub.data and sub.data["url"] == "http://cam/stream.m3u8"
