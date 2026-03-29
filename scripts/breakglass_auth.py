"""Human-only local authorization helpers for breakglass flows."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final

WINDOWS_CREDENTIAL_METHOD: Final[str] = "windows-credential-dialog"
WINDOWS_CREDENTIAL_CAPTION: Final[str] = "Thomas Windows Sign-In"
WINDOWS_CONFIRMATION_CAPTION: Final[str] = "Thomas Security Approval"

ERROR_CANCELLED: Final[int] = 1223
ERROR_INSUFFICIENT_BUFFER: Final[int] = 122

CREDUIWIN_IN_CRED_ONLY: Final[int] = 0x20
CREDUIWIN_ENUMERATE_CURRENT_USER: Final[int] = 0x200

EXTENDED_NAME_FORMAT_SAM_COMPATIBLE: Final[int] = 2

LOGON32_LOGON_NETWORK: Final[int] = 3
LOGON32_PROVIDER_DEFAULT: Final[int] = 0

SECURITY_LOGON_TYPE_NETWORK: Final[int] = 3

TDCBF_OK_BUTTON: Final[int] = 0x0001
TDCBF_CANCEL_BUTTON: Final[int] = 0x0008
IDOK: Final[int] = 1
IDCANCEL: Final[int] = 2
TD_SHIELD_ICON_RESOURCE_ID: Final[int] = -4


@dataclass(frozen=True)
class BreakglassAuthorization:
    ok: bool
    message: str
    actor: str | None = None
    method: str | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class _PromptResult:
    ok: bool
    message: str
    auth_package: int = 0
    auth_buffer: bytes = b""
    actor: str | None = None
    cancelled: bool = False


class _CREDUI_INFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hwndParent", wintypes.HWND),
        ("pszMessageText", wintypes.LPWSTR),
        ("pszCaptionText", wintypes.LPWSTR),
        ("hbmBanner", wintypes.HANDLE),
    ]


class _LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class _TOKEN_SOURCE(ctypes.Structure):
    _fields_ = [
        ("SourceName", ctypes.c_char * 8),
        ("SourceIdentifier", _LUID),
    ]


class _LSA_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_char_p),
    ]


class _QUOTA_LIMITS(ctypes.Structure):
    _fields_ = [
        ("PagedPoolLimit", ctypes.c_size_t),
        ("NonPagedPoolLimit", ctypes.c_size_t),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("PagefileLimit", ctypes.c_size_t),
        ("TimeLimit", ctypes.c_longlong),
    ]


def _ctypes_lib(name: str, *, use_last_error: bool = False):
    return ctypes.WinDLL(name, use_last_error=use_last_error)


def _format_windows_error(code: int) -> str:
    text = ctypes.FormatError(int(code or 0)).strip()
    return text or f"Windows error {int(code or 0)}"


def _current_windows_sam_name() -> str:
    if os.name != "nt":
        return ""
    try:
        secur32 = _ctypes_lib("secur32", use_last_error=True)
        get_user_name_ex = secur32.GetUserNameExW
        get_user_name_ex.argtypes = [wintypes.ULONG, wintypes.LPWSTR, ctypes.POINTER(wintypes.ULONG)]
        get_user_name_ex.restype = wintypes.BOOL

        size = wintypes.ULONG(0)
        get_user_name_ex(EXTENDED_NAME_FORMAT_SAM_COMPATIBLE, None, ctypes.byref(size))
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value + 1)
            if get_user_name_ex(EXTENDED_NAME_FORMAT_SAM_COMPATIBLE, buf, ctypes.byref(size)):
                value = str(buf.value or "").strip()
                if value:
                    return value
    except OSError:
        pass

    domain = str(os.environ.get("USERDOMAIN") or "").strip()
    username = str(os.environ.get("USERNAME") or "").strip()
    if domain and username:
        return f"{domain}\\{username}"
    return username


def _human_breakglass_enabled() -> bool:
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path
    except ImportError:
        return False

    try:
        prefs = PreferencesStore(get_db_path()).get(user_id="default")
    except (OSError, RuntimeError, ValueError):
        return False

    security = getattr(getattr(prefs, "advanced", None), "security", None)
    return bool(getattr(security, "human_breakglass_enabled", False))


def _build_windows_prompt_message(
    *,
    current_user: str,
) -> str:
    return (
        "Confirm this protected Thomas action with your Windows sign-in.\n"
        f"Account: {current_user or 'current signed-in user'}\n"
        "Windows may offer PIN, password, or Windows Hello."
    )


def _build_windows_confirmation_copy(
    *,
    purpose: str,
    agent: str,
    ticket: str,
    reason: str,
    skip_hooks: list[str],
    current_user: str,
) -> tuple[str, str]:
    hooks_preview = ", ".join(skip_hooks[:2]) if skip_hooks else "none"
    content = "\n".join(
        [
            f"Account: {current_user or 'current signed-in user'}",
            f"Requested by: {agent}",
            f"Ticket: {ticket}",
            f"Action: {purpose}",
            f"Hooks: {hooks_preview}",
            "",
            "Continue to open the Windows sign-in prompt.",
        ]
    )
    if reason:
        content = f"{content}\n\n{reason}"
    return WINDOWS_CONFIRMATION_CAPTION, "Approve protected Thomas change?", content


def _build_windows_prompt_copy(*, current_user: str) -> tuple[str, str]:
    return (
        WINDOWS_CREDENTIAL_CAPTION,
        _build_windows_prompt_message(current_user=current_user),
    )


def _task_dialog_icon(resource_id: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(resource_id & 0xFFFF)


def _show_breakglass_confirmation_dialog(*, window_title: str, main_instruction: str, content: str) -> bool:
    comctl32 = _ctypes_lib("comctl32", use_last_error=True)
    task_dialog = comctl32.TaskDialog
    task_dialog.argtypes = [
        wintypes.HWND,
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    task_dialog.restype = wintypes.LONG

    button = ctypes.c_int(0)
    hr = task_dialog(
        None,
        None,
        window_title,
        main_instruction,
        content,
        TDCBF_OK_BUTTON | TDCBF_CANCEL_BUTTON,
        _task_dialog_icon(TD_SHIELD_ICON_RESOURCE_ID),
        ctypes.byref(button),
    )
    if hr != 0:
        raise OSError(int(hr), f"TaskDialog failed: {_format_windows_error(hr)}")
    return int(button.value) == IDOK


def _pack_current_user(credui, current_user: str):
    pack = credui.CredPackAuthenticationBufferW
    pack.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    pack.restype = wintypes.BOOL

    size = wintypes.DWORD(0)
    ctypes.set_last_error(0)
    pack(0, current_user, "", None, ctypes.byref(size))
    err = ctypes.get_last_error()
    if size.value <= 0 or err not in {0, ERROR_INSUFFICIENT_BUFFER}:
        raise OSError(err or 0, f"CredPackAuthenticationBufferW size probe failed: {_format_windows_error(err)}")

    buf = (ctypes.c_byte * size.value)()
    ctypes.set_last_error(0)
    if not pack(0, current_user, "", ctypes.byref(buf), ctypes.byref(size)):
        err = ctypes.get_last_error()
        raise OSError(err or 0, f"CredPackAuthenticationBufferW failed: {_format_windows_error(err)}")
    return buf, int(size.value)


def _prompt_for_windows_credentials(
    *,
    current_user: str,
    caption: str,
    message: str,
) -> _PromptResult:
    credui = _ctypes_lib("credui", use_last_error=True)
    ole32 = _ctypes_lib("ole32")

    prompt = _CREDUI_INFO()
    prompt.cbSize = ctypes.sizeof(_CREDUI_INFO)
    prompt.hwndParent = None
    prompt.pszCaptionText = caption
    prompt.pszMessageText = message
    prompt.hbmBanner = None

    input_buffer, input_size = _pack_current_user(credui, current_user)
    auth_package = wintypes.ULONG(0)
    out_buffer = ctypes.c_void_p()
    out_size = wintypes.ULONG(0)
    save = wintypes.BOOL(False)

    prompt_for_creds = credui.CredUIPromptForWindowsCredentialsW
    prompt_for_creds.argtypes = [
        ctypes.POINTER(_CREDUI_INFO),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.ULONG),
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG),
        ctypes.POINTER(wintypes.BOOL),
        wintypes.DWORD,
    ]
    prompt_for_creds.restype = wintypes.DWORD

    flags = CREDUIWIN_IN_CRED_ONLY | CREDUIWIN_ENUMERATE_CURRENT_USER
    rc = prompt_for_creds(
        ctypes.byref(prompt),
        0,
        ctypes.byref(auth_package),
        ctypes.byref(input_buffer),
        input_size,
        ctypes.byref(out_buffer),
        ctypes.byref(out_size),
        ctypes.byref(save),
        flags,
    )
    if rc == ERROR_CANCELLED:
        return _PromptResult(
            ok=False,
            cancelled=True,
            actor=current_user,
            message="breakglass authorization cancelled by user",
        )
    if rc != 0:
        return _PromptResult(
            ok=False,
            actor=current_user,
            message=f"Windows credential prompt failed: {_format_windows_error(rc)}",
        )

    try:
        auth_buffer = ctypes.string_at(out_buffer.value, out_size.value) if out_buffer.value and out_size.value else b""
        return _PromptResult(
            ok=True,
            actor=current_user,
            auth_package=int(auth_package.value),
            auth_buffer=auth_buffer,
            message="credential prompt completed",
        )
    finally:
        if out_buffer.value and out_size.value:
            ctypes.memset(out_buffer.value, 0, out_size.value)
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        ole32.CoTaskMemFree(out_buffer)


def _unpack_authentication_buffer(auth_buffer: bytes) -> tuple[str, str, str]:
    if not auth_buffer:
        return "", "", ""
    credui = _ctypes_lib("credui", use_last_error=True)
    unpack = credui.CredUnPackAuthenticationBufferW
    unpack.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    unpack.restype = wintypes.BOOL

    raw = ctypes.create_string_buffer(auth_buffer, len(auth_buffer))
    username_len = wintypes.DWORD(0)
    domain_len = wintypes.DWORD(0)
    password_len = wintypes.DWORD(0)
    ctypes.set_last_error(0)
    unpack(
        0,
        ctypes.byref(raw),
        len(auth_buffer),
        None,
        ctypes.byref(username_len),
        None,
        ctypes.byref(domain_len),
        None,
        ctypes.byref(password_len),
    )
    err = ctypes.get_last_error()
    if err not in {0, ERROR_INSUFFICIENT_BUFFER}:
        return "", "", ""

    username = ctypes.create_unicode_buffer(max(1, int(username_len.value)))
    domain = ctypes.create_unicode_buffer(max(1, int(domain_len.value)))
    password = ctypes.create_unicode_buffer(max(1, int(password_len.value)))
    ctypes.set_last_error(0)
    ok = unpack(
        0,
        ctypes.byref(raw),
        len(auth_buffer),
        username,
        ctypes.byref(username_len),
        domain,
        ctypes.byref(domain_len),
        password,
        ctypes.byref(password_len),
    )
    if not ok:
        return "", "", ""
    return str(username.value or "").strip(), str(domain.value or "").strip(), str(password.value or "")


def _validate_with_logon_user(*, username: str, domain: str, secret: str) -> tuple[bool, str]:
    if not username or not secret:
        return False, "unpacked credentials were empty"
    advapi32 = _ctypes_lib("advapi32", use_last_error=True)
    kernel32 = _ctypes_lib("kernel32", use_last_error=True)

    logon_user = advapi32.LogonUserW
    logon_user.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    logon_user.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    ctypes.set_last_error(0)
    ok = logon_user(
        username,
        domain or None,
        secret,
        LOGON32_LOGON_NETWORK,
        LOGON32_PROVIDER_DEFAULT,
        ctypes.byref(token),
    )
    if ok:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(token)
        return True, "validated with LogonUserW"
    err = ctypes.get_last_error()
    return False, f"LogonUserW failed: {_format_windows_error(err)}"


def _lsa_string(value: str) -> tuple[_LSA_STRING, ctypes.Array[ctypes.c_char]]:
    encoded = str(value or "").encode("ascii", errors="ignore")
    buf = ctypes.create_string_buffer(encoded)
    return (
        _LSA_STRING(
            Length=len(encoded),
            MaximumLength=len(encoded) + 1,
            Buffer=ctypes.cast(buf, ctypes.c_char_p),
        ),
        buf,
    )


def _validate_with_lsa(auth_package: int, auth_buffer: bytes) -> tuple[bool, str]:
    if auth_package <= 0 or not auth_buffer:
        return False, "missing authentication package or credential buffer"

    secur32 = _ctypes_lib("secur32")
    advapi32 = _ctypes_lib("advapi32", use_last_error=True)
    kernel32 = _ctypes_lib("kernel32", use_last_error=True)

    lsa_connect = secur32.LsaConnectUntrusted
    lsa_connect.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lsa_connect.restype = wintypes.LONG

    lsa_logon = secur32.LsaLogonUser
    lsa_logon.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_LSA_STRING),
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.c_void_p,
        ctypes.POINTER(_TOKEN_SOURCE),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG),
        ctypes.POINTER(_LUID),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_QUOTA_LIMITS),
        ctypes.POINTER(wintypes.LONG),
    ]
    lsa_logon.restype = wintypes.LONG

    lsa_free = secur32.LsaFreeReturnBuffer
    lsa_free.argtypes = [ctypes.c_void_p]
    lsa_free.restype = wintypes.LONG

    lsa_deregister = secur32.LsaDeregisterLogonProcess
    lsa_deregister.argtypes = [ctypes.c_void_p]
    lsa_deregister.restype = wintypes.LONG

    lsa_to_winerr = secur32.LsaNtStatusToWinError
    lsa_to_winerr.argtypes = [wintypes.LONG]
    lsa_to_winerr.restype = wintypes.ULONG

    alloc_luid = advapi32.AllocateLocallyUniqueId
    alloc_luid.argtypes = [ctypes.POINTER(_LUID)]
    alloc_luid.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = ctypes.c_void_p()
    status = lsa_connect(ctypes.byref(handle))
    if status != 0:
        err = int(lsa_to_winerr(status))
        return False, f"LsaConnectUntrusted failed: {_format_windows_error(err)}"

    origin, origin_buf = _lsa_string("ThomasBG")
    _ = origin_buf
    source = _TOKEN_SOURCE()
    source.SourceName = b"THMBRKGS"
    if not alloc_luid(ctypes.byref(source.SourceIdentifier)):
        err = ctypes.get_last_error()
        lsa_deregister(handle)
        return False, f"AllocateLocallyUniqueId failed: {_format_windows_error(err)}"

    auth_blob = ctypes.create_string_buffer(auth_buffer, len(auth_buffer))
    profile = ctypes.c_void_p()
    profile_len = wintypes.ULONG(0)
    logon_id = _LUID()
    token = wintypes.HANDLE()
    quotas = _QUOTA_LIMITS()
    sub_status = wintypes.LONG(0)

    try:
        status = lsa_logon(
            handle,
            ctypes.byref(origin),
            SECURITY_LOGON_TYPE_NETWORK,
            auth_package,
            ctypes.byref(auth_blob),
            len(auth_buffer),
            None,
            ctypes.byref(source),
            ctypes.byref(profile),
            ctypes.byref(profile_len),
            ctypes.byref(logon_id),
            ctypes.byref(token),
            ctypes.byref(quotas),
            ctypes.byref(sub_status),
        )
        if status == 0:
            return True, "validated with LsaLogonUser"
        primary = int(lsa_to_winerr(status))
        secondary = int(lsa_to_winerr(sub_status.value)) if sub_status.value else 0
        detail = _format_windows_error(primary)
        if secondary and secondary != primary:
            detail += f" (substatus: {_format_windows_error(secondary)})"
        return False, f"LsaLogonUser failed: {detail}"
    finally:
        if profile.value:
            lsa_free(profile)
        if token:
            close_handle(token)
        lsa_deregister(handle)


def _run_windows_credential_prompt(*, prompt_caption: str, prompt_message: str) -> BreakglassAuthorization:
    current_user = _current_windows_sam_name()
    if not current_user:
        return BreakglassAuthorization(
            ok=False,
            message="current Windows user could not be resolved",
            method=WINDOWS_CREDENTIAL_METHOD,
        )

    try:
        prompt = _prompt_for_windows_credentials(
            current_user=current_user,
            caption=prompt_caption,
            message=prompt_message,
        )
    except OSError as exc:
        return BreakglassAuthorization(
            ok=False,
            message=str(exc),
            actor=current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
        )

    if not prompt.ok:
        return BreakglassAuthorization(
            ok=False,
            message=prompt.message,
            actor=prompt.actor or current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
            cancelled=prompt.cancelled,
        )

    auth_ok, auth_message = _validate_with_lsa(prompt.auth_package, prompt.auth_buffer)
    actor = prompt.actor or current_user
    if not auth_ok:
        unpacked_user, unpacked_domain, unpacked_secret = _unpack_authentication_buffer(prompt.auth_buffer)
        if unpacked_user and unpacked_secret:
            unpacked_leaf_user = unpacked_user.split("\\", 1)[-1]
            auth_ok, fallback_message = _validate_with_logon_user(
                username=unpacked_leaf_user,
                domain=unpacked_domain or unpacked_user.partition("\\")[0],
                secret=unpacked_secret,
            )
            if auth_ok:
                auth_message = fallback_message
            else:
                auth_message = f"{auth_message}; {fallback_message}"

    if not auth_ok:
        return BreakglassAuthorization(
            ok=False,
            message=auth_message,
            actor=actor,
            method=WINDOWS_CREDENTIAL_METHOD,
        )

    return BreakglassAuthorization(
        ok=True,
        message="validated with Windows sign-in prompt",
        actor=actor,
        method=WINDOWS_CREDENTIAL_METHOD,
    )


def authorize_breakglass(
    *,
    purpose: str,
    agent: str,
    ticket: str,
    reason: str,
    skip_hooks: list[str] | None = None,
) -> BreakglassAuthorization:
    hooks = [str(item or "").strip() for item in list(skip_hooks or []) if str(item or "").strip()]
    if os.name != "nt":
        return BreakglassAuthorization(
            ok=False,
            message="human breakglass authorization is only supported on Windows interactive sessions",
            method="unsupported-platform",
        )
    if not _human_breakglass_enabled():
        return BreakglassAuthorization(
            ok=False,
            message="human breakglass authorization is disabled. Enable Protected Override Approval in Thomas Settings or Easy Setup first.",
            method="disabled-by-preference",
        )
    current_user = _current_windows_sam_name()
    if not current_user:
        return BreakglassAuthorization(
            ok=False,
            message="current Windows user could not be resolved",
            method=WINDOWS_CREDENTIAL_METHOD,
        )

    confirm_title, confirm_instruction, confirm_content = _build_windows_confirmation_copy(
        purpose=str(purpose or "").strip() or "breakglass override",
        agent=str(agent or "").strip() or "unknown-agent",
        ticket=str(ticket or "").strip(),
        reason=str(reason or "").strip(),
        skip_hooks=hooks,
        current_user=current_user,
    )
    try:
        approved = _show_breakglass_confirmation_dialog(
            window_title=confirm_title,
            main_instruction=confirm_instruction,
            content=confirm_content,
        )
    except OSError as exc:
        return BreakglassAuthorization(
            ok=False,
            message=str(exc),
            actor=current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
        )
    if not approved:
        return BreakglassAuthorization(
            ok=False,
            message="breakglass approval cancelled before Windows sign-in",
            actor=current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
            cancelled=True,
        )

    prompt_caption, prompt_message = _build_windows_prompt_copy(current_user=current_user)
    return _run_windows_credential_prompt(
        prompt_caption=prompt_caption,
        prompt_message=prompt_message,
    )
