from __future__ import annotations

import platform
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

DESKTOP_OPERATOR_SERVICE_ID = "desktop.operator"
DESKTOP_OPERATOR_VERSION = "3.1.0"

SESSION_STATES = (
    "active",
    "paused_for_approval",
    "blocked_by_policy",
    "needs_rebind",
    "verification_failed",
    "terminated",
)
RISK_LEVELS = ("low", "medium", "high")
ACTION_CLASSES = ("safe", "bounded", "approval_required", "blocked")


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, int(self.right) - int(self.left))

    @property
    def height(self) -> int:
        return max(0, int(self.bottom) - int(self.top))

    def to_dict(self) -> dict[str, int]:
        return {
            "left": int(self.left),
            "top": int(self.top),
            "right": int(self.right),
            "bottom": int(self.bottom),
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    executable_path: str
    process_id: int
    visible: bool
    minimized: bool
    monitor_id: str
    bounds: Rect
    client_bounds: Rect
    class_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": int(self.handle),
            "title": self.title,
            "executable_path": self.executable_path,
            "process_id": int(self.process_id),
            "visible": bool(self.visible),
            "minimized": bool(self.minimized),
            "monitor_id": self.monitor_id,
            "bounds": self.bounds.to_dict(),
            "client_bounds": self.client_bounds.to_dict(),
            "class_name": self.class_name,
        }


@dataclass(frozen=True)
class DesktopVmContext:
    vm_id: str
    provider: str
    isolation_mode: str
    isolated: bool
    os_name: str = platform.system() or "Windows"
    viewer_mode: str = "none"
    viewer_url: str = ""
    viewer_label: str = ""
    viewer_takeover_supported: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "vm_id": self.vm_id,
            "provider": self.provider,
            "isolation_mode": self.isolation_mode,
            "isolated": bool(self.isolated),
            "os_name": self.os_name,
            "viewer_mode": self.viewer_mode,
            "viewer_url": self.viewer_url,
            "viewer_label": self.viewer_label,
            "viewer_takeover_supported": bool(self.viewer_takeover_supported),
        }


@dataclass(frozen=True)
class CaptureArtifact:
    path: str
    source: str
    timestamp_epoch_s: float
    occlusion_safe: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source": self.source,
            "timestamp_epoch_s": float(self.timestamp_epoch_s),
            "occlusion_safe": bool(self.occlusion_safe),
        }


