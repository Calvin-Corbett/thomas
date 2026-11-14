"""Thomas's approval cards: the only words a Windows PIN prompt may carry.

Owner direction, 2026-09-22: "if you got hacked, it could just literally say
whatever ... the card wants to say. So the solution is we make sure all the big
serious things have encrypted um, stuff in them. So the only card you can use is
the one that says what we want it to say."

Thomas never writes the words on an approval prompt. He names a card kind and
supplies its details; the wording is the template below, and the details are
computed by trusted code from the real bytes -- never passed through from the
model. This file is pinned: its SHA-256 lives in C:\\ProgramData\\ThomasPins,
writable only by Administrators, and every PIN flow refuses when the two differ
(thomas/tools/trusted_card.py). Changing a card's wording therefore takes a UAC
prompt, not a file write.

The pairing code is shown on both the chat card and the Windows dialog and
changes whenever the content does. Honest scope: the dialog is the source of
truth, and the code is how you match it to the card you expected at a glance --
it is not a secret, and it is not what stops a hacked Thomas. The dialog's
wording is.

Standard library only, and ASCII only: the commit-master loads this file too,
and its pin is a hash computed both in PowerShell and in Python.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CardKind:
    title: str
    body: str
    fields: tuple[str, ...]
    limit: int = 200  # characters per detail, after it is made one line
    limits: tuple[tuple[str, int], ...] = ()  # details with a cap of their own, and that cap

    def cap(self, name: str) -> int:
        """How long the detail *name* may be, after it is made one line."""
        return dict(self.limits).get(name, self.limit)


KINDS: dict[str, CardKind] = {
    "protected_write": CardKind(
        title="Let Thomas change one of his protected files",
        body="Change {path}: {diffstat}",
        fields=("path", "diffstat"),
    ),
    # The line break is the template's, never a detail's. 600 for the files: a 200-character detail hid two of a
    # change's six files (self-thomas-ea1c748556b8, 2026-10-08); name_files() fills it without cutting a name. 20 for
    # the count, a number: the owner desk renders this kind from details the caged server writes and measures nothing,
    # and a 600-character count as well made a message of 1,357 characters, past the 1,024 Windows shows (DIALOG_LIMIT).
    "promote_batch": CardKind(
        title="Put Thomas's changes into the running Thomas",
        body="Apply {count} change(s): {files}\nCancel declines this change.",
        fields=("count", "files"),
        limits=(("count", 20), ("files", 600)),
    ),
    "promote_dangerous": CardKind(
        title="Change a file that guards Thomas",
        body=(
            "Change {category} file {path}: {diffstat}\n"
            "Cancel leaves this file out; any other file in its change is still asked."
        ),
        fields=("category", "path", "diffstat"),
    ),
    "raise_dial": CardKind(
        title="Raise one of Thomas's own limits",
        body="Let Thomas raise {dial} to {value}",
        fields=("dial", "value"),
    ),
    "guarded_tool": CardKind(
        title="Let Thomas run a sensitive tool",
        body="Run {tool} with exactly: {args}",
        fields=("tool", "args"),
    ),
    # Part 4 (docs/superpowers/specs/2026-10-12-praxis-production-line-design.md, section 8): your window. Only the
    # promoter's own window loop asks these (scripts/cage/window_loop.py); the owner's desk never does. {cap} is one of
    # this file's own words (window_cap_words); {ends} names the day and time, or the date for a window of more than
    # six days, since a window can last until you turn it off.
    "open_window": CardKind(
        title="Let Thomas land checked changes while you are here",
        body=(
            "Open a window of {minutes} minute(s), until {ends}. {waiting} change(s) are waiting. Until then, a change "
            "the checker passed and a second look found safe lands without another card, {cap}. Locking "
            "your PC pauses it; 15 minutes locked or idle ends it. Cancel opens nothing."
        ),
        fields=("minutes", "ends", "waiting", "cap"),
        limits=(("minutes", 6), ("ends", 14), ("waiting", 4), ("cap", 25)),
    ),
    # The same window, opened to keep landing while you are away (your decision, 2026-10-22). Only on a PC where the
    # elevated setup turned that on (window.away in the pin folder), and only when you ask for it when you open one.
    "open_window_away": CardKind(
        title="Let Thomas land checked changes while you are away",
        body=(
            "Open a window of {minutes} minute(s), until {ends}. {waiting} change(s) are waiting. Until then, a change "
            "the checker passed and a second look found safe lands without another card, {cap}, and it KEEPS LANDING "
            "while your PC is locked or you are away. It ends at that time, at that number, with the off switch, or "
            "when the check after a landing fails. Cancel opens nothing."
        ),
        fields=("minutes", "ends", "waiting", "cap"),
        limits=(("minutes", 6), ("ends", 14), ("waiting", 4), ("cap", 25)),
    ),
    "undo_change": CardKind(
        title="Undo one of Thomas's changes",
        body="Undo {sid}: {files}. The checker passed the undo on today's Thomas. Cancel undoes nothing.",
        fields=("sid", "files"),
        limits=(("sid", 85), ("files", 600)),
    ),
    "revert_change": CardKind(
        title="Undo a change that broke Thomas after it landed",
        body=(
            "After {sid} landed, the check found: {failed}. Landed in the same window: {batch}. Signing in undoes "
            "{sid}; the checker passed the undo. Cancel keeps it, and the window stays closed."
        ),
        fields=("sid", "failed", "batch"),
        limits=(("sid", 85), ("failed", 200), ("batch", 200)),
    ),
}

# The window's limits (spec section 8.4), pinned with the cards: changing one takes your own commit and a re-pin.
# You choose each window's length when you open it, up to the ceiling (your decision, 2026-10-27: until you turn it
# off, which is a year at most; it was 24 hours), and its number of landings: a number, or none. These are the
# defaults when you choose nothing.
WINDOW_CEILING_MINUTES = 525600
WINDOW_DEFAULT_MINUTES = 120
WINDOW_MAX_LANDINGS = 25
WINDOW_IDLE_MINUTES = 15
WINDOW_CAP_WORDS = "at most {n}"
WINDOW_NO_CAP_WORDS = "with no limit on how many"


def window_cap_words(max_landings: int | None) -> str:
    """The open-window card's words for a window's number of landings: a number, or none."""
    if max_landings is None:
        return WINDOW_NO_CAP_WORDS
    if type(max_landings) is not int or max_landings < 1:
        raise ValueError("a window lands at least one change, or has no limit")
    return WINDOW_CAP_WORDS.format(n=max_landings)


# No 0/O, 1/I/L or U: a code you read aloud should not have a twin.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
_DETAIL_LIMIT = 200

DANGER_GATES = "gates and enforcement"
DANGER_CAGE = "the cage and approvals"
DANGER_NETWORK = "new network reach"

# Policy C: these never ride a scope grant; each change gets its own PIN.
_CAGE_AND_APPROVAL = (
    "scripts/cage/",
    "thomas/tools/cage_shell.py",
    "thomas/tools/shell.py",
    "thomas/tools/windows_auth.py",
    "thomas/tools/native_auth.py",
    "thomas/tools/runtime_protection_auth.py",
    "thomas/tools/protected_write_card.py",
    "thomas/tools/trusted_card.py",
    "thomas/core/protected_write_grants.py",
    "thomas/core/user_questions.py",
    "thomas/server/dial_elevation.py",
    "thomas/server/routes/user_questions_routes.py",
)
_ENFORCEMENT_KEYS = ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts")
# A change that ADDS a way to reach the network: a client import or a URL, read on each added line (_added).
_NETWORK_REACH = re.compile(
    r"\bimport\s+(?:socket|requests|httpx|urllib|urllib3|aiohttp|websocket|websockets|paramiko|ftplib|smtplib)\b"
    r"|\bfrom\s+(?:socket|requests|httpx|urllib|urllib3|aiohttp|websocket|websockets|paramiko|ftplib|smtplib)\b"
    r"|(?i:https?://)"
)
# A URL whose host can never be on the internet is not reach: this machine, and the names RFC 2606 and RFC 6761 keep
# for examples and tests. Test fixtures use them constantly (2026-10-08: every self-fix card that day asked a second
# time for one). The host has to end right there ("x.test.elsewhere" is reach), and no "@" may follow before the
# path starts, since what comes before an "@" is a user name and the real host is after it ("localhost;@elsewhere").
# A port may be a number or filled in by the code ({port}, ${port}, %d, or a string the code appends to).
_UNREACHABLE_URL = re.compile(
    r"https?://(?:localhost|127(?:\.\d{1,3}){3}|\[::1\]"
    r"|(?:[a-z0-9-]+\.)+(?:example|invalid|test|localhost)|(?:[a-z0-9-]+\.)*example\.(?:com|net|org))"
    r"(?::(?:\d{1,5}|\{[a-z_][a-z0-9_.]*\}|\$\{[a-z_][a-z0-9_.]*\}|%[ds])?)?"
    r"(?=[/?#\"'`\s)\]}>,;]|$)(?![^/?#]*@)",
    re.IGNORECASE | re.ASCII,
)
# In a file under tests/, "from aiohttp import web" and aiohttp's helpers that run entirely inside the test process are
# not reach. On 2026-10-09 a new test (tests/test_a_question_takes_only_the_answers_it_offered.py) asked a second time
# for its aiohttp imports. Only a line that is exactly such an import, and only these names. aiohttp.test_utils also
# hands out TestClient (it carries a live ClientSession), TestServer, RawTestServer, BaseTestServer and AioHTTPTestCase
# (they can listen beyond this machine), ClientSession, socket and aiohttp itself: all still reach.
_IN_PROCESS = (
    "(?:loop_context|make_mocked_coro|make_mocked_request|setup_test_loop|teardown_test_loop|unittest_run_loop"
    "|unused_port)"
)
_IN_PROCESS_IMPORT = re.compile(
    r"[ \t]*from[ \t]+aiohttp[ \t]+import[ \t]+web[ \t]*\r?"
    rf"|[ \t]*from[ \t]+aiohttp\.test_utils[ \t]+import[ \t]+{_IN_PROCESS}(?:[ \t]*,[ \t]*{_IN_PROCESS})*[ \t]*\r?"
)


def _one_line(value: object, limit: int = _DETAIL_LIMIT) -> str:
    """A detail is data: one line of printable ASCII, capped, so it cannot forge a second paragraph or turn the
    text around it (a right-to-left mark is shown as '?')."""
    flat = "".join(ch if " " <= ch <= "~" else "?" for ch in " ".join(str(value).split()))
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def render(kind: str, details: Mapping[str, object]) -> tuple[str, str]:
    """The title and body for *kind*, filled only from *details*.

    An unknown kind, or details that do not match the template's fields exactly,
    is refused: a card that does not fit its template is not a card this
    catalogue issues. List cards (LIST_KINDS) are never rendered here, so the
    owner's desk, which renders what the server names, cannot show one.
    """
    spec = KINDS.get(kind)
    if spec is None:
        raise KeyError(f"no card kind {kind!r}")
    if set(details) != set(spec.fields):
        raise ValueError(f"card {kind!r} takes {sorted(spec.fields)}, got {sorted(details)}")
    return spec.title, spec.body.format(**{name: _one_line(details[name], spec.cap(name)) for name in spec.fields})


# The whole Windows message, title to pairing code, is at most this long (CREDUI_MAX_MESSAGE_LENGTH, wincred.h);
# Windows cuts the rest without a word. The promoter measures every card against it, the retry line included.
DIALOG_LIMIT = 1024
# What the same card says above its pairing code when Windows did not accept the last sign-in. That answer is never
# yours: only Cancel is.
RETRY_NOTE = "Your last answer was not accepted. Try again, or press Cancel."


# -- one sign-in for several changes (your decision, 2026-10-08: "Yes, batch cards") ------------------------------- #
@dataclass(frozen=True)
class ListCardKind:
    """A card that lists changes, one line each. Every word is here; the promoter supplies only paths and line
    counts computed from the real trees, and this file ranks, fits and words them."""

    title: str
    head: str  # {count}
    row: str  # {n} {size} {count} {named}
    some_counted: str  # {named} {k}
    all_counted: str  # {k}
    min_rows: int
    max_rows: int
    row_soft: int  # tests and notes are named only while the line stays this short; nothing else ever stops
    body_limit: int  # title + body + RETRY_NOTE + the pairing-code line stay inside DIALOG_LIMIT


LIST_KINDS: dict[str, ListCardKind] = {
    "promote_several": ListCardKind(
        title="Put several of Thomas's changes into the running Thomas",
        head="Signing in puts these {count} changes into Thomas together. Cancel puts none in and asks about each alone:",
        row="{n}. {size} in {count} file(s): {named}",
        some_counted="{named} and {k} more test or note file(s)",
        all_counted="{k} test or note file(s)",
        min_rows=2,
        max_rows=5,
        row_soft=150,
        body_limit=820,
    ),
}

# A named path: printable ASCII with no space, quote or backslash (git prints those quoted), at most 200 long, and no
# "~", which spells an 8.3 short name on C: (thomas/server/TOOL_M~1 is thomas/server/tool_manifests).
_LISTED_PATH = re.compile(r"[!#-\[\]-}]{1,200}")
_RUNS_AS_YOU = (".ps1", ".cmd", ".bat", ".vbs", ".sh")
_RUNS_AS_YOU_NAMES = ("conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")


def file_class(path: str, status: str) -> int:
    """0 deleted, 1 runs outside Thomas as you, 2 code, 3 a test, 4 a note. A card names the low classes first.

    Under tests/, a helper module runs as you whenever the tests do; a data file (a fixture, a sample) runs nothing,
    and ranks with the tests -- thirty fixtures once pushed a code change off the card. A pytest config file runs as
    you at any depth: pytest reads the one nearest the files it is given, and its addopts can load a plugin. A .py
    file is code wherever it sits, docs/ and changelog.d/ included."""
    name = path.rsplit("/", 1)[-1]
    if status == "D":
        return 0
    if "/" not in path or path.startswith(".github/") or name in _RUNS_AS_YOU_NAMES or name.endswith(_RUNS_AS_YOU):
        return 1
    if path.startswith("tests/"):
        return 3 if name.startswith("test_") or not name.endswith(".py") else 1
    if path.startswith(("changelog.d/", "docs/")):
        return 2 if name.endswith(".py") else 4
    return 2


_File = tuple[str, str, int | None, int | None]


def _files(member: object) -> list[_File]:
    """A change's files, checked: {"files": [[path, "A"|"M"|"D", added, deleted], ...]}, None counts for binary."""
    if not isinstance(member, Mapping) or set(member) != {"files"} or not isinstance(member["files"], list):
        raise ValueError("a change is {'files': [[path, status, added, deleted], ...]}")
    out: list[_File] = []
    for item in member["files"]:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            raise ValueError("a named file is [path, status, added, deleted]")
        path, status, added, deleted = item
        if not isinstance(path, str) or not _LISTED_PATH.fullmatch(path) or status not in ("A", "M", "D"):
            raise ValueError("a named path is plain printable ASCII, at most 200 long; its status A, M or D")
        counts = (added, deleted)
        if counts != (None, None) and not all(type(n) is int and n >= 0 for n in counts):
            raise ValueError("a named size is two whole numbers, or two Nones for a binary file")
        out.append((path, status, added, deleted))
    if not out:
        raise ValueError("a change changes at least one file")
    return out


