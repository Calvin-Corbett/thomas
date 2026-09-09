"""P071 - Message voice metadata extraction.

This module provides best-effort voice metadata extraction for message attachments.
It keeps compatibility field names used by earlier prompt-pack flows.

Design goals
- Stable, machine-readable schema for automation.
- Deterministic error codes for invalid input, missing config/policy, and external failures.
- Best-effort local inspection when a file path is provided (cheap file stats + hash;
  WAV parsing via stdlib `wave` for sample rate / channels / duration).

Non-goals
- Audio transcoding/decoding beyond WAV header parsing.
- Network fetching of audio URLs (URL inputs are *recorded only* and gated by config).
"""

from __future__ import annotations

import hashlib
import mimetypes
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

SCHEMA_VERSION: int = 1


class VoiceMetadataStubError(RuntimeError):
    """Base error with deterministic code + structured details."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": dict(self.details)}


class InvalidVoiceMetadataRequestError(VoiceMetadataStubError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__("invalid_request", message, details=details)


class MissingVoiceMetadataConfigError(VoiceMetadataStubError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__("missing_config", message, details=details)


class VoiceMetadataExternalFailureError(VoiceMetadataStubError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__("external_failure", message, details=details)


class VoiceMetadataPayload(TypedDict, total=False):
    duration_ms: int | None
    size_bytes: int | None
    sha256: str | None
    mime_type: str | None

    sample_rate_hz: int | None
    channels: int | None
    bit_depth: int | None

    codec: str | None
    container: str | None


class VoiceMetadataStubRequestPayload(TypedDict, total=False):
    message_id: str
    audio_path: str
    audio_url: str


class VoiceMetadataStubResultPayload(TypedDict):
    schema_version: int
    message_id: str
    source: dict[str, Any]
    metadata: VoiceMetadataPayload
    is_stub: bool
    warnings: list[str]


@dataclass(frozen=True)
class VoiceMetadata:
    duration_ms: int | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    mime_type: str | None = None

    sample_rate_hz: int | None = None
    channels: int | None = None
    bit_depth: int | None = None

    codec: str | None = None
    container: str | None = None

    def to_dict(self) -> VoiceMetadataPayload:
        return {
            "duration_ms": self.duration_ms,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "bit_depth": self.bit_depth,
            "codec": self.codec,
            "container": self.container,
        }


@dataclass(frozen=True)
class VoiceMetadataStubRequest:
    message_id: str
    audio_path: str | None = None
    audio_url: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> VoiceMetadataStubRequest:
        return cls(
            message_id=str(payload.get("message_id", "")),
            audio_path=payload.get("audio_path") or None,
            audio_url=payload.get("audio_url") or None,
        )

    def to_dict(self) -> VoiceMetadataStubRequestPayload:
        out: VoiceMetadataStubRequestPayload = {"message_id": self.message_id}
        if self.audio_path is not None:
            out["audio_path"] = self.audio_path
        if self.audio_url is not None:
            out["audio_url"] = self.audio_url
        return out

    def validate(self) -> None:
        if not isinstance(self.message_id, str) or not self.message_id.strip():
            raise InvalidVoiceMetadataRequestError(
                "message_id must be a non-empty string",
                details={"field": "message_id"},
            )

        if self.audio_path is not None and not isinstance(self.audio_path, str):
            raise InvalidVoiceMetadataRequestError(
                "audio_path must be a string when provided",
                details={"field": "audio_path", "received_type": type(self.audio_path).__name__},
            )

        if self.audio_url is not None and not isinstance(self.audio_url, str):
            raise InvalidVoiceMetadataRequestError(
                "audio_url must be a string when provided",
                details={"field": "audio_url", "received_type": type(self.audio_url).__name__},
            )

        if self.audio_path and self.audio_url:
            raise InvalidVoiceMetadataRequestError(
                "Provide only one of audio_path or audio_url, not both.",
                details={"audio_path": True, "audio_url": True},
            )


@dataclass(frozen=True)
class VoiceMetadataStubResult:
    schema_version: int
    message_id: str
    source: dict[str, Any]
    metadata: VoiceMetadata
    is_stub: bool
    warnings: list[str]

    def to_dict(self) -> VoiceMetadataStubResultPayload:
        return {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "source": dict(self.source),
            "metadata": self.metadata.to_dict(),
            "is_stub": self.is_stub,
            "warnings": list(self.warnings),
        }


def run(
    payload: Mapping[str, Any] | VoiceMetadataStubRequest,
    *,
    config: Mapping[str, Any] | None = None,
) -> VoiceMetadataStubResultPayload:
    req = payload if isinstance(payload, VoiceMetadataStubRequest) else VoiceMetadataStubRequest.from_mapping(payload)
    return create_voice_metadata_stub(req, config=config).to_dict()


def create_voice_metadata_stub(
    request: VoiceMetadataStubRequest,
    *,
    config: Mapping[str, Any] | None = None,
) -> VoiceMetadataStubResult:
    if not isinstance(request, VoiceMetadataStubRequest):
        raise InvalidVoiceMetadataRequestError(
            "request must be a VoiceMetadataStubRequest",
            details={"received_type": type(request).__name__},
        )

    request.validate()

    warnings: list[str] = []
    source: dict[str, Any] = {"kind": "none", "inspection_mode": "none"}
    metadata = VoiceMetadata()
    is_stub = True

    if request.audio_url:
        parsed = urlparse(request.audio_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidVoiceMetadataRequestError(
                "audio_url must be an http(s) URL",
                details={"audio_url": request.audio_url},
            )

        # URL usage is config-gated. Even though we do NOT fetch, this keeps the
        # surface area intentional and avoids quietly accepting URLs.
        if config is None:
            raise MissingVoiceMetadataConfigError(
                "audio_url requires an explicit config/policy object",
                details={"required": "config", "audio_url": request.audio_url},
            )

        allow_urls = _config_get_bool(
            config, ["voice_metadata_allow_urls", "allow_urls", "allow_network"], default=False
        )
        if not allow_urls:
            raise MissingVoiceMetadataConfigError(
                "audio_url usage is disabled by config/policy",
                details={"audio_url": request.audio_url, "allow_urls": allow_urls},
            )

        source = {"kind": "url", "url": request.audio_url, "inspection_mode": "url_record_only"}
        warnings.append("url_source_not_fetched")

        return VoiceMetadataStubResult(
            schema_version=SCHEMA_VERSION,
            message_id=request.message_id,
            source=source,
            metadata=metadata,
            is_stub=True,
            warnings=warnings,
        )

    if request.audio_path:
        path = Path(request.audio_path)
        if not path.exists():
            raise VoiceMetadataExternalFailureError("audio_path does not exist", details={"audio_path": str(path)})
        if not path.is_file():
            raise VoiceMetadataExternalFailureError("audio_path is not a file", details={"audio_path": str(path)})

        try:
            size_bytes = int(path.stat().st_size)
        except OSError as e:
            raise VoiceMetadataExternalFailureError(
                "failed to stat audio_path",
                details={"audio_path": str(path), "os_error": type(e).__name__},
            ) from e

        try:
            sha256 = _sha256_file(path)
        except OSError as e:
            raise VoiceMetadataExternalFailureError(
                "failed to read audio_path for hashing",
                details={"audio_path": str(path), "os_error": type(e).__name__},
            ) from e

        guessed_mime, _ = mimetypes.guess_type(str(path))
        container = path.suffix.lower().lstrip(".") or None

        duration_ms: int | None = None
        sample_rate_hz: int | None = None
        channels: int | None = None
        bit_depth: int | None = None
        codec: str | None = None

        if container == "wav":
            try:
                with wave.open(str(path), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    sample_rate_hz = int(rate) if rate else None
                    channels = int(wf.getnchannels())
                    sampwidth = int(wf.getsampwidth())  # bytes
                    bit_depth = sampwidth * 8 if sampwidth else None
                    if rate:
                        duration_ms = int(round((frames / float(rate)) * 1000.0))
                    codec = "pcm"
            except wave.Error:
                warnings.append("wav_parse_failed")
        else:
            warnings.append("audio_not_inspected")

        metadata = VoiceMetadata(
            duration_ms=duration_ms,
            size_bytes=size_bytes,
            sha256=sha256,
            mime_type=guessed_mime,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            bit_depth=bit_depth,
            codec=codec,
            container=container,
        )
        source = {"kind": "file", "path": str(path), "inspection_mode": "file_best_effort"}
        # Local file mode performs real metadata extraction (size/hash + optional WAV details).
        is_stub = False
    else:
        warnings.append("no_audio_source")

    return VoiceMetadataStubResult(
        schema_version=SCHEMA_VERSION,
        message_id=request.message_id,
        source=source,
        metadata=metadata,
        is_stub=is_stub,
        warnings=warnings,
    )


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _config_get_bool(config: Any, keys: list[str], *, default: bool) -> bool:
    """Read a bool-ish flag from a Mapping or attribute-based config.

    Checks keys in order; first match wins.
    """
    if config is None:
        return default
    if isinstance(config, Mapping):
        for k in keys:
            if k in config:
                return bool(config.get(k))
        return default
    for k in keys:
        if hasattr(config, k):
            return bool(getattr(config, k))
    return default
