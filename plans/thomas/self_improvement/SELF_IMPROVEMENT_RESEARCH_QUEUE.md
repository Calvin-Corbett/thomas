# Thomas Self-Improvement Research Queue

Raw, deduped candidate improvements for Thomas from current evidence about agent self-improvement, coding agents, orchestration systems, eval harnesses, and agent operations.

This queue is intentionally unranked. Ranking, design selection, and implementation planning belong to later worker lanes. Each entry is a candidate, not an adoption decision.

## Cycle: 2026-06-28 Source Scout

### SI-2026-06-28-001 - Agent Lightning trajectory-training boundary

- Stable id: SI-2026-06-28-001
- Source type: paper/GitHub
- URL: https://github.com/microsoft/agent-lightning
- Date checked: 2026-06-28
- Observed self-improvement behavior: Agent Lightning separates agent execution from reinforcement-learning training by treating agent runs as trajectories that can be logged, decomposed, credited, and optimized without rewriting the agent application around the trainer.
- Why it matters: Thomas already has long-running worker runs, claims, messages, tests, commit gates, and artifacts. A clean trajectory boundary would let Thomas learn from completed work without entangling product runtime with training loops.
- Thomas gap/hypothesis: Thomas has run evidence, but not a first-class "trajectory" artifact with states, actions, rewards, costs, blocked decisions, and verification outcomes. A Thomas-owned trajectory schema could feed evals, ranking, replay, and future self-improvement loops.
- Likely repo surfaces: `thomas/forge/anvil/evolve_loop.py`, `thomas/forge/anvil/evolve_loop_learning.py`, `thomas/forge/anvil/native_orchestration.py`, `scripts/crew/workboard/*`, `thomas/benchmarks/*`, `tests/test_evolve_loop_learning.py`.
- Dependency/security risks: Avoid importing a trainer into live worker execution. Trajectory logs may include prompts, repo paths, secrets, or private code snippets; redaction and retention policy need to precede any training export.
- Expected test strategy: Add a local trajectory fixture for one completed workboard task; assert deterministic serialization, redaction of sensitive fields, reward/credit labels, and replay into an eval scorer without network access.
- Effort estimate: M
- Confidence: High
- Dedupe key: trajectory-rl-boundary-agent-lightning

### SI-2026-06-28-002 - GEPA-style reflective prompt evolution

- Stable id: SI-2026-06-28-002
- Source type: paper/GitHub
- URL: https://github.com/gepa-ai/gepa
- Date checked: 2026-06-28
- Observed self-improvement behavior: GEPA uses reflective prompt evolution with textual feedback to improve compound AI systems, treating failures as actionable natural-language updates rather than only scalar rewards.
- Why it matters: Thomas work often fails for textual reasons that scalar scores lose: stale claims, unverified repo state, wrong scope, missing tests, or unsupported assumptions. Reflective prompt evolution matches that failure shape.
- Thomas gap/hypothesis: Thomas has many prompts, skills, and worker instructions, but does not appear to have a governed prompt-evolution loop that turns failed runs into candidate prompt patches with evidence, rollback, and regression checks.
- Likely repo surfaces: `skills/`, `thomas/forge/anvil/evolve_loop_learning.py`, `scripts/crew/brief/startup_router.py`, `docs/THOMAS_BIBLE.md`, `plans/thomas/FORGE_CODE_RUBRIC.md`, `tests/test_evolve_loop_learning.py`.
- Dependency/security risks: Prompt mutation can silently erode safety constraints or claim discipline. Any prompt evolution must preserve non-negotiable guardrail text and diff prompt changes like code.
- Expected test strategy: Build an offline prompt-evolution fixture from 3 failed worker transcripts; assert generated prompt deltas cite failure evidence, preserve required guardrail phrases, and improve a deterministic rubric score.
- Effort estimate: M
- Confidence: High
- Dedupe key: reflective-prompt-evolution-gepa

### SI-2026-06-28-003 - AlphaEvolve evaluator-backed code evolution

