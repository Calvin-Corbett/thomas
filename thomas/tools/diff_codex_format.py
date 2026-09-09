"""Read the patch grammar the model writes, and hand the transaction what it reads (2026-09-05).

Counted on one day's Build transcripts: of 88 ``diff.apply_patch`` and
``diff.preview_patch`` calls, 35 were rejected with "no file headers (---/+++)
found in patch" and one with "unexpected line in hunk: '*** End Patch'". The
GPT worker writes the Codex apply-patch envelope::

    *** Begin Patch
    *** Update File: game.js
    @@ function loop() {
       update();
    -  render();
    +  render();
    +  requestAnimationFrame(loop);
     }
    *** Add File: notes.md
    +# Notes
    *** Delete File: old.txt
    *** End Patch

and the transaction reads numbered unified diffs only. Every rejection cost a
round, and the run then re-did the same edits as "small exact replacements".

This module converts the envelope: each hunk's old lines (context and ``-``)
are located in the current file, after the previous hunk and after the ``@@``
anchor when one is given, and a numbered unified hunk is emitted with the
file's own text so the transaction's exact preflight agrees. A hunk that
cannot be placed is refused by name with the first line that was not found,
and nothing is written. Plain unified diffs pass through untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from thomas.tools.diff_transaction import PatchFormatError

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_UPDATE = "*** Update File: "
_ADD = "*** Add File: "
_DELETE = "*** Delete File: "
_MOVE = "*** Move to: "
_EOF = "*** End of File"


@dataclass
class CodexConversion:
    unified: str
    created: list[Path] = field(default_factory=list)  # empty files made so an Add can apply
    to_delete: list[Path] = field(default_factory=list)  # files a Delete empties; remove after success


def looks_like_codex_patch(text: str) -> bool:
    head = str(text or "").lstrip()
    return head.startswith(_BEGIN) or any(marker in head for marker in (_UPDATE, _ADD, _DELETE))


def codex_patch_to_unified(text: str, root: Path) -> str:
    """The unified diff for ``text``; ``text`` itself when it is not the envelope."""
    return convert_codex_patch(text, root, create_files=False).unified


def convert_codex_patch(text: str, root: Path, *, create_files: bool) -> CodexConversion:
    if not looks_like_codex_patch(text):
        return CodexConversion(unified=text)
    base = Path(root).resolve()
    out: list[str] = []
    created: list[Path] = []
    to_delete: list[Path] = []
    try:
        for kind, rel, body in _sections(text):
            target = _inside(base, rel)
            if kind == "update":
                out.append(_update_diff(rel, target, body))
            elif kind == "add":
                new_lines = [line[1:] for line in body if line.startswith("+")]
                if create_files and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("", encoding="utf-8")
                    created.append(target)
                out.append(
                    f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(new_lines)} @@\n"
                    + "".join(f"+{line}\n" for line in new_lines)
                )
            elif kind == "delete":
                if not target.is_file():
                    raise PatchFormatError(f"{rel}: cannot delete a file that does not exist")
                old_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                out.append(
                    f"--- a/{rel}\n+++ b/{rel}\n@@ -1,{len(old_lines)} +0,0 @@\n"
                    + "".join(f"-{line}\n" for line in old_lines)
                )
                to_delete.append(target)
    except PatchFormatError:
        # A later section failed to parse: nothing is applied, so nothing this
        # conversion made may remain either.
        for made in created:
            made.unlink(missing_ok=True)
        raise
    return CodexConversion(unified="".join(out), created=created, to_delete=to_delete)


def _inside(base: Path, rel: str) -> Path:
    clean = rel.strip().replace("\\", "/")
    if not clean:
        raise PatchFormatError("a file marker names no path")
    target = (base / clean).resolve()
    if not target.is_relative_to(base):
        raise PatchFormatError(f"{clean}: path escapes the project")
    return target


def _sections(text: str) -> list[tuple[str, str, list[str]]]:
    """(kind, path, body lines) per file marker, in order."""
    sections: list[tuple[str, str, list[str]]] = []
    current: list[str] | None = None
    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.strip() in {_BEGIN, _END, _EOF}:
            continue
        if line.startswith(_UPDATE):
            current = []
            sections.append(("update", line[len(_UPDATE) :], current))
        elif line.startswith(_ADD):
            current = []
            sections.append(("add", line[len(_ADD) :], current))
        elif line.startswith(_DELETE):
            current = []
            sections.append(("delete", line[len(_DELETE) :], current))
        elif line.startswith(_MOVE):
            raise PatchFormatError("'*** Move to:' is not supported; delete and add the file instead")
        elif current is not None:
            current.append(line)
    if not sections:
        raise PatchFormatError("the patch names no file (*** Update File: / *** Add File: / *** Delete File:)")
    return sections


def _update_diff(rel: str, target: Path, body: list[str]) -> str:
    if not target.is_file():
        raise PatchFormatError(f"{rel}: target file does not exist")
    file_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    hunks = _hunks(body)
    if not hunks:
        raise PatchFormatError(f"{rel}: no hunk (a line starting with @@) in the update")
    rendered: list[str] = [f"--- a/{rel}\n+++ b/{rel}\n"]
    cursor = 0
    for index, (anchor, lines) in enumerate(hunks, 1):
        old = [line[1:] for line in lines if line[:1] in {" ", "-"} or line == ""]
        new = [line[1:] for line in lines if line[:1] in {" ", "+"} or line == ""]
        search_from = cursor
        if anchor:
            hit = _find_line(file_lines, anchor, cursor)
            if hit is not None:
                search_from = hit
        if old:
            start = _find_block(file_lines, old, search_from)
            if start is None:
                raise PatchFormatError(
                    f"{rel}#{index}: could not find these lines in the file (first: {old[0]!r})"
                    + (f" after anchor {anchor!r}" if anchor else "")
                )
            header = f"@@ -{start + 1},{len(old)} +{start + 1},{len(new)} @@\n"
            actual = iter(file_lines[start : start + len(old)])
            # The file's own text for context and removed lines, so an exact preflight agrees.
            body_out = []
            for line in lines:
                if line[:1] in {" ", "-"} or line == "":
                    body_out.append(("-" if line[:1] == "-" else " ") + next(actual))
                else:
                    body_out.append(line)
            cursor = start + len(old)
        else:
            # Pure insertion: after the anchor line when one was found, else at the cursor.
            start = search_from + 1 if anchor and search_from != cursor else cursor
            header = f"@@ -{start},0 +{start + 1},{len(new)} @@\n"
            body_out = list(lines)
            cursor = start
        rendered.append(header + "".join(f"{line}\n" for line in body_out))
    return "".join(rendered)


def _hunks(body: list[str]) -> list[tuple[str, list[str]]]:
    hunks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    anchor = ""
    for line in body:
        if line.startswith("@@"):
            if current is not None:
                hunks.append((anchor, current))
            anchor = line[2:].strip()
            current = []
        elif current is not None:
            current.append(line)
        elif line.strip():
            # Lines before any @@: treat as one hunk without an anchor.
            anchor, current = "", [line]
    if current is not None:
        hunks.append((anchor, current))
    return [(a, [l for l in body_lines if not l.startswith("\\")]) for a, body_lines in hunks]


def _find_line(file_lines: list[str], anchor: str, start: int) -> int | None:
    wanted = anchor.strip()
    for index in range(start, len(file_lines)):
        if file_lines[index].strip() == wanted:
            return index
    for index in range(start, len(file_lines)):
        if wanted and wanted in file_lines[index]:
            return index
    return None


def _find_block(file_lines: list[str], old: list[str], start: int) -> int | None:
    n = len(old)
    for exact in (True, False):
        for index in range(start, len(file_lines) - n + 1):
            window = file_lines[index : index + n]
            if exact and window == old:
                return index
            if not exact and [w.rstrip() for w in window] == [o.rstrip() for o in old]:
                return index
    return None
