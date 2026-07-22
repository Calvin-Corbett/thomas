"""CAP-120: One-step deploy / hosting with environments.

Turn a built artifact plus a target **environment** (``dev`` / ``staging`` /
``prod``) into a hosted **HTTPS** deployment in a single call, and be able to
roll back to the previous deployment for that environment.

The design keeps the external edge -- the thing that actually stands a site or a
container up on a public HTTPS URL -- behind an *injectable adapter*
(:class:`HostingProvider`). The real default,
:class:`StaticHostProvider`, is a pure-stdlib adapter that *builds the deploy
request* and derives a deterministic HTTPS URL for a static/container host from
the app name, environment, and version. It does **not** perform a live network
deploy -- pushing bytes to a real CDN/container host is a credential-gated live
lane documented on :class:`StaticHostProvider` and intentionally not exercised
here. Tests inject :class:`FakeHostProvider`, a hermetic fake that can be
scripted to succeed or fail deterministically.

Environments are first-class and **isolated**: each environment tracks its own
current deployment and its own history stack, so a ``prod`` deploy never touches
``staging``'s current deployment. One-step: :meth:`DeployHosting.deploy` goes
from an :class:`Artifact` to a returned :class:`DeploymentRecord` whose ``url``
is an ``https://`` URL, in one call. Rollback is per-environment:
:meth:`DeployHosting.rollback` restores the previous successful deployment for a
single environment and leaves every other environment alone.

A failed provision is **reported honestly**: the failed attempt is recorded in
the environment's history with ``status == "failed"``, the environment's current
deployment is left unchanged, and :class:`DeployError` is raised carrying the
failed record -- never a fabricated success.

Determinism comes from an injected clock (``clock`` -> epoch seconds) and the
injected provider, so the same inputs always yield the same records. This module
is pure-stdlib and imports nothing from ``agent`` / ``server`` / ``cli`` (tools
layer rule).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Recognised deployment environments. ``dev`` is the default target.
ENV_DEV = "dev"
ENV_STAGING = "staging"
ENV_PROD = "prod"
DEFAULT_ENVIRONMENTS: tuple[str, ...] = (ENV_DEV, ENV_STAGING, ENV_PROD)

# Deployment lifecycle statuses.
STATUS_LIVE = "live"
STATUS_FAILED = "failed"
STATUS_ROLLED_BACK = "rolled_back"

# Artifact kinds the default host adapter understands.
KIND_STATIC = "static"
KIND_CONTAINER = "container"


class DeployHostingError(Exception):
    """Base class for all deploy/hosting failures."""


class UnknownEnvironmentError(DeployHostingError):
    """Raised when an operation targets an environment that was not configured."""


class NoPreviousDeploymentError(DeployHostingError):
    """Raised when a rollback has no prior successful deployment to restore."""


class DeployError(DeployHostingError):
    """Raised when the hosting provider fails to provision a deployment.

    Carries the :class:`DeploymentRecord` for the failed attempt (status
    ``"failed"``) so callers can inspect and audit the failure instead of
    receiving a fabricated success.
    """

    def __init__(self, record: DeploymentRecord) -> None:
        self.record = record
        super().__init__(f"deploy to {record.environment!r} failed: {record.detail or 'provider reported failure'}")


# --------------------------------------------------------------------------- #
# Artifact + records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Artifact:
    """A built artifact ready to host.

    ``content`` is the raw bytes of the built site/bundle (the thing that would
    otherwise be *downloaded and previewed locally*). ``digest`` is derived from
    the content so a deployment record is pinned to exactly what was shipped.
    """

    name: str
    content: bytes = b""
    kind: str = KIND_STATIC
    digest: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("artifact name must be a non-empty string")
        if self.kind not in (KIND_STATIC, KIND_CONTAINER):
            raise ValueError(f"unsupported artifact kind: {self.kind!r}")
        if not self.digest:
            digest = hashlib.sha256(self.content).hexdigest()[:16]
            object.__setattr__(self, "digest", digest)


@dataclass(frozen=True)
class DeployRequest:
    """The request handed to a :class:`HostingProvider` to provision a deploy."""

    app_name: str
    environment: str
    version: int
    artifact_kind: str
    artifact_digest: str
    config: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    """What a :class:`HostingProvider` returns for a provision attempt."""

    ok: bool
    url: str = ""
    detail: str = ""


@dataclass(frozen=True)
class DeploymentRecord:
    """An immutable record of one deployment attempt for one environment."""

    deployment_id: str
    app_name: str
    environment: str
    version: int
    url: str
    status: str
    artifact_digest: str
    provider: str
    created_at: float
    detail: str = ""

    @property
    def is_live(self) -> bool:
        return self.status == STATUS_LIVE and self.url.startswith("https://")


# --------------------------------------------------------------------------- #
# Hosting provider adapter (the injectable external edge)
# --------------------------------------------------------------------------- #


@runtime_checkable
class HostingProvider(Protocol):
    """Adapter that turns a :class:`DeployRequest` into a hosted HTTPS URL.

    Implementations must be *deterministic* given their inputs and must return a
    :class:`ProviderResult` (they signal handled failures via ``ok=False`` rather
    than raising, so the orchestrator can record the failure honestly).
    """

    name: str

    def provision(self, request: DeployRequest) -> ProviderResult:
        """Provision ``request`` and return the resulting HTTPS URL (or failure)."""
        ...


@dataclass
class StaticHostProvider:
    """Real default adapter: build a deploy request for a static/container host.

    This derives a deterministic public **HTTPS** URL for the target
    environment from the app name, environment, and version -- exactly the
    request a static-site or container host (Netlify/Vercel/Cloud Run style)
    would accept. It is fully hermetic: it composes and validates the deploy
    request and returns the URL the host *would* serve.

    LIVE LANE (not exercised here): actually shipping the artifact bytes to a
    real host requires a provider API token and network egress. That belongs in
    a credential-gated adapter that performs the upload/rollout and reads the
    canonical URL back from the host's API. This default deliberately stops at
    building the request + deterministic URL so the core is provable offline; no
    live deploy is claimed.
    """

    domain: str = "thomas-apps.dev"
    name: str = "static-host"

    def provision(self, request: DeployRequest) -> ProviderResult:
        slug = _slugify(request.app_name)
        if not slug:
            return ProviderResult(ok=False, detail="app name did not yield a URL slug")
        # Environment-scoped subdomain; prod gets the bare app subdomain.
        if request.environment == ENV_PROD:
            host = f"{slug}.{self.domain}"
        else:
            host = f"{request.environment}--{slug}.{self.domain}"
        url = f"https://{host}/v{request.version}"
        return ProviderResult(ok=True, url=url, detail=f"provisioned {request.artifact_kind}")


@dataclass
class FakeHostProvider:
    """Hermetic fake provider for tests -- NO network, fully deterministic.

    By default every provision succeeds with a synthetic HTTPS URL. Pass
    ``fail_environments`` to make provisions to those environments fail (to prove
    a failed deploy is reported, not faked). Every provision is recorded in
    :attr:`calls` for assertion.
    """

    domain: str = "fake.test"
    name: str = "fake-host"
    fail_environments: frozenset[str] = frozenset()
    calls: list[DeployRequest] = field(default_factory=list)

    def provision(self, request: DeployRequest) -> ProviderResult:
        self.calls.append(request)
        if request.environment in self.fail_environments:
            return ProviderResult(ok=False, detail=f"forced failure for {request.environment}")
        slug = _slugify(request.app_name) or "app"
        url = f"https://{request.environment}.{slug}.{self.domain}/v{request.version}"
        return ProviderResult(ok=True, url=url, detail="fake provision")


def _slugify(text: str) -> str:
    """Lowercase, hyphen-join the alphanumeric runs of ``text`` for a URL slug."""
    out: list[str] = []
    prev_dash = False
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash and out:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")


# --------------------------------------------------------------------------- #
# Per-environment state
# --------------------------------------------------------------------------- #


@dataclass
class EnvironmentState:
    """Isolated state for a single environment: config, current, and history."""

    name: str
    config: dict[str, str] = field(default_factory=dict)
    current: DeploymentRecord | None = None
    history: list[DeploymentRecord] = field(default_factory=list)
    _version_counter: int = 0

    def next_version(self) -> int:
        self._version_counter += 1
        return self._version_counter

    def last_successful(self) -> DeploymentRecord | None:
        """Most recent live deployment in history (excluding the current one)."""
        current_id = self.current.deployment_id if self.current else None
        for record in reversed(self.history):
            if record.status == STATUS_LIVE and record.deployment_id != current_id:
                return record
        return None


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


class DeployHosting:
    """One-step deploy orchestrator over isolated, HTTPS-hosted environments."""

    def __init__(
        self,
        provider: HostingProvider | None = None,
        *,
        environments: Sequence[str] = DEFAULT_ENVIRONMENTS,
        env_config: Mapping[str, Mapping[str, str]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not environments:
            raise ValueError("at least one environment must be configured")
        self.provider: HostingProvider = provider or StaticHostProvider()
        self._clock: Callable[[], float] = clock or (lambda: 0.0)
        env_config = env_config or {}
        self._envs: dict[str, EnvironmentState] = {}
        for name in environments:
            self._envs[name] = EnvironmentState(
                name=name,
                config=dict(env_config.get(name, {})),
            )

    # -- introspection ----------------------------------------------------- #

    @property
    def environments(self) -> tuple[str, ...]:
        return tuple(self._envs)

    def _env(self, environment: str) -> EnvironmentState:
        try:
            return self._envs[environment]
        except KeyError:
            raise UnknownEnvironmentError(
                f"unknown environment {environment!r}; configured: {sorted(self._envs)}"
            ) from None

    def current(self, environment: str) -> DeploymentRecord | None:
        """The environment's live deployment, or ``None`` if never deployed."""
        return self._env(environment).current

    def history(self, environment: str) -> tuple[DeploymentRecord, ...]:
        """Immutable view of every deployment attempt for ``environment``."""
        return tuple(self._env(environment).history)

    def config(self, environment: str) -> dict[str, str]:
        """A copy of the per-environment config."""
        return dict(self._env(environment).config)

    # -- one-step deploy --------------------------------------------------- #

    def deploy(self, artifact: Artifact, environment: str = ENV_DEV) -> DeploymentRecord:
        """Deploy ``artifact`` to ``environment`` and return its hosted record.

        One call: build the deploy request, drive the injected provider, and --
        on success -- return a :class:`DeploymentRecord` whose ``url`` is an
        ``https://`` URL and make it the environment's current deployment. On
        provider failure the failed attempt is recorded in history, the current
        deployment is left untouched, and :class:`DeployError` is raised.
        """
        env = self._env(environment)
        version = env.next_version()
        request = DeployRequest(
            app_name=artifact.name,
            environment=environment,
            version=version,
            artifact_kind=artifact.kind,
            artifact_digest=artifact.digest,
            config=dict(env.config),
        )
        result = self.provider.provision(request)
        created_at = float(self._clock())
        deployment_id = f"{environment}-v{version}-{artifact.digest}"

        if not result.ok or not result.url.startswith("https://"):
            detail = result.detail or "provider did not return an https url"
            failed = DeploymentRecord(
                deployment_id=deployment_id,
                app_name=artifact.name,
                environment=environment,
                version=version,
                url=result.url,
                status=STATUS_FAILED,
                artifact_digest=artifact.digest,
                provider=self.provider.name,
                created_at=created_at,
                detail=detail,
            )
            env.history.append(failed)
            logger.warning(
                "deploy failed app=%s env=%s v=%s detail=%s",
                artifact.name,
                environment,
                version,
                detail,
            )
            raise DeployError(failed)

        record = DeploymentRecord(
            deployment_id=deployment_id,
            app_name=artifact.name,
            environment=environment,
            version=version,
            url=result.url,
            status=STATUS_LIVE,
            artifact_digest=artifact.digest,
            provider=self.provider.name,
            created_at=created_at,
            detail=result.detail,
        )
        env.history.append(record)
        env.current = record
        return record

    # -- rollback ---------------------------------------------------------- #

    def rollback(self, environment: str = ENV_DEV) -> DeploymentRecord:
        """Restore the previous successful deployment for ``environment``.

        Only ``environment`` is affected. The restored deployment becomes current
        again (recorded as a fresh ``rolled_back`` history entry pointing at the
        restored URL) so the environment's history is a full audit trail. Raises
        :class:`NoPreviousDeploymentError` if there is nothing to roll back to.
        """
        env = self._env(environment)
        previous = env.last_successful()
        if previous is None:
            raise NoPreviousDeploymentError(f"environment {environment!r} has no previous deployment to roll back to")
        version = env.next_version()
        restored = replace(
            previous,
            deployment_id=f"{environment}-v{version}-rollback-{previous.version}",
            version=version,
            status=STATUS_LIVE,
            created_at=float(self._clock()),
            detail=f"rolled back to v{previous.version} ({previous.url})",
        )
        # Mark the superseded deployment in history for auditability.
        if env.current is not None:
            superseded = replace(env.current, status=STATUS_ROLLED_BACK)
            for i, rec in enumerate(env.history):
                if rec.deployment_id == env.current.deployment_id:
                    env.history[i] = superseded
                    break
        env.history.append(restored)
        env.current = restored
        return restored
