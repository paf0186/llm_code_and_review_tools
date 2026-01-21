# AI Agent Guidelines

This document provides guidance for AI agents working on this codebase.

## Architecture

See [architecture.md](architecture.md) for a detailed explanation of the code
structure, module responsibilities, and data flow.

## Testing Requirements

**All new functionality must include tests.**

### Running Tests

```bash
# Run all tests
pytest gerrit_comments/tests/

# Run with coverage
pytest gerrit_comments/tests/ --cov=gerrit_comments --cov-report=term-missing

# Run specific test file
pytest gerrit_comments/tests/test_rebase.py -v
```

### Coverage Requirements

- Check coverage after making changes
- New modules should have corresponding test files
- Aim to maintain or improve overall coverage (currently 84%)

### Test File Naming

Each module `gerrit_comments/foo.py` should have a corresponding test file
`gerrit_comments/tests/test_foo.py`.

## Code Style

- Follow existing patterns in the codebase
- Use dataclasses for data structures
- Use type hints
- Keep functions focused and under ~60 lines
- Extract complex logic to separate modules when appropriate

## Making Changes

1. Understand the layer the change affects (CLI, Workflow, Core, Utility)
2. Write or update tests first when possible
3. Run the full test suite before committing
4. Check coverage to ensure new code is tested

