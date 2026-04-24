from __future__ import annotations

import json

import scripts.configure_github_branch_protection as mod


def test_repo_slug_parses_https_remote() -> None:
    assert mod._repo_slug_from_remote("https://github.com/example/thomas.git") == "example/thomas"


def test_repo_slug_parses_ssh_remote() -> None:
    assert mod._repo_slug_from_remote("git@github.com:example/thomas.git") == "example/thomas"


def test_repo_slug_returns_none_for_non_github() -> None:
    assert mod._repo_slug_from_remote("https://example.com/team/repo.git") is None


def test_required_checks_defaults_to_required_gates() -> None:
    assert mod._required_checks([]) == ("required-gates",)


def test_required_checks_dedupes_case_insensitive() -> None:
    assert mod._required_checks(["required-gates", "Required-Gates", "other"]) == (
        "required-gates",
        "other",
    )


def test_profile_payload_contains_expected_defaults() -> None:
    profile = mod.ProtectionProfile(
        strict_checks=True,
        required_checks=("required-gates",),
        enforce_admins=True,
        dismiss_stale_reviews=True,
        require_code_owner_reviews=False,
        required_approvals=1,
        require_conversation_resolution=True,
        require_linear_history=True,
        allow_force_pushes=False,
        allow_deletions=False,
    )
    payload = profile.to_payload()
    assert payload["required_status_checks"]["strict"] is True
    assert payload["required_status_checks"]["contexts"] == ["required-gates"]
    assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 1
    assert payload["enforce_admins"] is True


def test_diff_profile_reports_mismatches() -> None:
    expected = {"strict_checks": True, "required_checks": ["required-gates"]}
    current = {"strict_checks": False, "required_checks": ["required-gates"]}
    mismatches = mod._diff_profile(expected=expected, current=current)
    assert len(mismatches) == 1
    assert "strict_checks" in mismatches[0]


def test_dry_run_json_includes_payload(capsys, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_default_repo_slug", lambda: "example/thomas")
    rc = mod.run(["--dry-run", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "dry_run"
    assert payload["repo"] == "example/thomas"
    assert payload["payload"]["required_status_checks"]["contexts"] == ["required-gates"]


def test_check_requires_token_when_not_dry_run(capsys, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_default_repo_slug", lambda: "example/thomas")
    rc = mod.run(["--check", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "token" in payload["error"].lower()


def test_apply_verifies_after_put(capsys, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_default_repo_slug", lambda: "example/thomas")

    calls = []

    def fake_request(*, method: str, path: str, token: str, payload=None):
        calls.append((method, path, token, payload))
        if method == "PUT":
            return {}
        return {
            "required_status_checks": {"strict": True, "contexts": ["required-gates"]},
            "enforce_admins": {"enabled": True},
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False,
                "required_approving_review_count": 1,
            },
            "required_conversation_resolution": {"enabled": True},
            "required_linear_history": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
        }

    monkeypatch.setattr(mod, "_request_github", fake_request)
    rc = mod.run(["--apply", "--token", "x", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "apply"
    assert [item[0] for item in calls] == ["PUT", "GET"]
