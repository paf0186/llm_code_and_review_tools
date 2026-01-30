# Gerrit Comments Architecture

This document describes the code architecture of the `gerrit_comments` package.

## Overview

`gerrit_comments` is a CLI tool for working with Gerrit code review comments. It
provides functionality for fetching, reviewing, and replying to comments, as well
as managing patch series and rebasing workflows.

## Module Structure

```
gerrit_comments/
├── __init__.py          # Package exports and entry point
├── cli.py               # Command handlers (cmd_* functions)
├── parsers.py           # Argparse definitions for all commands
├── client.py            # Gerrit REST API client
├── models.py            # Data models (Comment, FileComments, etc.)
├── extractor.py         # Comment extraction and formatting
├── reviewer.py          # Interactive review workflow
├── replier.py           # Reply drafting and submission
├── series.py            # Patch series discovery and analysis
├── series_status.py     # Series status display
├── staging.py           # Staging area for pending replies
├── session.py           # Session persistence (RebaseSession, SessionManager)
├── rebase.py            # Rebase workflow management
├── reintegration.py     # Stale patch reintegration logic
├── git_utils.py         # Git helper functions
├── interactive.py       # Basic interactive mode
├── interactive_vim.py   # Vim-based interactive mode
└── tmux_vim.py          # Tmux/Vim split-pane integration
```

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLI Layer                               │
│  cli.py (command handlers) ← parsers.py (argument parsing)      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Workflow Layer                             │
│  reviewer.py    series.py    rebase.py    replier.py            │
│                              reintegration.py                    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Core Layer                                │
│  client.py (API)    models.py    extractor.py    staging.py     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Utility Layer                               │
│  git_utils.py    tmux_vim.py    interactive_vim.py              │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### CLI Layer

- **cli.py**: Contains `cmd_*` functions that handle each subcommand. Orchestrates
  calls to lower layers.
- **parsers.py**: All argparse setup extracted for maintainability. Defines
  subcommands and their arguments.

### Workflow Layer

- **reviewer.py**: Manages the interactive review workflow. Handles comment
  navigation, display, and user interaction.
- **series.py**: Discovers and analyzes patch series from Gerrit. Detects stale
  patches and series relationships.
- **rebase.py**: Manages rebase sessions with persistent state. Handles
  cherry-picking descendants after rebasing a patch.
- **reintegration.py**: Handles the complex state machine for reintegrating
  stale patches into a series.
- **replier.py**: Manages reply composition and submission to Gerrit.

### Core Layer

- **client.py**: `GerritClient` class wrapping the Gerrit REST API. Handles
  authentication and request formatting.
- **models.py**: Data classes for `Comment`, `FileComments`, `ChangeInfo`, etc.
- **extractor.py**: Extracts comments from Gerrit API responses and formats
  them for display.
- **staging.py**: Manages the staging area for pending reply drafts.

### Utility Layer

- **git_utils.py**: `GitRunner` class and helper functions for git operations
  (cherry-pick, checkout, branch management).
- **tmux_vim.py**: Integration with tmux for split-pane workflows with Vim.
- **interactive_vim.py**: Vim-based interactive review mode.

## Data Flow

### Fetching Comments

```
CLI (fetch) → GerritClient.get_change_comments()
            → Extractor.extract_comments()
            → models.FileComments
            → formatted output
```

### Review Workflow

```
CLI (review-series) → series.discover_series()
                    → reviewer.ReviewSession
                    → user interaction loop
                    → staging.StagingArea (for replies)
                    → replier.submit_replies()
```

### Rebase Workflow

```
CLI (start-patch) → rebase.RebaseManager
                  → session.SessionManager (persistence)
                  → session.RebaseSession (state)
                  → git_utils (cherry-pick operations)
                  → reintegration.ReintegrationManager (if stale patches)
```

## State Management

### Persistent State

- **RebaseSession**: Saved to `~/.gerrit_rebase_session.json`. Tracks:
  - Target change and commit
  - Series patches
  - Rebased/skipped changes
  - Reintegration state (if active)

- **StagingArea**: Saved to `~/.gerrit_staging/`. Stores pending reply drafts.

### Reintegration State Machine

When patches in a series have newer patchsets:

1. **Start**: Fetch stale patch, checkout, begin cherry-picking descendants
2. **Cherry-pick**: Cherry-pick each descendant in order
3. **Conflict**: Wait for user to resolve, then continue or skip
4. **Advance**: Move to next stale patch or complete
5. **Complete**: Clear reintegration state, return to normal workflow

## Testing

Tests are in `gerrit_comments/tests/`. Each module has a corresponding test file:

- `test_cli.py`, `test_client.py`, `test_extractor.py`, etc.
- Use pytest with coverage: `pytest --cov=gerrit_comments`
- Current coverage: 91% with 529 tests

## Key Design Decisions

1. **Extracted parsers.py**: Keeps CLI argument definitions separate from
   command logic for maintainability.

2. **Extracted git_utils.py**: Centralizes git operations with consistent
   error handling and testability.

3. **Extracted reintegration.py**: Encapsulates complex reintegration state
   machine with its own dataclasses.

4. **Session persistence**: Allows long-running workflows (rebase, review)
   to survive interruptions.

5. **Layered architecture**: Clear separation between CLI, workflow, core,
   and utility layers.

6. **Dataclass serialization patterns**: Data classes implement `to_dict()`
   and `from_dict()` classmethods for JSON persistence and interoperability.

7. **Action handler pattern**: Interactive modules (interactive.py) separate
   action handling from input gathering for better testability.

