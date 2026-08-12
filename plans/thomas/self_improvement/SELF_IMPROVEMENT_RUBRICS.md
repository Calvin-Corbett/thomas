# Thomas Self-Improvement Rubrics

Objective, implementable rubrics derived from `SELF_IMPROVEMENT_RESEARCH_QUEUE.md`.
This file is a grading contract, not an implementation decision. Each rubric is
small enough to hand to an implementation worker and strict enough for an
independent grader to reproduce pass/fail results from repository evidence.

## Rubric Quality Rules

- Durable artifact before grading: the implementation must create or update a
  committed artifact, fixture, schema, or test before any score can be assigned.
- Exact evidence only: every pass/fail item below names the observable file,
  command, output field, or test assertion that proves the result.
- Adversarial negative tests required: each implementation must include at least
  one fixture or test that intentionally violates the contract and fails closed.
- Security and privacy checks are mandatory, not extra credit.
- No self-reported scoring: implementers may report evidence, but a separate
  grader must run the listed commands and mark each item pass/fail.
- Perfect-score cap: no rubric may receive a perfect score unless an independent
  adversarial reviewer confirms that the negative tests would catch a plausible
  shortcut or bypass.
- Vague evidence cap: if a line item cannot be observed by command output,
  committed diff, or deterministic test assertion, the maximum score for that
  rubric is 60 percent even if the narrative sounds plausible.

## RUBRIC-SIR-2026-06-28-001 - Worker Trajectory Artifact Contract

- Stable rubric id: `RUBRIC-SIR-2026-06-28-001`
- Source candidate id: `SI-2026-06-28-001`
- Goal: define a Thomas-owned trajectory artifact that captures one completed
  worker task as ordered states, actions, claims, costs, blockers, verification
  results, commit metadata, and rollback evidence without coupling live worker
  execution to any external trainer.
- Likely files/surfaces touched:
  - `thomas/benchmarks/trajectory.py`
  - `thomas/benchmarks/__init__.py`
  - `tests/test_worker_trajectory.py`
  - `plans/thomas/self_improvement/trajectory_fixtures/*.json`
  - optionally `docs/THOMAS_BIBLE.md` only if the implementation changes a
    documented runtime truth.
- Non-goals:
  - Do not import Agent Lightning or any reinforcement-learning trainer.
  - Do not export private prompts, secrets, full file contents, or raw terminal
    logs to a training format.
  - Do not change live worker dispatch, claim, commit, or message behavior.
- Prerequisites:
  - Read `docs/THOMAS_BIBLE.md` agent guidance before implementation.
  - Confirm no active claim overlaps the files above.
  - Use a local/offline fixture; no network calls are allowed.
- Implementation steps:
  1. Add a versioned trajectory schema with required fields for run id, task id,
     ordered events, claim scope, action type, evidence path, verification
     command, result, blocker state, commit SHA, rollback criteria, and redaction
     metadata.
  2. Add one committed fixture representing a completed workboard task.
  3. Add deterministic serialization and validation helpers.
  4. Add a scorer adapter that reads the fixture and emits process-hygiene labels
     without mutating repo state.
  5. Add tests for valid serialization, invalid ordering, missing required
     fields, redaction, and offline scorer behavior.
- Pass/fail line items and tests:
  - `SIR001-L1 schema-version`: PASS only if a committed schema or typed helper
    exposes a `schema_version` field and tests assert the current accepted
    version. Test by running `python -m pytest tests/test_worker_trajectory.py -q`
    and inspecting for an assertion that rejects an unsupported version.
  - `SIR001-L2 deterministic-serialization`: PASS only if serializing the same
    fixture twice produces byte-identical JSON with stable event ordering. Test
    command: `python -m pytest tests/test_worker_trajectory.py -q -k deterministic`.
  - `SIR001-L3 required-process-events`: PASS only if validation rejects a
    trajectory missing claim acquisition, source read, verification command, or
    release/rollback terminal state. Test command: `python -m pytest
    tests/test_worker_trajectory.py -q -k required`.
  - `SIR001-L4 redaction`: PASS only if prompts, secret-looking tokens, absolute
    private home paths outside the repo, and raw file contents are redacted or
    rejected. Test command: `python -m pytest tests/test_worker_trajectory.py -q
    -k redaction`.
  - `SIR001-L5 offline-scorer`: PASS only if the scorer consumes the fixture and
    emits labels without network access, model calls, shelling out to external
    trainers, or mutating files. Test by running `python -m pytest
    tests/test_worker_trajectory.py -q -k scorer` and checking `git diff
    --exit-code -- thomas/benchmarks tests plans/thomas/self_improvement`.
  - `SIR001-L6 adversarial-negative`: PASS only if at least one test fixture
    intentionally includes a forged success state or missing failed command and
    the validator fails closed. Test command: `python -m pytest
    tests/test_worker_trajectory.py -q -k adversarial`.
