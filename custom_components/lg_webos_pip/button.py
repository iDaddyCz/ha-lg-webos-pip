"""Buttons: TV actions and a test button per PIP trigger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LgWebosPipConfigEntry
from .controller import PipController, PipTrigger
from .entity import PipEntity, PipTriggerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgWebosPipConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller = entry.runtime_data
    async_add_entities([
        PipActionButton(controller, "send_connection", controller.async_send_connection, EntityCategory.CONFIG),
        PipActionButton(controller, "open_setup", controller.async_open_setup, EntityCategory.CONFIG),
        PipActionButton(controller, "close_pip", partial(controller.async_close, raise_if_off=True), None),
    ])
    for subentry_id, trigger in controller.triggers.items():
        async_add_entities([PipTestButton(trigger)], config_subentry_id=subentry_id)


class PipActionButton(PipEntity, ButtonEntity):
    def __init__(
        self,
        controller: PipController,
        key: str,
        action: Callable[[], Awaitable[None]],
        category: EntityCategory | None,
    ) -> None:
        super().__init__(controller, key)
        self._action = action
        self._attr_entity_category = category

    async def async_press(self) -> None:
        await self._action()


class PipTestButton(PipTriggerEntity, ButtonEntity):
    """Shows this trigger's PIP now; says so if the TV is off."""

    def __init__(self, trigger: PipTrigger) -> None:
        super().__init__(trigger, "test")

    async def async_press(self) -> None:
        await self.trigger.controller.async_show(self.trigger.config, raise_if_off=True)
