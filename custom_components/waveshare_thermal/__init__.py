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
    # Clean up stored entity references
    if DOMAIN in hass.data and "entities" in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entities"].pop(entry.entry_id, None)

    return await hass.config_entries.async_unload_platforms(entry, [Platform.CAMERA, Platform.SENSOR])


async def _async_options_updated(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
    """Handle options update by reloading the integration entry."""
    await hass.config_entries.async_reload(entry.entry_id)
