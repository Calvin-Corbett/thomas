# PLAN for DESKTOP-CODE-SIGNING

- Owner: unassigned
- Status: up_for_grabs
- Updated At: 2026-08-26T17:21:57+00:00
- Scope: desktop,scripts/run-desktop.ps1,docs/DESKTOP.md

## Summary

BLOCKER found 2026-08-26. Windows Smart App Control moved to ENFORCEMENT (VerifiedAndReputablePolicyState=1, UsermodeCodeIntegrityPolicyEnforcementStatus=2) and now blocks the unsigned electron.exe with An Application Control policy has blocked this file. The app ran and was fully verified for hours before the flip, no code of ours changed, and the binary is simply NotSigned. Shipping the desktop shell needs a packaged code-signed build (electron-builder plus a certificate, EV or OV-with-reputation for SAC to accept it). Do NOT disable or bypass the policy, that is an owner decision and turning SAC off on Windows 11 is effectively one-way. Until signed the desktop app cannot launch on this machine. run-ui.cmd and the browser UI are unaffected

## Approach

- Document the intended implementation steps here.
