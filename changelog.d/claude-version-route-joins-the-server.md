### Changed

- **The version route now belongs to the server itself.** `GET /api/version`, which the boot checks and the debug dock ask, moved out of the model routes into the server's own list, so turning the model routes off later cannot take it away. Nothing you see changes: it answers the same version, code-freshness and dev or prod fields as before.
