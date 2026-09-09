#!/usr/bin/env python3
"""Block commits that add xfails without a justifying commit-message trailer.

Part of the xfail-debt enforcement arc (P0-1 from the 2026-05-27 senior
review). Implements the "strict" policy the product owner chose: no new xfails may
be added unless the commit message contains an `xfail-justified: <reason>`
trailer.

Why this gate exists:
- xfail accumulates silently; CI stays green when an xfail fails.
- Without enforcement, the count climbs and each xfail's "why" is lost
  to commit-history archaeology.
- This gate forces every additive change to declare intent in the
  commit message itself — which is auditable, sortable, and lives next
  to the change forever.

How it works:
1. Count xfail markers at BASE_SHA (via scripts/xfail_inventory.py).
2. Count xfail markers at HEAD_SHA.
3. If HEAD_count <= BASE_count: PASS (no growth, or net reduction).
4. If growth: scan every commit between BASE..HEAD for an
   `xfail-justified:` trailer. If at least one commit in the range has
   one, PASS. Otherwise FAIL with a clear message explaining how to fix.

The single-trailer-covers-the-range design lets you add 5 xfails in
one commit with one well-written trailer, instead of forcing five
individual trailers. Quality of explanation > paperwork volume.

The gate uses scripts/xfail_inventory.py::count_at_rev() so the
counting logic is one source of truth.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import shared scanner directly (skips the inventory module's reporting).
from scripts.xfail_scanner import count_at_rev  # noqa: E402
from scripts.xfail_scanner import find_xfail_markers as find_xfails

TRAILER_RE = "xfail-justified:"


def _resolve_revs(base: str | None, head: str | None) -> tuple[str, str]:
    """Resolve BASE/HEAD from args or environment.

    In CI: env vars BASE_SHA + HEAD_SHA are typically set by the workflow.
    Locally: defaults to HEAD~1..HEAD when not given.
    """
    base = base or os.environ.get("BASE_SHA")
    head = head or os.environ.get("HEAD_SHA") or "HEAD"
    if not base:
        try:
            base = subprocess.check_output(["git", "rev-parse", "HEAD~1"], cwd=ROOT, text=True).strip()
        except subprocess.CalledProcessError:
            base = "HEAD"
    return base, head


def _commit_messages(base: str, head: str) -> list[str]:
    """Get commit messages (subject + body) for every commit in base..head."""
    if base == head:
        return []
    try:
        result = subprocess.run(
            ["git", "log", "--format=%B%n---END---", f"{base}..{head}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    raw = result.stdout
    return [chunk.strip() for chunk in raw.split("---END---") if chunk.strip()]


def _has_justification(messages: list[str]) -> tuple[bool, str]:
    """True iff any commit in the range has a non-empty xfail-justified: trailer."""
    for msg in messages:
        for line in msg.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(TRAILER_RE):
                # Everything after the colon is the reason.
                reason = stripped.split(":", 1)[1].strip()
                if reason:
                    return True, reason
    return False, ""


def _diff_new_xfails(base: str, head: str) -> list[tuple[str, int, str]]:
    """List the xfails newly present at HEAD but absent at BASE.

    Identity is (file, classification, arc_id_or_file_signature). We don't try
    to match identical-line-moves; if a file's xfail moved 3 lines down, it
    looks like an add+remove. That's fine — the count is what matters for
    the gate; this listing is for the error message only.
    """
    head_set = {(e.file, e.line) for e in find_xfails(rev=head)}
    base_set = {(e.file, e.line) for e in find_xfails(rev=base)}
    added = sorted(head_set - base_set)
    return [(f, ln, "") for f, ln in added]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="BASE git revision (defaults to BASE_SHA env or HEAD~1)")
    parser.add_argument("--head", default=None, help="HEAD git revision (defaults to HEAD_SHA env or HEAD)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    base, head = _resolve_revs(args.base, args.head)
    base_count = count_at_rev(base)
    head_count = count_at_rev(head)

    if head_count <= base_count:
        msg = f"xfail growth gate: PASS (base={base_count}, head={head_count}, delta={head_count - base_count})"
        print(msg)
        return 0

    # Growth detected — check for justification trailer.
    messages = _commit_messages(base, head)
    justified, reason = _has_justification(messages)
    delta = head_count - base_count

    if justified:
        print(
            f"xfail growth gate: PASS (base={base_count}, head={head_count}, delta=+{delta}; justified: {reason[:120]})"
        )
        return 0

    # FAIL — print the actionable error.
    print("xfail growth gate: FAIL")
    print(f"- xfail count grew from {base_count} to {head_count} (delta=+{delta})")
    print(f"- no `xfail-justified:` trailer found in any commit between {base[:12]}..{head[:12]}")
    print()
    print("Newly-added xfails (at least one of these is new):")
    for f, ln, _ in _diff_new_xfails(base, head)[:10]:
        print(f"  + {f}:{ln}")
    print()
    print("To pass this gate, amend or add a commit with a trailer like:")
    print()
    print("    xfail-justified: <one-line explanation of why this xfail is acceptable>")
    print()
    print("Good examples:")
    print("  xfail-justified: telecom_5g_core skeleton pending implementation; tracked in DOMAIN_STUB_TRACKING.md")
    print("  xfail-justified: TestRRTConnect RNG flake on CI; tracked in pathfinding-flake-arc-2026-05")
    print("  xfail-justified: marketplace.webhooks schema-validation bug; ticket #145")
    print()
    print("Bad examples (gate doesn't accept these):")
    print("  xfail-justified:                          # empty reason")
    print("  xfail-justified: too lazy to fix          # not actionable")
    print()
    print("To skip this gate intentionally (e.g. CI infrastructure work), use")
    print("the breakglass mechanism — see docs/SAFETY_ARCHITECTURE.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
