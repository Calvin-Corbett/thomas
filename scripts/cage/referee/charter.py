"""The Charter: which derived changes may skip the sign-in, decided on the tree diff and nothing else.

The first referee binary has exactly one class, D: add-only ``changelog.d/<name>.md`` fragments. There is no code
path for any other class. A pinned Charter can only lower the caps; a row that names another class is refused
(``CharterRefused``), which lands nothing. ``decide`` takes the diff derived from git (``derive.Derived``) and the
Charter. It never sees patch text or any ``submission.json`` field. An answer of ``regular`` is a demotion, not a
refusal: the work goes to the ordinary sign-in unchanged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING

from .fragment import content_problems

if TYPE_CHECKING:
    from .derive import Derived

ENABLED_CLASSES = ("D",)
CLASS_D_PATH = re.compile(r"changelog\.d/[a-z0-9]+(?:-[a-z0-9]+)+\.md")
MAX_NAME = 100


@dataclass(frozen=True)
class Caps:
    files: int = 10
    lines: int = 400
    bytes: int = 24 * 1024  # across the whole change
    file_bytes: int = 4096
    line_bytes: int = 160  # the longest line, counted in bytes


@dataclass(frozen=True)
class Charter:
    caps: Caps = Caps()
    closure: frozenset[str] = frozenset()  # the owner-process import closure, derived by the caller from the base tree


@dataclass(frozen=True)
class Decision:
    lane: str  # "express" or "regular"
    code: str  # empty for express; otherwise a short code for the ledger
    detail: str = ""
    files: tuple[str, ...] = ()


class CharterRefused(ValueError):
    """The pinned Charter asks for something this binary cannot do."""


def parse_pin(raw: bytes | str | dict) -> Charter:
    """The Charter a pin file says. Other classes and wider caps are refused, never ignored."""
    data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    if not isinstance(data, dict) or set(data) - {"classes", "caps"}:
        raise CharterRefused("a Charter holds only classes and caps")
    if list(data.get("classes", ENABLED_CLASSES)) != list(ENABLED_CLASSES):
        raise CharterRefused("this referee binary has no code for any class but D")
    caps, limits = Caps(), data.get("caps", {})
    if not isinstance(limits, dict) or set(limits) - {f.name for f in fields(Caps)}:
        raise CharterRefused("unknown cap")
    for name, value in limits.items():
        if type(value) is not int or not 0 < value <= getattr(caps, name):
            raise CharterRefused(f"cap {name} may only be lowered")
    return Charter(replace(caps, **limits))


_NEVER = (  # (code, pattern searched in the lower-case path): the spec's never-eligible list, in coarse groups
    ("referee_or_cage", r"^(scripts/(cage|crew|forge)|docs/ops|\.github)/"),
    (
        "approval_or_checks",
        r"^thomas/(server/(express|precard|proof|ratchet|routes/express)|core/kernel|tools/(owner_desk|filesystem))"
        r"|(^|/)(green_[^/]*|thomas_project[^/]*|self_change_status|dial_elevation[^/]*|windows_auth|native_auth"
        r"|trusted_card|cage_shell|setting_request|chat_inline_actions|owner_wait|protection_tier"
        r"|commit_integrity|express_switch|self_edit_controls)\.(py|js)$",
    ),
    (
        "config_or_release",
        r"(^|/)((agent_safety|pyproject|thomas|thomas\.prod)\.toml|(agents|claude|guardrails|changelog)\.md"
        r"|\.pre-commit-config\.yaml|requirements-lock\.txt|version|run-ui\.(cmd|ps1)|thomas\.vbs)$",
    ),
    ("runtime_or_binary", r"^runtime/|(^|/)__pycache__/|\.(pyc|pyo|pyd|dll|exe|so|pth)$"),
)
AUTOEXEC = {
    "conftest.py",
    "sitecustomize.py",
    "usercustomize.py",
    "__main__.py",
    "setup.py",
    "noxfile.py",
    "__init__.py",
}


def path_problem(path: str, closure: frozenset[str] = frozenset()) -> str:
    """The code for why ``path`` is never eligible, or an empty string. Strict: unusual spellings are refused."""
    segments = path.split("/")
    if (
        not path.isascii()
        or not 0 < len(path) <= 200
        or any(ord(c) < 0x20 or c in '\\:*?"<>|' for c in path)
        or any(s in ("", ".", "..") or s != s.rstrip(" .") for s in segments)
    ):
        return "path_spelling"
    low = path.casefold()
    if any(s.startswith((".git", "git~")) for s in low.split("/")):
        return "referee_or_cage"
    if low in {c.casefold() for c in closure}:
        return "owner_process_closure"
    for code, pattern in _NEVER:
        if re.search(pattern, low):
            return code
    return "autoexec_name" if segments[-1].casefold() in AUTOEXEC else ""


def measure(data: bytes) -> tuple[int, int, int]:
    """Bytes, lines and the longest line in bytes. Everything is counted in bytes, never characters."""
    lines = data.split(b"\n")
    return len(data), len(lines) - (1 if lines[-1] == b"" else 0), max(map(len, lines))


def _demote(code: str, detail: str = "") -> Decision:
    return Decision("regular", code, detail)


_STATUS_CODES = {"D": "deletion", "R": "rename", "C": "copy", "M": "modified_existing", "T": "type_change"}
_MODE_CODES = {"160000": "gitlink", "120000": "symlink"}


def decide(derived: Derived, charter: Charter) -> Decision:
    """Express only if every change is a new, plain, well-formed class D fragment and every cap holds."""
    changes, caps = derived.changes, charter.caps
    if not changes:
        return _demote("empty_change")
    if len(changes) > caps.files:
        return _demote("too_many_files", f"{len(changes)} files")
    for change in changes:
        if problem := path_problem(change.path, charter.closure):
            return _demote(problem, change.path)
        if change.status != "A":
            return _demote(_STATUS_CODES.get(change.status, "status"), change.path)
        if change.new_mode != "100644":
            return _demote(_MODE_CODES.get(change.new_mode, "mode"), change.path)
        if not CLASS_D_PATH.fullmatch(change.path) or len(change.path) > MAX_NAME:
            return _demote("no_class", change.path)
    paths = [c.path for c in changes]
    folded = [p.casefold() for p in paths] + [f"changelog.d/{n}".casefold() for n in derived.existing_names]
    if len(set(folded)) != len(folded):
        return _demote("casefold_collision")
    total_bytes = total_lines = 0
    for change in changes:
        size = derived.sizes.get(change.new_sha, -1)
        if size < 0 or size > caps.file_bytes or change.new_sha not in derived.blobs:
            return _demote("file_too_large" if size > caps.file_bytes else "unreadable", change.path)
        data = derived.blobs[change.new_sha]
        if b"\x00" in data:
            return _demote("binary", change.path)
        nbytes, nlines, longest = measure(data)
        total_bytes, total_lines = total_bytes + nbytes, total_lines + nlines
        if longest > caps.line_bytes:
            return _demote("line_too_long", change.path)
        if problems := content_problems(change.path.rsplit("/", 1)[-1], data):
            return _demote("fragment_" + problems[0], change.path)
    if total_bytes > caps.bytes:
        return _demote("change_too_large", f"{total_bytes} bytes")
    if total_lines > caps.lines:
        return _demote("too_many_lines", f"{total_lines} lines")
    return Decision("express", "", "", tuple(sorted(paths)))
