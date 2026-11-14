### Fixed

- **The check before your card hands in exactly what it checked, and says what it did not run.** An
  independent review of that check found it was not yet trustworthy, and you said "a check I cannot trust is
  worse than none". Each finding had a cause in the code:
  - *The checked patch and the handed-in patch were two separate reads.* The green's processes were ended
    only after the check. One write in between gave `toctou_drive.py` a submission that broke
    `tests/test_adder.py::test_add_makes_a_sum` under a line saying "no failure this change causes".
    `precard.check_for_hand_in` now ends the green's processes first. It keeps the exact patch it checked
    and that patch's sha256, and it reads the green again before handing in. If the hashes differ, the
    change goes back to its team with both hashes named. `green_handoff.settle(patch=...)` hands in the
    checked bytes themselves, both from a Thomas project and from Chat's single worker.
  - *Tests were chosen by file-name stems.* For three changes that picked 748, 365 and 203 files, and the
    cap of 60 then dropped files that really imported the change, including 10 of the 18 files 820602fd
    broke. `proof/selection.py` now chooses by real imports and dotted names, follows helper modules, and
    ranks a changed `conftest.py`'s folder last. The cap is now 120 files, and the card names the files the
    cap left out instead of implying everything ran. All 18 files 820602fd broke are now selected.
  - *Checks had no limit and no deadline.* The step limits added up to about 24,600 s per check. Now one
    check runs at a time (a second hand-in waits its turn, and is never skipped), each has a deadline of
    3,600 s, and no check starts with less than 10 GB free on the drive it copies to. The card then says it
    was not checked and why. Anything a check that died left behind is cleared.
  - *`POST .../hand-in-again` ran the whole check inside the request*, holding the lock send-back shares.
    It now answers 202 at once, the listing says "checking", and a second click or a send-back is refused
    until the hand-in is out.
  - *A base re-run that timed out excused the failure* and the card called it "each confirmed on its own".
    A timed-out re-run on either copy now blocks, and a failure excused only by dev's own run is counted as
    "not settled by a re-run on its own".
  - The ratchet plan (`docs/superpowers/plans/2026-09-24-praxis-ratchet.md`, Tasks 3–4) now calls
    `thomas/server/proof/` instead of writing a second selection and runner.
  - `thomas_project.py` (800 → 703 lines) and `routes/evolve_agent_autopilot.py` (799 → 672) had code moved
    out into `thomas_project_words.py` and `routes/autopilot_messages.py` before anything was added.
