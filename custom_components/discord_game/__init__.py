"""Component to integrate with Discord and get information about users online and game status."""
import warnings

# Older nextcord builds used 'return' in 'finally' blocks. Python 3.14 emits
# that as a SyntaxWarning during import, before normal logging can classify it.
warnings.filterwarnings(
    "ignore",
    message=r"'return' in a 'finally' block",
    category=SyntaxWarning,
)

from homeassistant import config_entries, core
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, DATA_HASS_CONFIG

PLATFORMS = [Platform.SENSOR, Platform.MEDIA_PLAYER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(
        hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        **entry.data,
        "unsub_options_update_listener": entry.add_update_listener(async_options_updated),
    }

    # Sensor must be set up first so watchers are stored in hass.data
    # before the media_player platform reads them.
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.MEDIA_PLAYER])

    return True


async def async_unload_entry(
        hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Remove config entry from domain.
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        # Remove options_update_listener.
        unsub_options_update_listener = entry_data.get("unsub_options_update_listener")
        if unsub_options_update_listener:
            unsub_options_update_listener()

    return unload_ok


async def async_setup(hass: core.HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DATA_HASS_CONFIG] = config
    return True


async def async_options_updated(
        hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
