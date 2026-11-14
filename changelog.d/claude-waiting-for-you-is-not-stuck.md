### Fixed

- **A task waiting for your password is no longer failed as stuck.** On
  Autopilot, Thomas reached one of his protected files and the password prompt
  opened on your screen. The watchdog fails any background task that shows no
  progress for 135 seconds, and it counted his wait for you as being stuck. The
  task was marked failed while the prompt was still open, so you were being
  asked to approve work that had already been abandoned. Now, while a password
  prompt or question card is waiting on you, the clock stops. Once you answer,
  the task gets its full grace period again from that moment.