- Stable id: SI-2026-06-28-003
- Source type: blog/paper
- URL: https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
- Date checked: 2026-06-28
- Observed self-improvement behavior: AlphaEvolve evolves candidate programs through an automated evaluator loop, using model-generated variants plus scoring to discover stronger algorithms.
- Why it matters: Thomas has `evolve` surfaces and benchmark runners, but self-improvement should be constrained by executable evaluators, not narrative "looks better" claims.
- Thomas gap/hypothesis: Thomas could introduce "micro-evolve" lanes where a narrow helper, prompt, rubric, or fixture is mutated only when a local evaluator proves improvement and the commit helper gates pass.
- Likely repo surfaces: `thomas/forge/anvil/evolve_loop.py`, `thomas/forge/anvil/evolve_loop_actions.py`, `thomas/benchmarks/runner.py`, `scripts/run_agentic_benchmark.py`, `tests/test_evolve_loop.py`, `tests/test_agentic_benchmark.py`.
- Dependency/security risks: Evolution loops can optimize to the test harness, create brittle code, or run unbounded compute. Require sandboxing, caps, held-out fixtures, and human approval for product-code promotion.
- Expected test strategy: Create a docs-only or fixture-only micro-evolve proof that mutates one rubric phrase or local scoring helper, evaluates against training and holdout fixtures, and refuses promotion when holdout regresses.
- Effort estimate: M
- Confidence: Medium-high
- Dedupe key: evaluator-backed-code-evolution-alphaevolve

### SI-2026-06-28-004 - Claude Code hooks as deterministic worker guardrails

- Stable id: SI-2026-06-28-004
- Source type: docs
- URL: https://docs.anthropic.com/en/docs/claude-code/hooks
- Date checked: 2026-06-28
- Observed self-improvement behavior: Claude Code hooks expose deterministic lifecycle interception points around agent actions, allowing projects to enforce checks, inject context, block unsafe tool calls, and record audit evidence outside model discretion.
- Why it matters: Thomas already relies on commit gates, workboard claims, and active-folder guards, but some checks happen late. Hook-like pre-action and post-action layers could catch drift before a worker writes or spends.
- Thomas gap/hypothesis: Thomas needs a unified worker action hook bus that fires before shell/file/browser/model actions and after verification, producing audit records compatible with current workboard and commit gates.
- Likely repo surfaces: `thomas/agent/loop_tool_exec.py`, `thomas/agent/loop_execution.py`, `scripts/crew/workboard/claim.py`, `scripts/forge/gates/workboard_agent_claim.py`, `scripts/active_folders.py`, `tests/test_agent_loop_tool_policy.py`.
- Dependency/security risks: Hook systems can become bypassable if only advisory. Hooks must fail closed for protected actions and must not allow untrusted local config to weaken global policy.
- Expected test strategy: Add a local pre-action hook fixture that blocks out-of-claim file edits and a post-action hook fixture that records verification evidence; assert bypass attempts fail closed.
- Effort estimate: M
- Confidence: High
- Dedupe key: deterministic-agent-action-hooks-claude-code

### SI-2026-06-28-005 - Claude Code subagents for scoped reviewer lanes

- Stable id: SI-2026-06-28-005
- Source type: docs
- URL: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Date checked: 2026-06-28
- Observed self-improvement behavior: Claude Code subagents package specialized instructions, context windows, and tool permissions so the main agent can delegate focused tasks to constrained experts.
- Why it matters: Thomas already uses worker, coordinator, reviewer, ranker, and scout roles. Subagent packaging is a concrete reference for making those roles durable, versioned, permissioned, and testable rather than only prompt text in a thread.
- Thomas gap/hypothesis: Thomas could define role manifests for scout, ranker, reviewer, merger, and verifier lanes, then test that each role receives only the tools, paths, and required reads it needs.
- Likely repo surfaces: `scripts/crew/workboard/worker.py`, `scripts/crew/workboard/claim_dispatch.py`, `scripts/crew/brief/startup_router.py`, `skills/`, `plans/thomas/FORGE_CODE_RUBRIC.md`, `tests/test_workboard_worker_script.py`.
- Dependency/security risks: Role manifests become stale if they do not cite live paths and gates. Over-permissioned subagents recreate the current broad-agent risk with a new label.
- Expected test strategy: Add manifest schema fixtures for two Thomas roles; assert required reads, allowed scopes, blocked scopes, and message/claim behavior are validated before dispatch.
- Effort estimate: S-M
- Confidence: High
- Dedupe key: scoped-role-subagents-claude-code

