from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import platform
import secrets
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

AuthPlatform = Literal["windows", "macos", "linux", "unknown"]
AccessKind = Literal["read", "write", "exec", "admin"]
EnforcementMode = Literal["development", "protected"]

_PATH_KEYS = (
    "path",
    "paths",
    "file",
    "filename",
    "filepath",
    "file_path",
    "source_path",
    "destination_path",
    "payload_path",
    "auth_path",
    "auth_payload_path",
    "cwd",
    "workdir",
    "workspace",
    "workspace_path",
    "directory",
    "repo_root",
    "root",
)
_WRITE_KEYWORDS = (
    "write",
    "edit",
    "create",
    "delete",
    "remove",
    "replace",
    "patch",
    "append",
    "rename",
    "move",
    "mkdir",
    "touch",
    "copy",
    "commit",
)
_EXEC_KEYWORDS = ("shell", "exec", "run", "git", "browser", "workspace")
_ADMIN_KEYWORDS = ("secret", "settings", "approval", "admin")


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def desired_default_allow_third_party_agent_access(environment: str | None = None) -> bool:
    env = str(environment or os.environ.get("THOMAS_ENV") or "development").strip().lower()
    return env != "production"


def enforcement_mode_for_allow(enabled: bool) -> EnforcementMode:
    return "development" if bool(enabled) else "protected"


def production_default_seed_is_safe() -> bool:
    return not desired_default_allow_third_party_agent_access("production")


def current_local_actor() -> str:
    try:
        actor = str(getpass.getuser() or "").strip()
    except Exception:
        actor = ""
    if actor:
        return actor
    actor = str(os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()
    return actor or "local-user"


@dataclass(frozen=True)
class AuthResult:
    authorized: bool
    method: str
    platform: AuthPlatform
    error_code: str | None = None


class LocalStepUpAuthProvider(Protocol):
    def authorize(self, action: str, reason: str) -> AuthResult: ...


class UnsupportedLocalStepUpAuthProvider:
    def authorize(self, action: str, reason: str) -> AuthResult:
        _ = (action, reason)
        return AuthResult(
            authorized=False,
            method="unsupported",
            platform="unknown",
            error_code="platform_unsupported",
        )


class WindowsStepUpAuthProvider:
    def authorize(self, action: str, reason: str) -> AuthResult:
        if platform.system() != "Windows":
            return AuthResult(False, "windows_cred_ui", "windows", "wrong_platform")
        try:
            import win32api
            import win32cred
        except ImportError:
            return AuthResult(False, "windows_cred_ui", "windows", "pywin32_missing")

        target = f"THOMAS-STEP-UP:{str(action or '')[:60]}"
        message = (
            f"Thomas requires local authorization.\n\n"
            f"Action: {action}\n\n"
            f"Reason: {reason}\n\n"
            "Enter your Windows credentials to continue."
        )
        flags = (
            win32cred.CREDUI_FLAGS_GENERIC_CREDENTIALS
            | win32cred.CREDUI_FLAGS_EXPECT_CONFIRMATION
            | win32cred.CREDUI_FLAGS_COMPLETE_USERNAME
        )
        try:
            username = win32api.GetUserName()
        except Exception:
            username = ""
        try:
            result, _username, _password, _saved = win32cred.CredUIPromptForCredentials(
                target,
                0,
                username,
                "",
                False,
                flags,
                message,
            )
        except Exception:
            return AuthResult(False, "windows_cred_ui", "windows", "auth_dialog_failed")
        return AuthResult(result == 0, "windows_cred_ui", "windows", None if result == 0 else "auth_denied")


class MacOSStepUpAuthProvider:
    def authorize(self, action: str, reason: str) -> AuthResult:
        if platform.system() != "Darwin":
            return AuthResult(False, "macos_local_auth", "macos", "wrong_platform")
        script = (
            'display dialog "Thomas requires local authorization for: '
            + str(action or "").replace('"', '\\"')
            + '" with title "Thomas Security" buttons {"Cancel", "Allow"} '
            + 'default button "Allow" cancel button "Cancel" with icon caution '
            + "giving up after 120 with hidden answer"
        )
        try:
            completed = subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=130,
            )
        except FileNotFoundError:
            return AuthResult(False, "macos_local_auth", "macos", "osascript_missing")
        except Exception:
            return AuthResult(False, "macos_local_auth", "macos", "auth_dialog_failed")
        _ = reason
        return AuthResult(
            completed.returncode == 0,
            "macos_local_auth",
            "macos",
            None if completed.returncode == 0 else "auth_denied",
        )


