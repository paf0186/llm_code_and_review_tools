"""Tests for the interactive_vim module."""

from unittest.mock import MagicMock, patch

import pytest

from gerrit_comments.interactive_vim import (
    InteractiveVimSession,
    run_interactive_vim,
)
from gerrit_comments.tmux_vim import TmuxConfig, TmuxVimSession


class TestInteractiveVimSession:
    """Tests for InteractiveVimSession."""

    @pytest.fixture
    def session(self):
        """Create an InteractiveVimSession for testing."""
        return InteractiveVimSession()

    @pytest.fixture
    def mock_session(self, session):
        """Create a session with mocked dependencies."""
        session.vim_session = MagicMock(spec=TmuxVimSession)
        session.series_finder = MagicMock()
        session.staging_manager = MagicMock()
        session.replier = MagicMock()
        return session

    def test_init_default(self):
        """Test initialization with defaults."""
        session = InteractiveVimSession()
        assert session._vim_active is False
        assert session.current_index == 0
        assert session.all_comments == []

    def test_init_with_config(self):
        """Test initialization with custom config."""
        config = TmuxConfig(session_name="custom")
        session = InteractiveVimSession(config)
        assert session.vim_session.config.session_name == "custom"

    def test_setup_vim_requirements_not_met(self, mock_session):
        """Test _setup_vim when requirements not met."""
        mock_session.vim_session.check_requirements.return_value = (
            False, "tmux not installed"
        )

        ok, msg = mock_session._setup_vim()

        assert ok is False
        assert "tmux" in msg.lower()

    def test_setup_vim_not_in_tmux(self, mock_session):
        """Test _setup_vim when not inside tmux."""
        mock_session.vim_session.check_requirements.return_value = (True, "OK")
        mock_session.vim_session.is_inside_tmux.return_value = False

        ok, msg = mock_session._setup_vim()

        assert ok is False
        assert "tmux" in msg.lower()

    def test_setup_vim_success(self, mock_session):
        """Test successful _setup_vim."""
        mock_session.vim_session.check_requirements.return_value = (True, "OK")
        mock_session.vim_session.is_inside_tmux.return_value = True
        mock_session.vim_session.setup_session.return_value = (True, "Setup complete")

        ok, msg = mock_session._setup_vim()

        assert ok is True
        assert mock_session._vim_active is True

    def test_cleanup_vim(self, mock_session):
        """Test _cleanup_vim."""
        mock_session._vim_active = True

        mock_session._cleanup_vim()

        assert mock_session._vim_active is False
        mock_session.vim_session.cleanup.assert_called_once()

    def test_cleanup_vim_when_not_active(self, mock_session):
        """Test _cleanup_vim when not active."""
        mock_session._vim_active = False

        mock_session._cleanup_vim()

        mock_session.vim_session.cleanup.assert_not_called()

    def test_navigate_to_current_empty_comments(self, mock_session):
        """Test _navigate_to_current with no comments."""
        mock_session.all_comments = []

        mock_session._navigate_to_current()

        mock_session.vim_session.navigate_to.assert_not_called()

    def test_navigate_to_current_with_file(self, mock_session):
        """Test _navigate_to_current navigates vim to file."""
        mock_thread = MagicMock()
        mock_thread.root_comment.file_path = "test.c"
        mock_thread.root_comment.line = 42
        mock_thread.root_comment.author = "Test User"
        mock_thread.root_comment.message = "Test message"
        mock_thread.replies = []

        mock_patch = MagicMock()
        mock_patch.subject = "Test subject"

        mock_session.all_comments = [{
            'patch': mock_patch,
            'thread': mock_thread,
            'change_number': 12345,
            'extracted': MagicMock(),
        }]
        mock_session.current_index = 0
        mock_session.total_comments = 1

        mock_session._navigate_to_current()

        mock_session.vim_session.navigate_to.assert_called_once_with("test.c", 42)

    def test_navigate_to_current_patchset_level(self, mock_session):
        """Test _navigate_to_current with patchset-level comment."""
        mock_thread = MagicMock()
        mock_thread.root_comment.file_path = "/PATCHSET_LEVEL"
        mock_thread.root_comment.line = None
        mock_thread.root_comment.author = "Test User"
        mock_thread.root_comment.message = "Test message"
        mock_thread.replies = []

        mock_patch = MagicMock()
        mock_patch.subject = "Test subject"

        mock_session.all_comments = [{
            'patch': mock_patch,
            'thread': mock_thread,
            'change_number': 12345,
            'extracted': MagicMock(),
        }]
        mock_session.current_index = 0
        mock_session.total_comments = 1

        mock_session._navigate_to_current()

        # Should not navigate for patchset-level comments
        mock_session.vim_session.navigate_to.assert_not_called()

    def test_get_action_next(self, mock_session):
        """Test 'n' action advances to next comment."""
        mock_session.all_comments = [MagicMock(), MagicMock()]
        mock_session.current_index = 0
        mock_session.total_comments = 2

        with patch.object(mock_session, '_navigate_to_current'):
            with patch('builtins.input', return_value='n'):
                result = mock_session._get_action()

        assert result == 'continue'
        assert mock_session.current_index == 1

    def test_get_action_next_at_last(self, mock_session):
        """Test 'n' action at last comment doesn't advance."""
        mock_session.all_comments = [MagicMock(), MagicMock()]
        mock_session.current_index = 1
        mock_session.total_comments = 2

        with patch('builtins.input', return_value='n'):
            result = mock_session._get_action()

        assert result == 'continue'
        assert mock_session.current_index == 1  # Unchanged

    def test_get_action_prev(self, mock_session):
        """Test 'p' action goes to previous comment."""
        mock_session.all_comments = [MagicMock(), MagicMock()]
        mock_session.current_index = 1
        mock_session.total_comments = 2

        with patch.object(mock_session, '_navigate_to_current'):
            with patch('builtins.input', return_value='p'):
                result = mock_session._get_action()

        assert result == 'continue'
        assert mock_session.current_index == 0

    def test_get_action_prev_at_first(self, mock_session):
        """Test 'p' action at first comment doesn't go back."""
        mock_session.all_comments = [MagicMock(), MagicMock()]
        mock_session.current_index = 0
        mock_session.total_comments = 2

        with patch('builtins.input', return_value='p'):
            result = mock_session._get_action()

        assert result == 'continue'
        assert mock_session.current_index == 0  # Unchanged

    def test_get_action_goto(self, mock_session):
        """Test 'g' action goes to specific comment."""
        mock_session.all_comments = [MagicMock(), MagicMock(), MagicMock()]
        mock_session.current_index = 0
        mock_session.total_comments = 3

        with patch.object(mock_session, '_navigate_to_current'):
            with patch('builtins.input', side_effect=['g', '3']):
                result = mock_session._get_action()

        assert result == 'continue'
        assert mock_session.current_index == 2

    def test_get_action_focus_vim(self, mock_session):
        """Test 'f' action focuses vim pane."""
        mock_session.all_comments = [MagicMock()]

        with patch('builtins.input', return_value='f'):
            result = mock_session._get_action()

        assert result == 'continue'
        mock_session.vim_session.focus_vim.assert_called_once()

    def test_get_action_quit(self, mock_session):
        """Test 'q' action returns quit."""
        with patch('builtins.input', return_value='q'):
            result = mock_session._get_action()

        assert result == 'quit'

    def test_get_action_help(self, mock_session):
        """Test 'h' action prints help."""
        with patch.object(mock_session, '_print_help') as mock_help:
            with patch('builtins.input', return_value='h'):
                result = mock_session._get_action()

        assert result == 'continue'
        mock_help.assert_called_once()

    def test_get_action_unknown(self, mock_session):
        """Test unknown action is handled."""
        with patch('builtins.input', return_value='x'):
            result = mock_session._get_action()

        assert result == 'continue'

    def test_get_action_keyboard_interrupt(self, mock_session):
        """Test KeyboardInterrupt is handled."""
        with patch('builtins.input', side_effect=KeyboardInterrupt):
            result = mock_session._get_action()

        assert result == 'quit'

    def test_get_action_eof(self, mock_session):
        """Test EOFError is handled."""
        with patch('builtins.input', side_effect=EOFError):
            result = mock_session._get_action()

        assert result == 'quit'

    def test_handle_done(self, mock_session):
        """Test _handle_done stages a done reply."""
        mock_extracted = MagicMock()
        mock_thread = MagicMock()
        mock_extracted.threads = [mock_thread]

        mock_session.all_comments = [{
            'patch': MagicMock(),
            'thread': mock_thread,
            'change_number': 12345,
            'extracted': mock_extracted,
        }]
        mock_session.current_index = 0
        mock_session.total_comments = 1

        with patch.object(mock_session, '_stage_reply') as mock_stage:
            with patch.object(mock_session, '_navigate_to_current'):
                with patch('builtins.input', return_value=''):
                    mock_session._handle_done()

        mock_stage.assert_called_once()
        assert mock_session.staged_count == 1

    def test_handle_reply(self, mock_session):
        """Test _handle_reply stages a reply."""
        mock_extracted = MagicMock()
        mock_thread = MagicMock()
        mock_extracted.threads = [mock_thread]

        mock_session.all_comments = [{
            'patch': MagicMock(),
            'thread': mock_thread,
            'change_number': 12345,
            'extracted': mock_extracted,
        }]
        mock_session.current_index = 0
        mock_session.total_comments = 1

        with patch.object(mock_session, '_stage_reply') as mock_stage:
            with patch.object(mock_session, '_navigate_to_current'):
                with patch('builtins.input', side_effect=['Test reply', 'n']):
                    mock_session._handle_reply()

        mock_stage.assert_called_once()
        # Check the message was passed
        call_args = mock_stage.call_args[0]
        assert call_args[2] == 12345  # change_number
        assert call_args[3] == 'Test reply'  # message
        assert call_args[4] is False  # resolve (answered 'n')

    def test_handle_reply_cancelled(self, mock_session):
        """Test _handle_reply with empty message cancels."""
        mock_session.all_comments = [MagicMock()]
        mock_session.current_index = 0

        with patch.object(mock_session, '_stage_reply') as mock_stage:
            with patch('builtins.input', return_value=''):
                mock_session._handle_reply()

        mock_stage.assert_not_called()

    def test_handle_ack(self, mock_session):
        """Test _handle_ack stages an acknowledgment."""
        mock_extracted = MagicMock()
        mock_thread = MagicMock()
        mock_extracted.threads = [mock_thread]

        mock_session.all_comments = [{
            'patch': MagicMock(),
            'thread': mock_thread,
            'change_number': 12345,
            'extracted': mock_extracted,
        }]
        mock_session.current_index = 0
        mock_session.total_comments = 1

        with patch.object(mock_session, '_stage_reply') as mock_stage:
            with patch.object(mock_session, '_navigate_to_current'):
                with patch('builtins.input', return_value=''):
                    mock_session._handle_ack()

        mock_stage.assert_called_once()
        call_args = mock_stage.call_args[0]
        assert call_args[3] == 'Acknowledged'  # message

    def test_handle_skip(self, mock_session):
        """Test _handle_skip advances to next comment."""
        mock_session.all_comments = [MagicMock(), MagicMock()]
        mock_session.current_index = 0
        mock_session.total_comments = 2

        with patch.object(mock_session, '_navigate_to_current'):
            mock_session._handle_skip()

        assert mock_session.skipped_count == 1
        assert mock_session.current_index == 1

    def test_handle_edit_success(self, mock_session):
        """Test _handle_edit with successful edit start."""
        mock_session.all_comments = [{
            'patch': MagicMock(),
            'thread': MagicMock(),
            'change_number': 12345,
            'extracted': MagicMock(),
        }]
        mock_session.current_index = 0

        with patch('gerrit_comments.interactive_vim.work_on_patch', return_value=(True, "Started")):
            result = mock_session._handle_edit()

        assert result == 'quit'

    def test_handle_edit_failure(self, mock_session):
        """Test _handle_edit with failed edit start."""
        mock_session.all_comments = [{
            'patch': MagicMock(),
            'thread': MagicMock(),
            'change_number': 12345,
            'extracted': MagicMock(),
        }]
        mock_session.current_index = 0

        with patch('gerrit_comments.interactive_vim.work_on_patch', return_value=(False, "Failed")):
            result = mock_session._handle_edit()

        assert result == 'continue'


class TestRunInteractiveVim:
    """Tests for run_interactive_vim function."""

    def test_run_interactive_vim(self):
        """Test run_interactive_vim creates session and runs."""
        with patch.object(InteractiveVimSession, 'run_series') as mock_run:
            run_interactive_vim("https://example.com/12345")

        mock_run.assert_called_once_with("https://example.com/12345")

    def test_run_interactive_vim_with_config(self):
        """Test run_interactive_vim with custom config."""
        config = TmuxConfig(session_name="custom")

        with patch.object(InteractiveVimSession, '__init__', return_value=None) as mock_init:
            with patch.object(InteractiveVimSession, 'run_series'):
                run_interactive_vim("https://example.com/12345", config)

        mock_init.assert_called_once_with(config)

