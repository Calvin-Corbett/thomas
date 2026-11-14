# Module: tray_agent

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | wip                                                    |
| Last assessed    | 2026-09-30                                             |
| Assessed by      | claude-sonnet-5-5 (tray-agent audit fixes)             |
| Used in prod     | opt-in only: `python -m thomas.tray_agent`, `scripts/run-ui.ps1 -Tray`, `scripts/start-tray-agent.ps1` |
| Has real tests   | yes: `tests/test_tray_agent_*.py`, `tests/test_tray_launcher_source.py` |
| Blocking issues  | none in the module; see Known Gaps for what needs your decision |

## What This Is

The tray menu shows a Background Thomas section that only reads its health and project listing.

A background process that starts the Thomas server on a port (default 8899),
restarts it if it crashes, and, when `pystray` and Pillow are installed, shows a
tray icon: green = serving, amber = process alive but its port is not answering,
red = stopped. The menu can open Thomas, start / stop / restart the server, toggle
the Windows logon task, and open the log.

## Honest Assessment

- **Not the default.** `run-ui.ps1` starts the server directly unless you pass
  `-Tray`. No logon task exists until you tick "Auto-start with Windows" in the
  menu or run `scripts/start-tray-agent.ps1 -InstallStartup`. Both ask Windows for
  a per-user task (a logon trigger naming your account) that runs
  `pythonw.exe -m thomas.tray_agent --port N` without a console window, not
  elevated, with no time limit. Neither has been run against the real Task
  Scheduler (see Known Gaps).
- **The icon needs packages Thomas does not declare.** `pystray` and `win10toast`
  are not in `pyproject.toml` (only Pillow is), so a fresh install runs the agent
  headless: the server is still served and restarted, but there is no icon and no
  notification. The agent prints and logs that on start, with the pip command to
  fix it. `run-ui.ps1 -Tray` and `start-tray-agent.ps1` try to pip install them
  and, in `start-tray-agent.ps1`, warn when that fails.
- **Stop Server stays stopped.** The healthcheck only restarts a server that died
  on its own; Start Server or Restart Server hand it back.
- **Idle model calls are off.** The server the tray starts gets the same
  `THOMAS_*_ENGINE_ENABLED=0` defaults as the direct launcher, unless you export
  them yourself. The Electron launcher (`desktop/main.js`) does not; that is
  outside this module.
- **One agent per port.** A lock file in `~/.thomas` makes a second agent exit
  instead of starting a second server over the first.
- **Agent tools are retired.** `tools.py` defines four `tray_agent_*` tools, but
  nothing registers them (`thomas/server/tool_extensions.py` does not list this
  module, and `tests/test_tool_extensions.py` requires that), and each one imports
  a function `agent.py` never defined. The names still appear in
  `thomas/server/chat_tool_policy_model.py`.

## Known Gaps

- Declare an optional `tray` extra (`pystray`, `pillow`, `win10toast`) in
  `pyproject.toml`, or stop offering the tray to a fresh install.
- Delete `tools.py` and the four `tray_agent_*` names in
  `chat_tool_policy_model.py`, or implement `get_status` / `show_notification` /
  `start` / `stop` in `agent.py` and register them. Deleting is the smaller change.
- The logon task has only been tested against a mocked `schtasks`; its task file
  was never handed to the real Task Scheduler. If Windows refuses it, the menu
  says so and records nothing. To check the file without registering anything,
  call `RegisterTask` with `TASK_VALIDATE_ONLY` (flag 1) on the `Schedule.Service`
  COM object. That only validates the schema: a validate-only run from a
  non-elevated session accepted both a per-user trigger and one that names no user.
- A logon trigger that names no user (what `schtasks /Create /SC ONLOGON` builds)
  is expected to need administrator rights, but that was never checked, and it is
  not the only reason for the task file: `schtasks` has no flag for the time limit
  or the working directory. The real check is to tick Auto-start in a
  standard-user session and see whether the task registers.
- The tray icon and its menu (pystray) have never been run here: pystray is not
  installed in this environment. Only the Pillow drawing and the status logic are
  tested; the menu actions are plain methods tested without pystray.
