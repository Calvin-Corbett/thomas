from __future__ import annotations

from pathlib import Path

from thomas.marketplace.security.dependency_policy import evaluate_dependency_policy


def test_dependency_policy_flags_direct_url_and_wildcard(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample"
version = "0.1.0"
dependencies = [
  "safepkg>=1.0",
  "badpkg @ https://example.com/badpkg.whl",
  "wildpkg==*",
]
""".strip(),
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    assert report["ok"] is False
    codes = {item["code"] for item in report["errors"]}
    assert "dependency.direct_url_disallowed" in codes
    assert "dependency.wildcard_disallowed" in codes


def test_dependency_policy_warns_on_unconstrained_dependency(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample"
version = "0.1.0"
dependencies = ["click"]
""".strip(),
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    assert report["ok"] is True
    assert any(item["code"] == "dependency.unconstrained" for item in report["warnings"])
