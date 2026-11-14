### Security

- **Thomas's shell now runs as the caged account, so it cannot edit his own
  code.** His protected files were behind a card and your PIN, but the shell
  had no such check: one `git checkout` or `python -c` wrote whatever the
  server's own account could write. That happened in front of us — a run put a
  protected file back with a shell command, around the card entirely.
  Words could not fix that, so it is fixed at the only layer that can. A small
  runner, started by Windows as `thomas-agent`, executes his shell commands.
  That account can read and run the repo and cannot write his own code, so a
  shell command simply cannot change him however it is spelled. The approved
  path — the card, your PIN, then the write — still can.
  - **When the cage is required and its runner is not answering, the shell
    refuses.** It never quietly falls back to running the command as you.
  - **Nothing is pattern-matched.** No list of forbidden commands to keep up to
    date; the operating system decides.
  - **Setup is two elevated commands you run once**, and your password is typed
    into Windows' own credential prompt, never stored by Thomas
    (`scripts/cage/grant_repo_access.ps1`, then
    `scripts/cage/install_shell_runner.ps1`).
  - Until you turn it on, `[tools] cage_shell` stays `auto`: caged when the
    runner is alive, as before when it is not. Setting it to `required` is what
    makes it a wall.
