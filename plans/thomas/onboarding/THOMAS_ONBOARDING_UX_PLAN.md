# Thomas Onboarding UX + Implementation Plan

## 1. Objective

Design and ship a first-run experience where a user can:

1. Go to the Thomas website.
2. Click Download.
3. Run a simple installer wizard.
4. Launch Thomas.
5. Complete Easy Setup (ChatGPT/Codex login or manual/local connection).
6. Approve required dependency downloads.
7. Finish personalization in chat so Thomas is fully usable immediately.

The key product promise is: **Thomas becomes useful in minutes with minimal technical friction.**

## 2. Product Principles

1. Fast path first: every screen should support the shortest successful route.
2. Clear confidence: always show what Thomas is doing and why.
3. Explicit permissions: any downloads, installs, and network use require clear user approval.
4. Recoverable errors: every failure state offers next actions.
5. Progressive complexity: basic users get defaults; advanced users can tune later.

## 3. End-to-End User Journey

## 3.1 Website to Download

1. Landing page primary CTA: `Download Thomas`.
2. Platform-aware binaries: auto-detect OS, allow manual override.
3. Copy near CTA:
   - "Install in under 2 minutes."
   - "You can connect with ChatGPT/Codex, API key, or local Ollama."
4. Download page includes:
   - file name/version/hash
   - release channel (stable/beta)
   - trust indicators (signed installer, checksum link, changelog link)

## 3.2 Installer Wizard (Desktop)

1. Welcome step:
   - concise value statement
   - install location choice
2. Permissions step:
   - explain requested permissions (network, local storage, optional startup behavior)
3. Optional components step:
   - desktop shortcut
   - auto-update channel
4. Install progress step:
   - deterministic progress text and fallback messages
5. Complete step:
   - `Launch Thomas now` checked by default

## 3.3 First Launch: Easy Setup Modal

1. Step 1 - Choose connection path
   - ChatGPT/Codex (recommended when available)
   - Manual API key
   - Local Ollama
2. Step 2 - Connect and test
   - run live checks
   - show specific remediation if check fails
3. Step 3 - Dependency approvals
   - present required downloads with reason
   - support approve-all, review-details, skip-for-now
4. Step 4 - Brain ready
   - summarize verified connection + dependency status
   - transition to in-chat personalization interview

## 3.4 In-Chat Personalization

1. Start prompt: "Ready to personalize Thomas now?"
2. Chip-based quick answers for:
   - technical experience
   - personality/tone
   - autonomy level
   - cost vs quality
   - memory behavior
   - workflow mode
   - default toggle bundle
3. User can skip interview and finish with safe defaults.
4. Final confirmation:
   - show summary choices
   - finish setup and persist defaults

## 4. State Model and Persistence

Persist onboarding in preferences with fields:

1. `setup_completed`
2. `version`
3. `completed_at`
4. `dismissed_at`
5. `current_step`
6. `connection_method`
7. `dependency_plan`
8. `answers`

Behavior requirements:

1. Nullable clears supported for string/object fields.
2. Dismiss cooldown prevents aggressive re-open loops.
3. Step restore allows reopening where user left off.

## 5. API/Service Contract

Core backend capabilities required:

1. `GET /api/setup/bootstrap`
   - return quick-start recommendation and dependency status
2. `POST /api/setup/repair`
   - run targeted remediation by setup step
3. `POST /api/onboarding/telemetry`
   - accept client event + payload
4. `GET /api/onboarding/outcomes/gate`
   - evaluate onboarding KPI thresholds (completion, recovery, median time-to-ready)
   - support strict mode for rollout blocking
5. Preferences patch flow (`/api/preferences`)
   - store onboarding state
   - support partial patches and explicit clears
6. Connection validators
   - Codex status/login/models/profile validation
   - manual profile key save + validation
   - local profile validation

## 6. Dependency Approval UX Spec

Each dependency card should include:

1. Name
2. Why it is needed
3. Size estimate (if known)
4. Source/trust link
5. Current status (`ready`, `missing`, `pending`)
6. Action affordance

User actions:

1. Approve all downloads.
2. Review details before approval.
3. Skip for now (with warning on limited functionality).

Post-action behavior:

1. Refresh dependency state.
2. Show what changed.
3. Keep user unblocked with safe fallback where possible.

## 7. Copy and Tone Guidelines

1. Use plain language over technical jargon.
2. Avoid dead-end errors; always include "Next step".
3. Confirm success explicitly after each phase.
4. Keep trust-sensitive wording clear for any install/download actions.

Suggested copy:

1. "Thomas will finish setup for you after this check."
2. "Approve required downloads so core tools can run."
3. "Setup complete. Thomas now has the context to continue in chat."

## 8. Telemetry and Funnel Metrics

Track onboarding funnel stages:

1. wizard opened
2. path selected
3. connection test passed/failed
4. dependencies approved/skipped
5. interview started/completed/skipped
6. onboarding completed

Quality metrics:

1. first-run completion rate
2. median time to completion
3. drop-off by step
4. failure reasons by provider path
5. % users requiring repair flow

## 9. Testing Strategy

## 9.1 Automated

1. Unit tests for onboarding patch merge semantics.
2. API auth tests for remote mode onboarding telemetry.
3. UI smoke checks for onboarding wizard controls and slash command path.
4. End-to-end scenario tests for:
   - Codex path success
   - manual key path success/failure
   - local path success/failure
   - dependency approve and skip branches
   - interview complete and skip branches

## 9.2 Manual QA Matrix

1. Fresh install with no prior preferences.
2. Returning user with partially completed onboarding.
3. Offline/no-network first launch.
4. Missing dependency remediation flow.
5. Invalid API key handling and retry.
6. Accessibility pass:
   - keyboard-only navigation
   - focus order and visible focus
   - screen-reader labels for wizard controls

## 10. Rollout Plan

## Phase 1: Core onboarding path (shipped)

1. Settings entry point + modal wizard.
2. Connection path selection and validation.
3. Dependency approval step.
4. In-chat interview and preference persistence.
5. Onboarding telemetry endpoint and events.

## Phase 2: Distribution polish

1. Website download funnel updates.
2. Installer copy and permission UX alignment with onboarding language.
3. Signed binary + checksum UX hardening.

## Phase 3: Reliability and optimization

1. Guided repair improvements per provider.
2. More granular dependency provenance metadata.
3. Funnel-driven UX tuning based on telemetry.

## 11. Definition of Done

Feature is complete when:

1. A new user can go from download to productive chat in one uninterrupted flow.
2. Every critical setup action has deterministic success/error feedback.
3. Dependency downloads are explicit and user-approved.
4. Onboarding completion persists and suppresses unnecessary prompts.
5. Telemetry can diagnose conversion and failure points.
6. Full automated test suite is green.
