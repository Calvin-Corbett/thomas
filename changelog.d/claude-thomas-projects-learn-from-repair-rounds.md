### Added

- **A Thomas project's team now hears what earlier teams were sent back for.**
  You said: "he is really dumb like it doenst seem like he is learning
  anything". A repair round's reason used to be written only on its own
  project's record, so the next team repeated it. Now every round
  `thomas_project.prepare_repair` stamps (sent back by the check, sent back by
  hand through `POST /api/self/projects/{conversation_id}/send-back`, too large,
  or dev moved) also adds the kind it came back for to one ledger,
  `thomas_projects/repair_ledger.json` in your Thomas data folder
  (`resolve_thomas_data_dir()`). The kinds come from the check's own headings:
  tests that pass on dev and fail with the change, new tests that fail, failures
  that could not be settled or timed out, tests that could not run, ruff check
  findings added, files left unformatted, the size rule. There are also kinds for
  a change that will not apply to dev, a change that changed while it was being
  checked, a change that was too large, and a manual send-back, which keeps only
  its first sentence, at most 200 characters. The ledger keeps the 200 most
  recent records and is written atomically. When it cannot be read or written,
  that is logged, and the round and the project start go ahead anyway.
- When a Thomas project starts, its notes carry one more section after the
  lessons: "What earlier Thomas projects were sent back for most often", at most
  five lines, most frequent first, each with its count (for example
  "- 3 times: tests that pass on dev failed with the change"). The section is
  left out when the ledger is empty or missing.

### Changed

- The headings of the check's findings (`precard/report.py` `HEADINGS`,
  `FINDINGS_HEAD`, `CONFLICT_HEAD`) and the first line of a moved change's
  findings (`precard/handover.py` `MOVED_HEAD`) are now named constants, so the
  ledger sorts a round by the same words the team reads. The text itself is
  unchanged.
