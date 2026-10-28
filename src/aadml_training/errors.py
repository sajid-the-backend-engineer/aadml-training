"""The errors the client raises. Every one is an ``AADMLError``; an answer from AADML that is not a success is an
``APIError`` (or one of its kinds) with the HTTP status and AADML's own message."""
from typing import Optional


class AADMLError(Exception):
    """Anything that went wrong in this SDK."""


class ConfigurationError(AADMLError):
    """The client cannot be used as it was set up: no API key, or an address that is not http(s)."""


class ConnectionError(AADMLError):  # noqa: A001 - the SDK's own name, imported from this package
    """AADML could not be reached: no answer came back."""


class APIError(AADMLError):
    """AADML answered with an error.

    ``status_code`` is the HTTP status, ``message`` AADML's explanation, ``field`` the request field it is about
    (when there is one) and ``retry_after`` the seconds AADML asked to wait before trying again (when it said)."""

    def __init__(self, message: str, status_code: int, field: Optional[str] = None,
                 retry_after: Optional[float] = None, body: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field
        self.retry_after = retry_after
        self.body = body or {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code}, message={self.message!r}, field={self.field!r})"

    def __str__(self) -> str:
        where = f" (field: {self.field})" if self.field else ""
        return f"{self.status_code}: {self.message}{where}"


class BadRequestError(APIError):
    """400: the request itself was refused, for example a photo that is not a JPEG, PNG or WebP."""


class AuthenticationError(APIError):
    """401: the API key is missing, unknown or revoked."""


class PermissionDeniedError(APIError):
    """403: the key is valid but has no access to that project and environment."""


class NotFoundError(APIError):
    """404: there is no such project or environment."""


class PayloadTooLargeError(APIError):
    """413: the photo is larger than AADML accepts."""


class RateLimitError(APIError):
    """429: too many requests for this key. ``retry_after`` says how long to wait."""


class ModelUnavailableError(APIError):
    """503: no model is deployed to that environment yet, or it is starting. ``retry_after`` says when to try again."""


class ServerError(APIError):
    """5xx: AADML or the model failed to answer."""


_BY_STATUS = {400: BadRequestError, 401: AuthenticationError, 403: PermissionDeniedError, 404: NotFoundError,
              413: PayloadTooLargeError, 429: RateLimitError, 503: ModelUnavailableError}


def error_for(status_code: int) -> type:
    """The APIError kind of an HTTP status."""
    if status_code in _BY_STATUS:
        return _BY_STATUS[status_code]
    return ServerError if status_code >= 500 else APIError
