# Gerrit CLI Agent Skill

Extract and reply to Gerrit code review comments with code context. Designed for use as an agent skill for Claude or other AI assistants.

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Or using pip
pip install -e .
```

## Agent Skill Description

**Gerrit CLI Tool** - Extract unresolved comments from Gerrit code reviews and reply to them. Supports extracting comment threads with surrounding code context, replying to comments with custom messages, and marking comments as "Done" or "Acknowledged" to resolve threads.

### Capabilities

1. **Extract Comments**: Get all unresolved review comments from a Gerrit change URL
   - Returns structured data with comment threads, authors, patch sets, and line numbers
   - Includes surrounding code context for each comment
   - Outputs JSON for easy programmatic use

2. **Reply to Comments**: Post replies to comment threads
   - Reply with custom message
   - Mark as "Done" to resolve the thread
   - Mark as "Acknowledged" to resolve without changes
   - Batch reply to multiple comments

3. **Code Review**: Review code changes and post review comments
   - Fetch diffs and file changes from a Gerrit change
   - View changed files with full diff context
   - Post review comments on specific lines
   - Set Code-Review vote (+1, -1, +2, -2)

4. **Find Patch Series**: Find all patches in a linear series
   - Given any patch URL, finds the complete series from base to tip
   - Traces parent commits to build the linear chain
   - Returns structured data with change numbers, subjects, and URLs
   - Note: Follows one linear path only; branches are not included

5. **Series Comments**: Get all unresolved comments from an entire patch series
   - Collects comments across all patches in a series
   - Groups comments by patch with metadata (change number, subject, patchset)
   - Includes author information and code context
   - Useful for reviewing feedback on a multi-patch series at once

## CLI Usage

### Extract Comments

```bash
# Extract unresolved comments with code context
gc extract https://review.whamcloud.com/c/fs/lustre-release/+/62796

# Output as JSON
gc extract --json https://review.whamcloud.com/c/fs/lustre-release/+/62796

# Include resolved comments too
gc extract --all https://review.whamcloud.com/c/fs/lustre-release/+/62796
```

### Reply to Comments

```bash
# Reply to thread 0 with a message
gc reply https://review.whamcloud.com/c/fs/lustre-release/+/62796 0 "Fixed in next patchset"

# Mark thread 0 as done
gc reply --done https://review.whamcloud.com/c/fs/lustre-release/+/62796 0

# Acknowledge thread 1
gc reply --ack https://review.whamcloud.com/c/fs/lustre-release/+/62796 1

# Reply and resolve
gc reply --resolve https://review.whamcloud.com/c/fs/lustre-release/+/62796 0 "Implemented as suggested"
```

### Batch Reply

Create a JSON file with replies:

```json
[
  {"thread_index": 0, "message": "Done", "mark_resolved": true},
  {"thread_index": 1, "message": "Will address in follow-up", "mark_resolved": false}
]
```

Then run:

```bash
gc batch https://review.whamcloud.com/c/fs/lustre-release/+/62796 replies.json
```

### Code Review

```bash
# Get code changes for review (human-readable format)
gc review https://review.whamcloud.com/c/fs/lustre-release/+/62796

# Get code changes as JSON (for programmatic use)
gc review --json https://review.whamcloud.com/c/fs/lustre-release/+/62796

# Show only added/deleted lines (not full diff context)
gc review --changes-only https://review.whamcloud.com/c/fs/lustre-release/+/62796

# Post a code review with comments from JSON file
gc review --post-comments review.json https://review.whamcloud.com/c/fs/lustre-release/+/62796
```

Review JSON file format:
```json
{
  "message": "Some suggestions for improvement",
  "vote": -1,
  "comments": [
    {"path": "file.c", "line": 42, "message": "Consider using const here"},
    {"path": "file.c", "line": 100, "message": "Missing error handling"}
  ]
}
```

### Find Patch Series

```bash
# Find all patches in a series (given any patch in the series)
gc series https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Output as JSON
gc series --json https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Output only URLs (one per line, useful for scripting)
gc series --urls-only https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Output only change numbers (one per line)
gc series --numbers-only https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Include abandoned patches in the series
gc series --include-abandoned https://review.whamcloud.com/c/fs/lustre-release/+/61965
```

### Series Comments

```bash
# Get all unresolved comments from all patches in a series
gc series-comments https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Output as JSON
gc series-comments --json https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Include resolved comments too
gc series-comments --all https://review.whamcloud.com/c/fs/lustre-release/+/61965

# Exclude code context (faster)
gc series-comments --no-context https://review.whamcloud.com/c/fs/lustre-release/+/61965
```

## Python API

### Extract Comments

```python
from gerrit_cli import extract_comments

