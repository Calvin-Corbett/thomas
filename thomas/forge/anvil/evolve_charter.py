"""Evolve charter, session store, and shared low-level helpers.

Split out of ``evolve.py`` (2026-07-15) to keep the runtime under the
MONOLITH_CEILING. ``evolve.py`` re-exports everything here, so existing
imports of ``thomas.forge.anvil.evolve`` keep working.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .doppelganger import find_project_root
from .evolve_verification import _normalize_acceptance_checks

DEFAULT_EVOLVE_OBJECTIVE = (
    "Continuously improve Thomas across reliability, UI polish, safety, latency, and maintainability."
)
DEFAULT_EVOLVE_GOAL = "Choose the single highest-leverage safe improvement you can implement right now, then verify it."
DEFAULT_EVOLVE_PRINCIPLES = [
    "Operate only in the green doppelganger mirror. Never assume blue/live edits are safe.",
    "Prefer user-visible improvements, reliability, and maintainability over novelty.",
    "Respect existing work. Do not revert unrelated edits or broaden scope without evidence.",
    "Run targeted verification before you stop, and leave clear evidence in artifacts.",
    "If verification fails, fix it or stop with an honest failure record instead of hand-waving.",
]
# Verification runs inside the green mirror, which intentionally has no .git.
# Exclude checks that need git history/baselines; the dependency-direction
# architecture checks still run, and commit-time gates still catch banned files.
DEFAULT_VERIFY_COMMANDS = [
    'python -m pytest tests/test_architecture.py -q -k "not test_no_new_legacy_files and not test_debt_trending"'
]
LEGACY_DEFAULT_VERIFY_COMMAND_SETS = {
    ('python -m pytest tests/test_architecture.py -q -k "not test_no_new_legacy_files"',),
    ("python -m pytest tests/test_architecture.py -x --tb=short -q",),
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvolveCharter:
    objective: str = DEFAULT_EVOLVE_OBJECTIVE
    default_goal: str = DEFAULT_EVOLVE_GOAL
    principles: list[str] = field(default_factory=lambda: list(DEFAULT_EVOLVE_PRINCIPLES))
    verify_commands: list[str] = field(default_factory=lambda: list(DEFAULT_VERIFY_COMMANDS))
    acceptance_checks: list[str] = field(default_factory=list)
    max_passes: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "acceptance_checks", _normalize_acceptance_checks(self.acceptance_checks))

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "default_goal": self.default_goal,
            "principles": list(self.principles),
            "verify_commands": list(self.verify_commands),
            "acceptance_checks": list(self.acceptance_checks),
            "max_passes": int(self.max_passes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> EvolveCharter:
        payload = dict(payload or {})
        principles = payload.get("principles")
        verify_commands = _normalize_verify_commands(payload.get("verify_commands"))
        return cls(
            objective=str(payload.get("objective") or DEFAULT_EVOLVE_OBJECTIVE),
            default_goal=str(payload.get("default_goal") or DEFAULT_EVOLVE_GOAL),
            principles=[str(x).strip() for x in (principles or []) if str(x).strip()]
            or list(DEFAULT_EVOLVE_PRINCIPLES),
            verify_commands=_current_default_if_legacy(verify_commands),
            acceptance_checks=_normalize_acceptance_checks(payload.get("acceptance_checks")),
            max_passes=max(1, min(int(payload.get("max_passes") or 1), 8)),
        )


def _normalize_verify_commands(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _current_default_if_legacy(commands: list[str]) -> list[str]:
    if not commands:
        return list(DEFAULT_VERIFY_COMMANDS)
    if tuple(commands) in LEGACY_DEFAULT_VERIFY_COMMAND_SETS:
        return list(DEFAULT_VERIFY_COMMANDS)
    return list(commands)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_repo_root(project_root: Path | None = None) -> Path:
    if project_root is None:
        return find_project_root().resolve()
    return Path(project_root).expanduser().resolve()


def resolve_evolve_root(project_root: Path | None = None) -> Path:
    return resolve_repo_root(project_root) / ".thomas" / "evolve"


def _charter_json_path(project_root: Path | None = None) -> Path:
    return resolve_evolve_root(project_root) / "charter.json"


def _charter_markdown_path(project_root: Path | None = None) -> Path:
    return resolve_evolve_root(project_root) / "charter.md"


def _sessions_root(project_root: Path | None = None) -> Path:
    return resolve_evolve_root(project_root) / "sessions"


def has_evolve_charter(project_root: Path | None = None) -> bool:
    return _charter_json_path(project_root).exists()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_relpath(value: str | Path) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def build_charter_markdown(charter: EvolveCharter) -> str:
    lines = [
        "# Thomas Evolve Charter",
        "",
        f"## Objective\n{charter.objective}",
        "",
        f"## Default Goal\n{charter.default_goal}",
        "",
        "## Principles",
    ]
    lines.extend(f"- {item}" for item in charter.principles)
    lines.append("")
    lines.append("## Verification")
    lines.extend(f"- `{cmd}`" for cmd in charter.verify_commands)
    lines.append("")
    lines.append("## Acceptance Checks")
    if charter.acceptance_checks:
        lines.extend(f"- `{check}`" for check in charter.acceptance_checks)
    else:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Max Passes\n{int(charter.max_passes)}")
    return "\n".join(lines).strip() + "\n"


def ensure_evolve_charter(
    project_root: Path | None = None,
    charter: EvolveCharter | None = None,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    repo_root = resolve_repo_root(project_root)
    evolve_root = resolve_evolve_root(repo_root)
    json_path = _charter_json_path(repo_root)
    markdown_path = _charter_markdown_path(repo_root)
    if json_path.exists() and not overwrite:
        return evolve_root, json_path, markdown_path
    next_charter = charter or EvolveCharter()
    evolve_root.mkdir(parents=True, exist_ok=True)
    _sessions_root(repo_root).mkdir(parents=True, exist_ok=True)
    _write_json(json_path, next_charter.to_dict())
    _write_text(markdown_path, build_charter_markdown(next_charter))
    return evolve_root, json_path, markdown_path


def load_evolve_charter(project_root: Path | None = None) -> EvolveCharter:
    repo_root = resolve_repo_root(project_root)
    json_path = _charter_json_path(repo_root)
    if not json_path.exists():
        ensure_evolve_charter(repo_root)
    return EvolveCharter.from_dict(_read_json(json_path))


def list_evolve_sessions(project_root: Path | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    root = _sessions_root(project_root)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name, reverse=True):
        if not path.is_dir():
            continue
        payload_path = path / "session.json"
        if not payload_path.exists():
            continue
        try:
            rows.append(_read_json(payload_path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable evolve session metadata %s: %s", payload_path, exc)
            continue
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def load_latest_evolve_session(project_root: Path | None = None) -> dict[str, Any] | None:
    rows = list_evolve_sessions(project_root, limit=1)
    return rows[0] if rows else None


def load_evolve_session(project_root: Path | None, session_token: str) -> dict[str, Any]:
    root = _sessions_root(project_root)
    token = str(session_token or "").strip()
    if not token:
        raise RuntimeError("session_id is required")
    exact = root / token / "session.json"
    if exact.exists():
        return _read_json(exact)
    matches = sorted(root.glob(f"{token}*/session.json"), key=lambda item: item.parent.name, reverse=True)
    if not matches:
        raise RuntimeError(f"evolve session '{token}' was not found")
    return _read_json(matches[0])
