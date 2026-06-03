"""Regression: the public-repo leak guard must not be silently disable-able.

The local (gitignored) blocklist holds the competitor-name / comparison-artifact
rules. An earlier draft let ``THOMAS_LEAK_BLOCKLIST_FILE`` redirect where it
loads from -- a fail-open hole, because a worker could point it at a nonexistent
path and drop every rule while the gate still reported PASS. The path is now
fixed; these tests pin that.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

leak_guard = importlib.import_module("forge.gates.public_repo_leak_guard")


def _write_blocklist(path: Path) -> None:
    path.write_text(
        json.dumps({"forbidden_substrings": ["acmecorp"], "forbidden_paths": ["secret_doc.md"]}),
        encoding="utf-8",
    )


def test_leak_blocklist_ignores_env_override(monkeypatch, tmp_path) -> None:
    # Pointing the (removed) override env at a nonexistent file must NOT drop the
    # real rules: the fixed default path is always used.
    real = tmp_path / "leak_blocklist.local.json"
    _write_blocklist(real)
    monkeypatch.setattr(leak_guard, "LOCAL_BLOCKLIST_PATH", real)
    monkeypatch.setenv("THOMAS_LEAK_BLOCKLIST_FILE", str(tmp_path / "does_not_exist.json"))

    subs, paths, _prefixes, _regex = leak_guard._load_local_blocklist()

    assert "acmecorp" in subs
    assert "secret_doc.md" in paths


def test_leak_blocklist_absent_default_returns_empty(monkeypatch, tmp_path) -> None:
    # Fresh public clone with no local blocklist -> empty extras (legitimate:
    # the gate still enforces the generic defaults), not a crash or a bypass.
    monkeypatch.setattr(leak_guard, "LOCAL_BLOCKLIST_PATH", tmp_path / "missing.json")
    monkeypatch.delenv("THOMAS_LEAK_BLOCKLIST_FILE", raising=False)

    subs, paths, prefixes, regex = leak_guard._load_local_blocklist()

    assert (subs, paths, prefixes, regex) == ((), frozenset(), (), ())
