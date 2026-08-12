"""Parsed-command danger policy for shell-style tool arguments (CAP-084 L2).

Upgrades destructive-command detection from substring markers to tokenized
command analysis:

- ``shlex`` tokenization in both POSIX and Windows-style (non-POSIX) modes; a
  command is dangerous if either pass flags it. When neither mode can parse a
  line (e.g. unbalanced quotes) the analysis falls back to conservative marker
  matching, so it is never less strict than the legacy substring policy.
- argv[0] basename resolution (paths, quoting tricks, ``.exe``/``.cmd``/
  ``.bat`` suffixes) so ``/bin/rm``, ``"rm" -rf`` and ``r''m`` are caught.
- Command chaining: ``&&``, ``||``, ``;``, ``|``, ``&`` and newlines split the
  command and EVERY segment is evaluated.
- Wrapper unwrapping: ``sudo``/``env``/``nohup``/``xargs``-style prefixes are
  stripped; ``cmd /c``, ``powershell -Command`` and ``bash -c`` payloads are
  re-parsed one nesting level at a time (bounded depth).

This module is stdlib-only and co-located in ``thomas.agent`` with its sole
consumer (``thomas.agent.tool_risk``), so the import edge stays agent->agent
and respects the repo dependency hierarchy in ``thomas/_architecture.py``.
"""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass

__all__ = ["CommandAnalysis", "CommandFinding", "analyze_command"]

_MAX_DEPTH = 3
_PUNCTUATION_CHARS = ";()<>|&"
_SEPARATOR_CHARS = frozenset(";()<>|&")
_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_DELETE_COMMANDS = frozenset({"rm", "del", "erase", "rd", "rmdir", "remove-item", "ri", "unlink", "shred"})
_PERMISSION_COMMANDS = frozenset({"chmod", "chown", "chgrp", "icacls", "takeown"})
_FILESYSTEM_DESTROY_COMMANDS = frozenset({"format", "diskpart", "fdisk", "parted", "mkswap", "wipefs"})
_SHUTDOWN_COMMANDS = frozenset({"shutdown", "reboot", "poweroff", "halt", "stop-computer", "restart-computer"})
_SQL_CLIENTS = frozenset({"mysql", "mariadb", "psql", "sqlite3", "sqlcmd", "mongo", "mongosh"})
_POSIX_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})
_PROTECTED_GIT_REFS = frozenset({"main", "master"})
_PROTECTED_GIT_REF_PREFIXES = ("origin/", "upstream/")
_FORCE_PUSH_FLAGS = frozenset({"-f", "--force", "--force-with-lease", "--mirror", "--prune", "--delete", "-d"})

_SQL_DANGER_RE = re.compile(r"\bdrop\s+(?:database|schema|table)\b|\btruncate\s+table\b", re.IGNORECASE)

# Wrapper commands that merely prefix the real command. Values are the flags
# that consume a following value token (so ``sudo -u root rm ...`` resolves to
# ``rm``, not ``root``).
_WRAPPERS: dict[str, frozenset[str]] = {
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-r", "-t", "--user", "--group"}),
    "doas": frozenset({"-u"}),
    "nohup": frozenset(),
    "setsid": frozenset(),
    "nice": frozenset({"-n"}),
    "ionice": frozenset({"-c", "-n", "-p"}),
    "stdbuf": frozenset(),
    "time": frozenset(),
    "command": frozenset(),
    "exec": frozenset(),
    "busybox": frozenset(),
    "xargs": frozenset({"-n", "-i", "-l", "-p", "-s", "-d", "-a", "-e"}),
    "env": frozenset({"-u", "-s", "-c", "--unset"}),
    "timeout": frozenset({"-k", "-s", "--kill-after", "--signal"}),
}

# Conservative fallback for unparseable input: the legacy substring markers
# plus the aliases this module covers. Never remove a legacy marker from here.
_FALLBACK_MARKERS = (
    "chmod",
    "chown",
    "dd if=",
    "del ",
    "diskpart",
    "drop database",
    "drop table",
    "format",
    "git clean -f",
    "git push",
    "git reset --hard",
    "mkfs",
    "of=/dev/",
    "reboot",
    "remove-item",
    "rm ",
    "rmdir",
    "shutdown",
    "truncate table",
)


@dataclass(frozen=True)
class CommandFinding:
    """One destructive behavior detected in a parsed command segment."""

    rule: str
    segment: str
    reason: str


