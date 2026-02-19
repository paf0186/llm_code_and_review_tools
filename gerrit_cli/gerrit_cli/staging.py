"""Staging system for batching Gerrit comment operations.

This module provides functionality to stage multiple comment replies and push
them in a single API call, reducing notifications and improving efficiency.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class StagedOperation:
    """A staged comment operation."""
    thread_index: int
    file_path: str
    line: Optional[int]
    message: str
    resolve: bool
    comment_id: str  # Gerrit comment ID for the reply target


@dataclass
class StagedPatch:
    """Staged operations for a single patch."""
    change_number: int
    change_url: str
    patchset: int
    operations: list[StagedOperation]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'change_number': self.change_number,
            'change_url': self.change_url,
            'patchset': self.patchset,
            'operations': [
                {
                    'thread_index': op.thread_index,
                    'file_path': op.file_path,
                    'line': op.line,
                    'message': op.message,
                    'resolve': op.resolve,
                    'comment_id': op.comment_id,
                }
                for op in self.operations
            ]
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'StagedPatch':
        """Create from dictionary loaded from JSON."""
        operations = [
            StagedOperation(**op_data)
            for op_data in data['operations']
        ]
        return cls(
            change_number=data['change_number'],
            change_url=data['change_url'],
            patchset=data['patchset'],
            operations=operations,
        )


class StagingManager:
    """Manages staged operations for patches."""

    def __init__(self, staging_dir: Optional[Path] = None):
        """Initialize staging manager.

        Args:
            staging_dir: Directory to store staged operations.
                        Defaults to .gerrit-cli/staged/ in current working directory
        """
        if staging_dir is None:
            staging_dir = Path.cwd() / ".gerrit-cli" / "staged"

        self.staging_dir = staging_dir
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def _get_stage_file(self, change_number: int) -> Path:
        """Get the staging file path for a change."""
        return self.staging_dir / f"{change_number}.json"

    def load_staged(self, change_number: int) -> Optional[StagedPatch]:
        """Load staged operations for a change.

        Args:
            change_number: The change number

        Returns:
            StagedPatch object or None if no operations staged
        """
        stage_file = self._get_stage_file(change_number)
        if not stage_file.exists():
            return None

        with open(stage_file) as f:
            data = json.load(f)

        return StagedPatch.from_dict(data)

    def save_staged(self, staged: StagedPatch):
        """Save staged operations for a change.

        Args:
            staged: The StagedPatch to save
        """
        stage_file = self._get_stage_file(staged.change_number)

        with open(stage_file, 'w') as f:
            json.dump(staged.to_dict(), f, indent=2)

    def add_operation(
        self,
        change_number: int,
        change_url: str,
        patchset: int,
        thread_index: int,
        file_path: str,
        line: Optional[int],
        comment_id: str,
        message: str,
        resolve: bool,
    ):
        """Add a staged operation.

        Args:
            change_number: The change number
            change_url: URL to the change
            patchset: Current patchset number
            thread_index: Index of the comment thread
            file_path: Path to the file
            line: Line number (None for patchset-level)
            comment_id: Gerrit comment ID to reply to
            message: Reply message
            resolve: Whether to resolve the thread
        """
        staged = self.load_staged(change_number)

        if staged is None:
            # Create new staged patch
            staged = StagedPatch(
                change_number=change_number,
                change_url=change_url,
                patchset=patchset,
                operations=[]
            )
        else:
            # Update patchset if changed
            if staged.patchset != patchset:
                print(f"⚠ Warning: Patchset changed from {staged.patchset} to {patchset}")
                staged.patchset = patchset

        # Check if this thread is already staged
        existing_idx = None
        for i, op in enumerate(staged.operations):
            if op.thread_index == thread_index:
                existing_idx = i
                break

        operation = StagedOperation(
            thread_index=thread_index,
            file_path=file_path,
            line=line,
            message=message,
            resolve=resolve,
            comment_id=comment_id,
        )

        if existing_idx is not None:
            # Replace existing operation
            print(f"ℹ Replacing existing staged operation for thread {thread_index}")
            staged.operations[existing_idx] = operation
        else:
            # Add new operation
            staged.operations.append(operation)

        self.save_staged(staged)

    def remove_operation(self, change_number: int, operation_index: int) -> bool:
        """Remove a staged operation by index.

        Args:
            change_number: The change number
            operation_index: Index of the operation in the operations list

        Returns:
            True if removed, False if not found
        """
        staged = self.load_staged(change_number)
        if staged is None:
            return False

        if operation_index < 0 or operation_index >= len(staged.operations):
            return False  # Invalid index

        # Remove the operation at the specified index
        staged.operations.pop(operation_index)

        if len(staged.operations) == 0:
            # No more operations, remove the file
            self.clear_staged(change_number)
        else:
            self.save_staged(staged)

        return True

    def clear_staged(self, change_number: int) -> bool:
        """Clear all staged operations for a change.

        Args:
            change_number: The change number

        Returns:
            True if cleared, False if nothing was staged
        """
        stage_file = self._get_stage_file(change_number)
        if stage_file.exists():
            stage_file.unlink()
            return True
        return False

    def list_all_staged(self) -> list[StagedPatch]:
        """List all patches with staged operations.

        Returns:
            List of StagedPatch objects
        """
        staged_patches = []

        for stage_file in self.staging_dir.glob("*.json"):
            try:
                change_number = int(stage_file.stem)
                staged = self.load_staged(change_number)
                if staged and staged.operations:
                    staged_patches.append(staged)
            except (ValueError, json.JSONDecodeError):
                # Skip invalid files
                continue

        return sorted(staged_patches, key=lambda x: x.change_number)

    def clear_all_staged(self) -> int:
        """Clear all staged operations for all changes.

        Returns:
            Number of changes cleared
        """
        count = 0
        for stage_file in self.staging_dir.glob("*.json"):
            stage_file.unlink()
            count += 1
        return count

    def update_patchset(self, change_number: int, new_patchset: int) -> bool:
        """Update the patchset number for staged operations.

        Args:
            change_number: The change number
            new_patchset: New patchset number

        Returns:
            True if updated, False if no staged operations found
        """
        staged = self.load_staged(change_number)
        if staged is None:
            return False

        staged.patchset = new_patchset
        self.save_staged(staged)
        return True

    def stage_operation(
        self,
        change_number: int,
        thread_index: int,
        file_path: str,
        line: Optional[int],
        message: str,
        resolve: bool,
        comment_id: str,
        patchset: int,
        change_url: str = "",
    ):
        """Convenience method for staging an operation.

        Args:
            change_number: The change number
            thread_index: Index of the comment thread
            file_path: Path to the file
            line: Line number (None for patchset-level)
            message: Reply message
            resolve: Whether to resolve the thread
            comment_id: Gerrit comment ID to reply to
            patchset: Current patchset number
            change_url: URL to the change (optional)
        """
        if not change_url:
            change_url = f"https://review.whamcloud.com/{change_number}"

        self.add_operation(
            change_number=change_number,
            change_url=change_url,
            patchset=patchset,
            thread_index=thread_index,
            file_path=file_path,
            line=line,
            comment_id=comment_id,
            message=message,
            resolve=resolve,
        )

    def format_summary(self, staged: StagedPatch) -> str:
        """Format a summary of staged operations.

        Args:
            staged: The StagedPatch to summarize

        Returns:
            Formatted string
        """
        lines = []
        lines.append(f"Staged operations for Change {staged.change_number} (Patchset {staged.patchset}):")
        lines.append(f"URL: {staged.change_url}")
        lines.append(f"Operations: {len(staged.operations)}")
        lines.append("")

        for op in staged.operations:
            action = "RESOLVE" if op.resolve else "COMMENT"
            location = f"{op.file_path}:{op.line}" if op.line else f"{op.file_path}:patchset"
            msg_preview = op.message[:50] + "..." if len(op.message) > 50 else op.message
            lines.append(f"  [{op.thread_index}] {location}")
            lines.append(f"      {action}: \"{msg_preview}\"")

        lines.append("")
        lines.append(f"Push with: gerrit push {staged.change_number}")

        return "\n".join(lines)
