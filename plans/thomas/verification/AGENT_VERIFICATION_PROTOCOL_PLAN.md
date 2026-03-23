# Agent Verification Protocol — Plan to Close All 10 Remaining Gaps

**Date:** 2026-03-19
**Status:** Plan (not yet implemented)
**Principle:** The agent is intelligent. Make it prove its work is correct, not just structurally valid.

---

## The Core Idea

The current system has 35 pre-commit hooks that check the **shape** of code (syntax, file size, naming, imports). What's missing is verification of **correctness** — does the code actually work? Does it do what it claims? Did it break anything?

The fix is a **Verification Protocol**: before an agent can commit, it must produce a **verification record** — a JSON file proving it tested its work, reviewed its changes, and checked for regressions. A pre-commit hook checks for this record and blocks the commit if it's missing or incomplete.

The agent creates the record by running a structured verification sequence:
1. Write the code
2. Write tests for the code
3. Run the tests and capture output
4. Run a self-review (using a different prompt/perspective)
5. Check for regressions (run existing tests)
6. Summarize what changed and why
7. Write the verification record with all evidence
8. Commit (hooks verify the record exists and is valid)

---

## Gap-by-Gap Solutions

### Gap 1: Bad Logic (No correctness verification)
**Current state:** Agent writes code that's syntactically valid but logically wrong.
**Fix:** Require a verification record that includes test results.

**Mechanism:**
- Agent must create `tests/test_<module>_<feature>.py` alongside any new feature
- Agent must RUN the tests and capture the output
- Verification record must include: test file path, pass/fail count, test output hash
- Pre-commit hook: `check_verification_record_gate.py` — blocks commit if record is missing or shows failures

**Why this works:** The agent can't just SAY it tested — the record includes the actual pytest output. If the tests fail, the record shows it. If there are no tests, there's no record.

### Gap 2: Silent Code Deletion (Agent guts files)
**Current state:** Agent can delete 400 lines from a 500-line file without detection.
**Fix:** `check_shrinkage_gate.py` — flag files that shrink by more than 30% in one commit.

**Mechanism:**
- Pre-commit hook compares staged file line count vs HEAD
- If any file shrank by >30%, require the verification record to include an explicit `deletions_justified` field explaining what was removed and why
- If the field is missing or empty, block the commit

**Why this works:** Forces the agent to acknowledge and explain significant code removal. The human can review the justification in the verification record.

### Gap 3: No Test Requirement
**Current state:** Agent can add features with zero tests.
**Fix:** `check_test_coverage_gate.py` — require test file changes when source files change.

**Mechanism:**
- If 3+ files under `thomas/` are staged, at least one file under `tests/` must also be staged
- Exceptions: docs-only changes, config changes, CHANGELOG-only
- The verification record must include a `tests_run` field with the pytest command and output

**Why this works:** Same threshold pattern as the changelog gate. Forces test-alongside-code discipline.

### Gap 4: Frontend Code Barely Covered
**Current state:** Python hooks don't apply to JS/TS/React code.
**Fix:** Add ESLint + TypeScript checks to the pre-commit pipeline for `apps/`.

**Mechanism:**
- Add `check_frontend_lint_gate.py` that runs ESLint on staged `.ts`/`.tsx` files
- Add TypeScript type checking via `tsc --noEmit` on staged frontend files
- Only triggers when `apps/` files are staged

**Why this works:** Same pattern as the Python hooks, but for the frontend stack.

### Gap 5: Agent Can Add Dependencies Freely
**Current state:** No check on dependency additions.
**Fix:** `check_dependency_gate.py` — flag new imports and dependency changes.

**Mechanism:**
- If `pyproject.toml`, `requirements-lock.txt`, or `package.json` are staged, the verification record must include a `dependencies_reviewed` field
- For new Python imports: check if the package exists on PyPI (basic sanity)
- Flag any dependency that wasn't previously in the lock file

**Why this works:** The agent must explicitly acknowledge new dependencies. The human can review them.

### Gap 6: Misleading Documentation
**Current state:** Comments and docstrings can say the opposite of what code does.
**Fix:** Include in the agent self-review step.

**Mechanism:**
- The verification protocol includes a "self-review" step where the agent re-reads its own code with a different prompt: "Review this code for accuracy of comments and docstrings. Do the comments match what the code actually does?"
- The review output is included in the verification record
- No hard gate (too many false positives), but the review is visible to the human

**Why this works:** The agent is intelligent — when asked to specifically review comment accuracy, it catches mismatches. The review artifact gives the human a focused place to look.

### Gap 7: Enormous Commits
**Current state:** No limit on commit size.
**Fix:** `check_commit_scope_gate.py` — warn/block when too many files are staged.

**Mechanism:**
- If >20 files are staged in one commit, require the verification record to include a `scope_justification` field
- If >50 files, hard block — split the commit
- Exceptions: version bumps, bulk renames (detected via `git diff --name-status`)

**Why this works:** Forces agents to make focused commits. Large commits must be explicitly justified.

### Gap 8: Config Files Are Open
**Current state:** `thomas.toml`, `Dockerfile`, `.gitignore` are unprotected.
**Fix:** Add config files to the protected list in `agent_safety.toml`.