@dataclass(frozen=True)
class CommandAnalysis:
    """Aggregate danger verdict for one command string."""

    dangerous: bool
    findings: tuple[CommandFinding, ...]
    parsed: bool


def analyze_command(command: str) -> CommandAnalysis:
    """Analyze a command string for destructive behavior via parsed-command policy."""

    findings, parsed = _analyze_text(str(command or ""), depth=0)
    unique: list[CommandFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.rule, finding.segment)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return CommandAnalysis(dangerous=bool(unique), findings=tuple(unique), parsed=parsed)


def _analyze_text(text: str, depth: int) -> tuple[list[CommandFinding], bool]:
    if depth > _MAX_DEPTH or not text.strip():
        return [], True
    findings: list[CommandFinding] = []
    parsed = True
    for line in re.split(r"[\r\n]+", text):
        if not line.strip():
            continue
        line_findings, line_parsed = _analyze_line(line, depth)
        findings.extend(line_findings)
        parsed = parsed and line_parsed
    return findings, parsed


def _analyze_line(line: str, depth: int) -> tuple[list[CommandFinding], bool]:
    findings: list[CommandFinding] = []
    parsed_any = False
    for posix in (True, False):
        tokens = _tokenize(line, posix)
        if tokens is None:
            continue
        parsed_any = True
        for segment in _split_segments(tokens):
            findings.extend(_analyze_segment(segment, depth))
    if not parsed_any:
        return _marker_fallback(line), False
    return findings, True


def _tokenize(line: str, posix: bool) -> list[str] | None:
    lexer = shlex.shlex(line, posix=posix, punctuation_chars=_PUNCTUATION_CHARS)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quotes or similar; caller falls back to marker matching.
        return None


def _split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in _SEPARATOR_CHARS for char in token):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _analyze_segment(tokens: list[str], depth: int) -> list[CommandFinding]:
    findings: list[CommandFinding] = []
    for _ in range(_MAX_DEPTH + 3):
        tokens = _skip_assignments(tokens)
        if not tokens:
            return findings
        executable = _resolve_executable(tokens[0])
        if executable in _WRAPPERS:
            tokens = _skip_wrapper_args(executable, tokens[1:])
            continue
        if executable == "cmd":
            payload = _extract_cmd_payload(tokens[1:])
            if payload:
                findings.extend(_analyze_text(payload, depth + 1)[0])
            return findings
        if executable in {"powershell", "pwsh"}:
            payload = _extract_powershell_payload(tokens[1:])
            if payload:
                findings.extend(_analyze_text(payload, depth + 1)[0])
            return findings
        if executable in _POSIX_SHELLS:
            payload = _extract_shell_payload(tokens[1:])
            if payload:
                findings.extend(_analyze_text(payload, depth + 1)[0])
            return findings
        break
    findings.extend(_evaluate_argv(tokens))
    return findings


def _evaluate_argv(tokens: list[str]) -> list[CommandFinding]:
    executable = _resolve_executable(tokens[0])
    args = [_strip_quotes(token) for token in tokens[1:]]
    lowered = [arg.lower() for arg in args]
    segment = " ".join([_strip_quotes(tokens[0]), *args]).strip()

    if executable in _DELETE_COMMANDS:
        return [CommandFinding("delete_command", segment, f"'{executable}' deletes files or directories")]
    if executable.startswith("mkfs") or executable in _FILESYSTEM_DESTROY_COMMANDS:
        return [CommandFinding("filesystem_destroy", segment, f"'{executable}' destroys or reformats storage")]
    if executable == "dd" and any(arg.startswith(("of=/dev/", "of=\\\\.\\")) for arg in lowered):
        return [CommandFinding("raw_device_write", segment, "'dd' writes directly to a raw device")]
    if executable in _SHUTDOWN_COMMANDS:
        return [CommandFinding("system_shutdown", segment, f"'{executable}' stops or restarts the host")]
    if executable in _PERMISSION_COMMANDS:
        return [CommandFinding("permission_change", segment, f"'{executable}' changes ownership or permissions")]
    if executable == "git":
        return _evaluate_git(segment, lowered)
    if executable in _SQL_CLIENTS:
        if _SQL_DANGER_RE.search(" ".join(args)):
            return [CommandFinding("sql_destructive", segment, f"'{executable}' payload drops or truncates SQL data")]
        return []
    if executable in {"drop", "truncate"} and lowered:
        statement = f"{executable} {' '.join(lowered)}"
        if _SQL_DANGER_RE.search(statement):
            return [CommandFinding("sql_destructive", segment, "statement drops or truncates SQL data")]
    return []