def _rank(f: _File) -> tuple[int, int, str]:
    return file_class(f[0], f[1]), -((f[2] or 0) + (f[3] or 0)), f[0]


def file_text(path: str, status: str, added: int | None, deleted: int | None) -> str:
    if added is None:
        return f"{path} ({'new, ' if status == 'A' else 'deleted, ' if status == 'D' else ''}binary)"
    if status == "A":
        return f"{path} (new, +{added})"
    if status == "D":
        return f"{path} (deleted, -{deleted})"
    return f"{path} (+{added} -{deleted})"


def name_files(files: list[object], limit: int) -> str:
    """The {files} detail of promote_batch: the most telling files first (deleted, run as you, code, tests, notes),
    each with its size, as many as fit in *limit* without cutting a name; the rest counted. A single card's 600 names
    every file of nearly every change."""
    texts = [file_text(*f) for f in sorted(_files({"files": files}), key=_rank)]
    shown: list[str] = []
    for text in texts:
        rest = len(texts) - len(shown) - 1
        if len(", ".join([*shown, text]) + (f" and {rest} more" if rest else "")) > limit:
            break
        shown.append(text)
    hidden = len(texts) - len(shown)
    if not shown:
        return f"{hidden} file(s)"
    return ", ".join(shown) + (f" and {hidden} more" if hidden else "")


