"""Base entities: one device per TV, one device per PIP trigger."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import PipController, PipTrigger


class PipEntity(Entity):
    """Belongs to the TV's PIP device."""

    _attr_has_entity_name = True

    def __init__(self, controller: PipController, key: str) -> None:
        self.controller = controller
        entry = controller.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="LG webOS PIP",
            model="PIP on webOS TV",
        )


class PipTriggerEntity(Entity):
    """Belongs to one PIP trigger (config subentry)."""

    _attr_has_entity_name = True

    def __init__(self, trigger: PipTrigger, key: str) -> None:
        self.trigger = trigger
        entry = trigger.controller.entry
        subentry = trigger.subentry
        self._attr_translation_key = key
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="LG webOS PIP",
            model="PIP trigger",
            via_device=(DOMAIN, entry.entry_id),
        )
