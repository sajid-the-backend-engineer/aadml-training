"""The client: one object that holds AADML's address and your API key, with one method per thing you can ask.

    from aadml_training import Client

    client = Client(api_key="...")                       # or set AADML_API_KEY
    walls = client.predict(project_id=22, image="room.jpg")
    reply = client.chat(project_id=31, messages=[{"role": "user", "content": "How do I return an order?"}])

The key is an app key made on the project's Deploy page (Connected apps); it is sent as ``Authorization: Bearer``
and never written to a log or a repr.
"""
import json
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

import httpx

from . import errors
from ._version import __version__
from .images import ImageInput, load

DEFAULT_API_URL = "https://aadml.com"
ENVIRONMENTS = ("staging", "production")
_MAX_WAIT = 30.0


class Client:
    """AADML Training's API.

    ``api_key``: an app key from the project's Deploy page; ``AADML_API_KEY`` when not given.
    ``api_url``: AADML's address; ``AADML_API_URL`` or https://aadml.com when not given.
    ``timeout``: seconds to wait for one answer. ``max_retries``: how many times a request that AADML refused
    without processing it (429 too many requests, 503 model not ready) or that never reached AADML is sent again,
    waiting as AADML asks (at most 30 seconds each time)."""

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None, *, timeout: float = 60.0,
                 max_retries: int = 2, http_client: Optional[httpx.Client] = None):
        key = api_key if api_key is not None else os.environ.get("AADML_API_KEY", "")
        if not key or not key.strip():
            raise errors.ConfigurationError("No API key: pass api_key=... or set AADML_API_KEY.")
        url = (api_url or os.environ.get("AADML_API_URL") or DEFAULT_API_URL).rstrip("/")
        if not url.startswith(("https://", "http://")):
            raise errors.ConfigurationError(f"api_url must start with https:// (got {url!r}).")
        self.api_url = url
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.__key = key.strip()
        self._http = http_client or httpx.Client(timeout=timeout)
        self._owns_http = http_client is None

    def __repr__(self) -> str:
        return f"Client(api_url={self.api_url!r}, api_key='{self.__key[:4]}…')"

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── photo models ─────────────────────────────────────────────────────────────────────────────────────────────
    def predict(self, project_id: int, image: ImageInput, *, environment: str = "production",
                request_id: Optional[str] = None, capture_id: Optional[str] = None) -> Dict[str, Any]:
        """Send one photo to the model deployed in a project's ``environment`` and return what it found: ``walls``
        (each with its corners), ``openings`` (windows and doors), in the photo's own pixels, with ``model``,
        ``request_id``, ``warnings`` and ``timing_ms``.

        ``image``: a file path, bytes, an open binary file, a URL or a Pillow image (JPEG, PNG or WebP, at most 15 MB).
        ``request_id`` / ``capture_id``: your own ids (at most 128 characters), returned in the answer."""
        data, content_type, name = load(image, timeout=self.timeout)
        payload = {key: value for key, value in (("request_id", request_id), ("capture_id", capture_id)) if value}
        form = {"payload": json.dumps(payload)} if payload else None
        return self._send("POST", self._project_path(project_id, environment, "predict/"),
                          files={"file": (name, data, content_type)}, data=form).json()

    def run(self, model: str, image: ImageInput) -> Dict[str, Any]:
        """Send one photo to one of AADML's ready-to-use models (the Models page, "Use model"), named by its key, for
        example ``"segformer-b0"``. Calls open when AADML's per-call charging is connected; until then AADML answers
        503 and this raises ``ModelUnavailableError`` with the reason."""
        if not isinstance(model, str) or not model or not all(c.isalnum() or c == "-" for c in model):
            raise errors.ConfigurationError(f"model is a ready-to-use model's key, such as 'segformer-b0' (got {model!r}).")
        data, content_type, name = load(image, timeout=self.timeout)
        return self._send("POST", f"/api/training-data/v1/models/{model.lower()}/predict",
                          files={"file": (name, data, content_type)}).json()

    # ── chat models ──────────────────────────────────────────────────────────────────────────────────────────────
    def chat(self, project_id: int, messages: List[Dict[str, Any]], *, environment: str = "production",
             **options: Any) -> Dict[str, Any]:
        """Ask a project's deployed chat model, in OpenAI's chat completions format; returns the completion
        (``answer["choices"][0]["message"]["content"]`` is the reply). ``options`` go into the request as they are
        (``max_tokens``, ``temperature``, …)."""
        body = {"messages": messages, **options, "stream": False}
        return self._send("POST", self._project_path(project_id, environment, "v1/chat/completions"), json=body).json()

    def chat_text(self, project_id: int, messages: List[Dict[str, Any]], **kwargs: Any) -> str:
        """``chat``, returning only the reply's text."""
        answer = self.chat(project_id, messages, **kwargs)
        return (answer.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    def chat_stream(self, project_id: int, messages: List[Dict[str, Any]], *, environment: str = "production",
                    **options: Any) -> Iterator[str]:
        """``chat``, yielding the reply's text piece by piece as the model writes it."""
        body = {"messages": messages, **options, "stream": True}
        path = self._project_path(project_id, environment, "v1/chat/completions")
        with self._stream("POST", path, json=body) as answer:
            for line in answer.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if chunk.get("error"):
                    raise errors.ServerError(str(chunk["error"].get("message") or chunk["error"]), 502, body=chunk)
                for choice in chunk.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece

    def models(self, project_id: int, *, environment: str = "production") -> List[Dict[str, Any]]:
        """The chat models a project's ``environment`` answers with (OpenAI's model list)."""
        return self._send("GET", self._project_path(project_id, environment, "v1/models")).json().get("data", [])

    # ── plumbing ─────────────────────────────────────────────────────────────────────────────────────────────────
    def _project_path(self, project_id: int, environment: str, rest: str) -> str:
        if environment not in ENVIRONMENTS:
            raise errors.ConfigurationError(f"environment must be one of {', '.join(ENVIRONMENTS)} (got {environment!r}).")
        if isinstance(project_id, bool) or not str(project_id).isdigit():
            raise errors.ConfigurationError(f"project_id is the project's number (got {project_id!r}).")
        return f"/api/training-data/v1/projects/{int(project_id)}/environments/{environment}/{rest}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.__key}", "User-Agent": f"aadml-training-python/{__version__}",
                "Accept": "application/json"}

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            try:
                answer = self._http.request(method, self.api_url + path, headers=self._headers(), timeout=self.timeout,
                                            **kwargs)
            except httpx.ConnectError as failure:                          # never reached AADML: safe to send again
                if attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2 ** attempt, _MAX_WAIT))
                    continue
                raise errors.ConnectionError(f"Could not reach {self.api_url}: {failure}") from None
            except httpx.TimeoutException:
                raise errors.ConnectionError(f"No answer from {self.api_url} within {self.timeout} seconds.") from None
            if answer.status_code < 400:
                return answer
            failure = _error(answer)
            # 503 is sent again only when AADML says when (a model starting); one closed for good says no time.
            again = answer.status_code == 429 or (answer.status_code == 503 and failure.retry_after is not None)
            if again and attempt < self.max_retries:
                attempt += 1
                time.sleep(min(failure.retry_after or 2 ** attempt, _MAX_WAIT))
                continue
            raise failure

    @contextmanager
    def _stream(self, method: str, path: str, **kwargs: Any) -> Iterator[httpx.Response]:
        try:
            with self._http.stream(method, self.api_url + path, headers=self._headers(), timeout=self.timeout,
                                   **kwargs) as answer:
                if answer.status_code >= 400:
                    answer.read()
                    raise _error(answer)
                yield answer
        except httpx.ConnectError as failure:
            raise errors.ConnectionError(f"Could not reach {self.api_url}: {failure}") from None
        except httpx.TimeoutException:
            raise errors.ConnectionError(f"No answer from {self.api_url} within {self.timeout} seconds.") from None


def _error(answer: httpx.Response) -> errors.APIError:
    """The APIError for an error answer: AADML's ``{"error", "field"}`` or OpenAI's ``{"error": {"message"}}``."""
    try:
        body = answer.json()
    except ValueError:
        body = {}
    raw = body.get("error") if isinstance(body, dict) else None
    if isinstance(raw, dict):
        message, field = raw.get("message") or "", raw.get("param")
    else:
        message, field = raw or "", body.get("field") if isinstance(body, dict) else None
    retry = answer.headers.get("Retry-After")
    try:
        retry_after = float(retry) if retry else None
    except ValueError:
        retry_after = None
    kind = errors.error_for(answer.status_code)
    return kind(message or f"AADML answered {answer.status_code}.", answer.status_code, field=field,
                retry_after=retry_after, body=body if isinstance(body, dict) else {})