def _row(spec: ListCardKind, n: int, files: list[_File]) -> str:
    """One change's line: every deleted file, file that runs as you, and code file, in full; tests and notes while
    the line has room, the rest counted."""
    ranked = sorted(files, key=_rank)
    added = sum(f[2] or 0 for f in files)
    deleted = sum(f[3] or 0 for f in files)
    binary = sum(1 for f in files if f[2] is None)
    size = f"+{added} -{deleted}" + (f", {binary} binary" if binary else "")
    prefix = spec.row.format(n=n, size=size, count=len(files), named="")
    named = [file_text(*f) for f in ranked if file_class(f[0], f[1]) <= 2]
    counted = [file_text(*f) for f in ranked if file_class(f[0], f[1]) > 2]
    while counted:
        rest = len(counted) - 1
        tail = spec.some_counted.format(named="", k=rest) if rest else ""
        if len(prefix) + len(", ".join([*named, counted[0]])) + len(tail) > spec.row_soft:
            break
        named.append(counted.pop(0))
    if not counted:
        return prefix + ", ".join(named)
    if not named:
        return prefix + spec.all_counted.format(k=len(counted))
    return prefix + spec.some_counted.format(named=", ".join(named), k=len(counted))


def fit_rows(kind: str, members: Sequence[object]) -> int:
    """How many of *members*, from the first, fit one card of *kind* whole: every file that must be named is named
    in full and the body stays within its limit. The promoter adds a change to a card only when this grows by one."""
    spec = LIST_KINDS[kind]
    used = len(spec.head.format(count=spec.max_rows))
    for n, member in enumerate(members, 1):
        if n > spec.max_rows:
            return n - 1
        used += 1 + len(_row(spec, n, _files(member)))
        if used > spec.body_limit:
            return n - 1
    return len(members)


