### Changed

- **What this covers, and what it does not.** You asked for a check that
  everything Thomas registers at startup — tools, routes, background engines and
  loops, settings and toggles, and the features the docs and changelog claim —
  actually runs and does what it says. This change is not that whole sweep, and
  nothing in it should be read as having done one. It fixes the four things you
  named yourself — one "Improve Thomas", no test-made projects in your list, one
  size rule that hand-in checks, and a list that never calls a dead project
  running — each proven by a test that drives the real code, plus two things
  found on the way and fixed the same way: a settings dial the panel accepted
  and never sent, and a claim in Thomas's own source that cited a startup module
  which has never existed. The sweep across every tool, route, loop and toggle
  is still owed.
- **"Improve Thomas" is one way, not two.** The Build project chooser's "Improve
  Thomas" button asked for a list of files and opened a `self_edit` Build
  conversation: one worker editing a snapshot inside that scope, landing by
  writing those files over your running copy (Review → Apply → Restart). A
  Thomas project does the same job properly — a private git copy, Build's full
  team, the repo's size rule checked before hand-in, repair rounds on a refusal,
  and a submission on your sign-in card that lands a real commit. The button now
  starts that, and asks for the change in your own words instead of for
  filenames; the team finds the files itself. Nothing left in the UI can create
  a `self_edit` conversation, which `tests/test_improve_thomas_is_one_way.py`
  holds — along with the dials the button sends being exactly the ones that
  route takes, since it refuses an unknown one by name and a renamed dial would
  otherwise only show up as a 400 the first time you pressed the button. One of
  those ten was accepted by the route and never sent: the panel left out
  `build_roles`, so a project started from it ran its builder and reviewer on the
  default model while the same picks were honoured for a run started from Build.
  It now sends them, shaped exactly as Build's own composer shapes them — held
  to that composer character for character by a check that reads both files, so
  the proof of this one does not rest on the panel harness alone, which is
  skipped wherever node is not installed. The old
  review card still renders for conversations that already have one; when none
  is left, it and `/api/evolve/agent/self-edit/*` should go.
- **The panel shows what is already going.** `GET /api/self/projects` reported
  every project's state from the day it was written and no page had ever read
  it. The "Improve Thomas" panel now lists them — state, detail and changed
  files — before you start another.
- **The repo's size rule is one rule, and hand-in checks all of it.** Thomas
  states the same 800-line limit in two registers with two different exemption
  lists: `allowed_large_files` in `docs/monolith_guard_baseline.json`, read by
  the commit gate, and the `debt` notes in `thomas/_architecture.py`, read by
  `tests/test_architecture.py::test_debt_trending` over the whole tree. Hand-in
  read only the first. On 2026-09-25 that let a change to
  `thomas/agent/loop_execution.py` — waived to 1100 lines in the baseline,
  recorded in no debt note — pass its hand-in size check and then fail every
  later commit's architecture check until the file was split. New
  `thomas/server/green_size_rule.py` reads both registers out of the green's own
  checkout, and `green_handoff.size_problems` asks it, so a change that would
  break either goes back to its team for a repair round instead of landing.
  Neither gate was relaxed to do this. Each team is now told both halves of the
  rule up front.

  The debt register is read in both directions, because the same gap runs the
  other way: `test_architecture.py::test_health_annotations` also fails a debt
  note that names a file which no longer exists, or that calls a file oversized
  once it is back under 800 lines. Trimming `thomas/server/routes/work.py` from
  805 lines to 799 — the split the team notes ask for — would have passed the
  hand-in check and then failed every later commit, exactly as the 900-line case
  did. Hand-in now says so, in the team's own terms: bring the file under the
  limit and take it out of its module's debt note in the same change. A note that
  says "exceeds" once makes that claim about every file it names, so the warning
  names that too.

### Fixed

