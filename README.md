# LLM Code and Review Tools

CLI tools designed for LLM agents to interact with code review and issue tracking systems.

## Tools

| Tool | Purpose | Directory |
|------|---------|-----------|
| **jira** | JIRA issue tracking | [jira_tool/](jira_tool/) |
| **gerrit-cli** | Gerrit code review comments | [gerrit_cli/](gerrit_cli/) |
| **jenkins** | Jenkins build server | [jenkins_tool/](jenkins_tool/) |
| **maloo** | Lustre CI test results | [maloo_tool/](maloo_tool/) |

## Design Philosophy

These tools share common design principles:

- **Structured JSON output** with consistent envelope format (`ok`, `data`/`error`, `meta`) — use `--pretty` for formatted output
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

### Gerrit CLI Tool

```bash
# Install
cd gerrit_cli && pip install -e .

# Configure
export GERRIT_URL="https://review.example.com"
export GERRIT_USER="your-username"
export GERRIT_PASS="your-http-password"

# Use
gerrit-cli extract https://review.example.com/c/project/+/12345
gerrit-cli review https://review.example.com/c/project/+/12345
gerrit-cli series https://review.example.com/c/project/+/12345
```

### Jenkins Tool

```bash
# Install
cd jenkins_tool && pip install -e .

# Configure
export JENKINS_URL="https://build.whamcloud.com"
export JENKINS_USER="your-username"
export JENKINS_TOKEN="your-api-token"

# Use
jenkins builds lustre-reviews --limit 10
jenkins build lustre-reviews 121881
jenkins console lustre-master lastFailedBuild --grep "error"
```

## Documentation

- **[AGENTS.md](AGENTS.md)** - Combined guide for AI agents (recommended starting point)

Per-tool documentation:

- **JIRA Tool**: [README](jira_tool/README.md) | [Architecture](jira_tool/ARCHITECTURE.md) | [Skills](jira_tool/SKILLS.md)
- **Gerrit CLI**: [README](gerrit_cli/README.md) | [Architecture](gerrit_cli/ARCHITECTURE.md) | [Skills](gerrit_cli/SKILLS.md)
- **Jenkins Tool**: [README](jenkins_tool/README.md)
- **Maloo Tool**: [README](maloo_tool/README.md)

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
