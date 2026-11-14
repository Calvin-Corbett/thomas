### Fixed

- **A server you stop from the tray menu stays stopped.** The health check read
  "stopped" as "crashed" and restarted it about a minute later with a "Thomas
  server restarted" toast. Stop Server now holds the health check off until you
  choose Start Server or Restart Server; a server that dies on its own is still
  restarted. A Restart you click while the health check is already waiting to
  restart the server no longer ends the tray as "taken over by another process",
  and a Restart that fails now tells you instead of leaving the icon red.
- **The server the tray starts no longer runs the idle model engines.** The direct
  launcher already switched off the code-issue, self-upgrade, UI-workflow,
  local-agent and workspace-sync engines; the tray copied your environment
  unchanged, so those four ran with the defaults (on) and made background model
  calls while you were away. The tray now sets the same six variables to `0`
  unless you exported them yourself. Checked on a scratch server the tray
  launched: all six read `0` in the child's environment.
- **"Auto-start with Windows" asks for a task Windows accepts, and only says so
  when it did.** The menu passed `ON_LOGON`, which `schtasks` rejects as an invalid
  schedule type, then saved "enabled" anyway. It now hands Windows a task file
  whose logon trigger names your account, not elevated, with no 72-hour limit,
  running `pythonw.exe -m thomas.tray_agent --port <yours>` from the checkout,
  which is the command line `run-ui.ps1` looks for when it stops a tray. The
  setting is saved only when Windows accepted the task, and turning it off is
  saved only when Windows removed it; when it refuses you get a notification
  instead of a silent tick. The `schtasks` calls no longer open a console window.
  `tray_state.json` starts at "off". This was tested against a mocked `schtasks`;
  the task file has not been handed to the real Task Scheduler yet, so whether
  Windows accepts it from a standard-user session is expected, not checked.
- **`start-tray-agent.ps1` only stops what serves its own port, and its logon task
  is no longer elevated.** It used to stop every `thomas.server`,
  `thomas serve` and tray process on the machine, for every port and checkout.
  It now stops a process that names `--port <yours>`, a tray started as
  `python -m thomas.tray_agent` with no port (that serves 8899), and a Thomas
  server that listens on your port without naming it, together with the Thomas
  processes above it (a venv's `python.exe` and the tray), so the tray cannot
  start the server again. The climb stops at the first process that is not Thomas
  or that names another port. `-InstallStartup` registers a per-user,
  non-elevated task with no time limit that runs `pythonw.exe -m
  thomas.tray_agent` directly (no console window) instead of an elevated
  PowerShell console, says so and exits 1 if Windows refuses it, and no longer
  deletes an existing task before it knows the new one was accepted. The check for
  the tray icon packages threw under Windows PowerShell 5.1 on a fresh install,
  before it could install anything or warn; it now runs, and if the packages do
  not install it says so instead of promising an icon.
- **The tray says plainly when it is running headless.** `pystray` and
  `win10toast` are not declared dependencies, so a fresh install has no tray icon,
  and the old log line was easy to miss. The agent now prints (once) and logs why
  it is headless and the `pip install` line that fixes it, with a `python.exe`
  path you can paste, quoted if it has spaces. It says "no notifications" only
  when `win10toast` is missing too. If the port is already served by another
  process, or the server does not start, that is on the console as well as in the
  log, and Start Server in the menu now tells you when the server did not start.
  `STATUS.md` no longer claims the tray tools are registered or that there is
  no launcher: the tray is opt-in (`run-ui.ps1 -Tray`), and the four
  `tray_agent_*` tools are retired and not registered.
- **A second tray for the same port exits instead of fighting the first.** It used
  to log "Server started" because it saw the first tray's port open, and the two
  coexisted until the newer server replaced the older. A lock file in
  `~/.thomas` now makes the second agent exit cleanly (exit code 0), and a server
  is not spawned over a port something else already serves. If the lock file
  cannot be opened or locked for any other reason, the agent runs without it
  rather than exiting.
- **A bad `THOMAS_TRAY_LOG_MAX_BYTES` (for example `8MB`) no longer stops the tray
  from starting.** The fallback caught the wrong exception types, so the agent
  died with a `ValueError` before it began.
- **The tray icon shows health, not just a live process.** Green means the port is
  answering, amber ("Thomas Not Responding") means the process is alive but the
  port is not, red means stopped. Boot is allowed 60 seconds instead of 30.

### Removed

- **The "Super-user mode" tray menu item.** It flipped a flag nothing read.
