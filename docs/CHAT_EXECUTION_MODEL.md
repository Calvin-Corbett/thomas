# Chat Execution Model

> **This is the authoritative document for how Thomas chat works.**
> If you are changing chat, routing, skills, or delegation, read this first.

Last updated: 2026-07-22

## Model-Owned Orchestration

Thomas uses a model-owned execution model. Every natural-language turn goes to the
configured frontier model with its conversation context and the structured
capabilities allowed for that session. The model decides whether to answer directly
or make a structured call.

```text
User sends a natural-language message
              |
              v
Frontier Thomas model sees the conversation and allowed tools
       |                              |
       | direct answer                | structured tool call
       v                              v
Response streams to chat       Schema and policy validation
                                      |
                         +------------+-------------+
                         |                          |
                    invalid/unsafe             valid/allowed
                         |                          |
                  no side effect             governed execution
                                                    |
                                  receipt/events return to the model
                                                    |
                                          model explains the result
```

The dispatcher remains an execution capability. It does not sit in front of Thomas
and classify prose. Thomas may call `send_task` when governed background execution
is useful; otherwise Thomas replies, reasons, or uses another allowed tool inline.

## The Hard Boundary

Only either of these may start a semantic action:

1. a valid structured tool call emitted by the frontier model; or
2. an explicit structured client control defined by the API or UI contract.

Natural-language text is never an executable control plane. Deterministic code must
not use regexes, keywords, embeddings, fuzzy matching, scores, or a second model
classifier to decide or override:

- reply versus dispatch;
- which specialist, skill, mode, surface, or workspace should run;
- how many tasks or workers to create;
- whether a turn continues an earlier artifact or targets the live project;
- whether to cancel, update, monitor, or otherwise mutate a task;
- whether assistant prose should be treated as a hidden tool call.

This applies on both sides of the frontier-model call. There is no pre-model
auto-launch, no reclassification of the model's structured choice, and no
post-response prose scanner that creates side effects.

There is also no local prompt-content auto-reject. Thomas does not regex-scan a
natural-language turn, label it suspicious, and block it before GPT-5.6 sees it.
Provider policy governs model safety. Local authorization applies to a concrete
structured action after the model chooses that action.

If a structured call is absent, malformed, unavailable, or rejected, the runtime
must not pretend an action happened. Thomas can explain the limitation or choose a
different valid action on a subsequent model pass.

## What Deterministic Code Still Owns

The no-classifier rule is about semantic intent, not about removing deterministic
engineering. Runtime code should still:

- validate tool names, JSON schemas, enums, IDs, and required fields;
- enforce authorization, autonomy, risk, privacy, path, URL, and secret policies;
- clamp budgets, timeouts, concurrency, and other resource limits;
- veto unsafe, unauthorized, or impossible calls;
- execute an accepted call exactly once;
- verify artifacts and attach execution receipts;
- parse literal protocol fields and explicit UI/API controls;
- preserve user-visible honesty when execution fails or remains in progress.

These checks may reject or narrow a call. They may not infer a different semantic
intent, promote prose into a call, select a replacement specialist or surface, or
silently rewrite the task into something the user did not request.

Regex remains appropriate for schema, path, URL, protocol, redaction, and artifact
verification. It is not appropriate for deciding what a user meant or whether the
user's natural-language turn may reach the model.

## Structured Dispatch Contract

`send_task` is the model-facing bridge to governed background work. Its structured
payload owns the dispatch decision and execution shape. The runtime validates the
payload and forwards accepted fields; it does not rediscover them from the prompt.

Representative fields include:

| Field | Ownership |
|---|---|
| `title` | Model supplies a concise user-visible task label. |
| `instructions` | Model supplies the resolved task brief, including relevant conversational context. |
| `surface` | Model explicitly selects an allowed presentation surface. |
| `specialist` | Model explicitly selects an allowed specialist capability. |
| `workspace` | Model explicitly selects an allowed workspace target. |

The schema may define safe defaults for omitted optional fields. Defaults must be
literal contract defaults, not conclusions inferred from prose. Invalid enum values
fail closed or normalize to the documented safe default; they are never replaced by
keyword guessing.

The model-resolved `instructions` field is authoritative. In a follow-up such as
"I do not care, you pick," replacing those instructions with only the latest user
sentence discards the model's understanding and can produce an unrelated artifact.
The dispatcher must preserve the structured brief it was given.

## Skills

Skills follow the same ownership rule. Thomas may inspect the skills available in
the current environment and use a skill through a structured capability. Runtime
policy may filter skills by availability, trust, risk, and permissions.

An exact literal `$skill-name` invocation or a pinned skill is an explicit control
and may be honored directly. Ordinary prose must not be tokenized or keyword-ranked
into a skill before the model reasons about the request.

## Conversation and Follow-Ups

The frontier model receives bounded conversation history so references such as
"use the second option" or "make that a line graph" can be resolved organically.
Deterministic code may trim history by age, size, or privacy policy, but it must not
classify a follow-up and then substitute a detached sentence for the model's
resolved structured brief.

Transcript context is evidence for the model and worker, not a source of hidden
side effects. A worker receives the structured task plus bounded transcript context;
the structured task remains the controlling instruction.

## Governed Execution and Events

Once a valid `send_task` call is accepted, the dispatcher can create a task, select
the explicitly requested governed lane, and emit lifecycle events. Existing event
names such as `task_dispatched`, `task_claimed`, `task_progress`, `task_complete`,
`task_failed`, and `task_blocked` describe execution state; they are not evidence
that a prose classifier is permitted.

Execution receipts flow back to the model. Thomas should distinguish requested,
running, blocked, failed, and verified-complete states and must not claim completion
before evidence exists.

## Failure Behavior

- A malformed or unauthorized structured call has no side effect.
- A dispatch failure is reported honestly to the model; prose is not rescanned for
  another implicit attempt.
- If a tool is unavailable, it is not offered, and text that resembles its name is
  still ordinary text.
- A missing model call never triggers a background task, cancellation, update, or
  skill selection.

## Explicit Client Controls

Typed UI/API controls may request a defined action without natural-language intent
inference. Examples include a literal mode selector, an explicit task ID plus cancel
action, or a test-only force-inline flag. Their schemas must remain explicit and
auditable. A free-form text box labelled as a control is still natural language and
must go through the model.

## Relationship to Worker Systems

Thomas has multiple execution engines, including workboard workers and the
in-process swarm. The frontier model may select an exposed engine only through a
structured capability. The existence of an engine never authorizes a route-level
classifier to choose it from prose.

## Contributor Checklist

Before changing chat orchestration, verify all of the following:

1. The natural-language turn reaches the frontier model before any semantic side
   effect begins.
2. Every dispatch, skill selection, task update, cancellation, and prose-level tool
   action is backed by a structured model call or explicit structured client control.
3. No local prompt-content classifier rejects the turn before the frontier model.
4. Runtime code validates and governs the call without reclassifying its meaning.
5. Structured fields survive the bridge into execution without being replaced by a
   detached latest message.
6. Similar words in ordinary user or assistant prose create no side effect.
7. Tests target semantic ownership directly and do not ban regex used for typed
   validation, parsing, redaction, or artifact verification.

For response generation and tool-call execution, start in the agent loop and the
reasoning specialist. For task execution, start at the structured `send_task`
callback and its governed dispatcher bridge. Do not add a new natural-language
classifier in either location.
