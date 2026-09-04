"""Sensor platform for Waveshare Thermal Camera."""
import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from config entry."""
    name = entry.options.get(CONF_NAME, entry.data.get(CONF_NAME) or entry.title)
    unique_id = entry.entry_id

    # The camera entity is resolved lazily by each sensor: the camera and
    # sensor platforms are set up concurrently, so it may not exist yet.
    async_add_entities(
        [
            ThermalCameraMinTempSensor(name, unique_id),
            ThermalCameraMaxTempSensor(name, unique_id),
        ]
    )


class ThermalCameraMinTempSensor(SensorEntity):
    """Representation of minimum temperature from thermal camera."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, name, unique_id):
        """Initialize the sensor."""
        self._attr_name = f"{name} Min Temperature"
        self._attr_unique_id = f"{unique_id}_min_temp"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._entry_id = unique_id

    @property
    def _camera_entity(self):
        """Get camera entity dynamically from hass.data."""
        if DOMAIN in self.hass.data and "entities" in self.hass.data[DOMAIN]:
            return self.hass.data[DOMAIN]["entities"].get(self._entry_id)
        return None

    @property
    def native_value(self):
        """Return the current minimum temperature."""
        camera = self._camera_entity
        if camera and hasattr(camera, "get_min_temp"):
            return camera.get_min_temp()
        return None

    @property
    def icon(self):
        """Return the icon."""
        return "mdi:thermometer-low"


class ThermalCameraMaxTempSensor(SensorEntity):
    """Representation of maximum temperature from thermal camera."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, name, unique_id):
        """Initialize the sensor."""
        self._attr_name = f"{name} Max Temperature"
        self._attr_unique_id = f"{unique_id}_max_temp"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._entry_id = unique_id

    @property
    def _camera_entity(self):
        """Get camera entity dynamically from hass.data."""
        if DOMAIN in self.hass.data and "entities" in self.hass.data[DOMAIN]:
            return self.hass.data[DOMAIN]["entities"].get(self._entry_id)
        return None

    @property
    def native_value(self):
        """Return the current maximum temperature."""
        camera = self._camera_entity
        if camera and hasattr(camera, "get_max_temp"):
            return camera.get_max_temp()
        return None

    @property
    def icon(self):
        """Return the icon."""
        return "mdi:thermometer-high"
