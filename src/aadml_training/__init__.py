"""AADML Training's Python SDK: call your trained photo and chat models from your own code.

    from aadml_training import Client

    client = Client(api_key="...")
    result = client.predict(project_id=22, image="room.jpg")
"""
from ._version import __version__
from .client import DEFAULT_API_URL, Client
from .edge import EdgeModel
from .errors import (AADMLError, APIError, AuthenticationError, BadRequestError, ConfigurationError, ConnectionError,
                     ModelUnavailableError, NotFoundError, PayloadTooLargeError, PermissionDeniedError, RateLimitError,
                     ServerError)

__all__ = ["Client", "EdgeModel", "DEFAULT_API_URL", "__version__", "AADMLError", "APIError", "AuthenticationError",
           "BadRequestError", "ConfigurationError", "ConnectionError", "ModelUnavailableError", "NotFoundError",
           "PayloadTooLargeError", "PermissionDeniedError", "RateLimitError", "ServerError"]
