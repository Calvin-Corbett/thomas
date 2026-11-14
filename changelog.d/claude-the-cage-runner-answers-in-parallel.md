### Fixed

- **The caged shell answers every worker at once, not one after another.** The
  runner that executes Thomas's shell commands as the caged account used to run
  each request to the end before it read the next. Measured live: five self-fix
  workers shared it, so one worker's two-minute test run held every other
  worker's `git status` until that caller gave up with "the caged runner did not
  answer within 30s", and the workers spent their attempts waiting instead of
  working. Each request now runs on a thread of its own, up to the machine's
  measured limit (or `THOMAS_CAGE_RUNNER_WORKERS` if you set it; 8 when nothing
  is measured yet). A quick command beside a two-second one now answers in about
  0.2 seconds instead of after it, and ten one-second commands finish in about
  1.3 seconds instead of 10. A request is renamed to a working name before it
  runs, so no later poll can start it twice; one a stopped runner left
  half-done is answered with an error at the next start and never run again,
  because a command cut off halfway may already have changed things. Commands in
  the same green now run side by side too, so each gets its own job nested
  inside the green's: one timing out ends only itself, and settling a green
  still ends everything that green left running and nothing of another's.
