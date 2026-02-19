"""Tmux and Vim integration for interactive code review.

This module provides classes to manage a split-screen tmux session with
vim for reviewing Gerrit comments with full code context.
"""

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class TmuxConfig:
    """Configuration for tmux session."""

    session_name: str = "gerrit-review"
    vim_pane_width_percent: int = 60
    vim_server_name: str = "GERRIT"


class TmuxController:
    """Controls tmux sessions and panes."""

    def __init__(self, config: Optional[TmuxConfig] = None):
        """Initialize the tmux controller.

        Args:
            config: Optional configuration, uses defaults if not provided.
        """
        self.config = config or TmuxConfig()
        self._tmux_bin = shutil.which("tmux")

    def is_available(self) -> bool:
        """Check if tmux is available."""
        return self._tmux_bin is not None

    def is_inside_tmux(self) -> bool:
        """Check if we're running inside a tmux session."""
        return os.environ.get("TMUX") is not None

    def get_current_session(self) -> Optional[str]:
        """Get the name of the current tmux session if inside one."""
        if not self.is_inside_tmux():
            return None
        try:
            result = self._run_tmux(["display-message", "-p", "#{session_name}"])
            return result.strip() if result else None
        except subprocess.SubprocessError:
            return None

    def session_exists(self, session_name: Optional[str] = None) -> bool:
        """Check if a tmux session exists.

        Args:
            session_name: Session name to check, uses config default if None.
        """
        name = session_name or self.config.session_name
        try:
            self._run_tmux(["has-session", "-t", name])
            return True
        except subprocess.CalledProcessError:
            return False

    def create_session(self, session_name: Optional[str] = None) -> bool:
        """Create a new tmux session.

        Args:
            session_name: Session name to create, uses config default if None.

        Returns:
            True if session was created successfully.
        """
        name = session_name or self.config.session_name
        try:
            self._run_tmux(["new-session", "-d", "-s", name])
            return True
        except subprocess.CalledProcessError:
            return False

    def kill_session(self, session_name: Optional[str] = None) -> bool:
        """Kill a tmux session.

        Args:
            session_name: Session name to kill, uses config default if None.

        Returns:
            True if session was killed successfully.
        """
        name = session_name or self.config.session_name
        try:
            self._run_tmux(["kill-session", "-t", name])
            return True
        except subprocess.CalledProcessError:
            return False

    def split_window_horizontal(
        self,
        session_name: Optional[str] = None,
        percent: Optional[int] = None,
    ) -> Optional[str]:
        """Split the current window horizontally (left/right panes).

        Args:
            session_name: Session to split in, uses config default if None.
            percent: Width percentage for the new pane, uses config default if None.

        Returns:
            The pane ID of the new pane, or None on failure.
        """
        name = session_name or self.config.session_name
        pct = percent or self.config.vim_pane_width_percent

        try:
            # Split and get the new pane ID
            result = self._run_tmux([
                "split-window", "-h",
                "-t", name,
                "-p", str(pct),
                "-P", "-F", "#{pane_id}",
            ])
            return result.strip() if result else None
        except subprocess.CalledProcessError:
            return None

    def send_keys(
        self,
        keys: str,
        target: Optional[str] = None,
        literal: bool = False,
    ) -> bool:
        """Send keys to a tmux pane.

        Args:
            keys: The keys to send.
            target: Target pane (session:window.pane format), uses current if None.
            literal: If True, send keys literally without parsing.

        Returns:
            True if keys were sent successfully.
        """
        cmd = ["send-keys"]
        if target:
            cmd.extend(["-t", target])
        if literal:
            cmd.append("-l")
        cmd.append(keys)

        try:
            self._run_tmux(cmd)
            return True
        except subprocess.CalledProcessError:
            return False

    def select_pane(self, pane_id: str) -> bool:
        """Select (focus) a specific pane.

        Args:
            pane_id: The pane ID to select.

        Returns:
            True if pane was selected successfully.
        """
        try:
            self._run_tmux(["select-pane", "-t", pane_id])
            return True
        except subprocess.CalledProcessError:
            return False

    def get_pane_ids(self, session_name: Optional[str] = None) -> list:
        """Get all pane IDs in a session.

        Args:
            session_name: Session to query, uses config default if None.

        Returns:
            List of pane IDs.
        """
        name = session_name or self.config.session_name
        try:
            result = self._run_tmux([
                "list-panes", "-t", name, "-F", "#{pane_id}",
            ])
            return result.strip().split("\n") if result else []
        except subprocess.CalledProcessError:
            return []

    def resize_pane(self, pane_id: str, width: Optional[int] = None, height: Optional[int] = None) -> bool:
        """Resize a pane.

        Args:
            pane_id: The pane to resize.
            width: New width in columns.
            height: New height in rows.

        Returns:
            True if resize was successful.
        """
        cmd = ["resize-pane", "-t", pane_id]
        if width:
            cmd.extend(["-x", str(width)])
        if height:
            cmd.extend(["-y", str(height)])

        try:
            self._run_tmux(cmd)
            return True
        except subprocess.CalledProcessError:
            return False

    def _run_tmux(self, args: list) -> str:
        """Run a tmux command.

        Args:
            args: Command arguments (without 'tmux' prefix).

        Returns:
            Command output as string.

        Raises:
            subprocess.CalledProcessError: If command fails.
        """
        if not self._tmux_bin:
            raise RuntimeError("tmux not found")

        result = subprocess.run(
            [self._tmux_bin] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout


class VimController:
    """Controls vim via server mode and remote commands."""

    def __init__(self, server_name: str = "GERRIT"):
        """Initialize the vim controller.

        Args:
            server_name: The vim server name to use.
        """
        self.server_name = server_name
        self._vim_bin = shutil.which("vim")
        self._gvim_bin = shutil.which("gvim")

    def is_available(self) -> bool:
        """Check if vim is available."""
        return self._vim_bin is not None

    def has_clientserver(self) -> bool:
        """Check if vim has +clientserver feature.

        Returns:
            True if vim supports client-server mode.
        """
        if not self._vim_bin:
            return False
        try:
            result = subprocess.run(
                [self._vim_bin, "--version"],
                capture_output=True,
                text=True,
            )
            return "+clientserver" in result.stdout
        except subprocess.SubprocessError:
            return False

    def is_server_running(self) -> bool:
        """Check if a vim server with our name is running.

        Returns:
            True if the server is running.
        """
        if not self._vim_bin:
            return False
        try:
            result = subprocess.run(
                [self._vim_bin, "--serverlist"],
                capture_output=True,
                text=True,
            )
            servers = result.stdout.strip().upper().split("\n")
            return self.server_name.upper() in servers
        except subprocess.SubprocessError:
            return False

    def get_start_command(
        self,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
    ) -> list:
        """Get the command to start vim with server mode.

        Args:
            file_path: Optional file to open.
            line: Optional line number to jump to.

        Returns:
            Command list suitable for subprocess or tmux send-keys.
        """
        cmd = [self._vim_bin or "vim", "--servername", self.server_name]

        if file_path:
            if line:
                cmd.append(f"+{line}")
            cmd.append(file_path)

        return cmd

    def get_start_command_string(
        self,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
    ) -> str:
        """Get the command string to start vim.

        Args:
            file_path: Optional file to open.
            line: Optional line number to jump to.

        Returns:
            Command string.
        """
        cmd = self.get_start_command(file_path, line)
        # Quote paths with spaces
        return " ".join(
            f'"{part}"' if " " in part else part for part in cmd
        )

    def send_command(self, vim_command: str) -> bool:
        """Send a command to the vim server.

        Args:
            vim_command: The vim command to execute (without leading :).

        Returns:
            True if command was sent successfully.
        """
        if not self._vim_bin:
            return False

        try:
            subprocess.run(
                [
                    self._vim_bin,
                    "--servername", self.server_name,
                    "--remote-send", f"<Esc>:{vim_command}<CR>",
                ],
                capture_output=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def open_file(self, file_path: str, line: Optional[int] = None) -> bool:
        """Open a file in the vim server.

        Args:
            file_path: Path to the file to open.
            line: Optional line number to jump to.

        Returns:
            True if file was opened successfully.
        """
        # Use :edit to open the file
        cmd = f"edit +{line or 1} {file_path}"
        if not self.send_command(cmd):
            return False

        # Center the line in the window
        if line:
            self.send_command(f"{line}")
            self.send_command("zz")

        return True

    def jump_to_line(self, line: int, center: bool = True) -> bool:
        """Jump to a specific line in the current file.

        Args:
            line: Line number to jump to.
            center: If True, center the line in the window.

        Returns:
            True if jump was successful.
        """
        if not self.send_command(str(line)):
            return False

        if center:
            self.send_command("zz")

        return True

    def highlight_lines(
        self,
        start_line: int,
        end_line: Optional[int] = None,
        highlight_group: str = "Search",
    ) -> bool:
        """Highlight lines in the current file.

        Args:
            start_line: First line to highlight.
            end_line: Last line to highlight (defaults to start_line).
            highlight_group: Vim highlight group to use.

        Returns:
            True if highlighting was applied.
        """
        end = end_line or start_line
        # Use matchadd for highlighting
        pattern = f"\\%>{start_line - 1}l\\%<{end + 1}l"
        cmd = f"call matchadd('{highlight_group}', '{pattern}')"
        return self.send_command(cmd)

    def clear_highlights(self) -> bool:
        """Clear all match highlights.

        Returns:
            True if highlights were cleared.
        """
        return self.send_command("call clearmatches()")


@dataclass
class SessionState:
    """State of a TmuxVimSession."""

    is_active: bool = False
    session_name: Optional[str] = None
    comment_pane_id: Optional[str] = None
    vim_pane_id: Optional[str] = None
    current_file: Optional[str] = None
    current_line: Optional[int] = None


class TmuxVimSession:
    """Manages a split-screen tmux session with vim for code review.

    This class coordinates tmux and vim to provide a split-screen
    experience where comments are shown on one side and the code
    is visible in vim on the other side.
    """

    def __init__(self, config: Optional[TmuxConfig] = None):
        """Initialize the session.

        Args:
            config: Optional configuration.
        """
        self.config = config or TmuxConfig()
        self.tmux = TmuxController(self.config)
        self.vim = VimController(self.config.vim_server_name)
        self.state = SessionState()

    def check_requirements(self) -> tuple[bool, str]:
        """Check if all requirements are met.

        Returns:
            Tuple of (success, message).
        """
        if not self.tmux.is_available():
            return False, "tmux is not installed or not in PATH"

        if not self.vim.is_available():
            return False, "vim is not installed or not in PATH"

        if not self.vim.has_clientserver():
            return False, "vim does not have +clientserver feature (try gvim or recompile vim)"

        return True, "All requirements met"

    def is_inside_tmux(self) -> bool:
        """Check if we're running inside tmux."""
        return self.tmux.is_inside_tmux()

    def setup_session(self) -> tuple[bool, str]:
        """Set up the split-screen session.

        If already in tmux, splits the current window.
        Otherwise, creates a new tmux session.

        Returns:
            Tuple of (success, message).
        """
        # Check requirements first
        ok, msg = self.check_requirements()
        if not ok:
            return False, msg

        if self.tmux.is_inside_tmux():
            return self._setup_inside_tmux()
        else:
            return self._setup_new_session()

    def _setup_inside_tmux(self) -> tuple[bool, str]:
        """Set up when already inside tmux."""
        session_name = self.tmux.get_current_session()
        if not session_name:
            return False, "Could not determine current tmux session"

        self.state.session_name = session_name

        # Get current pane (this will be the comment pane)
        panes = self.tmux.get_pane_ids(session_name)
        if not panes:
            return False, "Could not get current pane"

        self.state.comment_pane_id = panes[0]

        # Split window for vim
        vim_pane = self.tmux.split_window_horizontal(
            session_name,
            self.config.vim_pane_width_percent,
        )
        if not vim_pane:
            return False, "Could not split window for vim"

        self.state.vim_pane_id = vim_pane

        # Start vim in the new pane
        vim_cmd = self.vim.get_start_command_string()
        self.tmux.send_keys(f"{vim_cmd}\n", self.state.vim_pane_id)

        # Give vim time to start
        time.sleep(0.5)

        # Focus back on comment pane
        self.tmux.select_pane(self.state.comment_pane_id)

        self.state.is_active = True
        return True, "Session set up successfully"

    def _setup_new_session(self) -> tuple[bool, str]:
        """Set up a new tmux session (when not in tmux)."""
        # This case requires attaching to tmux, which changes the terminal
        # For now, we'll just return instructions
        return False, (
            "Not inside tmux. Please either:\n"
            "  1. Start tmux first: tmux\n"
            "  2. Or run inside an existing tmux session\n\n"
            "Then run: gerrit interactive --vim <url>"
        )

    def navigate_to(
        self,
        file_path: str,
        line: Optional[int] = None,
        highlight: bool = True,
    ) -> bool:
        """Navigate vim to a specific file and line.

        Args:
            file_path: Path to the file.
            line: Optional line number.
            highlight: Whether to highlight the target line.

        Returns:
            True if navigation was successful.
        """
        if not self.state.is_active:
            return False

        # Clear previous highlights before navigating
        if highlight:
            self.vim.clear_highlights()

        success = self.vim.open_file(file_path, line)
        if success:
            self.state.current_file = file_path
            self.state.current_line = line

            # Highlight the target line
            if highlight and line is not None:
                self.vim.highlight_lines(line)

        return success

    def highlight_line(self, line: int, highlight_group: str = "Search") -> bool:
        """Highlight a specific line in vim.

        Args:
            line: Line number to highlight.
            highlight_group: Vim highlight group to use.

        Returns:
            True if highlighting was applied.
        """
        if not self.state.is_active:
            return False

        return self.vim.highlight_lines(line, highlight_group=highlight_group)

    def clear_highlights(self) -> bool:
        """Clear all line highlights in vim.

        Returns:
            True if highlights were cleared.
        """
        if not self.state.is_active:
            return False

        return self.vim.clear_highlights()

    def focus_vim(self) -> bool:
        """Focus the vim pane.

        Returns:
            True if focus was changed successfully.
        """
        if not self.state.is_active or not self.state.vim_pane_id:
            return False

        return self.tmux.select_pane(self.state.vim_pane_id)

    def focus_comments(self) -> bool:
        """Focus the comments pane.

        Returns:
            True if focus was changed successfully.
        """
        if not self.state.is_active or not self.state.comment_pane_id:
            return False

        return self.tmux.select_pane(self.state.comment_pane_id)

    def cleanup(self) -> bool:
        """Clean up the session by closing the vim pane.

        Returns:
            True if cleanup was successful.
        """
        if not self.state.is_active:
            return True

        # Send quit command to vim
        self.vim.send_command("qa!")

        # Small delay for vim to close
        time.sleep(0.2)

        self.state.is_active = False
        self.state.vim_pane_id = None
        self.state.current_file = None
        self.state.current_line = None

        return True

