"""CAP-062: custom sandbox images, scoped secret delivery, authenticated registries.

This module lets a sandbox run **custom images** pulled from **authenticated
registries** and receive **scoped secrets** without ever leaking a secret value
into an image manifest, a registry config, a container's create-time env, or a
log line. Three hard invariants drive the design:

1. **Immutable image manifests.** An image is pinned by a *content digest*
   (:func:`content_digest`) computed from its build spec. An :class:`ImageRegistry`
   maps ``name:version`` (a *tag*) to a digest. Re-publishing the same
   ``name:version`` -- even with identical content -- is rejected
   (:class:`ImmutableImageError`); an existing tag is never silently overwritten.
   A tag *resolves* to a digest (:meth:`ImageRegistry.resolve_tag`).

2. **Authenticated registries, credential-by-reference.** A :class:`RegistryConfig`
   references its credential by *name* (``credential_ref``), never by value. The
   real password is resolved from an injected :class:`SecretProvider` **at use
   time only** (:func:`authenticate_registry`) and handed to the registry via a
   *login-with-password-stdin* style :class:`RegistryClient` -- so it never lands
   in ``argv``, in the process environment, or in any log. The serialized config
   (:meth:`RegistryConfig.to_serializable`) contains only the reference.

3. **Scoped secret delivery.** A :class:`SecretGrant` scopes exactly which secret
   names a given image may receive. Secrets are resolved at use time and delivered
   **post-start** over an injected :class:`SecretDeliveryChannel` -- so they never
   reach image build args, the create-time env, or a manifest. A non-granted
   secret is withheld. A leak check (reused from :mod:`thomas.tools.dependency_env`)
   proves zero secret occurrences across manifest, config, and logs.

The module depends only on the standard library and on
:mod:`thomas.tools.dependency_env` (same tools layer), reusing its
:class:`SecretProvider` seam and its leak-check helpers rather than re-deriving
them.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from thomas.tools.dependency_env import (
    REDACTION_MASK,
    MappingSecretProvider,
    SecretLeakError,
    SecretProvider,
    SecretResolutionError,
    assert_no_secret_leak,
    count_secret_occurrences,
    find_secret_leaks,
    redact_text,
)

logger = logging.getLogger(__name__)

# Re-exported so callers depend on this module for the whole capability surface.
__all__ = [
    "REDACTION_MASK",
    "DeliveryReport",
    "ImageError",
    "ImageManifest",
    "ImageNotFoundError",
    "ImageRegistry",
    "ImmutableImageError",
    "InMemorySecretChannel",
    "LoginSession",
    "MappingSecretProvider",
    "RegistryAuthError",
    "RegistryClient",
    "RegistryConfig",
    "RegistryLoginResult",
    "SandboxImage",
    "SecretDeliveryChannel",
    "SecretGrant",
    "SecretLeakError",
    "SecretProvider",
    "SecretResolutionError",
    "SecretScopeError",
    "SubprocessRegistryClient",
    "assert_no_secret_leak",
    "content_digest",
    "count_secret_occurrences",
    "find_secret_leaks",
    "parse_reference",
    "redact_text",
]

DIGEST_ALGO = "sha256"
MANIFEST_VERSION = 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ImageError(RuntimeError):
    """Base class for image-manifest errors."""


class ImmutableImageError(ImageError):
    """Attempted to re-publish an already-published ``name:version`` tag."""


class ImageNotFoundError(ImageError):
    """A requested tag or digest is not present in the registry."""


class RegistryAuthError(RuntimeError):
    """A registry login could not be completed."""


class SecretScopeError(RuntimeError):
    """A secret was requested that a :class:`SecretGrant` does not permit."""


# ---------------------------------------------------------------------------
# Content-addressed digests + references
# ---------------------------------------------------------------------------


def _canonical_bytes(spec: Mapping[str, object]) -> bytes:
    """Deterministic canonical encoding of an image build spec."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_digest(spec: Mapping[str, object]) -> str:
    """Return the ``sha256:<hex>`` content digest of an image build ``spec``.

    Deterministic: identical specs (irrespective of key order) yield the same
    digest, and differing specs yield different digests.
    """
    hexdigest = hashlib.sha256(_canonical_bytes(spec)).hexdigest()
    return f"{DIGEST_ALGO}:{hexdigest}"


