"""Reply to Gerrit comments."""

from typing import Any, Optional

from .client import GerritCommentsClient
from .models import Comment, CommentThread, ExtractedComments, ReplyResult
from .staging import StagingManager


class CommentReplier:
    """Reply to comments on Gerrit changes."""

    def __init__(
        self,
        client: Optional[GerritCommentsClient] = None,
        staging_manager: Optional[StagingManager] = None,
    ):
        """Initialize the replier.

        Args:
            client: Optional GerritCommentsClient. Creates default if not provided.
            staging_manager: Optional StagingManager. Creates default if not provided.
        """
        self.client = client or GerritCommentsClient()
        self.staging_manager = staging_manager or StagingManager()

    def reply_to_comment(
        self,
        change_number: int,
        comment: Comment,
        message: str,
        mark_resolved: bool = False,
    ) -> ReplyResult:
        """Reply to a specific comment.

        Args:
            change_number: The change number
            comment: The Comment object to reply to
            message: Reply message
            mark_resolved: Whether to mark the comment thread as resolved

        Returns:
            ReplyResult with success status
        """
        try:
            # Use current revision for posting
            change = self.client.get_change_detail(change_number)
            current_revision = change.get("current_revision", "current")

            self.client.reply_to_comment(
                change_number=change_number,
                revision_id=current_revision,
                file_path=comment.file_path,
                comment_id=comment.id,
                message=message,
                line=comment.line,
                mark_resolved=mark_resolved,
            )

            return ReplyResult(
                success=True,
                comment_id=comment.id,
                message=message,
                marked_resolved=mark_resolved,
            )

        except Exception as e:
            return ReplyResult(
                success=False,
                comment_id=comment.id,
                message=message,
                marked_resolved=False,
                error=str(e),
            )

    def mark_done(
        self,
        change_number: int,
        comment: Comment,
        message: str = "Done",
    ) -> ReplyResult:
        """Mark a comment as done.

        Args:
            change_number: The change number
            comment: The Comment object to mark done
            message: Optional message (default: "Done")

        Returns:
            ReplyResult with success status
        """
        return self.reply_to_comment(
            change_number=change_number,
            comment=comment,
            message=message,
            mark_resolved=True,
        )

    def acknowledge(
        self,
        change_number: int,
        comment: Comment,
        message: str = "Acknowledged",
    ) -> ReplyResult:
        """Acknowledge a comment and mark it as resolved.

        Args:
            change_number: The change number
            comment: The Comment object to acknowledge
            message: Optional message (default: "Acknowledged")

        Returns:
            ReplyResult with success status
        """
        return self.reply_to_comment(
            change_number=change_number,
            comment=comment,
            message=message,
            mark_resolved=True,
        )

    def reply_to_thread(
        self,
        change_number: int,
        thread: CommentThread,
        message: str,
        mark_resolved: bool = False,
    ) -> ReplyResult:
        """Reply to a comment thread.

        Replies to the last comment in the thread.

        Args:
            change_number: The change number
            thread: The CommentThread to reply to
            message: Reply message
            mark_resolved: Whether to mark the thread as resolved

        Returns:
            ReplyResult with success status
        """
        # Reply to the last comment in the thread
        last_comment = thread.replies[-1] if thread.replies else thread.root_comment
        return self.reply_to_comment(
            change_number=change_number,
            comment=last_comment,
            message=message,
            mark_resolved=mark_resolved,
        )

    def mark_thread_done(
        self,
        change_number: int,
        thread: CommentThread,
        message: str = "Done",
    ) -> ReplyResult:
        """Mark a thread as done.

        Args:
            change_number: The change number
            thread: The CommentThread to mark done
            message: Optional message (default: "Done")

        Returns:
            ReplyResult with success status
        """
        return self.reply_to_thread(
            change_number=change_number,
            thread=thread,
            message=message,
            mark_resolved=True,
        )

    def batch_reply(
        self,
        change_number: int,
        replies: list[dict[str, Any]],
    ) -> list[ReplyResult]:
        """Post multiple replies in a single API call.

        Args:
            change_number: The change number
            replies: List of dicts with keys:
                - comment: Comment object to reply to
                - message: Reply message
                - mark_resolved: Whether to mark resolved (default False)

        Returns:
            List of ReplyResult for each reply
        """
        # Get current revision
        change = self.client.get_change_detail(change_number)
        current_revision = change.get("current_revision", "current")

        # Build comments dict for batch posting
        comments_dict: dict[str, list[dict[str, Any]]] = {}
        results = []

        for reply_spec in replies:
            comment = reply_spec["comment"]
            message = reply_spec["message"]
            mark_resolved = reply_spec.get("mark_resolved", False)

            if comment.file_path not in comments_dict:
                comments_dict[comment.file_path] = []

            comment_input = {
                "in_reply_to": comment.id,
                "message": message,
                "unresolved": not mark_resolved,
            }

            if comment.line is not None:
                comment_input["line"] = comment.line

            comments_dict[comment.file_path].append(comment_input)

        try:
            self.client.post_review(
                change_number=change_number,
                revision_id=current_revision,
                comments=comments_dict,
            )

            # All succeeded
            for reply_spec in replies:
                results.append(ReplyResult(
                    success=True,
                    comment_id=reply_spec["comment"].id,
                    message=reply_spec["message"],
                    marked_resolved=reply_spec.get("mark_resolved", False),
                ))

        except Exception as e:
            # All failed
            for reply_spec in replies:
                results.append(ReplyResult(
                    success=False,
                    comment_id=reply_spec["comment"].id,
                    message=reply_spec["message"],
                    marked_resolved=False,
                    error=str(e),
                ))

        return results

    def reply_from_extracted(
        self,
        extracted: ExtractedComments,
        thread_index: int,
        message: str,
        mark_resolved: bool = False,
    ) -> ReplyResult:
        """Reply to a thread from extracted comments by index.

        Args:
            extracted: ExtractedComments object
            thread_index: Index of the thread to reply to
            message: Reply message
            mark_resolved: Whether to mark as resolved

        Returns:
            ReplyResult with success status
        """
        if thread_index < 0 or thread_index >= len(extracted.threads):
            return ReplyResult(
                success=False,
                comment_id="",
                message=message,
                marked_resolved=False,
                error=f"Invalid thread index: {thread_index}",
            )

        thread = extracted.threads[thread_index]
        return self.reply_to_thread(
            change_number=extracted.change_info.change_number,
            thread=thread,
            message=message,
            mark_resolved=mark_resolved,
        )

    def push_staged(
        self,
        change_number: int,
        dry_run: bool = False,
    ) -> tuple[bool, str, int]:
        """Push all staged operations for a change.

        Note: Comments are identified by comment_id, so replies will be correctly
        threaded even if the change has moved to a newer patchset since staging.

        Args:
            change_number: The change number
            dry_run: If True, only show what would be pushed without actually pushing

        Returns:
            Tuple of (success, message, operations_count)
        """
        # Load staged operations
        staged = self.staging_manager.load_staged(change_number)

        if staged is None or not staged.operations:
            return False, f"No staged operations for change {change_number}", 0

        # Get current revision for posting
        try:
            change = self.client.get_change_detail(change_number)
            current_revision = change.get("current_revision", "")
            current_patchset = change.get("revisions", {}).get(current_revision, {}).get("_number", 0)

            if current_patchset == 0:
                return False, f"Error: Could not determine current patchset for change {change_number}", len(staged.operations)

            # Note: No patchset validation needed. Comments are identified by comment_id,
            # so replies work correctly even if patchset has changed.

        except ConnectionError as e:
            return False, f"Network error: Could not connect to Gerrit server.\nDetails: {e}", len(staged.operations)
        except TimeoutError as e:
            return False, f"Timeout error: Gerrit server did not respond in time.\nDetails: {e}", len(staged.operations)
        except Exception as e:
            return False, f"Error getting change details: {e}\nPlease check your network connection and try again.", len(staged.operations)

        # In dry-run mode, just show what would be done
        if dry_run:
            msg = f"Would push {len(staged.operations)} operations to Change {change_number}:\n"
            for op in staged.operations:
                action = "RESOLVE" if op.resolve else "COMMENT"
                location = f"{op.file_path}:{op.line}" if op.line else f"{op.file_path}:patchset"
                msg += f"  [{op.thread_index}] {location} - {action}: \"{op.message[:50]}...\"\n"
            return True, msg, len(staged.operations)

        # Build comments dict for batch posting
        comments_dict: dict[str, list[dict[str, Any]]] = {}

        for op in staged.operations:
            if op.file_path not in comments_dict:
                comments_dict[op.file_path] = []

            comment_input = {
                "in_reply_to": op.comment_id,
                "message": op.message,
                "unresolved": not op.resolve,
            }

            if op.line is not None:
                comment_input["line"] = op.line

            comments_dict[op.file_path].append(comment_input)

        # Push all operations in a single API call
        try:
            self.client.post_review(
                change_number=change_number,
                revision_id=current_revision,
                comments=comments_dict,
            )

            # Success: clear staged file
            self.staging_manager.clear_staged(change_number)

            success_msg = f"✓ Pushed {len(staged.operations)} operations to Change {change_number}"
            return True, success_msg, len(staged.operations)

        except ConnectionError as e:
            return False, f"Network error: Could not connect to Gerrit server.\nDetails: {e}\nPlease check your connection and try again.", len(staged.operations)
        except TimeoutError as e:
            return False, f"Timeout error: Gerrit server did not respond.\nDetails: {e}\nPlease try again later.", len(staged.operations)
        except Exception as e:
            error_msg = f"Error pushing operations: {e}"
            # Check if it's a common error and provide helpful message
            if "401" in str(e) or "Unauthorized" in str(e):
                error_msg += "\nPossible cause: Invalid credentials. Check your .env file or environment variables."
            elif "403" in str(e) or "Forbidden" in str(e):
                error_msg += "\nPossible cause: Insufficient permissions for this operation."
            elif "404" in str(e):
                error_msg += f"\nPossible cause: Change {change_number} not found or has been deleted."
            return False, error_msg, len(staged.operations)


def reply_to_comment(
    change_number: int,
    comment: Comment,
    message: str,
    mark_resolved: bool = False,
) -> ReplyResult:
    """Convenience function to reply to a comment.

    Args:
        change_number: The change number
        comment: The Comment object to reply to
        message: Reply message
        mark_resolved: Whether to mark the comment thread as resolved

    Returns:
        ReplyResult with success status
    """
    replier = CommentReplier()
    return replier.reply_to_comment(
        change_number=change_number,
        comment=comment,
        message=message,
        mark_resolved=mark_resolved,
    )


def mark_done(
    change_number: int,
    comment: Comment,
    message: str = "Done",
) -> ReplyResult:
    """Convenience function to mark a comment as done.

    Args:
        change_number: The change number
        comment: The Comment object to mark done
        message: Optional message (default: "Done")

    Returns:
        ReplyResult with success status
    """
    replier = CommentReplier()
    return replier.mark_done(
        change_number=change_number,
        comment=comment,
        message=message,
    )
