"""Tests for structured_extractor — JSON parsing and fallback behaviour."""
import json
from unittest.mock import MagicMock, patch

import pytest

from kuru.ingestion.structured_extractor import StructuredProgram, _parse_response


def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = json.dumps(data)
    return mock


def test_parse_response_full():
    data = {
        "overview": "หลักสูตรวิศวกรรมคอมพิวเตอร์",
        "plos": [{"id": "PLO1", "description": "ด้านความรู้", "category": "knowledge"}],
        "courses": [{"code": "01204111", "name_th": "แคลคูลัส", "credits": 3, "year": 1, "semester": 1}],
        "year_timeline": [{"year": 1, "narrative": "ปีแรก", "course_codes": ["01204111"]}],
        "curriculum_mapping": [{"course_code": "01204111", "plo_primary": ["PLO1"], "plo_secondary": []}],
    }
    result = _parse_response(json.dumps(data))
    assert result.overview == "หลักสูตรวิศวกรรมคอมพิวเตอร์"
    assert len(result.plos) == 1
    assert result.plos[0]["id"] == "PLO1"
    assert len(result.courses) == 1
    assert result.courses[0]["code"] == "01204111"
    assert len(result.year_timeline) == 1
    assert len(result.curriculum_mapping) == 1


def test_parse_response_empty_sections():
    data = {"overview": "", "plos": [], "courses": [], "year_timeline": [], "curriculum_mapping": []}
    result = _parse_response(json.dumps(data))
    assert result.overview == ""
    assert result.plos == []
    assert result.courses == []


def test_parse_response_invalid_json_returns_empty():
    result = _parse_response("not json at all")
    assert isinstance(result, StructuredProgram)
    assert result.plos == []
    assert result.courses == []
    assert result.overview == ""


def test_parse_response_partial_json():
    data = {"overview": "บางส่วน"}  # missing plos, courses, etc.
    result = _parse_response(json.dumps(data))
    assert result.overview == "บางส่วน"
    assert result.plos == []
    assert result.courses == []


def test_extract_structured_calls_gemini():
    sample_text = "หลักสูตรวิทยาศาสตรบัณฑิต สาขาวิชาวิทยาการคอมพิวเตอร์"
    mock_content = json.dumps({
        "overview": sample_text,
        "plos": [],
        "courses": [],
        "year_timeline": [],
        "curriculum_mapping": [],
    })
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = mock_content

    with patch("kuru.ingestion.structured_extractor.get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from kuru.ingestion.structured_extractor import extract_structured
        result = extract_structured(sample_text)

    assert result.overview == sample_text
    mock_client.chat.completions.create.assert_called_once()
