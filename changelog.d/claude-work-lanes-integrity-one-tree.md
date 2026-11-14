### Fixed

- **The native commit tool stopped refusing every commit in the repository over
  gate scripts those commits never touched.** `enforcement_integrity --check-staged`
  hashed each protected script from the index but read the manifest it compared
  them against from the working tree. During a scoped commit the index is HEAD plus
  that commit's own files, so an enforcement script another agent had staged — with
  its new hash already written to the on-disk manifest — hashed at HEAD while being
  compared with its new hash. Measured on 2026-09-10: three honestly staged scripts
  (`commit.py`, `briefing.py`, `workboard_agent_claim.py`) made the tool refuse a
  one-file plan update with `SAFETY GATE FAILED: Enforcement Scripts Tampered Or
  Uncovered`. The committing agent had tampered with nothing; a peer's in-flight
  work was reported as an attack on somebody else's commit. The manifest is now read
  from the same tree as the scripts. A tampered script staged beside a stale manifest
  entry still fails, a missing manifest still fails closed, and the manifest itself
  is still guarded by the protected-files gate.
