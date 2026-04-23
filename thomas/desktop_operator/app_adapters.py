from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import WindowInfo


@dataclass(frozen=True)
class DesktopAppAdapter:
    adapter_name: str
    workflow_profile: str
    display_name: str
    executable_contains: tuple[str, ...] = ()
    title_contains: tuple[str, ...] = ()
    class_names: tuple[str, ...] = ()
    selector_aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    readiness_terms: tuple[str, ...] = ()
    stable_actions: tuple[str, ...] = ()
    verification_modes: tuple[str, ...] = ()
    recovery_actions: tuple[str, ...] = ()
    action_classes: dict[str, str] = field(default_factory=dict)
    default_domain_allowlist: tuple[str, ...] = ()
    secret_zone_terms: tuple[str, ...] = ()
    approval_terms: tuple[str, ...] = ()

    def matches(self, window: WindowInfo) -> bool:
        exe = (window.executable_path or "").lower()
        title = (window.title or "").lower()
        class_name = (window.class_name or "").lower()
        if self.executable_contains and any(term in exe for term in self.executable_contains):
            return True
        if self.title_contains and any(term in title for term in self.title_contains):
            return True
        if self.class_names and class_name in self.class_names:
            return True
        return False

    def normalize_selector(self, selector: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(selector, dict):
            return selector
        alias = str(selector.get("alias") or "").strip().lower()
        if alias and alias in self.selector_aliases:
            merged = dict(self.selector_aliases[alias])
            for key, value in selector.items():
                if key != "alias" and value not in (None, ""):
                    merged[key] = value
            return merged
        return selector

    def summarize_state(self, accessibility: dict[str, Any] | None, ocr_text: str) -> dict[str, Any]:
        nodes = accessibility.get("nodes") if isinstance(accessibility, dict) else []
        names = []
        for node in nodes if isinstance(nodes, list) else []:
            if isinstance(node, dict):
                text = str(node.get("name") or "").strip()
                if text:
                    names.append(text)
        haystack = "\n".join(names + [str(ocr_text or "")]).lower()
        ready = [term for term in self.readiness_terms if term in haystack]
        secret_hits = [term for term in self.secret_zone_terms if term in haystack]
        return {
            "workflow_profile": self.workflow_profile,
            "adapter_name": self.adapter_name,
            "display_name": self.display_name,
            "stable_actions": list(self.stable_actions),
            "verification_modes": list(self.verification_modes),
            "recovery_actions": list(self.recovery_actions),
            "action_classes": dict(self.action_classes),
            "ready_indicators": ready,
            "ready": bool(ready),
            "secret_zone_hits": secret_hits,
            "secret_zone_detected": bool(secret_hits),
        }


_BROWSER = DesktopAppAdapter(
    adapter_name="browser",
    workflow_profile="browser-session",
    display_name="Browser session",
    executable_contains=("chrome", "msedge", "firefox", "brave"),
    selector_aliases={
        "address_bar": {"role": "edit"},
        "reload_button": {"name": "reload", "role": "button"},
        "page_view": {"role": "document"},
    },
    readiness_terms=("reload", "address", "search", "tab"),
    stable_actions=("focus_address_bar", "open_url", "refresh_page"),
    verification_modes=("ready", "title_contains", "ocr_contains", "capture_source"),
    recovery_actions=("ensure_visible", "refresh_state", "rebind_foreground"),
    action_classes={
        "focus_address_bar": "safe",
        "open_url": "navigation",
        "refresh_page": "safe",
    },
    default_domain_allowlist=("thomas.ai", "thomas.dev", "localhost", "127.0.0.1"),
    secret_zone_terms=(
        "password",
        "passkey",
        "verification code",
        "security code",
        "2fa",
        "mfa",
        "one-time code",
        "authenticator",
        "sign in",
        "log in",
    ),
    approval_terms=("billing", "payment", "checkout", "publish", "share", "account settings", "security settings"),
)

_CAPCUT = DesktopAppAdapter(
    adapter_name="capcut",
    workflow_profile="capcut-editing",
    display_name="CapCut editing",
    executable_contains=("capcut",),
    title_contains=("capcut",),
    selector_aliases={
        "new_project": {"name": "new project", "role": "button"},
        "import_button": {"name": "import", "role": "button"},
        "export_button": {"name": "export", "role": "button"},
        "media_bin": {"name": "media", "role": "pane"},
        "timeline": {"name": "timeline", "role": "pane"},
    },
    readiness_terms=("new project", "import", "export", "timeline"),
    stable_actions=("new_project", "import_assets", "read_timeline_state", "start_export"),
    verification_modes=("ready", "title_contains", "ocr_contains", "artifact_exists"),
    recovery_actions=("ensure_visible", "refresh_state", "rebind_foreground"),
    action_classes={
        "new_project": "bounded",
        "import_assets": "bounded",
        "read_timeline_state": "safe",
        "start_export": "bounded",
    },
    approval_terms=("publish", "share", "delete", "settings", "security"),
)

_FILE_DIALOG = DesktopAppAdapter(
    adapter_name="windows_file_dialog",
    workflow_profile="windows-file-dialog",
    display_name="Windows file dialog",
    title_contains=("open", "save as", "save", "import", "export"),
    class_names=("#32770",),
    selector_aliases={
        "file_name_input": {"automation_id": "1148", "role": "edit"},
        "open_button": {"name": "open", "role": "button"},
        "save_button": {"name": "save", "role": "button"},
        "cancel_button": {"name": "cancel", "role": "button"},
    },
    readiness_terms=("file name", "open", "save", "cancel"),
    stable_actions=("set_file_path", "confirm_open", "confirm_save"),
    verification_modes=("ready", "ocr_contains", "artifact_exists"),
    recovery_actions=("ensure_visible", "refresh_state", "rebind_foreground"),
    action_classes={
        "set_file_path": "bounded",
        "confirm_open": "bounded",
        "confirm_save": "bounded",
    },
)

_ADAPTERS = (_BROWSER, _FILE_DIALOG, _CAPCUT)

_MAGIC_QUALITY_BAR = {
    "criteria": [
        "setup_friction",
        "state_recognition_accuracy",
        "action_reliability",
        "recovery_quality",
        "verification_quality",
        "end_to_end_latency",
        "user_interruption_safety",
    ],
    "launch_rule": "A workflow is magic-ready only after repeated clean-session success with explicit verification.",
}


def magic_quality_bar() -> dict[str, Any]:
    return dict(_MAGIC_QUALITY_BAR)


def allowed_workflow_profiles() -> list[str]:
    return [adapter.workflow_profile for adapter in _ADAPTERS]


def workflow_profile_payloads() -> list[dict[str, Any]]:
    return [
        {
            "workflow_profile": adapter.workflow_profile,
            "adapter_name": adapter.adapter_name,
            "display_name": adapter.display_name,
            "stable_actions": list(adapter.stable_actions),
            "verification_modes": list(adapter.verification_modes),
            "recovery_actions": list(adapter.recovery_actions),
            "action_classes": dict(adapter.action_classes),
            "default_domain_allowlist": list(adapter.default_domain_allowlist),
            "secret_zone_terms": list(adapter.secret_zone_terms),
        }
        for adapter in _ADAPTERS
    ]


def resolve_adapter_for_window(
    window: WindowInfo,
    *,
    preferred_profile: str = "",
    allowlisted_profiles: set[str] | None = None,
) -> DesktopAppAdapter | None:
    preferred = str(preferred_profile or "").strip().lower()
    allowlisted = {item.strip().lower() for item in (allowlisted_profiles or set()) if str(item or "").strip()}
    for adapter in _ADAPTERS:
        if preferred and adapter.workflow_profile != preferred:
            continue
        if allowlisted and adapter.workflow_profile not in allowlisted:
            continue
        if adapter.matches(window):
            return adapter
    return None


def adapter_by_profile(profile: str) -> DesktopAppAdapter | None:
    wanted = str(profile or "").strip().lower()
    for adapter in _ADAPTERS:
        if adapter.workflow_profile == wanted:
            return adapter
    return None
