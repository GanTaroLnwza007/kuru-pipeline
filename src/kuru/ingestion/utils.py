"""Shared utilities for ingestion modules."""

from __future__ import annotations

import base64
import struct


def safe_print(msg: str) -> None:
    """Print safely on Windows regardless of console encoding."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode())


def is_transient_error(exc: BaseException) -> bool:
    """True for retriable API/network errors; False for programming errors."""
    if isinstance(exc, (TypeError, ValueError, AttributeError, UnicodeError)):
        return False
    return any(c in str(exc) for c in ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))


def png_dimensions(b64: str) -> tuple[int, int]:
    """Extract width, height from a base64 PNG without full decode (reads 24 bytes)."""
    raw = base64.b64decode(b64[:64])
    w = struct.unpack(">I", raw[16:20])[0]
    h = struct.unpack(">I", raw[20:24])[0]
    return w, h
