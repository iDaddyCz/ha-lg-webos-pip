"""Config flow: pick a webOS TV, set connection and defaults, add PIP triggers."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_APP_ID,
    CONF_CAMERA,
    CONF_HA_URL,
    CONF_MODE,
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
    DOMAIN,
    MODES,
    POSITIONS,
    SUBENTRY_TRIGGER,
    WEBOSTV_DOMAIN,
)

MODE_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=MODES, translation_key="mode", mode=SelectSelectorMode.DROPDOWN)
)
POSITION_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=POSITIONS, translation_key="position", mode=SelectSelectorMode.DROPDOWN)
)
SIZE_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=10, max=100, step=5, unit_of_measurement="%", mode=NumberSelectorMode.SLIDER)
)
TIMEOUT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=0, max=3600, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX)
)
TEXT = TextSelector()
URL_TEXT = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _webos_tvs(hass: HomeAssistant) -> list[str]:
    return [
        e.entity_id
        for e in er.async_get(hass).entities.values()
        if e.platform == WEBOSTV_DOMAIN and e.domain == "media_player"
    ]


def _default_ha_url(hass: HomeAssistant) -> str:
    try:
        return get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError:
        return ""


# Connection for the TV app plus display defaults.
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_HA_URL): URL_TEXT,
        vol.Optional(CONF_TOKEN): PASSWORD,
        vol.Required(CONF_MODE, default=DEFAULT_MODE): MODE_SELECTOR,
        vol.Required(CONF_POSITION, default=DEFAULT_POSITION): POSITION_SELECTOR,
        vol.Required(CONF_SIZE, default=DEFAULT_SIZE): SIZE_SELECTOR,
        vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): TIMEOUT_SELECTOR,
        vol.Required(CONF_APP_ID, default=DEFAULT_APP_ID): TEXT,
    }
)


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    options = dict(user_input)
    if options.get(CONF_HA_URL):
        options[CONF_HA_URL] = options[CONF_HA_URL].rstrip("/")
    options[CONF_SIZE] = int(options[CONF_SIZE])
    options[CONF_TIMEOUT] = int(options[CONF_TIMEOUT])
    return options


class LgWebosPipConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up PIP for one LG webOS TV."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LgWebosPipOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TRIGGER: PipTriggerSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        tvs = _webos_tvs(self.hass)
        if not tvs:
            return self.async_abort(reason="no_tv")

        if user_input is not None:
            tv = user_input.pop(CONF_TV)
            await self.async_set_unique_id(tv)
            self._abort_if_unique_id_configured()
            state = self.hass.states.get(tv)
            return self.async_create_entry(
                title=f"PIP on {state.name if state else tv}",
                data={CONF_TV: tv},
                options=_clean_options(user_input),
            )

        schema = vol.Schema(
            {vol.Required(CONF_TV): EntitySelector(EntitySelectorConfig(include_entities=tvs))}
        ).extend(OPTIONS_SCHEMA.schema)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, {CONF_HA_URL: _default_ha_url(self.hass)}),
        )


class LgWebosPipOptionsFlow(OptionsFlow):
    """Change the connection sent to the TV and the display defaults."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean_options(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, self.config_entry.options),
        )


TRIGGER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TEXT,
        vol.Required(CONF_TRIGGER_ENTITIES): EntitySelector(EntitySelectorConfig(multiple=True)),
        vol.Optional(CONF_TRIGGER_STATE): TEXT,
        vol.Optional(CONF_CAMERA): EntitySelector(EntitySelectorConfig(domain="camera")),
        vol.Optional(CONF_URL): TEXT,
        vol.Optional(CONF_TITLE): TEXT,
        vol.Optional(CONF_MODE): MODE_SELECTOR,
        vol.Optional(CONF_POSITION): POSITION_SELECTOR,
        vol.Optional(CONF_SIZE): SIZE_SELECTOR,
        vol.Optional(CONF_TIMEOUT): TIMEOUT_SELECTOR,
    }
)


class PipTriggerSubentryFlow(ConfigSubentryFlow):
    """Add or edit a PIP trigger: when X happens, show camera Y."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._form("user", user_input, {})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        return await self._form("reconfigure", user_input, {**subentry.data, CONF_NAME: subentry.title})

    async def _form(
        self, step_id: str, user_input: dict[str, Any] | None, current: dict[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if bool(user_input.get(CONF_CAMERA)) == bool(user_input.get(CONF_URL)):
                errors["base"] = "camera_or_url"
            else:
                data = dict(user_input)
                title = data.pop(CONF_NAME)
                for key in (CONF_SIZE, CONF_TIMEOUT):
                    if key in data:
                        data[key] = int(data[key])
                if step_id == "user":
                    return self.async_create_entry(title=title, data=data)
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(TRIGGER_SCHEMA, user_input or current),
            errors=errors,
        )
