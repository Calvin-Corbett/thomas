### Fixed

- **Your server keeps answering while a git command runs.** Tonight it stopped
  answering for over twenty seconds and came back the moment git finished. Two
  separate faults produced that. First, `subprocess.run(["git", ...], timeout=N)`
  never bounded anything: on a timeout it kills the process it started and then
  drains the pipes, and git reached through `Git\cmd\git.exe` has already handed
  those pipe handles to a grandchild the kill does not touch. Measured on the same
  read-only `git log`: the real binary honoured a 0.3-second timeout and returned
  in 0.32 s, while the launcher returned after 12.29 s. Second, every one of those
  calls ran on the server's single event loop, so even a correct bound would only
  have shortened the outage. Every git call the server itself makes now goes
  through one runner (`thomas/core/git_process.py`) that kills, waits a short
  grace period, and then abandons the process to a reaper thread rather than
  waiting on a pipe it does not own — so a caller is always back inside its bound
  — and the server's background loops, chat turns and Code endpoints hand that
  work to a worker thread (`thomas/core/event_loop_offload.py`). Read-only calls
  also run with `GIT_OPTIONAL_LOCKS=0`, so a status read cannot queue behind a
  commit in another worktree, and no more than eight git processes run at once.
- **Asking whether the server is alive no longer runs git where it is asked.**
  `/api/health` names the commit the build came from, because the version string
  alone cannot tell two worktrees apart — and working that out is `rev-parse`
  twice and `status` once. The answer is cached for the life of the process, but
  the first health request of a process filled that cache on the event loop,
  bounded at two seconds a call. Up to seven seconds of a server that could not
  answer anything, including the check that was asking. It is resolved in a
  worker thread now, and the payload is unchanged.
- **The Code surface's Changed Files list reads git status once, not twice per
  file.** `change_evidence` asked whether each file was untracked, and then
  `unified_diff` asked again, so a page's cost grew with the file count twice over:
  50 changed files meant about 100 full `git status --porcelain -uall` scans of the
  project. Measured 5 files at 0.60 s, 12 at 2.2-2.9 s, 50 at 9.7-13.3 s. One
  status read now serves the whole page and the per-file diffs are unchanged, so
  the evidence is the same and the scan is not repeated. The revert approval,
  which bound its hash with the same pair of scans, now takes one too.
- **A chat turn stops rediscovering things that cannot have changed.** Every
  message asked git where Thomas's own source lives (62-68 ms of subprocess, four
  times a turn, for the directory this package was imported from), re-resolved all
  213 registered project folders (433-505 ms a call), and rewrote the whole
  637-record execution board in order to read it (218-303 ms, three times a turn —
  the active task list twice and the digest once). The source root is now resolved
  once per process; the project list is memoized against the registry file's own
  signature and dropped the moment a conversation is bound; and reading the board
  re-derives it only when a record has actually been written. A newly written
  record is never served from a memo. The turn asks for the list once instead of
  twice, and it gathers all of these reads before it opens the reply stream
  (`thomas/server/routes/chat_v2_turn_inputs.py`): handing the work to a thread
  after the response headers are already on the wire would answer the request
  while the turn was still collecting what it needs to answer with.
- **Opening the Code history, and a build finishing, no longer stall everything
  else.** The conversation list walked 213 project roots and parsed 439
  conversation files on the loop — 4.4 s measured, and it re-read the project
  registry once per conversation instead of once. Recording a finished self-edit
  run fingerprinted its whole private copy of Thomas there too (8,456 files at
  9.5-10.9 s; 9,524 at over 11 s), as did the launch snapshot, the run's commit,
  and the delegations endpoint the Chat UI polls while work runs (175-446 ms quiet,
  0.77-1.64 s busy). All of them now run in a worker thread.
- **A revert approval is still claimable exactly once, now that two can arrive
  at the same time.** Authorizing a revert hashes the file and reads git, so it
  moved to a worker thread with the rest of that work — and its check-then-set on
  the shared approvals table had been atomic only because every handler ran on the
  one event loop. Two reverts sent together could both read the same approval as
  `approved` and both discard the file. The claim and its close-out take one lock,
  and a test runs eight concurrent authorizations through a barrier and requires
  exactly one to win — with the clock that window reads slowed to five
  milliseconds, so that removing the lock loses the race every time instead of
  being saved by how few instructions it spans.
