"""Authenticated GitHub source-host gateway (CAP-070, Level 2).

This module implements a real, credential-gated GitHub integration that
satisfies the injectable ``Gateway`` seam in
:mod:`thomas.tools.governed_git_pr` while adding the source-host flows the
Level-2 acceptance line calls for:

1. **Authenticated PR create / update** -- open a pull request and later patch
   its title/body/state/base.
2. **Review-comment reply + follow-up fix reference** -- reply into an existing
   review-comment thread, optionally embedding the SHA of the follow-up fix
   commit that addresses the reviewer.
3. **Check-reaction flows** -- inspect a failing check event (normalized with
   the existing :func:`thomas.integrations.github_automation.normalize_ci_status_event`
   helper) and *react*: re-run the check (``rerequest``) and/or acknowledge it
   with a reaction on the associated review comment.

Design (the injectable-adapter pattern):

* The HTTP edge is behind a :class:`Transport` protocol. The **real** default,
  :class:`UrllibTransport`, talks to ``api.github.com`` using only
  :mod:`urllib.request` from the stdlib -- no new pip dependency.
* A hermetic :class:`FakeGitHubTransport` records every request and returns
  canned responses, so the whole gateway is fully tested offline. The exact
  acceptance line is proven against the fake in
  ``tests/test_github_pr_gateway.py``.

Credentials / live lane
-----------------------
The token is resolved **at call time** from an injected ``token_provider`` (a
zero-arg callable) or, failing that, the ``GITHUB_TOKEN`` environment variable.
It is never stored as a plain attribute, never logged, and never included in
``repr()``. Live REST calls only happen when a real token is present and the
default :class:`UrllibTransport` is used; the fake-backed tests run with a dummy
token and never touch the network. A missing token raises
:class:`MissingGitHubTokenError` cleanly before any request is attempted.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from thomas.integrations.github_automation import normalize_ci_status_event
from thomas.tools.governed_git_pr import GatewayResult, PrPayload

DEFAULT_BASE_URL = "https://api.github.com"
DEFAULT_API_VERSION = "2022-11-28"
DEFAULT_USER_AGENT = "thomas-github-pr-gateway"

# Check conclusions that warrant a re-run / acknowledgement reaction.
_FAILING_CONCLUSIONS: frozenset[str] = frozenset({"failure", "cancelled", "timed_out", "action_required", "stale"})


class GitHubGatewayError(RuntimeError):
    """Base class for gateway errors."""


class MissingGitHubTokenError(GitHubGatewayError):
    """Raised when no token is available from the provider or environment."""


class GitHubApiError(GitHubGatewayError):
    """Raised when the GitHub REST API returns a non-2xx response."""

    def __init__(self, status: int, method: str, path: str, detail: str) -> None:
        self.status = int(status)
        self.method = method
        self.path = path
        self.detail = detail
        super().__init__(f"GitHub API {method} {path} failed with HTTP {status}: {detail}")


# A token provider returns the current token (or ``None`` to fall back to env).
TokenProvider = Callable[[], "str | None"]

# A push runner pushes ``branch`` to ``remote`` inside ``repo_path``.
PushRunner = Callable[[str, str, "Path | None"], None]


@dataclass(frozen=True)
class HttpResponse:
    """A minimal, transport-agnostic HTTP response with parsed JSON data."""

    status: int
    data: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= int(self.status) < 300


class Transport(Protocol):
    """The injectable HTTP edge. Implementations must never leak credentials."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse: ...


# ---------------------------------------------------------------------------
# Real transport (urllib) -- exercised live only when credentials are present.
# ---------------------------------------------------------------------------


class UrllibTransport:
    """Real GitHub transport using the stdlib :mod:`urllib.request`.

    No third-party HTTP client is introduced. This is the default and is what
    talks to the live service when a token is available.
    """

    def __init__(self, *, timeout_s: float = 20.0) -> None:
        self._timeout_s = max(1.0, float(timeout_s))

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = int(getattr(resp, "status", 200) or 200)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except OSError:
                detail = ""
            # The URL carries no secret (the token lives only in the Authorization
            # header), so surfacing the path here does not leak credentials.
            raise GitHubApiError(int(exc.code), method, url, detail.strip()) from exc
        except urllib.error.URLError as exc:
            raise GitHubGatewayError(f"GitHub request to {url} failed: {exc.reason}") from exc
        data: Any = None
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
        return HttpResponse(status=status, data=data)


# ---------------------------------------------------------------------------
# Hermetic fake transport for tests.
# ---------------------------------------------------------------------------


