# Module: companion

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (kernel/contract/device/release infra real) |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code, has server routes   |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Companion app platform — the mobile/secondary device experience for Thomas.
3,284 lines across 15 files, zero placeholders. Defines a stable kernel/update
contract for customizable companion experiences. Includes device registry,
release management, module contracts, networking, runtime, studio, and audit.

## What Actually Works

- `kernel.py` — CompanionKernel with versioned kernel contract. Real.
- `contracts.py` — ModuleContract, UpdateBundleManifest, permissions. Real.
- `devices.py` — DeviceRecord, DeviceRegistry. Real.
- `releases.py` — ReleaseRecord, ReleaseRegistry. Real.
- `runtime.py` — Companion runtime. Real.
- Server routes: `companion_aiohttp.py`, `companion_runtime.py`,
  `companion_device_release_aiohttp.py` in server module.
- PWA surface: `companion.html` in web UI.

## Architecture Notes

The companion is how Thomas reaches you on mobile. It's a PWA (Progressive
Web App) that connects back to your Thomas instance. The kernel/contract
pattern means companion apps can be customized while keeping the host safe.

## Known Gaps

- Not assessed how complete the mobile experience actually is
- No STATUS.md existed before this one (added 2026-03-18)