def render_list(kind: str, members: Sequence[object]) -> tuple[str, str, dict[str, str]]:
    """(title, body, details) for a list card. *details* is what its pairing code covers: every file of every
    change, named on the card or counted, so a code can never match a card that shows something else."""
    spec = LIST_KINDS.get(kind)
    if spec is None:
        raise KeyError(f"no list card kind {kind!r}")
    if not spec.min_rows <= len(members) <= spec.max_rows or fit_rows(kind, members) != len(members):
        raise ValueError(f"card {kind!r} lists {spec.min_rows} to {spec.max_rows} changes that each fit it whole")
    listed = [_files(member) for member in members]
    lines = [spec.head.format(count=len(listed))] + [_row(spec, n, files) for n, files in enumerate(listed, 1)]
    details = {"count": str(len(listed))}
    details.update({str(n): json.dumps(files, separators=(",", ":")) for n, files in enumerate(listed, 1)})
    return spec.title, "\n".join(_one_line(line, DIALOG_LIMIT) for line in lines), details


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pairing_code(kind: str, details: Mapping[str, object], content_digest: str, nonce: str) -> str:
    """Six characters derived from exactly what is being approved."""
    canonical = json.dumps(
        {
            "kind": kind,
            "details": {str(k): str(v) for k, v in sorted(details.items())},
            "content": content_digest,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    code = "".join(_CODE_ALPHABET[b % len(_CODE_ALPHABET)] for b in digest[:6])
    return f"{code[:3]}-{code[3:]}"


def diff_lines(before: str | None, after: str) -> list[str]:
    return list(
        difflib.unified_diff(
            (before or "").splitlines(),
            after.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
            n=2,
        )
    )


def _counts(lines: list[str]) -> tuple[int, int]:
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return added, removed


def diffstat(before: str | None, after: str) -> str:
    added, removed = _counts(diff_lines(before, after))
    if before is None:
        return f"new file, {len(after.splitlines())} line(s)"
    return f"+{added} -{removed} line(s)"


def diff_excerpt(before: str | None, after: str, max_lines: int = 40) -> str:
    """The real diff, without file headers, cut to fit on a card."""
    body = [line for line in diff_lines(before, after) if not line.startswith(("---", "+++"))]
    if len(body) > max_lines:
        rest = len(body) - max_lines
        body = body[:max_lines] + [f"... {rest} more line(s)"]
    return "\n".join(body)


def _norm(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip().lower()
    return text[2:] if text.startswith("./") else text


def _under(rel: str, entry: str) -> bool:
    return rel == entry or (entry.endswith("/") and rel.startswith(entry))


def load_enforcement_paths(repo_root: Path) -> frozenset[str]:
    """Every path agent_safety.toml protects, as the gates themselves read it."""
    import tomllib

    data = tomllib.loads((Path(repo_root) / "agent_safety.toml").read_text(encoding="utf-8"))
    protected = data.get("protected", {})
    return frozenset(_norm(p) for key in _ENFORCEMENT_KEYS for p in protected.get(key, []))


def _added(diff: str) -> list[str]:
    """The added lines of a diff, without its file headers. A header is told apart by where it sits (before a file's
    first hunk), not by its "+++": an added line that itself starts with "++" shows as "+++" and is still read.
    Lines split on "\\n" alone, as git splits them: a lone carriage return or a Unicode line separator inside an
    added line stays in that line, so the text after it is still read."""
    lines: list[str] = []
    in_hunk = False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif line.startswith("+") and (in_hunk or not line.startswith("+++")):
            lines.append(line[1:])
    return lines


def danger_class(path: str, *, added_diff: str = "", enforcement_paths: Iterable[str] = ()) -> str | None:
    """The policy-C class of a change, or None for an ordinary one."""
    rel = _norm(path)
    if rel.startswith("scripts/forge/gates/") or any(_under(rel, _norm(e)) for e in enforcement_paths):
        return DANGER_GATES
    if any(_under(rel, entry) for entry in _CAGE_AND_APPROVAL):
        return DANGER_CAGE
    added = _added(added_diff or "")
    if rel.startswith("tests/") and ".." not in rel.split("/"):
        added = [line for line in added if not _IN_PROCESS_IMPORT.fullmatch(line)]
    # A space where an unreachable URL was, so taking it out cannot join the text around it into a new match.
    if any(_NETWORK_REACH.search(_UNREACHABLE_URL.sub(" ", line)) for line in added):
        return DANGER_NETWORK
    return None


__all__ = [
    "DANGER_CAGE",
    "DANGER_GATES",
    "DANGER_NETWORK",
    "DIALOG_LIMIT",
    "KINDS",
    "LIST_KINDS",
    "RETRY_NOTE",
    "WINDOW_CAP_WORDS",
    "WINDOW_CEILING_MINUTES",
    "WINDOW_DEFAULT_MINUTES",
    "WINDOW_IDLE_MINUTES",
    "WINDOW_MAX_LANDINGS",
    "WINDOW_NO_CAP_WORDS",
    "CardKind",
    "ListCardKind",
    "content_hash",
    "danger_class",
    "diff_excerpt",
    "diff_lines",
    "diffstat",
    "file_class",
    "file_text",
    "fit_rows",
    "load_enforcement_paths",
    "name_files",
    "pairing_code",
    "render",
    "render_list",
]
