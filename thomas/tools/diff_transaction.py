"""Transactional unified-diff engine: preflight, rollback, per-hunk selection.

Backs ``diff.apply_patch`` and ``diff.preview_patch`` in ``thomas.tools.diff``.

Guarantees:

* **Transactional preflight** — every selected hunk is verified against the
  current file content *before* any write.  If any hunk conflicts, nothing is
  applied and the report names each conflicting hunk.
* **Rollback** — all affected files are snapshotted (raw bytes) before the
  first write.  If any write fails mid-apply, every touched file is restored
  from its snapshot (files that did not exist are removed again).
* **Independent hunk accept/reject** — callers may pass a selection of hunk
  ids (stable ``<file>#<n>`` identifiers, also exposed by the preview) or
  1-based global indices; exactly that subset is preflighted and applied.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from thomas.tools.filesystem import _is_protected_runtime_path, _safe_path

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchFormatError(ValueError):
    """Raised when patch text cannot be parsed as a unified diff."""


@dataclass(frozen=True)
class Hunk:
    """One hunk of a unified diff, with a stable identifier.

    ``hunk_id`` is ``<file>#<n>`` where *n* is the 1-based position of the
    hunk within its file's diff — stable across preview and apply calls for
    the same patch text.
    """

    hunk_id: str
    file: str
    header: str
    old_start: int  # 0-indexed position in the ORIGINAL file
    old_lines: tuple[str, ...]  # expected existing lines (context + removed)
    new_lines: tuple[str, ...]  # replacement lines (context + added)


@dataclass(frozen=True)
class FilePatch:
    file: str
    hunks: tuple[Hunk, ...]


@dataclass(frozen=True)
class HunkConflict:
    hunk_id: str
    file: str
    reason: str


@dataclass
class PreflightReport:
    """Per-hunk preflight outcome (no writes performed)."""

    hunks: list[Hunk] = field(default_factory=list)
    conflicts: list[HunkConflict] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def conflict_for(self, hunk_id: str) -> HunkConflict | None:
        for c in self.conflicts:
            if c.hunk_id == hunk_id:
                return c
        return None


@dataclass
class ApplyReport:
    ok: bool
    applied_hunks: list[str] = field(default_factory=list)
    skipped_hunks: list[str] = field(default_factory=list)
    conflicts: list[HunkConflict] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    rolled_back: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_patch(patch_text: str) -> list[FilePatch]:
    """Parse unified diff text into per-file patches with stable hunk ids."""
    chunks = _split_file_diffs(patch_text)
    if not chunks:
        raise PatchFormatError("no file headers (---/+++) found in patch")

    file_patches: list[FilePatch] = []
    for fname, hunks_text in chunks:
        hunks: list[Hunk] = []
        for index, (header, body) in enumerate(_parse_hunk_blocks(hunks_text), start=1):
            hunks.append(_build_hunk(fname, index, header, body))
        file_patches.append(FilePatch(file=fname, hunks=tuple(hunks)))
    return file_patches


def _split_file_diffs(patch_text: str) -> list[tuple[str, str]]:
    """Split a multi-file patch into (filename, hunks_text) pairs."""
    chunks: list[tuple[str, str]] = []
    lines = patch_text.splitlines(keepends=True)
    i = 0

    while i < len(lines):
        if lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            plus_line = lines[i + 1].rstrip()
            fname = plus_line[4:].split("\t")[0].strip()
            if fname.startswith("b/"):
                fname = fname[2:]
            i += 2

            hunk_start = i
            while i < len(lines) and not (lines[i].startswith("--- ") or lines[i].startswith("diff --git")):
                i += 1
            chunks.append((fname, "".join(lines[hunk_start:i])))
        else:
            i += 1

    return chunks


def _parse_hunk_blocks(hunks_text: str) -> list[tuple[str, list[str]]]:
    """Parse (header, body_lines) blocks from one file's diff text."""
    blocks: list[tuple[str, list[str]]] = []
    lines = hunks_text.splitlines()
    i = 0

    while i < len(lines):
        if lines[i].startswith("@@"):
            header = lines[i]
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("@@"):
                body.append(lines[i])
                i += 1
            blocks.append((header, body))
        else:
            i += 1

    return blocks


