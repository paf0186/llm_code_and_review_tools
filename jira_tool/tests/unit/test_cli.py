"""Unit tests for CLI module."""

import json

import pytest
import responses
from click.testing import CliRunner

from jira_tool.cli import main, _normalize_issue, _normalize_comment, _normalize_comments


@pytest.fixture
def runner():
    """Create CLI runner."""
    return CliRunner()


@pytest.fixture
def mock_env(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv("JIRA_SERVER", "https://jira.example.com")
    monkeypatch.setenv("JIRA_TOKEN", "test-token")


class TestNormalizeIssue:
    """Tests for issue normalization."""

    def test_normalize_full_issue(self):
        """Should normalize all fields."""
        raw = {
            "key": "PROJ-123",
            "id": "10001",
            "self": "https://jira.example.com/rest/api/2/issue/10001",
            "fields": {
                "summary": "Test issue",
                "description": "Issue description",
                "status": {"name": "Open"},
                "priority": {"name": "High"},
                "issuetype": {"name": "Bug"},
                "project": {"key": "PROJ"},
                "assignee": {"displayName": "John Doe"},
                "reporter": {"displayName": "Jane Doe"},
                "resolution": {"name": "Fixed"},
                "created": "2024-01-15T10:00:00.000+0000",
                "updated": "2024-01-15T12:00:00.000+0000",
                "labels": ["bug", "urgent"],
            },
        }

        result = _normalize_issue(raw)

        assert result["key"] == "PROJ-123"
        assert result["id"] == "10001"
        assert result["summary"] == "Test issue"
        assert result["description"] == "Issue description"
        assert result["status"] == "Open"
        assert result["priority"] == "High"
        assert result["issue_type"] == "Bug"
        assert result["project"] == "PROJ"
        assert result["assignee"] == "John Doe"
        assert result["reporter"] == "Jane Doe"
        assert result["resolution"] == "Fixed"
        assert result["labels"] == ["bug", "urgent"]

    def test_normalize_issue_with_null_fields(self):
        """Should handle null/missing fields."""
        raw = {
            "key": "PROJ-123",
            "fields": {
                "summary": "Test",
                "assignee": None,
                "resolution": None,
            },
        }

        result = _normalize_issue(raw)

        assert result["assignee"] is None
        assert result["resolution"] is None


class TestNormalizeComment:
    """Tests for comment normalization."""

    def test_normalize_comment(self):
        """Should normalize comment fields."""
        raw = {
            "id": "12345",
            "body": "Comment text",
            "author": {
                "displayName": "John Doe",
                "emailAddress": "john@example.com",
            },
            "updateAuthor": {"displayName": "Jane Doe"},
            "created": "2024-01-15T10:00:00.000+0000",
            "updated": "2024-01-15T12:00:00.000+0000",
        }

        result = _normalize_comment(raw)

        assert result["id"] == "12345"
        assert result["body"] == "Comment text"
        assert result["author"] == "John Doe"
        assert result["author_email"] == "john@example.com"
        assert result["update_author"] == "Jane Doe"


class TestNormalizeComments:
    """Tests for comments batch normalization."""

    def test_normalize_comments_with_content(self):
        """Should include full comment content."""
        raw = {
            "comments": [
                {"id": "1", "body": "First", "author": {"displayName": "User"}, "created": "2024-01-15T10:00:00.000+0000"},
                {"id": "2", "body": "Second", "author": {"displayName": "User"}, "created": "2024-01-15T11:00:00.000+0000"},
            ],
            "total": 2,
        }

        result = _normalize_comments(raw, summary_only=False)

        assert result["total_comments"] == 2
        assert len(result["comments"]) == 2
        assert result["comments"][0]["body"] == "First"

    def test_normalize_comments_summary_only(self):
        """Should only include summaries."""
        raw = {
            "comments": [
                {"id": "1", "body": "A" * 200, "author": {"displayName": "User"}, "created": "2024-01-15T10:00:00.000+0000"},
            ],
            "total": 1,
        }

        result = _normalize_comments(raw, summary_only=True)

        assert "comments" not in result
        assert "comments_summary" in result
        assert result["comments_summary"][0]["body_preview"].endswith("...")
        assert len(result["comments_summary"][0]["body_preview"]) <= 103  # 100 + "..."


class TestCLIIssueGet:
    """Tests for 'jira issue get' command."""

    @responses.activate
    def test_issue_get_success(self, runner, mock_env):
        """Should return issue in envelope."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-123",
            json={
                "key": "PROJ-123",
                "fields": {
                    "summary": "Test issue",
                    "status": {"name": "Open"},
                },
            },
            status=200,
        )

        result = runner.invoke(main, ["issue", "get", "PROJ-123"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["data"]["key"] == "PROJ-123"
        assert data["meta"]["command"] == "issue.get"

    @responses.activate
    def test_issue_get_not_found(self, runner, mock_env):
        """Should return error envelope for 404."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-999",
            json={"errorMessages": ["Issue not found"]},
            status=404,
        )

        result = runner.invoke(main, ["issue", "get", "PROJ-999"])

        assert result.exit_code == 3  # NOT_FOUND
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "ISSUE_NOT_FOUND" in data["error"]["code"]

    @responses.activate
    def test_issue_get_pretty(self, runner, mock_env):
        """Should format with indentation when --pretty."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-123",
            json={"key": "PROJ-123", "fields": {}},
            status=200,
        )

        result = runner.invoke(main, ["--pretty", "issue", "get", "PROJ-123"])

        assert result.exit_code == 0
        assert "\n" in result.output
        assert "  " in result.output


class TestCLIIssueComments:
    """Tests for 'jira issue comments' command."""

    @responses.activate
    def test_comments_default_limit(self, runner, mock_env):
        """Should use default limit of 5."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-123/comment",
            json={"comments": [], "total": 0},
            status=200,
        )

        result = runner.invoke(main, ["issue", "comments", "PROJ-123"])

        assert result.exit_code == 0
        # Check that limit was 5 (default)
        url = responses.calls[0].request.url
        assert "maxResults=5" in url

    @responses.activate
    def test_comments_custom_limit(self, runner, mock_env):
        """Should respect --limit option."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-123/comment",
            json={"comments": [], "total": 0},
            status=200,
        )

        result = runner.invoke(main, ["issue", "comments", "PROJ-123", "--limit", "10"])

        assert result.exit_code == 0
        url = responses.calls[0].request.url
        assert "maxResults=10" in url

    @responses.activate
    def test_comments_with_pagination_info(self, runner, mock_env):
        """Should include pagination metadata."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-123/comment",
            json={
                "comments": [{"id": "1", "body": "Test", "author": {"displayName": "User"}, "created": "2024-01-15T10:00:00.000+0000"}],
                "total": 10,
            },
            status=200,
        )

        result = runner.invoke(main, ["issue", "comments", "PROJ-123"])

        data = json.loads(result.output)
        assert data["data"]["pagination"]["total"] == 10
        assert data["data"]["pagination"]["returned"] == 1


