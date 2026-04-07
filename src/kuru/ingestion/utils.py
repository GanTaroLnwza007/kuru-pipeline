"""Shared utilities for ingestion modules."""

from __future__ import annotations


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
