### Fixed

- **A caged command no longer leaves processes running behind it.** After a
  self-fix run ended on 2026-09-22, a Python process it had started was still
  running as the cage account, with the self-fix's private copy as its working
  folder. The copy couldn't be removed, and agent code simply outlived its task.
  Stopping a command on Windows stops the command's shell, not what the shell
  started. Now:
  - **Every caged command runs in a Windows job.** Commands run inside a private
    copy share that copy's job, and the job is ended when the copy is cleared
    away. A command that times out takes everything it started with it. If the
    cage runner itself dies, a copy's processes die with it.
  - **A command that leaves something running no longer hangs the runner.**
    Output now goes to a file, not a pipe. A background process used to inherit
    the pipe, and the runner then waited for that process until the command's
    timeout, and after it.
  - **A request the runner fails on is answered.** It used to stay in the queue
    and was retried several times a second until the caller gave up.
  - **A private copy that is still held when its run ends is cleared by the next
    sweep**, instead of waiting a day.