**Mechanism:**
- Add `thomas.toml`, `thomas.prod.toml`, `pyproject.toml`, `docker-compose.yml`, `Dockerfile`, `.gitignore` to `[protected].policy_files`
- Agent must ask the human before modifying these

**Why this works:** Same mechanism as GUARDRAILS.md protection. Simple, proven.

### Gap 9: Exception Ratchet False Positives
**Current state:** Line-number shifts cause false positives.
**Fix:** Use diff hunk analysis instead of raw line numbers.

**Mechanism:**
- Instead of comparing line numbers directly, use `git diff --cached -U0` to get the actual changed line ranges
- Only flag broad exception handlers that appear in ADDED lines (lines starting with `+`), not in unchanged context
- This eliminates false positives from code that was merely shifted, not changed

**Why this works:** Diff hunks tell you exactly which lines were added vs which existed before. An existing handler that moved doesn't appear as an added line.

### Gap 10: No Runtime Verification
**Current state:** Boot smoke only checks imports, not behavior.
**Fix:** Include test execution in the verification protocol.

**Mechanism:**
- The verification record must include `tests_passed` with the pytest output
- For server changes: the record should include boot verification output (`python -m thomas serve --port 0`)
- The pre-commit hook checks that the test suite was actually executed, not just that the record claims it was (by verifying the output hash matches a real pytest run)

**Why this works:** The agent runs the actual test suite and includes the output. Fake results would be caught by hash verification. The human can inspect the test output in the record.

---

## The Verification Record Format

```json
{
  "version": 1,
  "timestamp": "2026-03-19T12:00:00Z",
  "agent": "claude-opus-4-6",
  "task_summary": "Added memory cleanup scheduler",
  "files_changed": ["thomas/memory/scheduler.py", "tests/test_memory_scheduler.py"],
  "tests_run": {
    "command": "python -m pytest tests/test_memory_scheduler.py -v",
    "passed": 5,
    "failed": 0,
    "output_hash": "sha256:abc123..."
  },
  "regression_check": {
    "command": "python -m pytest tests/test_architecture.py -x --tb=short -q",
    "passed": true,
    "output_hash": "sha256:def456..."
  },
  "self_review": {
    "comments_accurate": true,
    "logic_concerns": "None identified",
    "edge_cases_considered": ["empty memory store", "concurrent cleanup"]
  },
  "shrinkage": {
    "files_shrunk": [],
    "deletions_justified": ""
  },
  "scope_justification": "",
  "dependencies_reviewed": true,
  "boot_verified": false
}
```

---

## Implementation Order

1. **Verification record format + gate** (closes gaps 1, 2, 3, 7, 10)
   - Create `check_verification_record_gate.py`
   - Create `scripts/create_verification_record.py` (helper for agents)
   - Add to pre-commit and skip policy

2. **Diff-based ratchet** (closes gap 9)
   - Rewrite exception handler comparison to use diff hunks
   - Test with the false-positive scenario

3. **Config file protection** (closes gap 8)
   - Add config files to `agent_safety.toml` protected list

4. **Test coverage gate** (strengthens gap 3)
   - Create `check_test_coverage_gate.py`

5. **Frontend lint gate** (closes gap 4)
   - Create `check_frontend_lint_gate.py`

6. **Dependency gate** (closes gap 5)
   - Create `check_dependency_gate.py`

7. **Self-review protocol** (closes gap 6)
   - Add to verification record format
   - Document in agent briefing

---

## What This Means for a Non-Coder

When you tell an AI agent to work on Thomas, the agent will:
1. Read its briefing (rules for this specific task)
2. Write the code
3. Write tests for the code
4. Run the tests — if they fail, fix the code
5. Run existing tests — if anything broke, fix it
6. Review its own comments for accuracy
7. Create a verification record proving it did all of this
8. Commit — the hooks check the record and either accept or reject

If any step is skipped, the commit is blocked. The human can review the verification record to see exactly what the agent did and what evidence it produced.

This is the difference between "trust the agent" and "trust but verify."

---

Sources:
- [How I Validate Quality When AI Agents Write My Code](https://dev.to/teppana88/how-i-validate-quality-when-ai-agents-write-my-code-481c)
- [I stopped my AI coding agent from rewriting tests](https://dev.to/slimd/i-stopped-my-ai-coding-agent-from-rewriting-tests-heres-the-prompt-architecture-that-worked-1io8)
- [How to Make AI Agents Actually Fix Tests](https://raminmammadzada.medium.com/how-to-make-ai-agents-actually-fix-tests-instead-of-just-pretending-to-dbdfa349bb0b)
- [Stop Reading AI-Generated Code. Start Verifying It.](https://dev.to/choutos/stop-reading-ai-generated-code-start-verifying-it-1d1o)
- [CRabbit: 2025 was AI speed, 2026 will be AI quality](https://www.coderabbit.ai/blog/2025-was-the-year-of-ai-speed-2026-will-be-the-year-of-ai-quality)
- [How to write a good spec for AI agents](https://addyosmani.com/blog/good-spec/)
