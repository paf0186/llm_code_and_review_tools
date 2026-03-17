"""Tests for janitor_tool.client module."""

import re
from unittest.mock import MagicMock, patch

import pytest

from janitor_tool.client import JanitorClient, _ResultsParser
from janitor_tool.config import JanitorConfig


# ---------------------------------------------------------------------------
# _ResultsParser tests
# ---------------------------------------------------------------------------

class TestResultsParser:
    """Tests for _ResultsParser HTML parsing."""

    def test_parse_title(self):
        parser = _ResultsParser()
        parser.feed(
            "<html><head>"
            "<title>Results for build #61009 64440 rev 10: LU-19956 fix thing</title>"
            "</head></html>"
        )
        assert parser.build_number == 61009
        assert parser.change_number == 64440
        assert parser.patchset == 10
        assert parser.subject == "LU-19956 fix thing"

    def test_parse_build_status(self):
        parser = _ResultsParser()
        parser.feed(
            "<h3>Overall build status: Success</h3>"
        )
        assert parser.build_status == "Success"

    def test_parse_testing_section(self):
        parser = _ResultsParser()
        parser.feed(
            "<h3>Initial testing: Failure</h3>"
            "<table><tr><td>sanity</td><td>Success(100s)</td></tr></table>"
        )
        assert len(parser.sections) == 1
        assert parser.sections[0]["phase"] == "Initial testing"
        assert parser.sections[0]["status"] == "Failure"
        assert len(parser.sections[0]["tests"]) == 1
        assert parser.sections[0]["tests"][0]["test"] == "sanity"

    def test_parse_test_row_success(self):
        result = _ResultsParser._parse_test_row("sanity", "Success(1023s)", "")
        assert result["test"] == "sanity"
        assert result["status"] == "PASS"
        assert result["duration_s"] == 1023

    def test_parse_test_row_timeout(self):
        result = _ResultsParser._parse_test_row("sanity2", "Timeout(11332s)", "")
        assert result["status"] == "TIMEOUT"
        assert result["duration_s"] == 11332

    def test_parse_test_row_crash(self):
        result = _ResultsParser._parse_test_row("sanity3", "Client crashed(5340s)", "")
        assert result["status"] == "CRASH"
        assert result["status_detail"] == "Client crashed"

    def test_parse_test_row_server_crash(self):
        result = _ResultsParser._parse_test_row("test1", "Server crashed(100s)", "")
        assert result["status"] == "CRASH"

    def test_parse_test_row_lbug(self):
        result = _ResultsParser._parse_test_row("test2", "LBUG(200s)", "")
        assert result["status"] == "CRASH"

    def test_parse_test_row_failure(self):
        result = _ResultsParser._parse_test_row("test3", "Failure(50s)", "")
        assert result["status"] == "FAIL"

    def test_parse_test_row_error(self):
        result = _ResultsParser._parse_test_row("test4", "Error(10s)", "")
        assert result["status"] == "FAIL"

    def test_parse_test_row_not_run(self):
        result = _ResultsParser._parse_test_row("test5", "", "")
        assert result["status"] == "NOT_RUN"

    def test_parse_test_row_with_extra(self):
        result = _ResultsParser._parse_test_row("test6", "Failure(50s)", "some extra")
        assert result["extra"] == "some extra"

    def test_parse_test_row_unknown_status(self):
        result = _ResultsParser._parse_test_row("test7", "WeirdStatus", "")
        assert result["status"] == "WeirdStatus"
        assert result["duration_s"] is None

    def test_skip_header_rows(self):
        parser = _ResultsParser()
        parser.feed(
            "<h3>Initial testing: Failure</h3>"
            "<table>"
            "<tr><td>Test</td><td>Status</td></tr>"  # header row
            "<tr><td>sanity</td><td>Success(100s)</td></tr>"
            "</table>"
        )
        assert len(parser.sections[0]["tests"]) == 1

    def test_distros_table(self):
        parser = _ResultsParser()
        # Build status must come first to trigger distro table parsing
        parser.feed(
            "<h3>Overall build status: Success</h3>"
            "<table>"
            "<tr><td>Distro</td><td>Status</td></tr>"
            "<tr><td>rocky8.10</td><td>Success</td></tr>"
            "<tr><td>ubuntu2204</td><td>Success</td></tr>"
            "</table>"
        )
        assert len(parser.distros) == 2
        assert parser.distros[0]["distro"] == "rocky8.10"
        assert parser.distros[0]["status"] == "Success"

    def test_comprehensive_parse(self):
        html = """
        <html><head>
        <title>Results for build #61009 64440 rev 10: LU-19956 fix thing</title>
        </head><body>
        <h3>Overall build status: Success</h3>
        <table>
        <tr><td>Distro</td><td>Status</td></tr>
        <tr><td>rocky8.10</td><td>Success</td></tr>
        </table>
        <h3>Initial testing: Failure</h3>
        <table>
        <tr><td>Test</td><td>Status</td></tr>
        <tr><td>sanity</td><td>Success(500s)</td><td></td></tr>
        <tr><td>sanity2</td><td>Timeout(11332s)</td><td></td></tr>
        </table>
        <h3>Comprehensive testing: Not started</h3>
        </body></html>
        """
        parser = _ResultsParser()
        parser.feed(html)

        assert parser.build_number == 61009
        assert parser.build_status == "Success"
        assert len(parser.distros) == 1
        assert len(parser.sections) == 2
        assert parser.sections[0]["phase"] == "Initial testing"
        assert len(parser.sections[0]["tests"]) == 2
        assert parser.sections[1]["phase"] == "Comprehensive testing"