class LinuxPolkitStepUpAuthProvider:
    def authorize(self, action: str, reason: str) -> AuthResult:
        if platform.system() != "Linux":
            return AuthResult(False, "linux_polkit", "linux", "wrong_platform")
        cmd = [
            "pkcheck",
            "--allow-user-interaction",
            "--action-id",
            "com.thomas.security.toggle-third-party-agent-access",
            "--process",
            str(os.getpid()),
        ]
        env = dict(os.environ)
        env.setdefault("THOMAS_STEP_UP_REASON", str(reason or ""))
        env.setdefault("THOMAS_STEP_UP_ACTION", str(action or ""))
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=130,
                env=env,
            )
        except FileNotFoundError:
            return AuthResult(False, "linux_polkit", "linux", "pkcheck_missing")
        except Exception:
            return AuthResult(False, "linux_polkit", "linux", "auth_dialog_failed")
        return AuthResult(
            completed.returncode == 0,
            "linux_polkit",
            "linux",
            None if completed.returncode == 0 else "auth_denied",
        )


def build_local_step_up_auth_provider() -> LocalStepUpAuthProvider:
    system_name = platform.system()
    if system_name == "Windows":
        return WindowsStepUpAuthProvider()
    if system_name == "Darwin":
        return MacOSStepUpAuthProvider()
    if system_name == "Linux":
        return LinuxPolkitStepUpAuthProvider()
    return UnsupportedLocalStepUpAuthProvider()


@dataclass(frozen=True)
class TrustedAgentToken:
    token_id: str
    agent_id: str
    session_id: str
    issuer: str = "thomas-runtime"
    origin: str = "internal"
    issued_at: str = ""
    expires_at: str = ""
    capabilities: tuple[AccessKind, ...] = field(default_factory=tuple)
    allowed_roots: tuple[str, ...] = field(default_factory=tuple)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "issuer": self.issuer,
            "origin": self.origin,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "capabilities": list(self.capabilities),
            "allowed_roots": list(self.allowed_roots),
            "signature": self.signature,
        }


@dataclass(frozen=True)
class TrustedAgentContext:
    token: TrustedAgentToken | None
    authorized: bool
    capabilities: frozenset[AccessKind] = field(default_factory=frozenset)
    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    reason: str = ""


@dataclass(frozen=True)
class AccessRequest:
    action: AccessKind
    tool_name: str
    target_paths: tuple[str, ...] = field(default_factory=tuple)
    cwd: str = ""
    runtime_root: str = ""
    admin_surface: str = ""


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    enforcement_mode: EnforcementMode
    matched_paths: tuple[str, ...] = field(default_factory=tuple)


