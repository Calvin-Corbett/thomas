"""Moved to :mod:`thomas.core.model_auth_health`.

This lived here for one commit. The orchestrator brain is where a rejected
credential is first observed, and ``marketplace`` may not import ``server``, so
the module moved down to ``core`` where both the brain and the health endpoint
can reach it.

Kept as a re-export rather than deleted: removing a file under ``thomas/server``
requires a human-approved deletion record, and this shim is not worth asking for
one. Safe to delete whenever that record is made.
"""

from __future__ import annotations

from thomas.core.model_auth_health import (
    APP_MODEL_AUTH_STATE,
    SIGN_IN_REMEDY,
    inspect_stored_credential,
    looks_like_auth_failure,
    model_auth_health,
    record_auth_failure,
    record_auth_success,
)

__all__ = [
    "APP_MODEL_AUTH_STATE",
    "SIGN_IN_REMEDY",
    "inspect_stored_credential",
    "looks_like_auth_failure",
    "model_auth_health",
    "record_auth_failure",
    "record_auth_success",
]
