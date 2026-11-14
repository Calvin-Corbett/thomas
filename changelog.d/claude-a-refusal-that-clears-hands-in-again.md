### Added

- **A refusal that clears by itself hands the change in again.** On
  2026-09-25, between 03:25 and 03:45, four finished Thomas projects were
  refused within minutes of each other for one reason: "the running copy has
  uncommitted work in" a file the change touched. Another agent was editing
  those files, and committed them shortly after. Nothing tried again: only a
  refusal because dev moved on went anywhere, and sending one back would have
  spent a repair round and a whole Build run on a change that needed nothing.
  Now that refusal is recognised with the files it names, and the project waits
  until the running copy has no uncommitted work in them, by the promoter's own
  test, read without ever taking the index lock that other agents and the
  promoter use. Then the same private copy is handed in again the way it was
  first: a new submission, whose verdict is followed as usual, with no repair
  round, no Build run and no model call. It looks every 60 seconds for up to 6
  hours; a refusal of that hand-in for the same reason waits within the same 6
  hours, and after that it gives up and says why, in `GET /api/self/projects`
  and the issue log. While it waits, the listing says it is waiting for the
  running copy and on which files, and once handed in again it shows the new
  submission beside the refusal before it. A wait lives in the server, so a
  restart ends it: `POST /api/self/projects/{conversation_id}/hand-in-again`
  hands such a change in again at once, and so it can the four refused on
  2026-09-25. It answers with the new submission, or with a sentence saying
  why not: another kind of verdict (use send-back), work still uncommitted
  (which files), a copy that is gone, or a hand-in still in the promoter's
  inbox. It answers only on this machine. A project Chat started still shows
  the refusal on Chat's task card; that card does not yet follow the new
  hand-in.
