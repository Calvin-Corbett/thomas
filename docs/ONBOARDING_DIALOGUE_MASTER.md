# Onboarding Dialogue Master

This document defines the required onboarding dialogue flow for Thomas.

## Goals

- Make first-run setup reliable and fast.
- Support both ChatGPT OAuth (`codex`) and manual API key setup.
- Interview the user and tune default behavior automatically.
- Persist a clear profile so later runs/agents know user preferences.

## Required Flow

1. Connection path selection.
2. Provider connection and live health check.
3. User interview (7 core questions).
4. Summary + apply.

## Dialogue Script

### Step 1: Choose connection path

Prompt:
- "How do you want to connect Thomas?"

Options:
- `ChatGPT OAuth (Codex)`
- `Manual API key`
- `Local Ollama`

### Step 2: Connect provider

Codex path:
- "Connect ChatGPT and verify sign-in status."
- Actions: `Status`, `Connect ChatGPT`.

Manual key path:
- "Choose provider profile and save/test API key."
- Actions: `Connect and Test`, `Get API key`.

Local path:
- "Verify local endpoint is reachable."
- Actions: `Test Local Connection`, `Install Ollama`.

### Step 3: User interview

Questions:
1. Knowledge level: `New`, `Builder`, `Expert`
2. Autonomy preference: `Guided`, `Balanced`, `Aggressive`
3. Cost vs quality: `Low cost`, `Balanced`, `Max quality`
4. Memory policy: `Remember across sessions`, `Only current session`, `Disable memory`
5. Response depth: `Concise`, `Balanced`, `Deep technical`
6. Primary workflow: `Build features`, `Research`, `Ops + reliability`
7. Workflow mode: `Guided workflow`, `Expert bypass`

### Step 4: Apply profile

Prompt:
- "Review and apply your Thomas profile."

Outputs:
- `settings.setupCompleted = true`
- `settings.onboardingAnswers` payload
- `settings.onboardingProfile` payload
- `settings.preferredProfile`
- `settings.autonomyLevel`
- `settings.tokenEconomyLevel`
- `settings.showToolDetails`
- `settings.preferredMode`
- `settings.workflowMode`

## Configuration Mapping

Autonomy level:
- Base from knowledge level: `New -> L1`, `Builder -> L2`, `Expert -> L4`
- Adjust by autonomy preference: `Guided -1`, `Balanced +0`, `Aggressive +1`
- Clamp to `L1..L4`

Token economy:
- `Low cost -> cheap`
- `Balanced -> optimal`
- `Max quality -> max`

Memory:
- `Remember across sessions -> enabled_global=true`
- `Only current session -> enabled_global=false` plus per-thread override where available
- `Disable memory -> enabled_global=false`

Mode:
- `Research -> thinking`
- Otherwise default `auto`

Tool detail visibility:
- Enabled for `Expert`, high autonomy, or `Ops + reliability` workflow.

## Persistence Contract

The wizard must persist both:

- User-facing UI defaults (`saveSetting(...)` keys under `settings`).
- Server preferences (`PATCH /api/preferences`) for autonomy and memory.

Optional enrichment:
- Save onboarding directives into memory pins:
  - `onboarding_profile`
  - `onboarding_directives`

## Non-negotiable UX Rules

- Connection must be tested before apply.
- Failures must show exact remediation text.
- User can skip interview, but setup completion still needs an explicit action.
- Wizard must be re-openable from command palette.
