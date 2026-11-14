# Landing queue (stage S1 of the landing train)

Many agents land work on one branch through one commit tool. Measured with ten simulated agents, the whole fleet landed
about as fast as one agent: every waiting agent kept running the gate ladder against a branch that kept moving, and most
attempts were refused. The queue puts a first-in, first-out line in front of the **unchanged** commit tool, so waiters
run no gates.

**This is a queue, not protection.** Every agent runs as your account and can write every file the queue keeps, and
`commit.py` still works when called directly. The queue is advisory and tamper-evident only. The Praxis cage does not change
that for S1: nothing is carved out of `runtime/coordination` for it, so a caged agent can write the same files.

## What an agent runs

```
python scripts/crew/brief/land.py --status                        # who is queued; do this first
python scripts/crew/brief/land.py --message "..." [--include P]   # same arguments as commit.py; waits for you
python scripts/crew/brief/land.py --submit --message "..."        # take a ticket, return once it exists
python scripts/crew/brief/land.py --wait N [--wait-seconds S]     # ask about ticket N for up to S seconds (default 90)
```

A wait takes minutes when others are landing (3 to 6 at twenty agents). If your tool call can time out, use `--submit`
then `--wait N` in a loop (alias `--resume N`): each call is bounded and safe to repeat, and a separate worker process
keeps your place if a call is killed. Running the same command again attaches to your open ticket; if that ticket's
worker died, the re-run takes it back first, says so, and queues again with a new worker.

Exit codes: 0 landed or already landed, 1 refused (at least 2,000 characters of the gate's output printed, and the path
of `output/T<ticket>-<stage>.txt` under the queue root, which has all of it), 2 usage, identity or attempt cap, 3 waited too long,
4 your ticket was taken back and nothing landed, 5 still waiting. 3, 4 and 5 mean run it again. `--no-precheck` skips the
dry run; `--no-detach` waits and lands inside the calling process (it dies with it).

## Modules

| File | Job |
|---|---|
| `land.py` | entry: identity, already-landed check, pre-check, ticket, wait or submit, status |
| `land_worker.py` | detached worker and its log (`logs/T<ticket>.log`), `--submit`, `--wait`, exit codes from the ledger |
| `land_commit.py` | one real run of the commit tool (job object, lease), one bounded dry run, refusal output files |
| `land_precheck.py` | the pre-check in the waiting process: near the head, in a free slot, never in the way of a turn |
| `land_git.py` | the `Landing-Ticket` key, "did this change already land" |
| `land_env.py` | repo and commit tool, session-bound identity, presence heartbeat, lane wiring |
| `landing_queue.py` | the lane: tickets, wait, grant, hold, caps, pruning hook |
| `landing_reaper.py` | folding the ledger into states, finishing tickets whose owners are gone |
| `landing_liveness.py` | the liveness judgement and the wall-clock guard |
| `landing_store.py`, `landing_files.py` | the ticket store behind a small interface, file primitives |
| `landing_audit.py`, `landing_prune.py`, `landing_status.py` | `--verify`, pruning, `--status` |
| `landing_proc.py`, `landing_spawn.py` | start times, job object, git locks; every child starts with no console window |

## One landing

