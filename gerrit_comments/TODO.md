# gerrit-comments TODO

## Series Workflow Improvements

### High Priority (Biggest Pain Points)

#### 1. Series-Level Bulk Operations
**Status:** Not started

Add `series-push` command to push all staged operations across all patches in a series:
```bash
gerrit-comments series-push <series-url>
```

Should show progress:
```
Patch 1/5 (62640): Pushed 3 operations ✓
Patch 2/5 (62641): Pushed 1 operation ✓
Patch 3/5 (62642): No staged operations (skipped)
Patch 4/5 (62643): Pushed 2 operations ✓
Patch 5/5 (62644): No staged operations (skipped)

Total: Pushed 6 operations across 3 patches
```

Implementation notes:
- Iterate through series from `series` command
- For each patch, call `push_staged()`
- Show real-time progress
- Handle errors gracefully (continue to next patch or abort?)
- Option for `--dry-run` to preview all operations

---

#### 2. Series Status Overview
**Status:** ✓ Completed

Add `series-status` command for dashboard view:
```bash
gerrit-comments series-status <series-url>
```

Output:
```
Series Status: https://review.whamcloud.com/62640

┌─────────┬──────────────────────┬────────────┬──────────┬─────────┐
│ Change  │ Subject              │ Unresolved │ Staged   │ Status  │
├─────────┼──────────────────────┼────────────┼──────────┼─────────┤
│ 62640   │ LU-17501 llite: add  │ 3          │ 2        │ ⚠ Needs │
│ 62641   │ LU-17501 osc: impl   │ 1          │ 1        │ ✓ Ready │
│ 62642   │ LU-17501 mdc: add    │ 0          │ 0        │ ✓ Clean │
│ 62643   │ LU-17501 tests: add  │ 5          │ 0        │ ✗ Todo  │
│ 62644   │ LU-17501 docs: upd   │ 0          │ 0        │ ✓ Clean │
└─────────┴──────────────────────┴────────────┴──────────┴─────────┘

Summary:
  Total patches: 5
  Patches with unresolved comments: 2
  Patches with staged operations: 2
  Patches ready to push: 1
```

Legend:
- ✓ Ready: Has staged operations, no new unresolved comments
- ✓ Clean: No unresolved comments, no staged operations
- ⚠ Needs: Has both unresolved and staged (partially addressed)
- ✗ Todo: Has unresolved comments, no staged operations

**Implementation:**
- Created `series_status.py` module with `SeriesStatus` class
- Added `PatchStatus` dataclass to represent per-patch status
- Implements status calculation logic based on unresolved/staged counts
- Supports both text (ASCII table) and JSON output formats
- Added `series-status` CLI command with `--json` flag
- Comprehensive test coverage: 19 tests in `test_series_status.py`
- Documentation added to SKILLS.md

---

#### 3. Better series-comments Integration
**Status:** Not started

**Problem:** Thread indices from `series-comments` don't work with `stage` command because indices are per-patch.

**Option A: Patch-aware thread indices**

Modify `series-comments` output to include change number prefix:
```
[62640:0] lustre/llite/file.c:150 (Marc Vef)
[62640:1] lustre/obdclass/obd_config.c:89 (Marc Vef)
[62641:0] lustre/mdc/mdc_request.c:45 (Marc Vef)
```

Add `series-stage` command that accepts these combined indices:
```bash
gerrit-comments series-stage <series-url> 62640:0 "Fixed"
gerrit-comments series-stage <series-url> 62641:0 --done
```

**Option B: Export/import workflow**

```bash
# Export series comments to editable JSON
gerrit-comments series-export <series-url> responses.json

# Edit responses.json to add your replies
# File format:
# {
#   "62640": [
#     {"thread_index": 0, "message": "Fixed", "resolve": true},
#     {"thread_index": 1, "message": "Good point", "resolve": true}
#   ],
#   "62641": [
#     {"thread_index": 0, "message": "Done", "resolve": true}
#   ]
# }

# Import responses and stage them
gerrit-comments series-import responses.json

# Push everything
gerrit-comments series-push <series-url>
```

---

### Medium Priority (Quality of Life)

#### 4. Template Responses
**Status:** Not started

Common responses library:
```bash
# Manage templates
gerrit-comments template add "done" "Done, thanks for the review"
gerrit-comments template add "wip" "Will address in follow-up patch"
gerrit-comments template add "question" "Could you clarify what you mean?"
gerrit-comments template list
gerrit-comments template remove "done"

# Use in staging
gerrit-comments stage --template=done <url> <thread>
gerrit-comments series-stage --template=wip <series-url> 62640:1
```

