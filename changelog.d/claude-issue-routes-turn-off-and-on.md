### Changed

- **The routes that take failure reports from the Chat, Code and Work pages can now be turned off and on from the Plugins page.** Turning them off removes only `GET` and `POST` on `/api/issues`; the failure list Thomas writes to directly, and reads when it reviews its own work, is not touched.
