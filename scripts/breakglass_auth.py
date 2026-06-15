"""Human-only local authorization helpers for breakglass flows."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.breakglass_context import (
    BreakglassContext,
    breakglass_context_from_env,
    breakglass_context_payload,
)
from scripts.breakglass_window_core import (
    DEFAULT_WINDOW_HOURS,
    active_window,
    mint_window,
)

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

THOMAS_ASSET_PATH: Final[Path] = _REPO_ROOT / "assets" / "thomas.png"
THOMAS_ICON_PATH: Final[Path] = _REPO_ROOT / "assets" / "thomas.ico"


@dataclass(frozen=True)
class BreakglassAuthorization:
    ok: bool
    message: str
    actor: str | None = None
    method: str | None = None
    cancelled: bool = False
    action_requested: bool = False
    action_prompt: str | None = None


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


def _breakglass_window_prefs() -> tuple[bool, float]:
    """Read (enabled, hours) for the breakglass approval window from user prefs.

    The window length is user-controlled in Settings (Protected Override
    Approval). Returns (False, default) when prefs are unavailable so behavior
    falls back to prompting every time.
    """
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path
    except ImportError:
        return False, DEFAULT_WINDOW_HOURS

    try:
        prefs = PreferencesStore(get_db_path()).get(user_id="default")
    except (OSError, RuntimeError, ValueError):
        return False, DEFAULT_WINDOW_HOURS

    security = getattr(getattr(prefs, "advanced", None), "security", None)
    enabled = bool(getattr(security, "breakglass_window_enabled", False))
    try:
        hours = float(getattr(security, "breakglass_window_hours", DEFAULT_WINDOW_HOURS))
    except (TypeError, ValueError):
        hours = DEFAULT_WINDOW_HOURS
    return enabled, hours


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
) -> tuple[str, str, str]:
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


def _clip(value: str, limit: int = 260) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _without_recommendation_prefix(value: str) -> str:
    return _clip(str(value or "").removeprefix("Recommendation:"), 420).strip()


def _format_context_issue(index: int, issue) -> list[str]:
    human_reason = _clip(getattr(issue, "plain_reason", "") or issue.why, 240)
    impact = _clip(getattr(issue, "impact", ""), 260)
    next_step = _clip(getattr(issue, "next_step", ""), 260)
    recommendation = _without_recommendation_prefix(getattr(issue, "recommendation", ""))
    lines = [
        f"{index}. {issue.gate}",
        f"   What happened: {human_reason}",
    ]
    if impact:
        lines.append(f"   Why it matters: {impact}")
    for item in tuple(issue.evidence or ())[:2]:
        detail = _clip(item, 240)
        if detail.lower() == human_reason.lower():
            continue
        lines.append(f"   Evidence: {detail}")
    if recommendation:
        lines.append(f"   What I recommend: {recommendation}")
    if next_step:
        lines.append(f"   Next step: {next_step}")
    return lines


def _build_context_confirmation_copy(
    *,
    context: BreakglassContext,
    purpose: str,
    agent: str,
    ticket: str,
    reason: str,
    skip_hooks: list[str],
    current_user: str,
) -> tuple[str, str, str, str, str, str, str]:
    hooks_preview = ", ".join(skip_hooks[:4]) if skip_hooks else "none"
    lines = [
        _clip(context.summary, 360),
        "",
        "Thomas recommendation:",
        _clip(context.recommendation or reason, 560),
        "",
        "Commit issues:",
    ]
    for index, issue in enumerate(tuple(context.issues or ())[:5], start=1):
        lines.extend(_format_context_issue(index, issue))
        lines.append("")
    lines.extend(
        [
            "Request details:",
            f"Account: {current_user or 'current signed-in user'}",
            f"Requested by: {agent}",
            f"Ticket: {ticket}",
            f"Action: {purpose}",
            f"Guardrails involved: {hooks_preview}",
        ]
    )
    return (
        str(context.title or "Thomas commit blocker"),
        "Thomas needs your decision before breakglass.",
        "\n".join(lines).strip(),
        str(context.action_label or "Authorize recommended commit"),
        str(context.cancel_label or "Back out and talk to Thomas"),
        str(context.resolution_label or ""),
        str(context.resolution_prompt or ""),
    )


def _build_breakglass_decision_copy(
    *,
    purpose: str,
    agent: str,
    ticket: str,
    reason: str,
    skip_hooks: list[str],
    current_user: str,
    context: BreakglassContext | None = None,
) -> tuple[str, str, str, str, str, str, str]:
    if context is not None:
        return _build_context_confirmation_copy(
            context=context,
            purpose=purpose,
            agent=agent,
            ticket=ticket,
            reason=reason,
            skip_hooks=skip_hooks,
            current_user=current_user,
        )
    title, instruction, content = _build_windows_confirmation_copy(
        purpose=purpose,
        agent=agent,
        ticket=ticket,
        reason=reason,
        skip_hooks=skip_hooks,
        current_user=current_user,
    )
    return title, instruction, content, "Authorize protected change", "Back out", "", ""


def _build_windows_prompt_copy(*, current_user: str) -> tuple[str, str]:
    return (
        WINDOWS_CREDENTIAL_CAPTION,
        _build_windows_prompt_message(current_user=current_user),
    )


def _task_dialog_icon(resource_id: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(resource_id & 0xFFFF)


def _enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _dialog_geometry(screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    width = min(max(int(screen_width * 0.46), 920), min(1120, max(900, screen_width - 96)))
    height = min(max(int(screen_height * 0.54), 620), min(760, max(560, screen_height - 96)))
    left = max(24, int((screen_width - width) / 2))
    top = max(24, int((screen_height - height) / 2))
    return width, height, left, top


def _button_width_chars(label: str) -> int:
    return min(max((len(str(label or "")) + 2) // 2, 13), 22)


def _show_custom_breakglass_dialog(
    *,
    window_title: str,
    main_instruction: str,
    content: str,
    approve_label: str,
    cancel_label: str,
    resolution_label: str = "",
    resolution_prompt: str = "",
    context: BreakglassContext | None = None,
) -> str | None:
    _enable_windows_dpi_awareness()
    try:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk
    except Exception:
        return None

    try:
        root = tk.Tk()
    except Exception:
        return None

    result = {"decision": "cancel"}

    def finish(decision: str) -> None:
        result["decision"] = decision
        root.destroy()

    root.title(window_title)
    width, height, left, top = _dialog_geometry(root.winfo_screenwidth(), root.winfo_screenheight())
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.minsize(min(width, 900), min(height, 560))
    root.configure(bg="#f3faff")
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancel"))

    try:
        root.iconbitmap(str(THOMAS_ICON_PATH))
    except tk.TclError:
        pass

    try:
        root.attributes("-topmost", True)
        root.after(750, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass

    scale = max(0.9, min(1.03, width / 1220))
    title_font = tkfont.Font(family="Segoe UI", size=round(18 * scale), weight="bold")
    rail_title_font = tkfont.Font(family="Segoe UI", size=round(15 * scale), weight="bold")
    subtitle_font = tkfont.Font(family="Segoe UI", size=round(9 * scale))
    body_font = tkfont.Font(family="Segoe UI", size=round(10 * scale))
    body_bold_font = tkfont.Font(family="Segoe UI", size=round(10 * scale), weight="bold")
    label_font = tkfont.Font(family="Segoe UI", size=round(8 * scale), weight="bold")
    issue_title_font = tkfont.Font(family="Segoe UI", size=round(11 * scale), weight="bold")
    button_font = tkfont.Font(family="Segoe UI", size=round(9 * scale), weight="bold")

    navy = "#0b1726"
    blue = "#1769e0"
    robot_blue = "#9ad8ff"
    pale_blue = "#e5f6ff"
    page_bg = "#f3faff"
    card_border = "#b8d9f4"
    text_dark = "#0f172a"
    text_muted = "#475569"

    shell = tk.Frame(root, bg=page_bg)
    shell.pack(fill=tk.BOTH, expand=True)

    rail_width = max(150, int(width * 0.16))
    rail = tk.Frame(shell, bg=navy, width=rail_width, padx=18, pady=20)
    rail.pack(side=tk.LEFT, fill=tk.Y)
    rail.pack_propagate(False)

    try:
        robot_image = tk.PhotoImage(file=str(THOMAS_ASSET_PATH))
        max_robot_width = max(72, rail_width - 54)
        if robot_image.width() > max_robot_width:
            robot_image = robot_image.subsample(max(1, (robot_image.width() + max_robot_width - 1) // max_robot_width))
        root._thomas_robot_image = robot_image  # type: ignore[attr-defined]
        tk.Label(rail, image=robot_image, bg=navy).pack(anchor="w", pady=(0, 14))
    except tk.TclError:
        tk.Label(rail, text="Thomas", bg=navy, fg=robot_blue, font=rail_title_font, anchor="w").pack(
            fill=tk.X,
            pady=(0, 14),
        )

    tk.Label(
        rail,
        text="Thomas\nSecurity",
        bg=navy,
        fg=robot_blue,
        font=rail_title_font,
        anchor="w",
        justify=tk.LEFT,
    ).pack(fill=tk.X, pady=(0, 12))
    tk.Label(
        rail,
        text="Commit blocked. Human decision required.",
        bg=navy,
        fg="#d5ecff",
        font=body_bold_font,
        anchor="w",
        justify=tk.LEFT,
        wraplength=max(110, rail_width - 36),
    ).pack(fill=tk.X, pady=(0, 10))
    tk.Label(
        rail,
        text="Read the recommendation before bypassing guardrails.",
        bg=navy,
        fg="#94a3b8",
        font=subtitle_font,
        anchor="w",
        justify=tk.LEFT,
        wraplength=max(110, rail_width - 36),
    ).pack(fill=tk.X)

    main = tk.Frame(shell, bg=page_bg, padx=20, pady=16)
    main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    header = tk.Frame(main, bg=page_bg)
    header.pack(fill=tk.X)
    tk.Label(
        header,
        text=window_title,
        bg=page_bg,
        fg=text_dark,
        font=title_font,
        anchor="w",
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Label(
        header,
        text="BLOCKED",
        bg="#fff7ed",
        fg="#9a3412",
        font=label_font,
        padx=10,
        pady=5,
    ).pack(side=tk.RIGHT)
    tk.Label(
        main,
        text=main_instruction,
        bg=page_bg,
        fg=text_muted,
        font=subtitle_font,
        anchor="w",
        pady=4,
        wraplength=max(480, int(width * 0.52)),
    ).pack(fill=tk.X)

    recommendation_text = _clip(
        str(getattr(context, "recommendation", "") or "").strip() or _clip(content.split("Commit issues:", 1)[0], 560),
        460,
    )
    rec_card = tk.Frame(main, bg="#ffffff", highlightbackground=robot_blue, highlightthickness=2)
    rec_card.pack(fill=tk.X, pady=(12, 10))
    tk.Label(
        rec_card,
        text="MY RECOMMENDATION",
        bg=robot_blue,
        fg=navy,
        font=label_font,
        anchor="w",
        padx=12,
        pady=5,
    ).pack(fill=tk.X)
    tk.Label(
        rec_card,
        text=recommendation_text,
        bg="#ffffff",
        fg=text_dark,
        font=body_bold_font,
        anchor="w",
        justify=tk.LEFT,
        wraplength=max(460, width - rail_width - 100),
        padx=12,
        pady=10,
    ).pack(fill=tk.X)

    panel = tk.Frame(main, bg="#ffffff", highlightbackground="#b8d9f4", highlightthickness=1)
    panel.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

    canvas = tk.Canvas(panel, bg="#ffffff", highlightthickness=0, bd=0)
    scrollbar = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=canvas.yview)
    scroll_body = tk.Frame(canvas, bg="#ffffff")
    canvas_window = canvas.create_window((0, 0), window=scroll_body, anchor="nw")

    def sync_scroll_region(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def sync_canvas_width(event) -> None:
        canvas.itemconfigure(canvas_window, width=event.width)

    scroll_body.bind("<Configure>", sync_scroll_region)
    canvas.bind("<Configure>", sync_canvas_width)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def on_mousewheel(event) -> None:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", on_mousewheel)

    content_wrap = max(440, width - rail_width - 130)

    def add_field(parent, label: str, value: str, *, color: str, bg: str = "#ffffff") -> None:
        text_value = _clip(value, 360)
        if not text_value:
            return
        block = tk.Frame(parent, bg=bg, highlightbackground=color, highlightthickness=1)
        block.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            block,
            text=label.upper(),
            bg=color,
            fg=navy,
            font=label_font,
            anchor="w",
            padx=9,
            pady=3,
        ).pack(fill=tk.X)
        tk.Label(
            block,
            text=text_value,
            bg=bg,
            fg=text_dark,
            font=body_bold_font if label.lower().startswith(("what", "why")) else body_font,
            anchor="w",
            justify=tk.LEFT,
            wraplength=content_wrap,
            padx=10,
            pady=8,
        ).pack(fill=tk.X)

    def add_compact_row(parent, label: str, value: str, *, color: str) -> None:
        text_value = _clip(value, 240)
        if not text_value:
            return
        row = tk.Frame(parent, bg="#ffffff")
        row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(
            row,
            text=label.upper(),
            bg=color,
            fg=navy,
            font=label_font,
            anchor="w",
            width=18,
            padx=8,
            pady=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            row,
            text=text_value,
            bg="#ffffff",
            fg=text_dark,
            font=body_bold_font,
            anchor="w",
            justify=tk.LEFT,
            wraplength=max(320, content_wrap - 180),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def toggle_details(panel, button) -> None:
        if panel.winfo_ismapped():
            panel.pack_forget()
            button.configure(text="Details")
        else:
            panel.pack(fill=tk.X, pady=(8, 0))
            button.configure(text="Hide details")
        sync_scroll_region()

    if context is not None:
        issue_intro = tk.Frame(scroll_body, bg="#ffffff")
        issue_intro.pack(fill=tk.X, padx=14, pady=(10, 6))
        tk.Label(
            issue_intro,
            text=f"{len(tuple(context.issues or ())[:5])} commit issue(s)",
            bg="#ffffff",
            fg=text_dark,
            font=issue_title_font,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            issue_intro,
            text="Use Details only when you want the evidence.",
            bg="#ffffff",
            fg=text_muted,
            font=subtitle_font,
            anchor="e",
        ).pack(side=tk.RIGHT)
        for index, issue in enumerate(tuple(context.issues or ())[:5], start=1):
            card = tk.Frame(scroll_body, bg="#ffffff", highlightbackground=card_border, highlightthickness=1)
            card.pack(fill=tk.X, padx=14, pady=(0, 8))
            card_header = tk.Frame(card, bg=pale_blue)
            card_header.pack(fill=tk.X)
            tk.Label(
                card_header,
                text=str(index),
                bg=blue,
                fg="#ffffff",
                font=body_bold_font,
                width=3,
                pady=5,
            ).pack(side=tk.LEFT)
            tk.Label(
                card_header,
                text=str(issue.gate or "Commit issue"),
                bg=pale_blue,
                fg=text_dark,
                font=issue_title_font,
                anchor="w",
                padx=10,
                pady=6,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            detail_button = tk.Button(
                card_header,
                text="Details",
                font=button_font,
                bg="#ffffff",
                fg=text_dark,
                activebackground="#eef8ff",
                relief=tk.SOLID,
                bd=1,
                padx=8,
                pady=3,
            )
            detail_button.pack(side=tk.RIGHT, padx=(0, 8))
            tk.Label(
                card_header,
                text="BLOCKING",
                bg="#fff7ed",
                fg="#9a3412",
                font=label_font,
                padx=8,
                pady=4,
            ).pack(side=tk.RIGHT, padx=8)
            body = tk.Frame(card, bg="#ffffff", padx=10, pady=8)
            body.pack(fill=tk.X)
            add_compact_row(
                body,
                "Blocked because",
                getattr(issue, "plain_reason", "") or issue.why,
                color="#c7efff",
            )
            add_compact_row(
                body,
                "Thomas recommends",
                _without_recommendation_prefix(getattr(issue, "recommendation", "")),
                color="#bbf7d0",
            )
            details = tk.Frame(body, bg="#ffffff")
            detail_button.configure(command=lambda panel=details, button=detail_button: toggle_details(panel, button))
            add_field(details, "Why it matters", getattr(issue, "impact", ""), color="#fed7aa", bg="#fffaf5")
            evidence = tuple(getattr(issue, "evidence", ()) or ())[:2]
            if evidence:
                add_field(
                    details, "Evidence Thomas found", " | ".join(_clip(item, 180) for item in evidence), color="#e2e8f0"
                )
            add_field(details, "Next step", getattr(issue, "next_step", ""), color="#bfdbfe", bg="#eff6ff")
    else:
        text = tk.Text(
            scroll_body,
            wrap=tk.WORD,
            font=body_font,
            bg="#ffffff",
            fg="#1d2733",
            padx=12,
            pady=12,
            relief=tk.FLAT,
            height=16,
        )
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", content)
        text.configure(state=tk.DISABLED)

    footer = tk.Frame(main, bg=page_bg)
    footer.pack(fill=tk.X)
    tk.Label(
        footer,
        text="Choose an action:",
        bg=page_bg,
        fg=text_dark,
        font=body_bold_font,
        anchor="w",
    ).pack(side=tk.LEFT, padx=(0, 8))
    tk.Label(
        footer,
        text="Authorize opens Windows sign-in. Recommended action avoids breakglass and asks Thomas to fix the blocker first.",
        bg=page_bg,
        fg=text_muted,
        font=subtitle_font,
        anchor="w",
        justify=tk.LEFT,
        wraplength=max(260, int(width * 0.25)),
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)

    button_bar = tk.Frame(footer, bg=page_bg)
    button_bar.pack(side=tk.RIGHT)

    def add_button(label: str, decision: str, *, bg: str, fg: str, border: int = 0) -> tk.Button:
        button = tk.Button(
            button_bar,
            text=label,
            font=button_font,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief=tk.FLAT if border == 0 else tk.SOLID,
            bd=border,
            padx=8,
            pady=7,
            width=_button_width_chars(label),
            wraplength=max(110, int(width * 0.11)),
            justify=tk.CENTER,
            command=lambda: finish(decision),
        )
        button.pack(side=tk.RIGHT, padx=(8, 0))
        return button

    add_button(cancel_label, "cancel", bg="#ffffff", fg=text_dark, border=1)
    approve = add_button(approve_label, "approve", bg="#fff7ed", fg="#9a3412", border=1)
    if resolution_label and resolution_prompt:
        primary_button = add_button(resolution_label, "action", bg=blue, fg="#ffffff")
    else:
        primary_button = approve

    root.bind("<Escape>", lambda _event: finish("cancel"))
    root.bind("<Return>", lambda _event: finish("approve"))
    primary_button.focus_set()

    root.mainloop()
    return str(result["decision"])


def _show_breakglass_confirmation_dialog(
    *,
    window_title: str,
    main_instruction: str,
    content: str,
    approve_label: str = "Authorize protected change",
    cancel_label: str = "Back out",
    resolution_label: str = "",
    resolution_prompt: str = "",
    context: BreakglassContext | None = None,
) -> str:
    custom_result = _show_custom_breakglass_dialog(
        window_title=window_title,
        main_instruction=main_instruction,
        content=content,
        approve_label=approve_label,
        cancel_label=cancel_label,
        resolution_label=resolution_label,
        resolution_prompt=resolution_prompt,
        context=context,
    )
    if custom_result is not None:
        return custom_result

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
        content + "\n\nPress OK to authorize. Press Cancel to back out.",
        TDCBF_OK_BUTTON | TDCBF_CANCEL_BUTTON,
        _task_dialog_icon(TD_SHIELD_ICON_RESOURCE_ID),
        ctypes.byref(button),
    )
    if hr != 0:
        raise OSError(int(hr), f"TaskDialog failed: {_format_windows_error(hr)}")
    return "approve" if int(button.value) == IDOK else "cancel"


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
    context: BreakglassContext | dict[str, object] | None = None,
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

    # Approval window (sudo-style timestamp) for THIS gate only: if the human
    # recently proved presence and opened a time-boxed window via
    # scripts/breakglass_window.py, honor it without re-prompting. Scoped purely
    # to breakglass auth -- every other gate still runs exactly as before. Any
    # error falls back to the normal Windows sign-in prompt below.
    try:
        window = active_window(_REPO_ROOT, current_user)
    except Exception:  # noqa: BLE001 - never let a window error block the real prompt
        window = None
    if window:
        return BreakglassAuthorization(
            ok=True,
            message=f"authorized by active breakglass approval window (expires {window.get('expires_at')})",
            actor=current_user,
            method="windows-hello-window",
        )

    context_payload = breakglass_context_payload(context) or breakglass_context_from_env(os.environ)
    (
        confirm_title,
        confirm_instruction,
        confirm_content,
        approve_label,
        cancel_label,
        resolution_label,
        resolution_prompt,
    ) = _build_breakglass_decision_copy(
        purpose=str(purpose or "").strip() or "breakglass override",
        agent=str(agent or "").strip() or "unknown-agent",
        ticket=str(ticket or "").strip(),
        reason=str(reason or "").strip(),
        skip_hooks=hooks,
        current_user=current_user,
        context=context_payload,
    )
    try:
        approved = _show_breakglass_confirmation_dialog(
            window_title=confirm_title,
            main_instruction=confirm_instruction,
            content=confirm_content,
            approve_label=approve_label,
            cancel_label=cancel_label,
            resolution_label=resolution_label,
            resolution_prompt=resolution_prompt,
            context=context_payload,
        )
    except OSError as exc:
        return BreakglassAuthorization(
            ok=False,
            message=str(exc),
            actor=current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
        )
    decision = "approve" if approved is True else "cancel" if approved is False else str(approved or "cancel")
    if decision == "action":
        return BreakglassAuthorization(
            ok=False,
            message="recommended action requested instead of breakglass authorization",
            actor=current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
            cancelled=True,
            action_requested=True,
            action_prompt=resolution_prompt or None,
        )
    if decision != "approve":
        return BreakglassAuthorization(
            ok=False,
            message="breakglass approval cancelled before Windows sign-in",
            actor=current_user,
            method=WINDOWS_CREDENTIAL_METHOD,
            cancelled=True,
        )

    prompt_caption, prompt_message = _build_windows_prompt_copy(current_user=current_user)
    result = _run_windows_credential_prompt(
        prompt_caption=prompt_caption,
        prompt_message=prompt_message,
    )
    # If the user turned on the approval window in Settings, this single
    # (AI-prompted) tap also opens a time-boxed window for the duration they
    # chose -- so they aren't asked again for a while. Scoped to this gate only;
    # minting failures never block the authorization that already succeeded.
    if result.ok:
        try:
            window_enabled, window_hours = _breakglass_window_prefs()
            if window_enabled:
                mint_window(_REPO_ROOT, result.actor or current_user, window_hours)
        except Exception:  # noqa: BLE001 - window is a convenience, never fail the auth
            pass
    return result
