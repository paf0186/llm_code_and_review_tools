"""Tests for the reintegration module."""


from gerrit_cli.reintegration import (
    ReintegrationManager,
    ReintegrationState,
    StaleChangeInfo,
)


class TestStaleChangeInfo:
    """Tests for StaleChangeInfo dataclass."""

    def test_to_dict(self):
        """Test converting to dict."""
        info = StaleChangeInfo(
            change_number=123,
            old_revision=1,
            current_revision=2,
            subject="Test change",
        )
        d = info.to_dict()
        assert d == {
            'change_number': 123,
            'old_revision': 1,
            'current_revision': 2,
            'subject': "Test change",
        }

    def test_from_dict(self):
        """Test creating from dict."""
        d = {
            'change_number': 456,
            'old_revision': 3,
            'current_revision': 5,
            'subject': "Another change",
        }
        info = StaleChangeInfo.from_dict(d)
        assert info.change_number == 456
        assert info.old_revision == 3
        assert info.current_revision == 5
        assert info.subject == "Another change"


class TestReintegrationState:
    """Tests for ReintegrationState dataclass."""

    def test_default_values(self):
        """Test default values."""
        state = ReintegrationState()
        assert state.active is False
        assert state.stale_changes == []
        assert state.current_stale_idx == 0
        assert state.pending_descendants == []

    def test_to_dict(self):
        """Test converting to dict."""
        state = ReintegrationState(
            active=True,
            stale_changes=[{'change_number': 101}],
            current_stale_idx=1,
            pending_descendants=[102, 103],
        )
        d = state.to_dict()
        assert d['active'] is True
        assert d['stale_changes'] == [{'change_number': 101}]
        assert d['current_stale_idx'] == 1
        assert d['pending_descendants'] == [102, 103]

    def test_from_dict(self):
        """Test creating from dict."""
        d = {
            'active': True,
            'stale_changes': [{'change_number': 200}],
            'current_stale_idx': 2,
            'pending_descendants': [201],
        }
        state = ReintegrationState.from_dict(d)
        assert state.active is True
        assert state.stale_changes == [{'change_number': 200}]
        assert state.current_stale_idx == 2
        assert state.pending_descendants == [201]

    def test_current_stale(self):
        """Test current_stale property."""
        state = ReintegrationState(
            active=True,
            stale_changes=[
                {'change_number': 101, 'subject': 'First'},
                {'change_number': 102, 'subject': 'Second'},
            ],
            current_stale_idx=0,
        )
        assert state.current_stale['change_number'] == 101

        state.current_stale_idx = 1
        assert state.current_stale['change_number'] == 102

    def test_current_stale_out_of_bounds(self):
        """Test current_stale when index is out of bounds."""
        state = ReintegrationState(
            active=True,
            stale_changes=[{'change_number': 101}],
            current_stale_idx=5,
        )
        assert state.current_stale is None

    def test_is_complete(self):
        """Test is_complete property."""
        state = ReintegrationState(
            active=True,
            stale_changes=[{'change_number': 101}],
            current_stale_idx=0,
        )
        assert state.is_complete is False

        state.current_stale_idx = 1
        assert state.is_complete is True


