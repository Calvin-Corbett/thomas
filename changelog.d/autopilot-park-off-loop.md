### Fixed
- Autopilot's periodic parked-project scan reads the park list and stored conversations in worker threads instead of blocking the server event loop. Park-file checks and park-list or conversation updates in that scan also run off-loop.
- Park maintenance records timed `autopilot.*` offload receipts so the slowest calls can be inspected alongside other server work.
- Local-project listing, detail, edit, chat context, and sharing routes now offload project catalogue refreshes, registry reads and writes, dossier builds, generated-project lookups, library file reads, and workspace saves; import also compares resolved project roots off-loop. `local_projects.*` timing receipts include the background catalogue build and expose their slowest calls without stopping other requests.
- Chat exports read and render sessions in a worker, including filename generation; `chat_export.build` timing receipts show how long that work takes without holding up other requests.
- Code previews offload conversation lookup, source and target file checks, and the pruned allowlist walk; `preview.*` receipts expose their duration.
- Local-project registry mutations hold one per-app lock across refresh and save; registry writes replace a completed temporary file instead of truncating the live registry. Overlapping layout updates keep both saved positions.
