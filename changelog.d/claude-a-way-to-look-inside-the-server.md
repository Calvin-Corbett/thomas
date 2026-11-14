### Added

- **A way to look inside Thomas's server while it runs.** The server runs under its own Windows account, so nothing outside it could see what it was doing without an elevated tool. Two more "Look inside the cage" readings, answered only on this computer: `/api/inspect/profile?seconds=5` watches every thread of the server for a few seconds and lists where the busy ones were, and `/api/inspect/stacks` shows every thread in full at one moment. Both only read, and neither keeps anything.

You said: "You need to build a maintenance tunnel into Thomas's cage."
