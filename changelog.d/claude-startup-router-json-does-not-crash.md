### Fixed
- **`startup_router.py --json` prints its report instead of crashing.** The trunk-divergence and fleet-stall reports are dataclasses, so the JSON output died with "Object of type Report is not JSON serializable" after all the startup checks had run; they now come out as plain JSON objects.
