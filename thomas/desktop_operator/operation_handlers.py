"""
Desktop operator private operation handlers and supervision utilities.

This module contains the private helper methods for DesktopOperatorRuntime,
including action dispatchers, session validation, window management, and
security supervision logic.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .contracts import (
    DESKTOP_OPERATOR_SERVICE_ID,
    DESKTOP_OPERATOR_VERSION,
    DesktopSession,
    Rect,
    WindowInfo,
    invalid_input,
    not_found,
    session_error,
)

# Pattern constants imported from main module - these should match runtime.py
_ALLOWED_KEYS = {"enter", "escape", "esc", "tab", "up", "down", "left", "right"}
_ACTIVE_SESSION_STATES = {"active"}
_MAX_VERIFY_FAILURES_BEFORE_TERMINATE = 3
_LOW_CONFIDENCE_THRESHOLD = 0.70
_LOW_CONFIDENCE_LIMIT = 2


class OperationHandlersMixin:
    """Private operation and supervision helpers for DesktopOperatorRuntime."""

    def _perform_generic_action(
        self, session: DesktopSession, window: WindowInfo, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "click":
            return self.click(
                session.session_id,
                x=int(payload["x"]) if payload.get("x") is not None else None,
                y=int(payload["y"]) if payload.get("y") is not None else None,
                selector=payload.get("selector") if isinstance(payload.get("selector"), dict) else None,
                button=str(payload.get("button") or "left"),
                double=bool(payload.get("double", False)),
            )
        if action == "type":
            return self.type_text(session.session_id, text=str(payload.get("text") or ""))
        if action == "press_keys":
            return self.press_keys(session.session_id, keys=[str(x) for x in (payload.get("keys") or [])])
        if action == "drag":
            return self.drag(
                session.session_id,
                start_x=int(payload.get("start_x") or 0),
                start_y=int(payload.get("start_y") or 0),
                end_x=int(payload.get("end_x") or 0),
                end_y=int(payload.get("end_y") or 0),
            )
        if action == "ensure_visible":
            return self.ensure_visible(session.session_id, move_to_primary=bool(payload.get("move_to_primary", False)))
        raise invalid_input("Unsupported generic desktop action.", action=action)

    def _perform_browser_action(
        self, session: DesktopSession, window: WindowInfo, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "focus_address_bar":
            return self.click(session.session_id, selector={"alias": "address_bar"})
        if action == "open_url":
            url = str(payload.get("url") or "").strip()
            if not url:
                raise invalid_input("browser-session.open_url requires a url.")
            self.click(session.session_id, selector={"alias": "address_bar"})
            self.type_text(session.session_id, text=url)
            result = self.press_keys(session.session_id, keys=["enter"])
            result["navigation_target"] = url
            result["control_layer_used"] = "semantic"
            return result
        if action == "refresh_page":
            return self.click(session.session_id, selector={"alias": "reload_button"})
        raise invalid_input("Unsupported browser-session action.", action=action)

    def _perform_file_dialog_action(
        self, session: DesktopSession, window: WindowInfo, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "set_file_path":
            path = str(payload.get("path") or "").strip()
            if not path:
                raise invalid_input("windows-file-dialog.set_file_path requires a path.")
            self._require_allowed_path(session, path)
            self.click(session.session_id, selector={"alias": "file_name_input"})
            result = self.type_text(session.session_id, text=path)
            result["selected_path"] = path
            return result
        if action == "confirm_open":
            return self.click(session.session_id, selector={"alias": "open_button"})
        if action == "confirm_save":
            return self.click(session.session_id, selector={"alias": "save_button"})
        raise invalid_input("Unsupported windows-file-dialog action.", action=action)

    def _perform_capcut_action(
        self, session: DesktopSession, window: WindowInfo, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "new_project":
            return self.click(session.session_id, selector={"alias": "new_project"})
        if action == "import_assets":
            paths = [str(x) for x in (payload.get("paths") or []) if str(x or "").strip()]
            for path in paths:
                self._require_allowed_path(session, path)
            result = self.click(session.session_id, selector={"alias": "import_button"})
            result["next_expected_workflow_profile"] = "windows-file-dialog"
            result["pending_asset_paths"] = paths
            return result
        if action == "read_timeline_state":
            return self.read_state(session.session_id)
        if action == "start_export":
            result = self.click(session.session_id, selector={"alias": "export_button"})
            result["next_expected_workflow_profile"] = "windows-file-dialog"
            return result
        raise invalid_input("Unsupported capcut-editing action.", action=action)

    def _select_window(
        self,
        *,
        window_handle: int | None,
        title_contains: str,
        executable_contains: str,
    ) -> WindowInfo:
        if window_handle is not None:
            window = self.adapter.get_window(int(window_handle))
            if window is None:
                raise not_found("Requested window handle was not found.", window_handle=int(window_handle))
            return window
        matches = (
            self.list_apps(
                title_contains=title_contains,
                executable_contains=executable_contains,
                visible_only=True,
                limit=10,
            ).get("apps")
            or []
        )
        if not matches:
            raise not_found(
                "No allowlisted app matched the provided selector.",
                title_contains=title_contains,
                executable_contains=executable_contains,
            )
        return self.adapter.get_window(int(matches[0]["handle"])) or self._fallback_window(matches[0])

    def _fallback_window(self, payload: dict[str, Any]) -> WindowInfo:
        bounds = payload.get("bounds") or {}
        client = payload.get("client_bounds") or bounds
        return WindowInfo(
            handle=int(payload.get("handle") or 0),
            title=str(payload.get("title") or ""),
            executable_path=str(payload.get("executable_path") or ""),
            process_id=int(payload.get("process_id") or 0),
            visible=bool(payload.get("visible", True)),
            minimized=bool(payload.get("minimized", False)),
            monitor_id=str(payload.get("monitor_id") or ""),
            bounds=self._rect_from_payload(bounds),
            client_bounds=self._rect_from_payload(client),
            class_name=str(payload.get("class_name") or ""),
        )

    def _rect_from_payload(self, payload: dict[str, Any]) -> Rect:
        return Rect(
            int(payload.get("left") or 0),
            int(payload.get("top") or 0),
            int(payload.get("right") or 0),
            int(payload.get("bottom") or 0),
        )

    def _require_session_shell(self, session_id: str) -> DesktopSession:
        session = self._session
        if session is None or session.session_id != str(session_id or "").strip():
            raise session_error("Desktop session is not active.", session_id=session_id)
        if session.is_expired():
            self._session = None
            raise session_error("Desktop session expired.", session_id=session_id)
        session.touch(ttl_s=self.session_ttl_s)
        return session

    def _require_active_session(self, session: DesktopSession) -> None:
        if session.session_state in _ACTIVE_SESSION_STATES:
            return
        raise session_error(
            "Desktop session is not active for input actions.",
            session_id=session.session_id,
            session_state=session.session_state,
            refusal_reason=session.last_refusal_reason or self._last_refusal_reason,
        )

    def _require_bound_session(
        self, session_id: str, *, require_focus: bool = False
    ) -> tuple[DesktopSession, WindowInfo]:
        session = self._require_session_shell(session_id)
        if not session.handle:
            raise session_error("Desktop session has no bound app.", session_id=session_id)
        window = self.adapter.get_window(session.handle)
        if window is None:
            self._trip_circuit(session, state="needs_rebind", reason="Bound app no longer exists.")
            raise session_error("Bound app no longer exists.", session_id=session_id, handle=session.handle)
        if session.process_id and int(window.process_id) != int(session.process_id):
            self._trip_circuit(session, state="needs_rebind", reason="Bound app process changed; rebind before acting.")
            raise session_error(
                "Bound app process changed; rebind before acting.",
                session_id=session_id,
                expected=session.process_id,
                actual=window.process_id,
            )
        if require_focus and not window.visible:
            raise session_error("Bound app window is not visible.", session_id=session_id, handle=session.handle)
        return session, window

    def _window_if_bound(self, session: DesktopSession | None) -> WindowInfo | None:
        if session is None or not session.handle:
            return None
        return self.adapter.get_window(session.handle)

    def _resolve_allowlisted_adapter(self, window: WindowInfo, *, preferred_profile: str = ""):
        from .app_adapters import adapter_by_profile, resolve_adapter_for_window

        if preferred_profile:
            adapter = adapter_by_profile(preferred_profile)
            if adapter is not None:
                return adapter
        return resolve_adapter_for_window(window)

    def _resolve_click_target(
        self,
        window: WindowInfo,
        *,
        x: int | None = None,
        y: int | None = None,
        selector: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        if x is not None and y is not None:
            return (x, y)
        if selector is None:
            return (window.client_bounds.left + 10, window.client_bounds.top + 10)
        nodes = self.adapter.ax_query(window, selector)
        if not nodes:
            raise not_found("Accessibility selector did not match any nodes.", selector=selector)
        matched = self._match_accessibility_node(nodes, selector)
        if matched is None:
            raise not_found("Accessibility selector matched nodes but none satisfied the query.", selector=selector)
        bounds = matched.get("bounds") or {}
        center_x = int((int(bounds.get("left") or 0) + int(bounds.get("right") or 0)) / 2)
        center_y = int((int(bounds.get("top") or 0) + int(bounds.get("bottom") or 0)) / 2)
        return (center_x, center_y)

    def _match_accessibility_node(self, nodes: list[Any], selector: dict[str, Any]) -> dict[str, Any] | None:
        for node in nodes:
            if selector.get("role") and str(node.get("role") or "") != str(selector["role"]):
                continue
            if selector.get("name") and str(selector["name"]).lower() not in str(node.get("name") or "").lower():
                continue
            if selector.get("alias") and str(node.get("name") or "") != str(selector["alias"]):
                continue
            return node
        return None

    def _ensure_point_in_client(self, window: WindowInfo, x: int, y: int) -> None:
        if not (
            window.client_bounds.left <= x <= window.client_bounds.right
            and window.client_bounds.top <= y <= window.client_bounds.bottom
        ):
            raise invalid_input(
                "Click coordinates are outside the window client area.",
                x=x,
                y=y,
                window_bounds=window.client_bounds.to_dict(),
            )

    def _require_isolated(self, action: str) -> None:
        # `DesktopVmContext.isolated` is the canonical field; the old
        # `is_isolated` accessor was removed during the contracts refactor.
        # This call site still referenced the old name, raising
        # AttributeError instead of the expected "requires an isolated
        # desktop operator vm/session" message that the tests look for.
        if not getattr(self.vm_context, "isolated", False):
            raise session_error(
                "Action requires an isolated desktop operator vm/session.",
                action=action,
                isolation_required=True,
            )

    def _normalize_allowed_domains(self, raw: Any, defaults: tuple[str, ...]) -> list[str]:
        if isinstance(raw, list | tuple):
            return [str(x or "").strip().lower() for x in raw if str(x or "").strip()]
        if isinstance(raw, str):
            return [raw.strip().lower()] if raw.strip() else list(defaults)
        return list(defaults)

    def _normalize_allowed_paths(self, raw: Any) -> list[str]:
        if isinstance(raw, list | tuple):
            return [str(x or "").strip() for x in raw if str(x or "").strip()]
        if isinstance(raw, str):
            return [raw.strip()] if raw.strip() else []
        return []

    def _action_class(self, adapter, action: str) -> str:
        # ACTION_CLASSES is the tuple of valid class names; ACTION_CLASS_MAP
        # is the (action → class) mapping. The historic call site read
        # `ACTION_CLASSES.get(action)` — that confused the tuple of names
        # with the mapping that should have been used.
        from .contracts import ACTION_CLASS_MAP

        return ACTION_CLASS_MAP.get(action) or "generic"

    def _supervisor_preflight(
        self,
        session: DesktopSession,
        window: WindowInfo,
        *,
        action: str,
        payload: dict[str, Any],
        # runtime.py passes adapter + action_class — accept them so the
        # signature matches the caller. Both are recomputed if absent.
        adapter: Any = None,
        action_class: str | None = None,
    ) -> None:
        if action_class is None:
            action_class = self._action_class(adapter or self.adapter, action)

        if action_class == "sensitive":
            raise session_error(
                "Action requires human approval before execution.",
                action=action,
                action_class=action_class,
            )

        if session.risk_level in ("red", "circuit_broken"):
            raise session_error(
                "Desktop session is circuit-broken; reset required.",
                session_id=session.session_id,
                risk_level=session.risk_level,
            )

        if action_class == "navigation":
            url = payload.get("url") or window.title
            self._require_allowed_domain(session, url)

        if action_class in ("file_dialog", "filesystem"):
            paths = payload.get("path") or payload.get("paths") or []
            if not isinstance(paths, list | tuple):
                paths = [paths] if paths else []
            for path in paths:
                self._require_allowed_path(session, path)

        if action in ("drag",):
            self._require_isolated(action)

    def _post_action_supervision(
        self, session: DesktopSession, window: WindowInfo, *, action: str, result: dict[str, Any]
    ) -> None:
        if not result.get("ok", False):
            return
        from .contracts import ACTION_CLASS_MAP

        action_class = ACTION_CLASS_MAP.get(action) or "generic"

        if action_class == "capture":
            self._detect_secret_zone_hits(result.get("profile_summary") or {}, result.get("ocr_text") or "")

    def _require_allowed_domain(self, session: DesktopSession, url: str) -> None:
        parsed = urlparse(url)
        domain = parsed.hostname or ""

        allowed = session.allowed_domains or []
        if allowed and not any(domain.endswith(d.lstrip(".")) for d in allowed):
            raise session_error(
                "URL domain not in allowlist.",
                domain=domain,
                allowlist=allowed,
                session_id=session.session_id,
            )

    def _require_allowed_path(self, session: DesktopSession, path: str) -> None:
        allowed = session.allowed_paths or []
        if not allowed:
            return
        path_obj = Path(path)
        if not any(path_obj.is_relative_to(Path(p)) for p in allowed if p):
            raise session_error(
                "File path not in allowlist.",
                path=path,
                allowlist=allowed,
                session_id=session.session_id,
            )

    def _detect_secret_zone_hits(self, profile_summary: dict[str, Any], raw_ocr_text: str) -> list[str]:
        labels = profile_summary.get("labels") or []
        hits = [str(l).lower() for l in labels]
        return hits

    def _looks_like_secret(self, text: str) -> bool:
        from .contracts import _HIGH_RISK_TEXT_RE, _SECRET_VALUE_RE

        if _SECRET_VALUE_RE.search(text):
            return True
        if _HIGH_RISK_TEXT_RE.search(text):
            return True
        return False

    def _redact_text(self, text: str, *, force: bool = False) -> str:
        from .contracts import _SECRET_VALUE_RE

        if not force and not self._looks_like_secret(text):
            return text
        return _SECRET_VALUE_RE.sub("[REDACTED]", text)

    def _redact_capture(
        self, session: DesktopSession, capture_payload: dict[str, Any], *, reason: str
    ) -> dict[str, Any]:
        if not capture_payload.get("ok", False):
            return capture_payload
        payload = dict(capture_payload)
        payload["redacted_reason"] = reason
        payload["image_data"] = "[REDACTED IMAGE]"
        payload["image_path"] = None
        payload["ocr_text"] = self._redact_text(payload.get("ocr_text") or "", force=True)
        if isinstance(payload.get("profile_summary"), dict):
            profile = dict(payload["profile_summary"])
            profile["labels"] = []
            payload["profile_summary"] = profile
        return payload

    def _register_verification_result(self, session: DesktopSession, *, ok: bool, reason: str) -> None:
        if ok:
            session.verification_status = "verified"
            session.last_verify_ok = True
            session.verify_failure_count = 0
            self._last_refusal_reason = ""
        else:
            session.verify_failure_count += 1
            if session.verify_failure_count >= _MAX_VERIFY_FAILURES_BEFORE_TERMINATE:
                self._trip_circuit(
                    session,
                    state="verify_failed",
                    reason=f"Verification failed {session.verify_failure_count} times.",
                )
            self._last_refusal_reason = reason

    def _record_low_confidence(self, session: DesktopSession, *, target_confidence: float, action: str) -> None:
        session.low_confidence_count = (session.low_confidence_count or 0) + 1
        self._last_refusal_reason = f"Low confidence ({target_confidence:.2%}) for action: {action}"
        if session.low_confidence_count >= _LOW_CONFIDENCE_LIMIT:
            self._trip_circuit(
                session,
                state="low_confidence",
                reason=f"Low confidence recorded {session.low_confidence_count} times.",
            )

    def _pause_for_approval(self, session: DesktopSession, *, reason: str, approval_reason: str) -> None:
        self._set_session_state(session, "paused_for_approval", reason=reason, risk_level="yellow")
        self._last_refusal_reason = approval_reason

    def _block_by_policy(self, session: DesktopSession, *, reason: str) -> None:
        self._set_session_state(session, "blocked_by_policy", reason=reason, risk_level="red")

    def _trip_circuit(self, session: DesktopSession, *, state: str, reason: str) -> None:
        self._set_session_state(session, state, reason=reason, risk_level="red")
        self._last_refusal_reason = reason

    def _set_session_state(self, session: DesktopSession, state: str, *, reason: str, risk_level: str = "") -> None:
        session.session_state = state
        if risk_level:
            session.risk_level = risk_level
        self._record_action("_set_session_state", session=session, window=None, state=state, reason=reason)

    def _session_dir(self, session: DesktopSession) -> Path:
        return self.artifacts_dir / str(session.session_id)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

    def _append_jsonl(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            json.dump(payload, f, default=str)
            f.write("\n")

    def _write_session_snapshot(self, session: DesktopSession, *, metadata: dict[str, Any] | None = None) -> None:
        snapshot = session.to_dict()
        if metadata:
            snapshot.update(metadata)
        self._write_json(self._session_dir(session) / "snapshot.json", snapshot)

    def _sanitize_for_log(self, value: Any) -> Any:
        if isinstance(value, str):
            if self._looks_like_secret(value):
                return "[REDACTED]"
            return value
        if isinstance(value, dict):
            return {k: self._sanitize_for_log(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self._sanitize_for_log(v) for v in value]
        return value

    def _record_action(
        self,
        action: str,
        *,
        session: DesktopSession | None = None,
        window: WindowInfo | None = None,
        **kwargs,
    ) -> None:
        if session is None:
            return
        payload = {
            "timestamp": int(time.time() * 1000),
            "action": action,
            "session_id": session.session_id,
            "window_handle": window.handle if window else None,
            "params": self._sanitize_for_log(kwargs),
        }
        try:
            self._write_json(self._session_dir(session) / "last-action.json", payload)
            self._append_jsonl(self._session_dir(session) / "steps.jsonl", payload)
            self._write_session_snapshot(session)
        except Exception:
            pass

    def _session_payload(
        self,
        *,
        session: DesktopSession,
        window: WindowInfo | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .app_adapters import magic_quality_bar

        payload = {
            "service_id": DESKTOP_OPERATOR_SERVICE_ID,
            "version": DESKTOP_OPERATOR_VERSION,
            "session": session.to_dict(),
            "vm": self.vm_context.to_dict(),
            "workflow_profile": session.workflow_profile,
            "adapter_name": session.adapter_name,
            "session_state": session.session_state,
            "risk_level": session.risk_level,
            "target_confidence": float(session.last_target_confidence),
            "verification_status": session.verification_status,
            "refusal_reason": session.last_refusal_reason or self._last_refusal_reason,
            "artifact_refs": list(session.artifact_refs),
            "quality_bar": magic_quality_bar(),
            "window": window.to_dict() if window is not None else None,
        }
        if extra:
            payload.update(extra)
        return payload
