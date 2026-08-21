"""Sensor platform for the TL Remote connection status."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_ON, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_ENTITY_PREFIX,
    DOMAIN,
    REMOTE_ID,
    SIGNAL_CONNECTION_STATE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: entity_platform.AddEntitiesCallback,
) -> None:
    """Set up the connection status sensor for the main instance."""
    if config_entry.unique_id == REMOTE_ID:
        return
    async_add_entities([ConnectionStatusSensor(config_entry)])


class ConnectionStatusSensor(Entity):
    """Representation of the remote connection status."""

    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._entry = config_entry
        self._connected = False
        self._attr_unique_id = f"{config_entry.entry_id}_connection"
        self._attr_name = f"TL Remote {config_entry.data.get(CONF_HOST)}:{config_entry.data.get(CONF_PORT)}"
        self._attr_device_class = "connectivity"
        self._attr_icon = "mdi:server-network"
        self._attr_translation_key = "connection"
        self._attr_translation_placeholders = {
            "host": config_entry.data.get(CONF_HOST, ""),
            "port": str(config_entry.data.get(CONF_PORT, "")),
        }

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        return STATE_ON if self._connected else STATE_OFF

    @property
    def extra_state_attributes(self) -> dict:
        """Return connection attributes."""
        return {
            "host": self._entry.data.get(CONF_HOST),
            "port": self._entry.data.get(CONF_PORT),
            "entity_prefix": self._entry.options.get(CONF_ENTITY_PREFIX, ""),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection state updates."""
        await super().async_added_to_hass()

        # Initialize from the current connection state (avoids a race
        # where the connect signal is emitted before we subscribe).
        connection = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if connection is not None and getattr(connection, "is_connected", False):
            self._connected = True

        def _update(_entry_id: str, connected: bool) -> None:
            self._connected = connected
            # The dispatcher may invoke this callback on a worker thread;
            # always write the state from the event loop.
            self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CONNECTION_STATE, _update)
        )
