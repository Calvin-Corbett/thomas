### Fixed

- A refused Office state update now answers in JSON (`{"ok": false, "error": ...}`), as its successes already did, instead of a bare line of text; a page reading the route gets one shape either way.
