### Fixed

- When a landed-code drain clears without restarting the server, resume the Build runs that yielded for it. Retry while a yielded result is still being saved or Code capacity is unavailable, and reuse the existing carry-on checks before starting a continuation. Recheck recovery admission after acquiring the Build launch lock so shutdown or a new drain prevents a queued continuation from starting.
- Keep the restart lifecycle test's persistence in its temporary directory and skip unrelated tool and optional-route discovery, while still starting the server and exercising its automatic restart recovery.
