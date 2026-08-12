"""CAP-062 L2: custom images, scoped secrets, authenticated registries.

Proves the exact acceptance line:
- an image manifest pins ``name:version`` to a content digest and re-publishing
  the same tag is rejected (immutable);
- a registry login resolves the credential from the provider at use time and the
  value is ABSENT from the serialized config and from the login logs/argv/env;
- a :class:`SecretGrant` delivers only the scoped secrets to an image and a
  non-granted secret is withheld;
- a leak check finds zero secret occurrences in the manifest/config/logs;
- round-trip (publish -> resolve -> authenticate -> deliver -> leak-check).

Hermetic: an injected fake registry client (no docker, no network), an in-memory
secret provider, an in-memory post-start delivery channel, and a fixed clock.
"""

from __future__ import annotations

import json

import pytest

from thomas.tools.sandbox_images import (
    ImageRegistry,
    ImmutableImageError,
    InMemorySecretChannel,
    MappingSecretProvider,
    RegistryConfig,
    RegistryLoginResult,
    SandboxImage,
    SecretGrant,
    SecretLeakError,
    SecretScopeError,
    authenticate_registry,
    content_digest,
    deliver_scoped_secrets,
    parse_reference,
)

CLOCK = "2026-07-21T00:00:00Z"
REGISTRY_PASSWORD = "rG-p@ss-0xDEADBEEF-secret"
DB_SECRET = "db://user:5up3r-s3cret-token@host/prod"
API_SECRET = "sk-live-9f8e7d6c5b4a3210-do-not-log"

SPEC = {
    "base": "python:3.12-slim",
    "layers": ["pip install thomas", "copy ./app /app"],
    "env": {"THOMAS_ENV": "prod", "PORT": "8899"},
    "labels": {"org.thomas.cap": "062"},
}


class RecordingRegistryClient:
    """Fake registry client that proves the password travels over stdin only.

    It records what it was handed and asserts, at call time, that the secret is
    NOT in the argv it would exec and NOT in the environment it would set.
    """

    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.calls: list[dict[str, object]] = []

    def login(self, endpoint: str, username: str, *, password: str) -> RegistryLoginResult:
        # Emulate a `login --password-stdin` command: password on stdin, not argv/env.
        argv = ("docker", "login", endpoint, "--username", username, "--password-stdin")
        env_keys = ("PATH", "HOME")  # deliberately excludes any credential var
        stdin_payload = password  # this is the ONLY place the secret is used
        assert password not in argv, "password must never appear in argv"
        assert password not in env_keys
        self.calls.append({"endpoint": endpoint, "username": username, "argv": argv, "stdin": stdin_payload})
        # A well-behaved registry never echoes the credential; log is redaction-safe.
        log = f"Login {'Succeeded' if self.succeed else 'FAILED'} for {username}@{endpoint}"
        return RegistryLoginResult(
            ok=self.succeed,
            session_token=f"session:{endpoint}" if self.succeed else "",
            argv=argv,
            env_keys=env_keys,
            log=log,
        )


def _provider() -> MappingSecretProvider:
    return MappingSecretProvider(
        {
            "REGISTRY_PW": REGISTRY_PASSWORD,
            "DB_URL": DB_SECRET,
            "API_KEY": API_SECRET,
        }
    )


def _registry_config() -> RegistryConfig:
    return RegistryConfig(
        name="internal",
        endpoint="registry.internal:5000",
        username="ci-bot",
        credential_ref="REGISTRY_PW",
    )


# ---------------------------------------------------------------------------
# 1. Immutable image manifests -- tag pins a digest, re-publish rejected
# ---------------------------------------------------------------------------


def test_manifest_pins_tag_to_digest() -> None:
    reg = ImageRegistry()
    manifest = reg.publish("app", "1.4.2", SPEC, created_at=CLOCK)

    assert manifest.reference == "app:1.4.2"
    assert manifest.digest == content_digest(SPEC)
    assert manifest.digest.startswith("sha256:")
    # The tag resolves to exactly that digest, and the digest round-trips.
    assert reg.resolve_tag("app", "1.4.2") == manifest.digest
    assert reg.get_by_digest(manifest.digest).reference == "app:1.4.2"
    assert reg.get("app", "1.4.2").digest == manifest.digest


def test_digest_is_deterministic_and_content_addressed() -> None:
    # Key order does not change the digest; different content does.
    reordered = {k: SPEC[k] for k in reversed(list(SPEC))}
    assert content_digest(reordered) == content_digest(SPEC)
    changed = dict(SPEC)
    changed["base"] = "python:3.11-slim"
    assert content_digest(changed) != content_digest(SPEC)


def test_republish_same_tag_is_rejected_immutable() -> None:
    reg = ImageRegistry()
    reg.publish("app", "1.4.2", SPEC, created_at=CLOCK)

    # Re-publishing the identical tag is rejected even with identical content...
    with pytest.raises(ImmutableImageError):
        reg.publish("app", "1.4.2", SPEC, created_at=CLOCK)
    # ...and rejected with changed content too (tags never mutate).
    with pytest.raises(ImmutableImageError):
        reg.publish("app", "1.4.2", {**SPEC, "base": "other"}, created_at=CLOCK)

    # A new version is a distinct immutable tag.
    other = reg.publish("app", "1.5.0", {**SPEC, "base": "python:3.12"}, created_at=CLOCK)
    assert other.digest != reg.resolve_tag("app", "1.4.2")
    assert set(reg.tags()) == {"app:1.4.2", "app:1.5.0"}


