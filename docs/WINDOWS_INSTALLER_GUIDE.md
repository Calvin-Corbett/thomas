# Windows Installer Guide

This guide is for maintainers who want to ship Thomas as a simple Windows installer.

## Goal

End users should install Thomas like a normal app:

1. Double-click `ThomasSetup_*.exe`
2. Click Next through the installer
3. Launch Thomas from Start Menu or Desktop icon

No manual Python/Codex setup steps are required during install. The first launch does need an
internet connection, because it builds the `.venv` and downloads the dependencies (see
"First-Run Experience").

## Build Requirements

- Windows 10/11
- PowerShell
- Inno Setup 6.3 or newer (`ISCC.exe`); `ThomasSetup.iss` stops with a clear error on older releases
  - <https://jrsoftware.org/isinfo.php>
- Python 3 and Git (the build stages the release bundle with `scripts/package_release.py`)
- Thomas repo checkout

## Build Command

From repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_installer.ps1
```

Or:

```cmd
build-installer.cmd
```

The version defaults to the one in `pyproject.toml`, which is the version `package_release.py`
stamps into the bundle. Pass `-Version <version>` only to override it. Commit first: the build
copies tracked files as they are on disk and warns when they differ from git.

Outputs:

- `dist/installer/Thomas_source_<version>.zip`
- `dist/installer/ThomasSetup_<version>.exe` (if Inno Setup is installed)

## Installer Contents

The installer packages the release bundle that `scripts/package_release.py` selects from the
git-tracked files. It never packages the working tree: a maintainer's `.venv`, `runtime/`,
`.thomas/`, `.env.local`, logs and untracked files stay on the build machine. The allow-list in
`package_release.py` (pinned by `tests/test_release_hygiene.py`) decides what ships. The bundle
includes:

- `launch-thomas.vbs` (consumer launcher used by Start Menu/Desktop shortcut)
- `run-ui.cmd` (console launcher for power users)
- `repair.cmd` (repair flow: tests your config and databases, reinstalls dependencies, and asks before it installs a tool or moves a damaged database aside)
- the `thomas/` package and the launcher scripts the files above call (`scripts/run-ui.ps1`,
  `setup.ps1`, `repair.ps1`, `bootdoctor.ps1`, `startup_recovery_watch.ps1` and the helpers they
  start). `tests/test_a_windows_installer_ships_the_release_bundle.py` reads those launchers and
  fails when one names a script the bundle does not ship

`ThomasSetup.iss` takes the staged bundle through `/DStageDir` and refuses to compile without it,
so it cannot be pointed at the working tree by accident. The installer is not code-signed, so
Windows SmartScreen will warn when it is run.

`Thomas_source_<version>.zip` is the same bundle plus `RELEASE_MANIFEST.json` (sizes, hashes and
counts of what was left out, never their names or the build folder), `RELEASE_SUMMARY.md` and
`THIRD_PARTY_NOTICES.md`. The installer does not install the manifest: nothing reads it at run
time.

Installing over an existing copy replaces the program files but keeps `thomas.toml` as it is,
because first-run setup writes your chosen default model into it.

## Stopping and Restarting Thomas

The Start Menu **Thomas** shortcut runs `launch-thomas.vbs`, which starts the server without a window,
so closing the browser leaves Thomas running. The first launch from the shortcut that works shows a
message saying so, once; it is remembered in `runtime/background-notice-shown`, so it appears only
when `runtime/` can be written to. The installer adds two Start Menu entries as the off switch:

- **Stop Thomas** runs `launch-thomas.vbs /stop`, which runs `scripts/run-ui.ps1 -Stop` and says what
  happened: Thomas is stopped, no Thomas was found to stop, or Thomas could not be stopped.
- **Restart Thomas** runs `launch-thomas.vbs /restart`, which replaces the running Thomas
  (`-Restart`). It is refused while a Build run is active.

From a terminal in the install folder the same is
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ui.ps1 -Stop` (or `-Restart`). `-Stop`
exits 0 when it ended a Thomas, 3 while a Build run is active (that Thomas is left running), 5 when it
found none and 6 when one would not stop; only `launch-thomas.vbs` turns these codes into messages.
It looks on port 8899 and on the port in `runtime/thomas.port` when that holds this copy's Thomas, or
only on the port you give with `-Port`. Each launch writes `runtime\logs\launch-<date>-<time>-<n>.log`
(the newest five are kept); a launch that fails shows a message with its exit code and the path of
its log.

The uninstaller runs `run-ui.ps1 -Stop` hidden before it removes the files, so uninstalling does not
leave a server with no window running from a deleted folder. It does not check the exit code: if a
Build run is active that Thomas is left running, so stop it with **Stop Thomas** after the Build, or
before uninstalling.

## Uninstall

Uninstalling removes the program files and the `.venv` the first launch built. It leaves what
Thomas stored while it ran (for example `runtime/` and `.thomas/` in the install folder), so
chats and settings are not deleted without being asked. Delete the install folder to remove them.
It also leaves the `thomas://` link handler that launching Thomas registers (see below): delete
`HKEY_CURRENT_USER\Software\Classes\thomas` if you want it gone, or launch another copy of Thomas,
which points it at itself.

## First-Run Experience

On first launch, the shortcut runs `launch-thomas.vbs`, which starts Thomas in the background. If
no Python 3.10+ is found it tries to install one with winget, then it creates `.venv` and installs
the server dependencies, which takes a few minutes. The very first launch also runs
`scripts/setup.ps1` in easy mode without prompts (see `Invoke-FirstRunQuickSetup` in
`scripts/run-ui.ps1` for the exact options). It does not install Node.js, the Codex CLI or Ollama:
those install only when the launch is started with `-InstallTools` or `THOMAS_AUTO_INSTALL_TOOLS=1`
(afterwards, `setup.cmd` installs them), and the launch says what setup is about to do. Without
Node.js the desktop shell is not installed, so web tabs stay blank on sites that refuse framing.

Two more things happen that the installer does not show. A launch writes the `thomas://` link
handler under `HKEY_CURRENT_USER\Software\Classes\thomas`, outside the install folder, only when none
exists or the copy it names is gone, and says so in the launch log (`-RegisterProtocol` points it at
the copy being launched on purpose; `-NoProtocolHandler` skips it). Starting it with the tray icon
installs `pystray`, `pillow` and
`win10toast` into the `.venv`. Thomas then opens `http://127.0.0.1:8899` in your browser, where Easy
Setup starts on a fresh install:

- auto dependency check
- easy path recommendation
- one-click `Auto Repair`
- personalization interview
