# Task Problem Record: bible-public-system-2026-05-22

- task_id: `bible-public-system-2026-05-22`
- owner: `unassigned`
- status: `up_for_grabs`
- scope: `docs,scripts`
- summary: public vs local "bible" overlay system — ship an upstream bible while keeping per-install customizations out of the public tree, with health/lint/coverage tooling
- created_at_utc: `2026-05-22T00:00:00+00:00`
- last_synced_at_utc: `2026-06-03T00:00:00+00:00`

## Problem Statement

- The repo "bible" (canonical knowledge index) must be shippable upstream while
  letting each install keep private overlays, and must not silently decay: new
  repo paths need coverage, stale sections need flagging, and structure needs
  linting — without a human babysitting it.

## Evidence

- Bible toolkit under `scripts/bible_*.py` (status, query, diff, lint, freshness,
  coverage, autoupdate, gate, merge) and `docs/THOMAS_BIBLE.md` /
  `THOMAS_BIBLE.local.md` overlay model (`docs/REBRANDING_AND_FORK_MODEL.md`).

## Root Cause Hypothesis

- Without a public/local split + automated freshness/coverage gating, the bible
  drifts: per-install notes leak upstream, or upstream sections go stale and
  uncovered as the code moves.

## Fix Plan

1. Split public (`THOMAS_BIBLE.md`) from gitignored local overlay
   (`THOMAS_BIBLE.local.md`); merge at read time (`bible_merge.py`).
2. Auto-stub new repo paths and bump verification levels from the post-commit
   hook (`bible_autoupdate.py`); flag drift via `bible_status.py` / freshness.
3. Gate commits that add uncovered units (`bible_gate.py`).

## Outcome

- Toolkit and overlay model are in place (see the bible cheat-sheet in
  `START_HERE.md` and `BIBLE_VERIFICATION_LEVELS.md`). Residual: a local lint
  break currently leaves `bible_status` reporting `LINT_BROKEN / 0 sections` on
  this install — worth a follow-up to restore the freshness tracker. Record
  retained for traceability.