- **The monitoring endpoints no longer stop the thing they monitor.**
  `/api/agents/activity` answered by running `git status` and enumerating every
  process on the machine — through PowerShell on Windows — directly on the server's
  loop, and that `git status` carried no timeout at all, so there was nothing to
  come back from. `/api/task-bots/executions` and `/api/metrics` each re-derived and
  rewrote the whole 637-record execution board (218-303 ms) the same way. All three
  now hand that work to a worker thread, and the status read goes through the bounded
  runner with the rest. These were not in the measured sweep; they were found by
  applying its rule to the routes next door.
- **The two health readings cannot hang on git either.** The landing check and the
  system map each run a read-only git probe, and both promised in writing that no
  repo could turn them into a hang — on a timeout that bounds nothing. They already
  ran in worker threads, so they could no longer freeze the loop, but every piece of
  work moved off the loop shares one pool of threads: a probe that never returns
  holds a worker that the runtime guard, a chat turn and the Code endpoints all now
  depend on. Both read git through the one runner now, and a caller working to a
  deadline of its own says how long it will queue behind other git calls, rather
  than waiting twenty seconds for a turn its budget can no longer use. Git is also
  given nothing to read on its standard input, so it cannot wait on a terminal a
  server process does not have.
- **Running an engine by hand no longer stops everything else for the length of
  the cycle.** `POST /api/engine-actions` awaited `run_cycle_once` where it stood,
  and a cycle is not a query: the workspace sync engine shells out to git again
  and again, and checks every changed Python file. Asking for `engine: "all"` ran
  four of those back to back on the loop. The same call on the local agent engine
  was already handed to a thread in `setup_aiohttp`; this endpoint was missed.
  Every cycle now runs in a worker thread and is named in the receipts.
- **The auto-commit engine's git calls are bounded, and it no longer starts a
  Python interpreter per changed file.** `thomas/core/workspace_sync_engine.py`
  was the last place using `subprocess.run(["git", ...], timeout=60.0)` — the
  timeout that bounds nothing, described above. It runs on a thread of its own,
  so it was never the cause of tonight's outage, but a push that stalled on an
  unreachable remote or a credential prompt held that thread and with it the
  activity lease every workspace mutation waits on. Its git now goes through the
  same bounded runner as the rest of the server, with the longer bound reserved
  for the one call that talks to a remote, and a git that does not finish comes
  back as a cycle that reports why rather than an exception thrown out of the
  middle of one. Checking that the changed files parse was `python -m py_compile`
  in a subprocess, once per file — a fifty-file commit was fifty interpreter
  starts to answer a question the built-in `compile` answers in the process that
  is already running. Same check, same line numbers in the report, no spawn.
- **A finished task's result is located once, not three times a row.** Working
  out which file a task produced walks its whole workspace, and the three things
  a card shows about that file — the link, the name, and the kind that decides
  whether it opens in the preview or downloads — each walked it again for the
  same answer. That is three walks per finished row of the delegations board,
  which is read on every chat turn and on every poll the Chat UI makes while work
  is running, and three per card in the projects catalogue a picker opens with.
  A generated app that installed packages beside its output makes each of those
  walks thousands of file checks. The entry is resolved once and passed to the
  rest. Opening the result did the same walk twice more — once to decide whether
  to redirect to the preview origin and once to serve the file — and both were on
  the server's loop; now it is resolved once per request, in a worker thread.
- **A run that changes Thomas no longer silences Thomas while it measures
  itself.** To tell what a self-development run changed, the server took a
  before-and-after picture of the whole private copy: it walked every folder and
  then opened and hashed every byte of every file it found. On this checkout that
  is 8,446 files and 98.2 MB, which takes 1.67 s just to read and hash natively.
  That picture was taken on the server's event loop at the start of each attempt,
  again the moment the attempt finished, and twice more for a Max-effort run — so
  every retry of a run in which Thomas works on Thomas cost the whole server
  several seconds of silence, repeatedly, exactly while you were watching it work.
  The same two readings now happen in a worker thread. A first attempt of an
  ordinary workspace run also no longer asks git for a diff it has no use for, and
  salvaging what a cancelled or timed-out run left on disk — another full walk —
  moved off the loop with them.
