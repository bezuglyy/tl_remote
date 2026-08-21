"""Constants for TL Remote."""

DOMAIN = "tl_remote"

# Config flow type
CONF_TYPE = "type"
CONF_REMOTE = "remote"  # this instance exposes devices (source)
CONF_MAIN = "main"  # this instance connects to a remote source

# Connection details (main side)
CONF_HOST = "host"
CONF_PORT = "port"
CONF_ACCESS_TOKEN = "access_token"
CONF_SECURE = "secure"
CONF_VERIFY_SSL = "verify_ssl"
CONF_ENTITY_PREFIX = "entity_prefix"

# Remote node option: which entities to expose
CONF_EXPOSED_ENTITIES = "exposed_entities"

# Defaults
DEFAULT_PORT = 8123
DEFAULT_MAX_MSG_SIZE = 16 * 1024 * 1024

# Remote node unique id
REMOTE_ID = "remote"

# Discovery endpoint on the remote node
DISCOVERY_URL = "{proto}://{host}:{port}/api/tl_remote/discovery"

# How often the main instance re-fetches the allowed entity list
ALLOWED_REFRESH_SECONDS = 30

# Dispatcher signal for connection state changes (main side)
SIGNAL_CONNECTION_STATE = "tl_remote_connection_state"
