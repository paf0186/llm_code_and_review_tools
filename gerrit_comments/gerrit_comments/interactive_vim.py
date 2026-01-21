"""Interactive vim mode for reviewing and responding to comments.

This module extends the interactive mode with split-screen vim integration
using tmux.
"""

from typing import Optional

from .extractor import extract_comments
from .interactive import InteractiveSession
from .rebase import work_on_patch
from .tmux_vim import TmuxConfig, TmuxVimSession


class InteractiveVimSession(InteractiveSession):
    """Interactive session with vim split-screen integration.

    Extends the basic interactive session to show code in a vim pane
    synchronized with the comment being reviewed.
    """

    def __init__(self, vim_config: Optional[TmuxConfig] = None):
        """Initialize the interactive vim session.

        Args:
            vim_config: Optional configuration for tmux/vim.
        """
        super().__init__()
        self.vim_session = TmuxVimSession(vim_config)
        self._vim_active = False
        # Track current position for navigation
        self.current_index = 0
        self.all_comments: list[dict] = []

    def run_series(self, url: str):
        """Run interactive vim session for a patch series.

        Args:
            url: URL to any patch in the series
        """
        # Set up vim session first
        ok, msg = self._setup_vim()
        if not ok:
            print(f"\n⚠ Vim mode not available: {msg}")
            print("Falling back to standard interactive mode.\n")
            super().run_series(url)
            return

        try:
            self._run_vim_series(url)
        finally:
            self._cleanup_vim()

    def _setup_vim(self) -> tuple[bool, str]:
        """Set up the vim split-screen session.

        Returns:
            Tuple of (success, message).
        """
        # Check requirements
        ok, msg = self.vim_session.check_requirements()
        if not ok:
            return False, msg

        # Check if we're in tmux
        if not self.vim_session.is_inside_tmux():
            return False, (
                "Not running inside tmux. To use vim mode:\n"
                "  1. Start tmux: tmux\n"
                "  2. Run: gerrit-comments interactive --vim <url>"
            )

        # Set up the split-screen session
        ok, msg = self.vim_session.setup_session()
        if ok:
            self._vim_active = True

        return ok, msg

    def _cleanup_vim(self):
        """Clean up the vim session."""
        if self._vim_active:
            self.vim_session.cleanup()
            self._vim_active = False

    def _run_vim_series(self, url: str):
        """Run the vim-enhanced interactive session.

        Args:
            url: URL to any patch in the series.
        """
        # Find all patches in series
        print("Finding patches in series...")
        series_patches = self.series_finder.find_series(url)

        if not series_patches:
            print("Error: Could not find series")
            return

        print(f"Found {len(series_patches)} patch(es) in series")

        # Collect all comments from all patches
        print("Fetching comments...")
        self.all_comments = []
        for patch in series_patches:
            patch_url = f"https://review.whamcloud.com/{patch.change_number}"
            try:
                extracted = extract_comments(
                    url=patch_url,
                    include_resolved=False,
                    include_code_context=True,
                )
                if extracted.threads:
                    for thread in extracted.threads:
                        self.all_comments.append({
                            'patch': patch,
                            'extracted': extracted,
                            'thread': thread,
                            'change_number': patch.change_number,
                        })
            except Exception as e:
                print(f"Warning: Could not fetch comments for {patch.change_number}: {e}")
                continue

        if not self.all_comments:
            print("No unresolved comments found in series!")
            return

        self.total_comments = len(self.all_comments)
        print(f"Found {self.total_comments} unresolved comment(s) across series")
        print()
        self._print_help()

        # Start at first comment
        self.current_index = 0
        self._navigate_to_current()

        # Main interaction loop
        while True:
            action = self._get_action()
            if action == 'quit':
                break
            elif action == 'continue':
                continue

        # Show summary and offer to push
        self._show_summary_and_push()

    def _print_help(self):
        """Print keyboard shortcuts help."""
        print("=" * 70)
        print("VIM INTERACTIVE MODE")
        print("=" * 70)
        print("Navigation:  [n]ext  [p]rev  [g]oto #  [f]ocus vim")
        print("Actions:     [d]one  [r]eply  [a]ck  [s]kip  [e]dit patch")
        print("Other:       [h]elp  [P]ush  [q]uit")
        print("=" * 70)

    def _navigate_to_current(self):
        """Navigate vim to the current comment's location."""
        if not self.all_comments or self.current_index >= len(self.all_comments):
            return

        comment_data = self.all_comments[self.current_index]
        thread = comment_data['thread']
        root = thread.root_comment

        # Display comment info
        self._display_comment(comment_data, self.current_index + 1)

        # Navigate vim to the file/line
        if root.file_path and root.file_path != "/PATCHSET_LEVEL":
            self.vim_session.navigate_to(root.file_path, root.line)

    def _display_comment(self, comment_data: dict, comment_num: int):
        """Display current comment information.

        Args:
            comment_data: Dict with patch, extracted, thread info.
            comment_num: Current comment number (1-indexed).
        """
        patch = comment_data['patch']
        thread = comment_data['thread']
        change_number = comment_data['change_number']

        print()
        print("-" * 70)
        print(f"[{comment_num}/{self.total_comments}] Change {change_number}: {patch.subject}")
        print(f"URL: https://review.whamcloud.com/{change_number}")
        print("-" * 70)

        root = thread.root_comment
        location = f"{root.file_path}:{root.line or 'patchset'}"
        print(f"📍 {location}")
        print(f"👤 {root.author}")
        print()
        print(f"💬 {root.message}")

        # Show replies if any
        if thread.replies:
            print()
            print(f"  📝 {len(thread.replies)} reply/replies in thread")
            for idx, reply in enumerate(thread.replies, 1):
                # Show abbreviated replies
                msg_preview = reply.message[:60] + "..." if len(reply.message) > 60 else reply.message
                print(f"    {idx}. {reply.author}: {msg_preview}")

        print("-" * 70)

    def _get_action(self) -> str:
        """Get and process user action.

        Returns:
            'quit' to exit, 'continue' to stay in loop.
        """
        try:
            action = input("Action [n/p/d/r/a/s/e/f/g/h/P/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 'quit'

        if action == 'n':
            # Next comment
            if self.current_index < len(self.all_comments) - 1:
                self.current_index += 1
                self._navigate_to_current()
            else:
                print("Already at last comment")

        elif action == 'p':
            # Previous comment
            if self.current_index > 0:
                self.current_index -= 1
                self._navigate_to_current()
            else:
                print("Already at first comment")

        elif action == 'g':
            # Go to specific comment
            try:
                num = int(input(f"Go to comment (1-{self.total_comments}): "))
                if 1 <= num <= self.total_comments:
                    self.current_index = num - 1
                    self._navigate_to_current()
                else:
                    print(f"Invalid number. Use 1-{self.total_comments}")
            except ValueError:
                print("Invalid number")

        elif action == 'f':
            # Focus vim pane
            print("Switching focus to vim. Press Ctrl-b then arrow key to return.")
            self.vim_session.focus_vim()

        elif action == 'd':
            # Mark as done
            self._handle_done()

        elif action == 'r':
            # Reply
            self._handle_reply()

        elif action == 'a':
            # Acknowledge
            self._handle_ack()

        elif action == 's':
            # Skip
            self._handle_skip()

        elif action == 'e':
            # Edit patch
            return self._handle_edit()

        elif action == 'h':
            # Help
            self._print_help()

        elif action == 'P':
            # Push now
            print()
            print("Pushing staged operations...")
            self._push_all()
            print()

        elif action == 'q':
            # Quit
            return 'quit'

        else:
            print("Unknown action. Press 'h' for help.")

        return 'continue'

    def _handle_done(self):
        """Handle marking current comment as done."""
        if not self.all_comments:
            return

        comment_data = self.all_comments[self.current_index]
        extracted = comment_data['extracted']
        thread = comment_data['thread']
        change_number = comment_data['change_number']
        thread_index = extracted.threads.index(thread)

        message = input("Message (Enter for 'Done'): ").strip() or "Done"
        self._stage_reply(extracted, thread_index, change_number, message, True)
        print(f"✓ Staged 'Done' for comment {self.current_index + 1}")
        self.staged_count += 1

        # Auto-advance to next
        if self.current_index < len(self.all_comments) - 1:
            self.current_index += 1
            self._navigate_to_current()

    def _handle_reply(self):
        """Handle replying to current comment."""
        if not self.all_comments:
            return

        comment_data = self.all_comments[self.current_index]
        extracted = comment_data['extracted']
        thread = comment_data['thread']
        change_number = comment_data['change_number']
        thread_index = extracted.threads.index(thread)

        print("Enter reply (empty to cancel):")
        message = input("> ").strip()
        if not message:
            print("Cancelled")
            return

        resolve = input("Mark as resolved? [y/N]: ").strip().lower() == 'y'
        self._stage_reply(extracted, thread_index, change_number, message, resolve)
        print(f"✓ Staged reply for comment {self.current_index + 1}")
        self.staged_count += 1

        # Auto-advance to next
        if self.current_index < len(self.all_comments) - 1:
            self.current_index += 1
            self._navigate_to_current()

    def _handle_ack(self):
        """Handle acknowledging current comment."""
        if not self.all_comments:
            return

        comment_data = self.all_comments[self.current_index]
        extracted = comment_data['extracted']
        thread = comment_data['thread']
        change_number = comment_data['change_number']
        thread_index = extracted.threads.index(thread)

        message = input("Message (Enter for 'Acknowledged'): ").strip() or "Acknowledged"
        self._stage_reply(extracted, thread_index, change_number, message, True)
        print(f"✓ Staged acknowledgment for comment {self.current_index + 1}")
        self.staged_count += 1

        # Auto-advance to next
        if self.current_index < len(self.all_comments) - 1:
            self.current_index += 1
            self._navigate_to_current()

    def _handle_skip(self):
        """Handle skipping current comment."""
        print(f"⊘ Skipped comment {self.current_index + 1}")
        self.skipped_count += 1

        # Auto-advance to next
        if self.current_index < len(self.all_comments) - 1:
            self.current_index += 1
            self._navigate_to_current()

    def _handle_edit(self) -> str:
        """Handle editing the current patch.

        Returns:
            'quit' if edit mode was entered, 'continue' otherwise.
        """
        if not self.all_comments:
            return 'continue'

        comment_data = self.all_comments[self.current_index]
        change_number = comment_data['change_number']

        print(f"\n🔧 Starting edit mode for patch {change_number}...")
        print("=" * 70)

        series_url = f"https://review.whamcloud.com/{change_number}"
        success, message = work_on_patch(series_url, change_number)
        print(message)

        if success:
            print("\n" + "=" * 70)
            print("⚠ EDIT MODE ACTIVE")
            print("=" * 70)
            print()
            print("You are now in edit mode. The interactive session has been paused.")
            print("After you finish editing:")
            print("  1. Run: gerrit-comments finish-patch")
            print("  2. Re-run: gerrit-comments interactive --vim <url>")
            print()
            print("To abort the edit:")
            print("  Run: gerrit-comments abort-patch")
            print()
            print("=" * 70)
            print("\nExiting interactive mode...")
            return 'quit'
        else:
            print("\n✗ Failed to start edit mode. Returning to comment review...")
            return 'continue'


def run_interactive_vim(url: str, config: Optional[TmuxConfig] = None):
    """Run interactive vim session for a series.

    Args:
        url: URL to any patch in the series.
        config: Optional tmux/vim configuration.
    """
    session = InteractiveVimSession(config)
    session.run_series(url)

