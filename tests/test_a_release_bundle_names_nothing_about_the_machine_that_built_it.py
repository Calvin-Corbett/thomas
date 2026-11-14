"""The files a release bundle writes about itself do not leak, and they are readable.

scripts/package_release.py writes RELEASE_MANIFEST.json, RELEASE_SUMMARY.md and
THIRD_PARTY_NOTICES.md into every bundle, and the Windows installer and the source zip
now ship that bundle. The manifest held the absolute path of the folder it was built in
and listed the name of every tracked file it left out (internal handoff notes, threat
models, gate names). The summary and the notices were joined with a backslash and an
"n" instead of a newline, so the legal notices shipped as one line.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDED = [
    ("docs/HANDOFF_SOMEONE_2026-08-14.md", "not-in-allow-list"),
    ("plans/thomas/security/THREAT_MODEL.md", "not-in-allow-list"),
    ("thomas/agent/guardrails.md", "exact:thomas/agent/guardrails.md"),
    ("thomas/core/cache.pyc", "glob:*.pyc"),
    ("plans/x/PLAN.md", "prefix:plans/"),
]


def _packager():
    spec = importlib.util.spec_from_file_location("_pkg_release_leak", ROOT / "scripts" / "package_release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_manifest_carries_counts_not_the_names_of_what_was_left_out(tmp_path: Path) -> None:
    module = _packager()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    path = module._build_manifest(tmp_path, ["a.txt"], EXCLUDED, "1.2.3")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)

    assert "root" not in data and str(module.ROOT) not in text, "the manifest names the build folder"
    for private in ("HANDOFF", "THREAT_MODEL", "guardrails", "plans/"):
        assert private not in text, f"the manifest names {private}"
    assert "excluded" not in data
    assert data["excluded_by_reason"] == {"not-in-allow-list": 2, "exact": 1, "glob": 1, "prefix": 1}
    assert data["excluded_count"] == len(EXCLUDED)
    assert [entry["path"] for entry in data["files"]] == ["a.txt"]


def test_the_summary_is_readable_and_names_no_private_file(tmp_path: Path) -> None:
    module = _packager()
    path = module._write_summary(tmp_path, "1.2.3", ["a.txt"], EXCLUDED)
    text = path.read_text(encoding="utf-8")

    assert "\\n" not in text, "joined with a backslash and an n instead of a newline"
    assert len(text.splitlines()) > 8
    assert "- not-in-allow-list: 2" in text
    for private in ("HANDOFF", "THREAT_MODEL", "guardrails"):
        assert private not in text


def test_the_third_party_notices_are_readable(tmp_path: Path) -> None:
    module = _packager()
    text = module._generate_third_party_notices(tmp_path).read_text(encoding="utf-8")

    assert "\\n" not in text, "joined with a backslash and an n instead of a newline"
    assert len(text.splitlines()) > 8
    assert text.startswith("# Third-Party Notices")
