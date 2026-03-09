"""Unit tests for gerrit-cli response envelope wrappers."""

import json
from io import StringIO
from unittest.mock import patch

from gerrit_cli.envelope import (
    TOOL_NAME,
    error_response,
    error_response_from_dict,
    format_json,
    success_response,
)
from gerrit_cli.errors import GerritToolError


class TestToolName:
    """Tests for tool name configuration."""

    def test_tool_name_is_gerrit_cli(self):
        """Tool name should be 'gerrit-cli'."""
        assert TOOL_NAME == "gerrit-cli"


class TestSuccessResponse:
    """Tests for success response wrapper."""

    def test_success_response_includes_tool_name(self):
        """Success response should include gerrit-cli tool name."""
        result = success_response({"key": "value"}, "extract")
        assert result["ok"] is True
        assert result["data"] == {"key": "value"}
        assert result["meta"]["tool"] == "gerrit-cli"
        assert result["meta"]["command"] == "extract"

    def test_success_response_with_list_data(self):
        """Success response should work with list data."""
        data = [{"id": 1}, {"id": 2}]
        result = success_response(data, "series-comments")
        assert result["data"] == data
        assert result["meta"]["tool"] == "gerrit-cli"


class TestErrorResponse:
    """Tests for error response wrapper."""

    def test_error_response_with_tool_error(self):
        """Error response should work with GerritToolError."""
        error = GerritToolError(
            code="CHANGE_NOT_FOUND",
            message="Change 12345 not found",
            http_status=404,
        )
        result = error_response(error, "extract")

        assert result["ok"] is False
        assert result["error"]["code"] == "CHANGE_NOT_FOUND"
        assert result["error"]["message"] == "Change 12345 not found"
        assert result["error"]["http_status"] == 404
        assert result["meta"]["tool"] == "gerrit-cli"
        assert result["meta"]["command"] == "extract"

    def test_error_response_with_details(self):
        """Error response should include details."""
        error = GerritToolError(
            code="INVALID_URL",
            message="Invalid URL",
            details={"url": "not-a-url"},
        )
        result = error_response(error, "review")
        assert result["error"]["details"] == {"url": "not-a-url"}


