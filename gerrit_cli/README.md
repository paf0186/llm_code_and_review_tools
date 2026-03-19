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

## Series Graph (DAG Visualizer)

Visualize the full DAG of all related changes for a patch series as an
interactive HTML graph. Unlike `series` which traces a single linear chain,
`graph` shows the complete topology — branches, abandoned forks, stale
patchsets, and which patches need rebasing.

```bash
# Generate and open interactive graph (default: opens in browser)
gc graph https://review.whamcloud.com/c/fs/lustre-release/+/61962

# Just a change number (uses GERRIT_URL)
gc graph 61962

# Save to a specific file
gc graph 61962 -o series.html

# Generate without opening browser
gc graph 61962 --no-open

# Include detailed inline comments (slower, fetches per-change)
gc graph 61962 --comments

# Skip CI link fetching for faster generation
gc graph 61962 --skip-ci-details
```

The generated HTML is self-contained (uses vis.js from CDN) and includes:

- **Vertical tree layout** growing upward from the anchor change
- **Review health coloring**: green (verified OK + 2 non-author CR +1s),
  red (any verified -1 or CR veto), blue (pending)
- **Review status line** on each node: verified voters (J:+1 M:-1) and
  code review summary (CR: 3x(+1))
- **Unresolved comment count** on nodes (from batch query, no extra calls)
- **Edge labels** showing which patchset each dependency goes through
  (e.g., `ps57`). Stale edges show `ps53->57` in orange with dashed lines
- **Click-to-re-anchor**: click any node to make it the new starting point;
  the tree re-layouts with that node as the root
- **Filters**: toggle abandoned/stale branches on/off
- **Side panel**: click a node to see full details including:
  - Review health badge, all verified voters with clickable Jenkins/Maloo links
  - Code review votes with reviewer names (author votes dimmed)
  - Unresolved comments list with clickable links to Gerrit (with `--comments`)
  - Chain of dependents/dependencies, and a "Re-anchor here" button
- **Dark/Light mode**: toggle with the "Light" button
- **Keyboard shortcuts**: `F` = fit to screen, `Z` = focus/zoom to selected
  node, `R` = reset to initial anchor

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
graph <URL>                      # Interactive DAG visualizer (see above)
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
