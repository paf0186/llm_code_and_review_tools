# LLM Code and Review Tools

CLI tools designed for LLM agents to interact with code review and issue tracking systems.

## Tools

| Tool | Purpose | Directory |
|------|---------|-----------|
| **jira** | JIRA issue tracking | [jira_tool/](jira_tool/) |
| **gerrit-comments** | Gerrit code review comments | [gerrit_comments/](gerrit_comments/) |

## Design Philosophy

These tools share common design principles optimized for LLM agent consumption:

- **Structured JSON output** with consistent envelope format (`ok`, `data`/`error`, `meta`)
- **Deterministic behavior** - same input produces same output shape
- **Context-aware pagination** - built-in limits to avoid overwhelming LLM context windows
- **Explicit inputs** - no implicit defaults, fail fast with clear error codes

## Quick Start

### JIRA Tool

```bash
# Install
cd jira_tool && pip install -e .

# Configure
export JIRA_SERVER="https://jira.example.com"
export JIRA_TOKEN="your-api-token"

# Use
jira issue get PROJ-123
jira issue search "project = PROJ AND status = Open"
jira issue comments PROJ-123 --limit 5
```

### Gerrit Comments Tool

```bash
# Install
cd gerrit_comments && pip install -e .

# Configure
export GERRIT_URL="https://review.example.com"
export GERRIT_USER="your-username"
export GERRIT_PASS="your-http-password"

# Use
gerrit-comments extract https://review.example.com/c/project/+/12345
gerrit-comments review https://review.example.com/c/project/+/12345
gerrit-comments series https://review.example.com/c/project/+/12345
```

## Documentation

- **[AGENTS.md](AGENTS.md)** - Combined guide for AI agents (recommended starting point)

Per-tool documentation:

- **JIRA Tool**: [README](jira_tool/README.md) | [Architecture](jira_tool/ARCHITECTURE.md) | [Skills](jira_tool/SKILLS.md)
- **Gerrit Comments**: [README](gerrit_comments/README.md) | [Architecture](gerrit_comments/ARCHITECTURE.md) | [Skills](gerrit_comments/SKILLS.md)

## Output Format

All tools use a standard JSON response envelope:

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

On error:

```json
{
  "ok": false,
  "error": {
    "code": "AUTH_FAILED",
    "message": "Authentication failed",
    "http_status": 401
  },
  "meta": { ... }
}
```

## License

MIT