Implementation:
- Store templates in `~/.gerrit-comments/templates.json`
- Simple key-value pairs
- Support variables: `{author}`, `{file}`, `{line}` for personalization

---

#### 5. Filtering in series-comments
**Status:** Not started

Add filtering options:
```bash
# Filter by author
gerrit-comments series-comments --author="Marc Vef" <url>

# Filter by file pattern (glob)
gerrit-comments series-comments --file="*/llite/*" <url>
gerrit-comments series-comments --file="*.c" <url>

# Only specific patches in series
gerrit-comments series-comments --patches=62640,62641 <url>

# Group by file instead of by patch
gerrit-comments series-comments --group-by=file <url>

# Combine filters
gerrit-comments series-comments --author="Marc Vef" --file="*/llite/*" <url>
```

Useful for large series where you want to focus on specific areas.

---

### Nice to Have

#### 6. Interactive Mode
**Status:** ✓ Completed

Terminal interface for working with series:
```bash
gerrit-comments interactive <url>
```

Implemented features:
- Sequential comment review (one at a time)
- Keyboard actions:
  - `d` - Mark as done
  - `r` - Reply with custom message
  - `a` - Acknowledge
  - `s` - Skip
  - `q` - Quit with summary
  - `p` - Push all staged immediately
- Progress indicator (N/M comments addressed)
- Full thread history displayed
- URLs included for changes and comments
- Summary at end with push option
- All operations staged during session

Implementation: Simple prompt-based interaction (no curses/TUI library needed)

Possible future enhancements:
- Arrow key navigation
- Rich TUI with `blessed` or `rich` library
- Preview mode before pushing
- Visual grouping by patch/file

---

#### 7. Integrated Rebasing Mode
**Status:** ✓ Completed

**Goal:** Bridge the gap between reviewing comments and fixing code by integrating git rebase directly into the workflow.

**Two modes:**

**A. Interactive UI Integration**

Add `[e]dit patch` action to interactive mode:
```bash
gerrit-comments interactive <url>

# When viewing a comment, user can press 'e' to edit that patch
# Tool will:
# 1. Find the patch's position in the series
# 2. Run: git rebase -i <base>~<position> (stop at that patch)
# 3. Drop user into editor/shell to fix the code
# 4. User runs: git add <files> && git commit --amend
# 5. User signals completion (or runs gerrit-comments finish-patch)
# 6. Tool continues rebase to tip
# 7. Returns to interactive comment review
```

**B. Agent-Oriented Mode**

Allow AI agents to work on patches:
```bash
# Start working on a specific patch
gerrit-comments work-on-patch <series-url> <change-number>

# This will:
# 1. Find patch position in series
# 2. Rebase to that patch (leave tree in rebase state)
# 3. Show all comments for that patch
# 4. Agent can now:
#    - Read/edit files
#    - Run git add/commit --amend
#    - Test changes
# 5. When done, agent runs:
gerrit-comments finish-patch

# This will:
# 1. Continue rebase to series tip
# 2. Report success/conflicts
```

**Design Decisions:**

1. **One-patch-at-a-time (CHOSEN):**
   - Edit one patch fully, rebase entire series on top of it, then move to next patch
   - Pro: Simpler, safer, each patch stays internally consistent
   - Pro: Easier to implement and reason about
   - Con: More rebases, but they should be fast
   - Alternative: Multi-patch editing in single rebase (more complex, save for later)

2. **Rebase flow:**
   ```
   Initial series: base -> P1 -> P2 -> P3 -> P4 -> HEAD

   Work on P2:
   1. git rebase -i to stop at P2
   2. Make changes, amend P2
   3. Continue rebase: P2' -> P3' -> P4' -> HEAD'
   4. Series now: base -> P1 -> P2' -> P3' -> P4' -> HEAD'
   ```

3. **Conflict handling:**
   - If rebase fails with conflicts, drop user to shell with clear instructions
   - Provide helper: `gerrit-comments status` to check current state
   - Provide abort: `gerrit-comments abort` to abort rebase and return to original state

4. **Series tracking:**
   - Need to track which patches have been worked on
   - Store state in `~/.gerrit-comments/rebase-session.json`
   - Include: current patch, original HEAD, series URL, patches completed

5. **Integration with staging:**
   - After fixing a patch, can immediately stage "Done" replies for that patch's comments
   - Option: `--auto-stage` to automatically stage "Done" for all comments in the patch

