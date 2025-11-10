"""Exceptions for the Climate IP integration."""
from homeassistant.exceptions import HomeAssistantError

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class AuthError(HomeAssistantError):
    """Error to indicate there is an authentication problem."""

class CertNotFound(HomeAssistantError):
    """Error to indicate the certificate file is missing."""