@dataclass
class RecordedRequest:
    """A request captured by :class:`FakeGitHubTransport`."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None

    @property
    def path(self) -> str:
        # Everything after the scheme+host; good enough for endpoint assertions.
        marker = "://"
        idx = self.url.find(marker)
        if idx == -1:
            return self.url
        rest = self.url[idx + len(marker) :]
        slash = rest.find("/")
        return rest[slash:] if slash != -1 else "/"

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class FakeGitHubTransport:
    """Records requests and returns canned responses -- no network, no secrets.

    ``routes`` maps ``(METHOD, path_substring)`` to ``(status, json_data)``. The
    first matching route wins; otherwise a benign default is returned so callers
    always get a well-formed response.
    """

    def __init__(
        self,
        routes: Mapping[tuple[str, str], tuple[int, Any]] | None = None,
        *,
        default: tuple[int, Any] = (201, {"ok": True}),
    ) -> None:
        self.requests: list[RecordedRequest] = []
        self._routes = dict(routes or {})
        self._default = default

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        self.requests.append(RecordedRequest(method=method, url=url, headers=dict(headers), body=body))
        for (route_method, substring), (status, data) in self._routes.items():
            if route_method == method and substring in url:
                return HttpResponse(status=int(status), data=data)
        status, data = self._default
        return HttpResponse(status=int(status), data=data)


# ---------------------------------------------------------------------------
# Default push runner (git push) -- only used by the Gateway __call__ path.
# ---------------------------------------------------------------------------


def _subprocess_push(remote: str, branch: str, repo_path: Path | None) -> None:
    try:
        proc = subprocess.run(
            ["git", "push", "--set-upstream", remote, branch],
            cwd=str(repo_path) if repo_path is not None else None,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitHubGatewayError("git executable not found in PATH") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GitHubGatewayError(f"git push {remote} {branch} failed: {detail}")


# ---------------------------------------------------------------------------
# The gateway.
# ---------------------------------------------------------------------------


@dataclass(repr=False)
class AuthenticatedPrGateway:
    """Authenticated GitHub source-host gateway.

    Parameters
    ----------
    repo:
        ``"owner/name"`` slug of the target repository.
    token_provider:
        Optional zero-arg callable returning the token. If it returns a falsy
        value (or is ``None``), the ``GITHUB_TOKEN`` env var is used instead.
    transport:
        Injectable HTTP edge. Defaults to the real :class:`UrllibTransport`.
    base_url:
        API root; defaults to ``https://api.github.com``.
    remote / repo_path / push_runner:
        Used only by the :meth:`__call__` gateway path to push the feature
        branch before opening the PR.
    """

    repo: str
    token_provider: TokenProvider | None = None
    transport: Transport = field(default_factory=UrllibTransport)
    base_url: str = DEFAULT_BASE_URL
    api_version: str = DEFAULT_API_VERSION
    user_agent: str = DEFAULT_USER_AGENT
    remote: str = "origin"
    repo_path: Path | None = None
    push_runner: PushRunner = _subprocess_push

    def __post_init__(self) -> None:
        self.repo = str(self.repo).strip().strip("/")
        if not self.repo or self.repo.count("/") != 1:
            raise ValueError(f"repo must be 'owner/name', got {self.repo!r}")
        self.base_url = str(self.base_url).rstrip("/")
        if self.repo_path is not None:
            self.repo_path = Path(self.repo_path)

    # -- constructors ------------------------------------------------------

    @classmethod
    def with_token(cls, repo: str, token: str, **kwargs: Any) -> AuthenticatedPrGateway:
        """Build a gateway from a static token without storing it as an attribute.

        The token is captured in a closure so it never appears in ``vars()`` or
        ``repr()``.
        """

        captured = str(token)

        def _provider() -> str:
            return captured

        return cls(repo=repo, token_provider=_provider, **kwargs)

    # -- redaction ---------------------------------------------------------

    def __repr__(self) -> str:  # never leak the token
        return f"AuthenticatedPrGateway(repo={self.repo!r}, base_url={self.base_url!r}, token='***redacted***')"

    def describe(self) -> dict[str, str]:
        """A safe, secret-free description for logging/telemetry."""

        return {"repo": self.repo, "base_url": self.base_url, "token": "***redacted***"}

    # -- auth / low-level request ------------------------------------------

    def _resolve_token(self) -> str:
        token: str | None = None
        if self.token_provider is not None:
            token = self.token_provider()
        if not token:
            token = os.environ.get("GITHUB_TOKEN")
        token = (token or "").strip()
        if not token:
            raise MissingGitHubTokenError("No GitHub token available; set GITHUB_TOKEN or pass a token_provider.")
        return token

    def _headers(self, token: str, *, has_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": self.api_version,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _api(self, method: str, path: str, json_body: Mapping[str, Any] | None = None) -> HttpResponse:
        token = self._resolve_token()
        url = self.base_url + "/" + path.lstrip("/")
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(dict(json_body)).encode("utf-8")
        headers = self._headers(token, has_body=body is not None)
        resp = self.transport.request(method=method, url=url, headers=headers, body=body)
        if not resp.ok:
            detail = resp.data if isinstance(resp.data, str) else json.dumps(resp.data)
            raise GitHubApiError(resp.status, method, path, str(detail))
        return resp

    # -- (1) PR create / update -------------------------------------------

    def create_pull_request(
        self,
        *,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
        maintainer_can_modify: bool = True,
    ) -> HttpResponse:
        """Open a pull request (POST /repos/{repo}/pulls)."""

        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": bool(draft),
            "maintainer_can_modify": bool(maintainer_can_modify),
        }
        return self._api("POST", f"/repos/{self.repo}/pulls", payload)

    def update_pull_request(
        self,
        *,
        pr_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> HttpResponse:
        """Update an existing PR (PATCH /repos/{repo}/pulls/{n})."""

        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if base is not None:
            payload["base"] = base
        if not payload:
            raise ValueError("update_pull_request requires at least one field to change.")
        return self._api("PATCH", f"/repos/{self.repo}/pulls/{int(pr_number)}", payload)

    # -- (2) review-comment reply + follow-up fix reference ---------------

    def reply_to_review_comment(
        self,
        *,
        pr_number: int,
        comment_id: int,
        body: str,
    ) -> HttpResponse:
        """Reply inside an existing review-comment thread.

        POST /repos/{repo}/pulls/{pr}/comments/{comment_id}/replies
        """

        return self._api(
            "POST",
            f"/repos/{self.repo}/pulls/{int(pr_number)}/comments/{int(comment_id)}/replies",
            {"body": body},
        )

    def reply_with_fix(
        self,
        *,
        pr_number: int,
        comment_id: int,
        message: str,
        fix_commit: str,
    ) -> HttpResponse:
        """Reply to a reviewer, embedding the follow-up fix commit reference."""

        sha = str(fix_commit).strip()
        body = f"{message.strip()}\n\nFixed in {sha}." if message.strip() else f"Fixed in {sha}."
        return self.reply_to_review_comment(pr_number=pr_number, comment_id=comment_id, body=body)

    # -- (3) check-reaction flows -----------------------------------------

    def rerun_check(self, check_run_id: int) -> HttpResponse:
        """Re-run a check (POST /repos/{repo}/check-runs/{id}/rerequest)."""

        return self._api("POST", f"/repos/{self.repo}/check-runs/{int(check_run_id)}/rerequest")

    def react_to_review_comment(
        self,
        *,
        comment_id: int,
        content: str = "+1",
    ) -> HttpResponse:
        """Add a reaction to a review comment.

        POST /repos/{repo}/pulls/comments/{comment_id}/reactions
        """

        return self._api(
            "POST",
            f"/repos/{self.repo}/pulls/comments/{int(comment_id)}/reactions",
            {"content": content},
        )

    def react_to_check(
        self,
        event: Mapping[str, Any],
        *,
        check_run_id: int | None = None,
        acknowledge_comment_id: int | None = None,
        content: str = "rocket",
    ) -> dict[str, Any]:
        """React to a (failing) check event.

        The event is normalized with the shared
        :func:`normalize_ci_status_event` helper. When the check concluded in a
        failing state, this re-runs it (if ``check_run_id`` is given) and/or
        acknowledges it with a reaction on the associated review comment (if
        ``acknowledge_comment_id`` is given).
        """

        normalized = normalize_ci_status_event(event)
        conclusion = str(normalized.get("conclusion", "")).lower()
        failing = conclusion in _FAILING_CONCLUSIONS
        result: dict[str, Any] = {"normalized": normalized, "reacted": False}
        if not failing:
            return result
        if check_run_id is not None:
            result["rerun"] = self.rerun_check(check_run_id)
            result["reacted"] = True
        if acknowledge_comment_id is not None:
            result["acknowledged"] = self.react_to_review_comment(comment_id=acknowledge_comment_id, content=content)
            result["reacted"] = True
        return result

    # -- Gateway seam for GovernedPrFlow ----------------------------------

    def __call__(self, payload: PrPayload) -> GatewayResult:
        """Satisfy ``thomas.tools.governed_git_pr.Gateway``: push + create PR."""

        self.push_runner(self.remote, payload.branch, self.repo_path)
        resp = self.create_pull_request(
            title=payload.title,
            head=payload.branch,
            base=payload.base,
            body=payload.body,
        )
        html_url = ""
        if isinstance(resp.data, Mapping):
            html_url = str(resp.data.get("html_url", ""))
        return GatewayResult(
            pushed=True,
            pr_url_or_dryrun=html_url or f"opened PR on {self.repo}",
        )