**Implementation notes:**
- Requires git repository to be in correct state (clean working tree, on series branch)
- Need to validate we're in a git repo: `git rev-parse --git-dir`
- Find series base: use parent of first patch
- Track patches by commit hash (not change number) since we're rebasing
- After rebase completes, may need to update Gerrit with new commit hashes

**Example workflow:**
```bash
# Review series and identify patches that need fixes
gerrit-comments series-status https://review.whamcloud.com/62640

# Start interactive mode with edit support
gerrit-comments interactive --allow-edit https://review.whamcloud.com/62640

# Or, for agent mode:
gerrit-comments work-on-patch https://review.whamcloud.com/62640 62641
# Agent makes changes...
gerrit-comments finish-patch
```

**Implementation:**
- Created `rebase.py` module with `RebaseManager` class
- Session tracking via `RebaseSession` dataclass stored in `~/.gerrit-comments/rebase-session.json`
- Commands implemented:
  - `work-on-patch <url> <change-number>` - Start working on a patch
  - `next-patch` - Move to the next patch in series
  - `finish-patch` - Complete the rebase
  - `abort` - Abort and return to original state (with `--keep-changes` option)
  - `status` - Check current session status
- Git integration: checks repo state, manages git checkout/rebase operations
- Shows all comments for the target patch when starting
- Clear agent instructions in SKILLS.md with detailed workflow examples
- Comprehensive tests: 52 tests in `test_rebase.py`

**Note:** Interactive UI integration (`[e]dit` action in interactive mode) is not yet implemented. Current implementation focuses on agent-oriented workflow which can be used standalone.

---

#### 8. Batch Mark-All-Done
**Status:** Not started

Quick acknowledge all unresolved comments:
```bash
# Stage "Done" for all unresolved comments
gerrit-comments series-done-all <url>

# With custom message
gerrit-comments series-done-all --message="Fixed in v2" <url>

# Preview
gerrit-comments series-done-all --dry-run <url>

# Then push
gerrit-comments series-push <url>
```

Warning: Should require confirmation or `--force` flag to prevent accidents.

---

#### 9. Dependency Visualization
**Status:** Not started

Show patch dependencies in series:
```bash
gerrit-comments series --show-deps <url>
```

Output:
```
Series dependency graph:

62640 "LU-17501 llite: add O_DIRECT" (base)
  ├─ 62641 "LU-17501 osc: implement" (child)
  │   └─ 62642 "LU-17501 mdc: add support" (child)
  └─ 62643 "LU-17501 tests: add tests" (child)
      └─ 62644 "LU-17501 docs: update" (child)
```

With comment status:
```
62640 "LU-17501 llite: add O_DIRECT" [3 unresolved, 2 staged]
  ├─ 62641 "LU-17501 osc: implement" [1 unresolved, 1 staged]
  │   └─ 62642 "LU-17501 mdc: add support" [✓ clean]
  └─ 62643 "LU-17501 tests: add tests" [5 unresolved]
```

Warn if trying to push child when parent has unresolved comments.

---

## LLM Output Improvements

This tool is designed primarily for LLM-assisted code review.
These improvements focus on making output more parseable and actionable.

### High Priority

#### 10. Structured Output Mode (`--llm`)
**Status:** Not started

Add a global flag that produces consistently structured output:
- Clear section delimiters (`### SECTION ###`)
- Explicit action prompts
- Machine-parseable status codes
- No progress indicators or animations

Example:
```bash
gerrit-comments review-series --llm <url>
```

Output:
```
### SERIES INFO ###
URL: https://review.whamcloud.com/62640
PATCHES: 5
TARGET: 62640 (position 1/5)

### UNRESOLVED COMMENTS ###
PATCH 62640: 3 unresolved
PATCH 62643: 2 unresolved

### SUGGESTED ACTIONS ###
1. Address 3 comments on patch 62640
2. Run: gerrit-comments work-on-patch <url> 62640
```

---

#### 11. Comment-Code Inline View
**Status:** Not started

Show comments interleaved with the code they reference:
```bash
gerrit-comments review --inline <url>
```

Output:
```
=== lustre/llite/file.c ===
    40: for (i = 0; i < n; i++) {
    41:     for (j = 0; j < n; j++) {
>>> 42:         process(data[i][j]);
        │
        └── COMMENT [reviewer@example.com] (unresolved):
            "This loop has O(n²) complexity. Consider hash lookup."

            ACTION: Reply with 'gerrit-comments stage 0 "message"'
    43:     }
    44: }
```

