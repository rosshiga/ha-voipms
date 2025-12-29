"""Config flow for VoIP.ms SMS integration."""
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("account_user"): str,
        vol.Required("api_password"): str,  # Password field - will be masked by HA UI
        vol.Required("did"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    # Basic validation - check that required fields are present
    if not data.get("account_user") or not data.get("api_password") or not data.get("did"):
        raise InvalidAuth("Missing required configuration fields")
    
    # TODO: Could add API validation here by making a test API call
    # For now, we'll just validate the format
    
    # Validate DID is numeric and reasonable length (10 digits typically)
    did = data["did"].strip()
    if not did.isdigit() or len(did) < 10:
        raise InvalidAuth("DID must be a numeric phone number (at least 10 digits)")
    
    return {"title": f"VoIP.ms SMS ({did})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VoIP.ms SMS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check if this DID is already configured
                await self.async_set_unique_id(user_input["did"])
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

