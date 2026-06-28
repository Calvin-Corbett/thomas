# Thomas Chat Pipeline — Stress Test & Frontier Audit

**Date:** 2026-06-17 · **Branch:** `dev` (HEAD `be84b853`, the latest code) · **Author:** Claude (chat-audit lane)
**Scope:** read-only audit + headless test harness. No chat-pipeline source was modified.

---

## TL;DR

I built a frontier-grade quality **rubric** (8 dimensions, trust-weighted) and a **headless stress
harness** that drives Thomas's *real* pipeline functions — no UI clicking, no LLM cost, fully
deterministic, reruns in ~3 seconds. It ran **98 probes** across **7 sweeps**.

> ## Trust Index: **21 / 100**
> 52 of 98 probes failed — **5 critical, 35 high.**

Every failure you hit in your test session is reproduced on demand and traced to an exact line of
code. The headline: **Thomas tells you things succeeded when they didn't.** That single class of bug
(weighted highest in the rubric, 0.26) is the most damaging because you make real decisions based on
a phantom "done."

The one thing that genuinely works: the *file*-creation anti-hallucination guard
(`artifact-provenance-fidelity` scored 4/4). The problem is that guard only covers files — everything
else (emails, deploys, deletes, "verified") is taken on faith.

---

## Scorecard (scored against the rubric)

| Dimension | Weight | Score | What it means |
|---|---|---|---|
| Evidence-Gated Completion | 0.26 | **1/4** | Reports "done"/"sent" with no proof the action happened |
| Autonomy Fidelity | 0.16 | **0/4** | "Max autonomy" changes nothing the model sees — it still asks |
| Capability & Self-State Honesty | 0.12 | **0/4** | Claims it used integrations (Gmail) it isn't connected to |
| In-Flight Steerability | 0.12 | **1/4** | No way to edit/cancel a task once it's dispatched |
| Openable Artifact Affordances | 0.10 | **1/4** | Only `.html` results are clickable; txt/pdf/csv/png are dead text |
| Concurrency / Graceful Degradation | 0.08 | **1/4** | Rapid messages → HTTP 409 → task "fails" |
| Artifact Provenance (file claims) | 0.06 | **4/4** | ✅ The one guard that works — files are verified on disk |
| Semantic Intent Routing | 0.06 | **0/4** | "put a file on my desktop" classified as small-talk, never dispatched |

*(Scoring rule: a dimension with any **critical** probe failure scores 0; any **high** failure caps
it at 1; otherwise `round(4 × pass-rate)`. This matches the rubric's anchors, where level 0 =
"fabricated success.")*

---

## What you saw → why it happens → the fix

### 1. "Email sent" with no Gmail connected  *(the worst one)*
- **You saw:** Thomas reported the email task complete; you knew Gmail isn't connected.
- **Root cause:** `_build_result_summary` (`thomas/server/chat_delegation_deliverable.py:246`) only
  fact-checks **file**-creation claims against disk. A claim like *"Email sent successfully"* is not a
  file claim, so it is echoed to you **verbatim as fact**. There is no verification of action-verb
  outcomes (send / delete / deploy / post / connect / install), and no check that the tool even
  succeeded — only that it was *named*.
- **Proof:** `sweep_honesty` — 8/12 fail, including `email_sent_unverified` (critical).
- **Fix:** Gate the success wording on the actual **tool result** (HTTP 2xx / returned id / exit code),
  not the worker's prose. Extend the file-claim guard to a general "action claim → require evidence"
  guard. Detect a disconnected integration **before** attempting and say so.

### 2. Tasks marked "completed / verified" when nothing happened
- **You saw:** worker said *"no tools were executed"* yet the card flipped to Completed.
- **Root cause:** `complete_execution` → `mark_verified` (`thomas/core/task_bot_runtime.py:606`,`:576`)
  stamp `state="completed"` and `proof_status="verified"` **unconditionally**, with `proof.artifacts`
  empty and no success signal. "Verified" is a label applied without verifying anything. (Note: the
  `task_checklist.py` evidence-gate your memory believed exists is **not in the code** — it was never
  merged into `dev`.)
