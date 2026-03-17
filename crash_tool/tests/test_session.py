"""Tests for crash_tool.session module."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from crash_tool.session import (
    CommandResult,
    SessionResult,
    _detect_error,
    _split_on_sentinels,
    find_crash_binary,
    run_session,
)


class TestFindCrashBinary:
    """Tests for find_crash_binary()."""

    @patch("shutil.which", return_value="/usr/bin/crash")
    def test_found_via_which(self, mock_which):
        assert find_crash_binary() == "/usr/bin/crash"
        mock_which.assert_called_once_with("crash")

    @patch("shutil.which", return_value=None)
    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=True)
    def test_found_via_fallback(self, mock_access, mock_isfile, mock_which):
        result = find_crash_binary()
        assert result == "/usr/bin/crash"

    @patch("shutil.which", return_value=None)
    @patch("os.path.isfile", return_value=False)
    def test_not_found_raises(self, mock_isfile, mock_which):
        with pytest.raises(FileNotFoundError, match="crash binary not found"):
            find_crash_binary()

    @patch("shutil.which", return_value=None)
    def test_fallback_checks_multiple_paths(self, mock_which):
        checked = []

        def fake_isfile(path):
            checked.append(path)
            return path == "/usr/local/bin/crash"

        with patch("os.path.isfile", side_effect=fake_isfile), \
             patch("os.access", return_value=True):
            result = find_crash_binary()

        assert result == "/usr/local/bin/crash"
        assert "/usr/bin/crash" in checked
        assert "/usr/sbin/crash" in checked

    @patch("shutil.which", return_value=None)
    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=False)
    def test_not_executable(self, mock_access, mock_isfile, mock_which):
        with pytest.raises(FileNotFoundError):
            find_crash_binary()


class TestSplitOnSentinels:
    """Tests for _split_on_sentinels()."""

    def test_empty_sentinels(self):
        assert _split_on_sentinels("hello", []) == ["hello"]

    def test_single_sentinel(self):
        output = "init stuff\n$1 = 7777000\ncommand output"
        chunks = _split_on_sentinels(output, ["7777000"])
        assert len(chunks) == 2
        assert "init stuff" in chunks[0]
        assert "command output" in chunks[1]

    def test_multiple_sentinels(self):
        output = (
            "init output\n"
            "$1 = 7777000\n"
            "cmd0 result\n"
            "$2 = 7777001\n"
            "cmd1 result\n"
            "$3 = 7777002\n"
        )
        chunks = _split_on_sentinels(output, ["7777000", "7777001", "7777002"])
        assert len(chunks) == 4
        assert "init output" in chunks[0]
        assert "cmd0 result" in chunks[1]
        assert "cmd1 result" in chunks[2]

    def test_sentinel_with_spaces(self):
        output = "before\n$42  =  7777000  \nafter"
        chunks = _split_on_sentinels(output, ["7777000"])
        assert len(chunks) == 2

    def test_no_sentinel_found(self):
        output = "no sentinels here"
        chunks = _split_on_sentinels(output, ["7777000"])
        assert len(chunks) == 1
        assert chunks[0] == output


class TestDetectError:
    """Tests for _detect_error()."""

    def test_no_error(self):
        assert _detect_error("PID: 1234  COMMAND: init") == ""

    def test_invalid_command(self):
        result = _detect_error("crash: invalid command: foobar")
        assert result == "invalid command"

    def test_cannot_resolve(self):
        result = _detect_error("crash: cannot resolve \"some_symbol\"")
        assert result == "symbol resolution failed"

    def test_cannot_read(self):
        result = _detect_error("crash: cannot read 0xdeadbeef")
        assert result == "memory read failed"

    def test_invalid_address(self):
        result = _detect_error("crash: invalid address: 0x0")
        assert result == "invalid address"

    def test_file_not_found(self):
        result = _detect_error("No such file or directory")
        assert result == "file not found"

    def test_not_in_namelist(self):
        result = _detect_error("crash: obd_devs not found in namelist")
        assert result == "symbol not in namelist"

    def test_invalid_task(self):
        result = _detect_error("bt: invalid task or pid value: 9999")
        assert result == "invalid task/pid"


class TestRunSession:
    """Tests for run_session()."""

    @patch("crash_tool.session.subprocess.run")
    def test_basic_session(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["crash", "-s"],
            returncode=0,
            stdout=(
                "crash init\n"
                "$1 = 7777000\n"
                "PID: 1  TASK: ffff  COMMAND: init\n"
                "$2 = 7777001\n"
            ),
            stderr="",
        )

        result = run_session(
            commands=["bt"],
            crash_binary="/usr/bin/crash",
        )

        assert isinstance(result, SessionResult)
        assert result.return_code == 0
        assert len(result.commands) == 1
        assert result.commands[0].command == "bt"
        assert "PID: 1" in result.commands[0].output
        assert result.commands[0].error is False

    @patch("crash_tool.session.subprocess.run")
    def test_multiple_commands(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["crash", "-s"],
            returncode=0,
            stdout=(
                "init\n"
                "$1 = 7777000\n"
                "sys output\n"
                "$2 = 7777001\n"
                "bt output\n"
                "$3 = 7777002\n"
            ),
            stderr="",
        )

        result = run_session(
            commands=["sys", "bt"],
            crash_binary="/usr/bin/crash",
        )

        assert len(result.commands) == 2
        assert result.commands[0].command == "sys"
        assert "sys output" in result.commands[0].output
        assert result.commands[1].command == "bt"
        assert "bt output" in result.commands[1].output

    @patch("crash_tool.session.subprocess.run")
    def test_error_in_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["crash", "-s"],
            returncode=0,
            stdout=(
                "init\n"
                "$1 = 7777000\n"
                "crash: invalid command: badcmd\n"
                "$2 = 7777001\n"
            ),
            stderr="",
        )

        result = run_session(
            commands=["badcmd"],
            crash_binary="/usr/bin/crash",
        )

        assert result.commands[0].error is True
        assert result.commands[0].error_message == "invalid command"

    @patch("crash_tool.session.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["crash"], timeout=120
        )

        result = run_session(
            commands=["bt", "ps"],
            crash_binary="/usr/bin/crash",
            timeout=120,
        )

        assert result.return_code == -1
        assert "timed out" in result.crash_stderr
        assert len(result.commands) == 2
        for cr in result.commands:
            assert cr.error is True
            assert "timed out" in cr.error_message

    @patch("crash_tool.session.subprocess.run")
    def test_crash_binary_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("No such file")

        result = run_session(
            commands=["bt"],
            crash_binary="/nonexistent/crash",
        )

        assert result.return_code == -1
        assert "not found" in result.crash_stderr

    @patch("crash_tool.session.subprocess.run")
    def test_no_sentinels_in_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["crash", "-s"],
            returncode=1,
            stdout="crash: unable to open vmcore\n",
            stderr="fatal error",
        )

        result = run_session(
            commands=["bt"],
            crash_binary="/usr/bin/crash",
        )

        assert result.return_code == 1
        assert len(result.commands) == 1
        assert result.commands[0].error is True

    @patch("crash_tool.session.subprocess.run")
    def test_vmlinux_vmcore_args(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(
            commands=["bt"],
            vmlinux="/boot/vmlinux",
            vmcore="/var/crash/vmcore",
            crash_binary="/usr/bin/crash",
        )

        call_args = mock_run.call_args
        argv = call_args[0][0]
        assert "/boot/vmlinux" in argv
        assert "/var/crash/vmcore" in argv

    @patch("crash_tool.session.subprocess.run")
    def test_minimal_flag(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(
            commands=["bt"],
            crash_binary="/usr/bin/crash",
            minimal=True,
        )

        argv = mock_run.call_args[0][0]
        assert "--minimal" in argv

    @patch("crash_tool.session.subprocess.run")
    def test_mod_dir(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(
            commands=["bt"],
            crash_binary="/usr/bin/crash",
            mod_dir="/path/to/kos",
        )

        input_text = mock_run.call_args[1]["input"]
        assert "mod -S /path/to/kos" in input_text

    @patch("crash_tool.session.subprocess.run")
    def test_pre_commands(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(
            commands=["bt"],
            crash_binary="/usr/bin/crash",
            pre_commands=["set scroll off"],
        )

        input_text = mock_run.call_args[1]["input"]
        assert "set scroll off" in input_text

    @patch("crash_tool.session.subprocess.run")
    def test_extra_args(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(
            commands=["bt"],
            crash_binary="/usr/bin/crash",
            extra_args=["--no_strip"],
        )

        argv = mock_run.call_args[0][0]
        assert "--no_strip" in argv

    @patch("crash_tool.session.find_crash_binary", return_value="/usr/bin/crash")
    @patch("crash_tool.session.subprocess.run")
    def test_auto_detect_binary(self, mock_run, mock_find):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(commands=["bt"])

        mock_find.assert_called_once()
        argv = mock_run.call_args[0][0]
        assert argv[0] == "/usr/bin/crash"

    @patch("crash_tool.session.subprocess.run")
    def test_missing_output_chunk(self, mock_run):
        """If crash exits early, some commands get no output."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="init\n$1 = 7777000\ncmd0 out\n",
            stderr="",
        )

        result = run_session(
            commands=["bt", "ps"],
            crash_binary="/usr/bin/crash",
        )

        assert len(result.commands) == 2
        assert result.commands[0].output == "cmd0 out"
        # Second command should report error (no output captured)
        assert result.commands[1].error is True

    @patch("crash_tool.session.subprocess.run")
    def test_input_has_quit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="$1 = 7777000\nok\n$2 = 7777001\n",
            stderr="",
        )

        run_session(commands=["bt"], crash_binary="/usr/bin/crash")

        input_text = mock_run.call_args[1]["input"]
        assert input_text.strip().endswith("quit")


class TestDataclasses:
    """Tests for CommandResult and SessionResult dataclasses."""

    def test_command_result_defaults(self):
        cr = CommandResult(command="bt", output="some output")
        assert cr.error is False
        assert cr.error_message == ""

    def test_command_result_with_error(self):
        cr = CommandResult(
            command="bt", output="", error=True,
            error_message="crash: invalid command"
        )
        assert cr.error is True

    def test_session_result_defaults(self):
        sr = SessionResult()
        assert sr.commands == []
        assert sr.init_output == ""
        assert sr.crash_stderr == ""
        assert sr.return_code == 0