class TrustedAgentBroker:
    def __init__(self, *, secret: bytes | None = None, token_ttl_s: int = 900) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._token_ttl_s = max(30, int(token_ttl_s))
        self._revoked: set[str] = set()

    @staticmethod
    def _normalize_token(token: TrustedAgentToken | dict[str, Any]) -> TrustedAgentToken:
        if isinstance(token, TrustedAgentToken):
            return token
        capabilities = tuple(str(x) for x in list(token.get("capabilities") or []))
        allowed_roots = tuple(str(x) for x in list(token.get("allowed_roots") or []))
        return TrustedAgentToken(
            token_id=str(token.get("token_id") or "").strip(),
            agent_id=str(token.get("agent_id") or "").strip(),
            session_id=str(token.get("session_id") or "").strip(),
            issuer=str(token.get("issuer") or "thomas-runtime").strip() or "thomas-runtime",
            origin=str(token.get("origin") or "internal").strip() or "internal",
            issued_at=str(token.get("issued_at") or "").strip(),
            expires_at=str(token.get("expires_at") or "").strip(),
            capabilities=tuple(capabilities),
            allowed_roots=tuple(allowed_roots),
            signature=str(token.get("signature") or "").strip(),
        )

    @staticmethod
    def _canonical_payload(token: TrustedAgentToken) -> bytes:
        payload = token.to_dict()
        payload.pop("signature", None)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _signature_for(self, token: TrustedAgentToken) -> str:
        digest = hmac.new(self._secret, self._canonical_payload(token), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _parse_epoch(ts: str) -> float | None:
        raw = str(ts or "").strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                from datetime import datetime, timezone

                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
            return float(raw)
        except Exception:
            return None

    def mint_internal_token(
        self,
        *,
        agent_id: str,
        session_id: str,
        capabilities: list[AccessKind] | tuple[AccessKind, ...],
        allowed_roots: list[str] | tuple[str, ...],
    ) -> TrustedAgentToken:
        issued_at = _utc_now_iso()
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + self._token_ttl_s))
        unsigned = TrustedAgentToken(
            token_id=f"tat_{uuid.uuid4().hex}",
            agent_id=str(agent_id or "internal-agent").strip() or "internal-agent",
            session_id=str(session_id or "").strip(),
            issued_at=issued_at,
            expires_at=expires_at,
            capabilities=tuple(str(x) for x in capabilities),
            allowed_roots=tuple(str(Path(p).resolve()) for p in allowed_roots if str(p).strip()),
        )
        return TrustedAgentToken(**{**unsigned.to_dict(), "signature": self._signature_for(unsigned)})

    def revoke(self, token_id: str) -> None:
        token = str(token_id or "").strip()
        if token:
            self._revoked.add(token)

    def resolve_context(self, token: TrustedAgentToken | dict[str, Any] | None) -> TrustedAgentContext:
        if token is None:
            return TrustedAgentContext(token=None, authorized=False, reason="missing_internal_token")
        try:
            parsed = self._normalize_token(token)
        except Exception:
            return TrustedAgentContext(token=None, authorized=False, reason="invalid_internal_token")
        if not parsed.token_id or not parsed.signature:
            return TrustedAgentContext(token=None, authorized=False, reason="invalid_internal_token")
        if parsed.token_id in self._revoked:
            return TrustedAgentContext(token=parsed, authorized=False, reason="revoked_internal_token")
        if parsed.issuer != "thomas-runtime" or parsed.origin != "internal":
            return TrustedAgentContext(token=parsed, authorized=False, reason="untrusted_token_origin")
        if not hmac.compare_digest(
            parsed.signature, self._signature_for(TrustedAgentToken(**{**parsed.to_dict(), "signature": ""}))
        ):
            return TrustedAgentContext(token=parsed, authorized=False, reason="invalid_internal_token_signature")
        expires_at = self._parse_epoch(parsed.expires_at)
        if expires_at is None:
            return TrustedAgentContext(token=parsed, authorized=False, reason="invalid_internal_token_expiry")
        if time.time() > expires_at:
            return TrustedAgentContext(token=parsed, authorized=False, reason="expired_internal_token")
        allowed_roots = tuple(Path(p).resolve() for p in parsed.allowed_roots if str(p).strip())
        capabilities = frozenset(str(x) for x in parsed.capabilities)
        return TrustedAgentContext(
            token=parsed,
            authorized=True,
            capabilities=capabilities,
            allowed_roots=allowed_roots,
            reason="authorized_internal_token",
        )


