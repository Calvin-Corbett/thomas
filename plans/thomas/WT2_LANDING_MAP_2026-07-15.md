# wt2 Landing Map (2026-07-15)

Landing the unified Chat/Code/Work shell: branch `codex/unified-chat-code-work-clean-20260715`
(wt2 = C:/Users/corbe/tmp/thomas_unified_chat_code_work_clean_20260715, ~43.7k lines, 17 commits,
sole Work-tab implementation) onto dev. Source: 4-surveyor read-only sweep + synthesis
(wf_3ecf5e9c-719). Owner: claude (coordinator). Codex executes Phase 1 in wt2.

## Coordinator decisions (defaults under Calvin fast-mode; flag objections on the board)

- D-wt2-1: `_model_runtime_receipt` chunk in routes/chat_v2.py (~123-171, 633-643) is COMMITTED —
  it exists in no commit anywhere; losing it is not acceptable.
- D-wt2-2: TWO squash PRs — (1) mechanical virtual-office split (437f1962 content, ~9k move-only
  lines) at 0.17.1, (2) feature payload at 0.17.2. Halves review blast radius, keeps the move-only
  refactor out of the feature diff.
- D-wt2-3: Patch-level numbering accepted now; 0.18.0 is reserved for the formal public release tag.
- D-wt2-4: GitHub API/web squash-merge signature is acceptable (signed-commits-check runs only on
  pull_request events over BASE..HEAD branch commits; branch protection's required-signatures
  accepts GitHub's web-flow key on the squash commit — verified by PR 102 landing green).
- D-wt2-5: Keep the branch as an unmerged archival ref after landing (bisect forensics of the squash).
- D-wt2-6: Rubric truth = CAPABILITY_RUBRIC.json, 14 families x 4 tiers = 74 checks. Any checklist
  saying "61 rows" is wrong; fix on contact.
- D-wt2-7: PR 102 landed first (dev=4e6e9923, 0.17.0). wt2 rebases on top; 021/022 virtual-office
  JS untouched by PR 102 (only referenced in _architecture.py exemptions), so the split rebases clean —
  still pre-check at STEP 6.
- FLAG for Calvin (default yes): thomas.toml bumps openai_codex default model gpt-5.5 -> gpt-5.6-sol.

## Phase 1 — codex, inside wt2 (after current parity-blockers unit completes)

1. STOP the wt2 server first: PID 3216 (`python -m thomas serve --port 8908`, cwd=wt2). The
   Workspace Sync Engine reads THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED once at boot
   (workspace_sync_engine.py:254) and auto-commits+pushes on idle (it minted junk commit 8b94855e).
   After stopping: export THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED=0 and
   THOMAS_WORKSPACE_SYNC_AUTO_PUSH=0 in every future launch env.
2. Commit wt2's working tree as 3 tidy commits (grouping is for review; squash erases them):
   a. junk deletions: cleaned_data.csv, conflict_report.md, grounded_report.md (makes the squash junk-free);
   b. the ~24 WIP product/test files for HSK-20260715-162021 + probe-harness import wiring that
      makes 8b94855e's two auto-synced test files live;
   c. evidence set ATOMICALLY (latest_evidence.jsonl, latest_scorecard.json, GAP_LEDGER.md,
      latest_run.json — provenance-hashed, never hand-merged) + WORKBOARD/CHANGELOG doc updates.
3. Commit the orphaned `_model_runtime_receipt` + model_runtime SSE emit (D-wt2-1).
4. Fold in the landing salvage:
   a. wt3's six test_root_chat_* functions (tests/test_chat_canvas_live_preview.py lines 36-133 in
      C:/Users/corbe/tmp/thomas_unified_chat_fix_20260714) appended into wt2's copy — preserve wt2's
      existing streaming test, cherry-pick the six functions only, CRLF-normalize;
   b. forge branch one-line payload fix `model: state.modelId` (db512f16) into wt2 chat.html send()
      — wt2 still carries dev's `model: state.profile` bug.
5. Post state=open on the board: "wt2 Phase 1 complete" with commit shas. Then proceed to your next
   queued unit (coherence rebase+land) — do not wait.

## Phase 2 — claude (after Phase 1 handoff)

6. Version retarget 0.18.0 -> 0.17.1/0.17.2 (pyproject, __init__, CHANGELOG heading, pyproject
   checkpoint comment) — protected, one Calvin tap batches all protected diffs.
7. Rebase/rebuild onto dev tip. Given squash-land, fresh-branch-one-diff per PR is acceptable
   (mechanical split PR first, features second).
8. Junk verification on final tree: `git ls-files | grep -Ei 'cleaned_data.csv|conflict_report.md|grounded_report.md'`
   empty; CSV-injection marker `=HYPERLINK("https://evil.test"` only inside intentional test fixtures.
9. Local gate rehearsal: gates-required set, release_update, protected_files, parity suite (74 checks),
   six salvaged root-chat tests against the rebased chat.html.
10. Protected-file checklist surfaced in PR body: pyproject (version + reportlab>=4.0/openpyxl>=3.1
    extras), thomas.toml (gpt-5.6-sol), _architecture.py (new `work` module + server/forge deps),
    __init__ version. Calvin taps via commit_guarded.
11. PRs to dev with auto-merge; PR body carries the 16-checkpoint per-area map (chat/canvas, code,
    work, virtual-office split, agent runtime, services, docs). Post-land: junk absent, version right,
    gates green, six tests green; delete wt1/wt3 worktrees (nothing unique remains after Phase 1);
    keep wt2 branch as archival ref.

## Salvage verdicts (from cross-diff survey)

- KEEP in landing: wt2 dirty tree (see Phase 1), _model_runtime_receipt, wt3's six tests, forge payload fix.
- KEEP as follow-up P2 units: forge 'Auto' model-menu entry merged into wt2's renderModelMenu (keep
  wt2's persistence + 'GPT-5.6 Sol' display); forge Evolve spectator pane (backend evolve_loop_routes
  lands nearly clean; evolve.py integration RE-APPLIED SEMANTICALLY onto the post-split module layout —
  budget as re-implementation); sidebar/composer drag grips (Calvin's explicit ask); Ctrl/Cmd+K palette;
  favicon route.
- DROP: all wt1 residue (~397 lines: formatting noise + pre-evolution variants); wt3 residue except the
  six tests; forge Code-lane UI (ONE Code client: unified_code_mode.js); forge native settings pane
  (wt2's /settings?embed=1 iframe wins); tool_extensions.py line-ending churn; wt1/wt3 WORKBOARD residue.

## chat.html rule (binding)

wt2's unified-shell chat.html is canonical, landing unchanged except the payload fix. The forge-tab
branch is NEVER merged as a branch; its work is re-expressed inside the wt2 shell in the staged P2
units (its additions are hidden overlays + end-of-body IIFEs that don't restructure the chat column).
Porting rules: forge IIFEs become external js files per wt2 convention; add seams (window.showChat
extension, window.applyTheme, openWorkspace routing); no canned-demo chat.html variant may ever land.

## Known follow-ups filed

- Sync-engine porcelain path-mangling bug (workspace_sync_engine.py:828-831 strip vs :537-549 slice).
- .gitignore addition for probe artifacts (protected file — own reviewed change).
- evolve_corpus lockfile drift (protected dir — needs tap; pre-existing test failure).
- Landing Lane: release_update to land-time, judge-file protection (gates.yml, allowed_signers),
  breakglass-trailer audit binding, H journal separation (this board-fragmentation incident is exhibit A).