### SI-2026-06-28-006 - Anthropic multi-agent research system orchestration ratios

- Stable id: SI-2026-06-28-006
- Source type: blog
- URL: https://www.anthropic.com/engineering/built-multi-agent-research-system
- Date checked: 2026-06-28
- Observed self-improvement behavior: Anthropic describes a multi-agent research system where a lead agent delegates to subagents, aggregates evidence, and uses coordination patterns to outperform single-agent research on broad tasks.
- Why it matters: Thomas is moving toward visible native orchestration. The key lesson is not just "more agents"; it is coordinator bandwidth, evidence aggregation, and stopping rules for parallel exploration.
- Thomas gap/hypothesis: Thomas should track orchestration economics per task: number of workers spawned, evidence yield, duplicate rate, blocked rate, token spend, and final accepted improvements. That data can tune when Thomas should fan out.
- Likely repo surfaces: `thomas/forge/anvil/native_orchestration.py`, `scripts/crew/workboard/claim_dispatch.py`, `scripts/crew/workboard/message.py`, `thomas/server/chat_delegation_runner.py`, `thomas_spend.jsonl`, `tests/test_native_orchestration.py`.
- Dependency/security risks: Parallel agents amplify cost, overlapping claims, and stale-worker hazards. Fanout must be budgeted and claim-aware with dedupe and lease health checks.
- Expected test strategy: Add an orchestration metrics fixture with synthetic worker outcomes; assert duplicate-rate and blocked-rate calculations produce a "do not fan out" recommendation under poor conditions.
- Effort estimate: S-M
- Confidence: Medium-high
- Dedupe key: multi-agent-fanout-economics-anthropic

### SI-2026-06-28-007 - LangGraph persistence and time-travel debugging

- Stable id: SI-2026-06-28-007
- Source type: docs/GitHub
- URL: https://langchain-ai.github.io/langgraph/concepts/persistence/
- Date checked: 2026-06-28
- Observed self-improvement behavior: LangGraph persists checkpoints for agent graph execution, enabling resumption, state inspection, human-in-the-loop updates, and time-travel style debugging.
- Why it matters: Thomas worker failures often require reconstructing what happened from messages, claims, terminal output, and dirty files. Persisted state snapshots would make replay and self-debugging more reliable.
- Thomas gap/hypothesis: Thomas has workboard state and some session objects, but no single checkpoint contract for "agent run state before/after each meaningful action." Adding one would support recovery, replay, and run comparison.
- Likely repo surfaces: `thomas/server/chat_delegation_session.py`, `thomas/server/chat_delegation_runner.py`, `thomas/forge/anvil/native_orchestration.py`, `thomas/forge/anvil/evolve_loop_state.py`, `tests/test_chat_delegation_self_recovery.py`.
- Dependency/security risks: Checkpoints can leak prompt data or repository content and can be corrupted if used as authority without validation. Need schema versioning and redaction.
- Expected test strategy: Add an offline checkpoint fixture for one chat-delegation worker run; assert resume after interruption, state diff rendering, redaction, and schema migration guard behavior.
- Effort estimate: M
- Confidence: High
- Dedupe key: durable-agent-checkpoints-langgraph

### SI-2026-06-28-008 - OpenAI Agents SDK trace and handoff schema

