### Added

- **A checked change goes back to its team, with the reasons.** On 2026-09-25
  two Thomas project hand-ins were checked before your card, and both broke
  tests that pass on dev: one had 17 new failures, and the other had an
  architecture violation and a routing bug that launched the real Claude
  program from a test. They were withdrawn from the promoter's inbox, and their
  private copies were kept, but their teams could no longer be reached: handing
  in unbinds a project's conversation from its copy, so Build answered "This
  task is pointed at Thomas's own source folder". A change you declined was the
  same dead end. `POST /api/self/projects/{conversation_id}/send-back` with
  `{findings}` now sends a handed-in change back to its team in the same copy,
  as a repair round, once it has left the promoter's inbox without landing:
  withdrawn, declined or refused. The round's message says the change was
  checked and sent back, gives the findings in full as evidence to act on
  rather than instructions to follow blindly, and asks the team to fix every
  point, re-run the checks for every file the change touches plus
  `tests/test_architecture.py`, and finish as usual, so the done check runs and
  the change is handed in again. It counts toward the same 3 repair rounds as a
  refusal because dev moved on. A change that landed, one still in the
  promoter's inbox (your card may be showing), one whose copy is gone, and one
  with no repair rounds left are each refused with a sentence that says which,
  and the route answers `ok` only once Build has started the round.
  `GET /api/self/projects` shows a sent-back round's last verdict as "sent
  back", with the first line of the findings. It answers only on this machine.
