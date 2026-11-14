### Changed

- **A landing no longer stops the Builds that are running.** Until now every change to Thomas's server code that landed asked each running Build to stop where it was, restarted Thomas, and carried the Builds on afterwards. On 2026-11-10 one landing stopped ten Builds ten minutes into their work and cost each about five minutes; 25 landings began such a restart that day. Now landed code waits. The banner says newer code is ready and that it is waiting for a Build, and the Restart button loads it at once if you want it sooner. Thomas restarts by himself as soon as no Build is running.
- **The wait has a limit of 6 hours.** With Builds always running the restart would never come and no fix would ever load, so after 6 hours the Builds are asked to stop after all, as they were before. A second landing during the wait does not start the 6 hours again.

You said: "Yes, hold restarts".
