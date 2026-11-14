"""What a finish-check (or task-named) command is allowed to do.

Split out of ``acceptance_contract.py`` (pinned at 800 lines) so this policy has room of its own. Two
rounds of live fixes are folded in:

- Round 1 (task-5b-fix-round-1.md): five real cmd.exe ways to write outside the workspace survived the
  first narrowing -- an unanchored null-device check Windows path collapse defeated, single quotes that
  do not quote at all in cmd.exe, a bare `=` before `>` read as safe everywhere instead of only inside
  quotes, a caret-escaped quote (`^"`) that is not a real delimiter, and a shell re-entered inside a
  quoted argument. Fixed: the null-device exemption only applies to the whole target; quoting is
  OS-aware (Windows: only `"..."`, and `^"` is never a delimiter); and re-entering `cmd`, `sh`, `bash`,
  `powershell`, or `pwsh` inside the command line is refused outright, regardless of quoting.
- Round 2 (task-5b-fix-round-2.md): round 1's own new verbs were matched against the RAW command text, so
  Python's `del d[1]` and `'{}'.format(1)` quoted inside a `-c` script were refused even though the shell
  never sees them. Destructive verbs are now matched only against the quote-stripped text; shell re-entry
  and piping into a shell stay matched against the raw text, since a re-entered shell's own quoted payload
  is exactly what must not be stripped away first.
"""

from __future__ import annotations

import os
import re
import shlex

# Destructive verbs -- checked against the QUOTE-STRIPPED text (round 2): `del`/`format`/etc. quoted inside
# a script argument (Python's `del d[1]`, `.format(...)`) are not commands any shell will ever run.
_DENY_VERB_RE = re.compile(
    r"\b(?:rm|sudo|curl|wget|mkfs|dd|chmod|chown|kill|shutdown|reboot|del|erase|rd|rmdir|format|remove-item|rimraf)\b",
    re.I,
)
# Shell re-entry and piping into a shell -- checked against the RAW text: a re-entered shell's own quoted
# payload (`cmd /c "...>..."`, `sh -c '...>...'`) is exactly what must not be stripped away first.
_DENY_RAW_RE = re.compile(
    r"\bcmd(?:\.exe)?\s+/c\b|\bsh\s+-c\b|\bbash\s+-c\b|\bpowershell(?:\.exe)?\s+(?:-c|-Command)\b|\bpwsh\b"
    r"|\|\s*(?:sh|bash|zsh|cmd|powershell|pwsh|iex|invoke-expression)\b",
    re.I,
)
# On Windows only `"..."` quotes (cmd.exe's `^"` is an escaped literal, never a delimiter); elsewhere, POSIX quoting.
_QUOTED_SPAN_POSIX_RE = re.compile(r'"[^"]*"|\'[^\']*\'')
_QUOTED_SPAN_WINDOWS_RE = re.compile(r'(?<!\^)"[^"]*?(?<!\^)"')
# The null device only discards a command's own output as the WHOLE target: Windows collapses `nul\..\..` to `..`.
_UNSAFE_REDIRECT_RE = re.compile(r">(?!&\d)(?!\s*(?:nul|/dev/null)(?=\s|$|[&|;]))", re.I)


def deny_command(command: str) -> bool:
    """A shell re-entry or a pipe into a shell (raw text), a destructive verb (quote-stripped text), or a
    real redirection (quote-stripped text) -- never one quoted inside a script argument."""
    text = str(command or "")
    if _DENY_RAW_RE.search(text):
        return True
    quoted = _QUOTED_SPAN_WINDOWS_RE if os.name == "nt" else _QUOTED_SPAN_POSIX_RE
    stripped = quoted.sub("", text)
    return bool(_DENY_VERB_RE.search(stripped) or _UNSAFE_REDIRECT_RE.search(stripped))


# On 2026-10-07 all four Thomas Build runs ended their reply with `VERIFY: python -m pytest`, the whole ~13k-test suite,
# and held at the finish for about 3 hours. A whole-suite pytest still runs (in a small project it passes in seconds,
# and refusing it would cost the team a whole extra pass); when one runs out of time, the check says what to run instead.
WHOLE_SUITE_GUIDANCE = (
    "it runs the whole test suite (pytest with no test named), which did not finish inside the check's time limit: "
    "name the test files this work changed, e.g. `python -m pytest tests/test_<name>.py`, or select tests with -k"
)
NARROW_GUIDANCE = (
    "this pytest run did not finish inside the check's time limit: narrow it to the tests this work changed"
)
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;&|]")
_REDIRECTION_RE = re.compile(r"\d?>>?\s*(?:&\d|[^\s&|;]+)|<\s*[^\s&|;]+")
_PYTHON_HEAD_RE = re.compile(r"python(?:3(?:\.\d+)?)?|py")
# Options whose value is a separate word, so the value is not read as a test path (`-p no:cacheprovider`).
_PYTEST_VALUE_OPTIONS = frozenset(
    {"-p", "-c", "-o", "-W", "-m", "-n", "-r", "--tb", "--maxfail", "--rootdir", "--basetemp", "--durations"}
)


def _pytest_args(words: list[str]) -> list[str] | None:
    """The words after `pytest` when these words run pytest, else None."""
    if not words:
        return None
    head = words[0].strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if head in {"pytest", "py.test"}:
        return words[1:]
    if _PYTHON_HEAD_RE.fullmatch(head) and words[1:3] == ["-m", "pytest"]:
        return words[3:]
    return None


def _names_tests(args: list[str]) -> bool:
    value_next = False
    for arg in args:
        if value_next:
            value_next = False
        elif arg.startswith(("-k", "--keyword")):
            return True
        elif arg in _PYTEST_VALUE_OPTIONS:
            value_next = True
        elif not arg.startswith("-") and arg.strip("\"'") not in {".", "./", ".\\"}:
            return True
    return False


def _pytest_runs(command: str) -> list[list[str]]:
    """The arguments of every pytest run in the command, one list per part of a chained command."""
    runs: list[list[str]] = []
    for segment in _SEGMENT_SPLIT_RE.split(_REDIRECTION_RE.sub(" ", str(command or ""))):
        try:
            words = shlex.split(segment, posix=os.name != "nt")
        except ValueError:
            words = segment.split()
        args = _pytest_args(words)
        if args is not None:
            runs.append(args)
    return runs


def whole_suite_pytest(command: str) -> bool:
    """True when some part of the command runs pytest with no test path, file, node id or -k."""
    return any(not _names_tests(args) for args in _pytest_runs(command))


def pytest_timeout_guidance(command: str) -> str:
    """What to run instead when this command ran out of time: '' unless it runs pytest."""
    if not _pytest_runs(command):
        return ""
    return WHOLE_SUITE_GUIDANCE if whole_suite_pytest(command) else NARROW_GUIDANCE


__all__ = [
    "NARROW_GUIDANCE",
    "WHOLE_SUITE_GUIDANCE",
    "_DENY_RAW_RE",
    "_DENY_VERB_RE",
    "_QUOTED_SPAN_POSIX_RE",
    "_QUOTED_SPAN_WINDOWS_RE",
    "_UNSAFE_REDIRECT_RE",
    "deny_command",
    "pytest_timeout_guidance",
    "whole_suite_pytest",
]
