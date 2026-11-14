### Changed
- **Thomas reaches a working server about three times sooner.** On a quiet machine a warm start went from 22.9 s to about 6.7 s. The start no longer launches PowerShell to find who owns the port (2.2 s, read from the OS socket table now), plugin routes are published once instead of 59 times, and the theme scan, numpy and playwright load when first used instead of at boot.
- **The desktop window shows "Starting up" with a running clock instead of an empty page** while the server boots, and each launch appends its timings to `startup_timing.jsonl` in the app's profile folder.