1. **Already landed?** `find_landed` looks for the key in the newest `window_commits` (400) commits of HEAD, then
   requires that the files that commit changed hold, in your working tree, exactly what dev's TIP holds (so a landing that
   dev later reverted is landed again, not dropped) and that nothing else THIS landing would stage is still pending: with
   `--include` that is the dirty files inside those paths, without it the commit tool's own dry run names the staged set, so
   the unrelated dirty files every shared checkout has never matter. If the staged set cannot be determined (the dry run timed
   out, the commit tool refused it for any reason other than having nothing to stage, or no dry run runs at all, as in
   recovery and in the holder's check before its commit tool starts) the answer is "not landed": unproven means not landed,
   and the commit tool decides. A different change with the same words is therefore not "already landed". A landing older
   than the window is not found: the answer is "not landed", the change goes through the commit tool again, which refuses a
   change that is already in the tree (the safe direction).
2. **Pre-check, while waiting** (`land_precheck.py`). Never before the ticket exists: the process that waits for the ticket
   (the worker, or land.py with `--no-detach`) runs one dry run of the commit tool while it waits, and only when at most 2
   open tickets are ahead (so a hundred waiters do not all run dry runs), only when one of 2 queue-wide slots is free right
   now (no free slot: it tries again at the next poll, it never waits for one), at low priority, at most once per ticket,
   beating the ticket's heartbeat while it runs. When the ticket's turn comes during the dry run, the dry run is stopped: it
   never delays a turn. A refusal that only reflects a branch others keep moving (`branch_race`, `workboard_agent_claim`,
   `workboard_changed_files`) is retried once and is then advisory, like a timeout; any other refusal finishes the ticket as
   refused before it used the slot (exit 1, not counted toward the refusal cap). Alone, you pay for one gate ladder, not two.
3. **Ticket.** A numbered file created whole (temp file hard-linked into place), so a crash never leaves an empty numbered file
   and the number is the place in line. Numbers never go backwards, even if a ticket file is deleted. A ticket records the
   process and its start time (a reused pid is a different process), the includes, and the request.
4. **Wait without gates.** A worker polls every 2 s, writes at most one heartbeat per 5 s, and refreshes your presence
   session (never one that was closed). Every `--wait` call touches the ticket; a submitted ticket nobody asks about for
   10 minutes leaves the line (it is not counted against you).
5. **One in flight.** The head waiter takes the slot only if no commit tool of a skipped holder is still running and no
   abandoned git lock file is left (removed only when no git runs in this repo, and reported). The lease is the reaper's
   `max_hold` (900 s), clamped to 1800 s, never the holder's own word: a longer value in a ledger line is ignored and
   `--verify` reports it. A holder may ask for a shorter lease.
6. **The commit tool** runs in a job object with its output in a file, bounded by what is left of the lease. At the lease the
   whole tree is killed, orphaned grandchildren included, so the return time is bounded. Before anything is called a
   refusal, dev's tip is checked for the key and content: a landing that finished in the last milliseconds is a landing. A
   refusal keeps the commit tool's whole output in `output/T<ticket>-refused.txt` under the queue root, and the ledger keeps
   up to 4,000 characters of the reason, at least 2,000 of them from the gate's own output.
7. **Recovery** (any waiter, idempotent): a dead owner (pid and start time), a stale heartbeat, a lease overrun, a head that
   never takes the slot (60 s) and an unreadable heartbeat past its file's age are finished with a notice for the agent. A
   skipped holder's surviving commit tool is killed by pid and start time before the next grant. A wall clock that was set
   is detected and ages are then measured by what the observer has watched; a suspend is handled for running pollers, a first
   poller after the wake and a holder that has run (see "What the second review changed", which also says what is NOT proven).
8. **Exactly once.** The key rides in a `Landing-Ticket` trailer. Your own land.py run looks for it before it queues, and the
   run in the slot looks again before it calls a failure a refusal (step 6); both use the content check and, without
   `--include`, the commit tool's dry run. Recovery and the holder's check before its commit tool starts run no dry run, so
   they can answer "already landed" only for a landing with `--include`. Without it a holder that died is skipped, and if
   its landing did happen, running the same command again finds it through your own check.
9. **Caps.** Keyed on the session-bound identity the commit tool uses. A hold that overran its lease or went silent counts
   toward the strict cap (3 per hour); an honest refusal by the commit tool inside the slot counts toward a looser cap (10 per
   hour). A wait that timed out, a withdrawal, a killed or silent waiter, a killed holder and a lane skip never count.
10. **Pruning.** When more than about 600 finished tickets exist the lane removes the oldest below every open ticket and writes
    one ledger line saying so (so `--verify` does not read it as tampering). Heartbeats of finished tickets are deleted, and a
    pruned ticket's output files and worker log go with it.

## Tamper evidence (not protection)

`land.py --status --verify` reports: a deleted or rewritten ticket, a missing or reused number, an edited or missing ledger
line, an event written by someone other than the ticket's agent or a lane writer (those are also ignored, not honoured),
a lane verdict "owner is dead" about an owner that is alive and is the same process, a lease longer than the reaper allows,
and half-written files. An agent that forges a ticket and the ledger line that vouches for it passes every check.

## Later: a lane that agents cannot write as

The queue root is one setting, `THOMAS_LANDING_QUEUE_DIR` (default: the shared `runtime/coordination/landing_queue`). The lane
only calls the `TicketStore` interface. Moving it under the cage channel folder (`C:\ProgramData\ThomasCage`) means pointing
that setting at a folder whose ACL lets agents create request files and read but lets only the lane write tickets, ledger and
lease; running the lane (grant decisions, lease, recovery, the idempotency lookup) in a service as SYSTEM or `thomas-agent`;
and, in S2, making the commit tool (protected, your sign-in) refuse to land without a slot signed by that service. Today's
version runs as your account, so it is tamper-evident only.

## What the second review changed, and the limits that remain

- **Sleep.** On Windows the monotonic clock counts the time asleep, so a suspend moves both clocks together. The lane notices
  it two ways: a poller's own gap between polls longer than 30 s, and a queue in which every OTHER owner's newest beat is older
  than that gap (a first poller after the wake sees only this). Either resets the observation baseline once, so every beat is
  forgiven, and ages (and the lease) are measured from the wake for the next half hour. A holder's heartbeat also carries
  `ran`, the seconds its commit tool has actually run (sleep not charged), and the lease is over when `ran` passes it.
  **Proven:** running pollers, a first poller after the wake, and a holder that has run. **Not proven, known limits:** after a
  suspend longer than 10 minutes, a process that starts polling AFTER the workers have beaten again (any new `land.py` or
  `--wait`) sees fresh beats and old touch files, and can send every other detached ticket to the tail with exit 4 (no work is
  lost; the agents run it again); after a suspend of about two hours a holder that has run can lose its lease through the
  wall-time bound of eight leases (the landing then reads "lease overrun", its commit tool is stopped, and it goes again); and
  a suspend longer than what is left of a ticket's 45-minute limit gives a waiter that is already polling exit 3 (waited too
  long: run it again). The commit tool's own wait is sliced for the same reason as the lease. A fix needs an awake-time stamp
  in every beat and touch.
