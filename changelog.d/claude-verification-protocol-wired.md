### Fixed

- **The six gates that were supposed to make an agent prove its work now run.**
  The Agent Verification Protocol was written on 2026-03-23 and specified in
  `plans/thomas/verification/AGENT_VERIFICATION_PROTOCOL_PLAN.md`: before an agent
  may commit, it must produce a record showing it ran tests, ran regression tests,
  justified deletions and justified large commits. All six gates were written,
  unit-tested, hash-registered and listed as protected. None of them were ever
  called. For six months nothing checked any of it.

  The record they read had drifted to match. The one in this repo claimed a pass
  from the command `python -c print(123)` with 0 tests run and the regression check
  recorded as `"skipped": true`, dated three months earlier, and every gate that
  read it was dead anyway.

  What changed:
  - `verification_record_gate.py` now refuses a record older than 24h, one whose
    test command names no test runner, one showing 0 passed and 0 failed, and one
    whose regression check was skipped.
  - `create_verification_record.py` no longer writes a pass it did not see:
    `--skip-regression` recorded `passed: true`, so the tool itself produced the
    false receipt.
  - `commit_scope_gate.py` no longer counts files a commit merely moves or removes.
    It exempted renames but not removals, so it hard-blocked cleanup - replaying it
    over 60 commits, the single hard block it produced was the one that removed
    1,584 dead extension listings.
  - `verification_record_gate.py` dropped its private copies of the scope and
    shrinkage checks. They were the cruder ones: the scope copy had no exemptions
    at all, and the shrinkage copy sat behind a 3-code-file threshold, so it never
    saw the single-file gutting it existed to catch.
  - All six gates gained `--repo-root`, the option `monolith_guard.py` already had.
    Without it a gate always judges the checkout it lives in, so it can never be
    aimed at a fixture and never proven to fail - and the enforcement ratchet
    refuses to let an unprovable gate enforce. That missing seam is why these six
    could not have been wired.

  Replayed over the last 60 commits on dev, the wired set stops 6 of them: one real
  catch - a commit that added three modules under `thomas/` with no test - and five
  that ask for one sentence of justification. No hard blocks.
