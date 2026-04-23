"""Charter and session storage helpers for evolve mode."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
DEFAULT_VERIFY_COMMANDS = ["python -m pytest tests/test_architecture.py -q"]


@dataclass(frozen=True)
class EvolveCharter:
    objective: str = DEFAULT_EVOLVE_OBJECTIVE
    default_goal: str = DEFAULT_EVOLVE_GOAL
    principles: list[str] = field(default_factory=lambda: list(DEFAULT_EVOLVE_PRINCIPLES))
    verify_commands: list[str] = field(default_factory=lambda: list(DEFAULT_VERIFY_COMMANDS))
    max_passes: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "default_goal": self.default_goal,
            "principles": list(self.principles),
            "verify_commands": list(self.verify_commands),
            "max_passes": int(self.max_passes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> EvolveCharter:
        payload = dict(payload or {})
        principles = payload.get("principles")
        verify_commands = payload.get("verify_commands")
        return cls(
            objective=str(payload.get("objective") or DEFAULT_EVOLVE_OBJECTIVE),
            default_goal=str(payload.get("default_goal") or DEFAULT_EVOLVE_GOAL),
            principles=[str(x).strip() for x in (principles or []) if str(x).strip()]
            or list(DEFAULT_EVOLVE_PRINCIPLES),
            verify_commands=[str(x).strip() for x in (verify_commands or []) if str(x).strip()]
            or list(DEFAULT_VERIFY_COMMANDS),
            max_passes=max(1, min(int(payload.get("max_passes") or 1), 8)),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_repo_root(*, project_root: Path | None, find_project_root) -> Path:
    if project_root is None:
        return find_project_root().resolve()
    return Path(project_root).expanduser().resolve()


def resolve_evolve_root(*, repo_root: Path) -> Path:
    return repo_root / ".thomas" / "evolve"


def _charter_json_path(*, repo_root: Path) -> Path:
    return resolve_evolve_root(repo_root=repo_root) / "charter.json"


def _charter_markdown_path(*, repo_root: Path) -> Path:
    return resolve_evolve_root(repo_root=repo_root) / "charter.md"


def _sessions_root(*, repo_root: Path) -> Path:
    return resolve_evolve_root(repo_root=repo_root) / "sessions"


def has_evolve_charter(*, repo_root: Path) -> bool:
    return _charter_json_path(repo_root=repo_root).exists()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    lines.append(f"## Max Passes\n{int(charter.max_passes)}")
    return "\n".join(lines).strip() + "\n"


def ensure_evolve_charter(*, repo_root: Path, charter: EvolveCharter | None = None, overwrite: bool = False) -> tuple[Path, Path, Path]:
    evolve_root = resolve_evolve_root(repo_root=repo_root)
    json_path = _charter_json_path(repo_root=repo_root)
    markdown_path = _charter_markdown_path(repo_root=repo_root)
    if json_path.exists() and not overwrite:
        return evolve_root, json_path, markdown_path
    next_charter = charter or EvolveCharter()
    evolve_root.mkdir(parents=True, exist_ok=True)
    _sessions_root(repo_root=repo_root).mkdir(parents=True, exist_ok=True)
    _write_json(json_path, next_charter.to_dict())
    _write_text(markdown_path, build_charter_markdown(next_charter))
    return evolve_root, json_path, markdown_path


def load_evolve_charter(*, repo_root: Path) -> EvolveCharter:
    json_path = _charter_json_path(repo_root=repo_root)
    if not json_path.exists():
        ensure_evolve_charter(repo_root=repo_root)
    return EvolveCharter.from_dict(_read_json(json_path))


def list_evolve_sessions(*, repo_root: Path, limit: int = 20) -> list[dict[str, Any]]:
    root = _sessions_root(repo_root=repo_root)
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
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def load_latest_evolve_session(*, repo_root: Path) -> dict[str, Any] | None:
    rows = list_evolve_sessions(repo_root=repo_root, limit=1)
    return rows[0] if rows else None


def load_evolve_session(*, repo_root: Path, session_token: str) -> dict[str, Any]:
    root = _sessions_root(repo_root=repo_root)
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
