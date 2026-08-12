"""Hermetic tests for the authenticated GitHub PR gateway (CAP-070 Level 2).

Every test injects :class:`FakeGitHubTransport` -- no network, no real token.
The exact acceptance line is proven against the fake:

* PR create then update hit the right endpoints with the right payloads.
* A review-comment reply posts into the comment thread.
* A check-reaction flow fires (re-run + acknowledge reaction).
* The token never appears in logs/repr.
* A missing token errors cleanly.
"""

from __future__ import annotations

import pytest

from thomas.integrations.github_pr_gateway import (
    AuthenticatedPrGateway,
    FakeGitHubTransport,
    GitHubApiError,
    MissingGitHubTokenError,
)
from thomas.tools.governed_git_pr import GovernedPrFlow, PrPayload

REPO = "acme/thomas"
TOKEN = "ghp_SUPERSECRET_should_never_be_logged"


def _gateway(transport: FakeGitHubTransport, **kwargs) -> AuthenticatedPrGateway:
    return AuthenticatedPrGateway(
        repo=REPO,
        token_provider=lambda: TOKEN,
        transport=transport,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# (1) PR create then update
# ---------------------------------------------------------------------------


def test_pr_create_then_update_hits_right_endpoints_and_payloads() -> None:
    transport = FakeGitHubTransport(
        routes={
            ("POST", "/pulls"): (201, {"number": 7, "html_url": "https://github.com/acme/thomas/pull/7"}),
            ("PATCH", "/pulls/7"): (200, {"number": 7, "state": "open"}),
        }
    )
    gw = _gateway(transport)

    created = gw.create_pull_request(title="Add gateway", head="feature/gw", base="main", body="body text", draft=True)
    assert created.status == 201
    assert created.data["number"] == 7

    updated = gw.update_pull_request(pr_number=7, title="Add gateway (v2)", body="updated body")
    assert updated.status == 200

    # Endpoint + method + payload assertions.
    create_req, update_req = transport.requests
    assert create_req.method == "POST"
    assert create_req.path == f"/repos/{REPO}/pulls"
    assert create_req.json() == {
        "title": "Add gateway",
        "head": "feature/gw",
        "base": "main",
        "body": "body text",
        "draft": True,
        "maintainer_can_modify": True,
    }

    assert update_req.method == "PATCH"
    assert update_req.path == f"/repos/{REPO}/pulls/7"
    assert update_req.json() == {"title": "Add gateway (v2)", "body": "updated body"}


def test_update_requires_a_field() -> None:
    gw = _gateway(FakeGitHubTransport())
    with pytest.raises(ValueError):
        gw.update_pull_request(pr_number=1)


# ---------------------------------------------------------------------------
# (2) review-comment reply + follow-up fix reference
# ---------------------------------------------------------------------------


def test_review_comment_reply_posts_to_thread() -> None:
    transport = FakeGitHubTransport(routes={("POST", "/comments/555/replies"): (201, {"id": 999})})
    gw = _gateway(transport)

    resp = gw.reply_to_review_comment(pr_number=7, comment_id=555, body="Thanks, addressing now.")
    assert resp.status == 201

    (req,) = transport.requests
    assert req.method == "POST"
    assert req.path == f"/repos/{REPO}/pulls/7/comments/555/replies"
    assert req.json() == {"body": "Thanks, addressing now."}


def test_reply_with_fix_embeds_commit_reference() -> None:
    transport = FakeGitHubTransport(routes={("POST", "/comments/555/replies"): (201, {"id": 1000})})
    gw = _gateway(transport)

    gw.reply_with_fix(pr_number=7, comment_id=555, message="Good catch.", fix_commit="abc1234")

    (req,) = transport.requests
    assert req.path == f"/repos/{REPO}/pulls/7/comments/555/replies"
    assert "abc1234" in req.json()["body"]
    assert "Good catch." in req.json()["body"]


# ---------------------------------------------------------------------------
# (3) check-reaction flow
# ---------------------------------------------------------------------------


def test_check_reaction_flow_fires_rerun_and_ack_on_failure() -> None:
    transport = FakeGitHubTransport(
        routes={
            ("POST", "/check-runs/321/rerequest"): (201, {}),
            ("POST", "/pulls/comments/555/reactions"): (201, {"content": "rocket"}),
        }
    )
    gw = _gateway(transport)

    event = {
        "action": "completed",
        "repository": {"full_name": REPO},
        "check_run": {
            "status": "completed",
            "conclusion": "failure",
            "name": "pytest",
            "head_sha": "deadbeef",
        },
    }
    result = gw.react_to_check(event, check_run_id=321, acknowledge_comment_id=555)

    assert result["reacted"] is True
    assert result["normalized"]["kind"] == "check_run"
    assert result["normalized"]["conclusion"] == "failure"

    paths = [(r.method, r.path) for r in transport.requests]
    assert ("POST", f"/repos/{REPO}/check-runs/321/rerequest") in paths
    assert ("POST", f"/repos/{REPO}/pulls/comments/555/reactions") in paths


def test_check_reaction_flow_noops_on_success() -> None:
    transport = FakeGitHubTransport()
    gw = _gateway(transport)

    event = {
        "action": "completed",
        "repository": {"full_name": REPO},
        "check_run": {"status": "completed", "conclusion": "success", "name": "pytest"},
    }
    result = gw.react_to_check(event, check_run_id=321, acknowledge_comment_id=555)

    assert result["reacted"] is False
    assert transport.requests == []


# ---------------------------------------------------------------------------
# (4) token never in logs/repr; auth header carries it
# ---------------------------------------------------------------------------


def test_token_absent_from_repr_and_describe_but_present_in_header() -> None:
    transport = FakeGitHubTransport()
    gw = AuthenticatedPrGateway.with_token(REPO, TOKEN, transport=transport)

    assert TOKEN not in repr(gw)
    assert "***redacted***" in repr(gw)
    assert TOKEN not in str(gw.describe())
    # with_token must not store the raw token as an attribute.
    assert TOKEN not in str(vars(gw))

    gw.create_pull_request(title="t", head="h", base="main")
    (req,) = transport.requests
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    # The token lives only in the Authorization header, never in the URL.
    assert TOKEN not in req.url


# ---------------------------------------------------------------------------
# (5) missing token errors cleanly
# ---------------------------------------------------------------------------


def test_missing_token_raises_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    transport = FakeGitHubTransport()
    gw = AuthenticatedPrGateway(repo=REPO, token_provider=lambda: None, transport=transport)

    with pytest.raises(MissingGitHubTokenError):
        gw.create_pull_request(title="t", head="h", base="main")
    # Nothing was sent.
    assert transport.requests == []


def test_env_token_used_when_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
    transport = FakeGitHubTransport()
    gw = AuthenticatedPrGateway(repo=REPO, transport=transport)

    gw.create_pull_request(title="t", head="h", base="main")
    (req,) = transport.requests
    assert req.headers["Authorization"] == "Bearer ghp_from_env"


# ---------------------------------------------------------------------------
# API error surfacing
# ---------------------------------------------------------------------------


def test_non_2xx_raises_github_api_error() -> None:
    transport = FakeGitHubTransport(default=(422, {"message": "Validation Failed"}))
    gw = _gateway(transport)

    with pytest.raises(GitHubApiError) as excinfo:
        gw.create_pull_request(title="t", head="h", base="main")
    assert excinfo.value.status == 422


# ---------------------------------------------------------------------------
# Wiring: AuthenticatedPrGateway as the GovernedPrFlow gateway
# ---------------------------------------------------------------------------


def test_wired_as_governed_pr_flow_gateway(tmp_path) -> None:
    pushed_branches: list[str] = []

    transport = FakeGitHubTransport(
        routes={("POST", "/pulls"): (201, {"number": 42, "html_url": "https://github.com/acme/thomas/pull/42"})}
    )
    gw = AuthenticatedPrGateway(
        repo=REPO,
        token_provider=lambda: TOKEN,
        transport=transport,
        push_runner=lambda remote, branch, path: pushed_branches.append(branch),
    )

    # Directly exercise the Gateway seam contract.
    result = gw(PrPayload(branch="feature/x", base="main", title="T", body="B", head_commit="abc123"))
    assert result.pushed is True
    assert result.pr_url_or_dryrun == "https://github.com/acme/thomas/pull/42"
    assert pushed_branches == ["feature/x"]

    # And that GovernedPrFlow accepts it as its gateway (fake git runner).
    calls: list[list[str]] = []

    def _fake_git(args, cwd):
        calls.append(list(args))
        joined = " ".join(args)
        if joined.startswith("branch --list"):
            return ""
        if joined.startswith("rev-parse --short"):
            return "abc123"
        return ""

    def _validator(_ctx):
        from thomas.tools.governed_git_pr import ValidationCheck, ValidationReport

        return ValidationReport(checks=(ValidationCheck(name="pytest", passed=True, evidence="ok"),))

    flow = GovernedPrFlow(repo_path=tmp_path, gateway=gw, git_runner=_fake_git)
    flow_result = flow.run(branch="feature/y", base="main", title="Title", validator=_validator)

    assert flow_result.pr_created is True
    assert flow_result.pushed is True
    assert flow_result.pr_url_or_dryrun == "https://github.com/acme/thomas/pull/42"
    assert pushed_branches == ["feature/x", "feature/y"]
