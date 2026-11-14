### Changed

- **While Thomas is paused, the engines, the idle sweep and scheduled jobs start nothing.** Each engine, the idle awareness sweep and the scheduler now ask the saved Pause switch on every cycle and skip the cycle while it is on, keeping their timers. Press Resume and the next cycle goes ahead with no restart. A scheduled job that falls due while paused waits and runs once you resume. Runs already going are not ended.
