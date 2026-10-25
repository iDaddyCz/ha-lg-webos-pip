"""Shared fixtures."""

from __future__ import annotations

import pytest

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from custom_components.lg_webos_pip.const import (
    CONF_CAMERA,
    CONF_HA_URL,
    CONF_TOKEN,
    CONF_TRIGGER_ENTITIES,
    CONF_TV,
    DOMAIN,
    SUBENTRY_TRIGGER,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

TV = "media_player.lg_g4"
DOORBELL = "binary_sensor.doorbell"
CAMERA = "camera.front_door"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def tv(hass: HomeAssistant) -> str:
    """A media player that looks like it comes from the LG webOS TV integration."""
    entry = er.async_get(hass).async_get_or_create("media_player", "webostv", "tv-1", suggested_object_id="lg_g4")
    assert entry.entity_id == TV
    hass.states.async_set(TV, "on", {"friendly_name": "LG G4"})
    hass.states.async_set(CAMERA, "idle", {"friendly_name": "Front Door"})
    hass.states.async_set(DOORBELL, "off")
    return TV


@pytest.fixture
def webos_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Stands in for webostv.command."""
    return async_mock_service(hass, "webostv", "command")


def make_entry(options: dict | None = None, **trigger: object) -> MockConfigEntry:
    """Entry for TV with one "Doorbell" trigger; `options` values of None remove a key."""
    merged = {
        CONF_HA_URL: "http://10.0.0.2:8123",
        CONF_TOKEN: "secret",
        "mode": "mjpeg",
        "position": "top-right",
        "size": 30,
        "timeout": 30,
        "app_id": "io.github.idaddycz.lgwebospip",
    } | (options or {})
    return MockConfigEntry(
        domain=DOMAIN,
        title="PIP on LG G4",
        unique_id=TV,
        data={CONF_TV: TV},
        options={k: v for k, v in merged.items() if v is not None},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_TRIGGER_ENTITIES: [DOORBELL], CONF_CAMERA: CAMERA, **trigger},
                subentry_type=SUBENTRY_TRIGGER,
                title="Doorbell",
                unique_id=None,
            )
        ],
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