def parse_reference(reference: str) -> tuple[str, str]:
    """Split a ``name:version`` tag reference into ``(name, version)``.

    A digest reference (``sha256:...``) is not a tag and is rejected here.
    """
    text = str(reference or "").strip()
    if not text or ":" not in text:
        raise ValueError(f"reference must be 'name:version': {reference!r}")
    name, _, version = text.rpartition(":")
    if not name or not version:
        raise ValueError(f"reference must be 'name:version': {reference!r}")
    if name == DIGEST_ALGO:
        raise ValueError("a digest is not a tag reference")
    return name, version


# ---------------------------------------------------------------------------
# Immutable image manifests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageManifest:
    """An immutable, content-addressed image manifest.

    The manifest pins ``name:version`` to :attr:`digest`. It stores only the
    non-secret build spec -- secret values are structurally absent (they are
    delivered post-start, never baked into an image).
    """

    name: str
    version: str
    digest: str
    spec: Mapping[str, object]
    created_at: str
    manifest_version: int = MANIFEST_VERSION

    @property
    def reference(self) -> str:
        """The ``name:version`` tag reference."""
        return f"{self.name}:{self.version}"

    def to_serializable(self) -> dict[str, object]:
        """Persistable form. Contains no secret value by construction."""
        return {
            "manifest_version": self.manifest_version,
            "name": self.name,
            "version": self.version,
            "digest": self.digest,
            "created_at": self.created_at,
            "spec": dict(self.spec),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_serializable(), sort_keys=True, indent=2)


class ImageRegistry:
    """An in-memory registry of immutable image manifests.

    A tag (``name:version``) maps to exactly one content digest for its whole
    lifetime. Publishing a tag that already exists raises
    :class:`ImmutableImageError` -- tags are immutable.
    """

    __slots__ = ("_by_tag", "_by_digest")

    def __init__(self) -> None:
        self._by_tag: dict[str, str] = {}
        self._by_digest: dict[str, ImageManifest] = {}

    def publish(
        self,
        name: str,
        version: str,
        spec: Mapping[str, object],
        *,
        created_at: str,
    ) -> ImageManifest:
        """Publish ``name:version`` pinned to the content digest of ``spec``.

        Re-publishing an existing tag is rejected (immutable), even if the
        content is identical.
        """
        name = str(name or "").strip()
        version = str(version or "").strip()
        if not name or not version:
            raise ValueError("name and version are required")
        tag = f"{name}:{version}"
        if tag in self._by_tag:
            raise ImmutableImageError(
                f"image tag {tag!r} already published (pinned to {self._by_tag[tag]}); "
                "tags are immutable and cannot be re-published"
            )
        digest = content_digest(spec)
        manifest = ImageManifest(
            name=name,
            version=version,
            digest=digest,
            spec=dict(spec),
            created_at=str(created_at),
        )
        self._by_tag[tag] = digest
        # A digest may already exist (two tags, same content) -- keep the first.
        self._by_digest.setdefault(digest, manifest)
        return manifest

    def resolve_tag(self, name: str, version: str) -> str:
        """Resolve a ``name:version`` tag to its pinned content digest."""
        tag = f"{str(name).strip()}:{str(version).strip()}"
        try:
            return self._by_tag[tag]
        except KeyError as exc:
            raise ImageNotFoundError(f"unknown image tag: {tag!r}") from exc

    def get(self, name: str, version: str) -> ImageManifest:
        """Return the manifest for a ``name:version`` tag."""
        return self.get_by_digest(self.resolve_tag(name, version))

    def get_by_digest(self, digest: str) -> ImageManifest:
        """Return the manifest pinned to ``digest``."""
        try:
            return self._by_digest[str(digest).strip()]
        except KeyError as exc:
            raise ImageNotFoundError(f"unknown image digest: {digest!r}") from exc

    def has_tag(self, name: str, version: str) -> bool:
        return f"{str(name).strip()}:{str(version).strip()}" in self._by_tag

    def tags(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_tag))