- **A Thomas project that died hours ago is no longer listed as running.** You
  reported `GET /api/self/projects` showing one as "running: its first Build run
  is starting". That is the answer `project_phase` gives whenever a project's
  conversation carries no agent turn yet, and it had no clock in it — so a run
  killed before it recorded anything read as "just started" for as long as its
  copy existed. The liveness rule did exist, but only as a 120-second timer
  inside the chat card's follow loop, which dies with the process that started
  it; the list had none of its own. New `thomas/server/thomas_project_quiet.py`
  puts that rule on what is on disk: nothing written to a project's Build
  conversation for an hour, with no run going, is stopped, and it says so in
  words — the hours of silence it measured, and what the project had been
  waiting for. A project that really did just start, a live run thinking for a
  long time, a pause for a usage limit and a settle in flight are all left
  alone.

  Silence is all it measures and all it claims. A draft of this went further and
  ended every wait whose conversation predated the running process, calling that
  "stopped when Thomas restarted — nothing resumes it". That sentence is not
  true of Thomas any more, and two passes registered at boot are why: the
  Autopilot park loop, which rebuilds a build paused on a provider usage limit
  from the stamp on its conversation and starts it again when the limit resets,
  and Praxis's startup recovery, which resumes the unfinished children of a run
  the restart interrupted. The draft would have printed "stopped" over the
  projects either had just picked up, at the moment it picked them up — and said
  so in words that disagree with the ones the listing and the card already use
  for that event. The hour is now the whole rule, for a wait another pass owns as
  much as for one that recorded nothing, and no row says why a project fell
  silent or who will or will not start it again.

  The draft's justification had a second fault, and it is the one this whole
  change is about: it cited `thomas/server/autopilot_restart.py`, a module this
  repo has never contained. The claim was right and the citation was invented —
  something claimed, nothing wired — so it is now checked rather than asserted.
  `test_the_restart_passes_this_rule_defers_to_are_registered_at_startup` starts
  the real server and reads what boot left behind: the park loop is a live task
  on the app, Praxis recovery has written its resume report, and every
  `thomas/…` module the rule's own docstring names is a file in the tree. The settle-in-flight exemption is still a
  sentence compared by equality (`thomas_project` and the chat card's steer gate
  hold it separately), so its test drives `project_phase` itself and then
  compares the two copies, rather than asserting a constant against itself.
- **A test run no longer creates projects in your list.** Your Build list filled
  with projects your own tests made ("Use browser.open and browser.extract then
  …"): a card in that chooser is built straight from an execution record and
  titled with the run's own prompt. Two earlier fixes went at this and neither
  closed it — a lint for `repo_root=Path(".")`, which cannot see a call that
  passes no root at all, and `conftest.py` moving `THOMAS_DATA_DIR` and
  `THOMAS_OWNED_ROOT`, which covers the data-dir ledger but not the checkout's
  own `runtime/coordination/task_bots/`, where a resolved root lands and no
  `THOMAS_*` variable reaches. New `thomas/core/shared_root_sandbox.py` makes
  the stores refuse instead: in a test process, a root that would be a shared
  one — the checkout or the data dir, whichever the caller reached —
  becomes a throwaway folder. Reads go through the same redirect, so tests that
  write a record and read it back still work; a root a test passes in itself is
  left exactly as it is; outside a test process nothing is redirected at all.
  The throwaway folder is also removed when the run ends, and one a killed run
  left behind is swept a day later, so this trades nothing for litter in
  `%TEMP%`. There is one stand-in per root, not one per process: `THOMAS_DATA_DIR`
  is what a fixture moves to give a test a data dir of its own, and a single
  folder for the whole run made those tests share one ledger — a two-test probe
  read the first test's execution record in the second test — which is a leak
  the redirect would have introduced itself.

  There were two of those stores, not one, and the first round closed only the
  ledger. A coding task dispatched from chat also mints a project and binds its
  conversation to it, writing `.thomas/evolve/agent/project_registry.json` under
  the resolved checkout — and that registry is what
  `GET /api/evolve/agent/conversations` lists, so one run of
  `tests/test_chat_delegation_worker_contract.py` still put its own prompt in
  your list. The registry now goes through the same redirect, at the one place
  every read and write of it passes. The test drives the real join dispatch uses
  and reads the binding back, so a redirect that closed the leak by breaking the
  feature would fail it. This stops new ones; the test-made entries already in
  your list stay there until they are removed, which nothing here does. The
  older leak test that counted files in "the real checkout" asked the resolver
  for that directory, which now answers the throwaway one — it names the
  checkout's path directly, so it keeps measuring what its docstring says. That
  lint also stopped reporting prose: it already exempted `#` comments, and now
  exempts docstrings too, so a file that explains the hazard by quoting the
  spelling is not counted as a call site making it. Only a bare string statement
  is skipped, never a string inside a call, so a real offender still fails.
