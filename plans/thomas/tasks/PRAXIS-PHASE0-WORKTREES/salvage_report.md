# Worktree Salvage Report

Run timestamp (UTC): 2026-08-24T16:43:44Z
Tool: `.venv/Scripts/python.exe scripts/forge/worktree_triage.py` (Task 1 output)
Repo root: `C:\Users\corbe\Thomas` (branch `dev`)
Worktrees present at run start: 68 (67 candidates + the main checkout, which the tool always excludes)

## Triage table (BEFORE)

| worktree | branch | dirty | unique commits | last commit | venv-junction | assessment-failed | disposition |
|---|---|---|---|---|---|---|---|
| dlc3 | codex/dead-legacy-phase-c-3a884c61 | 1 | 32 | 2026-07-23 | no | no | needs-review |
| trp | codex/release-preflight-repair-20260723 | 1 | 31 | 2026-07-23 | no | no | needs-review |
| base |  | 10614 | 0 | 2026-08-14 | no | no | needs-review |
| thomas-repair | claude/repair-2026-08-11 | 0 | 0 |  | no | YES | needs-review |
| fin2 |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| fin3 |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| fin4 |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| final |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| full |  | 10741 | 0 | 2026-08-14 | no | no | needs-review |
| thomas-organic-routing-no-regex | codex/organic-routing-no-regex-20260722 | 8 | 28 | 2026-07-23 | YES | no | needs-review |
| thomas-dead-legacy-retirement | codex/dead-legacy-retirement-20260723 | 11 | 30 | 2026-07-23 | no | no | needs-review |
| thomas-installer-hardening | codex/installer-hardening-candidate-2c84f452 | 7 | 34 | 2026-07-23 | no | no | needs-review |
| thomas-installer-hardening-579b3c98 | codex/installer-hardening-candidate-579b3c98 | 4 | 35 | 2026-07-23 | no | no | needs-review |
| thomas-code-gpt-provider-route-579b3c98 | codex/code-gpt-provider-route-579b3c98-20260723 | 39 | 35 | 2026-07-23 | no | no | needs-review |
| thomas-organic-profile-frontier-phaseb | codex/organic-profile-frontier-phaseb-20260723 | 28 | 28 | 2026-07-23 | YES | no | needs-review |
| thomas-unified-permissions-artifact-2c84f452 | codex/unified-permissions-artifact-2c84f452-20260723 | 26 | 34 | 2026-07-23 | no | no | needs-review |
| thomas-unified-permissions-artifact-579b3c98 | codex/unified-permissions-artifact-579b3c98-20260723 | 0 | 35 | 2026-07-23 | no | no | needs-review |
| w426 | codex/privacy-public-release-integration-4e7bce5f | 12 | 30 | 2026-07-23 | no | no | needs-review |
| thomas-public-release-audit | codex/privacy-public-release-audit-20260723 | 8 | 0 | 2026-07-22 | no | no | needs-review |
| thomas-public-release-c679adee | codex/privacy-public-release-c679adee | 1 | 35 | 2026-07-23 | no | no | needs-review |
| thomas-public-release-e6420c41 | codex/privacy-public-release-candidate-e6420c41 | 9 | 28 | 2026-07-23 | no | no | needs-review |
| thomas-release-history | codex/release-history-20260723 | 6 | 0 | 2026-07-22 | no | no | needs-review |
| ci-pr138 |  | 0 | 4 | 2026-08-13 | no | no | needs-review |
| publish | codex/github-issues-2026-08-13 | 50 | 89 | 2026-08-14 | no | no | needs-review |
| unify | integration/unify-2026-08-14 | 2 | 16 | 2026-08-14 | no | no | needs-review |
| wf_1d065ed6-929-1 | worktree-wf_1d065ed6-929-1 | 1 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-10 | worktree-wf_1d065ed6-929-10 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-2 | worktree-wf_1d065ed6-929-2 | 10 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-3 | worktree-wf_1d065ed6-929-3 | 5 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-4 | worktree-wf_1d065ed6-929-4 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-5 | worktree-wf_1d065ed6-929-5 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-6 | worktree-wf_1d065ed6-929-6 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-7 | worktree-wf_1d065ed6-929-7 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-8 | worktree-wf_1d065ed6-929-8 | 1 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-9 | worktree-wf_1d065ed6-929-9 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-1 | worktree-wf_2dec1a77-79e-1 | 8 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-10 | worktree-wf_2dec1a77-79e-10 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-2 | worktree-wf_2dec1a77-79e-2 | 4 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-3 | worktree-wf_2dec1a77-79e-3 | 7 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-4 | worktree-wf_2dec1a77-79e-4 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-5 | worktree-wf_2dec1a77-79e-5 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-6 | worktree-wf_2dec1a77-79e-6 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-7 | worktree-wf_2dec1a77-79e-7 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-8 | worktree-wf_2dec1a77-79e-8 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-9 | worktree-wf_2dec1a77-79e-9 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-1 | worktree-wf_509cec4d-50f-1 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-10 | worktree-wf_509cec4d-50f-10 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-2 | worktree-wf_509cec4d-50f-2 | 5 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-3 | worktree-wf_509cec4d-50f-3 | 9 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-4 | worktree-wf_509cec4d-50f-4 | 4 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-5 | worktree-wf_509cec4d-50f-5 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-6 | worktree-wf_509cec4d-50f-6 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-7 | worktree-wf_509cec4d-50f-7 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-8 | worktree-wf_509cec4d-50f-8 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-9 | worktree-wf_509cec4d-50f-9 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-1 | worktree-wf_8e77dbc2-4d8-1 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-10 | worktree-wf_8e77dbc2-4d8-10 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-2 | worktree-wf_8e77dbc2-4d8-2 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-3 | worktree-wf_8e77dbc2-4d8-3 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-4 | worktree-wf_8e77dbc2-4d8-4 | 5 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-5 | worktree-wf_8e77dbc2-4d8-5 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-6 | worktree-wf_8e77dbc2-4d8-6 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-8 | worktree-wf_8e77dbc2-4d8-8 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-9 | worktree-wf_8e77dbc2-4d8-9 | 2 | 0 | 2026-06-09 | no | no | needs-review |
| thomas-proto | proto/code-activity | 9 | 0 | 2026-08-10 | YES | no | needs-review |
| Thomas-Unified-Test | local/unified-test-2026-08-15 | 3 | 77 | 2026-08-15 | YES | no | needs-review |
| ThomasUnifyRepair | integration/unify-repaired-2026-08-14 | 2 | 77 | 2026-08-15 | no | no | needs-review |