- **Stray ledger files.** Numbered files are read with any number of digits. A file that is not a valid event (such as
  `ledger/E999999.json` containing `{}`) is ignored by the lane and named by `--verify`; it can no longer hide later events.
- **Forged `by` fields.** S1 cannot stop an agent that writes a ledger line with a believable `by`, because there is no secret
  agents do not share: a forged line can evict a ticket. What it does: a lane verdict "owner gone" about an owner that is
  alive is ignored and reported unless its reason can honestly be given about a live owner (a lease verdict also has to be
  true); `--status` says plainly how many lane verdicts rest on their own `by` text; a second `--worker` for a ticket that is
  already held exits without adopting it, and `wait_turn` refuses a ticket that is already holding (one commit tool per ticket).
- **Never kill a pid a file names.** The reaper kills only the recorded commit child whose start time matches AND whose command
  line contains the commit tool the holder recorded, and only after the lease. Anything else a heartbeat names is left alone
  and reported. An agent that copies a real commit tool's start time and command line can still make the reaper kill THAT
  process, which is the same account today and a confused-deputy risk once agents run as another account: an S2 blocker.
- **Job object.** `KILL_ON_JOB_CLOSE` is set: if the worker dies the commit tree dies with it. If the OS refuses the job (a
  parent job forbids nesting) the ticket is marked `unbounded`, a warning is printed and the tree kill is the fallback. The
  worker is started with breakaway when allowed; when it is not, `--submit` warns that a tool that kills its job at a timeout
  takes the worker with it.
- **Pre-check** is bounded (120 s) like the real run; a timeout is advisory ("queueing anyway").
- **Honest slow landings.** A hold past 300 s is reported once as "hold overran" and is stopped only at the 900 s lease.
- **Lifetimes.** A submitted ticket nobody asks about for 10 minutes leaves the line (call `--wait` at least every 8 minutes);
  a ticket waits at most 45 minutes (`--wait-timeout`, which the worker honours).
- **Git locks.** A stale lock is removed only when no git process could hold it: a git whose directory or any path argument
  (`git -C <dir>`) is inside this checkout or a linked worktree, or whose directory cannot be read, counts as holding it.

Known limits, deferred: a waiter's poll costs about 55 ms at 100 waiters (it reads every open ticket's beat and touch file);
each worker is a Python process of about 32 MB (3 GB at 100); the lease for an honest 14-minute test run still holds the slot
for those 14 minutes; per-identity hold budgets and a sybil that takes a fresh agent name per cycle are not handled.

## After the verification

- **Prune under a reader.** On Windows a reader that has a file open makes its deletion fail. The prune now removes the tickets first
  and skips any file it cannot delete (the next prune finds it again), and a housekeeping failure never stops a landing.
- **Only the first `granted` line counts.** A holder that appends another cannot restart its own lease.
- **`--status` counts bypass commits since the OLDEST open ticket.**
- **The briefing text moved to `landing_briefing.py`** and says plainly what keeps your place: after `--submit` a worker does; a plain
  `land.py --message` that is killed together with its processes loses its ticket, and so does a `--submit` whose tool kills its whole
  job (`--wait` then answers exit 4: run again).
- **Exit codes worth knowing:** `--submit` exits 0 with status `submitted` while the change is NOT landed yet (read the status, not
  only the exit code); exit 2 also means the attempt cap, which has no override: ten honest refusals an hour, three slot-wasting
  holds an hour.

## After landing on dev: the first follow-ups

- **Gate reasons.** A refusal (in the slot or in the pre-check) keeps the commit tool's whole output in
  `output/T<ticket>-<stage>.txt` under the queue root and prints its path; the agent sees at least 2,000 characters of the
  gate's own output (it used to see about 300, cut mid-line).
- **The pre-check runs in the waiting process** (step 2), so `--submit` returns once the ticket exists, a dry run never runs
  without a free slot, and only tickets near the head run one.
- **Run it again re-attaches.** land.py reaps before it looks for your open ticket, and calls it attached only when the
  ticket it gets is that very one, so a re-run after a dead worker queues again with a new worker (and says the old ticket was
  taken back) instead of waiting on a ticket nobody holds.
- **A worker log and a git that does not answer.** Each worker writes what it does, and any crash, to `logs/T<ticket>.log`;
  an exit 4 names that log. A git call that does not answer within its timeout, or exits with an error, is "no answer"
  (`None`, never empty output): the already-landed check reads it as not landed, it is said on stderr, and it is never a
  traceback that kills the worker.
- **Pinned:** the fallback tree kill when the OS refuses a job object (the test's processes now carry the tag on their
  command lines), and the wall bound of eight leases on a holder whose own run-time count never moves.
- **Not covered here:** the awake-time stamp for a long suspend, the small items of the verifier's list, and the
  queue root the worker resolves for itself.
