# Prepared owner taps

Each script here patches one or more **protected** files (listed in
`agent_safety.toml` and sha256-pinned in `scripts/forge/gates/enforcement_manifest.json`)
and refreshes the manifest hash. They run only inside an owner breakglass
window, and each was exercised on a copy of its target before it was written
down here. They are prepared work, not applied work: nothing in this directory
changes behaviour until the owner runs it.

| Script | What it changes | Proof it was exercised |
|---|---|---|
| `tap_guard_seam_hint.py` | `monolith_guard.py` prints the seam finder's advice under every Python violation | copy patched, advice printed for a real oversized file, HTML skipped, missing path survived |
| `tap_changelog_fragments_gates.py` | `changelog_gate.py` and `release_update_gate.py` accept a staged `changelog.d/` fragment as the changelog update | copy reported `changelog_staged: true` for a staged fragment; original reported `false` |
| `tap_growth_guard_moves.py` | `commit_growth_guard.py` treats a new file made of lines deleted elsewhere in the same commit as a move, not growth | copy passed a split and still failed a genuinely new 360-line file |
| `tap_batch_2026-09-07.py` | runs the three above, removes the stale `repl.py` waiver from the monolith baseline, drops the xfail on the move test, and verifies | the batch itself |

## The window

```bash
python scripts/breakglass_window.py on        # the owner taps Windows Hello
python scripts/forge/taps/tap_batch_2026-09-07.py
# commit the result with the skip env the breakglass recipe documents, then
python scripts/breakglass_window.py off
```

The four together answer one steer from the owner on 2026-09-07: another agent's
concurrent work is to be understood and designed around, never flagged; the
shared surfaces these gates enforce were the collisions, so the gates learn.
