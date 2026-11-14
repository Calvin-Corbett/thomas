### Fixed
- `/api/health` no longer reads the preferences database on the server's event loop. On 2026-10-27 the server's freeze dumps showed health checks opening that database (checking its schema each time) while it was busy, and every other request waited behind them for up to 30 seconds, so the server answered nothing for minutes at a time.
