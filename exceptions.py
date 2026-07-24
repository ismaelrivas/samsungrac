# pylint: disable=import-outside-toplevel,too-few-public-methods
"""Exceptions for the Climate IP integration."""

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

    translation_domain = DOMAIN
    translation_key = "cannot_connect"


# pylint: disable=import-outside-toplevel,too-few-public-methods


class RetryNextAttempt(HomeAssistantError):
    """Raised to yield the executor thread back to the async loop during retries."""


class InvalidHeaderError(CannotConnect):
    """Error to indicate the device sent malformed HTTP headers."""

    translation_domain = DOMAIN
    translation_key = "invalid_response"


class AuthError(HomeAssistantError):
    """Error to indicate there is an authentication problem."""

    translation_domain = DOMAIN
    translation_key = "invalid_auth"


class CertNotFound(HomeAssistantError):
    """Error to indicate the certificate file is missing."""

    translation_domain = DOMAIN
    translation_key = "cert_not_found"


class TokenAcquisitionError(HomeAssistantError):
    """Base custom exception for token acquisition errors."""

    translation_domain = DOMAIN
    translation_key = "token_acquisition_failed"


class AuthTurnedOffError(TokenAcquisitionError):
    """Raised when authentication fails because the device was turned off (ErrorCode 301)."""

    translation_domain = DOMAIN
    translation_key = "auth_failed_turned_off"
