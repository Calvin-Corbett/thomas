"""CAP-120 L2: one-step deploy/hosting with isolated environments.

Proves, against a hermetic fake hosting provider and an injected clock:

- ``deploy`` returns a hosted **HTTPS** deployment record for the target
  environment (url / environment / version / status), in a single call.
- Deploying to ``prod`` leaves ``staging``'s current deployment unchanged
  (environment isolation).
- Each environment tracks its own history.
- ``rollback`` restores the previous deployment for that environment (and only
  that environment).
- A failed deploy is reported (``DeployError`` + a ``failed`` history record),
  not a fabricated success, and does not clobber the current deployment.
- Round-trip: current/history reflect exactly what was deployed.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.tools.deploy_hosting import (
    ENV_PROD,
    ENV_STAGING,
    STATUS_FAILED,
    STATUS_LIVE,
    Artifact,
    DeployError,
    DeployHosting,
    FakeHostProvider,
    NoPreviousDeploymentError,
    StaticHostProvider,
    UnknownEnvironmentError,
)


def _clock():
    """Deterministic monotonically-increasing injected clock."""
    counter = itertools.count(1000)
    return lambda: float(next(counter))


def _artifact(name: str = "landing", body: bytes = b"<html>v1</html>") -> Artifact:
    return Artifact(name=name, content=body)


def test_deploy_returns_https_record_for_target_environment() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    rec = dh.deploy(_artifact(), environment=ENV_STAGING)

    assert rec.status == STATUS_LIVE
    assert rec.environment == ENV_STAGING
    assert rec.url.startswith("https://")
    assert rec.is_live
    assert rec.version == 1
    assert dh.current(ENV_STAGING) is rec


def test_default_provider_builds_https_url() -> None:
    # The real default adapter (no network) derives a deterministic HTTPS URL.
    dh = DeployHosting(StaticHostProvider(domain="apps.example"), clock=_clock())
    prod = dh.deploy(_artifact("My Site"), environment=ENV_PROD)
    staging = dh.deploy(_artifact("My Site"), environment=ENV_STAGING)

    assert prod.url == "https://my-site.apps.example/v1"
    assert staging.url == "https://staging--my-site.apps.example/v1"


def test_prod_deploy_does_not_clobber_staging() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    staging_rec = dh.deploy(_artifact(body=b"staging"), environment=ENV_STAGING)
    prod_rec = dh.deploy(_artifact(body=b"prod"), environment=ENV_PROD)

    # Staging's current deployment is untouched by the prod deploy.
    assert dh.current(ENV_STAGING) is staging_rec
    assert dh.current(ENV_PROD) is prod_rec
    assert staging_rec.url != prod_rec.url
    # Isolation extends to history and version counters.
    assert len(dh.history(ENV_STAGING)) == 1
    assert len(dh.history(ENV_PROD)) == 1


def test_each_environment_tracks_its_own_history() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    dh.deploy(_artifact(body=b"a"), environment=ENV_STAGING)
    dh.deploy(_artifact(body=b"b"), environment=ENV_STAGING)
    dh.deploy(_artifact(body=b"c"), environment=ENV_PROD)

    staging_hist = dh.history(ENV_STAGING)
    prod_hist = dh.history(ENV_PROD)
    assert [r.version for r in staging_hist] == [1, 2]
    assert [r.version for r in prod_hist] == [1]
    assert all(r.environment == ENV_STAGING for r in staging_hist)


def test_rollback_restores_previous_deployment_for_that_environment() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    v1 = dh.deploy(_artifact(body=b"one"), environment=ENV_PROD)
    v2 = dh.deploy(_artifact(body=b"two"), environment=ENV_PROD)
    assert dh.current(ENV_PROD) is v2

    restored = dh.rollback(ENV_PROD)
    # Current now serves the previous deployment's URL again.
    assert restored.url == v1.url
    assert dh.current(ENV_PROD).url == v1.url
    assert restored.url != v2.url
    assert dh.current(ENV_PROD).status == STATUS_LIVE


def test_rollback_is_isolated_per_environment() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    dh.deploy(_artifact(body=b"s1"), environment=ENV_STAGING)
    dh.deploy(_artifact(body=b"s2"), environment=ENV_STAGING)
    prod = dh.deploy(_artifact(body=b"p1"), environment=ENV_PROD)

    dh.rollback(ENV_STAGING)
    # Prod is completely unaffected by the staging rollback.
    assert dh.current(ENV_PROD) is prod
    assert len(dh.history(ENV_PROD)) == 1


def test_rollback_without_history_raises() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    dh.deploy(_artifact(), environment=ENV_PROD)  # only one deployment
    with pytest.raises(NoPreviousDeploymentError):
        dh.rollback(ENV_PROD)


def test_failed_deploy_is_reported_not_faked() -> None:
    provider = FakeHostProvider(fail_environments=frozenset({ENV_PROD}))
    dh = DeployHosting(provider, clock=_clock())
    good = dh.deploy(_artifact(body=b"ok"), environment=ENV_STAGING)

    with pytest.raises(DeployError) as excinfo:
        dh.deploy(_artifact(body=b"boom"), environment=ENV_PROD)

    failed = excinfo.value.record
    assert failed.status == STATUS_FAILED
    assert failed.environment == ENV_PROD
    # No fake success: prod never got a current deployment...
    assert dh.current(ENV_PROD) is None
    # ...but the failure is auditable in prod's history.
    assert [r.status for r in dh.history(ENV_PROD)] == [STATUS_FAILED]
    # ...and the healthy staging deploy is untouched.
    assert dh.current(ENV_STAGING) is good


def test_failed_deploy_leaves_prior_current_unchanged() -> None:
    provider = FakeHostProvider()
    dh = DeployHosting(provider, clock=_clock())
    v1 = dh.deploy(_artifact(body=b"one"), environment=ENV_PROD)

    # Now make the next provision fail and retry.
    provider.fail_environments = frozenset({ENV_PROD})
    with pytest.raises(DeployError):
        dh.deploy(_artifact(body=b"two"), environment=ENV_PROD)

    # The live v1 is still current; it was not clobbered by the failed attempt.
    assert dh.current(ENV_PROD) is v1
    assert dh.current(ENV_PROD).is_live


def test_unknown_environment_raises() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    with pytest.raises(UnknownEnvironmentError):
        dh.deploy(_artifact(), environment="qa")


def test_round_trip_current_and_history() -> None:
    dh = DeployHosting(FakeHostProvider(), clock=_clock())
    art = _artifact(name="dashboard", body=b"payload")
    rec = dh.deploy(art, environment=ENV_STAGING)

    current = dh.current(ENV_STAGING)
    assert current == rec
    assert current.app_name == "dashboard"
    assert current.artifact_digest == art.digest
    assert dh.history(ENV_STAGING)[-1] == rec
    assert current.provider == "fake-host"
