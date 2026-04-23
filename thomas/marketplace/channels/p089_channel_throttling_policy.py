from __future__ import annotations

"""Channel throttling policy.

Implements a small, dependency-free token-bucket throttling policy.

This is meant to be shared by channel integrations (example: Telegram) and the
Thomas CLI.

The policy is generic: it throttles *events* (typically outbound messages) for a
bucket key. A bucket key can represent an integration ("telegram"), an
integration+destination ("telegram:123456"), or anything else that should be
rate-limited independently.

Why token-bucket?
- Supports bursts (up to a configured capacity).
- Enforces a long-term steady rate.
- Provides a meaningful "retry after" time when blocked.

Determinism:
All validation and I/O failures raise ChannelThrottleError with a stable code and
message. Errors are designed to be safe for machine consumption.
"""

import json
import math
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

SCHEMA_VERSION = 1


class ChannelThrottleError(Exception):
    """Deterministic error for throttling policy failures."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> ThrottleErrorJSON:
        payload: ThrottleErrorJSON = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ThrottleErrorJSON(TypedDict, total=False):
    code: str
    message: str
    details: dict[str, Any]


class ThrottlePolicyConfigJSON(TypedDict):
    rate_per_second: float
    burst: int


@dataclass(frozen=True, slots=True)
class ThrottlePolicyConfig:
    """Configuration for a token bucket."""

    rate_per_second: float
    burst: int

    def validate(self) -> None:
        if not isinstance(self.rate_per_second, (int, float)):
            raise ChannelThrottleError("invalid_config", "rate_per_second must be a number")
        rate = float(self.rate_per_second)
        if not math.isfinite(rate) or rate <= 0:
            raise ChannelThrottleError("invalid_config", "rate_per_second must be > 0")

        if not isinstance(self.burst, int):
            raise ChannelThrottleError("invalid_config", "burst must be an integer")
        if self.burst <= 0:
            raise ChannelThrottleError("invalid_config", "burst must be > 0")

    def to_dict(self) -> ThrottlePolicyConfigJSON:
        return {"rate_per_second": float(self.rate_per_second), "burst": int(self.burst)}


class TokenBucketStateJSON(TypedDict):
    tokens: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class TokenBucketState:
    """State for a token bucket."""

    tokens: float
    updated_at: float

    def to_dict(self) -> TokenBucketStateJSON:
        return {"tokens": float(self.tokens), "updated_at": float(self.updated_at)}

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> TokenBucketState:
        try:
            tokens = float(data["tokens"])
            updated_at = float(data["updated_at"])
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            raise ChannelThrottleError(
                "invalid_state",
                "invalid token bucket state",
                {"exception_type": type(exc).__name__},
            ) from None
        if not math.isfinite(tokens) or tokens < 0:
            raise ChannelThrottleError("invalid_state", "state.tokens must be >= 0")
        if not math.isfinite(updated_at) or updated_at < 0:
            raise ChannelThrottleError("invalid_state", "state.updated_at must be >= 0")
        return TokenBucketState(tokens=tokens, updated_at=updated_at)


class ThrottleCheckRequestJSON(TypedDict, total=False):
    bucket_key: str
    cost: float
    now: float
    dry_run: bool


@dataclass(frozen=True, slots=True)
class ThrottleCheckRequest:
    """Input contract for evaluating a throttling decision."""

    bucket_key: str
    cost: float = 1.0
    now: float | None = None
    dry_run: bool = False

    def to_dict(self) -> ThrottleCheckRequestJSON:
        payload: ThrottleCheckRequestJSON = {
            "bucket_key": self.bucket_key,
            "cost": float(self.cost),
            "dry_run": bool(self.dry_run),
        }
        if self.now is not None:
            payload["now"] = float(self.now)
        return payload


class ThrottleDecisionJSON(TypedDict):
    schema_version: int
    allowed: bool
    retry_after_seconds: float
    bucket_key: str
    now: float
    cost: float
    config: ThrottlePolicyConfigJSON
    state: TokenBucketStateJSON


@dataclass(frozen=True, slots=True)
class ThrottleDecision:
    """Output contract for a throttling evaluation."""

    allowed: bool
    retry_after_seconds: float
    bucket_key: str
    now: float
    cost: float
    config: ThrottlePolicyConfig
    state: TokenBucketState

    def to_dict(self) -> ThrottleDecisionJSON:
        return {
            "schema_version": SCHEMA_VERSION,
            "allowed": bool(self.allowed),
            "retry_after_seconds": float(self.retry_after_seconds),
            "bucket_key": str(self.bucket_key),
            "now": float(self.now),
            "cost": float(self.cost),
            "config": self.config.to_dict(),
            "state": self.state.to_dict(),
        }


class ThrottleStateStore(Protocol):
    """Minimal persistence interface for throttling state."""

    def load(self, bucket_key: str) -> TokenBucketState | None: ...

    def save(self, bucket_key: str, state: TokenBucketState) -> None: ...


class InMemoryThrottleStateStore:
    """An in-memory state store (useful for tests and ephemeral runs)."""

    def __init__(self) -> None:
        self._data: dict[str, TokenBucketState] = {}

    def load(self, bucket_key: str) -> TokenBucketState | None:
        return self._data.get(bucket_key)

    def save(self, bucket_key: str, state: TokenBucketState) -> None:
        self._data[bucket_key] = state


class _FileLock:
    """Best-effort cross-platform file lock using stdlib only.

    This lock is advisory and meant to reduce races for JsonFileThrottleStateStore
    in multi-process scenarios.
    """

    def __init__(self, lock_path: Path):
        self._lock_path = lock_path
        self._fh = None

    def __enter__(self) -> _FileLock:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise ChannelThrottleError(
                "state_lock_failed",
                "failed to lock throttle state file",
                {"path": str(self._lock_path), "exception_type": type(exc).__name__},
            ) from None
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                self._fh.close()
            except (ImportError, AttributeError, RuntimeError):
                pass
            self._fh = None


class JsonFileThrottleStateStore:
    """A JSON file-backed state store.

    File format: a single JSON object mapping bucket keys -> TokenBucketState.

    Missing file is treated as empty state.

    The store uses a sidecar lock file to reduce concurrent writer races.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")

    @property
    def path(self) -> Path:
        return self._path

    def _read_all_unlocked(self) -> dict[str, TokenBucketState]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ChannelThrottleError(
                "state_read_failed",
                "failed to read throttle state file",
                {"path": str(self._path), "exception_type": type(exc).__name__},
            ) from None
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            raise ChannelThrottleError(
                "state_read_failed",
                "throttle state file is not valid JSON",
                {"path": str(self._path), "exception_type": type(exc).__name__},
            ) from None
        if not isinstance(parsed, dict):
            raise ChannelThrottleError(
                "state_read_failed",
                "throttle state file must contain a JSON object",
                {"path": str(self._path)},
            )
        out: dict[str, TokenBucketState] = {}
        for k, v in parsed.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                raise ChannelThrottleError(
                    "state_read_failed",
                    "throttle state file has invalid structure",
                    {"path": str(self._path)},
                )
            out[k] = TokenBucketState.from_dict(v)
        return out

    def _write_all_unlocked(self, data: Mapping[str, TokenBucketState]) -> None:
        payload: dict[str, Any] = {k: v.to_dict() for k, v in sorted(data.items(), key=lambda kv: kv[0])}
        text = json.dumps(payload, indent=2, sort_keys=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(text + "\n", encoding="utf-8")
            os.replace(tmp_path, self._path)
        except OSError as exc:
            raise ChannelThrottleError(
                "state_write_failed",
                "failed to write throttle state file",
                {"path": str(self._path), "exception_type": type(exc).__name__},
            ) from None
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except (OSError, ConnectionError):
                pass

    def load(self, bucket_key: str) -> TokenBucketState | None:
        with _FileLock(self._lock_path):
            data = self._read_all_unlocked()
            return data.get(bucket_key)

    def save(self, bucket_key: str, state: TokenBucketState) -> None:
        with _FileLock(self._lock_path):
            data = self._read_all_unlocked()
            data[bucket_key] = state
            self._write_all_unlocked(data)


class ChannelThrottlePolicy:
    """Evaluates and persists token-bucket throttling decisions."""

    def __init__(self, config: ThrottlePolicyConfig, store: ThrottleStateStore | None = None):
        config.validate()
        self._config = config
        self._store: ThrottleStateStore = store or InMemoryThrottleStateStore()

    @property
    def config(self) -> ThrottlePolicyConfig:
        return self._config

    def evaluate(self, request: ThrottleCheckRequest) -> ThrottleDecision:
        if not isinstance(request.bucket_key, str) or not request.bucket_key.strip():
            raise ChannelThrottleError("invalid_input", "bucket_key must be a non-empty string")
        if not isinstance(request.cost, (int, float)):
            raise ChannelThrottleError("invalid_input", "cost must be a number")
        cost = float(request.cost)
        if not math.isfinite(cost) or cost <= 0:
            raise ChannelThrottleError("invalid_input", "cost must be > 0")

        now = float(request.now if request.now is not None else time.time())
        if not math.isfinite(now) or now < 0:
            raise ChannelThrottleError("invalid_input", "now must be a valid epoch timestamp")

        state = self._store.load(request.bucket_key)
        if state is None:
            state = TokenBucketState(tokens=float(self._config.burst), updated_at=now)

        elapsed = max(0.0, now - float(state.updated_at))
        tokens = min(float(self._config.burst), float(state.tokens) + elapsed * float(self._config.rate_per_second))

        if tokens + 1e-12 >= cost:
            allowed = True
            tokens_after = max(0.0, tokens - cost)
            retry_after = 0.0
        else:
            allowed = False
            tokens_after = tokens
            deficit = cost - tokens
            retry_after = max(0.0, deficit / float(self._config.rate_per_second))

        new_state = TokenBucketState(tokens=tokens_after, updated_at=now)

        if not request.dry_run:
            self._store.save(request.bucket_key, new_state)

        return ThrottleDecision(
            allowed=allowed,
            retry_after_seconds=retry_after,
            bucket_key=request.bucket_key,
            now=now,
            cost=cost,
            config=self._config,
            state=new_state,
        )

    def peek(self, request: ThrottleCheckRequest) -> ThrottleDecision:
        """Evaluate without persisting state."""
        return self.evaluate(
            ThrottleCheckRequest(
                bucket_key=request.bucket_key,
                cost=request.cost,
                now=request.now,
                dry_run=True,
            )
        )


def parse_throttle_policy_config(raw: Mapping[str, Any]) -> ThrottlePolicyConfig:
    """Parse a throttling policy config from a mapping.

    Supported keys (synonyms accepted):
    - rate_per_second
    - rate_per_minute
    - messages_per_second
    - messages_per_minute
    - burst (or capacity)

    Raises ChannelThrottleError on missing/invalid config.
    """

    burst_raw = raw.get("burst", raw.get("capacity"))
    if burst_raw is None:
        raise ChannelThrottleError("missing_config", "missing 'burst' for throttle policy")
    try:
        burst = int(burst_raw)
    except (ConnectionError, TimeoutError, RuntimeError):
        raise ChannelThrottleError("invalid_config", "burst must be an integer") from None

    rate: float | None = None
    if "rate_per_second" in raw:
        rate = float(raw["rate_per_second"])
    elif "messages_per_second" in raw:
        rate = float(raw["messages_per_second"])
    elif "rate_per_minute" in raw:
        rate = float(raw["rate_per_minute"]) / 60.0
    elif "messages_per_minute" in raw:
        rate = float(raw["messages_per_minute"]) / 60.0

    if rate is None:
        raise ChannelThrottleError("missing_config", "missing rate for throttle policy")

    config = ThrottlePolicyConfig(rate_per_second=float(rate), burst=burst)
    config.validate()
    return config


def load_throttle_policy_config_file(path: str | os.PathLike[str], channel: str) -> ThrottlePolicyConfig:
    """Load a policy config from a JSON file.

    The file may be either:
    - a single config object, or
    - an object with a top-level "channels" mapping and optional "defaults".

    Example:
      {"rate_per_second": 1.0, "burst": 5}

    Example:
      {
        "defaults": {"rate_per_second": 0.5, "burst": 2},
        "channels": {
           "telegram": {"messages_per_minute": 20, "burst": 10}
        }
      }
    """

    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ChannelThrottleError(
            "missing_config", "throttle policy config file not found", {"path": str(p)}
        ) from None
    except OSError as exc:
        raise ChannelThrottleError(
            "config_read_failed",
            "failed to read throttle policy config file",
            {"path": str(p), "exception_type": type(exc).__name__},
        ) from None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChannelThrottleError(
            "config_read_failed",
            "throttle policy config file is not valid JSON",
            {"path": str(p), "exception_type": type(exc).__name__},
        ) from None

    if not isinstance(data, dict):
        raise ChannelThrottleError("invalid_config", "throttle policy config must be a JSON object", {"path": str(p)})

    if "channels" in data:
        channels_raw = data.get("channels")
        if not isinstance(channels_raw, dict):
            raise ChannelThrottleError("invalid_config", "'channels' must be a JSON object", {"path": str(p)})

        channel_raw = channels_raw.get(channel)
        if channel_raw is None:
            defaults = data.get("defaults")
            if defaults is None:
                raise ChannelThrottleError(
                    "missing_config",
                    "no throttle policy found for channel",
                    {"path": str(p), "channel": channel},
                )
            if not isinstance(defaults, dict):
                raise ChannelThrottleError("invalid_config", "'defaults' must be a JSON object", {"path": str(p)})
            return parse_throttle_policy_config(defaults)

        if not isinstance(channel_raw, dict):
            raise ChannelThrottleError(
                "invalid_config",
                "channel throttle policy must be a JSON object",
                {"path": str(p), "channel": channel},
            )
        return parse_throttle_policy_config(channel_raw)

    return parse_throttle_policy_config(cast(Mapping[str, Any], data))
