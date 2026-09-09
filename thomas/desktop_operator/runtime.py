from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir
from thomas.marketplace.vision.ocr_fallback import extract_text_from_images

from .app_adapters import (
    adapter_by_profile,
    allowed_workflow_profiles,
    magic_quality_bar,
    resolve_adapter_for_window,
    workflow_profile_payloads,
)
from .contracts import (
    DESKTOP_OPERATOR_SERVICE_ID,
    DESKTOP_OPERATOR_VERSION,
    DesktopSession,
    invalid_input,
    not_found,
    session_error,
)
from .operation_handlers import OperationHandlersMixin
from .vm import resolve_vm_context
from .windows_adapter import DesktopAdapter, WindowsDesktopAdapter

_ALLOWED_KEYS = {"enter", "escape", "esc", "tab", "up", "down", "left", "right"}
_GENERIC_ACTIONS = {"click", "type", "press_keys", "drag", "ensure_visible"}
_ACTIVE_SESSION_STATES = {"active"}
_SECRET_VALUE_RE = re.compile(r"(?ix)" r"(password\s*[:=]\s*\S+)" r"|([A-Za-z0-9_\-]{24,})" r"|(\b\d{6,8}\b)")
_SECRET_LABEL_RE = re.compile(
    r"(?ix)"
    r"(password|passkey|verification\ code|security\ code|one[- ]time\ code|otp|2fa|mfa|authenticator|secret|token)"
)
_HIGH_RISK_TEXT_RE = re.compile(
    r"(?ix)"
    r"(password|passkey|verification\ code|security\ code|mfa|2fa|otp|billing|payment|checkout|publish|share|send|upload|delete|remove|security\ settings|account\ settings|installer|administrator|elevat)"
)
_SECRET_ZONE_DEFAULTS = (
    "password",
    "passkey",
    "verification code",
    "security code",
    "2fa",
    "mfa",
    "one-time code",
    "sign in",
    "log in",
    "authenticator",
)
_MAX_VERIFY_FAILURES_BEFORE_TERMINATE = 3
_LOW_CONFIDENCE_THRESHOLD = 0.70
_LOW_CONFIDENCE_LIMIT = 2


def resolve_artifacts_dir() -> Path:
    raw = str(os.environ.get("THOMAS_ARTIFACT_DIR") or "").strip()
    if raw:
        root = Path(raw).expanduser().resolve()
    else:
        root = resolve_thomas_data_dir() / "artifacts"
    path = (root / "desktop_operator").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