- Required focused commands:
  - `python -m pytest tests/test_worker_trajectory.py -q`
  - `python -m ruff check thomas/benchmarks/trajectory.py tests/test_worker_trajectory.py`
  - `git diff --check -- thomas/benchmarks/trajectory.py tests/test_worker_trajectory.py plans/thomas/self_improvement`
  - `python scripts/crew/brief/commit.py --dry-run --json --include thomas/benchmarks/trajectory.py --include tests/test_worker_trajectory.py --include plans/thomas/self_improvement`
- Security/privacy checks:
  - Verify fixture content does not include API keys, bearer tokens, private
    prompts, full user messages, or raw code snippets not needed for grading.
  - Verify redaction tests include both obvious secrets and path-like local
    identifiers.
  - Verify the implementation does not introduce network dependencies.
- Rollback criteria:
  - Revert the trajectory helper, tests, and fixtures if validation permits
    forged success, if redaction fails, or if commit dry-run reports protected
    file or release-hygiene blockers outside the claimed scope.
- Grader instructions:
  - Run every command above from a clean claimed worktree.
  - Mark each line item PASS or FAIL with the exact command output.
  - Award no perfect score unless a reviewer adds one additional malformed
    trajectory fixture and confirms the validator rejects it.
- Parallelization safety:
  - Safe to run in parallel with docs-only self-improvement planning.
  - Do not run in parallel with workers changing `thomas/benchmarks/*`,
    workboard claim gates, or commit helper gates.
- Commit criteria:
  - Diff is limited to the listed surfaces.
  - All required focused commands pass.
  - Commit message includes a `Thomas-Agent: <agent>` trailer.

## RUBRIC-SIR-2026-06-28-002 - Canonical Run-Event Trace Schema

- Stable rubric id: `RUBRIC-SIR-2026-06-28-002`
- Source candidate id: `SI-2026-06-28-008`
- Goal: define a canonical Thomas run-event schema for worker lifecycle traces
  so future self-improvement workers can learn from ordered, redacted evidence
  instead of reconstructing runs from scattered terminal output and workboard
  edits.
- Likely files/surfaces touched:
  - `thomas/server/chat_delegation_emitter.py`
  - `thomas/server/chat_delegation_runner.py`
  - `thomas/server/chat_delegation.py`
  - `tests/test_chat_delegation.py`
  - `tests/test_chat_delegation_handoff.py`
  - `plans/thomas/self_improvement/run_event_trace_fixture.json`
- Non-goals:
  - Do not adopt an external tracing backend directly.
  - Do not stream traces to a network exporter.
  - Do not redesign the UI or chat delegation protocol beyond adding a stable
    event payload contract.
- Prerequisites:
  - Read the Bible sections that cover chat delegation before touching runtime
    files, and verify whether they have drifted.
  - Confirm no active claim overlaps `thomas/server/chat_delegation*` or the
    target tests.
- Implementation steps:
  1. Define allowed event types: worker_started, claim_acquired, source_read,
     tool_call_started, tool_call_finished, file_edit, verification_started,
     verification_finished, blocker, handoff, commit_created, claim_released.
  2. Define required fields for each event type, including event id, run id,
     timestamp, actor, scope, parent event id where applicable, redaction status,
     and evidence pointer.
  3. Add an offline fixture trace for one successful worker lifecycle and one
     blocked worker lifecycle.
  4. Add validation tests for ordering, required fields, redaction, and handoff
     compatibility.
  5. Add a mapper function only if needed to translate Thomas events to a
     generic span-like shape; keep Thomas schema authoritative.
