# JIRA Tool Architecture

## Overview

This tool provides a thin, LLM-agent-focused CLI wrapper around the JIRA REST API. It is designed for deterministic behavior, strict JSON output, and stable command semantics.

## Design Principles

1. **JSON-only Interface**: All output is structured JSON. Human-readable formatting is available via `--pretty` flag.
2. **Explicit Inputs**: No implicit defaults. Required fields must be provided explicitly. Fail fast with clear error codes.
3. **Deterministic Behavior**: Same input produces same output shape. No silent field truncation.
4. **Thin Command Surface**: Minimal commands covering core agent workflows.
5. **LLM Context Awareness**: Comments and large fields support pagination to avoid overwhelming LLM context windows.

## Standard Response Envelope

### Success Response
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

### Error Response
```json
{
  "ok": false,
  "error": {
    "code": "AUTH_FAILED",
    "message": "Authentication failed",
    "http_status": 401,
    "details": {}
  },
  "meta": {
    "tool": "jira",
    "command": "issue.get",
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

## Exit Codes

- `0`: Success
- `1`: General error
- `2`: Authentication error
- `3`: Not found
- `4`: Invalid input
- `5`: Network/connection error

## Commands

### Issue Operations

| Command | Description |
|---------|-------------|
| `jira issue get <key>` | Get issue details (summary, description, status, etc.) |
| `jira issue comments <key>` | Get comments with pagination support |
| `jira issue search <jql>` | Search issues using JQL |
| `jira issue create` | Create a new issue |
| `jira issue comment <key>` | Add a comment to an issue |
| `jira issue transition <key>` | Transition issue to a new state |

### Comments Pagination Strategy

To manage LLM context limits, comments are fetched with awareness of size:

- Default: Returns summary (count, date range) + last N comments (configurable, default 5)
- `--limit N`: Fetch N comments
- `--offset N`: Skip first N comments
- `--all`: Fetch all comments (use with caution)

## Configuration

### Config File Location
`~/.jira-tool.json`

### Config File Format
```json
{
  "server": "https://jira.example.com",
  "auth": {
    "type": "token",
    "token": "your-api-token"
  }
}
```

### Environment Variable Overrides
- `JIRA_SERVER`: Override server URL
- `JIRA_TOKEN`: Override API token

Environment variables take precedence over config file values.

## Module Structure

```
jira_tool/
├── jira_tool/
│   ├── __init__.py
│   ├── cli.py           # CLI entry point using Click
│   ├── client.py        # JIRA REST API client
│   ├── config.py        # Configuration loading
│   ├── envelope.py      # Response envelope helpers
│   ├── errors.py        # Error codes and exceptions
│   └── models.py        # Data models for issues, comments
├── tests/
│   ├── unit/            # Unit tests (mocked HTTP)
│   └── integration/     # Integration tests (live API, read-only)
├── pyproject.toml
└── ARCHITECTURE.md
```

## JIRA REST API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/rest/api/2/issue/{key}` | GET | Get issue |
| `/rest/api/2/issue/{key}/comment` | GET | Get comments |
| `/rest/api/2/issue/{key}/comment` | POST | Add comment |
| `/rest/api/2/issue/{key}/transitions` | GET | Get available transitions |
| `/rest/api/2/issue/{key}/transitions` | POST | Perform transition |
| `/rest/api/2/search` | POST | Search with JQL |
| `/rest/api/2/issue` | POST | Create issue |

## Security Considerations

- Tokens are never logged or included in error output
- `--debug` mode redacts authorization headers
- Config file should have restricted permissions (0600)

## Future Considerations

- Shared conventions with Gerrit tool (same envelope, error model, exit codes)
- Optional `--human` flag for human-readable output
- Webhook support for real-time updates
