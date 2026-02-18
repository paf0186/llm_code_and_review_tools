# JIRA Tool

A thin, LLM-agent-focused CLI wrapper around the JIRA REST API.

## Installation

```bash
# Using pip
pip install -e .

# Using uv (recommended)
uv pip install -e .
```

## Configuration

Set environment variables:

```bash
export JIRA_SERVER="https://jira.example.com"
export JIRA_TOKEN="your-api-token"
```

Or use command-line options: `--server` and `--token`

## Quick Start

```bash
# Get issue details
jira get PROJ-123

# Get issue with comments inline
jira get PROJ-123 --comments

# Search issues
jira search "project = PROJ AND status = Open"

# Read comments (with pagination)
jira comments PROJ-123 --limit 5

# List attachments
jira attachments PROJ-123

# Check available transitions
jira transitions PROJ-123

# Add a comment
jira comment PROJ-123 "My comment text"

# Create an issue
jira create --project PROJ --type Bug --summary "Bug title"
```

## Output Format

All commands return JSON with a consistent envelope:

```json
{
  "ok": true,
  "data": { ... },
  "meta": {
    "tool": "jira",
    "command": "get",
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

Use `--pretty` for human-readable formatted output. It works in any position:
`jira --pretty get KEY` or `jira get KEY --pretty`.

## Commands

### Issue Operations

| Command | Description |
|---------|-------------|
| `jira get <key>` | Get issue details (add `--comments` to inline comments) |
| `jira comments <key>` | Get comments with pagination |
| `jira attachments <key>` | List attachments |
| `jira search <jql>` | Search with JQL |
| `jira create` | Create a new issue |
| `jira comment <key> <body>` | Add a comment |
| `jira transitions <key>` | List available transitions |
| `jira transition <key> <id>` | Transition to new state |

### Attachment Operations

| Command | Description |
|---------|-------------|
| `jira attachment get <id>` | Get attachment metadata |
| `jira attachment content <id>` | Download content (with size limits) |

### Config Operations

| Command | Description |
|---------|-------------|
| `jira config test` | Test connectivity |
| `jira config show` | Show configuration (redacted) |

## LLM Context Awareness

Built-in protections for LLM context windows:

- **Comments**: Default limit of 5, use `--limit N` for more
- **Attachments**: Default 100KB limit, use `--max-size N` to override
- **Search**: Default 20 results, use `--limit N` for more

## Documentation

- [Architecture](ARCHITECTURE.md) - Design principles and output format specification
- [Skills](SKILLS.md) - Detailed usage guide for LLM agents

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Lint
ruff check jira_tool/ tests/
```

## License

MIT