@dataclass
class DesktopSession:
    session_id: str
    session_type: str
    workflow_profile: str
    adapter_name: str
    vm_id: str
    isolated: bool
    created_at_epoch_s: float
    last_seen_epoch_s: float
    expires_at_epoch_s: float
    replay_mode: str = "redacted"
    session_state: str = "active"
    risk_level: str = "low"
    risk_score: int = 0
    magic_ready: bool = True
    handle: int = 0
    process_id: int = 0
    executable_path: str = ""
    title_snapshot: str = ""
    monitor_id: str = ""
    verification_status: str = "unverified"
    bound_app_title: str = ""
    control_layer_used: str = ""
    last_capture_path: str = ""
    last_capture_source: str = ""
    last_target_confidence: float = 0.0
    last_refusal_reason: str = ""
    last_verified_state_path: str = ""
    last_action: dict[str, Any] | None = None
    pending_approval_reason: str = ""
    sensitive_mode: bool = False
    secret_zone_hits: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    retry_budget_remaining: int = 2
    verify_failures: int = 0
    low_confidence_events: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    step_count: int = 0

    @classmethod
    def start(
        cls,
        *,
        ttl_s: int,
        vm_context: DesktopVmContext,
        workflow_profile: str,
        adapter_name: str,
        session_type: str,
        replay_mode: str = "redacted",
        metadata: dict[str, Any] | None = None,
        allowed_domains: list[str] | None = None,
        allowed_paths: list[str] | None = None,
    ) -> DesktopSession:
        now = time.time()
        initial_risk = "low" if vm_context.isolated else "high"
        return cls(
            session_id=f"desktop-session-{uuid.uuid4().hex}",
            session_type=session_type,
            workflow_profile=workflow_profile,
            adapter_name=adapter_name,
            vm_id=vm_context.vm_id,
            isolated=bool(vm_context.isolated),
            created_at_epoch_s=now,
            last_seen_epoch_s=now,
            expires_at_epoch_s=now + max(30, int(ttl_s)),
            replay_mode=str(replay_mode or "redacted").strip().lower() or "redacted",
            risk_level=initial_risk,
            risk_score=0 if vm_context.isolated else 70,
            magic_ready=bool(vm_context.isolated),
            metadata=dict(metadata or {}),
            allowed_domains=[str(item).strip().lower() for item in (allowed_domains or []) if str(item).strip()],
            allowed_paths=[str(item).strip() for item in (allowed_paths or []) if str(item).strip()],
        )

    def bind_window(self, window: WindowInfo) -> None:
        self.handle = int(window.handle)
        self.process_id = int(window.process_id)
        self.executable_path = window.executable_path
        self.title_snapshot = window.title
        self.bound_app_title = window.title
        self.monitor_id = window.monitor_id

    def clear_binding(self) -> None:
        self.handle = 0
        self.process_id = 0
        self.executable_path = ""
        self.title_snapshot = ""
        self.bound_app_title = ""
        self.monitor_id = ""
        self.control_layer_used = ""

    def touch(self, *, ttl_s: int | None = None) -> None:
        now = time.time()
        self.last_seen_epoch_s = now
        if ttl_s is not None:
            self.expires_at_epoch_s = now + max(30, int(ttl_s))

    def is_expired(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current > float(self.expires_at_epoch_s)

    def add_artifact(self, path: str) -> None:
        normalized = str(path or "").strip()
        if normalized and normalized not in self.artifact_refs:
            self.artifact_refs.append(normalized)

    def remove_artifact(self, path: str) -> None:
        normalized = str(path or "").strip()
        if not normalized:
            return
        self.artifact_refs = [item for item in self.artifact_refs if item != normalized]

    def set_state(self, state: str, *, reason: str = "") -> None:
        normalized = str(state or "").strip().lower()
        if normalized not in SESSION_STATES:
            raise ValueError(f"unsupported session state: {state}")
        self.session_state = normalized
        if reason:
            self.last_refusal_reason = str(reason).strip()

    def set_risk(self, level: str, *, score: int | None = None) -> None:
        normalized = str(level or "").strip().lower()
        if normalized not in RISK_LEVELS:
            raise ValueError(f"unsupported risk level: {level}")
        self.risk_level = normalized
        if score is not None:
            self.risk_score = max(0, int(score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "workflow_profile": self.workflow_profile,
            "adapter_name": self.adapter_name,
            "vm_id": self.vm_id,
            "isolated": bool(self.isolated),
            "created_at_epoch_s": float(self.created_at_epoch_s),
            "last_seen_epoch_s": float(self.last_seen_epoch_s),
            "expires_at_epoch_s": float(self.expires_at_epoch_s),
            "replay_mode": self.replay_mode,
            "session_state": self.session_state,
            "risk_level": self.risk_level,
            "risk_score": int(self.risk_score),
            "magic_ready": bool(self.magic_ready),
            "handle": int(self.handle),
            "process_id": int(self.process_id),
            "executable_path": self.executable_path,
            "title_snapshot": self.title_snapshot,
            "monitor_id": self.monitor_id,
            "verification_status": self.verification_status,
            "bound_app_title": self.bound_app_title,
            "control_layer_used": self.control_layer_used,
            "last_capture_path": self.last_capture_path,
            "last_capture_source": self.last_capture_source,
            "last_target_confidence": float(self.last_target_confidence),
            "last_refusal_reason": self.last_refusal_reason,
            "last_verified_state_path": self.last_verified_state_path,
            "last_action": self.last_action,
            "pending_approval_reason": self.pending_approval_reason,
            "sensitive_mode": bool(self.sensitive_mode),
            "secret_zone_hits": list(self.secret_zone_hits),
            "allowed_domains": list(self.allowed_domains),
            "allowed_paths": list(self.allowed_paths),
            "artifact_refs": list(self.artifact_refs),
            "retry_budget_remaining": int(self.retry_budget_remaining),
            "verify_failures": int(self.verify_failures),
            "low_confidence_events": int(self.low_confidence_events),
            "metadata": dict(self.metadata),
            "step_count": int(self.step_count),
        }


class DesktopOperatorError(RuntimeError):
    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": dict(self.details)}


def invalid_input(message: str, **details: Any) -> DesktopOperatorError:
    return DesktopOperatorError("invalid_input", message, details=details)


def missing_config(message: str, **details: Any) -> DesktopOperatorError:
    return DesktopOperatorError("missing_config", message, details=details)


def external_failure(message: str, **details: Any) -> DesktopOperatorError:
    return DesktopOperatorError("external_failure", message, details=details)


def session_error(message: str, **details: Any) -> DesktopOperatorError:
    return DesktopOperatorError("invalid_session", message, details=details)


def not_found(message: str, **details: Any) -> DesktopOperatorError:
    return DesktopOperatorError("not_found", message, details=details)


def unsupported(message: str, **details: Any) -> DesktopOperatorError:
    return DesktopOperatorError("unsupported", message, details=details)
