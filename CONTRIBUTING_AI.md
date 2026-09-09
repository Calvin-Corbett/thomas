# Contributing

Thomas welcomes focused bug reports, fixes, documentation improvements, and tests.

## Before changing code

1. Read [AGENTS.md](AGENTS.md), [GUARDRAILS.md](GUARDRAILS.md), and the relevant module instructions.
2. Reproduce the behavior and identify the live entry point.
3. Check for existing implementations before adding a new component.
4. Keep the change scoped and preserve unrelated work.

## Validation

Install development dependencies with `python -m pip install -e ".[server,repl,test]"`. Run focused tests for the behavior you change, lint modified Python files with `ruff check`, and perform relevant runtime checks.

Use the project's guarded commit workflow. Do not bypass checks, weaken tests, or change authorization controls to make a change pass.

## Public content

Use fictional names, organizations, and paths in test fixtures. Do not include credentials, personal conversations, screenshots of private sessions, populated coordination records, or raw local test logs. Describe product behavior in release notes and pull requests.

Keep accurate limitations and reproducible bug descriptions. Do not claim a feature works based only on a static inspection.
