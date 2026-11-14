### Added

- **Thomas lands his own backlog, one proven candidate at a time.** You asked:
  "the przcis racheting thing needs to happen we have a shit load of commits
  that arent l;anded. thats an autpomatic process thomas can run". Once a day,
  and whenever `POST /api/ratchet/run` asks, the caged Thomas works through its
  backlog:
  - It finds the work on its branches, salvage snapshots and remote branches
    that is not on dev, keyed by tip commit (seven branches point at one commit
    today) and ordered fewest files first, then oldest.
  - It sets aside the public repository's history, dependabot's updates, git
    stashes kept as salvage snapshots (a working-tree save, not work meant to
    land: one would have asked you to delete 11 files dev still has) and
    anything touched in the last three days, and says why. Which history is the
    public one is decided by what a commit's history is, not by the name of the
    remote it arrived on: a copy cloned straight from the work repository has a
    single remote called `origin` carrying the very branches waiting to land, and
    reading that name as "public" reported the whole backlog as nothing to do.
  - It measures the merge before spending a green: content dev already has, the
    files that conflict and which side to keep, what the promoter would refuse
    in its own words, files dev deleted coming back, tests dev already has.
  - It proves each remaining candidate against today's dev. The candidate's
    tests and the tests that import what it changes run in the cage, both with
    the candidate and on dev alone. Test selection and sharded runs use the
    shared `thomas.server.proof` service. A test that passes on dev and is gone,
    skipped or failing with the candidate stops it.
  - A candidate that holds goes to your promoter card. One that needs a model
    goes to a Build team in its own green first, whose settle is held, and the
    ratchet proves the result again before handing it in. When Thomas refuses
    the repaired change at hand-in (the size rule, or the check before your
    card), the candidate is recorded as reported, so it counts toward its limit
    like any other report and is not started over every day.

  Nothing reaches dev except through your card. A landing is recorded only when
  git confirms the commit is on dev, carries the submission's id and changes the
  files proven. A landing on a newer dev than its proof saw is proven again as
  it landed, and if that finds a broken test, the ratchet halts until that test
  passes on dev. A card you decline is not asked again. The board, task plans
  and `runtime/` are left out of every candidate.

  **No branch is ever deleted.** You asked that the ratchet not delete a branch,
  so a landed candidate's local refs gain a second name under
  `refs/archive/ratchet/` and stay exactly where they were. All seven branches of
  the first candidate are checked out in worktrees today, and deleting a ref a
  worktree holds leaves that worktree on "No commits yet"; the ledger line is
  what records that a candidate landed, so keeping the branch costs nothing.

  **What reaches your card is checked to be the candidate's own change**, twice:
  once before a proof is spent, against the merge the screen measured file by
  file, and once on the finished change, right before the hand-off. A private
  copy that starts with a tracked file already missing is refused rather than
  proven, because it is not a copy of dev. Without these, one such copy put the
  deletion of a file its candidate never touched on a card, and the proof passed
  it. A repair a restart cut short is taken up again in the green it is still in,
  rather than started over, which would have discarded the team's work.

  **A hand-off a restart cut short is found by the private copy it came from**,
  not by the name the run wrote down before making it. What a hand-off is called
  is decided inside it: a copy kept for your verdict — which every repair's copy
  is — names its second hand-in `-2`, so the guessed name would have found
  nothing, and the ratchet would have proven and handed in a second time a change
  already waiting on your card.
- **A held project's own readers live beside Build's, not inside it.** How a held
  project ended, and how to end one that will not land, are two things Build
  itself never needs; they live in `thomas_project_held` and callers import it
  directly. `thomas_project` gains only the `summary` a caller may hand
  `settle_if_finished`, rather than adding those readers to that module.
- **No test run can start the ratchet.** The daily run is on unless the
  environment turns it off, and the test suite turned it off only where nothing
  had set it already. A run started from a Thomas server's shell is the one that
  would carry the setting — and the one that would then prove real backlog
  candidates in real private copies while the suite ran. The suite now sets it
  off outright.
- **`GET /api/ratchet` says what is still unlanded**, listing every candidate
  with its state and reason and whether a halt stops the ratchet, and Chat
  answers the same question through a read-only tool, `self.unlanded`. Both read
  the ratchet's own census and ledger; neither runs git.

### Changed

- The ratchet delegates test selection and sharded JUnit runs to `thomas.server.proof`. Its cage adapter keeps reports outside the green before reading them. A selected test file missing from a shard is recorded as unrunnable even when other files in that shard produce a report.
- Held Thomas projects pass the ratchet's candidate summary to `settle_if_finished`, and the promoter receives the precard-checked change.
- The held-project settlement test checks the precard result passed to the promoter hand-in. Ratchet proof fixtures recognize the shared runner's report names.
- Ratchet merge-integrity, landing-summary, and host checks live in focused modules; the repair-goal test has its own test file, keeping the changed files within the 300-line growth gate.
- The backlog census regression uses a bounded fixture repository instead of scanning every ref and its history in the running checkout during the proof suite; the fixture checks that an `origin` work branch is not mistaken for public history.
