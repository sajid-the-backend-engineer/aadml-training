"""A model AADML runs on one of your own machines (Deployments, "Edge Devices"), called on your own network.

    from aadml_training import EdgeModel

    model = EdgeModel("http://192.168.1.20:8080")       # the machine's address and the port you chose
    walls = model.predict("room.jpg")
    model.ping()                                         # True once the model answers

The machine answers on your network only: no AADML key is sent, the photo goes straight to the machine and never
reaches AADML. The answer is the same as ``Client.predict``'s (fmw-predict.v1), without the fields only AADML's own
gateway adds.
"""
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx

from . import errors
from ._version import __version__
from .images import ImageInput, load


class EdgeModel:
    """One model on one of your machines, at ``url`` (``http://<address>:<port>``)."""

    def __init__(self, url: str, *, timeout: float = 60.0, http_client: Optional[httpx.Client] = None):
        parts = urlsplit(str(url or '').strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise errors.ConfigurationError(f"url is the machine's address, e.g. http://192.168.1.20:8080 (got {url!r}).")
        if parts.path.strip("/") or parts.query or parts.fragment or parts.username or parts.password:
            raise errors.ConfigurationError("url is only the machine's address and port, e.g. http://192.168.1.20:8080.")
        self.url = f"{parts.scheme}://{parts.netloc}"
        self.timeout = timeout
        self._http = http_client or httpx.Client(timeout=timeout)
        self._owns_http = http_client is None

    def __repr__(self) -> str:
        return f"EdgeModel({self.url!r})"

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "EdgeModel":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def predict(self, image: ImageInput) -> Dict[str, Any]:
        """Send one photo (a path, bytes, an open binary file, a URL or a Pillow image: JPEG, PNG or WebP) and return
        what the model found. The photo itself is the request body, as the machine's server takes it."""
        data, content_type, _name = load(image, timeout=self.timeout)
        answer = self._send("POST", "/invocations", content=data, headers={"Content-Type": content_type})
        return answer.json()

    def ping(self) -> bool:
        """True when the model answers its health check."""
        try:
            return self._send("GET", "/ping").json().get("status") == "ok"
        except errors.APIError:
            return False

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"User-Agent": f"aadml-training-python/{__version__}", "Accept": "application/json",
                   **kwargs.pop("headers", {})}
        try:
            answer = self._http.request(method, self.url + path, headers=headers, timeout=self.timeout, **kwargs)
        except httpx.ConnectError as failure:
            raise errors.ConnectionError(f"Could not reach the machine at {self.url}: {failure}") from None
        except httpx.TimeoutException:
            raise errors.ConnectionError(f"No answer from the machine at {self.url} within {self.timeout} seconds.") from None
        if answer.status_code < 400:
            return answer
        try:
            body = answer.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        retry = answer.headers.get("Retry-After")
        try:
            retry_after = float(retry) if retry else None
        except ValueError:
            retry_after = None
        kind = errors.BadRequestError if answer.status_code == 415 else errors.error_for(answer.status_code)
        raise kind(str(body.get("error") or f"The machine answered {answer.status_code}."), answer.status_code,
                   field=body.get("field"), retry_after=retry_after, body=body)
