# Windows Installer Guide

This guide is for maintainers who want to ship Thomas as a simple Windows installer.

## Goal

End users should install Thomas like a normal app:

1. Double-click `ThomasSetup_*.exe`
2. Click Next through the installer
3. Launch Thomas from Start Menu or Desktop icon

No manual Python/Codex setup steps are required during install.

## Build Requirements

- Windows 10/11, or GitHub Actions `windows-latest`
- PowerShell
- Inno Setup 6 (`ISCC.exe`)
  - <https://jrsoftware.org/isinfo.php>
- Thomas repo checkout

## GitHub Release Build

The public release workflow is `.github/workflows/windows-installer.yml`.

Use **Actions -> Windows Installer -> Run workflow** and pass the release tag,
for example `v0.14.60`. The workflow:

- installs Inno Setup on the hosted Windows runner
- runs `scripts\build_windows_installer.ps1`
- uploads `ThomasSetup_<version>.exe` and `Thomas_source_<version>.zip` as workflow artifacts
- uploads the same files to the GitHub release when a tag is provided

The workflow also runs automatically when a GitHub release is published.

## Local Build Command

From repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_installer.ps1 -Version 0.14.60
```

Or:

```cmd
build-installer.cmd -Version 0.1.0
```

Outputs:

- `dist/installer/Thomas_source_<version>.zip`
- `dist/installer/ThomasSetup_<version>.exe` (if Inno Setup is installed)

## Installer Contents

The installer uses `installer/ThomasSetup.iss` and includes:

- `scripts\first-run.cmd` and `scripts\first_run_wizard.ps1` (visible first-run setup)
- `launch-thomas.vbs` (consumer launcher used by Start Menu/Desktop shortcut)
- `run-ui.cmd` (console launcher for power users)
- `repair.cmd` (one-click repair flow)
- project files excluding heavy/dev artifacts (`.git`, `.venv`, `node_modules`, runtime caches, etc.)

## First-Run Experience

After the installer copies files, it offers **Finish setup and launch Thomas now**.
That runs `scripts\first-run.cmd` in a visible window so users can see progress and errors.
The first-run wizard:

- checks for Python 3.10+
- offers to install Python 3.12 through `winget` when available
- creates `.venv`
- installs `.[server,repl]` dependencies
- writes default Thomas setup state
- launches Thomas on `127.0.0.1:8899`

Logs are written to `runtime\logs\first_run_wizard.log`.

After setup is complete, Start Menu and desktop shortcuts run
`launch-thomas.vbs`, which starts Thomas hidden and opens the browser. If `.venv`
or `runtime\setup\last_setup.txt` is missing, the launcher falls back to the
visible first-run wizard instead of failing silently.
