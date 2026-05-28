# Runtime Protection Bypass Fix (2026-05-27)

## Problem

`thomas/tools/filesystem.py::_is_protected_runtime_path()` blocks agent writes
to `thomas/{tools,agent,core,server}/`, `scripts/`, and policy files — but it
honored a flag file at `runtime/.runtime_protection_disabled` whose path was
NOT in any protected list. An agent could call
`fs.write_file('runtime/.runtime_protection_disabled', '')` and disable all
runtime protection, making the OS-auth promise in `docs/SAFETY_ARCHITECTURE.md`
fiction.

Reproduce (pre-fix):

```
python -c "from pathlib import Path; Path('runtime').mkdir(exist_ok=True); (Path('runtime')/'.runtime_protection_disabled').write_text(''); from thomas.tools.filesystem import _is_protected_runtime_path; print(_is_protected_runtime_path(Path('.'), Path('thomas/core/_db.py')))"
```

Pre-fix: prints `None` (allows write). Post-fix: prints
`BLOCKED: 'thomas/core/_db.py' is inside protected runtime directory ...`.

## Fix (landed in this PR)

1. **Path protection**: added `runtime/.runtime_protection_disabled` and
   `runtime/.runtime_protection_key` to `_HARDCODED_PROTECTED_FILES`. The three
   write tools (`fs.write_file`, `diff.create`, `diff.apply_patch`) all share
   the `_is_protected_runtime_path` gate, so this blocks all of them.
2. **Signed content**: `_is_runtime_protection_disabled` now requires
   HMAC-SHA256-signed JSON flag content. `scripts/runtime_protection_toggle.py`
   generates a per-install key on first `off`, signs the flag against it, and
   re-uses the key across toggles. Validation is fail-closed.
3. **New tool**: `fs.write_protected_file` wires the previously-dormant
   `allow_native_auth_override` kwarg (PR #21 commit ab049bf9) to a real caller.
   It requires a non-empty `reason` and pops a Windows credential dialog via
   `request_native_authorization`.
4. **Audit**: `shell.exec` is the documented exemption (disabled by default).
   `thomas/integrations/*` and marketplace modules register no new write tools;
   they inherit the gates. Internal helper writes (`database.py`,
   `dep_scanner_*`, `sandbox_helpers`) use internal paths, not agent-controlled.

## Tests

`tests/test_filesystem_protection_adversarial.py` (21 new) — covers every
forged-flag variant, both protected-file paths refused via fs.write_file,
unprotected runtime/ subpath still writable, new tool refused/allowed paths,
toggle script payload-byte equality, key persistence.

`tests/test_native_auth_filesystem_guard.py::test_runtime_protection_disabled_flag_still_works`
updated to use signed format (it previously pinned the buggy behavior).

All 74 tests across the four named suites pass.

## Status

active — finishing PR now; Codex took follow-up units on gates.yml repair and
monolith_filename_guard cleanup (see msg-20260527215054-claude).