# ---------------------------------------------------------------------------
# 2. Authenticated registries -- credential resolved at use time, never leaked
# ---------------------------------------------------------------------------


def test_registry_config_serialization_holds_only_reference() -> None:
    config = _registry_config()
    blob = config.to_json()
    assert "REGISTRY_PW" in blob  # the reference is present
    assert REGISTRY_PASSWORD not in blob  # the value is not
    assert config.to_serializable()["credential_ref"] == "REGISTRY_PW"


def test_registry_login_resolves_credential_and_hides_it() -> None:
    config = _registry_config()
    provider = _provider()
    client = RecordingRegistryClient()

    session = authenticate_registry(config, provider, client)

    # Credential was resolved from the provider at use time and reached the
    # client exactly once, over stdin.
    assert len(client.calls) == 1
    assert client.calls[0]["stdin"] == REGISTRY_PASSWORD
    assert REGISTRY_PASSWORD not in client.calls[0]["argv"]

    # It is absent from every surface of the resulting session.
    session_blob = json.dumps(session.to_serializable())
    assert REGISTRY_PASSWORD not in session_blob
    assert REGISTRY_PASSWORD not in " ".join(session.argv)
    assert REGISTRY_PASSWORD not in session.log
    assert session.session_token == "session:registry.internal:5000"


def test_registry_login_rejects_empty_credential() -> None:
    config = RegistryConfig("r", "e", "u", credential_ref="MISSING")
    provider = MappingSecretProvider({"MISSING": ""})
    with pytest.raises(Exception):  # SecretResolutionError
        authenticate_registry(config, provider, RecordingRegistryClient())


# ---------------------------------------------------------------------------
# 3. Scoped secret delivery -- only granted secrets delivered, rest withheld
# ---------------------------------------------------------------------------


def test_grant_delivers_only_scoped_secrets() -> None:
    provider = _provider()
    channel = InMemorySecretChannel()
    grant = SecretGrant.of("app:1.4.2", ["DB_URL"])  # API_KEY NOT granted

    report = deliver_scoped_secrets(
        grant,
        ["DB_URL", "API_KEY"],
        provider,
        channel,
        sandbox_id="sbx-1",
    )

    assert report.delivered == ("DB_URL",)
    assert report.withheld == ("API_KEY",)
    # Only the granted secret actually reached the running sandbox.
    assert channel.delivered_names("sbx-1") == ("DB_URL",)
    assert channel.read("sbx-1", "DB_URL") == DB_SECRET
    assert channel.read("sbx-1", "API_KEY") is None


def test_non_granted_secret_raises_in_strict_mode() -> None:
    provider = _provider()
    channel = InMemorySecretChannel()
    grant = SecretGrant.of("app:1.4.2", ["DB_URL"])
    with pytest.raises(SecretScopeError):
        deliver_scoped_secrets(grant, ["API_KEY"], provider, channel, sandbox_id="sbx-1", strict=True)


# ---------------------------------------------------------------------------
# 4/5. Leak check + full round-trip
# ---------------------------------------------------------------------------


def test_round_trip_no_secret_leakage() -> None:
    provider = _provider()
    reg = ImageRegistry()
    manifest = reg.publish("app", "1.4.2", SPEC, created_at=CLOCK)

    sandbox = SandboxImage(
        manifest=manifest,
        registry=_registry_config(),
        grant=SecretGrant.of(manifest.reference, ["DB_URL"]),
        sandbox_id="sbx-42",
    )

    # create-time env is built from the non-secret spec only.
    create_env = sandbox.create_env()
    assert create_env["THOMAS_ENV"] == "prod"
    assert create_env["THOMAS_IMAGE_DIGEST"] == manifest.digest
    assert DB_SECRET not in json.dumps(create_env)

    # authenticate (credential at use time) + deliver scoped secrets post-start.
    client = RecordingRegistryClient()
    sandbox.authenticate(provider, client)
    report = sandbox.deliver_secrets(["DB_URL", "API_KEY"], provider, InMemorySecretChannel())
    assert report.delivered == ("DB_URL",)
    assert report.withheld == ("API_KEY",)

    # Leak check: zero occurrences of ANY secret across every artifact surface.
    all_secrets = [REGISTRY_PASSWORD, DB_SECRET, API_SECRET]
    assert sandbox.leak_check(all_secrets) == 0
    sandbox.assert_no_leak(all_secrets)  # does not raise

    # And the tag still resolves to the pinned digest after the whole flow.
    assert reg.resolve_tag("app", "1.4.2") == manifest.digest
    assert parse_reference(manifest.reference) == ("app", "1.4.2")


def test_leak_check_catches_a_planted_leak() -> None:
    """The leak check is not vacuous: a secret in a manifest label is caught."""
    reg = ImageRegistry()
    # Simulate the anti-pattern: a secret baked into the image spec.
    bad_spec = {**SPEC, "labels": {"leaked": DB_SECRET}}
    manifest = reg.publish("bad", "1.0.0", bad_spec, created_at=CLOCK)
    sandbox = SandboxImage(
        manifest=manifest,
        registry=_registry_config(),
        grant=SecretGrant.of(manifest.reference, ["DB_URL"]),
        sandbox_id="sbx-bad",
    )
    assert sandbox.leak_check(DB_SECRET) == 1
    with pytest.raises(SecretLeakError):
        sandbox.assert_no_leak(DB_SECRET)