# Extract unresolved comments
result = extract_comments(
    "https://review.whamcloud.com/c/fs/lustre-release/+/62796",
    include_resolved=False,  # Only unresolved
    include_code_context=True,  # Include surrounding code
    context_lines=3,  # Lines of context above/below
)

# Print summary
print(result.format_summary())

# Access structured data
print(f"Found {result.unresolved_count} unresolved threads")
for thread in result.threads:
    print(f"File: {thread.root_comment.file_path}")
    print(f"Line: {thread.root_comment.line}")
    print(f"Author: {thread.root_comment.author.name}")
    print(f"Message: {thread.root_comment.message}")

    # Code context
    if thread.root_comment.code_context:
        print("Context:")
        print(thread.root_comment.code_context.format())

# Export as JSON
import json
print(json.dumps(result.to_dict(), indent=2))
```

### Reply to Comments

```python
from gerrit_cli import CommentReplier, extract_comments

# Extract first
result = extract_comments("https://review.whamcloud.com/c/fs/lustre-release/+/62796")

# Reply to a thread
replier = CommentReplier()
reply_result = replier.reply_to_thread(
    change_number=62796,
    thread=result.threads[0],
    message="Fixed in patchset 5",
    mark_resolved=True,  # Mark as done
)

if reply_result.success:
    print("Reply posted!")
else:
    print(f"Error: {reply_result.error}")
```

### Mark as Done

```python
from gerrit_cli import CommentReplier, extract_comments

result = extract_comments("https://review.whamcloud.com/c/fs/lustre-release/+/62796")

replier = CommentReplier()
done_result = replier.mark_thread_done(
    change_number=62796,
    thread=result.threads[0],
    message="Done",  # Optional custom message
)
```

### Batch Reply

```python
from gerrit_cli import CommentReplier, extract_comments

result = extract_comments("https://review.whamcloud.com/c/fs/lustre-release/+/62796")

replier = CommentReplier()
results = replier.batch_reply(
    change_number=62796,
    replies=[
        {"comment": result.threads[0].root_comment, "message": "Done", "mark_resolved": True},
        {"comment": result.threads[1].root_comment, "message": "Will fix", "mark_resolved": False},
    ],
)

for r in results:
    print(f"Comment {r.comment_id}: {'✓' if r.success else '✗'}")
```

### Code Review

```python
from gerrit_cli import CodeReviewer, get_review_data, post_review

# Get review data for a change
review_data = get_review_data("https://review.whamcloud.com/c/fs/lustre-release/+/62796")

# Print formatted review information
print(review_data.format_for_review())

# Access structured data
print(f"Project: {review_data.change_info.project}")
print(f"Subject: {review_data.change_info.subject}")
print(f"Files changed: {len(review_data.files)}")

for file in review_data.files:
    print(f"  {file.path}: +{file.lines_added}/-{file.lines_deleted}")

    # Access individual hunks and lines
    for hunk in file.hunks:
        for line in hunk.lines:
            if line.type == "added":
                print(f"    +{line.line_number_new}: {line.content}")
            elif line.type == "deleted":
                print(f"    -{line.line_number_old}: {line.content}")

# Post a code review with comments
reviewer = CodeReviewer()
result = reviewer.post_review(
    change_number=62796,
    comments=[
        {"path": "lustre/utils/file.c", "line": 42, "message": "Consider using const here"},
        {"path": "lustre/utils/file.c", "line": 100, "message": "Missing error handling"},
    ],
    message="Some suggestions for improvement.",
    vote=-1,  # Code-Review vote: -2, -1, 0, +1, +2
)

if result.success:
    print(f"Posted {result.comments_posted} comments")
else:
    print(f"Error: {result.error}")

# Post a single inline comment
result = reviewer.post_comment(
    change_number=62796,
    path="lustre/utils/file.c",
    line=42,
    message="Consider using const here",
)
```

### Find Patch Series

```python
from gerrit_cli import find_series, SeriesFinder

# Find all patches in a series (given any patch URL)
series = find_series("https://review.whamcloud.com/c/fs/lustre-release/+/61965")

# Print summary
print(series.format_summary())

# Access structured data
print(f"Total patches: {len(series)}")
print(f"Target change {series.target_change} is at position {series.target_position}")
print(f"Base: {series.base_change}, Tip: {series.tip_change}")

# Iterate through patches (ordered base to tip)
for patch in series.patches:
    print(f"{patch.change_number}: {patch.subject}")
    print(f"  URL: {patch.url}")
    print(f"  Commit: {patch.commit} -> Parent: {patch.parent_commit}")

# Get just the change numbers or URLs
change_numbers = series.get_change_numbers()  # [62217, 62791, ...]
urls = series.get_urls()  # ["https://...", ...]

# Export as JSON
import json
print(json.dumps(series.to_dict(), indent=2))

