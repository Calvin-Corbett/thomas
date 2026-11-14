### Changed

- **A Thomas project that stops getting anywhere pauses and asks you.** You said "he
  needs a good this enough to stop": this month one project's change failed its check
  before your card 48 times in a row, another's check came back unavailable 35 times
  on the same patch, and a dozen Builds ran 30 to 84 hours. Nothing stopped them. Now
  three rules look for progress since your last message. A change sent back five
  times in a row without fewer failing tests than its best so far, a check that could
  not run four times in a row with no verdict in between, or (on Autopilot) six done
  checks in a row that each changed files again, pauses the project instead of going
  round again. There is no clock and no round limit: a new lowest count of failing
  tests starts the five again, so a project still making progress is never cut off.
  A paused project shows as paused, not ended: its copy is kept, the card says what
  it tried and why it stopped, a restart leaves it alone, and your next message -- in
  Build, or a reply in Chat -- carries it on. Each pause is recorded as an issue.
