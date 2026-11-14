### Fixed

- **An Autopilot you approved stays Autopilot after a restart.** Approvals to
  raise Thomas's limits lived only in the running server's memory, so every
  restart quietly dropped Autopilot to a lower level while the screen still said
  Autopilot. Now the owner desk, which asks you at the Windows sign-in, also
  records what you approved, in a folder the caged Thomas can read but never
  write, and Thomas reads it back when it starts. Nothing is approved that you
  did not approve at the sign-in.
