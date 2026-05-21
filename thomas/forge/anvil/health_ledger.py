"""Health audit ledger — tracks when each file/module was last reviewed and its status.

The ledger lives at `.thomas/evolve/health_ledger.json` and stores per-file
timestamps plus pass/fail status.  The evolve loop consults the ledger to
prioritise work: older or never-reviewed files get attention first, and files
that already passed recently are skipped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

LEDGER_VERSION = 1


@dataclass
class FileAuditRecord:
    """Single file's audit state."""

    path: str
    last_reviewed_at: str = ""
    status: str = "pending"  # pending | pass | needs_work | refactored
    line_count: int = 0
    notes: str = ""
    reviewed_by: str = ""  # which agent/session reviewed it

    @property
    def last_reviewed_dt(self) -> datetime | None:
        if not self.last_reviewed_at:
            return None
        try:
            return datetime.fromisoformat(self.last_reviewed_at)
        except (ValueError, TypeError):
            return None


@dataclass
class HealthLedger:
    """Full ledger with per-file records and metadata."""

    version: int = LEDGER_VERSION
    last_full_sweep_at: str = ""
    records: dict[str, FileAuditRecord] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "last_full_sweep_at": self.last_full_sweep_at,
            "records": {k: asdict(v) for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HealthLedger:
        records: dict[str, FileAuditRecord] = {}
        for key, val in (payload.get("records") or {}).items():
            records[key] = FileAuditRecord(
                **{k: v for k, v in val.items() if k in FileAuditRecord.__dataclass_fields__}
            )
        return cls(
            version=int(payload.get("version") or LEDGER_VERSION),
            last_full_sweep_at=str(payload.get("last_full_sweep_at") or ""),
            records=records,
        )

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def mark_reviewed(
        self,
        path: str,
        *,
        status: str = "pass",
        line_count: int = 0,
        notes: str = "",
        reviewed_by: str = "",
    ) -> None:
        """Record that a file was reviewed right now."""
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.records[path] = FileAuditRecord(
            path=path,
            last_reviewed_at=now,
            status=status,
            line_count=line_count,
            notes=notes,
            reviewed_by=reviewed_by,
        )

    def get_record(self, path: str) -> FileAuditRecord | None:
        return self.records.get(path)

    def needs_review(self, path: str, *, max_age_hours: float = 168.0) -> bool:
        """True if the file has never been reviewed or was reviewed > max_age_hours ago."""
        rec = self.records.get(path)
        if rec is None:
            return True
        dt = rec.last_reviewed_dt
        if dt is None:
            return True
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        return age > max_age_hours

    def prioritised_files(
        self,
        candidates: list[str],
        *,
        max_age_hours: float = 168.0,
    ) -> list[str]:
        """Sort candidate files so the most stale / never-reviewed come first.

        Files that already passed review within *max_age_hours* are excluded.
        """
        needs: list[tuple[float, str]] = []
        for path in candidates:
            rec = self.records.get(path)
            if rec is None:
                # Never reviewed — top priority (infinite age)
                needs.append((float("inf"), path))
                continue
            dt = rec.last_reviewed_dt
            if dt is None:
                needs.append((float("inf"), path))
                continue
            age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
            if age_hours <= max_age_hours and rec.status == "pass":
                continue  # recently passed — skip
            needs.append((age_hours, path))
        # Sort descending by age — oldest first
        needs.sort(key=lambda t: t[0], reverse=True)
        return [path for _, path in needs]


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _ledger_path(project_root: Path) -> Path:
    return project_root / ".thomas" / "evolve" / "health_ledger.json"


def load_health_ledger(project_root: Path) -> HealthLedger:
    """Load the ledger from disk, or create an empty one."""
    path = _ledger_path(project_root)
    if not path.exists():
        return HealthLedger()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return HealthLedger.from_dict(payload)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load health ledger, starting fresh: %s", exc)
        return HealthLedger()


def save_health_ledger(project_root: Path, ledger: HealthLedger) -> Path:
    """Persist the ledger to disk."""
    path = _ledger_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def scan_python_files(project_root: Path) -> list[dict[str, Any]]:
    """Scan all Python files under thomas/ and return path + line count."""
    thomas_root = project_root / "thomas"
    results: list[dict[str, Any]] = []
    if not thomas_root.exists():
        return results
    for py_file in thomas_root.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        rel = str(py_file.relative_to(project_root)).replace("\\", "/")
        try:
            line_count = len(py_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        results.append({"path": rel, "line_count": line_count})
    return results


def build_review_queue(
    project_root: Path,
    ledger: HealthLedger,
    *,
    max_age_hours: float = 168.0,
    min_lines: int = 100,
) -> list[dict[str, Any]]:
    """Build a prioritised queue of files needing review.

    Filters to files with at least *min_lines* (skips tiny __init__.py etc),
    then sorts by staleness — oldest / never-reviewed first.
    """
    all_files = scan_python_files(project_root)
    candidates = [f for f in all_files if f["line_count"] >= min_lines]
    paths = [f["path"] for f in candidates]
    ordered = ledger.prioritised_files(paths, max_age_hours=max_age_hours)
    lookup = {f["path"]: f for f in candidates}
    return [lookup[p] for p in ordered if p in lookup]
