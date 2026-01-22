"""Unit tests for shared response envelope functions."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from llm_tool_common.envelope import (
    _build_meta,
    _get_timestamp,
    error_response,
    error_response_from_dict,
    format_json,
    success_response,
)
from llm_tool_common.errors import ToolError


class TestTimestamp:
    """Tests for timestamp generation."""

    def test_timestamp_format(self):
        """Timestamp should be ISO-8601 format."""
        ts = _get_timestamp()
        # Should match format like "2024-01-15T10:30:00Z"
        assert len(ts) == 20
        assert ts.endswith("Z")
        # Should be parseable
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")

    @patch("llm_tool_common.envelope.datetime")
    def test_timestamp_uses_utc(self, mock_datetime):
        """Timestamp should use UTC timezone."""
        mock_dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_dt
        mock_datetime.strptime = datetime.strptime

        _get_timestamp()
        mock_datetime.now.assert_called_once_with(timezone.utc)


class TestBuildMeta:
    """Tests for metadata building."""

    def test_meta_structure(self):
        """Meta should have required fields."""
        meta = _build_meta("test-tool", "some.command")
        assert meta["tool"] == "test-tool"
        assert meta["command"] == "some.command"
        assert "timestamp" in meta

    def test_meta_tool_and_command_preserved(self):
        """Tool and command should be preserved exactly."""
        meta = _build_meta("gerrit-comments", "extract")
        assert meta["tool"] == "gerrit-comments"
        assert meta["command"] == "extract"


class TestSuccessResponse:
    """Tests for success response envelope."""

    def test_success_response_structure(self):
        """Success response should have ok=True and data."""
        result = success_response({"key": "value"}, "my-tool", "my.command")
        assert result["ok"] is True
        assert result["data"] == {"key": "value"}
        assert "meta" in result
        assert result["meta"]["tool"] == "my-tool"
        assert result["meta"]["command"] == "my.command"

    def test_success_response_with_list_data(self):
        """Success response should work with list data."""
        data = [{"id": 1}, {"id": 2}]
        result = success_response(data, "tool", "search")
        assert result["data"] == data

    def test_success_response_with_none_data(self):
        """Success response should work with None data."""
        result = success_response(None, "tool", "delete")
        assert result["data"] is None


class TestErrorResponse:
    """Tests for error response envelope."""

    def test_error_response_structure(self):
        """Error response should have ok=False and error dict."""
        error = ToolError(
            code="TEST_ERROR",
            message="Test message",
            http_status=400,
        )
        result = error_response(error, "my-tool", "my.command")

        assert result["ok"] is False
        assert result["error"]["code"] == "TEST_ERROR"
        assert result["error"]["message"] == "Test message"
        assert result["error"]["http_status"] == 400
        assert "meta" in result
        assert result["meta"]["tool"] == "my-tool"

    def test_error_response_with_details(self):
        """Error response should include details."""
        error = ToolError(
            code="TEST_ERROR",
            message="Test",
            details={"field": "value"},
        )
        result = error_response(error, "tool", "command")
        assert result["error"]["details"] == {"field": "value"}


class TestErrorResponseFromDict:
    """Tests for error_response_from_dict helper."""

    def test_minimal_error(self):
        """Should work with just code and message."""
        result = error_response_from_dict(
            code="ERROR",
            message="An error",
            tool="test-tool",
            command="test",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "ERROR"
        assert result["error"]["message"] == "An error"
        assert "http_status" not in result["error"]
        assert "details" not in result["error"]
        assert result["meta"]["tool"] == "test-tool"

    def test_full_error(self):
        """Should include all optional fields."""
        result = error_response_from_dict(
            code="ERROR",
            message="An error",
            tool="tool",
            command="test",
            http_status=500,
            details={"extra": "info"},
        )
        assert result["error"]["http_status"] == 500
        assert result["error"]["details"] == {"extra": "info"}


class TestFormatJson:
    """Tests for JSON formatting."""

    def test_compact_output(self):
        """Default should be compact JSON."""
        envelope = {"ok": True, "data": {"key": "value"}}
        result = format_json(envelope, pretty=False)
        assert "\n" not in result
        assert json.loads(result) == envelope

    def test_pretty_output(self):
        """Pretty should have indentation."""
        envelope = {"ok": True, "data": {"key": "value"}}
        result = format_json(envelope, pretty=True)
        assert "\n" in result
        assert "  " in result  # Indentation
        assert json.loads(result) == envelope

    def test_unicode_preserved(self):
        """Unicode should be preserved (not escaped)."""
        envelope = {"ok": True, "data": {"name": "日本語"}}
        result = format_json(envelope)
        assert "日本語" in result
        assert "\\u" not in result

