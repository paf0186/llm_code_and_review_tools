# TODO

## 1. Structured JSON output in lctl/lfs

Add `--json` flags to `lctl get_param`, `lfs getstripe`, etc. in
Lustre itself. Parsing text output is fragile for agents. This is
a Lustre feature patch, not a tools repo change — tracked here for
reference.

## 2. Test runner tool

Wrapper around `sanity.sh`, `sanity-ec.sh`, etc. that:
- Captures pass/fail/skip results as structured JSON
- Handles common env var setup (OSTCOUNT, ONLY, etc.)
- Manages the mount/unmount cycle
- Collects log paths from auster

## 3. Cross-tool workflow automation

Chain common multi-tool operations:
- Gerrit comments → find related JIRA bugs → check Maloo → retest
- Automate the patch shepherding loop currently done manually
- `gerrit watch` is a start but doesn't auto-retest or auto-link

## 4. Retry/backoff logic

None of the tools retry on transient failures. Add to
`llm_tool_common`:
- Exponential backoff with jitter
- Configurable retry count
- Transient error detection (timeouts, 502/503)

## 5. gerrit series-push

Push staged replies across all patches in a series at once:
```bash
gc series-push <series-url>
```
Currently requires pushing each patch individually.
