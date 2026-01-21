"""Response envelope helpers for standardized JSON output."""

import json
from datetime import datetime, timezone
from typing import Any

from .errors import JiraToolError


def _get_timestamp() -> str:
    """Get current timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_meta(command: str) -> dict[str, str]:
    """Build metadata block for response envelope."""
    return {
        "tool": "jira",
        "command": command,
        "timestamp": _get_timestamp(),
    }


def success_response(data: Any, command: str) -> dict[str, Any]:
    """
    Create a success response envelope.

    Args:
        data: The response data payload
        command: The command that was executed (e.g., "issue.get")

    Returns:
        Standard success envelope dictionary
    """
    return {
        "ok": True,
        "data": data,
        "meta": _build_meta(command),
    }


def error_response(error: JiraToolError, command: str) -> dict[str, Any]:
    """
    Create an error response envelope from a JiraToolError.

    Args:
        error: The error that occurred
        command: The command that was executed

    Returns:
        Standard error envelope dictionary
    """
    return {
        "ok": False,
        "error": error.to_dict(),
        "meta": _build_meta(command),
    }


def error_response_from_dict(
    code: str,
    message: str,
    command: str,
    http_status: int | None = None,
    details: dict | None = None,
) -> dict[str, Any]:
    """
    Create an error response envelope from individual fields.

    Args:
        code: Error code string
        message: Human-readable error message
        command: The command that was executed
        http_status: Optional HTTP status code
        details: Optional additional error details

    Returns:
        Standard error envelope dictionary
    """
    error_dict: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if http_status is not None:
        error_dict["http_status"] = http_status
    if details:
        error_dict["details"] = details

    return {
        "ok": False,
        "error": error_dict,
        "meta": _build_meta(command),
    }


def format_json(envelope: dict[str, Any], pretty: bool = False) -> str:
    """
    Format envelope as JSON string.

    Args:
        envelope: The response envelope dictionary
        pretty: If True, format with indentation for human readability

    Returns:
        JSON string
    """
    if pretty:
        return json.dumps(envelope, indent=2, ensure_ascii=False)
    return json.dumps(envelope, ensure_ascii=False)
