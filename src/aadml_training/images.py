"""Turning what a caller gives as a photo into bytes: a file path, bytes, an open binary file, a URL, or a Pillow
image. Nothing here is sent anywhere; ``Client.predict`` sends the bytes to AADML."""
import io
import os
from pathlib import Path
from typing import Any, Tuple, Union

import httpx

from .errors import BadRequestError, PayloadTooLargeError

#: The largest photo AADML accepts (its prediction API refuses anything larger).
MAX_BYTES = 15 * 1024 * 1024
_TYPES = {b"\xff\xd8\xff": ("image/jpeg", ".jpg"), b"\x89PNG": ("image/png", ".png")}

ImageInput = Union[str, os.PathLike, bytes, bytearray, Any]


def _kind(data: bytes) -> Tuple[str, str]:
    for magic, kind in _TYPES.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise BadRequestError("The photo must be a JPEG, PNG or WebP image.", 400, field="image")


def _checked(data: bytes) -> Tuple[bytes, str, str]:
    if not data:
        raise BadRequestError("The photo is empty.", 400, field="image")
    if len(data) > MAX_BYTES:
        raise PayloadTooLargeError(f"The photo is larger than {MAX_BYTES // (1024 * 1024)} MB.", 413, field="image")
    content_type, suffix = _kind(data)
    return data, content_type, suffix


def _download(url: str, timeout: float) -> bytes:
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as answer:
        answer.raise_for_status()
        chunks, size = [], 0
        for chunk in answer.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise PayloadTooLargeError(f"The photo at {url} is larger than {MAX_BYTES // (1024 * 1024)} MB.", 413,
                                      field="image")
            chunks.append(chunk)
    return b"".join(chunks)


def load(image: ImageInput, timeout: float = 30.0) -> Tuple[bytes, str, str]:
    """``(bytes, content type, file name)`` of the photo ``image``."""
    if isinstance(image, (bytes, bytearray)):
        data, content_type, suffix = _checked(bytes(image))
        return data, content_type, "image" + suffix
    if isinstance(image, str) and image.startswith(("http://", "https://")):
        data, content_type, suffix = _checked(_download(image, timeout))
        return data, content_type, "image" + suffix
    if isinstance(image, (str, os.PathLike)):
        path = Path(image)
        if not path.is_file():
            raise BadRequestError(f"There is no file at {path}.", 400, field="image")
        data, content_type, _suffix = _checked(path.read_bytes())
        return data, content_type, path.name
    if hasattr(image, "read"):
        data, content_type, suffix = _checked(image.read())
        return data, content_type, Path(getattr(image, "name", "image" + suffix)).name
    if hasattr(image, "save") and hasattr(image, "mode"):             # a Pillow image
        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=95)
        data, content_type, _suffix = _checked(out.getvalue())
        return data, content_type, "image.jpg"
    raise BadRequestError("Give the photo as a file path, bytes, an open binary file, a URL or a Pillow image.", 400,
                          field="image")
