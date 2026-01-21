#!/usr/bin/env python3
"""Command-line interface for Gerrit comments tools.

This CLI provides commands for:
1. extract - Extract unresolved comments from a Gerrit change
2. reply - Reply to comments or mark them as done
3. review - Get diff/changes for code review, optionally post review comments

Examples:
    # Extract unresolved comments
    gerrit-comments extract https://review.whamcloud.com/c/fs/lustre-release/+/62796

    # Extract with JSON output
    gerrit-comments extract --json https://review.whamcloud.com/c/fs/lustre-release/+/62796

    # Reply to a comment (by thread index from extract output)
    gerrit-comments reply https://review.whamcloud.com/c/fs/lustre-release/+/62796 0 "Done"

    # Mark a comment as done
    gerrit-comments reply --done https://review.whamcloud.com/c/fs/lustre-release/+/62796 0

    # Get changes for code review
    gerrit-comments review https://review.whamcloud.com/c/fs/lustre-release/+/62796

    # Get changes as JSON for programmatic use
    gerrit-comments review --json https://review.whamcloud.com/c/fs/lustre-release/+/62796

    # Post a code review with comments from JSON file
    gerrit-comments review --post-comments comments.json https://review.whamcloud.com/62796
"""

import argparse
import json
import sys

from .client import GerritCommentsClient
from .extractor import extract_comments
from .interactive import run_interactive
from .interactive_vim import run_interactive_vim
from .rebase import (
    RebaseManager,
    abort_patch,
    end_session,
    finish_patch,
    get_session_info,
    get_session_url,
    next_patch,
    rebase_status,
    work_on_patch,
)
from .replier import CommentReplier
from .reviewer import CodeReviewer
from .series import SeriesFinder
from .series_status import show_series_status
from .staging import StagingManager


def generate_review_prompt(url: str) -> str:
    """Generate a prompt for AI-assisted patch series review.

    Args:
        url: URL to any patch in the series

    Returns:
        Formatted prompt string
    """
    return f"""Address comments on this patch series.

Start: gerrit-comments review-series {url}
  (shows series, checks out first patch with comments)

For each patch:
  1. Review comments shown, make fixes
  2. Stage replies:  gerrit-comments stage --done <index>
                     gerrit-comments stage <index> "message"
  3. Commit:         git add <files> && git commit --amend --no-edit
  4. Next patch:     gerrit-comments finish-patch
     (rebases descendants, advances to next patch with comments)

For substantive issues, ask me before making changes.

When done: gerrit-comments end-session
To abort: gerrit-comments abort-session (discards all changes)"""


