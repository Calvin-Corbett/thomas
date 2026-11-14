### Fixed

- Thomas project preparation no longer refuses your start after a period without progress. It waits for completion or an actual error and logs elapsed seconds with the current preparation stage.
- Slow project advisory reads finish without a deadline instead of being skipped for taking too long. Explicit cancellation still releases start admission.
