"""The Waveshare Thermal Camera integration."""
import logging

from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Set up from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entities", {})

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.CAMERA, Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform.CAMERA, Platform.SENSOR]
    )

    # Only drop the stored entity references once the platforms are really
    # gone; a failed unload leaves the entities in place and still in use.
    if unload_ok:
        entities = hass.data.get(DOMAIN, {}).get("entities")
        if entities is not None:
            entities.pop(entry.entry_id, None)
            if not entities:
                hass.data.pop(DOMAIN, None)

    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
    """Handle options update by reloading the integration entry."""
    await hass.config_entries.async_reload(entry.entry_id)
