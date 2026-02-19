"""Session persistence for rebase workflows.

This module handles saving, loading, and clearing rebase session state.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .reintegration import ReintegrationState


def _default_reintegration() -> dict[str, Any]:
    """Create default reintegration dict."""
    return ReintegrationState().to_dict()


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
    rebased_changes: list[int] = field(default_factory=list)  # Track which changes have been rebased
    skipped_changes: list[int] = field(default_factory=list)  # Track which changes were skipped
    pending_cherry_pick: int | None = None  # Change currently being cherry-picked
    reintegration: dict[str, Any] = field(default_factory=_default_reintegration)  # ReintegrationState as dict

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

    def __init__(self, state_dir: Path | None = None):
        """Initialize the session manager.

        Args:
            state_dir: Directory for state files. Defaults to .gerrit-cli
                      in the current directory.
        """
        if state_dir is None:
            state_dir = Path.cwd() / ".gerrit-cli"
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


class LastURLManager:
    """Manages persistence of the last-used Gerrit URL.

    This allows commands like `gc reply` to omit the URL argument
    after running `gc comments URL`, using the remembered URL instead.
    """

    def __init__(self, state_dir: Path | None = None):
        """Initialize the last URL manager.

        Args:
            state_dir: Directory for state files. Defaults to .gerrit-cli
                      in the current directory.
        """
        if state_dir is None:
            state_dir = Path.cwd() / ".gerrit-cli"
        self.state_dir = state_dir
        self.state_file = state_dir / "last-url.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, url: str, change_number: int | None = None) -> None:
        """Save the last-used URL.

        Args:
            url: The Gerrit change URL
            change_number: Optional change number (extracted from URL)
        """
        data = {"url": url}
        if change_number is not None:
            data["change_number"] = change_number
        with open(self.state_file, 'w') as f:
            json.dump(data, f, indent=2)

    def load(self) -> str | None:
        """Load the last-used URL.

        Returns:
            The URL string or None if not saved
        """
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file) as f:
                data = json.load(f)
            return data.get("url")
        except Exception:
            return None

    def clear(self) -> None:
        """Clear the saved URL."""
        if self.state_file.exists():
            self.state_file.unlink()