# ---------------------------------------------------------------------------
# Authenticated registries -- credential by reference, resolved at use time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryConfig:
    """An authenticated registry whose credential is referenced by *name*.

    ``credential_ref`` is the name of a secret in an injected
    :class:`SecretProvider`. The value is never stored here, so the config is
    safe to serialize and log.
    """

    name: str
    endpoint: str
    username: str
    credential_ref: str

    def to_serializable(self) -> dict[str, str]:
        """Persistable form: references only, never the credential value."""
        return {
            "name": self.name,
            "endpoint": self.endpoint,
            "username": self.username,
            "credential_ref": self.credential_ref,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_serializable(), sort_keys=True, indent=2)


@dataclass(frozen=True)
class RegistryLoginResult:
    """What a :class:`RegistryClient` reports back from a login attempt.

    A conforming client MUST NOT place the password in :attr:`argv` or in
    :attr:`env_keys`, and MUST redact it from :attr:`log`. The core verifies
    this (belt-and-suspenders) in :func:`authenticate_registry`.
    """

    ok: bool
    session_token: str
    argv: tuple[str, ...]
    env_keys: tuple[str, ...]
    log: str


@runtime_checkable
class RegistryClient(Protocol):
    """Performs a registry login, feeding the password over stdin only."""

    def login(self, endpoint: str, username: str, *, password: str) -> RegistryLoginResult: ...


class SubprocessRegistryClient:
    """Default real client: runs a ``login --password-stdin`` command.

    The password is written to the child's **stdin** and never appears in
    ``argv`` or the process environment. This is the production edge: it needs a
    real CLI (default ``docker``) and network access to a live registry, so it
    is exercised only in a credential/registry-gated live lane. The hermetic
    core is proven against an injected fake client in the tests.
    """

    __slots__ = ("_executable", "_timeout")

    def __init__(self, executable: str = "docker", *, timeout: float = 30.0) -> None:
        self._executable = str(executable)
        self._timeout = float(timeout)

    def login(self, endpoint: str, username: str, *, password: str) -> RegistryLoginResult:
        # Password goes on stdin only -- never in argv, never in env.
        argv = (self._executable, "login", str(endpoint), "--username", str(username), "--password-stdin")
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed, password is on stdin
                list(argv),
                input=f"{password}\n".encode(),
                capture_output=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("registry login command failed for endpoint %s", endpoint)
            raise RegistryAuthError(f"registry login command failed: {type(exc).__name__}") from exc
        combined = (completed.stdout or b"").decode("utf-8", "replace") + (completed.stderr or b"").decode(
            "utf-8", "replace"
        )
        # Redact defensively in case a registry echoes the credential back.
        log = redact_text(combined, [password])
        return RegistryLoginResult(
            ok=completed.returncode == 0,
            session_token=f"session:{endpoint}" if completed.returncode == 0 else "",
            argv=argv,
            env_keys=(),
            log=log,
        )


@dataclass(frozen=True)
class LoginSession:
    """Result of authenticating to a registry. Holds no secret value."""

    registry: str
    endpoint: str
    username: str
    session_token: str
    argv: tuple[str, ...]
    env_keys: tuple[str, ...]
    log: str

    def to_serializable(self) -> dict[str, object]:
        return {
            "registry": self.registry,
            "endpoint": self.endpoint,
            "username": self.username,
            "session_token": self.session_token,
            "argv": list(self.argv),
            "env_keys": list(self.env_keys),
            "log": self.log,
        }


