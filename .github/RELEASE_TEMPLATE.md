# Thomas Release Notes

## Download

- Windows installer: `ThomasSetup_<version>.exe`

## What changed

- TBD

## Install and support notes

- Fresh install path: download the Windows installer, run it, keep launch checked, then finish Easy Setup in the browser.
- If setup fails, run `support.cmd` and attach the ZIP from `runtime\support\` to the issue.
- Thomas defaults to `127.0.0.1:8899`; firewall prompts should be checked against `docs/NETWORKING_AND_FIREWALL.md`.

## Validation checklist

- [ ] Windows installer workflow passed.
- [ ] Public publish preflight passed with `--strict --deep`.
- [ ] Repo hygiene passed with a clean worktree.
- [ ] Release asset is EXE-only unless a future release explicitly changes packaging.