def _build_hunk(fname: str, index: int, header: str, body: list[str]) -> Hunk:
    m = _HUNK_HEADER_RE.match(header)
    if not m:
        raise PatchFormatError(f"malformed hunk header in {fname}: {header!r}")
    raw_start = int(m.group(1))
    old_count = int(m.group(2)) if m.group(2) is not None else 1
    # "-N,0" means "insert after line N" (0-indexed position N); otherwise
    # "-N,c" means the hunk's expected lines start at line N (0-indexed N-1).
    old_start = raw_start if old_count == 0 else max(raw_start - 1, 0)

    old_lines: list[str] = []
    new_lines: list[str] = []
    for line in body:
        if line.startswith("\\"):
            continue  # "\ No newline at end of file"
        op = line[0] if line else " "
        text = line[1:] if line else ""
        if op == " ":
            old_lines.append(text)
            new_lines.append(text)
        elif op == "-":
            old_lines.append(text)
        elif op == "+":
            new_lines.append(text)
        else:
            raise PatchFormatError(f"unexpected line in hunk {fname}#{index}: {line!r}")

    return Hunk(
        hunk_id=f"{fname}#{index}",
        file=fname,
        header=header,
        old_start=old_start,
        old_lines=tuple(old_lines),
        new_lines=tuple(new_lines),
    )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def resolve_selection(
    file_patches: list[FilePatch],
    selection: Sequence[str | int] | None,
) -> tuple[set[str], list[str]]:
    """Resolve a caller-supplied hunk selection to hunk ids.

    Accepts stable hunk ids (``"<file>#<n>"``) and 1-based global indices in
    patch order (as ints or digit strings).  ``None`` selects every hunk.
    Returns ``(accepted_ids, unknown_entries)``.
    """
    all_hunks = [h for fp in file_patches for h in fp.hunks]
    if selection is None:
        return {h.hunk_id for h in all_hunks}, []

    by_id = {h.hunk_id for h in all_hunks}
    accepted: set[str] = set()
    unknown: list[str] = []
    for item in selection:
        token = str(item).strip()
        if token in by_id:
            accepted.add(token)
        elif token.isdigit() and 1 <= int(token) <= len(all_hunks):
            accepted.add(all_hunks[int(token) - 1].hunk_id)
        else:
            unknown.append(token)
    return accepted, unknown


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _line_text(raw: str) -> str:
    """Line content without its trailing newline (LF or CRLF)."""
    if raw.endswith("\r\n"):
        return raw[:-2]
    if raw.endswith("\n"):
        return raw[:-1]
    return raw


def _preflight_file(
    fp: FilePatch,
    content: str,
    accepted: set[str],
) -> tuple[list[HunkConflict], str]:
    """Verify accepted hunks against *content*; return conflicts + new content.

    Positions in hunk headers refer to the ORIGINAL file, so skipping a hunk
    never shifts the expected position of later hunks — the running offset
    accumulates only from hunks actually applied.
    """
    lines = content.splitlines(keepends=True)
    result = list(lines)
    conflicts: list[HunkConflict] = []
    offset = 0
    prev_end = 0  # end of previous applied/verified hunk, original coordinates

    for hunk in fp.hunks:
        if hunk.hunk_id not in accepted:
            continue
        pos = hunk.old_start
        n_old = len(hunk.old_lines)

        if pos < prev_end:
            conflicts.append(HunkConflict(hunk.hunk_id, fp.file, f"overlaps previous hunk (line {pos + 1})"))
            continue
        if pos > len(lines) or pos + n_old > len(lines):
            conflicts.append(
                HunkConflict(
                    hunk.hunk_id,
                    fp.file,
                    f"extends past end of file (needs lines {pos + 1}-{pos + n_old}, file has {len(lines)})",
                )
            )
            continue

        mismatch: HunkConflict | None = None
        for j, expected in enumerate(hunk.old_lines):
            actual = _line_text(lines[pos + j])
            if actual != expected:
                mismatch = HunkConflict(
                    hunk.hunk_id,
                    fp.file,
                    f"line {pos + j + 1} mismatch: expected {expected!r}, found {actual!r}",
                )
                break
        if mismatch is not None:
            conflicts.append(mismatch)
            continue

        result[pos + offset : pos + offset + n_old] = [t + "\n" for t in hunk.new_lines]
        offset += len(hunk.new_lines) - n_old
        prev_end = pos + n_old

    return conflicts, "".join(result)


def _plan(
    file_patches: list[FilePatch],
    root: Path,
    accepted: set[str],
) -> tuple[list[tuple[Path, str, str]], list[HunkConflict], list[str], list[str]]:
    """Preflight all files; return (planned_writes, conflicts, applied, skipped).

    ``planned_writes`` entries are (resolved_path, relative_name, new_content).
    """
    planned: list[tuple[Path, str, str]] = []
    conflicts: list[HunkConflict] = []
    applied: list[str] = []
    skipped: list[str] = []

    for fp in file_patches:
        file_accepted = [h for h in fp.hunks if h.hunk_id in accepted]
        skipped.extend(h.hunk_id for h in fp.hunks if h.hunk_id not in accepted)
        if not file_accepted:
            continue

        def _reject(reason: str, hunks: list[Hunk] = file_accepted, file: str = fp.file) -> None:
            conflicts.extend(HunkConflict(h.hunk_id, file, reason) for h in hunks)

        try:
            path = _safe_path(root, fp.file)
        except ValueError as e:
            _reject(str(e))
            continue

        blocked = _is_protected_runtime_path(root, path)
        if blocked:
            _reject(blocked)
            continue

        if path.exists():
            if not path.is_file():
                _reject(f"not a regular file: {fp.file}")
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                _reject(f"cannot read {fp.file}: {e}")
                continue
        else:
            if any(h.old_lines for h in file_accepted):
                _reject(f"target file does not exist: {fp.file}")
                continue
            content = ""

        file_conflicts, new_content = _preflight_file(fp, content, accepted)
        if file_conflicts:
            conflicts.extend(file_conflicts)
            continue

        planned.append((path, fp.file, new_content))
        applied.extend(h.hunk_id for h in file_accepted)

    return planned, conflicts, applied, skipped