This is the format LLMs work best with - seeing the comment in context.

---

#### 12. Consolidated Context Command
**Status:** Not started

New command: `gerrit-comments context <url>`

Outputs everything an LLM needs in one block:
- Commit message
- All diffs with line numbers
- All comments at their locations
- Current staging status
- Clear action instructions

This avoids needing multiple commands to gather context.

---

#### 13. Response Generation Hints
**Status:** Not started

Categorize comments to help LLMs respond appropriately:
```
COMMENT TYPE: style-nit
SUGGESTED RESPONSE: "Fixed, thanks" or explain why not
---
COMMENT TYPE: bug-report
SUGGESTED RESPONSE: Describe the fix or explain why it's not a bug
---
COMMENT TYPE: question
SUGGESTED RESPONSE: Answer the question
```

---

### Medium Priority

#### 14. Clean Output Flags
**Status:** Not started

Add flags to reduce noise:
- `--no-progress`: Skip progress indicators
- `--no-emoji`: Use text instead of ✓ ✗
- `--no-color`: Strip ANSI codes

These help when output is being captured for LLM input.

---

#### 15. Session Context File
**Status:** Not started

Write `.gerrit-comments/context.md` with current session state:
```markdown
# Current Review Session

## Series
- URL: https://review.whamcloud.com/62640
- Patches: 5

## Current Patch
- Change: 62641
- Subject: LU-17501 osc: implement buffered I/O
- Unresolved: 2 comments
- Staged: 1 reply

## Git State
- Branch: review-62640
- Original branch: master
- Working tree: clean

## Next Steps
1. Address remaining 2 comments
2. Run: gerrit-comments finish-patch
```

LLM can read this file to understand current state.

---

#### 16. Batch Reply JSON Format
**Status:** Not started

Command to generate reply template:
```bash
gerrit-comments generate-replies <url> > replies.json
```

Output:
```json
{
  "62640": [
    {
      "thread_index": 0,
      "file": "file.c",
      "line": 42,
      "comment": "This loop has O(n² complexity",
      "type": "bug-report",
      "suggested_response": "",
      "resolve": false
    }
  ]
}
```

LLM fills in `suggested_response`, then:
```bash
gerrit-comments import-replies replies.json
gerrit-comments series-push <url>
```

---

### Low Priority

#### 17. Output Consistency Audit
**Status:** Not started

Review all print() calls for consistency:
- Use ✓/✗ OR text, not mixed
- Consistent error message format: "Error: {message}"
- Consistent section headers
- All commands support `--json`

---

#### 18. Error Recovery Suggestions
**Status:** Not started

When errors occur, show clear recovery steps:
```
ERROR: Cherry-pick conflict in lustre/llite/file.c

CONFLICT CONTEXT:
Lines 42-50 have conflicting changes.

RECOVERY OPTIONS:
1. Resolve manually:
   - Edit lustre/llite/file.c
   - Run: git add lustre/llite/file.c
   - Run: gerrit-comments continue-reintegration

2. Skip this patch:
   - Run: gerrit-comments skip-reintegration

3. Abort session:
   - Run: gerrit-comments abort
```

---

#### 19. Token Budget Mode
**Status:** Not started (deferred)

Add `--max-tokens N` to truncate output:
- Summarize long diffs
- Prioritize unresolved comments
- Include truncation notice

Useful for LLMs with limited context windows.

---

## Other Improvements

### Error Handling
**Status:** Ongoing

- Better error messages for network failures
- Retry logic for transient failures
- Clearer messages when credentials are wrong
- Handle rate limiting gracefully

### Performance
**Status:** Not started

- Cache change details to avoid repeated API calls
- Parallel fetching for series operations
- Progress indicators for long operations

### Testing
**Status:** ✓ Comprehensive

- ✓ 513 tests, 90% coverage
- ✓ Integration tests for CLI wiring
- ✓ Parser-handler contract tests
- ✓ Real git repository tests
- Add tests for different Gerrit versions

---

## Completed

- ✓ Basic staging workflow
- ✓ Single-patch push
- ✓ Series comment extraction
- ✓ Patchset validation fix
- ✓ Clean install script
- ✓ Comprehensive unit tests for staging
- ✓ Command consolidation (24 → 16 commands)
- ✓ CLI integration tests
- ✓ Session/reintegration extraction
- ✓ Architecture documentation
