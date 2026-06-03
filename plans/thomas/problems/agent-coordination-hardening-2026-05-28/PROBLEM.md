# Task Problem Record: agent-coordination-hardening-2026-05-28

- task_id: `agent-coordination-hardening-2026-05-28`
- owner: `claude`
- status: `in_progress`
- scope: `scripts,thomas,tests,plans`
- summary: multi-agent Praxis red/blue hardening — drive gate/rule fixes until known bypasses fail, under enforced cross-agent coordination
- created_at_utc: `2026-05-28T00:00:00+00:00`
- last_synced_at_utc: `2026-06-03T00:00:00+00:00`

## Problem Statement

- With multiple agents (claude, codex) editing the same repo, the Praxis safety
  gates and rules-of-road must hold against an agent that actively probes for
  bypasses, and concurrent agents must coordinate (claims + inbox) rather than
  clobber each other's in-flight work.

## Evidence

- Agent message traffic in `plans/thomas/WORKBOARD.md` (codex red-team findings:
  shell-write invisibility in `rules_of_road`, failed-pytest-as-success,
  echo-spoofed skill probes, local protected-file self-approval, guard-disable
  envs, high-risk skill explicit-mention approval).
- Companion charter under `praxis-unbypassable-2026-05-29`.

## Root Cause Hypothesis

- Several gates classified intent by tool name or command text rather than by
  verified effect/outcome, and some honored unauthenticated env toggles — so a
  motivated agent could present a passing surface without doing the safe thing.

## Fix Plan

1. Codex attacks (read-only / sentinel repros); claude fixes under the active
   claim; codex re-attacks the fixed surface.
2. Fail closed on unauthenticated disable envs; require native-auth breakglass
   for protected/local self-approval; classify writes/tests by verified effect.
3. Add a regression for every confirmed bypass before closing it.

## Outcome

- Multiple bypasses fixed and regression-pinned across the 2026-05-29..06-03
  hardening line (rules_of_road effect-based classification, breakglass spine,
  enforcement-integrity fail-closed, sanitize_env deny-set). Coordination is now
  scope-aware (commit-master inbox enforcement). In progress: continue closing
  residual fail-open edges as found.
