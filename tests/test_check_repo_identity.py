from __future__ import annotations

import json
from pathlib import Path

import scripts.forge.gates.repo_identity as mod


def test_extract_slug_from_remote_handles_https_and_ssh() -> None:
    assert mod._extract_slug_from_remote("https://github.com/corbe/thomas.git") == "corbe/thomas"
    assert mod._extract_slug_from_remote("git@github.com:corbe/thomas.git") == "corbe/thomas"
    assert mod._extract_slug_from_remote("") is None


def test_evaluate_identity_passes_for_matching_slug_and_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "Thomas"
    result = mod.evaluate_identity(
        repo_root=repo_root,
        remote_urls={"origin": "https://github.com/corbe/thomas.git"},
        canonical_slug="corbe/thomas",
        canonical_roots=[str(repo_root)],
        enforce_local_root=True,
    )

    assert result["ok"] is True
    assert result["violations"] == []
    assert result["expected_slug"] == "corbe/thomas"


def test_evaluate_identity_fails_for_remote_and_root_drift(tmp_path: Path) -> None:
    repo_root = tmp_path / "other-clone"
    result = mod.evaluate_identity(
        repo_root=repo_root,
        remote_urls={"origin": "https://github.com/example/not-thomas.git"},
        canonical_slug="corbe/thomas",
        canonical_roots=["C:/Users/corbe/Thomas"],
        enforce_local_root=True,
    )

    assert result["ok"] is False
    assert any("remote slug mismatch" in item for item in result["violations"])
    assert any("repo root drift detected" in item for item in result["violations"])


def test_run_json_success_payload(monkeypatch, tmp_path: Path, capsys) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")
    fake_root = tmp_path / "Thomas"

    monkeypatch.setattr(
        mod,
        "_load_policy",
        lambda _path: {
            "canonical_repo_slug": "corbe/thomas",
            "canonical_local_roots": [str(fake_root)],
            "enforce_local_root_when_not_ci": True,
            "allowed_remote_names": ["origin"],
        },
    )
    monkeypatch.setattr(mod, "_git_repo_root", lambda _path_hint: fake_root)
    monkeypatch.setattr(
        mod, "_git_remote_urls", lambda _root, allowed_remote_names: {"origin": "git@github.com:corbe/thomas.git"}
    )  # type: ignore[call-arg]

    rc = mod.run(["--policy", str(policy), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "repo_identity"
