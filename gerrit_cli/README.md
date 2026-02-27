# Gerrit CLI Tool

CLI for Gerrit code review: extract/reply to comments, manage reviewers,
triage Maloo test results, review patch series, and manage changes.

## Installation

```bash
cd /shared/llm_code_and_review_tools/gerrit_cli && ./install.sh
# or: pip install -e .
```

Configure via environment variables or `~/.config/gerrit-cli/.env`:
```bash
export GERRIT_URL="https://review.whamcloud.com"
export GERRIT_USER="your-username"
export GERRIT_PASS="your-http-password"
```

If `gerrit-cli` is not found after install, add `$HOME/.local/bin` to PATH.

## Output Format

All commands return JSON: `{"ok": true, "data": {...}, "meta": {"tool": "gerrit-cli", ...}}`

## Quick Start

```bash
# 1. Start reviewing - checks out first patch with comments
gc review-series <URL>

# 2. For each patch: fix issues, stage replies, finish
gc stage --done <index>        # Mark comment as done
gc stage <index> "message"     # Reply with message
git add <files> && git commit --amend --no-edit
gc finish-patch                # Auto-advances to next

# 3. When done
gc abort --keep-changes
git push origin HEAD:refs/for/master
```

## Commands

### Comments & Review
```bash
comments <URL>                   # Get unresolved comments
reply <thread_index> "msg"       # Reply to a comment
reply <thread_index> --done      # Mark as done
review <URL>                     # Get code changes for review
```

### Workflow
```bash
review-series <URL>              # Start review, checkout first patch
stage --done <index>             # Stage "Done" reply
stage <index> "message"          # Stage reply with message
finish-patch                     # Complete patch, auto-advance
abort                            # End session, restore original state
abort --keep-changes             # End session, keep current state
```

### Navigation
```bash
work-on-patch <URL> <change>     # Jump to specific patch
next-patch                       # Manually advance to next patch
status                           # Check session status (default if in session)
```

### Information
```bash
series-status <URL>              # Show status of all patches in series
series-comments <URL>            # Get comments for all patches in series
info <URL>                       # Show change info (reviewers, labels, etc.)
maloo <URL> [URL...]             # Triage Maloo CI results (batch mode)
watch <json-file>                # Check CI status on watched patches
```

### Reviewer Management
```bash
add-reviewer <URL> "Name"        # Add a reviewer to a change
reviewers <URL>                  # List reviewers on a change
```

### Change Management
```bash
checkout <URL>                   # Fetch and checkout a Gerrit change
abandon <URL>                    # Abandon a Gerrit change
message <URL> "text"             # Post a top-level message
```

### Interactive Mode
```bash
interactive <URL>                # Interactive mode for reviewing comments
i <URL>                          # Shorthand for interactive
```

### Staging Management
```bash
staged list                      # List all staged operations
staged show <change>             # Show staged for specific change
staged remove <change> <index>   # Remove one staged operation
staged clear [change]            # Clear staged (one change or all)
staged refresh <url>             # Refresh staged metadata
push <change>                    # Push staged operations for a change
```

### Reintegration (for stale patches)
```bash
continue-reintegration           # Continue after resolving conflicts
skip-reintegration               # Skip conflicting change
```

## Key Points

1. **Work earliest to latest** - finish-patch rebases all later patches
2. **Stage replies as you fix** - Don't forget to stage for each comment
3. **finish-patch auto-advances** - Finds the next patch with comments
4. **Conflicts?** - Fix them, run `git add`, then `finish-patch` again
5. **Stale patches?** - Auto-reintegrated (or prompts for conflict resolution)

## Error Handling

Exit codes: 0=success, 1=general, 2=auth, 3=not found, 4=invalid input, 5=network.

Error responses include: `code` (machine-readable), `message` (human-readable),
`http_status`, and `details`.

## Development

```bash
pip install -e ".[dev]"
pytest gerrit_cli/tests/
pytest gerrit_cli/tests/ --cov=gerrit_cli
ruff check gerrit_cli/
```