- Stable id: SI-2026-06-28-008
- Source type: docs/GitHub
- URL: https://openai.github.io/openai-agents-python/tracing/
- Date checked: 2026-06-28
- Observed self-improvement behavior: The OpenAI Agents SDK exposes tracing for agent runs, model calls, tool calls, handoffs, guardrails, and custom spans.
- Why it matters: Thomas needs inspectable run evidence so future agents can learn from prior runs and users can see why a worker acted, blocked, or handed off.
- Thomas gap/hypothesis: Thomas should define a canonical run-event schema before more orchestration accumulates: worker started, claim acquired, source read, tool call, file edit, test, blocker, handoff, commit, release.
- Likely repo surfaces: `thomas/server/chat_delegation_emitter.py`, `thomas/server/chat_delegation_runner.py`, `thomas/server/chat_delegation.py`, `thomas/server/web/*`, `tests/test_chat_delegation.py`, `tests/test_chat_delegation_handoff.py`.
- Dependency/security risks: Trace exporters can leak sensitive input. Also, adopting external span names directly may create churn; wrap them behind a Thomas schema mapper.
- Expected test strategy: Create a fixture trace for one worker lifecycle; assert event ordering, required fields, redaction, and compatibility mapping to OpenTelemetry-style GenAI attributes.
- Effort estimate: S-M
- Confidence: High
- Dedupe key: canonical-agent-run-tracing-openai-agents

### SI-2026-06-28-009 - OpenHands isolated software-agent workspaces

- Stable id: SI-2026-06-28-009
- Source type: GitHub/docs
- URL: https://github.com/All-Hands-AI/OpenHands
- Date checked: 2026-06-28
- Observed self-improvement behavior: OpenHands treats coding agents as software workers operating inside managed workspaces with explicit execution, browser, and file interaction surfaces.
- Why it matters: Thomas repeatedly blocks when the live checkout is dirty or not on the expected branch. Isolated worker worktrees and managed workspace lifecycles would let scouts, rankers, and fixers keep moving without contaminating the main checkout.
- Thomas gap/hypothesis: Thomas has active-folder leases and workboard claims, but the source scout itself needed a separate clean worktree to proceed. That pattern should become a first-class worker workspace allocation flow.
- Likely repo surfaces: `scripts/active_folders.py`, `scripts/crew/worktree_ledger.py`, `thomas/server/chat_delegation_live_repo.py`, `scripts/crew/workboard/claim.py`, `tests/test_active_folders.py`, `tests/test_chat_delegation.py`.
- Dependency/security risks: Workspace provisioning touches filesystem boundaries and secrets. Workers must not inherit host credentials or write outside their allocated worktree.
- Expected test strategy: Add a worktree allocation fixture that creates a disposable clean branch/worktree, records a lease, rejects out-of-root file writes, and cleans up after release.
- Effort estimate: M-L
- Confidence: High
- Dedupe key: isolated-coding-agent-workspaces-openhands

### SI-2026-06-28-010 - SWE-agent and SWE-bench style regression tasks

- Stable id: SI-2026-06-28-010
- Source type: GitHub/paper
- URL: https://github.com/SWE-agent/SWE-agent
- Date checked: 2026-06-28
- Observed self-improvement behavior: SWE-agent frames repository repair as an agent-computer interface task, while SWE-bench-style harnesses score agents on real issue-to-patch workflows.
- Why it matters: Thomas needs a way to prove coding-worker improvements actually make workers better at scoped repo tasks, not just better at producing plausible plans.
- Thomas gap/hypothesis: Thomas has benchmark surfaces and an existing `thomas/benchmarks/swe_bench.py`, but should add small local SWE-bench-inspired regression tasks that mirror Thomas claims, tests, commit gates, and release rules before running larger external suites.
- Likely repo surfaces: `thomas/benchmarks/swe_bench.py`, `thomas/benchmarks/runner.py`, `scripts/run_agentic_benchmark.py`, `plans/thomas/evals/*`, `tests/test_benchmarks.py`, `tests/test_agentic_benchmark.py`.
- Dependency/security risks: Full external benchmarks can be heavyweight, flaky, and network-dependent. Start with local fixtures and explicit resource caps.
- Expected test strategy: Create two local issue-to-patch fixtures with expected file scopes, failing tests, passing tests, and a commit-helper dry-run check; score both final patch success and process hygiene.
- Effort estimate: M
- Confidence: High
- Dedupe key: coding-worker-regression-harness-swe-agent

