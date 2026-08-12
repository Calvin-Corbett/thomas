# Parallel Code Worker UI Comparison

Created: 2026-06-28

Source ranking: `plans/thomas/AGENTIC_AI_FEATURE_RANKINGS.md` item 17,
`Parallel Code Worktree Agent UI`.

External reference checked: `https://github.com/johannesjo/parallel-code`
README on 2026-06-28.

## Purpose

Compare Parallel Code's worker/worktree user interface model against Thomas's
native orchestration direction and portal status needs. This is a planning
artifact only. It does not change Thomas runtime behavior.

Parallel Code is useful to Thomas because it treats parallel coding agents as
visible work units: each task has an isolated branch/worktree, a live agent
session, a diff review surface, and a merge action. Thomas needs a similar
operator experience, but Thomas cannot copy the flow directly because Thomas
already has stronger local semantics: workboard claims, agent messages,
commit gates, protected-file rules, release metadata rules, and promotion
approval boundaries.

## Parallel Code Flow Dimensions

| Dimension | Parallel Code-style flow | Thomas implication |
| --- | --- | --- |
| Task creation | Operator creates a task from the UI. | Portal should create or import a Thomas task with an explicit owner, scope, and source prompt. |
| Isolation | New branch and git worktree per task. | Thomas can use worktrees for higher-risk or broad slices, but native orchestration may also run inside one shared checkout with strict claims. The UI must show which isolation mode is active. |
| Agent launch | Spawn Claude Code, Codex, Gemini, Copilot, or another CLI in the task worktree. | Thomas should surface the actual worker identity, launch command class, allowed tools, and current claim scope. |
| Session view | Tiled overview plus focused single-task view. | Thomas portal should have both an overview dashboard and a focused run page with transcript/status/diff/checks. |
| Progress timeline | Step tracking panel records agent progress. | Thomas needs a timeline sourced from workboard claims, messages, commit-helper events, verification commands, and worker status updates. |
| Diff review | Changed-files panel, inline comments, and per-commit navigation. | Thomas should review only the worker-owned diff by default and flag unrelated dirty files separately. |
| Merge action | Merge winning branch back to main from the sidebar. | Thomas must route merges through `scripts/crew/brief/commit.py`, protected-file gates, release metadata gates, and explicit approval when required. |
| CI/check watcher | PR CI status watcher reports settled checks. | Thomas portal needs local verification state first, then optional GitHub/CI state when a branch or PR exists. |
| Existing worktree import | Bring existing worktrees into the UI. | Thomas should import visible worker threads, active folders, workboard claims, and already-created worktrees into one status model. |
| Sandboxing | Optional project Dockerfile isolation per task. | Thomas should expose whether the worker is in shared checkout, linked worktree, container, or self-evolve green/blue sandbox. |

## Thomas Native Orchestration Needs

Thomas-native orchestration should treat the workboard as the authoritative
coordination ledger. A worker UI that only shows branches and diffs would hide
the state Thomas depends on to avoid corrupting shared work.

Minimum native concepts the portal must preserve:

- Worker identity: stable agent id, visible thread id if any, role, parent,
  task id, current branch, current checkout path, and launch source.
- Claimed scope: exact paths claimed via `scripts/crew/workboard/claim.py`,
  with active/released/failed state and dirty-claim override reasons.
- Dirty baseline: files dirty before the worker started, especially shared
  coordination files such as `plans/thomas/WORKBOARD.md`.
- Worker-owned diff: files created or modified by the worker after claim.
- Unowned dirty diff: files outside the claim, shown as preserved state rather
  than reviewable worker output.
- Message state: current inbox items, coordination blockers, approvals, stale
  peer messages, and acknowledged decisions.
- Verification state: commands run, exit codes, short results, and whether a
  command was skipped because the slice was docs-only.
- Commit gate state: dry-run result from `scripts/crew/brief/commit.py`,
  selected include paths, detected blockers, final commit SHA if landed.
- Release state: claim release result, residual dirty files, and whether any
  approval-required gate remains.

## Workboard And Claim Preservation

The portal must make it difficult for a worker UI to blur ownership. Thomas
workers often share one dirty checkout, so every task view should separate:

- Baseline dirty files captured before claim.
- Claim helper writes to `plans/thomas/WORKBOARD.md`.
- New or modified files inside the claimed scope.
- New or modified files outside the claimed scope.
- Commit-helper selected files versus ignored files.

For shared-checkout runs, the portal should default to a "preserve unrelated
dirty files" mode. The worker diff panel should not stage or revert files
outside the active claim unless a human explicitly expands scope.

For worktree-backed runs, the portal should still record the workboard claim in
the parent repo and should show the linked worktree path, base branch, task
branch, and merge target. Worktree isolation reduces file conflict risk; it
does not replace claim discipline.

## Diff Review And Status Timeline

Thomas should combine Parallel Code's diff-first ergonomics with a stronger
status timeline. A useful run page would have:

1. Header: task title, agent id, claim scope, checkout path, branch, isolation
   mode, and current status.
2. Timeline: claimed, edited, verified, dry-run gated, committed, released, or
   blocked.
3. Diff review: claimed files first, unclaimed dirty files in a separate
   preserved-state section.
4. Messages: approvals and blockers relevant to this worker, with stale
   unrelated messages collapsed.
5. Verification: focused command list with result badges and output summaries.
6. Commit gate: dry-run include list, blocker class, final commit command, and
   commit SHA.
