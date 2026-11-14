### Changed

- **The chat page is minimal again, the way you set it on 2026-09-06.** You asked
  to "remove the whole brand header in the sidebar, the face icon and the word
  Thomas, there are two icons on the left and we want one", and to remove the
  welcome tiles so "a new chat is just the greeting and the composer". Both were
  applied to your personal overlay — and then cleared 72 seconds later by a
  verification session, on the promise that "Thomas is making the same change in
  stock". That stock change never happened: no commit on any branch ever removed
  either, and the ask appears nowhere else in Thomas's history. Both are now gone
  from the page itself, and a test fails if either comes back, so the next
  refactor of this page cannot quietly undo it. (Your third ask — the Tools button
  matching the plus button — had already been fixed in stock.)
- **One of your two surviving overlay edits now lands on the wrong button.** It
  addresses its target by position (`button:nth-of-type(3)` under a chain of
  unnamed `div`s), and the page was reorganised on 2026-09-20; that address now
  resolves to the "Bad reply" button under each message. The overlay's own checker
  already warns such edits "may not resolve after a stock change". Left as it is
  for you to decide; worth knowing that positional edits drift.
