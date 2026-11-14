### Fixed

- Your elevated window setup now keeps the test-runner account description within Windows' 48-character limit and grants the checker batch-logon rights before it registers its scheduled tasks.
- The setup gives the checker and runner accounts recursive read/execute access to the base Python named in the live checkout's `.venv/pyvenv.cfg` and to `scripts/cage` and `scripts/forge/gates`, even when those service directories do not inherit the checkout ACL. A non-elevated `-Plan` regression check verifies the grants and their ordering.
