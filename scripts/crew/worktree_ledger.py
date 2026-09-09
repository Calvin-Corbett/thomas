#!/usr/bin/env python3
"""Worktree ledger — make every git worktree on this machine discoverable.

This module is the foundation of the worktree-sprawl prevention system. It
enumerates *all* git worktrees attached to the repository, captures the state
that matters for merge-debt decisions (branch, HEAD, uncommitted file count,
staleness), and writes both a human-readable ledger (``.thomas/WORKTREES.md``)
and a machine-readable snapshot (``.thomas/worktrees.json``).

The same data feeds two siblings:
  * ``worktree_creation_gate.py`` — the sanctioned front door for new worktrees.
  * ``worktree_debt.py``          — the over-ceiling alarm.

Design laws (see the build request):
  * **Additive + default-safe.** With only the main checkout, every code path is
    a quiet no-op — a fresh clone is never affected.
  * **Defensive.** A missing or broken worktree path degrades to a noted row,
    never a crash.
  * **Cross-platform.** Paths are handled via :mod:`pathlib`; worktrees are read
    live from git, so no machine paths are ever hard-coded.

Config is read from ``agent_safety.toml`` ``[worktree_governance]`` (with the
optional ``agent_safety.local.toml`` overlay for per-install tuning). If the
section is absent, the built-in defaults below apply.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _force_utf8_streams() -> None:
    """UTF-8 stdout/stderr so ledger glyphs (warnings, table rules) render on a
    legacy-code-page console (Windows cp1252) instead of crashing on encode."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


_force_utf8_streams()

# scripts/crew/worktree_ledger.py -> parents[2] == repo root
ROOT = Path(__file__).resolve().parents[2]

# ── Built-in governance defaults (used when agent_safety.toml omits them) ──────
DEFAULT_MAX_DIRTY_WORKTREES = 5
DEFAULT_STALE_DAYS = 7
DEFAULT_LEDGER_DIR = ".thomas"
_GIT_TIMEOUT_SECONDS = 15


