### Fixed

- **A Thomas project the promoter refuses because dev moved on goes back to its
  team, in the same private copy.** On 2026-09-24 five projects started from the
  same base; after the first landed, two more passed their own done checks and
  were refused ("the change no longer applies to dev"). Their copies had already
  been deleted at hand-in, so a person had to rebase both by hand. A project's copy
  is now kept until the promoter's verdict. A refusal because dev moved on starts a
  repair round in that copy, with no message from you: its message names the
  commit dev moved to, says to `git merge` it, resolve every conflict keeping both
  sides' intent, move release notes into a changelog.d fragment, and hand in again
  after the done check, and it carries the promoter's refusal in full. A repair
  round is not one of Autopilot's 12 continuations; at most 3 run per project,
  and the card then says the change was refused again and where it is kept. A
  landed change's copy is removed as before; a decline or any other refusal keeps
  it for 7 days from the verdict, and the card and the chat say where. Every other
  refusal is shown word for word.

- **The promoter's refusal names every file that no longer applies.** It kept
  only git's first 300 characters and stopped mid-word ("error:
  tests/web_node/conftest.py: does not mat"). The verdict now carries the full
  list of files, capped at 200, in its `conflicts` field and in its words.

- **A Thomas project's request tells its team the repo's conventions and what
  the other projects are changing.** It names the size rule (a file not in
  allowed_large_files stays at 800 lines or fewer; a listed one keeps to its
  max_lines and max_growth_lines) along with the changelog.d rule, and lists the
  files every other running Thomas project has changed so far, read from their
  copies without writing to them, so two teams do not make the same file blind.
  The promoter runs no size check, so the hand-in now checks the size rule
  itself, and a change that breaks it goes back to its team as a repair round
  instead of being handed in.
