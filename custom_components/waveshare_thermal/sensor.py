"""Sensor platform for Waveshare Thermal Camera."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from config entry."""
    name = entry.data.get(CONF_NAME) or entry.title
    unique_id = entry.entry_id

    # Get the camera entity to access temperature data
    camera_entity = None
    if DOMAIN in hass.data and "entities" in hass.data[DOMAIN]:
        camera_entity = hass.data[DOMAIN]["entities"].get(unique_id)

    if camera_entity is None:
        _LOGGER.warning("Could not find camera entity for thermal sensors")

    async_add_entities(
        [
            ThermalCameraMinTempSensor(hass, name, unique_id, camera_entity),
            ThermalCameraMaxTempSensor(hass, name, unique_id, camera_entity),
        ]
    )


class ThermalCameraMinTempSensor(SensorEntity):
    """Representation of minimum temperature from thermal camera."""

    def __init__(self, hass, name, unique_id, camera_entity):
        """Initialize the sensor."""
        self.hass = hass
        self._name = name
        self._attr_unique_id = f"{unique_id}_min_temp"
        self._camera_entity = camera_entity
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._name} Min Temperature"

    @property
    def native_value(self):
        """Return the current minimum temperature."""
        if self._camera_entity and hasattr(self._camera_entity, "get_min_temp"):
            return self._camera_entity.get_min_temp()
        return None

    @property
    def icon(self):
        """Return the icon."""
        return "mdi:thermometer-low"


class ThermalCameraMaxTempSensor(SensorEntity):
    """Representation of maximum temperature from thermal camera."""

    def __init__(self, hass, name, unique_id, camera_entity):
        """Initialize the sensor."""
        self.hass = hass
        self._name = name
        self._attr_unique_id = f"{unique_id}_max_temp"
        self._camera_entity = camera_entity
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._name} Max Temperature"

    @property
    def native_value(self):
        """Return the current maximum temperature."""
        if self._camera_entity and hasattr(self._camera_entity, "get_max_temp"):
            return self._camera_entity.get_max_temp()
        return None

    @property
    def icon(self):
        """Return the icon."""
        return "mdi:thermometer-high"
