### Fixed

- **The Thomas desktop icon no longer carries one machine's folder, and on the default port
  it starts Thomas when its port refuses a connection, instead of opening a browser window
  onto nothing.** `Thomas.vbs` is tracked in git and ships in the installer, but it was
  written with the folder it was generated in baked into it, including a Windows user name
  and its path layout. On a machine without that folder none of those paths existed: it
  skipped the desktop shell, started no server, and opened an app window on Thomas's local
  address with nothing listening. It now works out its paths to Thomas's own files from
  where the file sits. On the default port, when it falls back to a browser window and a
  connection to Thomas's port is refused, it starts Thomas first (through
  `launch-thomas.vbs` and `scripts/run-ui.ps1`) and says so; if either of those files is
  missing, or the icon is for another port or is the caged icon, it opens the browser window
  as before. The copy in git is what `scripts/thomas_app.py` writes for the default port, so
  installing on the default port leaves it unchanged, and a test keeps the two identical. If
  you install the caged icon (`python scripts/thomas_app.py --caged`), that test still reads
  the copy git holds, not the one on disk.

- **When the icon falls back to a browser window, it starts Thomas only if a connection to
  Thomas's port is refused.** Before it starts a new server, `run-ui.ps1` stops a Thomas
  server or tray agent on that port, so a server that accepts the connection but is too busy
  to answer in time (it happens while agents or builds are running) counts as running, and
  so does any odd reply or a probe that cannot be made. The desktop shell, which the icon
  normally opens, does its own health check and starts a server of its own when that check
  fails, including when it takes longer than 2.5 seconds; it does not run `run-ui.ps1`.

- **A start that reaches `run-ui.ps1` is asked about first when it could run setup, and the
  docs now list several things it can do without asking.** A machine counts as set up when
  `.venv\Scripts\python.exe`, `.venv\pyvenv.cfg` and `runtime\setup\last_setup.txt` all
  exist, the three files `run-ui.ps1` works from. There the start is hidden, with a short
  "Starting Thomas" notice, and it is the same `run-ui.ps1` run that `launch-thomas.vbs`
  makes. That run can still, without asking, write the `thomas://` link for your Windows
  account under `HKCU\Software\Classes`; install Python with winget if neither `python` nor
  `py` is on your PATH; run `pip install` if `aiohttp` or `httpx` cannot be imported; and
  start Ollama when `thomas.toml` points the default model at a local Ollama. If the server
  it starts comes up degraded or does not come up healthy, `run-ui.ps1` also starts Boot
  Doctor in a hidden window, again without asking (when no free port is found near the one
  it wants, it runs Boot Doctor's report step inside its own run instead). Boot Doctor can
  stop a Thomas process
  that is listening on the port but failing its health check, run `pip install` for
  Thomas's server packages, start a server of its own to test a repair, and change up to
  three known startup files in this folder. When a model is configured it can send the
  failure details to that model for a summary and, if Thomas is still down, let a model
  agent make up to three rounds of edits to a fixed list of startup files and folders in
  this folder, which means model calls. A machine missing any of the three files is asked
  first, because that start can build `.venv` again (deleting an incomplete one) and can
  run `setup.ps1`. The question lists what that can do: winget installs of Python, Node.js
  and Ollama; the Codex command-line tool through npm; Thomas's Python packages;
  `npm install` in `desktop/`, which downloads the Electron shell; a change to
  `default_model` in `thomas.toml`; the Thomas shortcuts on your Desktop and in your Start
  Menu, with a rewrite of `assets/thomas.ico` and `Thomas.vbs`; the `thomas://` link; and
  Boot Doctor if Thomas does not start. It defaults to No, and No starts nothing; on Yes
  the start runs in a PowerShell window that stays open. A test compares the question with the winget
  installs and npm calls that `setup.ps1` and `run-ui.ps1` make through the helpers they use
  now and with a table of other changes, and requires the words for each on a single line of
  the question, so a new winget package or npm call made through those helpers that the
  question does not name fails it. An install made another way is not found by that test.

- **Clicking the icon again while a start is under way asks before starting another.**
  `run-ui.ps1` normally starts the server, opens your browser and exits, so it is in the
  process list only while a start is under way. A `run-ui.ps1` of this folder that began
  in the last half hour counts as a start under way: if nothing is serving yet, the icon
  asks "Start Thomas again anyway?" (No is the default) and starts another only if you
  say Yes. One older than half an hour, such as a PowerShell window left open after
  `run-ui.cmd`, does not count, and neither does a shell that only mentions the script.
  If the process list or a start time cannot be read, nothing counts and the icon starts
  Thomas without asking whether another start is under way.

- **If Windows reports a refused launch of the unsigned desktop shell as an error, the
  icon now falls back to a browser and says why, instead of doing nothing.** The
  launcher started `electron.exe` and quit whatever happened. That error is now caught,
  the "install the desktop shell" prompt is skipped (installing again cannot unblock
  it), and Thomas opens in a browser with a note that the desktop shell could not be
  started. This has not been tried on a machine with Smart App Control turned on, and a
  process that starts and then closes on its own is not something the launcher can see.
  The "install the desktop shell" question, which downloads the Electron shell, now
  defaults to No like the other questions the icon asks; before, pressing Enter said Yes.

- **The desktop shell starts its server with the background engines off, as `run-ui`
  does.** Four self-improvement engines (code-issue, self-upgrade, UI-workflow,
  local-agent) default to on in code. They can run a heartbeat script and optional command
  checks, check configuration and release contracts, search image providers (Openverse,
  Unsplash and Pexels), and read local Ollama models and `git status`.
  `scripts/run-ui.ps1` sets all six engine flags to 0 for the server it starts, but the
  shell spawned its own server with the environment unchanged, so the Desktop icon left
  them running. The shell now gives its server the same six defaults; a flag you set
  yourself still wins, and an empty one is not a setting (the engines read it as unset,
  which leaves them on).

- **`scripts/README.md` says which launcher is which, and what a click on the icon can
  do.** `run-ui.cmd` is the canonical start and `launch-thomas.vbs` is the same script
  without a console window. The installer's Thomas icons use `launch-thomas.vbs` and its
  Console icon uses `run-ui.cmd`; `Thomas.vbs` is the icon `python scripts/thomas_app.py`
  writes.
