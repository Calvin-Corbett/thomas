"""Filesystem storage for research-mode programs and experiment artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .research_models import ResearchProgramConfig, ResearchRunRecord, utc_now_iso

RESEARCH_ROOT = Path(".thomas") / "research"
CONFIG_FILE = "config.json"
PROGRAM_FILE = "program.md"
RUNS_DIR = "runs"
RUN_JSON = "run.json"
RUN_STDOUT = "stdout.log"
RUN_STDERR = "stderr.log"
RUN_PATCH = "diff.patch"

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_repo_root(repo_root: str | Path | None) -> Path:
    """Resolve the target repo root."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return root.expanduser().resolve()


def resolve_research_root(repo_root: str | Path | None) -> Path:
    """Return the research root for a repo."""
    return resolve_repo_root(repo_root) / RESEARCH_ROOT


def resolve_runs_dir(repo_root: str | Path | None) -> Path:
    """Return the runs directory for a repo."""
    return resolve_research_root(repo_root) / RUNS_DIR


def ensure_research_layout(repo_root: str | Path | None) -> Path:
    """Ensure research directories exist."""
    root = resolve_research_root(repo_root)
    runs_dir = root / RUNS_DIR
    runs_dir.mkdir(parents=True, exist_ok=True)
    return root


def has_research_program(repo_root: str | Path | None) -> bool:
    """Return whether a repo already has a research program."""
    return (resolve_research_root(repo_root) / CONFIG_FILE).exists()


def _slugify(text: str, *, fallback: str = "run") -> str:
    cleaned = _SAFE_RE.sub("-", str(text or "").strip()).strip("-").lower()
    return cleaned[:48] if cleaned else fallback


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def build_program_markdown(config: ResearchProgramConfig) -> str:
    """Render the editable research charter."""
    editable = config.editable_paths or ["<unrestricted>"]
    eval_command = config.evaluation_command or "<set with thomas research init --eval-cmd ...>"
    metric_source = config.metric_path or "<direct --metric-value or metric JSON path>"
    metric_key = config.metric_key or "<root value>"
    lines = [
        "# Research Program",
        "",
        "## Objective",
        config.objective,
        "",
        "## Evaluation Contract",
        f"- Metric: `{config.metric_name}`",
        f"- Goal: `{config.metric_goal}`",
        f"- Runtime budget (seconds): `{config.runtime_budget_seconds}`",
        f"- Baseline: `{config.baseline_value}`" if config.baseline_value is not None else "- Baseline: `<unset>`",
        f"- Evaluation command: `{eval_command}`",
        f"- Metric JSON path: `{metric_source}`",
        f"- Metric JSON key: `{metric_key}`",
        "",
        "## Editable Scope",
    ]
    for item in editable:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "## Rules",
            "- Keep changes inside the editable scope unless the operator updates the program.",
            "- Every run must produce an immutable artifact under `.thomas/research/runs/<run_id>/`.",
            "- Promote a run only after reviewing its metric and diff.",
            "- Reject runs that regress the frontier or drift outside the allowed scope.",
            "",
            "## Notes",
            "- Update this file when the mission, metric, or allowed paths change.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def init_research_program(
    repo_root: str | Path | None,
    config: ResearchProgramConfig,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    """Create or update a repo-local research program."""
    root = ensure_research_layout(repo_root)
    config_path = root / CONFIG_FILE
    program_path = root / PROGRAM_FILE
    if not overwrite:
        if config_path.exists():
            raise FileExistsError(f"research config already exists: {config_path}")
        if program_path.exists():
            raise FileExistsError(f"research program already exists: {program_path}")
    _write_json_atomic(config_path, config.to_dict())
    program_path.write_text(build_program_markdown(config), encoding="utf-8")
    return root, config_path, program_path


def load_research_config(repo_root: str | Path | None) -> ResearchProgramConfig:
    """Load a repo-local research program configuration."""
    config_path = resolve_research_root(repo_root) / CONFIG_FILE
    if not config_path.exists():
        raise FileNotFoundError(f"research config not found: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return ResearchProgramConfig.from_dict(payload)


def save_research_config(repo_root: str | Path | None, config: ResearchProgramConfig) -> Path:
    """Persist a repo-local research program configuration."""
    root = ensure_research_layout(repo_root)
    config.updated_at = utc_now_iso()
    config_path = root / CONFIG_FILE
    _write_json_atomic(config_path, config.to_dict())
    return config_path


def save_research_run(
    repo_root: str | Path | None,
    run: ResearchRunRecord,
    *,
    stdout_text: str = "",
    stderr_text: str = "",
    patch_text: str = "",
) -> Path:
    """Persist an experiment artifact directory."""
    resolved_root = resolve_repo_root(repo_root)
    runs_dir = resolve_runs_dir(resolved_root)
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runs_dir / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = run_dir / RUN_STDOUT
    stderr_path = run_dir / RUN_STDERR
    patch_path = run_dir / RUN_PATCH
    run.stdout_path = str(stdout_path.relative_to(resolved_root).as_posix())
    run.stderr_path = str(stderr_path.relative_to(resolved_root).as_posix())
    run.patch_path = str(patch_path.relative_to(resolved_root).as_posix())

    stdout_path.write_text(str(stdout_text or ""), encoding="utf-8")
    stderr_path.write_text(str(stderr_text or ""), encoding="utf-8")
    patch_path.write_text(str(patch_text or ""), encoding="utf-8")
    _write_json_atomic(run_dir / RUN_JSON, run.to_dict())
    return run_dir


def update_research_run(repo_root: str | Path | None, run: ResearchRunRecord) -> Path:
    """Update run metadata without touching the captured logs."""
    run_dir = resolve_runs_dir(repo_root) / run.run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"research run not found: {run_dir}")
    _write_json_atomic(run_dir / RUN_JSON, run.to_dict())
    return run_dir


def list_research_runs(repo_root: str | Path | None) -> list[ResearchRunRecord]:
    """Return all run artifacts sorted by creation time."""
    runs_dir = resolve_runs_dir(repo_root)
    if not runs_dir.exists():
        return []
    rows: list[ResearchRunRecord] = []
    for path in sorted(runs_dir.glob(f"*/{RUN_JSON}")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows.append(ResearchRunRecord.from_dict(payload))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    rows.sort(key=lambda row: (row.created_at, row.run_id), reverse=True)
    return rows


def resolve_run_record(repo_root: str | Path | None, run_token: str) -> ResearchRunRecord:
    """Resolve a run by exact id or unique prefix."""
    token = str(run_token or "").strip()
    if not token:
        raise ValueError("run id is required")
    runs = list_research_runs(repo_root)
    exact = [row for row in runs if row.run_id == token]
    if exact:
        return exact[0]
    matches = [row for row in runs if row.run_id.startswith(token)]
    if not matches:
        raise FileNotFoundError(f"research run not found: {token}")
    if len(matches) > 1:
        raise ValueError(f"research run prefix is ambiguous: {token}")
    return matches[0]


def metric_sort_key(metric_value: float | None, goal: str) -> tuple[int, float]:
    """Create a stable sort key for scoreboard rows."""
    if metric_value is None:
        return (1, 0.0)
    if goal == "minimize":
        return (0, float(metric_value))
    return (0, -float(metric_value))
