### Fixed

- The Autopilot usage-limit tests now calculate their whole-second reset time once at import from the 429 body's 149460-second interval, so turns appended during the test can pause until that future reset instead of falling back to a retry counted from the turn.
