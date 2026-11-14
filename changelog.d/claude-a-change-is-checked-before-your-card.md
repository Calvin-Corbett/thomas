### Added

- **Every change Thomas makes to himself is checked before its card is shown to
  you.** You said: "Every change you make to yourself reaches my Windows sign-in
  card with nothing on it that says whether it was checked. Tonight every hand-in
  was checked by hand before I saw its card, and 9 of 10 checks found something
  real... This morning two cards reached me before that check ran; I approved
  both, and between them they took `thomas/core/llm_client.py` past the 800-line
  limit (`tests/test_architecture.py` failed on dev), broke about 45 chat tests
  ... and removed a helper the restart resume still called." `settle_if_finished`
  now runs that check itself, between the size rule and the hand-off, in the
  order you described it: take the change's patch and the dev commit the promoter
  will re-derive it against; apply it to a scratch copy of that dev with
  `git apply --3way` (a conflict is a finding); run the change's own test files,
  `tests/test_architecture.py`, and every test file that imports a module the
  change touches, on that copy and on an unpatched copy of the same commit; count
  only the failures that pass on dev and fail with the change, each re-run on its
  own to rule out flakiness; run `ruff check` and `ruff format --check` on the
  changed files, counting only what is new; and apply the repo's size rule. The
  check runs with none of your `THOMAS_*`, `GIT_*` or `PYTEST_*` variables and a
  data folder of its own, never touches the running copy's git index, and runs
  off the server's event loop. Its scratch copies are removed when it finishes,
  pass or fail; one Windows will not let go of is marked for the next green
  sweep. While the check is using them, the sweep another self-fix starts leaves
  them alone and no other team's sibling note lists them.
- **A change that fails goes back to its team instead of reaching you.** It
  raises `ChangeFailedCheck`, and Autopilot turns that into a repair round with
  the findings — the same path, the same three-round bound and the same wording
  as `POST /api/self/projects/{conversation_id}/send-back`
  (`thomas_project.SENT_BACK`). The findings name the exact test ids, say how
  each was established, and list what was excused because dev already fails it
  too, so a team can tell a regression from a failure that was there first.
- **A single worker's change gets the same check.** When Chat cannot start a
  Thomas project it still hands work on Thomas to one worker, and that worker's
  change used to reach your card through `chat_delegation_emitter` with no check
  at all. It is now checked the same way. A single worker has no team to send a
  failure back to, so a change that fails is not handed in, and the chat that
  asked gets the findings instead of a card.
- **A card that passes says what was checked.** The submission manifest carries a
  `checked` line, the settled project record carries it, `GET /api/self/projects`
  reports it per project, and the card mirrored into the chat shows it under
  "Checked". The Windows dialog's own wording is fixed by the pinned card
  catalogue (`scripts/cage/card_catalogue.py`, whose SHA-256 lives in
  `C:\ProgramData\ThomasPins`), so it is unchanged. When the check itself cannot
  run — no interpreter to run the tests with, the dev commit unreadable, or
  turned off with `THOMAS_PRECARD_CHECK=off` — the card says "Not checked before
  this card" and why, rather than claiming a check that did not happen.

### Changed

- The proof step lives on its own in `thomas/server/proof/`, apart from the card
  check in `thomas/server/precard/`: which test files prove a set of changed
  files, running them in shards, reading the failures back from a JUnit report by
  test id, re-running one on its own, and comparing two runs so a base failure is
  excused only when it is confirmed alone. It knows nothing about greens, cards
  or candidates. The card check is its only caller today; the reason it stands
  apart is that a second one is being built in another project's copy and not on dev yet — the
  ratchet's design asks for a `proof_set(changed_files)` and says it "has no
  equivalent in the repo today"
  (`docs/superpowers/specs/2026-09-23-praxis-ratchet-design.md`, §3). It has one
  now, so that work can call this step rather than write it twice.