The machine copy of this table is `salvage_report.json` (generated in the same run, `--json` flag).

## REMOVED

**Zero worktrees removed.**

The tool's `removable` disposition requires `dirty == 0 AND unique_commits == 0 AND assessment_failed == false`
(see `scripts/forge/worktree_triage.py`, `triage()`). Of the 67 candidate worktrees in the BEFORE table, **none**
carry that disposition — every row reads `needs-review`. There was no candidate to hand-verify against Hard
Safety Rule (c), so no `git worktree remove` calls were made this pass.

For completeness, the two rows a naive read might mistake for candidates were checked and are not:

- `ci-pr138` — dirty 0, but 4 unique commits ahead of `dev` (not merged into `dev`).
- `thomas-unified-permissions-artifact-579b3c98` — dirty 0, but 35 unique commits ahead of `dev`.

Neither qualifies: "unique commits" here means commits reachable from the worktree's HEAD but not from `dev`.
Zero dirty files does not imply zero risk if the branch itself is not fully contained in `dev`.

## SKIPPED-REFUSED

None. No `git worktree remove` was attempted (no `removable` candidates existed), so git never had the chance
to refuse one.

## NEEDS-REVIEW AWAITING OWNER

Every worktree below stays untouched. Numbers are as read from the BEFORE table above (worktree name / dirty
file count / unique commits ahead of `dev` / last commit date):

