"""Tests for janitor_tool.cli module."""

import json
import re
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from janitor_tool.cli import CRASH_RE, _resolve_build, main


class TestCrashPatterns:
    """Tests for CRASH_RE regex."""

    def test_matches_lbug(self):
        assert CRASH_RE.search("LBUG hit at some_file.c:42")

    def test_matches_lassert(self):
        assert CRASH_RE.search("LASSERT failed: condition")

    def test_matches_kernel_bug(self):
        assert CRASH_RE.search("kernel BUG at fs/ext4/inode.c:123!")

    def test_matches_kernel_panic(self):
        assert CRASH_RE.search("Kernel panic - not syncing: Fatal exception")

    def test_matches_oops(self):
        assert CRASH_RE.search("Oops: 0000 [#1] SMP")

    def test_matches_gpf(self):
        assert CRASH_RE.search("general protection fault: 0000")

    def test_matches_rip(self):
        assert CRASH_RE.search("RIP: 0010:some_function+0x42/0x100")

    def test_matches_call_trace(self):
        assert CRASH_RE.search("Call Trace:")

    def test_case_insensitive(self):
        assert CRASH_RE.search("lbug hit")
        assert CRASH_RE.search("kernel panic")

    def test_no_match(self):
        assert not CRASH_RE.search("All tests passed successfully")


class TestResolveBuild:
    """Tests for _resolve_build()."""

    def test_resolve_as_build(self):
        client = MagicMock()
        client.get_ref.return_value = {"ref": "refs/changes/40/64440/10"}

        result = _resolve_build(client, "61009", "test", False)
        assert result == 61009

    def test_resolve_as_change(self):
        client = MagicMock()
        client.get_ref.return_value = None
        client.resolve_change.return_value = 61009

        result = _resolve_build(client, "64440", "test", False)
        assert result == 61009

    def test_resolve_from_url(self):
        client = MagicMock()
        client.get_ref.return_value = {"ref": "refs/changes/40/64440/10"}

        result = _resolve_build(
            client,
            "https://review.whamcloud.com/c/fs/lustre-release/+/64440",
            "test", False,
        )
        # Should extract 64440 from URL and try it
        assert result == 64440
        client.get_ref.assert_called_with(64440)

    def test_resolve_not_found_exits(self):
        client = MagicMock()
        client.get_ref.return_value = None
        client.resolve_change.return_value = None

        with pytest.raises(SystemExit):
            _resolve_build(client, "99999", "test", False)