# ---------------------------------------------------------------------------
# JanitorClient tests
# ---------------------------------------------------------------------------

def _make_client(base_url="https://testing.example.com/janitor"):
    config = JanitorConfig(base_url=base_url)
    return JanitorClient(config)


class TestJanitorClientBuildUrl:
    """Tests for _build_url."""

    def test_build_url(self):
        client = _make_client()
        assert client._build_url(61009, "results.html") == \
            "https://testing.example.com/janitor/61009/results.html"

    def test_build_url_empty_path(self):
        client = _make_client()
        assert client._build_url(61009) == \
            "https://testing.example.com/janitor/61009/"


class TestResolveChange:
    """Tests for JanitorClient.resolve_change()."""

    def test_resolve_found(self):
        client = _make_client()

        dir_resp = MagicMock()
        dir_resp.status_code = 200
        dir_resp.text = '<a href="61009/">61009/</a> <a href="61008/">61008/</a>'

        ref_resp = MagicMock()
        ref_resp.status_code = 200
        ref_resp.text = "refs/changes/40/64440/10"

        client.session.get = MagicMock(side_effect=[dir_resp, ref_resp])

        result = client.resolve_change(64440)
        assert result == 61009

    def test_resolve_not_found(self):
        client = _make_client()

        dir_resp = MagicMock()
        dir_resp.status_code = 200
        dir_resp.text = '<a href="61009/">61009/</a>'

        ref_resp = MagicMock()
        ref_resp.status_code = 200
        ref_resp.text = "refs/changes/40/99999/1"

        client.session.get = MagicMock(side_effect=[dir_resp, ref_resp])

        result = client.resolve_change(64440)
        assert result is None

    def test_resolve_network_error(self):
        client = _make_client()
        client.session.get = MagicMock(side_effect=Exception("network error"))

        result = client.resolve_change(64440)
        assert result is None


