"""Tests for the staging module."""

import tempfile
from pathlib import Path

import pytest

from gerrit_cli.staging import (
    StagedOperation,
    StagedPatch,
    StagingManager,
)


@pytest.fixture
def temp_staging_dir():
    """Create a temporary staging directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def staging_manager(temp_staging_dir):
    """Create a StagingManager with a temporary directory."""
    return StagingManager(staging_dir=temp_staging_dir)


class TestStagedOperation:
    """Tests for StagedOperation dataclass."""

    def test_create_operation(self):
        """Test creating a staged operation."""
        op = StagedOperation(
            thread_index=0,
            file_path="test.c",
            line=42,
            message="Done",
            resolve=True,
            comment_id="abc123",
        )

        assert op.thread_index == 0
        assert op.file_path == "test.c"
        assert op.line == 42
        assert op.message == "Done"
        assert op.resolve is True
        assert op.comment_id == "abc123"

    def test_operation_with_no_line(self):
        """Test operation without line number (patchset-level)."""
        op = StagedOperation(
            thread_index=0,
            file_path="/PATCHSET_LEVEL",
            line=None,
            message="Overall looks good",
            resolve=False,
            comment_id="def456",
        )

        assert op.line is None
        assert op.resolve is False


class TestStagedPatch:
    """Tests for StagedPatch dataclass."""

    def test_create_patch(self):
        """Test creating a staged patch."""
        ops = [
            StagedOperation(0, "test.c", 10, "Done", True, "id1"),
            StagedOperation(1, "test.c", 20, "Fixed", True, "id2"),
        ]
        patch = StagedPatch(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            operations=ops,
        )

        assert patch.change_number == 12345
        assert patch.patchset == 5
        assert len(patch.operations) == 2

    def test_to_dict(self):
        """Test converting patch to dictionary."""
        ops = [StagedOperation(0, "test.c", 10, "Done", True, "id1")]
        patch = StagedPatch(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            operations=ops,
        )

        result = patch.to_dict()

        assert result["change_number"] == 12345
        assert result["patchset"] == 5
        assert len(result["operations"]) == 1
        assert result["operations"][0]["message"] == "Done"

    def test_from_dict(self):
        """Test creating patch from dictionary."""
        data = {
            "change_number": 12345,
            "change_url": "https://review.example.com/12345",
            "patchset": 5,
            "operations": [
                {
                    "thread_index": 0,
                    "file_path": "test.c",
                    "line": 10,
                    "message": "Done",
                    "resolve": True,
                    "comment_id": "id1",
                }
            ],
        }

        patch = StagedPatch.from_dict(data)

        assert patch.change_number == 12345
        assert patch.patchset == 5
        assert len(patch.operations) == 1
        assert patch.operations[0].message == "Done"


class TestStagingManager:
    """Tests for StagingManager."""

    def test_init_creates_directory(self, temp_staging_dir):
        """Test that initialization creates the staging directory."""
        mgr = StagingManager(staging_dir=temp_staging_dir / "new_dir")
        assert mgr.staging_dir.exists()
        assert mgr.staging_dir.is_dir()

    def test_save_and_load_staged(self, staging_manager):
        """Test saving and loading staged operations."""
        ops = [StagedOperation(0, "test.c", 10, "Done", True, "id1")]
        patch = StagedPatch(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            operations=ops,
        )

        # Save
        staging_manager.save_staged(patch)

        # Load
        loaded = staging_manager.load_staged(12345)

        assert loaded is not None
        assert loaded.change_number == 12345
        assert loaded.patchset == 5
        assert len(loaded.operations) == 1
        assert loaded.operations[0].message == "Done"

    def test_load_nonexistent(self, staging_manager):
        """Test loading nonexistent staged operations."""
        result = staging_manager.load_staged(99999)
        assert result is None

    def test_add_operation(self, staging_manager):
        """Test adding an operation."""
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done",
            resolve=True,
        )

        loaded = staging_manager.load_staged(12345)

        assert loaded is not None
        assert len(loaded.operations) == 1
        assert loaded.operations[0].message == "Done"

    def test_add_multiple_operations(self, staging_manager):
        """Test adding multiple operations to same change."""
        for i in range(3):
            staging_manager.add_operation(
                change_number=12345,
                change_url="https://review.example.com/12345",
                patchset=5,
                thread_index=i,
                file_path="test.c",
                line=10 * (i + 1),
                comment_id=f"id{i}",
                message=f"Comment {i}",
                resolve=True,
            )

        loaded = staging_manager.load_staged(12345)

        assert loaded is not None
        assert len(loaded.operations) == 3

    def test_replace_existing_operation(self, staging_manager):
        """Test that adding same thread_index replaces existing operation."""
        # Add first operation
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="First message",
            resolve=False,
        )

        # Add second operation with same thread_index
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Second message",
            resolve=True,
        )

        loaded = staging_manager.load_staged(12345)

        assert loaded is not None
        assert len(loaded.operations) == 1
        assert loaded.operations[0].message == "Second message"
        assert loaded.operations[0].resolve is True

    def test_stage_operation_convenience_method(self, staging_manager):
        """Test the convenience stage_operation method."""
        staging_manager.stage_operation(
            change_number=12345,
            thread_index=0,
            file_path="test.c",
            line=10,
            message="Done",
            resolve=True,
            comment_id="id1",
            patchset=5,
            change_url="https://review.example.com/12345",
        )

        loaded = staging_manager.load_staged(12345)

        assert loaded is not None
        assert len(loaded.operations) == 1

    def test_remove_operation(self, staging_manager):
        """Test removing a staged operation by index."""
        # Add multiple operations
        for i in range(3):
            staging_manager.add_operation(
                change_number=12345,
                change_url="https://review.example.com/12345",
                patchset=5,
                thread_index=i,
                file_path="test.c",
                line=10 * (i + 1),
                comment_id=f"id{i}",
                message=f"Comment {i}",
                resolve=True,
            )

        # Remove middle operation
        success = staging_manager.remove_operation(12345, 1)

        assert success is True

        loaded = staging_manager.load_staged(12345)
        assert len(loaded.operations) == 2
        assert loaded.operations[0].message == "Comment 0"
        assert loaded.operations[1].message == "Comment 2"

    def test_remove_invalid_index(self, staging_manager):
        """Test removing with invalid index."""
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done",
            resolve=True,
        )

        # Try to remove with invalid index
        success = staging_manager.remove_operation(12345, 5)

        assert success is False

        loaded = staging_manager.load_staged(12345)
        assert len(loaded.operations) == 1

    def test_remove_last_operation_clears_file(self, staging_manager):
        """Test that removing last operation deletes the staging file."""
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done",
            resolve=True,
        )

        # Remove the only operation
        success = staging_manager.remove_operation(12345, 0)

        assert success is True

        # File should be gone
        loaded = staging_manager.load_staged(12345)
        assert loaded is None

    def test_clear_staged(self, staging_manager):
        """Test clearing all staged operations for a change."""
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done",
            resolve=True,
        )

        result = staging_manager.clear_staged(12345)

        assert result is True

        loaded = staging_manager.load_staged(12345)
        assert loaded is None

    def test_clear_nonexistent(self, staging_manager):
        """Test clearing nonexistent staged operations."""
        result = staging_manager.clear_staged(99999)
        assert result is False

    def test_list_all_staged(self, staging_manager):
        """Test listing all patches with staged operations."""
        # Add operations for multiple changes
        for change_num in [12345, 12346, 12347]:
            staging_manager.add_operation(
                change_number=change_num,
                change_url=f"https://review.example.com/{change_num}",
                patchset=5,
                thread_index=0,
                file_path="test.c",
                line=10,
                comment_id="id1",
                message="Done",
                resolve=True,
            )

        staged_list = staging_manager.list_all_staged()

        assert len(staged_list) == 3
        # Should be sorted by change number
        assert staged_list[0].change_number == 12345
        assert staged_list[1].change_number == 12346
        assert staged_list[2].change_number == 12347

    def test_list_all_staged_empty(self, staging_manager):
        """Test listing when no operations are staged."""
        staged_list = staging_manager.list_all_staged()
        assert len(staged_list) == 0

    def test_clear_all_staged(self, staging_manager):
        """Test clearing all staged operations."""
        # Add operations for multiple changes
        for change_num in [12345, 12346, 12347]:
            staging_manager.add_operation(
                change_number=change_num,
                change_url=f"https://review.example.com/{change_num}",
                patchset=5,
                thread_index=0,
                file_path="test.c",
                line=10,
                comment_id="id1",
                message="Done",
                resolve=True,
            )

        count = staging_manager.clear_all_staged()

        assert count == 3

        staged_list = staging_manager.list_all_staged()
        assert len(staged_list) == 0

    def test_update_patchset(self, staging_manager):
        """Test updating patchset number for staged operations."""
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done",
            resolve=True,
        )

        success = staging_manager.update_patchset(12345, 6)

        assert success is True

        loaded = staging_manager.load_staged(12345)
        assert loaded.patchset == 6

    def test_update_patchset_nonexistent(self, staging_manager):
        """Test updating patchset for nonexistent change."""
        success = staging_manager.update_patchset(99999, 6)
        assert success is False

    def test_format_summary(self, staging_manager):
        """Test formatting summary of staged operations."""
        ops = [
            StagedOperation(0, "test.c", 10, "Done", True, "id1"),
            StagedOperation(1, "test.c", 20, "Fixed this issue", False, "id2"),
        ]
        patch = StagedPatch(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            operations=ops,
        )

        summary = staging_manager.format_summary(patch)

        assert "Change 12345" in summary
        assert "Patchset 5" in summary
        assert "test.c:10" in summary
        assert "test.c:20" in summary
        assert "RESOLVE" in summary
        assert "COMMENT" in summary

    def test_patchset_change_warning(self, staging_manager, capsys):
        """Test warning when patchset changes."""
        # Add operation with patchset 5
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done",
            resolve=True,
        )

        # Add another operation with different patchset
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=6,  # Different patchset
            thread_index=1,
            file_path="test.c",
            line=20,
            comment_id="id2",
            message="Fixed",
            resolve=True,
        )

        captured = capsys.readouterr()
        assert "Warning" in captured.out or "Patchset changed" in captured.out

    def test_json_serialization_round_trip(self, staging_manager):
        """Test that data survives JSON serialization round trip."""
        # Add operation
        staging_manager.add_operation(
            change_number=12345,
            change_url="https://review.example.com/12345",
            patchset=5,
            thread_index=0,
            file_path="test.c",
            line=10,
            comment_id="id1",
            message="Done with special chars: 你好 🎉",
            resolve=True,
        )

        # Load and verify
        loaded = staging_manager.load_staged(12345)

        assert loaded is not None
        assert loaded.operations[0].message == "Done with special chars: 你好 🎉"

    def test_get_stage_file_path(self, staging_manager):
        """Test getting the staging file path."""
        path = staging_manager._get_stage_file(12345)

        assert path.name == "12345.json"
        assert path.parent == staging_manager.staging_dir
