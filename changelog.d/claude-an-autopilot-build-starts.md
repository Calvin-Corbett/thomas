### Fixed

- **A Build started on Autopilot runs.** Build's settings accepted Autopilot
  (autonomy 5), but the program a Build launches still only took 1 to 4. Every
  Autopilot Build stopped before doing any work, saying "build process exited 2",
  while the same request handed over from Chat worked. Both now read one list of
  levels, so they cannot disagree again.
