# PLAN for thomas-coherence-passage-2026-07-12

- Owner: codex-coherence
- Status: in_progress
- Updated At: 2026-07-13T00:54:40+00:00
- Scope: canonical Thomas identity, V2 conversation routing, governed inline actions, delegation, memory, evidence, and duplicate-path retirement

## Outcome

Thomas presents one enduring identity and turns user intent into verified reality through one governed loop:

1. observe the request and relevant state;
2. remember durable user context;
3. decide whether to answer, act within explicit permission, or delegate;
4. execute only bounded reversible actions inline;
5. route long-running, specialized, risky, or artifact-producing work to the task manager;
6. verify the real effect before claiming success;
7. record the evidence in conversation memory and report it in Thomas's voice.

## Product Laws

- Thomas is the persistent user-owned framework; the model is a replaceable engine.
- Conversation is the single relationship and control surface, not a powerless facade.
- The user remains sovereign. Important, irreversible, or elevated actions require explicit approval.
- A claim without effect evidence is not completion.
- Self-improvement may propose continuously, but its judge and promotion authority remain outside mutable code.
- Coherence comes before breadth: retire duplicate live paths and state stores before expanding capability inventory.

## Implementation Phases

### Phase 1 - Governed operator foundation

Status: implemented and verified in the current branch.

- Replace the chatbot-only identity prompt with a governed-operator contract.
- Add a narrow V2 inline-action interface for user-owned settings.
- Require guardrails for mutations and fail closed when they are unavailable.
- Capture pre-action state and post-action readback as reversible evidence.
- Thread inline-action evidence through specialist events, memory episodes, and done telemetry.

### Phase 2 - Canonical state and action journal

Status: canonical receipt and V2 session identity are implemented; lifecycle-store retirement remains.

- Define one action receipt shared by inline actions, delegated tasks, and completion reporting.
- Reconcile task, conversation, and memory identifiers around the V2 session.
- Retire parallel task lifecycle stores after migrating remaining readers.

### Phase 3 - One live conversation path

Status: live consumers and the production backend route are migrated. `/api/chat` is now a deprecated
URL alias to V2, legacy `batch`/`swarm` modes map to `max`, and production startup no longer imports
the legacy engine modules. Plan/slash helpers live in an engine-free auxiliary route bundle. Physical
deletion of the compatibility-only V1 modules remains a later removal after downstream callers migrate.

- Move remaining V1 consumers to V2.
- Remove the inert V2 feature flag and retire the V1 chat route family with behavioral replacement tests.
- Update the Bible and contributor guidance to the verified live path.

### Phase 4 - Prove the full owner journey

Status: real-browser inline read and guarded reversible mutation are proved. Delegated artifact,
steering/cancellation, and cross-restart completion persistence are proved against the durable ledger.

- Drive a real browser conversation using real input.
- Prove direct reversible action, delegated artifact work, steering/cancellation, persistence, and honest completion.
- Run focused, architecture, step-up, release, and browser-proof gates.

## Current Tranche Acceptance Criteria

- The canonical prompt describes Thomas as a governed operator, not "only a chatbot."
- The model can call one narrow operator tool for preferences get/list/set.
- Preference mutation is unavailable below Assist autonomy and fails closed without the guarded runner.
- Successful mutation records the previous value and a readback of the resulting value.
- The frontend stream receives tool evidence, and the captured memory episode includes that evidence.
- Existing send-task, task-update, remember, recall, and read-only repo behavior remains green.
- Inline and delegated work expose the same canonical action-receipt keys.
- Main web, virtual-office, companion, and Discord clients contain no V1 chat endpoint switch.

## Checkpoint Evidence

- Expanded operator, receipt, identity, send-task, orchestrator, route-helper, control, legacy-mode migration,
  route-registration, and migrated-web tests: 70 passed.
- Complete V2 max-mode route file: 26 passed.
- Discord bridge client contract: 4 passed.
- Ruff, Python compilation, diff check, and monolith guard: passed.
- Architecture dependency failures match the untouched base exactly (four pre-existing violations).
- Real browser proof with a deterministic local model: the visible chat accepted user input, called
  `preferences.list`, emitted started/completed action evidence, returned a verified reply, and closed
  with `tool_calls=1`.
- Default guardrails-off runtime rejected mutation capability; the proof runtime used explicit local
  guardrails and no-human test approval without changing production defaults.
- A second real-browser proof selected L4 through the visible Tools control, invoked a guarded
  `preferences.set` for an isolated `favorite_color` key, verified the API readback as `burnt orange`,
  then removed the isolated proof database and generated fake chat sessions.
- Delegated lifecycle proof creates real disk-ledger executions, walks the governed state transitions,
  steers and consumes an instruction, requests cancellation, rebuilds receipts from disk, completes a
  separate task only after attaching an artifact, and proves report-once behavior after clearing the
  process-local completion cache.
- Expanded coherence gate after lifecycle and production-route isolation: 117 passed. The production
  app import graph loads no `chat_aiohttp*` legacy module; auxiliary plan/slash route coverage remains green.
- Final 0.17.0 local-machine browser proof used the visible Thomas UI with real typed input. The rendered
  answer identified Thomas 0.17.0 and the canonical V2 engine; browser network evidence showed
  `POST /api/v2/chat` returning 200; reload preserved the Recent entry; reopening it restored the full
  prompt and answer. The isolated server, browser session, proof data, and harness were removed afterward.
- Owner testing then exposed a false-green in the handoff server: the demo profile selected keyless Gemini
  because saved `Local` casing did not match the lowercase catalog name and fallback considered only API
  keys. Startup selection is now case-insensitive and falls back through the same usable-profile predicate;
  the real profile is served with workspace auto-push disabled and verified through a genuine model turn.

## Release Checkpoint

The owner explicitly approved the protected 0.17.0 updates to `pyproject.toml` and `thomas/__init__.py`,
and both now match. The 117-test coherence gate, Ruff, Python compilation, and diff check pass after the
bump. Local commit creation still requires the repository's native Windows sign-in for protected-file
authorization; no safety gate is bypassed without that human confirmation.
