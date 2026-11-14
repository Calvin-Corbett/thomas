### Changed

- **Pause and Resume can be pressed by anyone, with three addresses that need no administrator rights.** A new Pause and Resume entry, which cannot be turned off, answers `GET /api/thomas/pause`, `POST /api/thomas/pause` (with an optional reason) and `POST /api/thomas/resume`. Each says whether Thomas is paused, since when, why, and how many runs are still going. Pausing keeps the server and Chat running and stops everything Thomas starts by himself; runs already going finish. The choice is kept in your data folder, so a restart does not undo it.