- Pass/fail line items and tests:
  - `SIR002-L1 event-type-enum`: PASS only if allowed event types are explicit
    and validation rejects unknown types. Test command: `python -m pytest
    tests/test_chat_delegation.py tests/test_chat_delegation_handoff.py -q -k
    event_type`.
  - `SIR002-L2 required-fields`: PASS only if each event type has deterministic
    required fields and fixtures missing any required field fail validation. Test
    command: `python -m pytest tests/test_chat_delegation.py -q -k
    required_fields`.
  - `SIR002-L3 ordering`: PASS only if validation rejects commit_created before
    verification_finished, claim_released before claim_acquired, and handoff
    without a blocker or decision event. Test command: `python -m pytest
    tests/test_chat_delegation_handoff.py -q -k ordering`.
  - `SIR002-L4 redaction-status`: PASS only if every event carrying user text,
    shell output, file path, or model content has an explicit redaction status
    and tests reject missing status. Test command: `python -m pytest
    tests/test_chat_delegation.py -q -k redaction`.
  - `SIR002-L5 durable-fixtures`: PASS only if at least two committed fixtures
    exist: one successful trace and one blocked/handoff trace. Test by checking
    `git ls-files plans/thomas/self_improvement/*trace*` and running the trace
    fixture tests.
  - `SIR002-L6 adversarial-negative`: PASS only if a malformed trace fixture
    with a forged commit event or missing verification evidence is rejected.
    Test command: `python -m pytest tests/test_chat_delegation.py
    tests/test_chat_delegation_handoff.py -q -k adversarial`.
- Required focused commands:
  - `python -m pytest tests/test_chat_delegation.py tests/test_chat_delegation_handoff.py -q`
  - `python -m ruff check thomas/server/chat_delegation_emitter.py thomas/server/chat_delegation_runner.py thomas/server/chat_delegation.py tests/test_chat_delegation.py tests/test_chat_delegation_handoff.py`
  - `git diff --check -- thomas/server/chat_delegation_emitter.py thomas/server/chat_delegation_runner.py thomas/server/chat_delegation.py tests/test_chat_delegation.py tests/test_chat_delegation_handoff.py plans/thomas/self_improvement`
  - `python scripts/crew/brief/commit.py --dry-run --json --include thomas/server/chat_delegation_emitter.py --include thomas/server/chat_delegation_runner.py --include thomas/server/chat_delegation.py --include tests/test_chat_delegation.py --include tests/test_chat_delegation_handoff.py --include plans/thomas/self_improvement`
- Security/privacy checks:
  - Ensure traces carry evidence pointers or hashes instead of raw secrets,
    private prompts, or full terminal dumps.
  - Ensure any exporter or mapper is local-only by default.
  - Ensure untrusted local configuration cannot disable redaction validation.
- Rollback criteria:
  - Revert if trace validation is advisory only, if malformed traces can pass,
    if tests depend on network access, or if the schema silently changes
    existing handoff semantics without a migration path.
- Grader instructions:
  - Inspect the committed fixtures before running tests.
  - Confirm each event has the required fields using test assertions, not visual
    review alone.
  - Cap score at 80 percent if only success traces exist and no blocked/handoff
    trace is committed.
- Parallelization safety:
  - Do not run beside other workers editing chat delegation runtime or handoff
    tests.
  - Safe beside docs-only rubric, ranking, or source-scout lanes.
- Commit criteria:
  - Diff is limited to claimed trace schema/runtime/test/fixture surfaces.
  - Required focused commands pass.
  - Commit helper dry-run is green and commit includes `Thomas-Agent`.

## RUBRIC-SIR-2026-06-28-003 - Orchestration Fanout Economics Gate

- Stable rubric id: `RUBRIC-SIR-2026-06-28-003`
- Source candidate id: `SI-2026-06-28-006`
- Goal: add a local metric contract that helps Thomas decide when native
  orchestration should or should not fan out to multiple workers based on
  duplicate rate, blocked rate, accepted-evidence yield, token spend, and claim
  overlap risk.
- Likely files/surfaces touched:
  - `thomas/forge/anvil/native_orchestration.py`
  - `scripts/crew/workboard/claim_dispatch.py`
  - `scripts/crew/workboard/message.py`
  - `tests/test_native_orchestration.py`
  - `tests/test_workboard_claim_dispatch.py`
  - `plans/thomas/self_improvement/fanout_metrics_fixture.json`
- Non-goals:
  - Do not increase default fanout.
  - Do not create new worker threads from the implementation.
  - Do not read real spend logs containing private data unless a redacted local
    fixture is committed first.
- Prerequisites:
  - Verify current native-orchestration behavior against live code and Bible
    notes before editing.
  - Confirm no active claims overlap orchestration or workboard dispatch files.
  - Use synthetic or redacted fixtures only.