- **Proof:** `sweep_lifecycle` — a no-op task ends `completed` + `verified`, artifacts `[]`.
- **Fix:** No code path should reach `completed` without an evidence check. Add states
  `failed` / `blocked` for no-op or errored runs. Require `proof.artifacts` or a tool-success signal
  before `verified`.

### 3. "Max autonomy" still asks permission
- **You saw:** on Max, Thomas asked *"Want me to hand it to the task manager?"*
- **Root cause:** the chatbot system prompt `THOMAS_CHATBOT_SYSTEM_PROMPT`
  (`thomas/marketplace/specialists/reasoning.py`) is **one static string** hardcoded to *"OFFER to
  hand it to the task manager — ask if they'd like you to."* The `autonomy_level` reaches the
  capability *token* (tool permissions) but is **never put in the model's `input_context`**
  (`brain.py:966-973`). So the model literally cannot see your autonomy setting; it gets identical
  instructions at L1 and L4.
- **Proof:** `sweep_autonomy` — model-facing instructions are **byte-identical** across L1–L4.
- **Fix:** Thread `autonomy_level` into `input_context` and make the prompt autonomy-aware:
  at high autonomy, "act without asking; only pause for genuine ambiguity."

### 4. Real requests treated as small-talk
- **You saw:** you had to fight to get "put a file on my desktop" to dispatch.
- **Root cause:** `should_dispatch` (`thomas/agent/dispatch.py:148`) is a **keyword whitelist**. "put"
  isn't in the action-verb list, so the message defaults to `casual` — even in max mode. ~10 of 14
  natural-language tasks ("schedule a meeting", "order printer paper", "book a flight") misroute.
