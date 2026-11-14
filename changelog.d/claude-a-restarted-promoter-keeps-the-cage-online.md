### Fixed

- **A restarted promoter no longer takes the caged Thomas offline.** The promoter
  also runs the caged Thomas's only route to the network. When its task was ended
  and started again straight away, the new copy found the old one still holding
  the lock and exited without leaving any record. The scheduler reported success,
  and the caged Thomas lost its network for a minute. The new copy now waits up
  to 15 seconds for the lock, and if it still gives up it says so in the
  promoter's log.
- **Two test files that failed or hung on `dev` pass again.** Each broke when
  the code changed and its test did not:
  - `test_claude_exit_one_success_truth.py` (red since 378ec386): its stand-in
    snapshot did not accept the `allow_without_history` argument the Build runner
    now passes.
  - `test_evolve_agent_persistence.py` (red since 75729831): its stand-in request
    had no port, which the send route now reads. Two of its tests hung instead of
    failing because they waited for a start gate the crashed handler never
    reached. They now wait for the gate or the handler, whichever finishes first,
    so the next crash fails in seconds.
