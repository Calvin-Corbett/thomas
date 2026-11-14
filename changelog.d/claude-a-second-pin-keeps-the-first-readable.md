### Fixed

- **Writing a second pin no longer locks everyone out of the first.** The first
  real pin run on 2026-09-22 left the cage posture pin readable by nobody. Even
  its permissions could not be listed. The folder step re-applied the folder's
  rights to every file inside, and on a file those rights do not apply. The error
  was swallowed, and the pin was left with no permissions at all. For the posture
  that fails safe: an unreadable pin reads as "required". For the card catalogue
  it would not: an unreadable catalogue pin reads as tampered, and every PIN
  prompt would refuse. Re-pinning the posture would have caused exactly that. The
  folder is now locked on its own, and each pin inherits from it. A test
  reproduces the failure without elevation, on a folder it owns.
- **Repairing it took one more fix.** A pin left with no permissions at all
  cannot be reset even by an elevated script until ownership is taken back.
  Windows PowerShell also turned the first warning from a system tool into a
  fatal error, so the repair stopped at the damaged pin. The pin script now
  takes ownership first and judges each step by its exit code. The live posture
  pin reads `required` again, from the file itself.
