"""Config flow for Waveshare Thermal Camera integration."""
import logging
import socket
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)

async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input allows us to connect."""
    # Test connection
    try:
        # We run this in a thread because socket is blocking
        def try_connect():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((data[CONF_HOST], data[CONF_PORT]))

        await hass.async_add_executor_job(try_connect)
    except Exception as e:
        _LOGGER.error("Connection failed: %s", e)
        raise ConnectionError
    
    return {"title": data[CONF_NAME]}


class WaveshareThermalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Waveshare Thermal Camera."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return WaveshareThermalOptionsFlow(config_entry)


class WaveshareThermalOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Waveshare Thermal Camera."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Manage the integration options."""
        errors = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
                return self.async_create_entry(title="", data=user_input)
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception in options flow")
                errors["base"] = "unknown"

        current_host = self._config_entry.options.get(CONF_HOST, self._config_entry.data.get(CONF_HOST, ""))
        current_port = self._config_entry.options.get(CONF_PORT, self._config_entry.data.get(CONF_PORT, DEFAULT_PORT))
        current_name = self._config_entry.options.get(CONF_NAME, self._config_entry.data.get(CONF_NAME, DEFAULT_NAME))

        options_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=current_host): str,
                vol.Optional(CONF_PORT, default=current_port): int,
                vol.Optional(CONF_NAME, default=current_name): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema, errors=errors)