def cmd_extract(args):
    """Extract comments from a Gerrit change."""
    try:
        result = extract_comments(
            url=args.url,
            include_resolved=args.all,
            include_code_context=not args.no_context,
            context_lines=args.context_lines,
        )

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(result.format_summary())

            # Print numbered list for easy reference
            if result.threads:
                print("\n" + "=" * 60)
                print("Thread Index Reference (use with 'reply' command):")
                print("=" * 60)
                for i, thread in enumerate(result.threads):
                    loc = f"{thread.root_comment.file_path}:{thread.root_comment.line or 'patchset'}"
                    author = thread.root_comment.author.name
                    msg_preview = thread.root_comment.message[:50].replace("\n", " ")
                    print(f"  [{i}] {loc}")
                    print(f"      {author}: {msg_preview}...")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error extracting comments: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reply(args):
    """Reply to a comment."""
    try:
        # Parse URL to get change number
        base_url, change_number = GerritCommentsClient.parse_gerrit_url(args.url)

        # Extract to get the threads
        result = extract_comments(
            url=args.url,
            include_resolved=False,
            include_code_context=False,
        )

        if args.thread_index >= len(result.threads):
            print(f"Error: Thread index {args.thread_index} out of range. Only {len(result.threads)} threads.", file=sys.stderr)
            sys.exit(1)

        thread = result.threads[args.thread_index]

        # Determine message and resolved status
        if args.done:
            message = args.message or "Done"
            mark_resolved = True
        elif args.ack:
            message = args.message or "Acknowledged"
            mark_resolved = True
        else:
            message = args.message
            mark_resolved = args.resolve

        if not message:
            print("Error: Message is required (or use --done/--ack)", file=sys.stderr)
            sys.exit(1)

        # Post the reply
        replier = CommentReplier()
        reply_result = replier.reply_to_thread(
            change_number=change_number,
            thread=thread,
            message=message,
            mark_resolved=mark_resolved,
        )

        if reply_result.success:
            action = "Marked as done" if mark_resolved else "Posted reply"
            print(f"✓ {action} on {thread.root_comment.file_path}:{thread.root_comment.line or 'patchset'}")
            if args.json:
                print(json.dumps(reply_result.to_dict(), indent=2))
        else:
            print(f"✗ Failed: {reply_result.error}", file=sys.stderr)
            sys.exit(1)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error posting reply: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_batch_reply(args):
    """Reply to multiple comments from a JSON file."""
    try:
        # Load replies from JSON file
        with open(args.file) as f:
            replies_data = json.load(f)

        # Parse URL
        base_url, change_number = GerritCommentsClient.parse_gerrit_url(args.url)

        # Extract to get threads
        result = extract_comments(
            url=args.url,
            include_resolved=False,
            include_code_context=False,
        )

        # Build reply list
        replies = []
        for item in replies_data:
            thread_idx = item['thread_index']
            if thread_idx >= len(result.threads):
                print(f"Warning: Thread index {thread_idx} out of range, skipping", file=sys.stderr)
                continue

            thread = result.threads[thread_idx]
            last_comment = thread.replies[-1] if thread.replies else thread.root_comment

            replies.append({
                'comment': last_comment,
                'message': item['message'],
                'mark_resolved': item.get('mark_resolved', False),
            })

        # Post all replies
        replier = CommentReplier()
        results = replier.batch_reply(change_number=change_number, replies=replies)

        # Report results
        success_count = sum(1 for r in results if r.success)
        print(f"Posted {success_count}/{len(results)} replies")

        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_review(args):
    """Get code changes for review, optionally post review comments."""
    try:
        reviewer = CodeReviewer()

        # Get review data
        review_data = reviewer.get_review_data(
            url=args.url,
            include_file_content=args.full_content,
        )

        # If posting comments from file
        if args.post_comments:
            with open(args.post_comments) as f:
                review_spec = json.load(f)

            result = reviewer.post_review(
                change_number=review_data.change_info.change_number,
                comments=review_spec.get('comments', []),
                message=review_spec.get('message'),
                vote=review_spec.get('vote'),
            )

            if result.success:
                print(f"✓ Posted review with {result.comments_posted} comments")
                if result.vote is not None:
                    print(f"  Code-Review vote: {result.vote:+d}")
            else:
                print(f"✗ Failed: {result.error}", file=sys.stderr)
                sys.exit(1)
            return

        # Output the review data
        if args.json:
            print(json.dumps(review_data.to_dict(), indent=2))
        elif args.changes_only:
            # Just show changed lines
            for f in review_data.files:
                print(f"=== {f.path} ({f.status}) +{f.lines_added}/-{f.lines_deleted} ===")
                for hunk in f.hunks:
                    for line in hunk.lines:
                        if line.type == 'added':
                            print(f"{line.line_number_new:5d}+ {line.content}")
                        elif line.type == 'deleted':
                            print(f"{line.line_number_old:5d}- {line.content}")
                print()
        else:
            print(review_data.format_for_review())

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_series_comments(args):
    """Get all unresolved comments from all patches in a series."""
    try:
        finder = SeriesFinder()
        result = finder.get_series_comments(
            url=args.url,
            include_resolved=args.all,
            include_code_context=not args.no_context,
            context_lines=args.context_lines,
            show_progress=not args.json,  # Show progress for interactive use
        )

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(result.format_summary())

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error getting series comments: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_series(args):
    """Find all patches in a series and show AI review prompt."""
    try:
        # Check git state FIRST before any slow operations (fail fast)
        no_checkout = getattr(args, 'no_checkout', False)
        if not no_checkout and not (args.json or args.urls_only or args.numbers_only):
            manager = RebaseManager()
            ready, msg = manager.check_git_repo()
            if not ready:
                print(f"Error: {msg}", file=sys.stderr)
                sys.exit(1)

        finder = SeriesFinder()
        series = finder.find_series(
            url=args.url,
            include_abandoned=args.include_abandoned,
        )

        if args.json:
            print(json.dumps(series.to_dict(), indent=2))
        elif args.urls_only:
            # Just print URLs, one per line
            for patch in series.patches:
                print(patch.url)
        elif args.numbers_only:
            # Just print change numbers, one per line
            for patch in series.patches:
                print(patch.change_number)
        else:
            # Show prompt FIRST (before slow comment fetching)
            no_prompt = getattr(args, 'no_prompt', False)
            if not no_prompt:
                print("=" * 70)
                print("AI REVIEW PROMPT")
                print("=" * 70)
                print(generate_review_prompt(args.url))

            print(series.format_summary())

            # Fetch comment counts for each patch
            total = len(series.patches)
            patch_comments = {}
            for i, patch in enumerate(series.patches, 1):
                # Progress indicator with carriage return to overwrite
                print(f"\rFetching comments... ({i}/{total}) {patch.change_number}", end="", flush=True)
                try:
                    result = extract_comments(
                        url=patch.url,
                        include_resolved=False,
                        include_code_context=False,
                    )
                    patch_comments[patch.change_number] = len(result.threads)
                except Exception:
                    patch_comments[patch.change_number] = -1  # Error fetching
            # Clear the progress line
            print("\r" + " " * 60 + "\r", end="")

            # Show patches with comment counts
            print("\nPatches (in order):")
            patches_with_comments = []
            for i, patch in enumerate(series.patches, 1):
                count = patch_comments.get(patch.change_number, 0)
                if count > 0:
                    comment_str = f" [{count} comment{'s' if count > 1 else ''}]"
                    patches_with_comments.append(patch.change_number)
                elif count < 0:
                    comment_str = " [error fetching comments]"
                else:
                    comment_str = ""
                marker = " <-- queried" if patch.change_number == series.target_change else ""
                print(f"{i:3}. {patch.change_number}: {patch.subject[:50]}{comment_str}{marker}")

            # Summary of patches needing attention
            if patches_with_comments:
                print(f"\n→ {len(patches_with_comments)} patch(es) with unresolved comments: {', '.join(map(str, patches_with_comments))}")
                first_with_comments = patches_with_comments[0]
            else:
                print("\n→ No patches have unresolved comments")
                first_with_comments = None

            # Checkout (unless --no-checkout)
            if not no_checkout:
                if first_with_comments:
                    print("\n" + "=" * 70)
                    print(f"CHECKING OUT PATCH {first_with_comments}")
                    print("=" * 70)
                    success, message = work_on_patch(args.url, first_with_comments)
                    print(message)
                    if not success:
                        sys.exit(1)
                else:
                    # No patches with comments - checkout the first patch
                    first_patch = series.patches[0].change_number
                    print("\n" + "=" * 70)
                    print(f"CHECKING OUT FIRST PATCH {first_patch}")
                    print("=" * 70)
                    success, message = work_on_patch(args.url, first_patch)
                    print(message)
                    if not success:
                        sys.exit(1)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error finding series: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_interactive(args):
    """Run interactive mode for reviewing series comments."""
    try:
        if args.vim:
            run_interactive_vim(args.url)
        else:
            run_interactive(args.url)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error in interactive mode: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_series_status(args):
    """Show status dashboard for a patch series."""
    try:
        result = show_series_status(args.url, output_json=args.json)
        print(result)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_work_on_patch(args):
    """Start working on a specific patch in a series."""
    try:
        # If URL not provided, try to get it from active session
        url = args.url
        if url is None:
            url = get_session_url()
            if url is None:
                print("Error: No URL provided and no active session.", file=sys.stderr)
                print("Start a session with: gerrit-comments work-on-patch <change> <url>", file=sys.stderr)
                sys.exit(1)
            print(f"Using URL from active session: {url}")

        success, message = work_on_patch(url, args.change_number)
        print(message)
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_next_patch(args):
    """Move to the next patch in the series."""
    try:
        success, message = next_patch(with_comments=args.with_comments)
        print(message)
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_finish_patch(args):
    """Finish working on the current patch."""
    try:
        auto_next = not getattr(args, 'stay', False)
        success, message = finish_patch(auto_next=auto_next)
        print(message)
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_abort(args):
    """End the current session (abort or keep changes)."""
    try:
        if getattr(args, 'keep_changes', False):
            success, message = end_session()
        else:
            success, message = abort_patch()
        print(message)
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    """Show current rebase session status."""
    try:
        has_session, message = rebase_status()
        print(message)
        if not has_session:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_continue_reintegration(args):
    """Continue reintegration after conflict resolution."""
    try:
        from .rebase import RebaseManager
        manager = RebaseManager()
        success, message = manager.continue_reintegration()
        print(message)
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_skip_reintegration(args):
    """Skip the current change during reintegration."""
    try:
        from .rebase import RebaseManager
        manager = RebaseManager()
        success, message = manager.skip_reintegration()
        print(message)
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_stage(args):
    """Stage a comment reply without posting."""
    try:
        # Get URL from args or session
        url = args.url
        if url is None:
            # Try to get from active session
            session_info = get_session_info()
            if session_info:
                # Construct URL for current patch
                target_change = session_info['target_change']
                base = session_info['series_url'].rsplit('/', 1)[0]
                url = f"{base}/{target_change}"
                print(f"Using current patch: {target_change}")
            else:
                print("Error: No URL provided and no active session.", file=sys.stderr)
                print("Start a session with: gerrit-comments work-on-patch <change> <url>", file=sys.stderr)
                sys.exit(1)

        # Parse URL to get change number
        base_url, change_number = GerritCommentsClient.parse_gerrit_url(url)

        # Extract to get the threads
        result = extract_comments(
            url=url,
            include_resolved=False,
            include_code_context=False,
        )

        if args.thread_index >= len(result.threads):
            print(f"Error: Thread index {args.thread_index} out of range. Only {len(result.threads)} threads.", file=sys.stderr)
            sys.exit(1)

        thread = result.threads[args.thread_index]

        # Determine message and resolved status
        if args.done:
            message = args.message or "Done"
            resolve = True
        elif args.ack:
            message = args.message or "Acknowledged"
            resolve = True
        else:
            message = args.message
            resolve = args.resolve

        if not message:
            print("Error: Message is required (or use --done/--ack)", file=sys.stderr)
            sys.exit(1)

        # Get last comment in thread
        last_comment = thread.replies[-1] if thread.replies else thread.root_comment

        # Get current patchset from change detail
        client = GerritCommentsClient()
        change = client.get_change_detail(change_number)
        current_revision = change.get("current_revision", "")
        current_patchset = change.get("revisions", {}).get(current_revision, {}).get("_number", 0)

        # Stage the operation
        staging_mgr = StagingManager()
        staging_mgr.stage_operation(
            change_number=change_number,
            thread_index=args.thread_index,
            file_path=last_comment.file_path,
            line=last_comment.line,
            message=message,
            resolve=resolve,
            comment_id=last_comment.id,
            patchset=current_patchset,
            change_url=result.change_info.url,
        )

        action = "resolve" if resolve else "comment on"
        loc = f"{last_comment.file_path}:{last_comment.line or 'patchset'}"
        print(f"✓ Staged operation to {action} {loc}")
        print(f"  Message: \"{message[:50]}{'...' if len(message) > 50 else ''}\"")
        print(f"\nUse 'gerrit-comments push {change_number}' to post all staged operations")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error staging operation: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_push(args):
    """Push all staged operations for a change."""
    try:
        replier = CommentReplier()
        success, message, count = replier.push_staged(
            change_number=args.change_number,
            dry_run=args.dry_run,
        )

        print(message)

        if not success:
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_staged_list(args):
    """List all patches with staged operations."""
    try:
        staging_mgr = StagingManager()
        staged_patches = staging_mgr.list_all_staged()

        if not staged_patches:
            print("No staged operations")
            return

        if args.json:
            output = [
                {
                    "change_number": sp.change_number,
                    "patchset": sp.patchset,
                    "operation_count": len(sp.operations),
                }
                for sp in staged_patches
            ]
            print(json.dumps(output, indent=2))
        else:
            print(f"Staged operations for {len(staged_patches)} patch(es):\n")
            for sp in staged_patches:
                print(f"Change {sp.change_number} (patchset {sp.patchset}):")
                print(f"  {len(sp.operations)} operation(s) staged")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_staged_show(args):
    """Show staged operations for a specific patch."""
    try:
        staging_mgr = StagingManager()
        staged = staging_mgr.load_staged(args.change_number)

        if staged is None or not staged.operations:
            print(f"No staged operations for change {args.change_number}")
            return

        if args.json:
            print(json.dumps(staged.to_dict(), indent=2))
        else:
            print(f"Staged operations for Change {staged.change_number} (patchset {staged.patchset}):\n")
            for i, op in enumerate(staged.operations):
                action = "RESOLVE" if op.resolve else "COMMENT"
                location = f"{op.file_path}:{op.line}" if op.line else f"{op.file_path}:patchset"
                print(f"[{i}] {location}")
                print(f"    Action: {action}")
                print(f"    Thread index: {op.thread_index}")
                print(f"    Message: \"{op.message}\"")
                print()

            print(f"Total: {len(staged.operations)} operation(s)")
            print(f"\nUse 'gerrit-comments push {args.change_number}' to post all operations")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_staged_remove(args):
    """Remove a specific staged operation."""
    try:
        staging_mgr = StagingManager()
        success = staging_mgr.remove_operation(args.change_number, args.operation_index)

        if success:
            print(f"✓ Removed operation {args.operation_index} from change {args.change_number}")
        else:
            print("✗ Failed to remove operation (check change number and index)", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_staged_clear(args):
    """Clear staged operations for a patch (or all if no change specified)."""
    try:
        staging_mgr = StagingManager()
        change_number = getattr(args, 'change_number', None)
        if change_number:
            staging_mgr.clear_staged(change_number)
            print(f"✓ Cleared all staged operations for change {change_number}")
        else:
            count = staging_mgr.clear_all_staged()
            print(f"✓ Cleared staged operations for {count} change(s)")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_staged_refresh(args):
    """Refresh patchset number for staged operations."""
    try:
        staging_mgr = StagingManager()
        client = GerritCommentsClient()

        # Get current patchset
        change = client.get_change_detail(args.change_number)
        current_revision = change.get("current_revision", "")
        current_patchset = change.get("revisions", {}).get(current_revision, {}).get("_number", 0)

        if current_patchset == 0:
            print(f"Error: Could not determine current patchset for change {args.change_number}", file=sys.stderr)
            sys.exit(1)

        # Update staged patchset
        success = staging_mgr.update_patchset(args.change_number, current_patchset)

        if success:
            print(f"✓ Updated staged operations for change {args.change_number} to patchset {current_patchset}")
        else:
            print(f"✗ No staged operations found for change {args.change_number}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point."""
    from .parsers import setup_parsers

    parser = argparse.ArgumentParser(
        description="Extract and reply to Gerrit review comments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Map command names to handler functions
    handlers = {
        'review': cmd_review,
        'series_comments': cmd_series_comments,
        'series': cmd_series,
        'series_status': cmd_series_status,
        'interactive': cmd_interactive,
        'work_on_patch': cmd_work_on_patch,
        'next_patch': cmd_next_patch,
        'finish_patch': cmd_finish_patch,
        'abort': cmd_abort,
        'status': cmd_status,
        'stage': cmd_stage,
        'push': cmd_push,
        'staged_list': cmd_staged_list,
        'staged_show': cmd_staged_show,
        'staged_remove': cmd_staged_remove,
        'staged_clear': cmd_staged_clear,
        'staged_refresh': cmd_staged_refresh,
        'continue_reintegration': cmd_continue_reintegration,
        'skip_reintegration': cmd_skip_reintegration,
    }

    setup_parsers(subparsers, handlers)

    args = parser.parse_args()

    if not args.command:
        # If there's an active session, show status by default
        from .rebase import RebaseManager
        manager = RebaseManager()
        if manager.has_active_session():
            cmd_status(args)
        else:
            parser.print_help()
            sys.exit(1)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
