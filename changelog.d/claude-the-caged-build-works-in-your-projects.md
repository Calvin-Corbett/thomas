### Fixed

- **Build in the caged Thomas works in your projects.** The caged server runs as the
  cage account, whose home is not yours, so its Build rooted everything at an empty
  `~/.thomas` of its own and saw none of your projects. `THOMAS_OWNED_ROOT` now names
  that root. The caged server sets it to your `.thomas`, and Build's projects, scratch
  folder and task workspaces all follow it. `scripts/cage/enable_build_projects.ps1`
  gives the cage account access to exactly those folders and to each registered
  project outside them (such as `F:\DevHub`), and trusts them in git for both
  accounts. It needs no elevation. The Thomas repo itself stays behind the self-fix
  path. Proven on 2026-09-23: from the caged Thomas, Build listed your 250 projects,
  wrote a file into one, re-read it, and passed its check.
- `forge_code_projects.py` had passed 900 lines, so the monolith guard refused any
  change to it. Its conversation registry moved, unchanged, to
  `forge_code_conversations.py`, and every name still resolves from the old module.