class TestResultsCommand:
    """Tests for the 'results' CLI command."""

    @patch("janitor_tool.cli._make_client")
    def test_basic_results(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "refs/changes/40/64440/10"}
        client.get_results.return_value = {
            "build": 61009,
            "change": 64440,
            "patchset": 10,
            "subject": "LU-19956 fix",
            "build_status": "Success",
            "distros": [],
            "sections": [
                {
                    "phase": "Initial testing",
                    "status": "Success",
                    "tests": [
                        {"test": "sanity", "status": "PASS", "duration_s": 500},
                    ],
                }
            ],
            "url": "https://example.com/61009/results.html",
        }

        runner = CliRunner()
        result = runner.invoke(main, ["results", "61009"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["build"] == 61009
        assert data["summary"]["passed"] == 1

    @patch("janitor_tool.cli._make_client")
    def test_results_failures_only(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "refs/changes/40/64440/10"}
        client.get_results.return_value = {
            "build": 61009,
            "change": 64440,
            "patchset": 10,
            "subject": "LU-19956",
            "build_status": "Failure",
            "distros": [],
            "sections": [
                {
                    "phase": "Initial testing",
                    "status": "Failure",
                    "tests": [
                        {"test": "sanity", "status": "PASS", "duration_s": 500},
                        {"test": "sanity2", "status": "FAIL", "duration_s": 100},
                    ],
                }
            ],
            "url": "https://example.com/61009/results.html",
        }

        runner = CliRunner()
        result = runner.invoke(main, ["results", "--failures-only", "61009"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # Only failures should be in sections tests
        for section in data["sections"]:
            for t in section["tests"]:
                assert t["status"] != "PASS"

    @patch("janitor_tool.cli._make_client")
    def test_results_not_found(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.get_results.return_value = None

        runner = CliRunner()
        result = runner.invoke(main, ["results", "99999"])

        assert result.exit_code == 1


class TestDetailCommand:
    """Tests for the 'detail' CLI command."""

    @patch("janitor_tool.cli._make_client")
    def test_basic_detail(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-ldiskfs-rocky8"
        client.get_test_yaml.return_value = {
            "Tests": [
                {
                    "name": "sanity",
                    "SubTests": [
                        {"name": "test_1", "status": "PASS", "duration": 10},
                        {"name": "test_2", "status": "FAIL", "duration": 5, "error": "bad"},
                    ],
                }
            ],
            "TestGroup": {"testhost": "host1"},
        }

        runner = CliRunner()
        result = runner.invoke(main, ["detail", "61009", "sanity@ldiskfs"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_subtests"] == 2
        assert data["failed_count"] == 1

    @patch("janitor_tool.cli._make_client")
    def test_detail_test_not_found(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = None

        runner = CliRunner()
        result = runner.invoke(main, ["detail", "61009", "nonexistent"])

        assert result.exit_code == 1


class TestLogsCommand:
    """Tests for the 'logs' CLI command."""

    @patch("janitor_tool.cli._make_client")
    def test_basic_logs(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-test"
        client.list_test_files.return_value = [
            {"name": "console.txt", "href": "console.txt", "size": "1.2M"},
            {"name": "results.yml", "href": "results.yml", "size": "45K"},
        ]
        client._build_url.return_value = "https://example.com/61009/testresults/sanity-test/"

        runner = CliRunner()
        result = runner.invoke(main, ["logs", "61009", "sanity@ldiskfs"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["files"]) == 2


class TestFetchCommand:
    """Tests for the 'fetch' CLI command."""

    @patch("janitor_tool.cli._make_client")
    def test_basic_fetch(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-test"
        client.fetch_log.return_value = "line1\nline2\nline3\n"

        runner = CliRunner()
        result = runner.invoke(main, ["fetch", "61009", "sanity@ldiskfs", "console.txt"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["line_count"] == 3

    @patch("janitor_tool.cli._make_client")
    def test_fetch_with_grep(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-test"
        client.fetch_log.return_value = "ok line\nLBUG found\nanother ok\n"

        runner = CliRunner()
        result = runner.invoke(main, [
            "fetch", "61009", "sanity@ldiskfs", "console.txt",
            "--grep", "LBUG",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["line_count"] == 1
        assert "LBUG" in data["content"]

    @patch("janitor_tool.cli._make_client")
    def test_fetch_with_tail(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-test"
        client.fetch_log.return_value = "line1\nline2\nline3\nline4\n"

        runner = CliRunner()
        result = runner.invoke(main, [
            "fetch", "61009", "sanity@ldiskfs", "console.txt",
            "--tail", "2",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["line_count"] == 2


class TestCrashCommand:
    """Tests for the 'crash' CLI command."""

    @patch("janitor_tool.cli._make_client")
    def test_crash_with_matches(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-test"
        client.list_test_files.return_value = [
            {"name": "console.txt", "href": "console.txt", "size": "1M"},
        ]
        client.fetch_log.return_value = "ok line\nLBUG at file.c:42\nmore ok\n"

        runner = CliRunner()
        result = runner.invoke(main, ["crash", "61009", "sanity@ldiskfs"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["crash_signatures_found"] >= 1
        assert len(data["matches"]) >= 1

    @patch("janitor_tool.cli._make_client")
    def test_crash_no_matches(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = "sanity-test"
        client.list_test_files.return_value = [
            {"name": "console.txt", "href": "console.txt", "size": "1M"},
        ]
        client.fetch_log.return_value = "all good\nno problems\n"

        runner = CliRunner()
        result = runner.invoke(main, ["crash", "61009", "sanity@ldiskfs"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["crash_signatures_found"] == 0
        assert "assessment" in data

    @patch("janitor_tool.cli._make_client")
    def test_crash_test_not_found(self, mock_make):
        client = MagicMock()
        mock_make.return_value = client
        client.get_ref.return_value = {"ref": "x"}
        client.find_test_dir.return_value = None

        runner = CliRunner()
        result = runner.invoke(main, ["crash", "61009", "nonexistent"])

        assert result.exit_code == 1


# Need pytest for the SystemExit test
import pytest
