"""Tests for the tmux_vim module."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from gerrit_cli.tmux_vim import (
    SessionState,
    TmuxConfig,
    TmuxController,
    TmuxVimSession,
    VimController,
)


class TestTmuxConfig:
    """Tests for TmuxConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TmuxConfig()
        assert config.session_name == "gerrit-review"
        assert config.vim_pane_width_percent == 60
        assert config.vim_server_name == "GERRIT"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TmuxConfig(
            session_name="my-review",
            vim_pane_width_percent=70,
            vim_server_name="MYSERVER",
        )
        assert config.session_name == "my-review"
        assert config.vim_pane_width_percent == 70
        assert config.vim_server_name == "MYSERVER"


class TestTmuxController:
    """Tests for TmuxController."""

    @pytest.fixture
    def controller(self):
        """Create a TmuxController for testing."""
        return TmuxController()

    @pytest.fixture
    def mock_tmux_available(self, controller):
        """Mock tmux as available."""
        controller._tmux_bin = "/usr/bin/tmux"
        return controller

    def test_is_available_when_found(self):
        """Test is_available when tmux is installed."""
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            controller = TmuxController()
            assert controller.is_available() is True

    def test_is_available_when_not_found(self):
        """Test is_available when tmux is not installed."""
        with patch("shutil.which", return_value=None):
            controller = TmuxController()
            assert controller.is_available() is False

    def test_is_inside_tmux_true(self):
        """Test is_inside_tmux when TMUX env var is set."""
        controller = TmuxController()
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            assert controller.is_inside_tmux() is True

    def test_is_inside_tmux_false(self):
        """Test is_inside_tmux when TMUX env var is not set."""
        controller = TmuxController()
        with patch.dict(os.environ, {}, clear=True):
            # Remove TMUX if it exists
            os.environ.pop("TMUX", None)
            assert controller.is_inside_tmux() is False

    def test_get_current_session_not_in_tmux(self):
        """Test get_current_session when not in tmux."""
        controller = TmuxController()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TMUX", None)
            assert controller.get_current_session() is None

    def test_get_current_session_in_tmux(self, mock_tmux_available):
        """Test get_current_session when in tmux."""
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            with patch.object(
                mock_tmux_available, "_run_tmux", return_value="my-session\n"
            ):
                result = mock_tmux_available.get_current_session()
                assert result == "my-session"

    def test_session_exists_true(self, mock_tmux_available):
        """Test session_exists when session exists."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value=""):
            assert mock_tmux_available.session_exists("test-session") is True

    def test_session_exists_false(self, mock_tmux_available):
        """Test session_exists when session does not exist."""
        with patch.object(
            mock_tmux_available,
            "_run_tmux",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ):
            assert mock_tmux_available.session_exists("test-session") is False

    def test_create_session_success(self, mock_tmux_available):
        """Test successful session creation."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value=""):
            assert mock_tmux_available.create_session("new-session") is True

    def test_create_session_failure(self, mock_tmux_available):
        """Test failed session creation."""
        with patch.object(
            mock_tmux_available,
            "_run_tmux",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ):
            assert mock_tmux_available.create_session("new-session") is False

    def test_kill_session_success(self, mock_tmux_available):
        """Test successful session kill."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value=""):
            assert mock_tmux_available.kill_session("old-session") is True

    def test_kill_session_failure(self, mock_tmux_available):
        """Test failed session kill."""
        with patch.object(
            mock_tmux_available,
            "_run_tmux",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ):
            assert mock_tmux_available.kill_session("old-session") is False

    def test_split_window_horizontal(self, mock_tmux_available):
        """Test horizontal window split."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value="%5\n"):
            pane_id = mock_tmux_available.split_window_horizontal("test-session", 60)
            assert pane_id == "%5"

    def test_split_window_horizontal_failure(self, mock_tmux_available):
        """Test failed horizontal window split."""
        with patch.object(
            mock_tmux_available,
            "_run_tmux",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ):
            pane_id = mock_tmux_available.split_window_horizontal("test-session")
            assert pane_id is None

    def test_send_keys_success(self, mock_tmux_available):
        """Test successful send_keys."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value=""):
            assert mock_tmux_available.send_keys("ls\n", "%1") is True

    def test_send_keys_literal(self, mock_tmux_available):
        """Test send_keys with literal flag."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value="") as mock:
            mock_tmux_available.send_keys("hello", "%1", literal=True)
            # Verify -l flag was included
            call_args = mock.call_args[0][0]
            assert "-l" in call_args

    def test_select_pane_success(self, mock_tmux_available):
        """Test successful pane selection."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value=""):
            assert mock_tmux_available.select_pane("%1") is True

    def test_select_pane_failure(self, mock_tmux_available):
        """Test failed pane selection."""
        with patch.object(
            mock_tmux_available,
            "_run_tmux",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ):
            assert mock_tmux_available.select_pane("%99") is False

    def test_get_pane_ids(self, mock_tmux_available):
        """Test getting pane IDs."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value="%1\n%2\n%3\n"):
            panes = mock_tmux_available.get_pane_ids("test-session")
            assert panes == ["%1", "%2", "%3"]

    def test_get_pane_ids_empty(self, mock_tmux_available):
        """Test getting pane IDs when session has no panes."""
        with patch.object(
            mock_tmux_available,
            "_run_tmux",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ):
            panes = mock_tmux_available.get_pane_ids("nonexistent")
            assert panes == []

    def test_resize_pane(self, mock_tmux_available):
        """Test pane resizing."""
        with patch.object(mock_tmux_available, "_run_tmux", return_value="") as mock:
            assert mock_tmux_available.resize_pane("%1", width=80, height=24) is True
            call_args = mock.call_args[0][0]
            assert "-x" in call_args
            assert "80" in call_args
            assert "-y" in call_args
            assert "24" in call_args

    def test_run_tmux_without_binary(self):
        """Test _run_tmux raises when tmux not found."""
        controller = TmuxController()
        controller._tmux_bin = None
        with pytest.raises(RuntimeError, match="tmux not found"):
            controller._run_tmux(["list-sessions"])