class TestErrorResponseFromDict:
    """Tests for error_response_from_dict wrapper."""

    def test_minimal_error(self):
        """Should work with just code and message."""
        result = error_response_from_dict(
            code="ERROR",
            message="An error",
            command="test",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "ERROR"
        assert result["meta"]["tool"] == "gerrit-cli"

    def test_full_error(self):
        """Should include all optional fields."""
        result = error_response_from_dict(
            code="ERROR",
            message="An error",
            command="test",
            http_status=500,
            details={"extra": "info"},
        )
        assert result["error"]["http_status"] == 500
        assert result["error"]["details"] == {"extra": "info"}


class TestFormatJson:
    """Tests for format_json output modes."""

    # -- Default behaviour: strip envelope, output payload only --

    def test_format_json_default_strips_success_envelope(self):
        """Default format_json should output only the data payload."""
        envelope = {"ok": True, "data": {"key": "value"}, "meta": {"tool": "gerrit-cli"}}
        result = format_json(envelope)
        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    def test_format_json_default_strips_error_envelope(self):
        """Default format_json should output only the error payload."""
        envelope = {
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": "gone"},
            "meta": {"tool": "gerrit-cli"},
        }
        result = format_json(envelope)
        parsed = json.loads(result)
        assert parsed == {"code": "NOT_FOUND", "message": "gone"}

    def test_format_json_default_compact(self):
        """Default format_json should produce compact (single-line) output."""
        envelope = {"ok": True, "data": {"key": "value"}}
        result = format_json(envelope)
        assert "\n" not in result

    def test_format_json_default_pretty(self):
        """Default format_json with pretty=True should indent the payload."""
        envelope = {"ok": True, "data": {"key": "value"}}
        result = format_json(envelope, pretty=True)
        assert "\n" in result
        assert json.loads(result) == {"key": "value"}

    def test_format_json_default_list_data(self):
        """Default format_json should handle list data payloads."""
        envelope = {"ok": True, "data": [{"id": 1}, {"id": 2}]}
        parsed = json.loads(format_json(envelope))
        assert parsed == [{"id": 1}, {"id": 2}]

    # -- full_envelope=True: preserve the complete wrapper --

    def test_format_json_full_envelope_compact(self):
        """full_envelope=True should output the complete envelope."""
        envelope = {"ok": True, "data": {"key": "value"}, "meta": {"tool": "gerrit-cli"}}
        result = format_json(envelope, pretty=False, full_envelope=True)
        assert "\n" not in result
        assert json.loads(result) == envelope

    def test_format_json_full_envelope_pretty(self):
        """full_envelope=True with pretty should indent the full envelope."""
        envelope = {"ok": True, "data": {"key": "value"}, "meta": {"tool": "gerrit-cli"}}
        result = format_json(envelope, pretty=True, full_envelope=True)
        assert "\n" in result
        assert json.loads(result) == envelope

    def test_format_json_full_envelope_error(self):
        """full_envelope=True should preserve error envelopes."""
        envelope = {
            "ok": False,
            "error": {"code": "ERR", "message": "bad"},
            "meta": {"tool": "gerrit-cli"},
        }
        result = format_json(envelope, full_envelope=True)
        assert json.loads(result) == envelope

    # -- Edge / fallback cases --

    def test_format_json_malformed_envelope_passthrough(self):
        """Envelope without data or error keys should pass through as-is."""
        envelope = {"something": "else"}
        result = format_json(envelope)
        assert json.loads(result) == envelope


class TestOutputResultEnvelopeFlag:
    """Tests for output_result respecting FULL_ENVELOPE flag."""

    def test_output_result_default_strips_envelope(self):
        """output_result should strip envelope when FULL_ENVELOPE is False."""
        import gerrit_cli.cli
        from gerrit_cli.commands._helpers import output_result

        envelope = success_response({"key": "value"}, "test")

        old = gerrit_cli.cli.FULL_ENVELOPE
        try:
            gerrit_cli.cli.FULL_ENVELOPE = False
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                output_result(envelope, pretty=False)
            parsed = json.loads(mock_out.getvalue().strip())
            # Should be just the data, not the full envelope
            assert parsed == {"key": "value"}
            assert "ok" not in parsed
            assert "meta" not in parsed
        finally:
            gerrit_cli.cli.FULL_ENVELOPE = old

    def test_output_result_full_envelope_preserves_wrapper(self):
        """output_result should preserve envelope when FULL_ENVELOPE is True."""
        import gerrit_cli.cli
        from gerrit_cli.commands._helpers import output_result

        envelope = success_response({"key": "value"}, "test")

        old = gerrit_cli.cli.FULL_ENVELOPE
        try:
            gerrit_cli.cli.FULL_ENVELOPE = True
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                output_result(envelope, pretty=False)
            parsed = json.loads(mock_out.getvalue().strip())
            assert parsed["ok"] is True
            assert parsed["data"] == {"key": "value"}
            assert parsed["meta"]["tool"] == "gerrit-cli"
        finally:
            gerrit_cli.cli.FULL_ENVELOPE = old

    def test_output_success_default_strips_envelope(self):
        """output_success should strip envelope by default."""
        import gerrit_cli.cli
        from gerrit_cli.commands._helpers import output_success

        old = gerrit_cli.cli.FULL_ENVELOPE
        try:
            gerrit_cli.cli.FULL_ENVELOPE = False
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                output_success({"items": [1, 2]}, "test", pretty=False)
            parsed = json.loads(mock_out.getvalue().strip())
            assert parsed == {"items": [1, 2]}
        finally:
            gerrit_cli.cli.FULL_ENVELOPE = old

    def test_output_error_default_strips_envelope(self):
        """output_error should strip envelope by default."""
        import gerrit_cli.cli
        from gerrit_cli.commands._helpers import output_error

        old = gerrit_cli.cli.FULL_ENVELOPE
        try:
            gerrit_cli.cli.FULL_ENVELOPE = False
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                output_error("NOT_FOUND", "gone", "test", pretty=False)
            parsed = json.loads(mock_out.getvalue().strip())
            assert parsed["code"] == "NOT_FOUND"
            assert parsed["message"] == "gone"
            assert "ok" not in parsed
        finally:
            gerrit_cli.cli.FULL_ENVELOPE = old

