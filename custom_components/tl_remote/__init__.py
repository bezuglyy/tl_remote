"""TL Remote integration.

Links two Home Assistant instances:
- the remote node (source) exposes a user-selected list of entities
- the main instance mirrors exactly those entities
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import slugify

from .const import (
    ALLOWED_REFRESH_SECONDS,
    CONF_ACCESS_TOKEN,
    CONF_ENTITY_PREFIX,
    CONF_HOST,
    CONF_PORT,
    CONF_SECURE,
    CONF_VERIFY_SSL,
    DEFAULT_MAX_MSG_SIZE,
    DISCOVERY_URL,
    DOMAIN,
    REMOTE_ID,
    SIGNAL_CONNECTION_STATE,
)
from .views import DiscoveryInfoView

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TL Remote from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if entry.unique_id == REMOTE_ID:
        # Remote node: expose the discovery endpoint only.
        if not hass.data[DOMAIN].get("view_registered"):
            hass.http.register_view(DiscoveryInfoView())
            hass.data[DOMAIN]["view_registered"] = True
        return True

    # Main instance: create the remote connection.
    connection = RemoteConnection(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = connection

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_update_listener))
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, connection.async_stop)
    )

    hass.loop.create_task(connection.async_connect())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.unique_id == REMOTE_ID:
        return True

    connection: RemoteConnection = hass.data[DOMAIN].pop(entry.entry_id)
    await connection.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Remove mirrored entities that were created by us.
    registry = er.async_get(hass)
    for entity_id in list(connection._entities):
        reg_entry = registry.async_get(entity_id)
        if reg_entry and reg_entry.platform == DOMAIN:
            registry.async_remove(entity_id)
        hass.states.async_remove(entity_id)
    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    if entry.unique_id == REMOTE_ID:
        return
    connection: RemoteConnection = hass.data[DOMAIN].get(entry.entry_id)
    if connection:
        await connection.async_update_options(entry)


class RemoteConnection:
    """WebSocket connection to the remote TL Remote node."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the connection."""
        self._hass = hass
        self._entry = entry
        self._secure = bool(entry.data.get(CONF_SECURE, False))
        self._verify_ssl = bool(entry.data.get(CONF_VERIFY_SSL, False))
        self._access_token = entry.data.get(CONF_ACCESS_TOKEN, "")
        self._host = entry.data[CONF_HOST]
        self._port = entry.data.get(CONF_PORT, 8123)
        self._prefix = (entry.options.get(CONF_ENTITY_PREFIX) or "").strip()

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ws_id_counter = 0
        self._running = True
        self._reconnect_delay = 5
        self._allowed: set[str] = set()
        self._last_allowed_fetch = 0.0
        self._entities: set[str] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    @property
    def host(self) -> str:
        """Return remote host."""
        return self._host

    @property
    def port(self) -> int:
        """Return remote port."""
        return self._port

    @property
    def is_connected(self) -> bool:
        """Return True if the WebSocket is connected."""
        return self._ws is not None and not self._ws.closed

    def _ws_url(self) -> str:
        return f"{'wss' if self._secure else 'ws'}://{self._host}:{self._port}/api/websocket"

    def _discovery_url(self) -> str:
        return DISCOVERY_URL.format(
            proto="https" if self._secure else "http",
            host=self._host,
            port=self._port,
        )

    async def async_stop(self, _event: Event | None = None) -> None:
        """Stop the connection."""
        self._running = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        self._report_state(False)

    async def async_update_options(self, entry: ConfigEntry) -> None:
        """Apply new options (prefix change) without full reconnect."""
        self._prefix = (entry.options.get(CONF_ENTITY_PREFIX) or "").strip()
        _LOGGER.debug("Options updated, prefix=%s", self._prefix)

    # ------------------------------------------------------------------ #
    # connection loop
    # ------------------------------------------------------------------ #
    async def async_connect(self) -> None:
        """Connect to the remote node, reconnecting as needed."""
        while self._running:
            try:
                await self._connect_once()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("TL Remote connection error: %s", err)
            finally:
                self._report_state(False)
            if not self._running:
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 1.5, 60)

    async def _connect_once(self) -> None:
        """Perform a single connect + message loop iteration."""
        self._session = async_get_clientsession(self._hass, self._verify_ssl)
        self._reconnect_delay = 5

        # Refresh allowed list before connecting.
        await self._refresh_allowed()

        ws = await self._session.ws_connect(
            self._ws_url(),
            max_msg_size=DEFAULT_MAX_MSG_SIZE,
            heartbeat=55,
        )
        self._ws = ws
        self._report_state(True)

        msg = await ws.receive_json()
        if msg.get("type") != "auth_required":
            raise ConnectionError(f"Unexpected ws greeting: {msg}")
        await ws.send_json({"type": "auth", "access_token": self._access_token})
        msg = await ws.receive_json()
        if msg.get("type") != "auth_ok":
            raise PermissionError(f"Auth failed: {msg}")

        await ws.send_json(
            {
                "id": self._next_ws_id(),
                "type": "subscribe_events",
                "event_type": "state_changed",
            }
        )
        await ws.send_json({"id": self._next_ws_id(), "type": "get_states"})

        _LOGGER.info(
            "TL Remote connected to %s:%s (%s)", self._host, self._port, self._allowed
        )

        # Background task that keeps the allowed list fresh.
        refresh_task = asyncio.create_task(self._allowed_refresh_loop(ws))

        try:
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(message.json(), ws)
                elif message.type == aiohttp.WSMsgType.CLOSED:
                    break
                elif message.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresh_task
            with contextlib.suppress(Exception):
                await ws.close()
            self._ws = None
            self._remove_missing_entities(set())

    # ------------------------------------------------------------------ #
    # message handling
    # ------------------------------------------------------------------ #
    async def _handle_message(
        self, message: dict, ws: aiohttp.ClientWebSocketResponse
    ) -> None:
        """Handle one incoming WS message."""
        if (
            message.get("type") == "event"
            and message.get("event", {}).get("event_type") == "state_changed"
        ):
            data = message["event"].get("data") or {}
            entity_id = data.get("entity_id")
            if not entity_id:
                return
            new_state = data.get("new_state")
            if new_state is None:
                self._remove_entity(entity_id)
            else:
                self._process_state(
                    entity_id, new_state.get("state"), new_state.get("attributes") or {}
                )
        elif message.get("type") == "result":
            # get_states result
            if isinstance(message.get("result"), list):
                for item in message["result"]:
                    self._process_state(
                        item.get("entity_id"),
                        item.get("state"),
                        item.get("attributes") or {},
                    )

    @callback
    def _process_state(self, entity_id: str, state: Any, attr: dict) -> None:
        """Mirror one entity if it is allowed."""
        if entity_id not in self._allowed:
            return

        domain, object_id = entity_id.split(".", 1)
        object_id = self._prefixed_object_id(entity_id)

        if self._prefix:
            attr = dict(attr)
            friendly = attr.get("friendly_name")
            if friendly:
                attr["friendly_name"] = f"{self._prefix}{friendly}"

        registry = er.async_get(self._hass)
        # HA 2026.3+ renamed the keyword: config_entry_id -> config_entry
        reg_entry = self._async_registry_get_or_create(
            registry, domain, object_id, entity_id
        )
        # Use the entity id assigned by the registry to keep states and
        # registry consistent (avoids "_2" style mismatches).
        assigned = reg_entry.entity_id or self._prefixed_entity_id(entity_id)
        self._entities.add(assigned)
        self._hass.states.async_set(assigned, state, attr)

    def _async_registry_get_or_create(
        self, registry: er.EntityRegistry, domain: str, object_id: str, entity_id: str
    ):
        """Call registry.async_get_or_create with the right kwarg for this HA."""
        kwargs = {
            "domain": domain,
            "platform": DOMAIN,
            "unique_id": self._unique_id_for(entity_id),
            "suggested_object_id": object_id,
        }
        params = er.EntityRegistry.async_get_or_create.__code__.co_varnames
        if "config_entry" in params:
            kwargs["config_entry"] = self._entry
        else:
            kwargs["config_entry_id"] = self._entry.entry_id
        return registry.async_get_or_create(**kwargs)

    @callback
    def _remove_entity(self, entity_id: str) -> None:
        """Remove one mirrored entity."""
        local_id = self._prefixed_entity_id(entity_id)
        if local_id in self._entities:
            self._entities.discard(local_id)
            self._remove_registry_entity(local_id)
            self._hass.states.async_remove(local_id)

    @callback
    def _remove_missing_entities(self, still_valid: set[str]) -> None:
        """Remove mirrored entities that are no longer allowed."""
        valid_local = {self._prefixed_entity_id(e) for e in still_valid}
        for entity_id in list(self._entities):
            if entity_id not in valid_local:
                self._entities.discard(entity_id)
                self._remove_registry_entity(entity_id)
                self._hass.states.async_remove(entity_id)

    def _remove_registry_entity(self, entity_id: str) -> None:
        with contextlib.suppress(Exception):
            registry = er.async_get(self._hass)
            reg_entry = registry.async_get(entity_id)
            if reg_entry and reg_entry.platform == DOMAIN:
                registry.async_remove(entity_id)

    # ------------------------------------------------------------------ #
    # allowed list
    # ------------------------------------------------------------------ #
    async def _allowed_refresh_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Periodically refresh the allowed entity list and re-sync states."""
        while self._running and not ws.closed:
            try:
                await asyncio.sleep(ALLOWED_REFRESH_SECONDS)
                old = self._allowed
                await self._refresh_allowed()
                # Keep the connection sensor in sync even if a dispatcher
                # signal was missed during startup races.
                self._report_state(self.is_connected)
                if old != self._allowed:
                    _LOGGER.info(
                        "Allowed entity list changed on remote: %d -> %d entities",
                        len(old),
                        len(self._allowed),
                    )
                    self._remove_missing_entities(self._allowed)
                # Re-request all states so newly allowed entities appear
                # (and disallowed ones are dropped) without waiting for a
                # state_changed event from the remote.
                await ws.send_json({"id": self._next_ws_id(), "type": "get_states"})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Allowed list refresh failed", exc_info=True)

    async def _refresh_allowed(self) -> None:
        """Fetch the allowed entity list from the remote discovery endpoint."""
        if not self._session:
            self._session = async_get_clientsession(self._hass, self._verify_ssl)
        try:
            headers = {
                "Authorization": "Bearer " + self._access_token,
                "Content-Type": "application/json",
            }
            async with self._session.get(
                self._discovery_url(), headers=headers, timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    allowed = data.get("allowed_entities") or []
                    self._allowed = {str(e).lower() for e in allowed}
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch allowed entities: %s", err)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _next_ws_id(self) -> int:
        self._ws_id_counter += 1
        return self._ws_id_counter

    def _prefixed_object_id(self, entity_id: str) -> str:
        """Return the (prefixed) object id for a remote entity id."""
        _domain, object_id = entity_id.split(".", 1)
        if self._prefix:
            return f"{slugify(self._prefix)}_{object_id}"
        return object_id

    def _prefixed_entity_id(self, entity_id: str) -> str:
        if not self._prefix:
            return entity_id
        domain, object_id = entity_id.split(".", 1)
        return f"{domain}.{slugify(self._prefix)}_{object_id}"

    def _unique_id_for(self, entity_id: str) -> str:
        """Stable unique id. Includes the prefix so entity ids stay clean
        when a prefix is configured."""
        return f"{self._entry.unique_id}_{self._prefixed_object_id(entity_id)}"

    def _report_state(self, connected: bool) -> None:
        """Report the connection state (safe from any thread)."""
        self._hass.loop.call_soon_threadsafe(
            async_dispatcher_send,
            self._hass,
            SIGNAL_CONNECTION_STATE,
            self._entry.entry_id,
            connected,
        )