| worktree | dirty | unique commits | last commit |
|---|---|---|---|
| dlc3 | 1 | 32 | 2026-07-23 |
| trp | 1 | 31 | 2026-07-23 |
| base | 10614 | 0 | 2026-08-14 |
| thomas-repair | 0 | 0 |  |
| fin2 | 10744 | 0 | 2026-08-14 |
| fin3 | 10744 | 0 | 2026-08-14 |
| fin4 | 10744 | 0 | 2026-08-14 |
| final | 10744 | 0 | 2026-08-14 |
| full | 10741 | 0 | 2026-08-14 |
| thomas-organic-routing-no-regex | 8 | 28 | 2026-07-23 |
| thomas-dead-legacy-retirement | 11 | 30 | 2026-07-23 |
| thomas-installer-hardening | 7 | 34 | 2026-07-23 |
| thomas-installer-hardening-579b3c98 | 4 | 35 | 2026-07-23 |
| thomas-code-gpt-provider-route-579b3c98 | 39 | 35 | 2026-07-23 |
| thomas-organic-profile-frontier-phaseb | 28 | 28 | 2026-07-23 |
| thomas-unified-permissions-artifact-2c84f452 | 26 | 34 | 2026-07-23 |
| thomas-unified-permissions-artifact-579b3c98 | 0 | 35 | 2026-07-23 |
| w426 | 12 | 30 | 2026-07-23 |
| thomas-public-release-audit | 8 | 0 | 2026-07-22 |
| thomas-public-release-c679adee | 1 | 35 | 2026-07-23 |
| thomas-public-release-e6420c41 | 9 | 28 | 2026-07-23 |
| thomas-release-history | 6 | 0 | 2026-07-22 |
| ci-pr138 | 0 | 4 | 2026-08-13 |
| publish | 50 | 89 | 2026-08-14 |
| unify | 2 | 16 | 2026-08-14 |
| wf_1d065ed6-929-1 | 1 | 0 | 2026-07-31 |
| wf_1d065ed6-929-10 | 2 | 0 | 2026-07-31 |
| wf_1d065ed6-929-2 | 10 | 0 | 2026-07-31 |
| wf_1d065ed6-929-3 | 5 | 0 | 2026-07-31 |
| wf_1d065ed6-929-4 | 2 | 0 | 2026-07-31 |
| wf_1d065ed6-929-5 | 2 | 0 | 2026-07-31 |
| wf_1d065ed6-929-6 | 3 | 0 | 2026-07-31 |
| wf_1d065ed6-929-7 | 3 | 0 | 2026-07-31 |
| wf_1d065ed6-929-8 | 1 | 0 | 2026-07-31 |
| wf_1d065ed6-929-9 | 2 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-1 | 8 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-10 | 2 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-2 | 4 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-3 | 7 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-4 | 3 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-5 | 3 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-6 | 2 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-7 | 2 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-8 | 2 | 0 | 2026-07-31 |
| wf_2dec1a77-79e-9 | 2 | 0 | 2026-07-31 |
| wf_509cec4d-50f-1 | 2 | 0 | 2026-07-31 |
| wf_509cec4d-50f-10 | 2 | 0 | 2026-07-31 |
| wf_509cec4d-50f-2 | 5 | 0 | 2026-07-31 |
| wf_509cec4d-50f-3 | 9 | 0 | 2026-07-31 |
| wf_509cec4d-50f-4 | 4 | 0 | 2026-07-31 |
| wf_509cec4d-50f-5 | 2 | 0 | 2026-07-31 |
| wf_509cec4d-50f-6 | 3 | 0 | 2026-07-31 |
| wf_509cec4d-50f-7 | 2 | 0 | 2026-07-31 |
| wf_509cec4d-50f-8 | 2 | 0 | 2026-07-31 |
| wf_509cec4d-50f-9 | 2 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-1 | 2 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-10 | 3 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-2 | 2 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-3 | 2 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-4 | 5 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-5 | 3 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-6 | 2 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-8 | 3 | 0 | 2026-07-31 |
| wf_8e77dbc2-4d8-9 | 2 | 0 | 2026-06-09 |
| thomas-proto | 9 | 0 | 2026-08-10 |
| Thomas-Unified-Test | 3 | 77 | 2026-08-15 |
| ThomasUnifyRepair | 2 | 77 | 2026-08-15 |

