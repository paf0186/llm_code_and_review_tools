"""Tests for the session module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from gerrit_comments.reintegration import ReintegrationState
from gerrit_comments.session import RebaseSession, SessionManager


class TestRebaseSession:
    """Tests for RebaseSession dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        session = RebaseSession(
            series_url="http://test",
            target_change=123,
            target_commit="abc123",
            original_head="def456",
            original_branch="main",
            series_patches=[],
            started_at="2026-01-17T10:00:00",
        )

        assert session.rebased_changes == []
        assert session.skipped_changes == []
        assert session.pending_cherry_pick is None
        assert session.reintegration is not None
        assert session.reintegrating is False

    def test_to_dict(self):
        """Test converting to dict."""
        session = RebaseSession(
            series_url="http://test",
            target_change=123,
            target_commit="abc123",
            original_head="def456",
            original_branch="main",
            series_patches=[{"change_number": 100}],
            started_at="2026-01-17T10:00:00",
            rebased_changes=[101, 102],
        )

        d = session.to_dict()

        assert d['series_url'] == "http://test"
        assert d['target_change'] == 123
        assert d['rebased_changes'] == [101, 102]

    def test_from_dict(self):
        """Test creating from dict."""
        d = {
            'series_url': "http://test",
            'target_change': 456,
            'target_commit': "xyz789",
            'original_head': "head123",
            'original_branch': "feature",
            'series_patches': [],
            'started_at': "2026-01-17T11:00:00",
        }

        session = RebaseSession.from_dict(d)

        assert session.series_url == "http://test"
        assert session.target_change == 456
        assert session.rebased_changes == []
        assert session.skipped_changes == []

    def test_reintegrating_property(self):
        """Test reintegrating property."""
        session = RebaseSession(
            series_url="http://test",
            target_change=123,
            target_commit="abc123",
            original_head="def456",
            original_branch="main",
            series_patches=[],
            started_at="2026-01-17T10:00:00",
            reintegration={'active': True, 'stale_changes': [],
                          'current_stale_idx': 0, 'pending_descendants': []},
        )

        assert session.reintegrating is True

    def test_reintegration_state_property(self):
        """Test reintegration_state property."""
        session = RebaseSession(
            series_url="http://test",
            target_change=123,
            target_commit="abc123",
            original_head="def456",
            original_branch="main",
            series_patches=[],
            started_at="2026-01-17T10:00:00",
            reintegration={'active': True, 'stale_changes': [{'change_number': 100}],
                          'current_stale_idx': 0, 'pending_descendants': [101]},
        )

        state = session.reintegration_state

        assert isinstance(state, ReintegrationState)
        assert state.active is True
        assert state.pending_descendants == [101]

    def test_update_reintegration(self):
        """Test updating reintegration state."""
        session = RebaseSession(
            series_url="http://test",
            target_change=123,
            target_commit="abc123",
            original_head="def456",
            original_branch="main",
            series_patches=[],
            started_at="2026-01-17T10:00:00",
        )

        new_state = ReintegrationState(
            active=True,
            stale_changes=[{'change_number': 200}],
            current_stale_idx=1,
            pending_descendants=[201, 202],
        )
        session.update_reintegration(new_state)

        assert session.reintegrating is True
        assert session.reintegration_state.pending_descendants == [201, 202]


class TestSessionManager:
    """Tests for SessionManager class."""

    def test_init_default_dir(self):
        """Test initialization with default directory."""
        with patch('gerrit_comments.session.Path.cwd') as mock_cwd:
            mock_cwd.return_value = Path('/test/dir')
            with patch.object(Path, 'mkdir'):
                mgr = SessionManager()

        assert mgr.state_dir == Path('/test/dir') / ".gerrit-comments"

    def test_init_custom_dir(self):
        """Test initialization with custom directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "custom-state"
            mgr = SessionManager(state_dir=state_dir)

            assert mgr.state_dir == state_dir
            assert state_dir.exists()

    def test_has_active_session_no_file(self):
        """Test has_active_session when no session file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))

            assert mgr.has_active_session() is False

    def test_has_active_session_with_file(self):
        """Test has_active_session when session file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))
            mgr.state_file.touch()

            assert mgr.has_active_session() is True

    def test_save_and_load(self):
        """Test saving and loading a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))

            session = RebaseSession(
                series_url="http://test/123",
                target_change=123,
                target_commit="abc123",
                original_head="def456",
                original_branch="main",
                series_patches=[{"change_number": 100, "subject": "Test"}],
                started_at="2026-01-17T10:00:00",
                rebased_changes=[101],
            )

            mgr.save(session)

            assert mgr.state_file.exists()

            loaded = mgr.load()

            assert loaded is not None
            assert loaded.series_url == "http://test/123"
            assert loaded.target_change == 123
            assert loaded.rebased_changes == [101]

    def test_load_no_file(self):
        """Test loading when no session file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))

            loaded = mgr.load()

            assert loaded is None

    def test_load_invalid_json(self):
        """Test loading when session file has invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))
            mgr.state_file.write_text("not valid json {{{")

            loaded = mgr.load()

            assert loaded is None

    def test_clear_removes_file(self):
        """Test that clear removes the session file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))
            mgr.state_file.touch()

            assert mgr.state_file.exists()

            mgr.clear()

            assert not mgr.state_file.exists()

    def test_clear_no_file(self):
        """Test that clear handles missing file gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))

            # Should not raise
            mgr.clear()

            assert not mgr.state_file.exists()

    def test_roundtrip_with_reintegration(self):
        """Test saving and loading session with reintegration state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(state_dir=Path(tmpdir))

            session = RebaseSession(
                series_url="http://test",
                target_change=123,
                target_commit="abc123",
                original_head="def456",
                original_branch="main",
                series_patches=[],
                started_at="2026-01-17T10:00:00",
                reintegration={
                    'active': True,
                    'stale_changes': [{'change_number': 100, 'subject': 'Test'}],
                    'current_stale_idx': 0,
                    'pending_descendants': [101, 102],
                },
            )

            mgr.save(session)
            loaded = mgr.load()

            assert loaded.reintegrating is True
            state = loaded.reintegration_state
            assert state.active is True
            assert len(state.stale_changes) == 1
            assert state.pending_descendants == [101, 102]

