"""Config flow for TL Remote."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ENTITY_PREFIX,
    CONF_EXPOSED_ENTITIES,
    CONF_HOST,
    CONF_MAIN,
    CONF_PORT,
    CONF_REMOTE,
    CONF_SECURE,
    CONF_TYPE,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DISCOVERY_URL,
    DOMAIN,
    REMOTE_ID,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class EndpointMissing(HomeAssistantError):
    """Error to indicate the remote node does not run TL Remote."""


async def async_get_discovery_info(
    hass: HomeAssistant,
    host: str,
    port: int,
    secure: bool,
    access_token: str,
    verify_ssl: bool,
) -> dict:
    """Fetch discovery information from the remote node."""
    url = DISCOVERY_URL.format(
        proto="https" if secure else "http",
        host=host,
        port=port,
    )
    headers = {
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json",
    }
    session = aiohttp_client.async_get_clientsession(hass, verify_ssl)
    async with session.get(url, headers=headers, timeout=15) as resp:
        if resp.status == 404:
            raise EndpointMissing()
        if 400 <= resp.status < 500:
            raise InvalidAuth()
        if resp.status != 200:
            raise CannotConnect()
        data = await resp.json()
        if not isinstance(data, dict) or "uuid" not in data:
            raise EndpointMissing()
        return data


class TLRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TL Remote."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step: choose instance role."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_TYPE] == CONF_REMOTE:
                await self.async_set_unique_id(REMOTE_ID)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="TL Remote узел",
                    data={CONF_TYPE: CONF_REMOTE},
                )
            return await self.async_step_connection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TYPE): vol.In(
                        {
                            CONF_REMOTE: "Этот HA — источник устройств (узел)",
                            CONF_MAIN: "Этот HA — приёмник (подключить другой HA)",
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_connection(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle the connection details step (main side)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await async_get_discovery_info(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input.get(CONF_SECURE, False),
                    user_input[CONF_ACCESS_TOKEN],
                    user_input.get(CONF_VERIFY_SSL, False),
                )
            except EndpointMissing:
                errors["base"] = "missing_endpoint"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during discovery")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["uuid"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["location_name"] or "TL Remote",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                    vol.Required(CONF_ACCESS_TOKEN): str,
                    vol.Optional(CONF_SECURE, default=False): bool,
                    vol.Optional(CONF_VERIFY_SSL, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the connection (main instance)."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None or entry.unique_id == REMOTE_ID:
            return self.async_abort(reason="reconfigure_not_supported")

        if user_input is not None:
            try:
                info = await async_get_discovery_info(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input.get(CONF_SECURE, False),
                    user_input[CONF_ACCESS_TOKEN],
                    user_input.get(CONF_VERIFY_SSL, False),
                )
            except EndpointMissing:
                errors["base"] = "missing_endpoint"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during reconfigure")
                errors["base"] = "unknown"
            else:
                data = {**entry.data, **user_input}
                return self.async_update_reload_and_abort(
                    entry, data=data, reason="reconfigure_successful"
                )

        data = entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
                    vol.Optional(
                        CONF_PORT, default=data.get(CONF_PORT, DEFAULT_PORT)
                    ): cv.port,
                    vol.Required(
                        CONF_ACCESS_TOKEN, default=data.get(CONF_ACCESS_TOKEN, "")
                    ): str,
                    vol.Optional(
                        CONF_SECURE, default=data.get(CONF_SECURE, False)
                    ): bool,
                    vol.Optional(
                        CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL, False)
                    ): bool,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return TLRemoteOptionsFlow(config_entry)


class TLRemoteOptionsFlow(OptionsFlow):
    """Handle options: remote node picks entities, main picks prefix."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = config_entry

    @callback
    def _available_entities(self) -> list[str]:
        """Return all currently available entities."""
        return sorted(self.hass.states.async_entity_ids())

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Route to the right step based on the entry role."""
        if self._entry.unique_id == REMOTE_ID:
            return await self.async_step_expose(user_input)
        return await self.async_step_prefix(user_input)

    async def async_step_expose(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Remote node: choose which entities to expose."""
        if user_input is not None:
            exposed = user_input.get(CONF_EXPOSED_ENTITIES, [])
            if isinstance(exposed, str):
                exposed = [exposed]
            return self.async_create_entry(
                title="", data={CONF_EXPOSED_ENTITIES: list(exposed)}
            )

        current = self._entry.options.get(CONF_EXPOSED_ENTITIES, [])
        return self.async_show_form(
            step_id="expose",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXPOSED_ENTITIES, default=current
                    ): EntitySelector(EntitySelectorConfig(multiple=True))
                }
            ),
        )

    async def async_step_prefix(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Main side: optional entity prefix."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="prefix",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENTITY_PREFIX,
                        default=self._entry.options.get(CONF_ENTITY_PREFIX, ""),
                    ): str
                }
            ),
        )