## Cycle: 2026-06-28 Source Scout heartbeat follow-up

### SI-2026-06-28-011 - Self-improving coding agent edits its own agent code

- Stable id: SI-2026-06-28-011
- Source type: paper
- URL: https://arxiv.org/html/2504.15228v2
- Date checked: 2026-06-28
- Observed self-improvement behavior: The SICA paper demonstrates an agent system with coding tools that autonomously edits its own codebase and benchmarks the resulting agent variants, eliminating the hard separation between target agent and meta-agent.
- Why it matters: Thomas has an evolve loop, worker orchestration, commit gates, and planning queues, but its self-improvement path should require explicit variant boundaries, benchmark evidence, and rollback before any agent edits its own runtime.
- Thomas gap/hypothesis: Thomas can borrow the "agent variant under benchmark" concept without allowing live self-editing: generate a disposable worktree variant, run a fixed worker-eval pack, and only promote if gates and held-out checks pass.
- Likely repo surfaces: `thomas/forge/anvil/evolve_loop.py`, `thomas/forge/anvil/evolve_loop_actions.py`, `thomas/forge/anvil/evolve_loop_learning.py`, `scripts/crew/worktree_ledger.py`, `scripts/crew/brief/commit.py`, `tests/test_evolve_loop.py`.
- Dependency/security risks: Self-editing agents can optimize around tests, weaken guardrails, or mutate protected files. Promotions need strict scope controls, held-out evals, and human approval for runtime surfaces.
- Expected test strategy: Add a local "variant worktree" fixture that proposes a harmless prompt/helper mutation, runs training and held-out eval fixtures, refuses protected-file edits, and records a promotion/rejection decision.
- Effort estimate: M-L
- Confidence: High
- Dedupe key: self-editing-agent-variant-benchmark-sica

### SI-2026-06-28-012 - Reflexion-style verbal failure memory

- Stable id: SI-2026-06-28-012
- Source type: paper/GitHub
- URL: https://openreview.net/forum?id=vAElhFcKW6
- Date checked: 2026-06-28
- Observed self-improvement behavior: Reflexion agents convert task feedback into natural-language reflections stored in an episodic memory buffer, improving later attempts without model fine-tuning.
- Why it matters: Thomas already produces rich failure text from gates, tests, workboard blockers, and coordinator decisions. Most of that text is not converted into durable, task-shaped learning.
- Thomas gap/hypothesis: Thomas should add a "failure reflection card" artifact for completed or blocked worker runs: what failed, what invariant was missed, what should be checked earlier next time, and which prompt/guard/test should change.
- Likely repo surfaces: `thomas/memory/v2/fabric.py`, `thomas/memory/curator.py`, `scripts/crew/workboard/message.py`, `thomas/server/chat_delegation_result_summary.py`, `tests/test_memory_fabric_v2.py`, `tests/test_chat_delegation_result_summary.py`.
- Dependency/security risks: Reflection memory can preserve bad assumptions or sensitive data. Cards need source citations, expiry/review state, and redaction before entering shared memory.
- Expected test strategy: Feed a synthetic failed commit-gate transcript into a reflection-card builder; assert it extracts checkable lessons, redacts paths/secrets as configured, and does not override Bible/live-code truth.
- Effort estimate: S-M
- Confidence: High
- Dedupe key: verbal-reflection-memory-reflexion

### SI-2026-06-28-013 - Voyager-style skill library with automatic curriculum