class TestReintegrationManager:
    """Tests for ReintegrationManager class."""

    def test_create_state(self):
        """Test creating initial reintegration state."""
        manager = ReintegrationManager()

        stale_info = [
            StaleChangeInfo(
                change_number=101,
                old_revision=1,
                current_revision=2,
                subject="Stale change",
            ),
        ]
        series_patches = [
            {'change_number': 100, 'subject': 'Base'},
            {'change_number': 101, 'subject': 'Stale change'},
            {'change_number': 102, 'subject': 'Descendant 1'},
            {'change_number': 103, 'subject': 'Descendant 2'},
        ]

        state, descendants = manager.create_state(stale_info, series_patches)

        assert state.active is True
        assert len(state.stale_changes) == 1
        assert state.stale_changes[0]['change_number'] == 101
        assert state.current_stale_idx == 0
        assert descendants == [102, 103]
        assert state.pending_descendants == [102, 103]

    def test_find_descendants(self):
        """Test finding descendants of a stale change."""
        manager = ReintegrationManager()

        series_patches = [
            {'change_number': 100, 'subject': 'Base'},
            {'change_number': 101, 'subject': 'Middle'},
            {'change_number': 102, 'subject': 'Tip'},
        ]

        descendants = manager._find_descendants(100, series_patches)
        assert descendants == [101, 102]

        descendants = manager._find_descendants(101, series_patches)
        assert descendants == [102]

        descendants = manager._find_descendants(102, series_patches)
        assert descendants == []

    def test_find_descendants_not_found(self):
        """Test finding descendants when change not in series."""
        manager = ReintegrationManager()

        series_patches = [
            {'change_number': 100, 'subject': 'Base'},
        ]

        descendants = manager._find_descendants(999, series_patches)
        assert descendants == []

    def test_get_next_descendant(self):
        """Test getting next descendant to cherry-pick."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            pending_descendants=[102, 103, 104],
        )

        assert manager.get_next_descendant(state) == 102

    def test_get_next_descendant_empty(self):
        """Test getting next descendant when none pending."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            pending_descendants=[],
        )

        assert manager.get_next_descendant(state) is None

    def test_mark_descendant_done(self):
        """Test marking a descendant as done."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            pending_descendants=[102, 103, 104],
        )
        rebased = []

        manager.mark_descendant_done(state, 102, rebased)

        assert 102 not in state.pending_descendants
        assert 102 in rebased
        assert state.pending_descendants == [103, 104]

    def test_mark_descendant_done_already_rebased(self):
        """Test marking a descendant that's already in rebased list."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            pending_descendants=[102],
        )
        rebased = [102]  # Already there

        manager.mark_descendant_done(state, 102, rebased)

        # Should not duplicate
        assert rebased.count(102) == 1

    def test_mark_descendant_skipped(self):
        """Test marking a descendant as skipped."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            pending_descendants=[102, 103],
        )
        skipped = []

        manager.mark_descendant_skipped(state, 102, skipped)

        assert 102 not in state.pending_descendants
        assert 102 in skipped
        assert state.pending_descendants == [103]

    def test_advance_to_next_stale(self):
        """Test advancing to next stale change."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            stale_changes=[
                {'change_number': 101, 'subject': 'First stale'},
                {'change_number': 103, 'subject': 'Second stale'},
            ],
            current_stale_idx=0,
            pending_descendants=[],
        )
        series_patches = [
            {'change_number': 100, 'subject': 'Base'},
            {'change_number': 101, 'subject': 'First stale'},
            {'change_number': 102, 'subject': 'Middle'},
            {'change_number': 103, 'subject': 'Second stale'},
            {'change_number': 104, 'subject': 'Tip'},
        ]

        has_more = manager.advance_to_next_stale(state, series_patches)

        assert has_more is True
        assert state.current_stale_idx == 1
        assert state.pending_descendants == [104]

    def test_advance_to_next_stale_complete(self):
        """Test advancing when all stale changes are done."""
        manager = ReintegrationManager()

        state = ReintegrationState(
            active=True,
            stale_changes=[{'change_number': 101}],
            current_stale_idx=0,
            pending_descendants=[],
        )

        has_more = manager.advance_to_next_stale(state, [])

        assert has_more is False
        assert state.current_stale_idx == 1
        assert state.active is False

    def test_format_conflict_message(self):
        """Test formatting conflict message."""
        manager = ReintegrationManager()

        msg = manager.format_conflict_message(123, "Fix the bug")

        assert "CONFLICT" in msg
        assert "123" in msg
        assert "Fix the bug" in msg
        assert "continue-reintegration" in msg
        assert "skip-reintegration" in msg

    def test_format_start_message(self):
        """Test formatting start message."""
        manager = ReintegrationManager()

        series_patches = [
            {'change_number': 100, 'subject': 'Base'},
            {'change_number': 101, 'subject': 'Stale'},
            {'change_number': 102, 'subject': 'Desc 1'},
            {'change_number': 103, 'subject': 'Desc 2'},
        ]

        msg = manager.format_start_message(
            stale_change=101,
            old_rev=1,
            new_rev=2,
            subject="Stale",
            descendants=[102, 103],
            series_patches=series_patches,
        )

        assert "REINTEGRATION" in msg
        assert "101" in msg
        assert "v1 -> v2" in msg
        assert "Stale" in msg
        assert "102" in msg
        assert "103" in msg
        assert "Desc 1" in msg
        assert "Desc 2" in msg

    def test_format_complete_message(self):
        """Test formatting complete message."""
        manager = ReintegrationManager()

        msg = manager.format_complete_message(rebased_count=5, skipped_count=0)

        assert "COMPLETE" in msg
        assert "5 change(s)" in msg
        assert "Skipped" not in msg

    def test_format_complete_message_with_skipped(self):
        """Test formatting complete message with skipped changes."""
        manager = ReintegrationManager()

        msg = manager.format_complete_message(rebased_count=3, skipped_count=2)

        assert "COMPLETE" in msg
        assert "3 change(s)" in msg
        assert "Skipped 2" in msg