def _resolve_path(candidate: Any, *, base: Path) -> str | None:
    text = str(candidate or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = (base / path).resolve()
    else:
        path = path.resolve()
    return str(path)


def _dedupe_preserve(items: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return tuple(out)


def _infer_action(tool_name: str, args: dict[str, Any]) -> AccessKind:
    lowered = str(tool_name or "").strip().lower()
    if any(keyword in lowered for keyword in _ADMIN_KEYWORDS):
        return "admin"
    if any(keyword in lowered for keyword in _WRITE_KEYWORDS):
        return "write"
    if any(keyword in lowered for keyword in _EXEC_KEYWORDS) or "command" in args:
        return "exec"
    return "read"


def build_access_request(*, tool_name: str, args: dict[str, Any], cwd: str, runtime_root: str) -> AccessRequest:
    base = Path(str(cwd or runtime_root or ".")).resolve()
    targets: list[str] = []
    action = _infer_action(tool_name, args)
    if action in {"exec", "read", "write"}:
        targets.append(str(base))
    for key in _PATH_KEYS:
        if key not in args:
            continue
        raw_value = args.get(key)
        if isinstance(raw_value, (list, tuple, set)):
            for item in raw_value:
                resolved = _resolve_path(item, base=base)
                if resolved:
                    targets.append(resolved)
            continue
        resolved = _resolve_path(raw_value, base=base)
        if resolved:
            targets.append(resolved)
    admin_surface = ""
    if action == "admin":
        admin_surface = str(tool_name or "admin").strip() or "admin"
    return AccessRequest(
        action=action,
        tool_name=str(tool_name or "").strip(),
        target_paths=_dedupe_preserve(targets),
        cwd=str(base),
        runtime_root=str(Path(runtime_root).resolve()) if str(runtime_root or "").strip() else "",
        admin_surface=admin_surface,
    )


class ProtectedInternalsGate:
    def __init__(
        self,
        *,
        token_broker: TrustedAgentBroker,
        allow_third_party_access: bool,
        repo_root: str | Path,
        data_root: str | Path,
        extra_protected_roots: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self._token_broker = token_broker
        self._allow_third_party_access = bool(allow_third_party_access)
        roots = [str(Path(repo_root).resolve()), str(Path(data_root).resolve())]
        roots.append(str((Path(data_root).resolve() / ".thomas").resolve()))
        for raw in list(extra_protected_roots or []):
            if str(raw or "").strip():
                roots.append(str(Path(raw).resolve()))
        self._protected_roots = tuple(Path(p).resolve() for p in _dedupe_preserve(roots))

    @property
    def protected_roots(self) -> tuple[str, ...]:
        return tuple(str(p) for p in self._protected_roots)

    @property
    def allow_third_party_access(self) -> bool:
        return self._allow_third_party_access

    def set_allow_third_party_access(self, enabled: bool) -> None:
        self._allow_third_party_access = bool(enabled)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "protected_mode": not self._allow_third_party_access,
            "allow_third_party_agent_access": self._allow_third_party_access,
            "enforcement_mode": enforcement_mode_for_allow(self._allow_third_party_access),
            "protected_roots": [str(p) for p in self._protected_roots],
        }

    def _matched_protected_paths(self, request: AccessRequest) -> tuple[str, ...]:
        matches: list[str] = []
        for raw in request.target_paths:
            try:
                target = Path(raw).resolve()
            except Exception:
                continue
            for root in self._protected_roots:
                try:
                    target.relative_to(root)
                    matches.append(str(target))
                    break
                except Exception:
                    continue
        if request.admin_surface:
            matches.append(f"admin:{request.admin_surface}")
        return _dedupe_preserve(matches)

    @staticmethod
    def _path_allowed(targets: tuple[str, ...], allowed_roots: tuple[Path, ...]) -> bool:
        if not targets:
            return True
        concrete_targets = [Path(t).resolve() for t in targets if not str(t).startswith("admin:")]
        if not concrete_targets:
            return True
        if not allowed_roots:
            return False
        for target in concrete_targets:
            allowed = False
            for root in allowed_roots:
                try:
                    target.relative_to(root)
                    allowed = True
                    break
                except Exception:
                    continue
            if not allowed:
                return False
        return True

    def check(
        self,
        request: AccessRequest,
        *,
        trusted_agent_token: TrustedAgentToken | dict[str, Any] | None = None,
    ) -> AccessDecision:
        mode = enforcement_mode_for_allow(self._allow_third_party_access)
        if self._allow_third_party_access:
            return AccessDecision(True, "third_party_agent_access_enabled", mode)

        matched = self._matched_protected_paths(request)
        if not matched:
            return AccessDecision(True, "outside_protected_internals", mode)

        context = self._token_broker.resolve_context(trusted_agent_token)
        if not context.authorized:
            return AccessDecision(False, context.reason or "missing_internal_token", mode, matched)
        if request.action not in context.capabilities:
            return AccessDecision(False, f"internal_token_missing_{request.action}_capability", mode, matched)
        if not self._path_allowed(matched, context.allowed_roots):
            return AccessDecision(False, "internal_token_root_mismatch", mode, matched)
        return AccessDecision(True, "internal_token_authorized", mode, matched)
