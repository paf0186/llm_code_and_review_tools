"""Tests for janitor_tool.errors module."""

from janitor_tool.errors import ErrorCode


class TestErrorCode:
    """Tests for ErrorCode constants."""

    def test_build_not_found(self):
        assert ErrorCode.BUILD_NOT_FOUND == "BUILD_NOT_FOUND"

    def test_test_not_found(self):
        assert ErrorCode.TEST_NOT_FOUND == "TEST_NOT_FOUND"

    def test_log_not_found(self):
        assert ErrorCode.LOG_NOT_FOUND == "LOG_NOT_FOUND"

    def test_change_not_found(self):
        assert ErrorCode.CHANGE_NOT_FOUND == "CHANGE_NOT_FOUND"
