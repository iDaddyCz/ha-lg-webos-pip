"""Switch per PIP trigger to turn it on and off without deleting it."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LgWebosPipConfigEntry
from .controller import PipTrigger
from .entity import PipTriggerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosPipConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, trigger in entry.runtime_data.triggers.items():
        async_add_entities([PipTriggerSwitch(trigger)], config_subentry_id=subentry_id)


class PipTriggerSwitch(PipTriggerEntity, SwitchEntity, RestoreEntity):
    def __init__(self, trigger: PipTrigger) -> None:
        super().__init__(trigger, "enabled")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.trigger.enabled = last.state != STATE_OFF

    @property
    def is_on(self) -> bool:
        return self.trigger.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.trigger.enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.trigger.enabled = False
        self.async_write_ha_state()