def _evaluate_git(segment: str, lowered_args: list[str]) -> list[CommandFinding]:
    index = 0
    while index < len(lowered_args):
        token = lowered_args[index]
        if token == "-c":  # covers -c and -C (lowered), both consume a value
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        break
    if index >= len(lowered_args):
        return []
    subcommand = lowered_args[index]
    rest = lowered_args[index + 1 :]

    if subcommand == "clean" and any(
        token == "--force" or (token.startswith("-") and not token.startswith("--") and "f" in token) for token in rest
    ):
        return [CommandFinding("git_clean_force", segment, "'git clean' with force flag deletes untracked files")]
    if subcommand == "reset" and "--hard" in rest:
        refs = [token for token in rest if not token.startswith("-")]
        if any(ref in _PROTECTED_GIT_REFS or ref.startswith(_PROTECTED_GIT_REF_PREFIXES) for ref in refs):
            return [
                CommandFinding("git_reset_hard_protected_ref", segment, "'git reset --hard' targets a protected ref")
            ]
    if subcommand == "push":
        forced = [token for token in rest if token in _FORCE_PUSH_FLAGS]
        detail = f" with {forced[0]}" if forced else ""
        return [CommandFinding("git_push", segment, f"'git push'{detail} mutates remote refs")]
    return []


def _skip_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and _ASSIGNMENT_RE.match(_strip_quotes(tokens[index])):
        index += 1
    return tokens[index:]


def _skip_wrapper_args(executable: str, tokens: list[str]) -> list[str]:
    valued_flags = _WRAPPERS.get(executable, frozenset())
    index = 0
    while index < len(tokens):
        token = _strip_quotes(tokens[index]).lower()
        if token in valued_flags:
            index += 2
            continue
        if token.startswith("-") and token != "-":
            index += 1
            continue
        if executable == "env" and _ASSIGNMENT_RE.match(token):
            index += 1
            continue
        break
    if executable == "timeout" and index < len(tokens):
        index += 1  # positional duration argument
    return tokens[index:]


def _extract_cmd_payload(tokens: list[str]) -> str | None:
    for index, token in enumerate(tokens):
        if _strip_quotes(token).lower() in {"/c", "/k", "-c"}:
            payload = " ".join(_strip_quotes(item) for item in tokens[index + 1 :]).strip()
            return payload or None
    return None


def _extract_powershell_payload(tokens: list[str]) -> str | None:
    for index, token in enumerate(tokens):
        raw = _strip_quotes(token)
        if not raw:
            continue
        if raw[0] not in "-/":
            # Positional command/script: analyze everything from here on.
            payload = " ".join(_strip_quotes(item) for item in tokens[index:]).strip()
            return payload or None
        flag = raw.lstrip("-/").lower()
        if flag and "command".startswith(flag):
            payload = " ".join(_strip_quotes(item) for item in tokens[index + 1 :]).strip()
            return payload or None
        if flag in {"encodedcommand", "ec", "enc", "e"} and index + 1 < len(tokens):
            return _decode_powershell_encoded(_strip_quotes(tokens[index + 1]))
    return None


def _decode_powershell_encoded(token: str) -> str | None:
    try:
        return base64.b64decode(token, validate=True).decode("utf-16-le")
    except (ValueError, UnicodeDecodeError):
        return None


def _extract_shell_payload(tokens: list[str]) -> str | None:
    for index, token in enumerate(tokens):
        raw = _strip_quotes(token)
        if not raw.startswith("-"):
            return None  # script-file execution; nothing quoted to re-parse
        if not raw.startswith("--") and "c" in raw[1:].lower():
            if index + 1 < len(tokens):
                return _strip_quotes(tokens[index + 1]) or None
            return None
    return None


def _marker_fallback(line: str) -> list[CommandFinding]:
    lowered = line.lower()
    return [
        CommandFinding(
            "marker_fallback",
            line.strip(),
            f"unparseable command contains destructive marker '{marker.strip()}'",
        )
        for marker in _FALLBACK_MARKERS
        if marker in lowered
    ]


def _resolve_executable(token: str) -> str:
    text = str(token).replace('"', "").replace("'", "").strip()
    text = text.replace("\\", "/").rstrip("/")
    base = text.rsplit("/", 1)[-1].lower()
    for suffix in _EXECUTABLE_SUFFIXES:
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _strip_quotes(token: str) -> str:
    text = str(token).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text
