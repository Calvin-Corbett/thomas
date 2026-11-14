### Security

- **The cage's own switch moved somewhere Thomas cannot reach it.** Requiring
  the cage was going to be a setting in `thomas.toml`, and that would not have
  held: the server runs as you, so it can rewrite any file in the repo at any
  moment, and the protected-files gate only notices afterwards, in a diff. The
  posture is now pinned at `C:\ProgramData\ThomasCage\posture`, written by an
  elevated script and granted write access for administrators only. An
  unelevated process running as you — which is what Thomas is — cannot change
  it, because Windows hands that process a token where Administrators is
  deny-only. You can raise or drop it whenever you like, behind one prompt.
  - **The pin is a floor, not a fixed value.** The environment and the config
    may ask for *more* cage than is pinned, never less.
  - **Pointing `THOMAS_CAGE_ROOT` somewhere empty does not retire a pin.** The
    posture is read from the default location as well as the configured one,
    and the stricter of the two wins.
  - **A byte order mark cannot silently disable it.** A BOM is not whitespace,
    so the value would stop matching and the wall would quietly become a
    suggestion; the file is written without one and read as `utf-8-sig`.
  - **A pin nobody can read is treated as the strictest posture**, not as no
    pin. Only an administrator can put that file there, so its presence is the
    decision — a typo, a truncated write or an unreadable byte must not be the
    difference between a wall and nothing.
  - `scripts/cage/pin_posture.ps1` writes it, `-Remove` takes it away.
- **The setting that was going to carry this would have done nothing.** The
  `cage_shell` field had been added to `ToolsConfig`, but that loader is built
  from explicit keyword arguments, so the key would have been read out of
  `thomas.toml` and dropped — a switch that looked live and changed nothing.
  It is gone rather than half-wired.
- **Granting the caged account access got faster, though it is still slow.**
  The setup walked every file in the repo with `icacls /T`, including `.venv`,
  `.git` and every benchmark workspace: 19 minutes and 1,125 seconds of CPU on
  this machine for one of its three steps. Dropping `/T` and letting the
  inheritable ACE propagate brought that step under six minutes — not to
  seconds, as first claimed here. Windows propagates an inherited ACE by
  walking the tree too; `/T` only adds per-file work on top of it. The enabler
  also takes `-SkipPermissions` now, because those permissions do not change
  between attempts and re-applying them dominated every retry.