- Implementation steps:
  1. Define fanout metric inputs: workers spawned, duplicate scopes, blocked
     workers, accepted artifacts, verification failures, token/cost estimate,
     stale leases, and final coordinator decision.
  2. Add a deterministic recommendation function returning `fanout_ok`,
     `fanout_limited`, or `do_not_fanout` with machine-readable reasons.
  3. Add fixtures for a healthy fanout, duplicate-heavy fanout, blocked-heavy
     fanout, and over-budget fanout.
  4. Wire the recommendation into a planning or reporting surface without
     changing worker launch defaults unless a separate implementation claim
     covers that behavior.
  5. Add tests that prove poor economics prevent or warn against fanout.
- Pass/fail line items and tests:
  - `SIR003-L1 metric-input-contract`: PASS only if the metric input fields are
    explicit and missing duplicate-rate, blocked-rate, accepted-yield, or budget
    fields fail validation. Test command: `python -m pytest
    tests/test_native_orchestration.py tests/test_workboard_claim_dispatch.py -q
    -k metric_input`.
  - `SIR003-L2 deterministic-recommendation`: PASS only if identical fixture
    input always produces the same recommendation and reason list. Test command:
    `python -m pytest tests/test_native_orchestration.py -q -k recommendation`.
  - `SIR003-L3 duplicate-rate-stop`: PASS only if a duplicate-heavy fixture
    returns `do_not_fanout` or an equivalent hard stop before worker dispatch.
    Test command: `python -m pytest tests/test_workboard_claim_dispatch.py -q -k
    duplicate`.
  - `SIR003-L4 blocked-rate-stop`: PASS only if a blocked-heavy or stale-lease
    fixture returns a hard stop or limited fanout with explicit reasons. Test
    command: `python -m pytest tests/test_native_orchestration.py -q -k blocked`.
  - `SIR003-L5 evidence-yield`: PASS only if accepted artifacts count more than
    spawned worker count alone; a fixture with many workers and zero accepted
    artifacts must not be scored as successful. Test command: `python -m pytest
    tests/test_native_orchestration.py -q -k evidence_yield`.
  - `SIR003-L6 adversarial-negative`: PASS only if a fixture that omits cost or
    claim-overlap data cannot receive `fanout_ok`. Test command: `python -m
    pytest tests/test_native_orchestration.py tests/test_workboard_claim_dispatch.py
    -q -k adversarial`.
- Required focused commands:
  - `python -m pytest tests/test_native_orchestration.py tests/test_workboard_claim_dispatch.py -q`
  - `python -m ruff check thomas/forge/anvil/native_orchestration.py scripts/crew/workboard/claim_dispatch.py scripts/crew/workboard/message.py tests/test_native_orchestration.py tests/test_workboard_claim_dispatch.py`
  - `git diff --check -- thomas/forge/anvil/native_orchestration.py scripts/crew/workboard/claim_dispatch.py scripts/crew/workboard/message.py tests/test_native_orchestration.py tests/test_workboard_claim_dispatch.py plans/thomas/self_improvement`
  - `python scripts/crew/brief/commit.py --dry-run --json --include thomas/forge/anvil/native_orchestration.py --include scripts/crew/workboard/claim_dispatch.py --include scripts/crew/workboard/message.py --include tests/test_native_orchestration.py --include tests/test_workboard_claim_dispatch.py --include plans/thomas/self_improvement`
- Security/privacy checks:
  - Fixtures must not include raw `thomas_spend.jsonl` content, user prompts, or
    private worker transcript text.
  - Budget and token fields must be numeric and bounded.
  - Recommendation logic must fail closed when claim overlap or stale lease data
    is missing.
- Rollback criteria:
  - Revert if the gate increases fanout by default, treats missing risk data as
    safe, or requires real spend logs for tests.
- Grader instructions:
  - Run focused tests and inspect the fixtures.
  - Confirm the duplicate-heavy, blocked-heavy, and missing-risk fixtures all
    prevent `fanout_ok`.
  - Cap score at 75 percent if the implementation reports metrics but never
    converts them into a deterministic recommendation.
- Parallelization safety:
  - Do not run beside workers changing native orchestration, claim dispatch, or
    message tools.
  - Safe beside source scouting, rubric editing, or unrelated docs-only lanes.
- Commit criteria:
  - Diff stays within the claimed implementation surfaces.
  - Required tests and commit-helper dry-run pass.
  - Commit includes `Thomas-Agent` and reports whether fanout defaults changed.
