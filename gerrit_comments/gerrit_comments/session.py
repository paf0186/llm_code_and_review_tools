"""Session persistence for rebase workflows.

This module handles saving, loading, and clearing rebase session state.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .reintegration import ReintegrationState


@dataclass
class RebaseSession:
    """Represents an active rebase session."""
    series_url: str
    target_change: int
    target_commit: str
    original_head: str
    original_branch: str
    series_patches: list[dict]  # Serializable patch info
    started_at: str
    rebased_changes: list[int] = None  # Track which changes have been rebased
    skipped_changes: list[int] = None  # Track which changes were skipped
    pending_cherry_pick: int = None  # Change currently being cherry-picked
    reintegration: dict = None  # ReintegrationState as dict

    def __post_init__(self):
        if self.rebased_changes is None:
            self.rebased_changes = []
        if self.skipped_changes is None:
            self.skipped_changes = []
        if self.reintegration is None:
            self.reintegration = ReintegrationState().to_dict()

    @property
    def reintegrating(self) -> bool:
        """Check if reintegration is active."""
        return self.reintegration.get('active', False)

    @property
    def reintegration_state(self) -> ReintegrationState:
        """Get the reintegration state object."""
        return ReintegrationState.from_dict(self.reintegration)

    def update_reintegration(self, state: ReintegrationState) -> None:
        """Update the reintegration state."""
        self.reintegration = state.to_dict()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RebaseSession":
        if 'rebased_changes' not in data:
            data['rebased_changes'] = []
        if 'skipped_changes' not in data:
            data['skipped_changes'] = []
        if 'pending_cherry_pick' not in data:
            data['pending_cherry_pick'] = None
        if 'reintegration' not in data:
            data['reintegration'] = ReintegrationState().to_dict()
        return cls(**data)


class SessionManager:
    """Manages persistence of rebase sessions."""

    def __init__(self, state_dir: Path = None):
        """Initialize the session manager.

        Args:
            state_dir: Directory for state files. Defaults to .gerrit-comments
                      in the current directory.
        """
        if state_dir is None:
            state_dir = Path.cwd() / ".gerrit-comments"
        self.state_dir = state_dir
        self.state_file = state_dir / "rebase-session.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def has_active_session(self) -> bool:
        """Check if there's an active rebase session.

        Returns:
            True if session exists
        """
        return self.state_file.exists()

    def save(self, session: RebaseSession) -> None:
        """Save rebase session state.

        Args:
            session: The session to save
        """
        with open(self.state_file, 'w') as f:
            json.dump(session.to_dict(), f, indent=2)

    def load(self) -> Optional[RebaseSession]:
        """Load rebase session state.

        Returns:
            RebaseSession or None if no session
        """
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file) as f:
                data = json.load(f)
            return RebaseSession.from_dict(data)
        except Exception:
            return None

    def clear(self) -> None:
        """Clear the saved session state."""
        if self.state_file.exists():
            self.state_file.unlink()