- **Proof:** `sweep_routing` — 26/64 misrouted; the flagship case fails (critical).
- **Fix:** Use the model to classify intent (it's already in the loop), not a regex. Your own memory
  notes this: "regex `should_dispatch` proven to misjudge 6/18 real tasks → Phase 2 = model
  `send_task`." This audit quantifies it.

### 5. No clickable file in chat
- **You saw:** `Desktop/hello.txt` shown as bare text, nothing to click.
- **Root cause:** the deliverable resolver (`deliverable_aiohttp.py:47`) scans `*.html` **only**, and
  the completion path never populates `proof.artifacts`. So no structured artifact list ever reaches
  the UI for non-HTML files.
- **Proof:** `sweep_artifacts` — 7 of 8 file types yield no affordance; `proof.artifacts` stays `[]`.
- **Fix:** Populate `proof.artifacts` with `{path, type, actions}` on completion; render open / reveal /
  download in the chat card for any file type.

### 6. Can't edit a task in progress
- **You saw:** no way to steer a running task; you expected "just message the task manager."
- **Root cause:** there is **no API** to amend/redirect/cancel a *dispatched* background execution.
  `update_execution` only mutates status/progress bookkeeping. The only interrupt that exists
  (`loop_execution.py:1097`) steers the **synchronous in-chat run**, not a background task card.
- **Proof:** `sweep_steerability` — no steering/cancel functions exist in the task runtime API.
- **Fix:** Add a steering channel keyed by `execution_id` that injects a follow-up instruction (or a
  cancel) the worker checks between steps — exactly the mid-run interrupt queue, but for background
  tasks.

### 7. "Too many chats in a row → task failed"
- **You saw:** rapid messages caused failures.
- **Root cause:** two deterministic 409s. (a) **Race:** `begin_session_run` marks the session busy
  (`chat_aiohttp_handlers.py:73`) *before* the interrupt queue is created
  (`chat_request_execution.py:210`); a follow-up in that window finds `queue is None` → 409.
  (b) **Saturation:** the queue is `asyncio.Queue(maxsize=4)`; the 5th rapid message → `QueueFull` → 409.
- **Proof:** `sweep_concurrency` — both 409 paths reproduced with a real `asyncio.Queue(maxsize=4)`.
- **Fix:** Create the queue *before* marking busy (close the race); replace the hard cap-4 with
  coalescing/backpressure so rapid input is merged, not rejected.

---

## Recommended fix order (by trust impact)

1. **Evidence-gated completion + capability honesty** (0.38 of the rubric combined). Stop reporting
   unverified success. This is the trust-killer; fix it first.
2. **Autonomy fidelity** (0.16). One-line plumbing fix (autonomy into `input_context`) + an
   autonomy-aware prompt. High value, low effort.
3. **Steerability** (0.12) and **artifact affordances** (0.10).
4. **Concurrency** (0.08) and **semantic routing** (0.06). Routing is the long-game model-classifier
   change you already planned.

---

## Adversarial discovery — 16 more confirmed failures

A second multi-agent workflow swept six pipeline slices for failure modes *beyond* the seven above,
and handed each to a skeptic agent told to refute it against the real code. **18 proposed, 16
confirmed** (3 high, 6 medium, 6 low, 1 reclassified). Full detail in
[FINDINGS_ADVERSARIAL.md](FINDINGS_ADVERSARIAL.md). The ones that change the picture:

- **(HIGH) A failed tool result is swallowed.** A tool returning `ok=False` (or hitting a per-tool
  timeout) is reduced to a content-free event; if the model then emits `AGENT_DONE`, the failure
  becomes a reported success. This is the *execution-layer* root of the same disease as defect #2.
- **(HIGH) "Model gave up" looks identical to success.** Iteration/budget exhaustion (no
  `AGENT_DONE`/`ERROR`) is finished as `done` and reported completed.
- **(HIGH/security) Autonomy isn't enforced for tools either.** `token.autonomy_level` is never read
  by any specialist, and `ToolSpecialist` (`tools.py:192`) swaps in the **full** tool registry — so a
  low-autonomy task can still invoke shell / filesystem-write tools. (Note: the *separate* AgentLoop
  path does gate approval at `loop_tool_exec.py:435`; the V2-chat specialist path does not.) This
  makes autonomy cosmetic at the permission layer, not just the prompt.
- **Worker context gaps.** The handoff to a worker is snapshotted one turn too early, so the very
  message that triggered the task ("do that", "make it blue") is missing; multi-version and
  retry-fallback workers get *zero* conversation context.
- **Status & frontend truthfulness.** A dead/stranded worker is reported "still running" forever
  (the `stale` flag is ignored in the chat summary); a pure mark-reported write re-freshens the
  recency window so stale completions can re-appear as "recent".

These reinforce the same conclusion: the trust failures aren't one bug, they're a missing *discipline*
(verify before you claim) applied consistently from tool-result handling up through the status summary.

---

## How to re-run

```
.venv/Scripts/python.exe tests/stress/run_all.py        # full scorecard
.venv/Scripts/python.exe tests/stress/sweep_honesty.py  # any single sweep
```

Artifacts: `plans/thomas/chat_stress_2026-06-17/` — `RUBRIC.md`, `scorecard.json`,
`results_<sweep>.jsonl`, `FINDINGS_ADVERSARIAL.md`. Harness: `tests/stress/` (7 sweeps + runner).

**Final tally:** 99 deterministic probes → Trust Index 21/100; plus 16 adversarially-confirmed
findings. 23 distinct issues total across the 8 rubric dimensions.

## What this audit did NOT do
- It did **not** modify any chat-pipeline source (read-only lane; another Claude owns the gate/guard
  files, coordinated via workboard). All output is new files under `tests/stress/` and this folder.
- Concurrency mode 1/2 are faithful logic mirrors of the real handler, not a live HTTP load test
  (no server was started). A live probe script can be added if you want end-to-end confirmation.
- It did not attempt fixes. Every finding includes a concrete fix direction; implementation is a
  separate, owner-approved change.