class TestCLIIssueSearch:
    """Tests for 'jira issue search' command."""

    @responses.activate
    def test_search_basic(self, runner, mock_env):
        """Should search with JQL."""
        responses.add(
            responses.POST,
            "https://jira.example.com/rest/api/2/search",
            json={"issues": [], "total": 0},
            status=200,
        )

        result = runner.invoke(main, ["issue", "search", "project = PROJ"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["jql"] == "project = PROJ"


class TestCLIIssueComment:
    """Tests for 'jira issue comment' command."""

    @responses.activate
    def test_add_comment(self, runner, mock_env):
        """Should add comment to issue."""
        responses.add(
            responses.POST,
            "https://jira.example.com/rest/api/2/issue/PROJ-123/comment",
            json={
                "id": "12345",
                "body": "Test comment",
                "author": {"displayName": "User"},
                "created": "2024-01-15T10:00:00.000+0000",
            },
            status=201,
        )

        result = runner.invoke(main, ["issue", "comment", "PROJ-123", "Test comment"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["issue_key"] == "PROJ-123"
        assert data["data"]["comment"]["body"] == "Test comment"


class TestCLIIssueTransitions:
    """Tests for 'jira issue transitions' command."""

    @responses.activate
    def test_list_transitions(self, runner, mock_env):
        """Should list available transitions."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/issue/PROJ-123/transitions",
            json={
                "transitions": [
                    {"id": "11", "name": "Start", "to": {"name": "In Progress"}},
                ],
            },
            status=200,
        )

        result = runner.invoke(main, ["issue", "transitions", "PROJ-123"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]["transitions"]) == 1
        assert data["data"]["transitions"][0]["name"] == "Start"


class TestCLIConfigTest:
    """Tests for 'jira config test' command."""

    @responses.activate
    def test_config_test_success(self, runner, mock_env):
        """Should test connectivity."""
        responses.add(
            responses.GET,
            "https://jira.example.com/rest/api/2/serverInfo",
            json={
                "serverTitle": "Test JIRA",
                "version": "8.0.0",
                "baseUrl": "https://jira.example.com",
            },
            status=200,
        )

        result = runner.invoke(main, ["config", "test"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["connected"] is True
        assert data["data"]["version"] == "8.0.0"

    def test_config_missing(self, runner, monkeypatch):
        """Should error when config missing."""
        monkeypatch.delenv("JIRA_SERVER", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        result = runner.invoke(main, ["--config", "/nonexistent/path.json", "config", "test"])

        assert result.exit_code == 1  # GENERAL_ERROR
        data = json.loads(result.output)
        assert data["ok"] is False
        assert "CONFIG_ERROR" in data["error"]["code"]


class TestCLIConfigShow:
    """Tests for 'jira config show' command."""

    def test_config_show_redacts_token(self, runner, mock_env):
        """Should redact token in output."""
        result = runner.invoke(main, ["config", "show"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # Token should be redacted - full token never shown
        assert "test-token" not in data["data"]["token"]
        # Short tokens show as ***, longer tokens show partial with ...
        assert "..." in data["data"]["token"] or "***" in data["data"]["token"]
