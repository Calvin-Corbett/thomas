### Added

- **Thomas can see what is going wrong with him.** `self.issues` returns his own issue ledger as a work queue: one row per distinct failure, how many times it happened, where, and when it was last seen, loudest first. Five modules have been recording his failures for months and nothing ever showed them to the model — a route rendered them for a person, so Thomas could never look at his own problems and pick one to fix. A chronological tail would have been the wrong shape: the same failure repeats hundreds of times, and the newest entry is rarely the worst one.
- **Autonomy level 5, Autopilot: a blocker is work, not a reason to stop.** "If there is a blocker, fix the blocker... there should be never anything that stops you." The ladder stopped at L4 Full Autonomy, whose directive ends "Only stop if something is truly impossible or unsafe" — and `clamp_autonomy_level` capped every request at 4, so the level that fixes its own blockers could not be reached even in principle. At L5 a missing dependency, a failing check or a refusing tool is the next task, not a report handed back.

### Changed

- **The autonomy ceiling is 5 instead of 4.** L1-L4 are untouched, `full autonomy` still resolves to 4 for every existing caller, and the default is still L2 — the user opts up into hands-off autonomy, it is never on out of the box.