# ── Config loading (protected-file-aware, mirrors safety_config overlay) ───────


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, tolerating a missing file or absent parser."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        pass
    except (ValueError, TypeError):  # malformed TOML — degrade to defaults
        return {}
    try:
        import tomli

        return tomli.loads(text)
    except (ImportError, ValueError, TypeError):
        return {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Recursively merge ``overlay`` into ``base`` in place (overlay wins)."""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@dataclass
class GovernanceConfig:
    """Resolved ``[worktree_governance]`` settings."""

    max_dirty_worktrees: int = DEFAULT_MAX_DIRTY_WORKTREES
    stale_days: int = DEFAULT_STALE_DAYS
    ledger_dir: str = DEFAULT_LEDGER_DIR


def load_governance(root: Path | None = None) -> GovernanceConfig:
    """Read ``[worktree_governance]`` from agent_safety.toml (+ .local overlay).

    Falls back to safe defaults for any missing key, so the system works with no
    config at all. Negative or non-numeric overrides degrade to the default.
    """
    base = root or ROOT
    data = _load_toml(base / "agent_safety.toml")
    overlay = _load_toml(base / "agent_safety.local.toml")
    if overlay:
        _deep_merge(data, overlay)
    section = data.get("worktree_governance") if isinstance(data, dict) else None
    section = section if isinstance(section, dict) else {}

    def _int(key: str, default: int) -> int:
        try:
            value = int(section.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value >= 0 else default

    ledger_dir = str(section.get("ledger_dir", DEFAULT_LEDGER_DIR) or DEFAULT_LEDGER_DIR).strip()
    return GovernanceConfig(
        max_dirty_worktrees=_int("max_dirty_worktrees", DEFAULT_MAX_DIRTY_WORKTREES),
        stale_days=_int("stale_days", DEFAULT_STALE_DAYS),
        ledger_dir=ledger_dir or DEFAULT_LEDGER_DIR,
    )


# ── Git helpers (all defensive — never raise to the caller) ────────────────────


def _run_git(args: list[str], cwd: Path, timeout: int = _GIT_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Run a git command, returning (returncode, stdout, stderr).

    Any failure (git missing, timeout, OS error) returns a non-zero code with the
    error text in stderr rather than raising — callers degrade gracefully.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


def parse_worktree_list(porcelain: str) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` output into records.

    Each record carries: path, head, branch (short name or ""), and flags
    ``bare`` / ``detached``. Blocks are separated by blank lines.
    """
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in porcelain.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current:
                records.append(current)
            current = {"path": line[len("worktree ") :].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            ref = line[len("branch ") :].strip()
            current["branch"] = ref.replace("refs/heads/", "", 1)
        elif line.strip() == "bare":
            current["bare"] = "1"
        elif line.strip() == "detached":
            current["detached"] = "1"
    if current:
        records.append(current)
    return records


def purpose_from_branch(branch: str, *, detached: bool = False, bare: bool = False) -> str:
    """Derive a human one-line purpose from a branch name.

    ``feat/gpu-citizenship`` -> ``gpu citizenship``. Drops common type prefixes
    (feat/fix/wip/...) so the purpose reads as the subject of the work.
    """
    if bare:
        return "bare repository"
    if detached or not branch:
        return "detached HEAD (no branch)"
    name = branch.split("/")[-1] if "/" in branch else branch
    type_prefixes = {"feat", "feature", "fix", "bugfix", "wip", "chore", "refactor", "exp", "experiment", "spike"}
    # If the branch is grouped like feat/<thing>, the leading segment is a type.
    head_segment = branch.split("/")[0].lower()
    words = name.replace("_", " ").replace("-", " ").strip()
    if head_segment in type_prefixes and "/" in branch:
        return words or branch
    return words or branch


# ── Ledger model ───────────────────────────────────────────────────────────────


@dataclass
class WorktreeRow:
    path: str
    is_main: bool
    branch: str
    head_sha: str
    uncommitted_count: int
    last_commit_iso: str
    days_since_last_commit: int | None
    purpose: str
    stale: bool
    dirty: bool
    exists: bool
    note: str = ""


@dataclass
class Ledger:
    generated_at: str
    root: str
    config: GovernanceConfig
    rows: list[WorktreeRow] = field(default_factory=list)

    # ── Derived counts ──
    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def linked(self) -> list[WorktreeRow]:
        """Worktrees other than the main checkout."""
        return [row for row in self.rows if not row.is_main]

    @property
    def dirty_worktrees(self) -> list[WorktreeRow]:
        """DIRTY linked worktrees — these drive the merge-debt ceiling."""
        return [row for row in self.linked if row.dirty]

    @property
    def stale_worktrees(self) -> list[WorktreeRow]:
        return [row for row in self.linked if row.stale]

    @property
    def dirty_count(self) -> int:
        return len(self.dirty_worktrees)

    @property
    def stale_count(self) -> int:
        return len(self.stale_worktrees)

    @property
    def over_ceiling(self) -> bool:
        return self.dirty_count >= self.config.max_dirty_worktrees


def _now_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _days_since(iso: str, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    delta = now - then
    return max(0, delta.days)


def _inspect_worktree(record: dict[str, str], *, main_path: Path, stale_days: int, now: datetime) -> WorktreeRow:
    """Build a single ledger row, degrading a broken path to a noted row."""
    raw_path = record.get("path", "")
    path = Path(raw_path)
    branch = record.get("branch", "")
    head = record.get("head", "")
    bare = record.get("bare") == "1"
    detached = record.get("detached") == "1"
    purpose = purpose_from_branch(branch, detached=detached, bare=bare)
    head_sha = head[:10] if head else ""

    try:
        is_main = path.resolve() == main_path.resolve()
    except OSError:
        is_main = raw_path == str(main_path)

    if not path.exists():
        return WorktreeRow(
            path=raw_path,
            is_main=is_main,
            branch=branch,
            head_sha=head_sha,
            uncommitted_count=0,
            last_commit_iso="",
            days_since_last_commit=None,
            purpose=purpose,
            stale=False,
            dirty=False,
            exists=False,
            note="worktree path is missing on disk (prune candidate)",
        )

    note = ""
    # Uncommitted file count.
    code, out, err = _run_git(["status", "--porcelain"], cwd=path)
    if code == 0:
        uncommitted = sum(1 for line in out.splitlines() if line.strip())
    else:
        uncommitted = 0
        note = (note + "; " if note else "") + f"status unavailable ({err.strip()[:60]})"

    # Last commit timestamp (strict ISO 8601).
    code, out, err = _run_git(["log", "-1", "--format=%cI"], cwd=path)
    last_iso = out.strip() if code == 0 else ""
    if code != 0 and not note:
        note = f"no commits / log unavailable ({err.strip()[:60]})"
    days = _days_since(last_iso, now)

    dirty = uncommitted > 0
    stale = days is not None and days > stale_days
    return WorktreeRow(
        path=raw_path,
        is_main=is_main,
        branch=branch,
        head_sha=head_sha,
        uncommitted_count=uncommitted,
        last_commit_iso=last_iso,
        days_since_last_commit=days,
        purpose=purpose,
        stale=stale,
        dirty=dirty,
        exists=True,
        note=note,
    )


def collect(root: Path | None = None, *, now: datetime | None = None) -> Ledger:
    """Enumerate all worktrees and build the in-memory ledger.

    Never raises: if ``git worktree list`` itself fails, an empty ledger with a
    single noted main row is returned so the rest of the system stays alive.
    """
    base = root or ROOT
    config = load_governance(base)
    moment = _now_utc(now)
    generated_at = moment.isoformat()

    code, out, err = _run_git(["worktree", "list", "--porcelain"], cwd=base)
    if code != 0:
        # Git unavailable or not a repo — degrade to a single noted row.
        main_row = WorktreeRow(
            path=str(base),
            is_main=True,
            branch="",
            head_sha="",
            uncommitted_count=0,
            last_commit_iso="",
            days_since_last_commit=None,
            purpose="main checkout",
            stale=False,
            dirty=False,
            exists=base.exists(),
            note=f"git worktree list failed ({err.strip()[:80]})",
        )
        return Ledger(generated_at=generated_at, root=str(base), config=config, rows=[main_row])

    records = parse_worktree_list(out)
    rows = [_inspect_worktree(record, main_path=base, stale_days=config.stale_days, now=moment) for record in records]
    if not rows:
        rows = [
            WorktreeRow(
                path=str(base),
                is_main=True,
                branch="",
                head_sha="",
                uncommitted_count=0,
                last_commit_iso="",
                days_since_last_commit=None,
                purpose="main checkout",
                stale=False,
                dirty=False,
                exists=base.exists(),
                note="no worktrees reported",
            )
        ]
    return Ledger(generated_at=generated_at, root=str(base), config=config, rows=rows)


# ── Rendering ──────────────────────────────────────────────────────────────────


def _flags(row: WorktreeRow) -> str:
    marks: list[str] = []
    if not row.exists:
        marks.append("MISSING")
    if row.dirty:
        marks.append("DIRTY")
    if row.stale:
        marks.append("STALE")
    return ",".join(marks) if marks else "ok"


def header_line(ledger: Ledger) -> str:
    """The loud one-line header used by ``show`` and the startup brief."""
    total = ledger.total
    if total <= 1:
        return f"✓ {total} worktree — clean. No merge debt."
    dirty = ledger.dirty_count
    stale = ledger.stale_count
    glyph = "⚠" if (dirty or stale or ledger.over_ceiling) else "✓"
    msg = f"{glyph} {total} worktrees — {dirty} DIRTY, {stale} STALE."
    if dirty or stale:
        msg += " Review before creating a new one."
    if ledger.over_ceiling:
        msg += f" OVER CEILING ({dirty} ≥ {ledger.config.max_dirty_worktrees}) — consolidate."
    return msg


def summary_line(ledger: Ledger) -> str:
    """Compact, single-line summary for the startup router."""
    if ledger.total <= 1:
        return f"worktrees: {ledger.total} (clean)"
    return (
        f"worktrees: {ledger.total} total, {ledger.dirty_count} dirty, "
        f"{ledger.stale_count} stale (ceiling={ledger.config.max_dirty_worktrees})"
    )


def render_table(ledger: Ledger) -> str:
    """Render a clean fixed-width table to a string."""
    rows = ledger.rows
    headers = ["FLAGS", "BRANCH", "HEAD", "UNCMT", "AGE(d)", "PURPOSE", "PATH"]

    def _row_cells(row: WorktreeRow) -> list[str]:
        age = "-" if row.days_since_last_commit is None else str(row.days_since_last_commit)
        branch = row.branch or ("(main)" if row.is_main else "(detached)")
        return [
            _flags(row),
            branch,
            row.head_sha or "-",
            str(row.uncommitted_count),
            age,
            row.purpose or "-",
            row.path,
        ]

    table = [headers] + [_row_cells(row) for row in rows]
    widths = [max(len(str(cell)) for cell in column) for column in zip(*table)]
    lines = [header_line(ledger), ""]
    for index, cells in enumerate(table):
        line = "  ".join(str(cell).ljust(widths[col]) for col, cell in enumerate(cells))
        lines.append(line.rstrip())
        if index == 0:
            lines.append("  ".join("-" * widths[col] for col in range(len(widths))))
    notes = [row for row in rows if row.note]
    if notes:
        lines.append("")
        lines.append("notes:")
        for row in notes:
            lines.append(f"  - {row.branch or row.path}: {row.note}")
    return "\n".join(lines)


def render_markdown(ledger: Ledger) -> str:
    """Render the tracked ``WORKTREES.md`` ledger."""
    lines = [
        "# Worktree Ledger",
        "",
        "<!-- GENERATED by scripts/crew/worktree_ledger.py — do not edit by hand. -->",
        f"_Snapshot: {ledger.generated_at}_",
        "",
        header_line(ledger),
        "",
        "| Flags | Branch | HEAD | Uncommitted | Age (days) | Purpose | Path |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in ledger.rows:
        age = "-" if row.days_since_last_commit is None else str(row.days_since_last_commit)
        branch = row.branch or ("(main)" if row.is_main else "(detached)")
        path = row.path.replace("\\", "/")
        lines.append(
            f"| {_flags(row)} | {branch} | {row.head_sha or '-'} | {row.uncommitted_count} "
            f"| {age} | {row.purpose or '-'} | `{path}` |"
        )
    notes = [row for row in ledger.rows if row.note]
    if notes:
        lines.extend(["", "## Notes", ""])
        for row in notes:
            lines.append(f"- **{row.branch or row.path}**: {row.note}")
    lines.extend(
        [
            "",
            "## How to use",
            "",
            f"- Merge-debt ceiling: **{ledger.config.max_dirty_worktrees}** dirty worktrees "
            f"(stale = no commit in > {ledger.config.stale_days} days).",
            "- Create new worktrees only via `python scripts/forge/gates/worktree_creation_gate.py new <name>`.",
            "- Raw `git worktree add` is discouraged — it bypasses the debt ceiling and the ledger.",
            "- Refresh this file with `python scripts/crew/worktree_ledger.py update`.",
            "",
        ]
    )
    return "\n".join(lines)


def _ledger_to_json(ledger: Ledger) -> dict[str, Any]:
    return {
        "generated_at": ledger.generated_at,
        "root": ledger.root,
        "config": asdict(ledger.config),
        "summary": {
            "total": ledger.total,
            "dirty": ledger.dirty_count,
            "stale": ledger.stale_count,
            "over_ceiling": ledger.over_ceiling,
        },
        "worktrees": [asdict(row) for row in ledger.rows],
    }


def ledger_paths(ledger: Ledger) -> tuple[Path, Path]:
    """Return (markdown_path, json_path) for the configured ledger dir."""
    base = Path(ledger.root)
    out_dir = base / ledger.config.ledger_dir
    return out_dir / "WORKTREES.md", out_dir / "worktrees.json"


def write_ledger(ledger: Ledger) -> tuple[Path, Path]:
    """Write WORKTREES.md and worktrees.json; create the ledger dir if needed."""
    md_path, json_path = ledger_paths(ledger)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(ledger), encoding="utf-8")
    json_path.write_text(
        json.dumps(_ledger_to_json(ledger), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return md_path, json_path


def update(root: Path | None = None, *, now: datetime | None = None) -> Ledger:
    """Collect + persist the ledger. Returns the in-memory ledger."""
    ledger = collect(root, now=now)
    write_ledger(ledger)
    return ledger


# ── CLI ────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enumerate and report git worktrees (sprawl-prevention ledger).")
    sub = parser.add_subparsers(dest="command")
    p_update = sub.add_parser("update", help="Refresh .thomas/WORKTREES.md and .thomas/worktrees.json.")
    p_update.add_argument("--root", default=str(ROOT), help="Repository root.")
    p_show = sub.add_parser("show", help="Print today's worktree snapshot as a table.")
    p_show.add_argument("--root", default=str(ROOT), help="Repository root.")
    p_show.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "show"
    root = Path(getattr(args, "root", str(ROOT))).expanduser()

    if command == "update":
        ledger = update(root)
        md_path, json_path = ledger_paths(ledger)
        print(header_line(ledger))
        print(f"wrote {md_path}")
        print(f"wrote {json_path}")
        return 0

    # show
    ledger = collect(root)
    if getattr(args, "json", False):
        print(json.dumps(_ledger_to_json(ledger), ensure_ascii=False, indent=2))
    else:
        print(render_table(ledger))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
