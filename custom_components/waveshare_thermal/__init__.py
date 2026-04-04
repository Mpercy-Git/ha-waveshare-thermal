"""The Waveshare Thermal Camera integration."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
import homeassistant.helpers.config_validation as cv

from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Waveshare Thermal Camera component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Set up from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entities", {})
    
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.CAMERA, Platform.SENSOR])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Unload a config entry."""
    # Clean up stored entity references
    if DOMAIN in hass.data and "entities" in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entities"].pop(entry.entry_id, None)
    
    return await hass.config_entries.async_unload_platforms(entry, [Platform.CAMERA, Platform.SENSOR])