class DesktopOperatorRuntime(OperationHandlersMixin):
    def __init__(
        self,
        *,
        adapter: DesktopAdapter | None = None,
        artifacts_dir: Path | None = None,
        session_ttl_s: int = 900,
        vm_context=None,
        allowlisted_profiles: list[str] | None = None,
    ) -> None:
        self.adapter = adapter or WindowsDesktopAdapter()
        self.artifacts_dir = (artifacts_dir or resolve_artifacts_dir()).resolve()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.session_ttl_s = max(30, int(session_ttl_s))
        self.vm_context = vm_context or resolve_vm_context()
        configured = [str(item or "").strip().lower() for item in (allowlisted_profiles or allowed_workflow_profiles())]
        self.allowlisted_profiles = {item for item in configured if item}
        self._session: DesktopSession | None = None
        self._last_error: dict[str, Any] | None = None
        self._last_refusal_reason = ""

    def start_session(
        self,
        *,
        workflow_profile: str,
        session_type: str = "",
        session_ttl_s: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = str(workflow_profile or "").strip().lower()
        adapter = adapter_by_profile(profile)
        if adapter is None or profile not in self.allowlisted_profiles:
            raise invalid_input(
                "Desktop operator only starts allowlisted workflow profiles.",
                workflow_profile=profile,
                allowlisted_profiles=sorted(self.allowlisted_profiles),
            )
        ttl_s = max(30, int(session_ttl_s or self.session_ttl_s))
        resolved_type = str(session_type or "").strip().lower() or (
            "isolated_vm" if self.vm_context.isolated else "shared_session"
        )
        metadata_payload = dict(metadata or {})
        allowed_domains = self._normalize_allowed_domains(
            metadata_payload.get("allowed_domains"), adapter.default_domain_allowlist
        )
        allowed_paths = self._normalize_allowed_paths(metadata_payload.get("allowed_paths"))
        replay_mode = str(metadata_payload.get("replay_mode") or "redacted").strip().lower() or "redacted"
        session = DesktopSession.start(
            ttl_s=ttl_s,
            vm_context=self.vm_context,
            workflow_profile=adapter.workflow_profile,
            adapter_name=adapter.adapter_name,
            session_type=resolved_type,
            replay_mode=replay_mode,
            metadata=metadata_payload,
            allowed_domains=allowed_domains,
            allowed_paths=allowed_paths,
        )
        if not self.vm_context.isolated:
            session.magic_ready = False
            session.set_risk("high", score=70)
        self._session = session
        self._last_error = None
        self._last_refusal_reason = ""
        self._write_session_snapshot(session, metadata=metadata_payload)
        self._record_action("start_session", session=session, window=None, session_type=resolved_type)
        return self._session_payload(session=session, window=None, extra={"quality_bar": magic_quality_bar()})

    def pause_session(self, session_id: str, *, reason: str = "") -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        reason_text = str(reason or "").strip() or "Paused by desktop operator."
        self._set_session_state(session, "paused_for_approval", reason=reason_text, risk_level="high")
        self._record_action("pause_session", session=session, window=self._window_if_bound(session), reason=reason_text)
        return self._session_payload(session=session, window=self._window_if_bound(session), extra={"paused": True})

    def resume_session(self, session_id: str, *, approved: bool = False, reason: str = "") -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        if session.session_state not in {
            "paused_for_approval",
            "blocked_by_policy",
            "verification_failed",
            "needs_rebind",
        }:
            raise session_error(
                "Desktop session is not paused or blocked.",
                session_id=session_id,
                session_state=session.session_state,
            )
        if session.session_state in {"paused_for_approval", "blocked_by_policy"} and not approved:
            raise session_error(
                "Resuming this session requires explicit approval.",
                session_id=session_id,
                session_state=session.session_state,
                pending_approval_reason=session.pending_approval_reason or session.last_refusal_reason,
            )
        session.set_state("active", reason="")
        session.pending_approval_reason = ""
        session.last_refusal_reason = str(reason or "").strip()
        session.sensitive_mode = False
        session.secret_zone_hits = []
        session.set_risk("medium" if not session.magic_ready else "low")
        session.touch(ttl_s=self.session_ttl_s)
        self._record_action(
            "resume_session", session=session, window=self._window_if_bound(session), approved=bool(approved)
        )
        return self._session_payload(session=session, window=self._window_if_bound(session), extra={"resumed": True})

    def terminate_session(self, session_id: str, *, reason: str = "") -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        reason_text = str(reason or "").strip() or "Desktop session terminated."
        self._set_session_state(session, "terminated", reason=reason_text, risk_level="high")
        payload = self._session_payload(
            session=session,
            window=self._window_if_bound(session),
            extra={"terminated": True},
        )
        self._record_action(
            "terminate_session", session=session, window=self._window_if_bound(session), reason=reason_text
        )
        self._session = None
        self._last_refusal_reason = reason_text
        return payload

    def get_risk_state(self, session_id: str) -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        return {
            "service_id": DESKTOP_OPERATOR_SERVICE_ID,
            "version": DESKTOP_OPERATOR_VERSION,
            "session_id": session.session_id,
            "workflow_profile": session.workflow_profile,
            "vm_id": session.vm_id,
            "session_state": session.session_state,
            "risk_level": session.risk_level,
            "risk_score": int(session.risk_score),
            "retry_budget_remaining": int(session.retry_budget_remaining),
            "verify_failures": int(session.verify_failures),
            "low_confidence_events": int(session.low_confidence_events),
            "pending_approval_reason": session.pending_approval_reason,
            "refusal_reason": session.last_refusal_reason or self._last_refusal_reason,
            "magic_ready": bool(session.magic_ready),
        }

    def end_session(self, session_id: str) -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        payload = self._session_payload(session=session, window=self._window_if_bound(session), extra={"ended": True})
        self._record_action("end_session", session=session, window=self._window_if_bound(session))
        self._session = None
        self._last_refusal_reason = ""
        return payload

    def list_apps(
        self,
        *,
        title_contains: str = "",
        executable_contains: str = "",
        visible_only: bool = True,
        limit: int = 40,
    ) -> dict[str, Any]:
        windows = self.adapter.list_windows()
        title_q = str(title_contains or "").strip().lower()
        exe_q = str(executable_contains or "").strip().lower()
        out: list[dict[str, Any]] = []
        for window in windows:
            if visible_only and not window.visible:
                continue
            if title_q and title_q not in window.title.lower():
                continue
            if exe_q and exe_q not in window.executable_path.lower():
                continue
            adapter = resolve_adapter_for_window(window, allowlisted_profiles=self.allowlisted_profiles)
            if adapter is None:
                continue
            payload = window.to_dict()
            payload["workflow_profile"] = adapter.workflow_profile
            payload["adapter_name"] = adapter.adapter_name
            payload["display_name"] = adapter.display_name
            payload["stable_actions"] = list(adapter.stable_actions)
            payload["action_classes"] = dict(adapter.action_classes)
            out.append(payload)
            if len(out) >= max(1, int(limit)):
                break
        return {
            "apps": out,
            "count": len(out),
            "vm": self.vm_context.to_dict(),
            "allowlisted_profiles": sorted(self.allowlisted_profiles),
            "workflow_profiles": workflow_profile_payloads(),
            "quality_bar": magic_quality_bar(),
        }

    def list_windows(
        self,
        *,
        title_contains: str = "",
        executable_contains: str = "",
        visible_only: bool = True,
        limit: int = 40,
    ) -> dict[str, Any]:
        payload = self.list_apps(
            title_contains=title_contains,
            executable_contains=executable_contains,
            visible_only=visible_only,
            limit=limit,
        )
        payload["windows"] = list(payload.get("apps") or [])
        return payload

    def bind_app(
        self,
        session_id: str,
        *,
        window_handle: int | None = None,
        title_contains: str = "",
        executable_contains: str = "",
        move_to_primary: bool = False,
    ) -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        if session.session_state == "terminated":
            raise session_error("Desktop session has been terminated.", session_id=session_id)
        window = self._select_window(
            window_handle=window_handle,
            title_contains=title_contains,
            executable_contains=executable_contains,
        )
        adapter = self._resolve_allowlisted_adapter(window, preferred_profile=session.workflow_profile)
        if adapter.workflow_profile != session.workflow_profile:
            raise invalid_input(
                "Requested window does not match the active desktop workflow profile.",
                workflow_profile=session.workflow_profile,
                adapter_name=adapter.adapter_name,
                window=window.to_dict(),
            )
        if move_to_primary:
            self._require_isolated("Moving windows to the primary monitor")
            window = self.adapter.ensure_visible(window.handle, move_to_primary=True)
        session.bind_window(window)
        session.set_state("active")
        session.touch(ttl_s=self.session_ttl_s)
        self._write_session_snapshot(session)
        self._record_action("bind_app", session=session, window=window, adapter_name=adapter.adapter_name)
        return self._session_payload(session=session, window=window)

    def bind_window(
        self,
        *,
        window_handle: int | None = None,
        title_contains: str = "",
        executable_contains: str = "",
        move_to_primary: bool = False,
        session_ttl_s: int | None = None,
        workflow_profile: str = "",
    ) -> dict[str, Any]:
        window = self._select_window(
            window_handle=window_handle,
            title_contains=title_contains,
            executable_contains=executable_contains,
        )
        adapter = self._resolve_allowlisted_adapter(window, preferred_profile=workflow_profile)
        start = self.start_session(
            workflow_profile=adapter.workflow_profile,
            session_ttl_s=session_ttl_s,
        )
        session_id = str(((start.get("session") or {}).get("session_id")) or "")
        return self.bind_app(
            session_id,
            window_handle=window.handle,
            move_to_primary=move_to_primary,
        )

    def capture(self, session_id: str) -> dict[str, Any]:
        return self.capture_window(session_id)

    def capture_window(self, session_id: str) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        output_path = self._session_dir(session) / f"capture-{int(time.time() * 1000)}.png"
        capture = self.adapter.capture_window(window.handle, output_path)
        session.last_capture_path = capture.path
        session.last_capture_source = capture.source
        session.control_layer_used = "vision"
        session.touch(ttl_s=self.session_ttl_s)
        session.add_artifact(capture.path)
        capture_payload = capture.to_dict()
        capture_payload["bounds"] = window.bounds.to_dict()
        capture_payload["client_bounds"] = window.client_bounds.to_dict()
        self._record_action("capture", session=session, window=window, path=capture.path, source=capture.source)
        return self._session_payload(
            session=session,
            window=window,
            extra={
                "capture": capture_payload,
                "capture_source": capture.source,
            },
        )

    def ax_snapshot(self, session_id: str) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        payload = self.adapter.snapshot_accessibility(window.handle)
        ax_path = self._session_dir(session) / f"ax-{int(time.time() * 1000)}.json"
        self._write_json(ax_path, payload)
        session.touch(ttl_s=self.session_ttl_s)
        session.add_artifact(str(ax_path))
        self._record_action("ax_snapshot", session=session, window=window, available=bool(payload.get("available")))
        return self._session_payload(
            session=session, window=window, extra={"accessibility": payload, "artifact": str(ax_path)}
        )

    def read_state(self, session_id: str) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        capture = self.capture_window(session_id)
        accessibility = self.ax_snapshot(session_id)
        capture_path = str(((capture.get("capture") or {}).get("path")) or "")
        raw_ocr_text = ""
        if capture_path:
            texts = extract_text_from_images([capture_path])
            if texts:
                raw_ocr_text = str(texts[0] or "").strip()
        adapter = adapter_by_profile(session.workflow_profile)
        accessibility_payload = (
            accessibility.get("accessibility") if isinstance(accessibility.get("accessibility"), dict) else {}
        )
        profile_summary = adapter.summarize_state(accessibility_payload, raw_ocr_text) if adapter is not None else {}
        available = bool(accessibility_payload.get("available"))
        control_layer = "semantic" if available else ("vision" if raw_ocr_text else "unknown")
        target_confidence = 0.98 if available else (0.64 if raw_ocr_text else 0.0)
        secret_zone_hits = self._detect_secret_zone_hits(profile_summary, raw_ocr_text)
        capture_payload = capture.get("capture") if isinstance(capture.get("capture"), dict) else {}
        if secret_zone_hits and session.replay_mode == "redacted":
            capture_payload = self._redact_capture(session, capture_payload, reason="secret_zone")
        redacted_ocr = self._redact_text(raw_ocr_text, force=bool(secret_zone_hits or session.sensitive_mode))
        session.control_layer_used = control_layer
        session.last_target_confidence = target_confidence
        session.secret_zone_hits = secret_zone_hits
        session.sensitive_mode = bool(secret_zone_hits)
        if secret_zone_hits:
            self._pause_for_approval(
                session,
                reason="Sensitive screen detected; user takeover required.",
                approval_reason="secret_zone_detected",
            )
        state = {
            "session": session.to_dict(),
            "window": window.to_dict(),
            "vm": self.vm_context.to_dict(),
            "focus_handle": self.adapter.get_foreground_window(),
            "capture": capture_payload,
            "capture_source": capture.get("capture_source") or "",
            "accessibility": accessibility_payload,
            "ocr_text_summary": redacted_ocr[:4000],
            "workflow_profile": session.workflow_profile,
            "adapter_name": session.adapter_name,
            "control_layer_used": control_layer,
            "target_confidence": target_confidence,
            "verification_status": session.verification_status,
            "risk_level": session.risk_level,
            "session_state": session.session_state,
            "refusal_reason": session.last_refusal_reason or self._last_refusal_reason,
            "profile_state": profile_summary,
            "artifact_refs": list(session.artifact_refs),
            "secret_zone_detected": bool(secret_zone_hits),
            "secret_zone_hits": list(secret_zone_hits),
        }
        state_path = self._session_dir(session) / f"state-{int(time.time() * 1000)}.json"
        self._write_json(state_path, state)
        session.last_verified_state_path = str(state_path)
        session.add_artifact(str(state_path))
        self._record_action(
            "read_state",
            session=session,
            window=window,
            ocr_chars=len(redacted_ocr),
            control_layer=control_layer,
            secret_zone_detected=bool(secret_zone_hits),
        )
        return state

    def act(self, session_id: str, *, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        self._require_active_session(session)
        normalized = str(action or "").strip().lower()
        payload = dict(params or {})
        adapter = adapter_by_profile(session.workflow_profile)
        if adapter is None:
            raise invalid_input("Unknown workflow profile for session.", workflow_profile=session.workflow_profile)
        action_class = self._action_class(adapter, normalized)
        self._supervisor_preflight(
            session, window, adapter=adapter, action=normalized, payload=payload, action_class=action_class
        )
        if normalized in _GENERIC_ACTIONS:
            result = self._perform_generic_action(session, window, normalized, payload)
        elif normalized in adapter.stable_actions:
            if session.workflow_profile == "browser-session":
                result = self._perform_browser_action(session, window, normalized, payload)
            elif session.workflow_profile == "windows-file-dialog":
                result = self._perform_file_dialog_action(session, window, normalized, payload)
            elif session.workflow_profile == "capcut-editing":
                result = self._perform_capcut_action(session, window, normalized, payload)
            else:
                raise invalid_input(
                    "No action dispatcher is available for the active workflow profile.",
                    workflow_profile=session.workflow_profile,
                )
        else:
            raise invalid_input(
                "Action is not available for the active desktop workflow profile.",
                action=normalized,
                workflow_profile=session.workflow_profile,
                stable_actions=list(adapter.stable_actions),
            )
        self._post_action_supervision(session, window, action=normalized, result=result)
        return result

    def verify(
        self,
        session_id: str,
        *,
        mode: str = "ready",
        title_contains: str = "",
        ocr_contains: str = "",
        artifact_path: str = "",
        capture_source: str = "",
    ) -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        state = self.read_state(session_id) if session.handle else self._session_payload(session=session, window=None)
        normalized_mode = str(mode or "ready").strip().lower()
        verification_ok = False
        reason = ""
        title = str(((state.get("window") or {}).get("title")) or "")
        ocr_text = str(state.get("ocr_text_summary") or "")
        actual_capture_source = str(state.get("capture_source") or "")
        if normalized_mode in {"ready", "profile_ready"}:
            verification_ok = bool(
                ((state.get("profile_state") or {}).get("ready"))
                if isinstance(state.get("profile_state"), dict)
                else False
            )
            if not verification_ok:
                reason = "Profile readiness indicators were not found."
        elif normalized_mode == "title_contains":
            wanted = str(title_contains or "").strip().lower()
            verification_ok = bool(wanted) and wanted in title.lower()
            if not verification_ok:
                reason = f"Window title did not contain '{wanted}'."
        elif normalized_mode == "ocr_contains":
            wanted = str(ocr_contains or "").strip().lower()
            verification_ok = bool(wanted) and wanted in ocr_text.lower()
            if not verification_ok:
                reason = f"OCR text did not contain '{wanted}'."
        elif normalized_mode == "artifact_exists":
            path = Path(str(artifact_path or "").strip())
            verification_ok = bool(str(path)) and path.exists()
            if not verification_ok:
                reason = f"Artifact does not exist: {path}"
        elif normalized_mode == "capture_source":
            wanted = str(capture_source or "").strip().lower()
            verification_ok = bool(wanted) and actual_capture_source.lower() == wanted
            if not verification_ok:
                reason = f"Capture source was '{actual_capture_source}', not '{wanted}'."
        else:
            raise invalid_input("Unsupported desktop verification mode.", mode=normalized_mode)

        self._register_verification_result(session, ok=bool(verification_ok), reason=reason)
        verification_payload = {
            "session_id": session.session_id,
            "workflow_profile": session.workflow_profile,
            "mode": normalized_mode,
            "ok": bool(verification_ok),
            "verification_status": session.verification_status,
            "reason": reason,
            "timestamp_epoch_s": time.time(),
            "state": state,
        }
        verification_path = self._session_dir(session) / f"verification-{int(time.time() * 1000)}.json"
        self._write_json(verification_path, verification_payload)
        session.last_verified_state_path = str(verification_path)
        session.add_artifact(str(verification_path))
        self._record_action(
            "verify",
            session=session,
            window=self._window_if_bound(session),
            mode=normalized_mode,
            ok=bool(verification_ok),
        )
        return self._session_payload(
            session=session,
            window=self._window_if_bound(session),
            extra={
                "ok": bool(verification_ok),
                "verification_status": session.verification_status,
                "verification_mode": normalized_mode,
                "verification_reason": reason,
                "artifact": str(verification_path),
                "state": state,
            },
        )

    def recover(self, session_id: str, *, strategy: str = "ensure_visible") -> dict[str, Any]:
        session = self._require_session_shell(session_id)
        normalized = str(strategy or "ensure_visible").strip().lower()
        if normalized == "ensure_visible":
            if not session.handle:
                raise session_error("No bound app is available to recover.", session_id=session_id)
            payload = self.ensure_visible(session_id)
        elif normalized == "refresh_state":
            if not session.handle:
                raise session_error("No bound app is available to refresh.", session_id=session_id)
            payload = self.read_state(session_id)
        elif normalized == "rebind_foreground":
            foreground = self.adapter.get_foreground_window()
            if foreground is None:
                raise not_found("No foreground window is available for rebind.")
            payload = self.bind_app(session_id, window_handle=int(foreground))
        else:
            raise invalid_input("Unsupported desktop recovery strategy.", strategy=normalized)
        session.verify_failures = 0
        session.low_confidence_events = 0
        if session.session_state != "terminated":
            session.set_state("active", reason="")
            session.pending_approval_reason = ""
        self._record_action(
            "recover", session=self._session, window=self._window_if_bound(self._session), strategy=normalized
        )
        return payload

    def click(
        self,
        session_id: str,
        *,
        x: int | None = None,
        y: int | None = None,
        selector: dict[str, Any] | None = None,
        button: str = "left",
        double: bool = False,
    ) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        self._require_active_session(session)
        raw_selector = selector if isinstance(selector, dict) else None
        if raw_selector is None:
            self._require_isolated("Pointer-based clicking")
        target_x, target_y, target_confidence, control_layer = self._resolve_click_target(
            window,
            workflow_profile=session.workflow_profile,
            selector=raw_selector,
            x=x,
            y=y,
        )
        self.adapter.click(window.handle, target_x, target_y, button=button, double=double)
        session.touch(ttl_s=self.session_ttl_s)
        session.control_layer_used = control_layer
        session.last_target_confidence = target_confidence
        session.last_refusal_reason = ""
        self._record_action(
            "click",
            session=session,
            window=window,
            x=target_x,
            y=target_y,
            button=button,
            double=bool(double),
            control_layer=control_layer,
            target_confidence=target_confidence,
        )
        self._record_low_confidence(session, target_confidence=target_confidence, action="click")
        return self._session_payload(
            session=session,
            window=window,
            extra={
                "ok": True,
                "x": target_x,
                "y": target_y,
                "control_layer_used": control_layer,
                "target_confidence": target_confidence,
            },
        )

    def type_text(self, session_id: str, *, text: str) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        self._require_active_session(session)
        self._require_isolated("Typing into desktop apps")
        typed = str(text or "")
        if self._looks_like_secret(typed):
            self._pause_for_approval(
                session,
                reason="Secret-looking input requires user takeover.",
                approval_reason="secret_input_blocked",
            )
            raise session_error(
                "Secret-looking input cannot be typed by the model.",
                session_id=session.session_id,
                session_state=session.session_state,
            )
        self.adapter.type_text(window.handle, typed)
        session.touch(ttl_s=self.session_ttl_s)
        session.control_layer_used = "semantic"
        session.last_refusal_reason = ""
        self._record_action(
            "type", session=session, window=window, text=typed, length=len(typed), control_layer="semantic"
        )
        return self._session_payload(
            session=session, window=window, extra={"ok": True, "typed": self._redact_text(typed)}
        )

    def press_keys(self, session_id: str, *, keys: list[str]) -> dict[str, Any]:
        normalized = [str(k or "").strip().lower() for k in (keys or []) if str(k or "").strip()]
        if not normalized:
            raise invalid_input("At least one key is required.")
        blocked = [k for k in normalized if k not in _ALLOWED_KEYS]
        if blocked:
            raise invalid_input("Desktop Magic blocks non-approved key chords.", blocked_keys=blocked)
        session, window = self._require_bound_session(session_id)
        self._require_active_session(session)
        self._require_isolated("Sending key input")
        self.adapter.press_keys(window.handle, normalized)
        session.touch(ttl_s=self.session_ttl_s)
        session.control_layer_used = "semantic"
        session.last_refusal_reason = ""
        self._record_action("press_keys", session=session, window=window, keys=normalized, control_layer="semantic")
        return self._session_payload(session=session, window=window, extra={"ok": True, "keys": normalized})

    def drag(
        self,
        session_id: str,
        *,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
    ) -> dict[str, Any]:
        session, window = self._require_bound_session(session_id)
        self._require_active_session(session)
        self._require_isolated("Dragging inside desktop apps")
        self._ensure_point_in_client(window, int(start_x), int(start_y))
        self._ensure_point_in_client(window, int(end_x), int(end_y))
        self.adapter.drag(window.handle, int(start_x), int(start_y), int(end_x), int(end_y))
        session.touch(ttl_s=self.session_ttl_s)
        session.control_layer_used = "pointer"
        session.last_refusal_reason = ""
        self._record_action(
            "drag",
            session=session,
            window=window,
            start={"x": int(start_x), "y": int(start_y)},
            end={"x": int(end_x), "y": int(end_y)},
            control_layer="pointer",
        )
        self._record_low_confidence(session, target_confidence=0.52, action="drag")
        return self._session_payload(
            session=session, window=window, extra={"ok": True, "control_layer_used": "pointer"}
        )

    def ensure_visible(self, session_id: str, *, move_to_primary: bool = False) -> dict[str, Any]:
        session, _window = self._require_bound_session(session_id)
        self._require_active_session(session)
        self._require_isolated("Changing desktop window focus")
        window = self.adapter.ensure_visible(session.handle, move_to_primary=bool(move_to_primary))
        session.bind_window(window)
        session.touch(ttl_s=self.session_ttl_s)
        session.control_layer_used = "semantic"
        session.last_refusal_reason = ""
        self._record_action("ensure_visible", session=session, window=window, move_to_primary=bool(move_to_primary))
        return self._session_payload(session=session, window=window, extra={"ok": True})

    def status_payload(self) -> dict[str, Any]:
        session = self._session
        active = None
        if session is not None:
            try:
                active = self._session_payload(session=session, window=self._window_if_bound(session))
            except Exception as exc:  # noqa: BLE001
                self._last_error = {"type": type(exc).__name__, "message": str(exc)}
                self._last_refusal_reason = str(exc)
                active = {"session": session.to_dict(), "window": None, "error": self._last_error}
        return {
            "service_id": DESKTOP_OPERATOR_SERVICE_ID,
            "version": DESKTOP_OPERATOR_VERSION,
            "running": True,
            "vm": self.vm_context.to_dict(),
            "workflow_profiles": workflow_profile_payloads(),
            "allowlisted_profiles": sorted(self.allowlisted_profiles),
            "quality_bar": magic_quality_bar(),
            "security_posture": {
                "background_first": True,
                "replay_mode_default": "redacted",
                "requires_isolated_vm": True,
                "balanced_approvals": True,
            },
            "active_session": active,
            "last_error": self._last_error,
            "refusal_reason": self._last_refusal_reason,
        }