- Stable id: SI-2026-06-28-013
- Source type: paper/GitHub
- URL: https://github.com/MineDojo/Voyager
- Date checked: 2026-06-28
- Observed self-improvement behavior: Voyager combines an automatic curriculum, an expanding executable skill library, and iterative prompting with environment feedback and self-verification.
- Why it matters: Thomas has skills and recurring worker lanes, but successful procedures are not consistently captured as reusable, tested skills after a worker solves a task.
- Thomas gap/hypothesis: Thomas could turn repeated successful worker patterns into candidate skills only after a curriculum/eval rule proves the pattern recurs and a small fixture validates the procedure.
- Likely repo surfaces: `skills/`, `scripts/crew/brief/startup_router.py`, `scripts/crew/workboard/worker.py`, `thomas/agent/skills_runtime.py`, `tests/test_agent_skills_runtime.py`, memory/reflection artifacts.
- Dependency/security risks: Auto-growing skill libraries can accumulate stale or overbroad permissions. New skills need ownership, required reads, risk labels, and regression fixtures before activation.
- Expected test strategy: Add a "promote transcript to candidate skill" fixture that requires at least two successful similar runs, extracts a minimal procedure, blocks risky tools by default, and emits a disabled skill draft plus tests.
- Effort estimate: M
- Confidence: Medium-high
- Dedupe key: automatic-curriculum-skill-library-voyager

### SI-2026-06-28-014 - RE-Bench style long-horizon research-engineering evals

- Stable id: SI-2026-06-28-014
- Source type: GitHub/paper/blog
- URL: https://github.com/METR/RE-Bench
- Date checked: 2026-06-28
- Observed self-improvement behavior: RE-Bench evaluates frontier agents on long-horizon ML research-engineering tasks and includes human expert comparison data and full run transcripts.
- Why it matters: Thomas should not optimize only for short issue patches. Many Thomas tasks are long-running, ambiguous, multi-step engineering/research jobs with coordination and verification overhead.
- Thomas gap/hypothesis: Thomas needs a local "long-horizon worker eval" lane using real archived tasks: setup, allowed tools, time budget, transcript capture, final artifact score, process hygiene score, and human-baseline notes where available.
- Likely repo surfaces: `thomas/benchmarks/runner.py`, `scripts/run_agentic_benchmark.py`, `plans/thomas/evals/`, `thomas/demo/agentic_benchmark.py`, `tests/test_agentic_benchmark.py`, `tests/test_benchmark_lane.py`.
- Dependency/security risks: Long-horizon evals are expensive and can be noisy. Use capped local fixtures first, record cost/time, and avoid turning the eval into a hidden autonomous work loop.
- Expected test strategy: Convert one completed Thomas planning task into a deterministic long-horizon eval fixture with setup, transcript, expected artifacts, scoring rubric, and budget assertions.
- Effort estimate: M-L
- Confidence: High
- Dedupe key: long-horizon-research-engineering-eval-rebench

### SI-2026-06-28-015 - OpenTelemetry GenAI agent semantic conventions

- Stable id: SI-2026-06-28-015
- Source type: GitHub/docs
- URL: https://github.com/open-telemetry/semantic-conventions-genai
- Date checked: 2026-06-28
- Observed self-improvement behavior: OpenTelemetry's GenAI semantic conventions are converging on standardized spans, metrics, and events for GenAI clients, MCP, providers, and agentic systems.
- Why it matters: Thomas self-improvement needs comparable run evidence across workers, models, tools, and orchestration modes. A standard telemetry vocabulary makes regressions and improvements easier to query.
- Thomas gap/hypothesis: Thomas should map internal worker events to a small OpenTelemetry-compatible schema before adding more bespoke run logs, preserving Thomas-specific fields behind a mapper.
- Likely repo surfaces: `thomas/server/chat_delegation_emitter.py`, `thomas/agent/loop_execution.py`, `thomas/agent/loop_tool_exec.py`, `thomas/forge/anvil/native_orchestration.py`, `thomas_spend.jsonl`, telemetry schema tests.
- Dependency/security risks: Raw telemetry can leak prompts, tool arguments, file paths, or secrets. Schema adoption must include redaction, sampling, and opt-in export controls.
- Expected test strategy: Build a fixture run with model call, tool call, claim, test, blocker, and commit events; assert deterministic mapping to internal and OpenTelemetry-style attributes with redaction.
- Effort estimate: S-M
- Confidence: High
- Dedupe key: opentelemetry-genai-agent-semantics