def preflight_patch(
    patch_text: str,
    root: Path,
    selection: Sequence[str | int] | None = None,
) -> PreflightReport:
    """Parse + verify a patch against current file content. Never writes."""
    file_patches = parse_patch(patch_text)
    accepted, unknown = resolve_selection(file_patches, selection)
    report = PreflightReport(
        hunks=[h for fp in file_patches for h in fp.hunks],
        selected=sorted(accepted),
    )
    if unknown:
        report.conflicts.extend(HunkConflict(token, "", "unknown hunk id or index") for token in unknown)
        return report
    _, conflicts, _, _ = _plan(file_patches, root, accepted)
    report.conflicts.extend(conflicts)
    return report


# ---------------------------------------------------------------------------
# Transactional apply
# ---------------------------------------------------------------------------


def _restore_snapshots(snapshots: dict[Path, bytes | None], touched: list[Path]) -> list[str]:
    """Restore every touched file from its snapshot. Returns restore failures."""
    failures: list[str] = []
    for path in touched:
        snapshot = snapshots.get(path)
        try:
            if snapshot is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(snapshot)
        except OSError as e:
            failures.append(f"{path}: {e}")
    return failures


def apply_patch_transactional(
    patch_text: str,
    root: Path,
    selection: Sequence[str | int] | None = None,
) -> ApplyReport:
    """Apply a unified diff atomically: preflight everything, write, or roll back.

    * Any conflicting hunk (in the selected subset) blocks the ENTIRE apply.
    * All affected files are snapshotted before the first write; a mid-apply
      write failure restores every touched file (created files are removed).
    * ``selection`` limits the apply to the named hunks; ``None`` = all hunks.
    """
    file_patches = parse_patch(patch_text)
    accepted, unknown = resolve_selection(file_patches, selection)
    all_ids = [h.hunk_id for fp in file_patches for h in fp.hunks]

    if unknown:
        return ApplyReport(
            ok=False,
            skipped_hunks=all_ids,
            error="unknown hunk selection: " + ", ".join(unknown) + "; nothing applied",
        )
    if selection is not None and not accepted:
        return ApplyReport(ok=False, skipped_hunks=all_ids, error="empty hunk selection; nothing applied")

    planned, conflicts, applied, skipped = _plan(file_patches, root, accepted)

    if conflicts:
        return ApplyReport(
            ok=False,
            skipped_hunks=skipped,
            conflicts=conflicts,
            error=f"preflight failed for {len(conflicts)} hunk(s); nothing applied",
        )
    if not planned:
        return ApplyReport(ok=False, skipped_hunks=skipped, error="No valid hunks found in patch")

    # ── Snapshot phase: capture every affected file BEFORE any write ──
    snapshots: dict[Path, bytes | None] = {}
    for path, rel, _ in planned:
        try:
            snapshots[path] = path.read_bytes() if path.exists() else None
        except OSError as e:
            return ApplyReport(
                ok=False,
                skipped_hunks=skipped,
                error=f"snapshot failed for {rel}: {e}; nothing applied",
            )

    # ── Write phase: any failure rolls back every touched file ──
    touched: list[Path] = []
    failed_rel: str | None = None
    write_error: OSError | None = None
    for path, rel, new_content in planned:
        touched.append(path)  # a failed write may still truncate — restore it too
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            failed_rel = rel
            write_error = e
            break

    if write_error is not None:
        restore_failures = _restore_snapshots(snapshots, touched)
        error = f"write failed for {failed_rel}: {write_error}; all files rolled back"
        if restore_failures:
            error += "; ROLLBACK INCOMPLETE: " + "; ".join(restore_failures)
        return ApplyReport(
            ok=False,
            skipped_hunks=skipped,
            rolled_back=True,
            error=error,
        )

    return ApplyReport(
        ok=True,
        applied_hunks=applied,
        skipped_hunks=skipped,
        files_written=[rel for _, rel, _ in planned],
    )
