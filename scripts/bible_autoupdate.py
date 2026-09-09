#!/usr/bin/env python3
"""Bible post-commit advisory (non-fatal).

Invoked by the local ``post-commit`` hook after every commit:

    python scripts/bible_autoupdate.py --bible docs/THOMAS_BIBLE.md --repo . --sha HEAD

It is purely ADVISORY: it never edits the bible and never fails the commit
(always exits 0). It runs hash-based drift detection
(``scripts/forge/bible_drift.py``) and logs:

  * stamped sections whose covered files changed since they were stamped
    (``status=green`` -> "drifted", needs a human/agent to re-verify and re-stamp);
  * stamped sections whose covered paths no longer exist on disk;
  * a note when zero sections are stamped (drift detection is dormant).

Why advisory and not auto-bump: the surviving bible model is hash-based drift
detection. Automatically refreshing a section's stamp hash on every commit that
touches its area would make drift impossible to detect. Re-verification is a
deliberate act (re-stamp the section), not a silent side effect of committing.
The older "bump Last verified on touch" autoupdate script was never committed
to this repo; this script provides the correct Model-B behavior instead.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIFT_PATH = ROOT / "scripts" / "forge" / "bible_drift.py"


def _load_bible_drift():
    """Import bible_drift by file path (no package-layout assumptions)."""
    spec = importlib.util.spec_from_file_location("bible_drift", DRIFT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {DRIFT_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__ during import.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="Bible post-commit drift advisory (never fails the commit).")
    parser.add_argument("--bible", type=Path, default=ROOT / "docs" / "THOMAS_BIBLE.md")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--sha", default="HEAD")
    args, _unknown = parser.parse_known_args()

    try:
        if not args.bible.exists():
            print(f"bible-advisory: bible not found ({args.bible}) -- skipped")
            return 0
        bible_drift = _load_bible_drift()
        sections, unstamped = bible_drift.parse_bible(args.bible)
        sections = bible_drift.evaluate_drift(bible_drift.ROOT, sections)
        drifted = [s for s in sections if s.status == "green" and s.drifted]
        missing = [s for s in sections if s.missing_paths]

        print(
            f"bible-advisory: {len(sections)} stamped / {len(unstamped)} unstamped; "
            f"{len(drifted)} drifted, {len(missing)} with missing paths"
        )
        for section in drifted[:10]:
            print(f"  DRIFTED (re-verify + re-stamp): `{section.title}`")
        for section in missing[:10]:
            print(f"  MISSING PATHS: `{section.title}` -> {', '.join(section.missing_paths[:3])}")
        if not sections:
            print(
                "  note: 0 sections stamped -- drift detection is dormant until sections carry "
                "`> Stamp: covers=[...] hash=sha256:... status=green`."
            )
    except (ImportError, OSError, ValueError, AttributeError, RuntimeError, TypeError) as exc:
        # A post-commit hook must never fail the commit; the hook wrapper also `|| true`s.
        print(f"bible-advisory: skipped due to error: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
