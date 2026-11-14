### Fixed

- **A shell command containing quotes now reaches the shell intact.** Commands
  were handed to Windows as an argv list, and `subprocess` joins an argv list
  with `list2cmdline`, which escapes inner quotes as `\"` — an escape `cmd.exe`
  does not understand. So anything quoted arrived mangled: `python -c
  "print(7*6)"` answered *"is not recognized"* instead of `42`, and
  `git log --format="%s"` printed its own quotes. That is most of what a
  `git commit -m "..."` looks like. The whole line now goes to the shell as
  typed, which is the same shell reading the same string the way a person
  would; nothing about what may be run changes. POSIX was never affected —
  `exec` takes argv directly — and is untouched.
  - The caged runner had the identical bug and has the identical fix, because
    the two paths must agree or the cage would change what a command means.
- **The test suite no longer depends on the cage being up.** With the posture
  pinned, `shell.exec` routed every test command through the caged runner, so
  tests covering the local execution path — hang evidence, the spool file, the
  selector-loop fallback — quietly stopped covering it, and when the runner
  stopped, twelve tests failed for reasons that had nothing to do with them.
  Tests now redirect the cage root in their own process, which changes nothing
  on disk; the pin still cannot be lowered. Tests that mean to exercise the
  cage set it up themselves.
- **A long command no longer makes the caged runner look dead.** The heartbeat
  shared the serve loop, so it paused for as long as a command took — and the
  stale window is 20 seconds. One 61-second test run made a perfectly healthy
  runner read as gone, which with the posture pinned turns every other shell
  call into a refusal. It fooled me into declaring it dead twice. The beat now
  runs on its own thread.
- **The runner keeps a log and survives a bad request.** Anything raising out of
  its serve loop used to end the process; a clean exit is not a failure, so the
  scheduled task did not restart it, and the only symptom was a shell refusing
  everything with nothing anywhere saying why. Failures are now logged to
  `<cage>/shell/runner.log` — with its start and stop — and serving continues.
