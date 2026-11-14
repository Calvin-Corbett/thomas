# xfail Policy

## TL;DR

Every new `pytest.mark.xfail` requires a one-line justification in the commit
message:

```
xfail-justified: <one-line reason; reference a tracking doc or ticket if applicable>
```

`scripts/forge/gates/xfail_growth_gate.py` enforces this — locally via
pre-commit and server-side via `.github/workflows/gates.yml`. Without
the trailer, the gate blocks any commit that grows the xfail count.

## Why this policy exists

Before this policy (read: today), `xfail` was used as a CI relief valve:
when a test failed, someone marked it `xfail` and the build went green.
The reason text was free-form, often unhelpful, and impossible to scan
for "what should be cleaned up next."

The cost stayed invisible until the 2026-05-27 senior review counted
**60 xfails across 59 test files**, with batches of 16-25 added in single
"step-up" commits. Each one is a real failing test that someone deferred
without an explicit "this is fine because X" attached. The policy makes
that explicit-because clause mandatory.

## Allowed xfail categories

Use these in your `xfail-justified:` trailer. The inventory tool
classifies xfails by matching reason text against these categories:

| Category | When to use | Example reason |
|---|---|---|
| **domain-stub** | Module is `skeleton`/`placeholder`/`stub`; tests document the future API | `Agriculture module skeleton pending implementation (DOMAIN_STUB_TRACKING.md)` |
| **step-up** | Test coverage was expanded; pre-existing bug surfaced. Real bug to fix later. | `Search domain pre-existing bug surfaced by mixed-19 step-up run; tracked in marketplace-inventory-2026-05` |
| **flake** | Test is nondeterministic (RNG, timing, race). Not a real product bug. | `TestRRTConnect RNG flake on CI; pathfinding-flake-arc-2026-05` |
| **tracked** | Already documented elsewhere; xfail is a pointer to the ledger | `Tracked in docs/ops/remediation/STUB_TRACKING.md` |
| **platform-specific** | Test runs on N-1 OSes; cleanest expression in xfail form | `Windows-only feature; skipif equivalent` |

Anything else gets classified as `other` and shows up at the top of
triage reports.

## Workflow

### Adding a new xfail

1. Write the xfail in your test as usual:
   ```python
   @pytest.mark.xfail(reason="<descriptive reason text>", strict=False)
   def test_something():
       ...
   ```
2. In your commit message, add a trailer:
   ```
   test(arc-name): describe the change

   <body>

   xfail-justified: <category>: <one-line why>
   Thomas-Agent: <your name>
   ```
3. The pre-commit hook (`xfail-growth-gate`) checks the trailer exists.
   If you forget, the gate fails with a message showing the new xfails
   it detected.

### Triaging existing xfails

Run the inventory tool:

```bash
python scripts/xfail_inventory.py            # human summary
python scripts/xfail_inventory.py --by-arc   # grouped by arc-id
python scripts/xfail_inventory.py --json     # machine-readable
```

Output classifies every xfail by category and shows the introducing
commit + date. Sort by:
- `commit_date` ascending → oldest unresolved xfails first (P0 cleanup)
- `arc_id` → batch cleanup by the original arc

### Removing an xfail

When the underlying bug is fixed:
1. Delete the `@pytest.mark.xfail` decorator (or `pytestmark = ...` line)
2. Confirm the test now passes locally
3. Commit normally. The gate sees a *decrease* in count and passes
   without requiring any trailer.

If a test was marked `xfail(strict=False)` and starts passing
unexpectedly, it does NOT fail CI (because `strict=False` makes
unexpected passes silent). Consider switching long-lived xfails to
`strict=True` so passing tests bubble up as XPASS noise that gets
investigated.

## Gate behavior

### Pass conditions
- xfail count at HEAD ≤ count at BASE (no growth, or net reduction)
- Count grew BUT at least one commit in BASE..HEAD has a non-empty
  `xfail-justified:` trailer

### Fail conditions
- Count grew AND no commit between BASE..HEAD has the trailer
- Trailer present but reason is empty (`xfail-justified:` with nothing after)

### Bypass
The gate's only bypass is the `breakglass` mechanism (see
`docs/SAFETY_ARCHITECTURE.md`). That requires Windows credential auth
on the product owner's device, leaves an audit trail in `.git/thomas_skip_audit.jsonl`,
and is rate-limited to 3 uses per agent per 24h. Use only when the
xfail-growth-gate misfires (e.g. the gate itself has a bug, or
infrastructure changes legitimately add xfails to tests-of-tests).

## The first 60 (existing inventory at 2026-05-27)

| Arc | Count | Category | Cleanup priority |
|---|---|---|---|
| `79f59ef4` (2026-03-18) | 25 | domain-stub | Low — these are agriculture / supply_chain / travel domain skeletons; intentional per DOMAIN_STUB_TRACKING.md |
| `mixed-19` (2026-05-22) | 16 | step-up | **High** — search / serialization / setup_wizard / siem bugs surfaced by coverage expansion |
| `mixed-20` (2026-05-22) | 9 | step-up | **High** — smart_home / social domain bugs |
| `mixed-22` | 3 | step-up | Medium — templates |
| `mixed-17` | 3 | tracked | Already documented; just needs follow-through |
| `mixed-21` | 2 | step-up | Medium — telecom |
| `pathfinding` | 1 | flake | Low — known RNG flake |

**Recommended first cleanup pass:** the `mixed-19` arc (16 xfails). All
share a common reason string ("Pre-existing search/serialization/setup_wizard/siem
domain-module bugs surfaced by step-up"). Fixing one domain's bugs
typically fixes the rest in that domain (shared root cause).

## Future-proofing

If the inventory grows past 80 xfails total, treat that as a signal that
the policy needs tightening (e.g. add per-arc caps, require ticket
references not just reason text). The growth gate gives one number to
watch; the inventory tool gives one report to read.

## References

- [`scripts/xfail_inventory.py`](../scripts/xfail_inventory.py) — AST-based scanner + report generator
- [`scripts/forge/gates/xfail_growth_gate.py`](../scripts/forge/gates/xfail_growth_gate.py) — enforcement gate
- [`tests/test_xfail_growth_gate.py`](../tests/test_xfail_growth_gate.py) — tests for both
- [`.github/workflows/gates.yml`](../.github/workflows/gates.yml) — server-side mirror (job: `xfail-growth-gate`)
- [`docs/SAFETY_ARCHITECTURE.md`](SAFETY_ARCHITECTURE.md) — the safety architecture this gate plugs into
- [`docs/ops/remediation/DOMAIN_STUB_TRACKING.md`](ops/remediation/DOMAIN_STUB_TRACKING.md) — existing tracking doc for the domain-stub xfail category