- **The board that shows the work no longer stops the work.** Mission Control's
  snapshot rebuilds the whole execution summary from disk, reads the run store,
  and asks the autonomy store for its jobs, objectives, audit rows and pending
  approvals — four SQLite queries behind one lock. All of it was synchronous and
  awaited where it stood, and the streaming endpoint re-runs the whole thing
  about every two seconds for as long as anyone leaves the page open. So the one
  surface someone watches *because* builds and cards are running was blocking the
  loop those builds and cards run on, on a timer. The snapshot and the approvals
  read now each go to a worker thread. This one was not in the measured sweep
  either; it was found by following the sweep's own rule — the execution board is
  expensive to re-derive, so every place that re-derives it was worth checking.
- **`code.find_definition` cannot spend four minutes inside Thomas's own state.**
  Pointed at `.`, it took 227.5 s, because its skip list named `.git` and
  `node_modules` but not `.thomas` or the root's `runtime/` — and a Build child
  agent's tool calls are tasks on the server's loop, so that was 227.5 s of total
  silence. The `code.*` scans share one skip list and one budget now
  (`thomas/tools/code_search_scan.py`), stop at 20,000 files or 20 seconds with a
  line saying they stopped early and why, and run in a worker thread. At a
  project's root the only name skipped is `runtime/`, exactly as `fs.search` does
  it: a directory skipped there is a directory of your code that a search reports
  no matches in. This is the same fix `fs.search` got on 2026-09-23, applied to
  the tools that were missed.
- **A chat turn's first model call no longer loads certificates on the loop.**
  The new lag sampler found this one on its first run through the test suite: it
  logged a 1.33-second stall during a chat request. Building the HTTP client for a
  model loads the CA bundle into an SSL context, twice when a proxy is set, and
  that held the loop for 0.42 s and then 0.84 s in the same call. The client is
  now built in a worker thread.
- **The delegation tests stop leaving phantom agents behind.** Three cases in
  `tests/test_chat_delegation.py` passed no repo root, so the task contract they
  exercised wrote `exec-answer`, `exec-native` and `exec-read-only-artifact` into
  the live `runtime/coordination/task_bots/`. Mission Control counted them as
  running agents in the tests that came after. Every case now uses the throwaway
  root its `setUp` already made for exactly this.
- **A test's stubbed board is the board it reads.** The delegation board is now
  memoized per project folder (above), and that memo outlived the test that filled
  it: after `tests/test_chat_delegation.py`, the partial-artifacts test replaced
  `list_executions` with a stub and got the real folder's rows back instead, so a
  failed task's leftover files were missing from its card. `tests/conftest.py`
  now clears the memo before every test, as it already does for the other
  process-wide state.

### Added

- **The server measures whether it is answering, and says so.** A sampler asks the
  loop to wake it every quarter second and records how late it actually was, which
  is the honest definition of "the server stopped answering" — a request handler
  cannot start until the loop can schedule it either. `GET /api/landing-health`
  now carries `event_loop` (worst and mean lag, and whether it stayed inside its
  half-second budget) and `off_loop` (how much blocking work was kept off it,
  slowest first), and a stall past the budget is logged as a warning naming the
  duration. Without this, the next regression would be felt before it was found.
  Both sets of durations — the lag samples and the off-loop receipts — are timed
  with `perf_counter`, because Windows' `monotonic` clock ticks every 15.6 ms and
  recorded a measured 1.2005-second call as 1.187 s about one reading in seven:
  precise enough to notice a stall, too coarse to be quoted back as the length of
  one. A few milliseconds of the reported lag is the loop's own timer granularity
  rather than blocked work, and that is lateness a request would have felt too.
- The loop-lag tests that prove the server keeps answering now leave a clear
  margin: 1.2 s of blocking work against a 0.5 s lag budget, up from 0.8-1.0 s
  against 0.3 s. On a loaded machine the loop measured 0.3046 s with the work
  correctly off the loop, so the old budget failed a fix that was working, while
  work left on the loop still lags by the full 1.2 s and fails.