class TestVimController:
    """Tests for VimController."""

    @pytest.fixture
    def controller(self):
        """Create a VimController for testing."""
        return VimController()

    @pytest.fixture
    def mock_vim_available(self, controller):
        """Mock vim as available."""
        controller._vim_bin = "/usr/bin/vim"
        return controller

    def test_is_available_when_found(self):
        """Test is_available when vim is installed."""
        with patch("shutil.which", return_value="/usr/bin/vim"):
            controller = VimController()
            assert controller.is_available() is True

    def test_is_available_when_not_found(self):
        """Test is_available when vim is not installed."""
        with patch("shutil.which", return_value=None):
            controller = VimController()
            assert controller.is_available() is False

    def test_has_clientserver_true(self, mock_vim_available):
        """Test has_clientserver when vim has the feature."""
        mock_result = MagicMock()
        mock_result.stdout = "VIM - Vi IMproved 8.2\n+clientserver\n+clipboard"
        with patch("subprocess.run", return_value=mock_result):
            assert mock_vim_available.has_clientserver() is True

    def test_has_clientserver_false(self, mock_vim_available):
        """Test has_clientserver when vim lacks the feature."""
        mock_result = MagicMock()
        mock_result.stdout = "VIM - Vi IMproved 8.2\n-clientserver\n+clipboard"
        with patch("subprocess.run", return_value=mock_result):
            assert mock_vim_available.has_clientserver() is False

    def test_has_clientserver_no_vim(self):
        """Test has_clientserver when vim not available."""
        controller = VimController()
        controller._vim_bin = None
        assert controller.has_clientserver() is False

    def test_is_server_running_true(self, mock_vim_available):
        """Test is_server_running when server is running."""
        mock_result = MagicMock()
        mock_result.stdout = "GERRIT\nOTHER\n"
        with patch("subprocess.run", return_value=mock_result):
            assert mock_vim_available.is_server_running() is True

    def test_is_server_running_false(self, mock_vim_available):
        """Test is_server_running when server is not running."""
        mock_result = MagicMock()
        mock_result.stdout = "OTHER\nANOTHER\n"
        with patch("subprocess.run", return_value=mock_result):
            assert mock_vim_available.is_server_running() is False

    def test_is_server_running_case_insensitive(self, mock_vim_available):
        """Test is_server_running is case insensitive."""
        mock_result = MagicMock()
        mock_result.stdout = "gerrit\n"
        with patch("subprocess.run", return_value=mock_result):
            assert mock_vim_available.is_server_running() is True

    def test_get_start_command_basic(self, mock_vim_available):
        """Test get_start_command with no file."""
        cmd = mock_vim_available.get_start_command()
        assert cmd == ["/usr/bin/vim", "--servername", "GERRIT"]

    def test_get_start_command_with_file(self, mock_vim_available):
        """Test get_start_command with file."""
        cmd = mock_vim_available.get_start_command("test.c")
        assert cmd == ["/usr/bin/vim", "--servername", "GERRIT", "test.c"]

    def test_get_start_command_with_file_and_line(self, mock_vim_available):
        """Test get_start_command with file and line."""
        cmd = mock_vim_available.get_start_command("test.c", 42)
        assert cmd == ["/usr/bin/vim", "--servername", "GERRIT", "+42", "test.c"]

    def test_get_start_command_string(self, mock_vim_available):
        """Test get_start_command_string."""
        cmd_str = mock_vim_available.get_start_command_string("test.c", 42)
        assert cmd_str == '/usr/bin/vim --servername GERRIT +42 test.c'

    def test_get_start_command_string_quotes_spaces(self, mock_vim_available):
        """Test get_start_command_string quotes paths with spaces."""
        cmd_str = mock_vim_available.get_start_command_string("my file.c", 42)
        assert '"my file.c"' in cmd_str

    def test_send_command_success(self, mock_vim_available):
        """Test successful send_command."""
        with patch("subprocess.run") as mock_run:
            assert mock_vim_available.send_command("e test.c") is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "--remote-send" in call_args

    def test_send_command_failure(self, mock_vim_available):
        """Test failed send_command."""
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "vim")):
            assert mock_vim_available.send_command("e test.c") is False

    def test_send_command_no_vim(self):
        """Test send_command when vim not available."""
        controller = VimController()
        controller._vim_bin = None
        assert controller.send_command("test") is False

    def test_open_file(self, mock_vim_available):
        """Test open_file method."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.open_file("test.c", 42)
            assert result is True
            # Should call send_command multiple times (edit, line number, zz)
            assert mock.call_count >= 1

    def test_jump_to_line(self, mock_vim_available):
        """Test jump_to_line method."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.jump_to_line(42, center=True)
            assert result is True
            # Should call for line number and zz
            assert mock.call_count == 2

    def test_jump_to_line_no_center(self, mock_vim_available):
        """Test jump_to_line without centering."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.jump_to_line(42, center=False)
            assert result is True
            assert mock.call_count == 1

    def test_highlight_lines(self, mock_vim_available):
        """Test highlight_lines method."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.highlight_lines(10, 15)
            assert result is True
            call_arg = mock.call_args[0][0]
            assert "matchadd" in call_arg

    def test_highlight_lines_single_line(self, mock_vim_available):
        """Test highlight_lines with single line (no end_line)."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.highlight_lines(42)
            assert result is True
            call_arg = mock.call_args[0][0]
            assert "matchadd" in call_arg
            # Pattern should highlight just line 42
            assert "41" in call_arg  # >41 (start-1)
            assert "43" in call_arg  # <43 (end+1)

    def test_highlight_lines_custom_group(self, mock_vim_available):
        """Test highlight_lines with custom highlight group."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.highlight_lines(10, 20, highlight_group="Error")
            assert result is True
            call_arg = mock.call_args[0][0]
            assert "Error" in call_arg

    def test_highlight_lines_pattern_format(self, mock_vim_available):
        """Test highlight_lines generates correct vim pattern."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            mock_vim_available.highlight_lines(5, 10)
            call_arg = mock.call_args[0][0]
            # Pattern format: \%>4l\%<11l (lines 5-10)
            assert "\\%>4l" in call_arg
            assert "\\%<11l" in call_arg

    def test_clear_highlights(self, mock_vim_available):
        """Test clear_highlights method."""
        with patch.object(mock_vim_available, "send_command", return_value=True) as mock:
            result = mock_vim_available.clear_highlights()
            assert result is True
            mock.assert_called_once_with("call clearmatches()")


class TestSessionState:
    """Tests for SessionState dataclass."""

    def test_default_state(self):
        """Test default session state."""
        state = SessionState()
        assert state.is_active is False
        assert state.session_name is None
        assert state.comment_pane_id is None
        assert state.vim_pane_id is None
        assert state.current_file is None
        assert state.current_line is None

    def test_active_state(self):
        """Test active session state."""
        state = SessionState(
            is_active=True,
            session_name="test-session",
            comment_pane_id="%1",
            vim_pane_id="%2",
            current_file="test.c",
            current_line=42,
        )
        assert state.is_active is True
        assert state.session_name == "test-session"
        assert state.vim_pane_id == "%2"


class TestTmuxVimSession:
    """Tests for TmuxVimSession."""

    @pytest.fixture
    def session(self):
        """Create a TmuxVimSession for testing."""
        return TmuxVimSession()

    @pytest.fixture
    def mock_session(self, session):
        """Create a session with mocked controllers."""
        session.tmux = MagicMock()
        session.vim = MagicMock()
        return session

    def test_init_default_config(self):
        """Test initialization with default config."""
        session = TmuxVimSession()
        assert session.config.session_name == "gerrit-review"
        assert session.state.is_active is False

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = TmuxConfig(session_name="custom", vim_pane_width_percent=50)
        session = TmuxVimSession(config)
        assert session.config.session_name == "custom"
        assert session.config.vim_pane_width_percent == 50

    def test_check_requirements_all_met(self, mock_session):
        """Test check_requirements when all requirements are met."""
        mock_session.tmux.is_available.return_value = True
        mock_session.vim.is_available.return_value = True
        mock_session.vim.has_clientserver.return_value = True

        ok, msg = mock_session.check_requirements()
        assert ok is True
        assert "requirements met" in msg.lower()

    def test_check_requirements_no_tmux(self, mock_session):
        """Test check_requirements when tmux is not available."""
        mock_session.tmux.is_available.return_value = False
        mock_session.vim.is_available.return_value = True
        mock_session.vim.has_clientserver.return_value = True

        ok, msg = mock_session.check_requirements()
        assert ok is False
        assert "tmux" in msg.lower()

    def test_check_requirements_no_vim(self, mock_session):
        """Test check_requirements when vim is not available."""
        mock_session.tmux.is_available.return_value = True
        mock_session.vim.is_available.return_value = False

        ok, msg = mock_session.check_requirements()
        assert ok is False
        assert "vim" in msg.lower()

    def test_check_requirements_no_clientserver(self, mock_session):
        """Test check_requirements when vim lacks clientserver."""
        mock_session.tmux.is_available.return_value = True
        mock_session.vim.is_available.return_value = True
        mock_session.vim.has_clientserver.return_value = False

        ok, msg = mock_session.check_requirements()
        assert ok is False
        assert "clientserver" in msg.lower()

    def test_is_inside_tmux(self, mock_session):
        """Test is_inside_tmux delegation."""
        mock_session.tmux.is_inside_tmux.return_value = True
        assert mock_session.is_inside_tmux() is True

        mock_session.tmux.is_inside_tmux.return_value = False
        assert mock_session.is_inside_tmux() is False

    def test_setup_session_requirements_not_met(self, mock_session):
        """Test setup_session when requirements not met."""
        mock_session.tmux.is_available.return_value = False

        ok, msg = mock_session.setup_session()
        assert ok is False

    def test_setup_session_not_in_tmux(self, mock_session):
        """Test setup_session when not inside tmux."""
        mock_session.tmux.is_available.return_value = True
        mock_session.vim.is_available.return_value = True
        mock_session.vim.has_clientserver.return_value = True
        mock_session.tmux.is_inside_tmux.return_value = False

        ok, msg = mock_session.setup_session()
        assert ok is False
        assert "tmux" in msg.lower()

    def test_setup_session_inside_tmux(self, mock_session):
        """Test setup_session when inside tmux."""
        mock_session.tmux.is_available.return_value = True
        mock_session.vim.is_available.return_value = True
        mock_session.vim.has_clientserver.return_value = True
        mock_session.tmux.is_inside_tmux.return_value = True
        mock_session.tmux.get_current_session.return_value = "my-session"
        mock_session.tmux.get_pane_ids.return_value = ["%1"]
        mock_session.tmux.split_window_horizontal.return_value = "%2"
        mock_session.vim.get_start_command_string.return_value = "vim --servername GERRIT"

        with patch("time.sleep"):  # Skip the sleep
            ok, msg = mock_session.setup_session()

        assert ok is True
        assert mock_session.state.is_active is True
        assert mock_session.state.session_name == "my-session"
        assert mock_session.state.comment_pane_id == "%1"
        assert mock_session.state.vim_pane_id == "%2"

    def test_setup_session_split_fails(self, mock_session):
        """Test setup_session when split fails."""
        mock_session.tmux.is_available.return_value = True
        mock_session.vim.is_available.return_value = True
        mock_session.vim.has_clientserver.return_value = True
        mock_session.tmux.is_inside_tmux.return_value = True
        mock_session.tmux.get_current_session.return_value = "my-session"
        mock_session.tmux.get_pane_ids.return_value = ["%1"]
        mock_session.tmux.split_window_horizontal.return_value = None  # Split fails

        ok, msg = mock_session.setup_session()
        assert ok is False
        assert "split" in msg.lower()

    def test_navigate_to_when_not_active(self, mock_session):
        """Test navigate_to when session not active."""
        mock_session.state.is_active = False
        result = mock_session.navigate_to("test.c", 42)
        assert result is False

    def test_navigate_to_success(self, mock_session):
        """Test successful navigate_to."""
        mock_session.state.is_active = True
        mock_session.vim.open_file.return_value = True
        mock_session.vim.clear_highlights.return_value = True
        mock_session.vim.highlight_lines.return_value = True

        result = mock_session.navigate_to("test.c", 42)

        assert result is True
        assert mock_session.state.current_file == "test.c"
        assert mock_session.state.current_line == 42
        mock_session.vim.open_file.assert_called_once_with("test.c", 42)
        # Should clear old highlights and add new one
        mock_session.vim.clear_highlights.assert_called_once()
        mock_session.vim.highlight_lines.assert_called_once_with(42)

    def test_navigate_to_with_highlight(self, mock_session):
        """Test navigate_to clears and sets highlights."""
        mock_session.state.is_active = True
        mock_session.vim.open_file.return_value = True
        mock_session.vim.clear_highlights.return_value = True
        mock_session.vim.highlight_lines.return_value = True

        result = mock_session.navigate_to("test.c", 100, highlight=True)

        assert result is True
        mock_session.vim.clear_highlights.assert_called_once()
        mock_session.vim.highlight_lines.assert_called_once_with(100)

    def test_navigate_to_without_highlight(self, mock_session):
        """Test navigate_to with highlight=False skips highlighting."""
        mock_session.state.is_active = True
        mock_session.vim.open_file.return_value = True

        result = mock_session.navigate_to("test.c", 42, highlight=False)

        assert result is True
        mock_session.vim.clear_highlights.assert_not_called()
        mock_session.vim.highlight_lines.assert_not_called()

    def test_navigate_to_no_line_no_highlight(self, mock_session):
        """Test navigate_to without line number doesn't highlight."""
        mock_session.state.is_active = True
        mock_session.vim.open_file.return_value = True
        mock_session.vim.clear_highlights.return_value = True

        result = mock_session.navigate_to("test.c", line=None, highlight=True)

        assert result is True
        # Should clear highlights but not add new one (no line specified)
        mock_session.vim.clear_highlights.assert_called_once()
        mock_session.vim.highlight_lines.assert_not_called()

    def test_navigate_to_failure(self, mock_session):
        """Test failed navigate_to."""
        mock_session.state.is_active = True
        mock_session.vim.open_file.return_value = False
        mock_session.vim.clear_highlights.return_value = True

        result = mock_session.navigate_to("test.c", 42)

        assert result is False
        assert mock_session.state.current_file is None
        # Should still clear highlights even if open fails
        mock_session.vim.clear_highlights.assert_called_once()
        # But should not add highlight since open failed
        mock_session.vim.highlight_lines.assert_not_called()

    def test_focus_vim_when_not_active(self, mock_session):
        """Test focus_vim when session not active."""
        mock_session.state.is_active = False
        assert mock_session.focus_vim() is False

    def test_focus_vim_success(self, mock_session):
        """Test successful focus_vim."""
        mock_session.state.is_active = True
        mock_session.state.vim_pane_id = "%2"
        mock_session.tmux.select_pane.return_value = True

        result = mock_session.focus_vim()

        assert result is True
        mock_session.tmux.select_pane.assert_called_once_with("%2")

    def test_focus_comments_when_not_active(self, mock_session):
        """Test focus_comments when session not active."""
        mock_session.state.is_active = False
        assert mock_session.focus_comments() is False

    def test_focus_comments_success(self, mock_session):
        """Test successful focus_comments."""
        mock_session.state.is_active = True
        mock_session.state.comment_pane_id = "%1"
        mock_session.tmux.select_pane.return_value = True

        result = mock_session.focus_comments()

        assert result is True
        mock_session.tmux.select_pane.assert_called_once_with("%1")

    def test_cleanup_when_not_active(self, mock_session):
        """Test cleanup when session not active."""
        mock_session.state.is_active = False
        result = mock_session.cleanup()
        assert result is True

    def test_cleanup_success(self, mock_session):
        """Test successful cleanup."""
        mock_session.state.is_active = True
        mock_session.state.vim_pane_id = "%2"
        mock_session.state.current_file = "test.c"
        mock_session.state.current_line = 42

        with patch("time.sleep"):  # Skip the sleep
            result = mock_session.cleanup()

        assert result is True
        assert mock_session.state.is_active is False
        assert mock_session.state.vim_pane_id is None
        assert mock_session.state.current_file is None
        assert mock_session.state.current_line is None
        mock_session.vim.send_command.assert_called_with("qa!")

    def test_highlight_line_when_not_active(self, mock_session):
        """Test highlight_line when session not active."""
        mock_session.state.is_active = False
        result = mock_session.highlight_line(42)
        assert result is False
        mock_session.vim.highlight_lines.assert_not_called()

    def test_highlight_line_success(self, mock_session):
        """Test successful highlight_line."""
        mock_session.state.is_active = True
        mock_session.vim.highlight_lines.return_value = True

        result = mock_session.highlight_line(42)

        assert result is True
        mock_session.vim.highlight_lines.assert_called_once_with(
            42, highlight_group="Search"
        )

    def test_highlight_line_custom_group(self, mock_session):
        """Test highlight_line with custom highlight group."""
        mock_session.state.is_active = True
        mock_session.vim.highlight_lines.return_value = True

        result = mock_session.highlight_line(42, highlight_group="Error")

        assert result is True
        mock_session.vim.highlight_lines.assert_called_once_with(
            42, highlight_group="Error"
        )

    def test_clear_highlights_when_not_active(self, mock_session):
        """Test clear_highlights when session not active."""
        mock_session.state.is_active = False
        result = mock_session.clear_highlights()
        assert result is False
        mock_session.vim.clear_highlights.assert_not_called()

    def test_clear_highlights_success(self, mock_session):
        """Test successful clear_highlights."""
        mock_session.state.is_active = True
        mock_session.vim.clear_highlights.return_value = True

        result = mock_session.clear_highlights()

        assert result is True
        mock_session.vim.clear_highlights.assert_called_once()