def authenticate_registry(
    config: RegistryConfig,
    provider: SecretProvider,
    client: RegistryClient,
) -> LoginSession:
    """Log in to ``config``'s registry, resolving the credential at use time.

    The password is resolved from ``provider`` here (and nowhere else), handed
    to ``client`` over stdin, and immediately verified to be absent from the
    login's ``argv``, environment keys, and log. A leaked credential raises
    :class:`SecretLeakError`; a failed login raises :class:`RegistryAuthError`.
    """
    password = provider.get_secret(config.credential_ref)
    if not password:
        raise SecretResolutionError(f"registry credential {config.credential_ref!r} resolved to an empty value")

    result = client.login(config.endpoint, config.username, password=password)

    # Belt-and-suspenders: the credential must not have leaked into any surface
    # the client hands back, regardless of the client's own guarantees.
    surface = " ".join([*result.argv, *result.env_keys, result.log])
    assert_no_secret_leak(surface, password, context="registry login surface")

    if not result.ok:
        raise RegistryAuthError(f"registry login rejected for {config.name!r} ({config.endpoint})")

    return LoginSession(
        registry=config.name,
        endpoint=config.endpoint,
        username=config.username,
        session_token=result.session_token,
        argv=result.argv,
        env_keys=result.env_keys,
        log=result.log,
    )


# ---------------------------------------------------------------------------
# Scoped secret delivery -- post-start, over an injected channel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretGrant:
    """Scopes which secret names an image is permitted to receive."""

    image_ref: str
    allowed_secret_names: frozenset[str]

    @classmethod
    def of(cls, image_ref: str, names: Iterable[str]) -> SecretGrant:
        return cls(image_ref=str(image_ref), allowed_secret_names=frozenset(str(n) for n in names))

    def permits(self, name: str) -> bool:
        return str(name) in self.allowed_secret_names

    def to_serializable(self) -> dict[str, object]:
        return {"image_ref": self.image_ref, "allowed_secret_names": sorted(self.allowed_secret_names)}


@runtime_checkable
class SecretDeliveryChannel(Protocol):
    """Delivers a secret to a running sandbox post-start (never at create)."""

    def deliver(self, sandbox_id: str, name: str, value: str) -> None: ...


class InMemorySecretChannel:
    """Hermetic post-start channel: an in-process stand-in for a runtime pipe.

    Real deployments inject a channel that writes to a mounted tmpfs or streams
    over a ``docker exec`` pipe into the already-running container. Either way
    the secret arrives **after** the container has started, so it is never part
    of the image, its build args, or its create-time env.
    """

    __slots__ = ("_delivered",)

    def __init__(self) -> None:
        self._delivered: dict[str, dict[str, str]] = {}

    def deliver(self, sandbox_id: str, name: str, value: str) -> None:
        self._delivered.setdefault(str(sandbox_id), {})[str(name)] = str(value)

    def delivered_names(self, sandbox_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._delivered.get(str(sandbox_id), {})))

    def read(self, sandbox_id: str, name: str) -> str | None:
        return self._delivered.get(str(sandbox_id), {}).get(str(name))

    def __repr__(self) -> str:  # never reveal delivered values
        counts = {sid: len(v) for sid, v in self._delivered.items()}
        return f"InMemorySecretChannel(delivered={counts})"


@dataclass(frozen=True)
class DeliveryReport:
    """Outcome of a scoped secret delivery."""

    sandbox_id: str
    delivered: tuple[str, ...]
    withheld: tuple[str, ...]

    def to_serializable(self) -> dict[str, object]:
        return {
            "sandbox_id": self.sandbox_id,
            "delivered": list(self.delivered),
            "withheld": list(self.withheld),
        }


