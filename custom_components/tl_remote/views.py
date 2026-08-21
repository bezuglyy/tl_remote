"""Discovery view for TL Remote (runs on the remote node)."""

from __future__ import annotations

import homeassistant
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.instance_id import async_get as async_get_instance_id
from homeassistant.helpers.system_info import async_get_system_info

from .const import CONF_EXPOSED_ENTITIES, DOMAIN, REMOTE_ID


class DiscoveryInfoView(HomeAssistantView):
    """Expose remote node info + the allowed entity list."""

    url = "/api/tl_remote/discovery"
    name = "api:tl_remote:discovery"

    async def get(self, request):
        """Return discovery info."""
        hass = request.app["hass"]
        system_info = await async_get_system_info(hass)
        allowed = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == REMOTE_ID:
                allowed = entry.options.get(CONF_EXPOSED_ENTITIES, [])
                break
        return self.json(
            {
                "uuid": await async_get_instance_id(hass),
                "location_name": hass.config.location_name,
                "ha_version": homeassistant.const.__version__,
                "installation_type": system_info["installation_type"],
                "allowed_entities": allowed,
            }
        )
