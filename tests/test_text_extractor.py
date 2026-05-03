"""Tests for text_extractor — scanned detection and per-page Typhoon routing."""
import base64
import struct
from unittest.mock import MagicMock, patch

import pytest

from kuru.ingestion.text_extractor import (
    SCANNED_CHAR_THRESHOLD,
    _should_ocr_page,
)


def test_should_ocr_page_true_when_low_yield():
    assert _should_ocr_page("   ") is True
    assert _should_ocr_page("ab") is True


def test_should_ocr_page_false_when_sufficient():
    assert _should_ocr_page("x" * 50) is False
    assert _should_ocr_page("สวัสดี " * 10) is False


def test_scanned_char_threshold_is_500():
    assert SCANNED_CHAR_THRESHOLD == 500
