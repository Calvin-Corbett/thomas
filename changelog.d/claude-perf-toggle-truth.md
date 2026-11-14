### Security

- **The runtime-protection switch now reports the truth and can always be re-armed.**
  It decided whether protection was off by checking only that the flag file existed, so a
  flag that had expired, was unsigned, or was signed for another machine still counted:
  `status` said DISABLED while every gate correctly treated protection as ON, and `off`
  answered "already DISABLED" and refused to issue a fresh one — leaving no way to restore
  the override except deleting files by hand. It now asks the same validator the gates ask,
  and says so when a flag is present but not honoured.

### Fixed

- **`python scripts/runtime_protection_toggle.py off` works the way the docs say.** Run as
  a plain script it could not find its own authorisation module and blamed the working
  directory: "Run from the Thomas repo root" — which is where it already was.