66 worktrees remain in this list after prune (the `thomas-repair` row above is pre-prune; see AFTER table).
`base`, `fin2`, `fin3`, `fin4`, `final`, `full` are the six `%TEMP%` worktrees with 10,000+ uncommitted files
named in Task 2's Step 3. `thomas-organic-routing-no-regex`, `thomas-organic-profile-frontier-phaseb`,
`thomas-proto`, and `Thomas-Unified-Test` are the four with `venv-junction: YES` — flagged per Hard Safety
Rule (b), not touched regardless of what their dirty/unique numbers would otherwise imply.

## Prune

`git worktree prune --verbose` reported one prunable entry: `thomas-repair`
(`gitdir file points to non-existent location` — its directory at
`C:\Users\corbe\AppData\Local\Temp\claude\thomas-repair` no longer exists on disk). This is git's own
prunable-detection, not a triage judgment call, and involves no file removal beyond git's worktree
administrative metadata (`.git/worktrees/thomas-repair`). Ran for real; the entry is gone.

## Triage table (AFTER)

Same tool, same repo, run again after `git worktree prune`. 66 rows (67 candidates − the pruned
`thomas-repair` entry). Disposition mix is unchanged: **0 removable, 66 needs-review.**

| worktree | branch | dirty | unique commits | last commit | venv-junction | assessment-failed | disposition |
|---|---|---|---|---|---|---|---|
| dlc3 | codex/dead-legacy-phase-c-3a884c61 | 1 | 32 | 2026-07-23 | no | no | needs-review |
| trp | codex/release-preflight-repair-20260723 | 1 | 31 | 2026-07-23 | no | no | needs-review |
| base |  | 10614 | 0 | 2026-08-14 | no | no | needs-review |
| fin2 |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| fin3 |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| fin4 |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| final |  | 10744 | 0 | 2026-08-14 | no | no | needs-review |
| full |  | 10741 | 0 | 2026-08-14 | no | no | needs-review |
| thomas-organic-routing-no-regex | codex/organic-routing-no-regex-20260722 | 8 | 28 | 2026-07-23 | YES | no | needs-review |
| thomas-dead-legacy-retirement | codex/dead-legacy-retirement-20260723 | 11 | 30 | 2026-07-23 | no | no | needs-review |
| thomas-installer-hardening | codex/installer-hardening-candidate-2c84f452 | 7 | 34 | 2026-07-23 | no | no | needs-review |
| thomas-installer-hardening-579b3c98 | codex/installer-hardening-candidate-579b3c98 | 4 | 35 | 2026-07-23 | no | no | needs-review |
| thomas-code-gpt-provider-route-579b3c98 | codex/code-gpt-provider-route-579b3c98-20260723 | 39 | 35 | 2026-07-23 | no | no | needs-review |
| thomas-organic-profile-frontier-phaseb | codex/organic-profile-frontier-phaseb-20260723 | 28 | 28 | 2026-07-23 | YES | no | needs-review |
| thomas-unified-permissions-artifact-2c84f452 | codex/unified-permissions-artifact-2c84f452-20260723 | 26 | 34 | 2026-07-23 | no | no | needs-review |
| thomas-unified-permissions-artifact-579b3c98 | codex/unified-permissions-artifact-579b3c98-20260723 | 0 | 35 | 2026-07-23 | no | no | needs-review |
| w426 | codex/privacy-public-release-integration-4e7bce5f | 12 | 30 | 2026-07-23 | no | no | needs-review |
| thomas-public-release-audit | codex/privacy-public-release-audit-20260723 | 8 | 0 | 2026-07-22 | no | no | needs-review |
| thomas-public-release-c679adee | codex/privacy-public-release-c679adee | 1 | 35 | 2026-07-23 | no | no | needs-review |
| thomas-public-release-e6420c41 | codex/privacy-public-release-candidate-e6420c41 | 9 | 28 | 2026-07-23 | no | no | needs-review |
| thomas-release-history | codex/release-history-20260723 | 6 | 0 | 2026-07-22 | no | no | needs-review |
| ci-pr138 |  | 0 | 4 | 2026-08-13 | no | no | needs-review |
| publish | codex/github-issues-2026-08-13 | 50 | 89 | 2026-08-14 | no | no | needs-review |
| unify | integration/unify-2026-08-14 | 2 | 16 | 2026-08-14 | no | no | needs-review |
| wf_1d065ed6-929-1 | worktree-wf_1d065ed6-929-1 | 1 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-10 | worktree-wf_1d065ed6-929-10 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-2 | worktree-wf_1d065ed6-929-2 | 10 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-3 | worktree-wf_1d065ed6-929-3 | 5 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-4 | worktree-wf_1d065ed6-929-4 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-5 | worktree-wf_1d065ed6-929-5 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-6 | worktree-wf_1d065ed6-929-6 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-7 | worktree-wf_1d065ed6-929-7 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-8 | worktree-wf_1d065ed6-929-8 | 1 | 0 | 2026-07-31 | no | no | needs-review |
| wf_1d065ed6-929-9 | worktree-wf_1d065ed6-929-9 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-1 | worktree-wf_2dec1a77-79e-1 | 8 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-10 | worktree-wf_2dec1a77-79e-10 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-2 | worktree-wf_2dec1a77-79e-2 | 4 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-3 | worktree-wf_2dec1a77-79e-3 | 7 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-4 | worktree-wf_2dec1a77-79e-4 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-5 | worktree-wf_2dec1a77-79e-5 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-6 | worktree-wf_2dec1a77-79e-6 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-7 | worktree-wf_2dec1a77-79e-7 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-8 | worktree-wf_2dec1a77-79e-8 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_2dec1a77-79e-9 | worktree-wf_2dec1a77-79e-9 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-1 | worktree-wf_509cec4d-50f-1 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-10 | worktree-wf_509cec4d-50f-10 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-2 | worktree-wf_509cec4d-50f-2 | 5 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-3 | worktree-wf_509cec4d-50f-3 | 9 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-4 | worktree-wf_509cec4d-50f-4 | 4 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-5 | worktree-wf_509cec4d-50f-5 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-6 | worktree-wf_509cec4d-50f-6 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-7 | worktree-wf_509cec4d-50f-7 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-8 | worktree-wf_509cec4d-50f-8 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_509cec4d-50f-9 | worktree-wf_509cec4d-50f-9 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-1 | worktree-wf_8e77dbc2-4d8-1 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-10 | worktree-wf_8e77dbc2-4d8-10 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-2 | worktree-wf_8e77dbc2-4d8-2 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-3 | worktree-wf_8e77dbc2-4d8-3 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-4 | worktree-wf_8e77dbc2-4d8-4 | 5 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-5 | worktree-wf_8e77dbc2-4d8-5 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-6 | worktree-wf_8e77dbc2-4d8-6 | 2 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-8 | worktree-wf_8e77dbc2-4d8-8 | 3 | 0 | 2026-07-31 | no | no | needs-review |
| wf_8e77dbc2-4d8-9 | worktree-wf_8e77dbc2-4d8-9 | 2 | 0 | 2026-06-09 | no | no | needs-review |
| thomas-proto | proto/code-activity | 9 | 0 | 2026-08-10 | YES | no | needs-review |
| Thomas-Unified-Test | local/unified-test-2026-08-15 | 3 | 77 | 2026-08-15 | YES | no | needs-review |
| ThomasUnifyRepair | integration/unify-repaired-2026-08-14 | 2 | 77 | 2026-08-15 | no | no | needs-review |

## Delta (BEFORE -> AFTER)

- Worktrees: 68 -> 67 total (67 -> 66 candidates, main checkout untouched throughout).
- Removed via `git worktree remove`: 0.
- Cleaned via `git worktree prune`: 1 (`thomas-repair`, already-deleted directory).
- `removable` disposition count: 0 -> 0 (unchanged; nothing became removable and nothing removable was
  consumed, because there was none to begin with).
- Everything else in the NEEDS-REVIEW AWAITING OWNER list above is exactly as it was before this run.
