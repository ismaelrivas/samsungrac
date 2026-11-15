# pylint: disable=import-outside-toplevel,too-few-public-methods
"""Exceptions for the Climate IP integration."""

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class ClimateIPHomeAssistantError(HomeAssistantError):
    """Base exception for Climate IP that preserves class-level translation metadata."""

    translation_domain: str | None = DOMAIN
    translation_key: str | None = None

    def __init__(
        self,
        *args: object,
        translation_domain: str | None = None,
        translation_key: str | None = None,
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        """Initialize exception while preserving class-level translation attributes."""
        # HomeAssistantError.__init__ resets translation attributes to None unless passed.
        resolved_domain = (
            self.translation_domain
            if translation_domain is None
            else translation_domain
        )
        resolved_key = (
            self.translation_key if translation_key is None else translation_key
        )
        super().__init__(
            *args,
            translation_domain=resolved_domain,
            translation_key=resolved_key,
            translation_placeholders=translation_placeholders,
        )


class CannotConnect(ClimateIPHomeAssistantError):
    """Error to indicate we cannot connect."""

    translation_domain = DOMAIN
    translation_key = "cannot_connect"


# pylint: disable=import-outside-toplevel,too-few-public-methods


class RetryNextAttempt(ClimateIPHomeAssistantError):
    """Raised to yield the executor thread back to the async loop during retries."""


class InvalidHeaderError(CannotConnect):
    """Error to indicate the device sent malformed HTTP headers."""

    translation_domain = DOMAIN
    translation_key = "invalid_response"


class AuthError(ClimateIPHomeAssistantError):
    """Error to indicate there is an authentication problem."""

    translation_domain = DOMAIN
    translation_key = "invalid_auth"


class CertNotFound(ClimateIPHomeAssistantError):
    """Error to indicate the certificate file is missing."""

    translation_domain = DOMAIN
    translation_key = "cert_not_found"


class TokenAcquisitionError(ClimateIPHomeAssistantError):
    """Base custom exception for token acquisition errors."""

    translation_domain = DOMAIN
    translation_key = "token_acquisition_failed"


class AuthTurnedOffError(TokenAcquisitionError):
    """Raised when authentication fails because the device was turned off (ErrorCode 301)."""

    translation_domain = DOMAIN
    translation_key = "auth_failed_turned_off"