class TestGetRef:
    """Tests for JanitorClient.get_ref()."""

    def test_valid_ref(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "refs/changes/40/64440/10"
        client.session.get = MagicMock(return_value=resp)

        result = client.get_ref(61009)
        assert result == {
            "ref": "refs/changes/40/64440/10",
            "change": 64440,
            "patchset": 10,
        }

    def test_non_standard_ref(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "refs/heads/master"
        client.session.get = MagicMock(return_value=resp)

        result = client.get_ref(61009)
        assert result == {"ref": "refs/heads/master"}

    def test_not_found(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        client.session.get = MagicMock(return_value=resp)

        result = client.get_ref(99999)
        assert result is None

    def test_network_error(self):
        client = _make_client()
        client.session.get = MagicMock(side_effect=Exception("timeout"))

        result = client.get_ref(61009)
        assert result is None


class TestGetResults:
    """Tests for JanitorClient.get_results()."""

    def test_basic(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = """
        <html><head>
        <title>Results for build #61009 64440 rev 10: LU-19956 fix</title>
        </head><body>
        <h3>Overall build status: Success</h3>
        <h3>Initial testing: Failure</h3>
        <table>
        <tr><td>sanity</td><td>Success(500s)</td></tr>
        </table>
        </body></html>
        """
        client.session.get = MagicMock(return_value=resp)

        result = client.get_results(61009)
        assert result is not None
        assert result["build"] == 61009
        assert result["change"] == 64440
        assert result["build_status"] == "Success"

    def test_not_found(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        client.session.get = MagicMock(return_value=resp)

        result = client.get_results(99999)
        assert result is None

    def test_network_error(self):
        client = _make_client()
        client.session.get = MagicMock(side_effect=Exception("fail"))

        result = client.get_results(61009)
        assert result is None


class TestFindTestDir:
    """Tests for JanitorClient.find_test_dir()."""

    def test_exact_match(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '''
        <a href="sanity2-ldiskfs-DNE-rocky8.10_x86_64-rocky8.10_x86_64/">sanity2-ldiskfs-DNE-rocky8.10_x86_64-rocky8.10_x86_64/</a>
        '''
        client.session.get = MagicMock(return_value=resp)

        result = client.find_test_dir(61009, "sanity2@ldiskfs+DNE")
        assert result is not None
        assert "sanity2-ldiskfs-DNE" in result

    def test_no_match(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<a href="other-test/">other-test/</a>'
        client.session.get = MagicMock(return_value=resp)

        result = client.find_test_dir(61009, "nonexistent@test")
        assert result is None

    def test_not_found_status(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        client.session.get = MagicMock(return_value=resp)

        result = client.find_test_dir(99999, "sanity")
        assert result is None


class TestListTestFiles:
    """Tests for JanitorClient.list_test_files()."""

    def test_basic(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '''
        <a href="console.txt">console.txt</a> </td><td> </td><td> 1.2M
        <a href="results.yml">results.yml</a> </td><td> </td><td> 45K
        '''
        client.session.get = MagicMock(return_value=resp)

        files = client.list_test_files(61009, "sanity-test")
        assert isinstance(files, list)

    def test_not_found(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        client.session.get = MagicMock(return_value=resp)

        files = client.list_test_files(99999, "test")
        assert files == []


class TestGetTestYaml:
    """Tests for JanitorClient.get_test_yaml()."""

    def test_basic(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "Tests:\n  - name: sanity\n    SubTests:\n      - name: test_1\n        status: PASS\n"
        client.session.get = MagicMock(return_value=resp)

        result = client.get_test_yaml(61009, "sanity-test")
        assert result is not None
        assert "Tests" in result

    def test_not_found(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        client.session.get = MagicMock(return_value=resp)

        result = client.get_test_yaml(99999, "test")
        assert result is None


class TestFetchLog:
    """Tests for JanitorClient.fetch_log()."""

    def test_basic(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        resp.iter_content = MagicMock(return_value=[b"line1\nline2\n"])
        client.session.get = MagicMock(return_value=resp)

        result = client.fetch_log(61009, "test-dir", "console.txt")
        assert result == "line1\nline2\n"

    def test_not_found(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 404
        client.session.get = MagicMock(return_value=resp)

        result = client.fetch_log(61009, "test-dir", "missing.txt")
        assert result is None

    def test_truncation(self):
        client = _make_client()
        resp = MagicMock()
        resp.status_code = 200
        # Return chunks totaling more than max_bytes
        resp.iter_content = MagicMock(return_value=[b"x" * 100, b"y" * 100])
        client.session.get = MagicMock(return_value=resp)

        result = client.fetch_log(61009, "test-dir", "big.txt", max_bytes=150)
        assert result is not None
        assert len(result) <= 150