# Use SeriesFinder directly for more control
finder = SeriesFinder()
series = finder.find_series_by_change(61965, include_abandoned=True)
```

### Series Comments

```python
from gerrit_cli import get_series_comments, SeriesFinder

# Get all unresolved comments from all patches in a series
result = get_series_comments(
    "https://review.whamcloud.com/c/fs/lustre-release/+/61965",
    include_resolved=False,  # Only unresolved
    include_code_context=True,  # Include surrounding code
    context_lines=3,  # Lines of context above/below
)

# Print summary
print(result.format_summary())
# Output: SERIES COMMENTS (130 unresolved across 17 patches)

# Access structured data
print(f"Total unresolved: {result.total_unresolved}")
print(f"Patches with comments: {result.patches_with_unresolved}")

# Iterate through patches with comments
for patch_comments in result.patches_with_comments:
    print(f"Change {patch_comments.change_number}: {patch_comments.subject}")
    print(f"  URL: {patch_comments.url}")
    print(f"  Patchset: {patch_comments.current_patchset}")
    print(f"  Unresolved: {patch_comments.unresolved_count}")

    for thread in patch_comments.threads:
        comment = thread.root_comment
        print(f"    {comment.file_path}:{comment.line or 'patchset'}")
        print(f"    Author: {comment.author.name}")
        print(f"    Message: {comment.message[:50]}...")
        if comment.code_context:
            print(f"    Context:\n{comment.code_context.format()}")

# Export as JSON
import json
print(json.dumps(result.to_dict(), indent=2))

# Use SeriesFinder directly for more control
finder = SeriesFinder()
result = finder.get_series_comments(
    url="https://review.whamcloud.com/c/fs/lustre-release/+/61965",
    include_resolved=True,
    include_code_context=False,
)
```

## Configuration

The tool uses credentials from environment variables or built-in defaults:

```bash
export GERRIT_URL="https://review.whamcloud.com"
export GERRIT_USER="your-username"
export GERRIT_PASS="your-http-password"
```

Or pass directly:

```python
from gerrit_cli import GerritCommentsClient, CommentExtractor

client = GerritCommentsClient(
    url="https://your-gerrit.com",
    username="user",
    password="http-password",
)
extractor = CommentExtractor(client=client)
```

## Data Models

### ExtractedComments
- `change_info`: Info about the change (project, branch, subject, etc.)
- `threads`: List of CommentThread objects
- `unresolved_count`: Number of unresolved threads
- `total_count`: Total comment count

### CommentThread
- `root_comment`: The original comment
- `replies`: List of reply comments
- `is_resolved`: Whether the thread is resolved

### Comment
- `id`: Unique comment ID
- `patch_set`: Patch set number
- `file_path`: Path to the file
- `line`: Line number (None for patchset-level)
- `message`: Comment text
- `author`: Author info (name, email)
- `unresolved`: Whether comment is unresolved
- `code_context`: Optional CodeContext with surrounding lines

### ReviewData
- `change_info`: Info about the change
- `files`: List of FileChange objects
- `commit_message`: Full commit message
- `parent_commit`: Parent commit SHA

### FileChange
- `path`: File path
- `status`: Change status (A=added, M=modified, D=deleted, R=renamed)
- `old_path`: Original path (for renames)
- `lines_added`: Number of lines added
- `lines_deleted`: Number of lines deleted
- `hunks`: List of DiffHunk objects with line-by-line changes

### PatchSeries
- `patches`: List of PatchInfo objects (ordered base to tip)
- `target_change`: The change number that was queried
- `target_position`: Position of target in series (1-indexed)
- `tip_change`: Change number at the tip of the series
- `base_change`: Change number at the base of the series

### PatchInfo
- `change_number`: Gerrit change number
- `subject`: Commit subject line
- `commit`: Short commit SHA
- `parent_commit`: Short parent commit SHA
- `status`: Change status (NEW, ABANDONED, etc.)
- `url`: URL to the change

### SeriesComments
- `series`: The PatchSeries object
- `patches_with_comments`: List of PatchComments objects (only patches with comments)
- `total_unresolved`: Total unresolved comments across all patches
- `patches_with_unresolved`: Number of patches that have unresolved comments

### PatchComments
- `change_number`: Gerrit change number
- `subject`: Commit subject line
- `url`: URL to the change
- `current_patchset`: Current patchset number
- `threads`: List of CommentThread objects
- `unresolved_count`: Number of unresolved threads in this patch

## Running Tests

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run unit tests
pytest gerrit_cli/tests/ -v --ignore=gerrit_cli/tests/test_integration.py

# Run integration tests (requires network)
pytest gerrit_cli/tests/test_integration.py -v

# Run all tests
pytest gerrit_cli/tests/ -v
```

## License

MIT
