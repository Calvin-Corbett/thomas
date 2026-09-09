# Core Overhead Lock (OS-Native)

This protects the shared Thomas overhead used by both REPL and Web UI.

Protected file list:
- `docs/core_overhead_manifest.json`

## Why

Accidental edits to core overhead can change how Thomas behaves globally.
This lock keeps regular edits easy while requiring intentional OS-native elevation for overhead edits.

## Guardrail Layers

1. OS-native file lock scripts:
- Windows (UAC-elevated PowerShell)
- macOS (`sudo`)

2. Edit guard in tooling:
- `scripts/forge/gates/core_overhead_guard.py`
- Blocks protected-file edits unless `THOMAS_CORE_OVERHEAD_UNLOCK=1`

## Windows

Lock:
```powershell
powershell -File scripts/lock_core_overhead_windows.ps1
```

Unlock for intentional edits:
```powershell
powershell -File scripts/unlock_core_overhead_windows.ps1
```

Notes:
- Run from an elevated PowerShell window (native UAC prompt).
- After edits, re-lock.

## macOS

Lock:
```bash
bash scripts/lock_core_overhead_macos.sh
```

Unlock for intentional edits:
```bash
bash scripts/unlock_core_overhead_macos.sh
```

Notes:
- Uses native `sudo` password prompt.
- After edits, re-lock.

## Intentional Edit Workflow

1. Unlock files using OS script.
2. Export unlock flag for guard:
```bash
THOMAS_CORE_OVERHEAD_UNLOCK=1
```
or on PowerShell:
```powershell
$env:THOMAS_CORE_OVERHEAD_UNLOCK = "1"
```
3. Make intentional changes.
4. Clear unlock flag.
5. Re-lock files.
