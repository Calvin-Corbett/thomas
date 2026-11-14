### Changed

- **While Thomas is paused, no new Build or Code run starts and the loops that start work by themselves wait.** A new Build or Code run is refused with "Thomas is paused. Press Resume on the Plugins page." and that sentence shows in the page that asked. The ratchet's daily run, the check for paused Builds, the retry of held hand-ins, the queue that starts planned Thomas projects, the carrying on of Builds after a restart and the branch sweep each skip their cycle and keep their timers, then go ahead on the next cycle after Resume. Runs already going are not ended.
