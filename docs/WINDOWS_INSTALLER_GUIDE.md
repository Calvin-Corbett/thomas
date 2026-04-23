# Windows Installer Guide

This guide is for maintainers who want to ship Thomas as a simple Windows installer.

## Goal

End users should install Thomas like a normal app:

1. Double-click `ThomasSetup_*.exe`
2. Click Next through the installer
3. Launch Thomas from Start Menu or Desktop icon

No manual Python/Codex setup steps are required during install.

## Build Requirements

- Windows 10/11
- PowerShell
- Inno Setup 6 (`ISCC.exe`)
  - <https://jrsoftware.org/isinfo.php>
- Thomas repo checkout

## Build Command

From repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_installer.ps1 -Version 0.1.0
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

- `launch-thomas.vbs` (consumer launcher used by Start Menu/Desktop shortcut)
- `run-ui.cmd` (console launcher for power users)
- `repair.cmd` (one-click repair flow)
- project files excluding heavy/dev artifacts (`.git`, `.venv`, `node_modules`, runtime caches, etc.)

## First-Run Experience

On first launch, the shortcut runs `launch-thomas.vbs`, which starts Thomas in the background and opens the onboarding flow:

- auto dependency check
- easy path recommendation
- one-click `Auto Repair`
- personalization interview