def deliver_scoped_secrets(
    grant: SecretGrant,
    requested_names: Iterable[str],
    provider: SecretProvider,
    channel: SecretDeliveryChannel,
    *,
    sandbox_id: str,
    strict: bool = False,
) -> DeliveryReport:
    """Deliver only the ``grant``-permitted secrets among ``requested_names``.

    Each permitted name is resolved from ``provider`` at use time and pushed
    over ``channel`` to the running sandbox. A non-permitted name is withheld
    (skipped) -- or, when ``strict`` is set, raises :class:`SecretScopeError`.
    """
    delivered: list[str] = []
    withheld: list[str] = []
    for raw in requested_names:
        name = str(raw)
        if not grant.permits(name):
            if strict:
                raise SecretScopeError(f"secret {name!r} is not granted to image {grant.image_ref!r}")
            withheld.append(name)
            logger.debug("withholding non-granted secret %r from image %s", name, grant.image_ref)
            continue
        value = provider.get_secret(name)
        if not value:
            raise SecretResolutionError(f"granted secret {name!r} resolved to an empty value")
        channel.deliver(sandbox_id, name, value)
        delivered.append(name)
    return DeliveryReport(
        sandbox_id=str(sandbox_id),
        delivered=tuple(delivered),
        withheld=tuple(withheld),
    )


# ---------------------------------------------------------------------------
# The tie-together: a sandbox running a custom image
# ---------------------------------------------------------------------------


@dataclass
class SandboxImage:
    """A sandbox that runs a pinned custom image with a scoped secret grant.

    Ties the three invariants together: it launches an immutable manifest from
    an authenticated registry, guarantees its create-time env is secret-free,
    and delivers only granted secrets post-start.
    """

    manifest: ImageManifest
    registry: RegistryConfig
    grant: SecretGrant
    sandbox_id: str
    _login: LoginSession | None = field(default=None, init=False, repr=False)

    def create_env(self) -> dict[str, str]:
        """The env passed at container *create* -- from non-secret spec only.

        Secrets never appear here; they are delivered post-start instead.
        """
        raw_env = self.manifest.spec.get("env", {})
        env: dict[str, str] = {}
        if isinstance(raw_env, Mapping):
            for key, value in raw_env.items():
                env[str(key)] = str(value)
        env["THOMAS_IMAGE_DIGEST"] = self.manifest.digest
        return env

    def authenticate(self, provider: SecretProvider, client: RegistryClient) -> LoginSession:
        """Authenticate to the backing registry (credential resolved at use time)."""
        self._login = authenticate_registry(self.registry, provider, client)
        return self._login

    def deliver_secrets(
        self,
        requested_names: Iterable[str],
        provider: SecretProvider,
        channel: SecretDeliveryChannel,
        *,
        strict: bool = False,
    ) -> DeliveryReport:
        """Deliver granted secrets to the running sandbox, post-start."""
        return deliver_scoped_secrets(
            self.grant,
            requested_names,
            provider,
            channel,
            sandbox_id=self.sandbox_id,
            strict=strict,
        )

    def audit_surfaces(self) -> dict[str, str]:
        """Every serialized/logged surface a leak check should scan.

        Notably excludes the delivery channel: delivered secrets live only
        inside the running sandbox, not in any manifest/config/log artifact.
        """
        surfaces = {
            "manifest": self.manifest.to_json(),
            "registry_config": self.registry.to_json(),
            "grant": json.dumps(self.grant.to_serializable(), sort_keys=True),
            "create_env": json.dumps(self.create_env(), sort_keys=True),
        }
        if self._login is not None:
            surfaces["login_session"] = json.dumps(self._login.to_serializable(), sort_keys=True)
        return surfaces

    def leak_check(self, secret_values: str | Iterable[str]) -> int:
        """Total secret occurrences across all audit surfaces (must be zero)."""
        blob = "\n".join(self.audit_surfaces().values())
        return count_secret_occurrences(blob, secret_values)

    def assert_no_leak(self, secret_values: str | Iterable[str]) -> None:
        """Raise :class:`SecretLeakError` if any secret appears in an artifact."""
        blob = "\n".join(self.audit_surfaces().values())
        assert_no_secret_leak(blob, secret_values, context="sandbox image artifacts")
