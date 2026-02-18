# LLM Code and Review Tools - Development Guide

This repository contains CLI tools for LLM agents: `jira` and `gerrit-comments`.

For tool usage documentation (to be installed in other repos), see [docs/TOOL_USAGE.md](docs/TOOL_USAGE.md).

## Project Structure

```
llm_code_and_review_tools/
├── jira_tool/           # JIRA CLI tool
│   ├── cli.py           # Click-based CLI
│   ├── client.py        # REST API client
│   ├── config.py        # Configuration
│   ├── envelope.py      # JSON response formatting
│   └── errors.py        # Error codes
├── gerrit_comments/     # Gerrit review tool
│   ├── cli.py           # Command handlers
│   ├── client.py        # Gerrit API client
│   └── ...
├── llm_tool_common/     # Shared utilities
├── docs/                # Documentation for tool users
│   └── TOOL_USAGE.md    # Agent instructions for using the tools
└── .beads/              # Issue tracking database
```

---

## Issue Tracking with Beads

This project uses **beads** (`bd`) for issue tracking. Issues are prefixed with `jira-`.

### Configuration

**IMPORTANT**: This repository is configured to use a separate `beads-sync` branch to keep beads metadata commits out of the main git history. The `.beads/config.yaml` file has:

```yaml
sync-branch: "beads-sync"
```

This means:
- Beads commits go to the `beads-sync` branch automatically
- The main development history stays clean
- You periodically merge `beads-sync` to `main` (or create PRs) to sync issue tracking state

**Do NOT comment out the `sync-branch` setting** - this would cause beads commits to pollute the main git history.

### Quick Reference

| Command | Action |
|---------|--------|
| `bd ready` | Find unblocked work |
| `bd list --status=open` | All open issues |
| `bd show <id>` | View issue details |
| `bd create --title="..." --type=feature --priority=2` | Create issue |
| `bd update <id> --status=in_progress` | Claim work |
| `bd close <id>` | Complete work |
| `bd stats` | Project health |

### Priority Values

Use numeric priorities 0-4:
- **P0**: Critical/blocking
- **P1**: High priority
- **P2**: Medium (default)
- **P3**: Low priority
- **P4**: Backlog

### Starting Work (Claiming a Bead)

⚠️ **Race Condition Warning**: Beads uses a local SQLite database. Status changes are LOCAL until you sync and push. Without the full claim sequence below, another worker may see the same bead as available and claim it too.

**Always use the full claim sequence:**

```bash
bd ready                              # Find available work
bd show <id>                          # Review issue details
bd update <id> --status in_progress   # Claim locally
bd sync                               # Export to JSONL and commit to beads-sync branch
git push origin beads-sync            # Push beads-sync branch immediately!
```

Only after `git push` succeeds is the bead truly claimed. If push fails (someone else claimed it), pick a different bead.

**Note**: With `sync-branch` configured, `bd sync` automatically commits to the `beads-sync` branch. You don't need to manually `git add` or `git commit` - just push the `beads-sync` branch.

### Completing Work

```bash
bd close <id>                         # Mark complete
bd sync                               # Sync beads with git (commits to beads-sync branch)
git add . && git commit -m "..."      # Commit your code changes to main branch
git push origin HEAD                  # Push your code changes
git push origin beads-sync            # Push beads metadata
```

### Merging Beads Metadata to Main

Periodically (e.g., weekly or when convenient), merge the `beads-sync` branch to `main` to sync issue tracking state:

```bash
git checkout main
git pull origin main
git merge origin/beads-sync
git push origin main
```

Or create a PR from `beads-sync` to `main` if you prefer code review.

### Important Notes

- **Do NOT use** `bd edit` - it opens an editor which blocks agents
- **No distributed locking** - beads is local-first; always push claims immediately
- **Do NOT comment out `sync-branch`** in `.beads/config.yaml` - this keeps beads commits separate
- Run `bd prime` after context compaction or new session
- Use `bd doctor` to check for sync problems
- The `beads-sync` branch is for metadata only; your code changes go to your normal working branch

---

## Development Workflow

### Building

```bash
pip install -e .                      # Install in development mode
# or
make install                          # Uses Makefile
```

### Testing

```bash
# Run all tests
pytest

# Run specific tool tests
pytest jira_tool/tests/
pytest gerrit_comments/tests/

# With coverage
pytest --cov=jira_tool --cov=gerrit_comments
```

### Code Style

- Use dataclasses for data structures
- Use type hints throughout
- Keep functions focused and under ~60 lines
- Follow existing patterns in the codebase
- All new functionality must include tests

### JSON Output Format

All tools use a standard envelope:

```json
{
  "ok": true,
  "data": { ... },
  "meta": {
    "tool": "jira",
    "command": "issue.get",
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

---

## Session Close Protocol

Before ending a work session:

1. `git status` - Check what changed
2. `git add <files>` - Stage your code changes
3. `git commit -m "..."` - Commit your code changes
4. `bd sync` - Sync beads database (commits to beads-sync branch)
5. `git push origin HEAD` - Push your code changes (MANDATORY)
6. `git push origin beads-sync` - Push beads metadata (MANDATORY)

Work is NOT complete until both pushes succeed.

**Note**: Your code changes and beads metadata are on separate branches. Make sure to push both!
