### Fixed

When your Build run records a provider overload or server error followed only by an exit-status error, Autopilot now waits for the provider instead of spending a self-continuation. A newer real error, such as a TypeError, still makes the run an ordinary failure.
