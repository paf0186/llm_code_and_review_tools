# Gerrit Comments Tool

Address review comments on a patch series.

## Output Format

All commands return JSON with this structure:
- `ok`: boolean indicating success
- `data`: the response payload (on success)
- `error`: error details (on failure)
- `meta`: metadata including tool name (`gerrit-comments`), command, and timestamp

Use `--pretty` flag for human-readable formatted output.

Example response:
```json
{"ok": true, "data": {...}, "meta": {"tool": "gerrit-comments", "command": "extract", "timestamp": "2026-01-22T12:00:00Z"}}
```

## Quick Start

```bash
# 1. Start reviewing - checks out first patch with comments
gerrit-comments review-series <URL>

# 2. For each patch: fix issues, stage replies, finish
gerrit-comments stage --done <index>        # Mark comment as done
gerrit-comments stage <index> "message"     # Reply with message
git add <files> && git commit --amend --no-edit
gerrit-comments finish-patch                # Auto-advances to next

# 3. When done
gerrit-comments abort --keep-changes
git push origin HEAD:refs/for/master
```

## Commands

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
review <URL>                     # Get code changes for review
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

Exit codes:
- 0: Success
- 1: General error
- 2: Authentication error
- 3: Not found
- 4: Invalid input
- 5: Network error

Error responses include:
- `code`: Machine-readable error code (e.g., `CHANGE_NOT_FOUND`, `INVALID_URL`)
- `message`: Human-readable description
- `http_status`: HTTP status code (if applicable)
- `details`: Additional context

## Tips for LLM Agents

1. **Parse the `ok` field** first to determine success/failure
2. **Use `--pretty`** when debugging or showing output to users
3. **Check series-status** before starting work on a patch series
4. **Stage replies as you go** - don't forget to stage before finish-patch
5. **Handle exit codes** to distinguish error types

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linter
ruff check gerrit_comments/

# Run tests
pytest gerrit_comments/tests/

# Run tests with coverage
pytest gerrit_comments/tests/ --cov=gerrit_comments
```

Pre-commit hook runs linting automatically.
