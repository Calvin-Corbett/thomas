### Added

- **A task card in Chat now shows the updates the run actually recorded.** Every
  dispatched task writes a timestamped history as it works, and the card showed one
  status sentence with all of it sitting unread behind `/detail` — the rest was
  reachable only by leaving Chat for Build, and ordinary worker tasks have no Build
  conversation to leave for. The card carries a "Task updates" panel: the latest four
  collapsed, the whole run behind "Show all", each line with its time, its state and
  the reason a step stalled.
- **The panel can be reached and read without a pointer.** It is a tab stop while it
  has something to scroll, and a running card repaints every three seconds — which
  destroyed whatever control the keyboard was resting on, including the ✕ that stops
  the task. Focus is now handed back across the repaint, and on to the line that
  replaced a control that removed itself — and on again from that line into the
  history, on the paint where the read it was waiting for arrives. Each hand-back
  asks whether the target can still hold focus rather than only whether it is still
  there: the panel keeps its element after a paint with nothing left to scroll but
  loses its tab stop, so it passes the keyboard on instead of swallowing it.

### Fixed

- **A card no longer invents a status it has not read.** The four states are now
  distinct and each is true when shown: a read still in flight says it is reading, a
  read that came back empty on a finished task says no updates were recorded, a
  record the server no longer keeps says none is kept, and a read that reached only
  some of a card's workers says so instead of reporting the gap as an empty history.
- **"Temporarily unavailable" now has something behind it.** Nothing retries a task
  that has finished, so on a settled card that word was a promise with no mechanism.
  A failed or partial read offers **Try again**, which skips the backoff and repaints
  immediately; a record reported gone offers nothing, because asking cannot bring it
  back.
- **A read that reaches fewer workers than the card has no longer shrinks the history
  it already shows.** Recorded transitions are append-only, so a line already read stays
  true when the worker that produced it goes quiet. Merging used to replace the list
  wholesale, dropping one worker's history on a single bad poll — thirty polls an hour on
  a running card — and it did the same when a task record was swept after its updates
  had already been read, taking two updates down to one with nothing said about it.
- **The card no longer prints the runtime's bookkeeping as a reason.** Stopping a task
  is recorded with `blocker="cancelled"`, so pressing ✕ produced a red "Blocked:
  cancelled" beneath an update that already read "Stopped by you."; a run with nothing
  to show produced "Blocked: no_evidence" beneath a sentence that had just said it in
  English. `/detail` drops both tokens and a real blocker passes through untouched.
- **A multi-worker card no longer claims all its history lives in Build.** One Build
  handoff labelled the whole merged list "Recorded in Build", including lines from a
  worker that was never there and that the "Open in Build" button does not reach. A
  mixed card reads "Recorded as it happened".
- **The collapsed card no longer prints its newest update twice.** The header's second
  line reached into the recorded history, from before this panel existed; the panel now
  sits directly beneath it under the same heading, so the line appeared once ellipsised
  and once in full — and on a multi-worker card the header leaked the internal
  `[worker]` tag it strips everywhere else. The header shows the task's status.
