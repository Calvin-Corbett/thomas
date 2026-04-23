# Module: core

| Field            | Value                                      |
|------------------|--------------------------------------------|
| Status           | functional (mixed — see below)             |
| Last assessed    | 2026-03-18                                 |
| Assessed by      | claude-opus-4-6 (Cowork session)           |
| Used in prod     | yes — most files are live infrastructure   |
| Has real tests   | partial                                    |
| Blocking issues  | testing_suite scores are misleading        |

## What This Is

The `core` package is the backbone of Thomas: config loading, LLM client wiring,
persistence, RAG indexing, event system, cost tracking, agent engine, and the
background testing suite. Most of the runtime depends on something in here.

## Honest Assessment

**Solid and production-used:**
- `config.py` — real config loading, used everywhere
- `persistence.py` — real key-value persistence, tested, works
- `llm.py` / `llm_client.py` / `llm_providers.py` / `llm_streaming.py` — real LLM wiring, actively used
- `events.py` / `event_schemas.py` — real pub/sub event bus
- `cost_tracker.py` / `tokens.py` — real token counting
- `rag_*.py` — real RAG pipeline (embeddings, indexing, search)
- `agent_presence.py` — new (0.14.37) but real, tested
- `placeholder_policy.py` — new (0.14.36) but real, enforced by tests
- `rules_of_road.py` — real validation, tested

**Scaffold / misleading:**
- `testing_suite.py` — **This is the big one.** The background testing suite
  runs 4 "tests" but they are not what they appear:
  - `prompt_injection_resistance` (scores 80): Real but narrow. Tests 10 hardcoded
    strings against `check_prompt_suspicious()`. Catches 8/10. Not adversarial,
    not dynamic, not probing novel attacks. More of a smoke test.
  - `persistence_survival` (scores 100): Trivial round-trip write/read. Proves
    the persistence layer boots. Not a stress test, not an edge-case test.
  - `autonomy_accuracy` (scores 50): **Not actually running.** Returns 50 (the
    "skipped" default) because no `executor_fn` is wired in. This score has
    NEVER reflected real autonomy testing.
  - `cost_efficiency` (scores 99-100): **Circular placeholder.** Checks whether
    previous cycles scored above 50. The docstring says "Real token tracking =
    future work." This is not measuring cost efficiency at all.
  - **The composite score of 77.8 looks like a health metric but it's mostly
    smoke tests and placeholders producing stable-looking numbers.**
  - `_auto_improve()` emits suggestions but they're hardcoded strings, not
    actual code changes.

- `self_upgrade_engine.py` — have not assessed yet, needs review
- `ui_effects_catalog.py` / `ui_review.py` / `ui_workflow_engine.py` — have not
  assessed yet, may be scaffold

## Vision / Full Scope

### testing_suite.py — what it should become:
1. **Prompt injection resistance**: Dynamic test set that pulls from a maintained
   probe library (not 10 hardcoded strings). Should include encoding attacks,
   indirect injection, multi-turn manipulation. Score should reflect miss severity
   not just catch count.
2. **Autonomy accuracy**: Wire an actual executor. Give it 5-10 real goals
   (file operations, search tasks, multi-step reasoning). Score on correctness
   of output, not just "did it return something."
3. **Persistence survival**: Test edge cases — concurrent writes, large values,
   corrupt DB recovery, cross-session continuity. Current test is necessary but
   not sufficient.
4. **Cost efficiency**: Track actual tokens consumed per cycle and per tool call.
   Compare against a baseline. Flag regressions. The infrastructure for this
   exists in `cost_tracker.py` and `tokens.py` — it just needs to be wired in.
5. **Composite score**: Should only report when ALL dimensions are actually
   measured. A score that includes "50 = skipped" is lying by omission.
6. **Auto-improve**: Should generate actual diffs or at minimum file-specific
   TODOs, not generic suggestions.

## Known Gaps

- testing_suite composite score is reported in dashboards but is misleading
- autonomy_accuracy has never run a real test
- cost_efficiency is circular (measures itself, not actual cost)
- self_upgrade_engine.py needs assessment
- ui_* files need assessment
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `persistence.py` — stable, production-critical, has good test coverage.
  Don't refactor without explicit user request.
- `config.py` — everything depends on this. Changes here break everything.
- `placeholder_policy.py` — intentionally strict. Don't loosen validation
  without explicit user approval.