7. Release: claim release result and post-release active-claim check.

The status model should be append-only for auditability. Operators need to see
when a worker was blocked by policy rather than infer it from a missing commit.

## Merge And Verification Gates

Parallel Code's "merge the wins" action maps to a stricter Thomas sequence:

1. Confirm branch and checkout are expected.
2. Confirm claim is active and scoped to the intended paths.
3. Run focused verification appropriate to the changed file type.
4. Run `python scripts/crew/brief/commit.py --dry-run --json --include <paths>`.
5. Stop if the helper selects files outside the claim or reports protected,
   release, branch-race, or claim-scope blockers.
6. Commit through `scripts/crew/brief/commit.py` with a `Thomas-Agent` trailer.
7. Release the claim and verify no active claim remains for the worker.
8. Leave unrelated dirty files untouched and visible in final status.

The portal should not offer a generic "merge" button for Thomas-owned work
until the dry-run gate is green. The button should instead display the next
required action: verify, fix scope, request approval, commit, or release.

## Gaps To Resolve Before Implementation

- Define the canonical portal status schema for a worker run.
- Decide whether shared-checkout runs and worktree-backed runs use the same
  UI model with different isolation badges, or separate pages.
- Decide how visible Codex threads map to Thomas worker records.
- Decide how stale cross-lane message noise is filtered without hiding true
  blockers.
- Decide whether worktree import is read-only at first or can attach a claim.
- Decide where local command output summaries are stored for restart recovery.
- Decide which commit-gate blocker classes need human-only approval surfaces.
- Decide how portal status handles workers that finish without a commit
  because the slice is planning-only or blocked by policy.

## Minimum Local UI/Status Fixture Shape

A future implementation can start with this fixture shape before wiring live
routes:

```json
{
  "run_id": "parallel-code-worker-ui-comparison",
  "task": {
    "title": "Compare Parallel Code worker UI to Thomas orchestration",
    "source": "AGENTIC_AI_FEATURE_RANKINGS.md#17",
    "rank_score": 89
  },
  "worker": {
    "agent": "codex-parallel-code-worker-ui",
    "thread_id": null,
    "role": "solo",
    "checkout": "C:/Users/corbe/Thomas",
    "branch": "dev",
    "isolation_mode": "shared-checkout"
  },
  "claim": {
    "scope": ["plans/thomas/ui/PARALLEL_CODE_WORKER_UI_COMPARISON.md"],
    "state": "active",
    "dirty_claim_reason": "Existing unrelated dirty files preserved"
  },
  "baseline_dirty_files": [
    "plans/thomas/WORKBOARD.md",
    "_codex_rundown.md"
  ],
  "owned_files": [
    "plans/thomas/ui/PARALLEL_CODE_WORKER_UI_COMPARISON.md"
  ],
  "unowned_dirty_files": [
    "plans/thomas/WORKBOARD.md",
    "_codex_rundown.md"
  ],
  "timeline": [
    {"state": "claimed", "at": "2026-06-28T00:00:00Z"},
    {"state": "edited", "at": "2026-06-28T00:00:00Z"},
    {"state": "verified", "at": "2026-06-28T00:00:00Z"},
    {"state": "commit_dry_run_green", "at": "2026-06-28T00:00:00Z"},
    {"state": "committed", "at": "2026-06-28T00:00:00Z"},
    {"state": "claim_released", "at": "2026-06-28T00:00:00Z"}
  ],
  "verification": [
    {
      "command": "git diff --check -- plans/thomas/ui/PARALLEL_CODE_WORKER_UI_COMPARISON.md",
      "result": "passed"
    }
  ],
  "commit_gate": {
    "dry_run_command": "python scripts/crew/brief/commit.py --dry-run --json --include plans/thomas/ui/PARALLEL_CODE_WORKER_UI_COMPARISON.md",
    "selected_files": ["plans/thomas/ui/PARALLEL_CODE_WORKER_UI_COMPARISON.md"],
    "blocker": null
  },
  "release": {
    "claim_released": true,
    "active_claim_count_for_agent": 0,
    "preserved_dirty_files": [
      "plans/thomas/WORKBOARD.md",
      "_codex_rundown.md"
    ]
  }
}
```

## Acceptance Checklist For Future Implementation

- The portal can show all active Thomas workers with task, agent, branch,
  checkout path, isolation mode, and current claim scope.
- A worker run page separates baseline dirty files, worker-owned files, and
  unowned dirty files.
- The diff viewer defaults to claimed files and visibly blocks staging or
  reverting files outside the claim.
- The timeline records claim, edit, verification, commit dry-run, commit,
  release, and blocker events.
- Verification commands and concise results are visible without opening raw
  transcripts.
- Commit dry-run output is represented as structured state, including selected
  files and blocker class.
- The UI has no enabled commit or merge action when dry-run selected files
  exceed the active claim.
- Worktree-backed runs show base branch, task branch, worktree path, and merge
  target while still showing workboard claim state.
- Shared-checkout runs show a stronger dirty-baseline warning than worktree
  runs.
- Stale unrelated coordination messages are collapsed, but direct blockers and
  approvals remain prominent.
- Claim release is a first-class final step, not a footnote in the transcript.
- Final run status includes commit SHA, files changed, verification summary,
  claim release confirmation, preserved dirty files, and residual blockers.
