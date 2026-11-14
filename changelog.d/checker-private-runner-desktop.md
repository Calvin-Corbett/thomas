### Fixed
- Give the checker’s test runner a private Windows desktop with scoped window-station access, then restore the station permissions after each launch. This prevents background-task launches from inheriting a desktop the runner cannot open.
