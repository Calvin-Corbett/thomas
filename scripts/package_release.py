#!/usr/bin/env python3
"""Create a GitHub-safe product release bundle."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

try:
    from importlib import metadata as importlib_metadata
except ModuleNotFoundError:  # pragma: no cover
    import importlib_metadata  # type: ignore

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_PREFIXES = (
    ".git/",
    ".venv/",
    ".thomas/",
    ".claude/",
    ".playwright-cli/",
    ".feature_backups/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "runtime/",
    "output/",
    "tmp/",
    "tmp.patch/",
    "logs/",
    "artifacts/",
    "dist/",
    "node_modules/",
    "pack/",
    "patches/",
    "Inbox/",
    "inbox/",
    "tasks/",
    "plans/",
    "code_intake/",
    "demo/agentic-runs/",
    "library/entries/",
    "library/entries/research-notes/",
    "reference_cli_gap_runs/",
    "Installed_Features/",
    "temp_swarm/",
    "_archive/",
    "archives/",
)

EXCLUDE_PATHS = (
    ".github/pull_request_template.md",
    "definitions/model-vs-os.md",
    "docs/deletion_policy.md",
    "docs/chat_control_protocol.md",
    "docs/evidence_pack_runbook.md",
    "docs/evals/2026-02-21_webui_natural_behavior_eval.md",
    "docs/feature_13_dep_scanner.md",
    "docs/launch/launch_gate_scoreboard_2026-02-25.md",
    "docs/migration_notes_workspace_rbac_multi_tenant.md",
    "docs/mission_control_ux_blueprint.md",
    "docs/ops/docker_deploy.md",
    "docs/ops/focus_program_operating_model.md",
    "docs/ops/gateway_security_runbook.md",
    "docs/ops/monolith_baseline_approvals.md",
    "docs/ops/next_agent_handoff.md",
    "docs/ops/competitor_deep_dive_attention_2026-02-25.md",
    "docs/ops/security_program_cadence.md",
    "docs/website_release_flow.md",
    "docs/placeholder_completion_policy.md",
    "docs/release/release_notes_0.11.73.md",
    "docs/surface_parity_protocol.md",
    "thomas/server/web/accessibility_quick_start.md",
    "thomas/agent/guardrails.md",
    "thomas/core/guardrails.md",
)

EXCLUDE_GLOBS = (
    ".inbox_extract*",
    ".tmp*",
    "tmp_*.py",
    "tmp_*.js",
    "tmp*.js",
    "*.log",
    "*.tmp",
    "*.tmp*",
    "*.swp",
    "*.sqlite3",
    "*.sqlite3-*",
    "*.db",
    "*.db-*",
    "*.egg-info/*",
    "*/*.egg-info/*",
    "__pycache__/*",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "tmp_companion_*.png",
    "thomas_test_report_*.md",
)

EXCLUDE_EXACT = {
    "nul",
    "=",
    "=%",
    "=*",
    "tmp.patch",
    "server_output.txt",
    "response.txt",
    "response2.txt",
    "server_stderr.log",
    "server_stdout.log",
    "thomas_state.json",
    "thomas_tool_registry.json",
    "thomas_webhooks.json.lock",
    "thomas_test_results.jsonl",
    "thomas_search.db",
    "thomas.db",
    "thomas.db-shm",
    "thomas.db-wal",
    "thomas.marketplace.asset_studio.db",
    "thomas.marketplace.asset_studio.db-shm",
    "thomas.marketplace.asset_studio.db-wal",
    "secrets.json",
    ".tmp_patch.txt",
    ".task-manager-loop.err",
    ".task-manager-loop.log",
    ".task-manager-loop2.err",
    ".task-manager-loop2.log",
    "thomas_smoke_stderr.txt",
    "thomas_smoke_stdout.txt",
}

DEFAULT_NOTICE_FILENAME = "THIRD_PARTY_NOTICES.md"
DEFAULT_MANIFEST_FILENAME = "RELEASE_MANIFEST.json"
DEFAULT_SUMMARY_FILENAME = "RELEASE_SUMMARY.md"
RELEASE_ENSURE_FILES = ("LICENSE",)


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").strip("/")


def _project_version() -> str:
    try:
        pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not read pyproject.toml: {exc}") from exc
    try:
        data = tomllib.loads(pyproject_text)
    except (TypeError, ValueError) as exc:  # pragma: no cover
        raise RuntimeError(f"invalid pyproject.toml: {exc}") from exc
    return str((data.get("project") or {}).get("version") or "").strip()


def _git_ls_files(git_args: Sequence[str]) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", *git_args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git command not found") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git ls-files failed: {exc.stderr.strip()}") from exc

    lines: list[str] = []
    for raw in proc.stdout.splitlines():
        rel = _normalize_path(raw)
        if rel:
            lines.append(rel)
    return lines


def _iter_candidates(include_untracked: bool) -> tuple[list[str], list[str]]:
    tracked = _git_ls_files([])
    candidates = set(tracked)
    if include_untracked:
        untracked = _git_ls_files(["--others", "--exclude-standard"])
        candidates.update(untracked)
    return sorted(candidates), tracked


_DEPENDENCY_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.+-]+)")


def _dependency_name(spec: str) -> str:
    cleaned = str(spec or "").split(";", 1)[0].strip()
    if not cleaned:
        return ""
    if "[" in cleaned:
        cleaned = cleaned.split("[", 1)[0]
    match = _DEPENDENCY_LINE_RE.match(cleaned)
    if match:
        return match.group(1).strip().replace("_", "-")
    return ""


def _extract_dependency_names() -> set[str]:
    try:
        pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        data = tomllib.loads(pyproject_text)
    except (OSError, TypeError, ValueError):
        return set()

    dependencies: set[str] = set()
    project = data.get("project") or {}
    for raw in project.get("dependencies", []) or []:
        dep = _dependency_name(str(raw))
        if dep:
            dependencies.add(dep.lower())
    for section in (project.get("optional-dependencies") or {}).values():
        for raw in section:
            dep = _dependency_name(str(raw))
            if dep:
                dependencies.add(dep.lower())
    return dependencies


def _find_distribution(name: str):
    try:
        return importlib_metadata.distribution(name)
    except importlib_metadata.PackageNotFoundError:
        normalized = name.replace("_", "-").lower()
        for dist in importlib_metadata.distributions():
            dist_name = dist.metadata.get("Name", "").replace("_", "-").lower()
            if dist_name == normalized:
                return dist
        return None


def _license_from_metadata(meta) -> str:
    explicit = meta.get("License") if meta is not None else ""
    if explicit:
        return explicit.strip()
    classifiers = [item.strip() for item in (meta.get_all("Classifier") if meta else []) if item]
    for item in classifiers:
        if item.lower().startswith("license ::"):
            return item.split("::", 1)[1].strip()
    return "license metadata not available"


def _project_url_from_metadata(meta) -> str:
    home = meta.get("Home-page") if meta is not None else ""
    if home:
        return home.strip()
    urls = meta.get_all("Project-URL") if meta is not None else []
    if urls:
        return str(urls[0]).split(",", 1)[-1].strip()
    return "not listed"


def _generate_third_party_notices(bundle_root: Path) -> Path:
    lines = [
        "# Third-Party Notices",
        "",
        "This release includes third-party dependencies and optional integrations.",
        "The project itself is provided under the MIT license in LICENSE.",
        "",
        "Licenses below are pulled from installed package metadata when available.",
        "",
        "## Direct package dependencies",
        "",
    ]
    missing: list[str] = []
    for dep in sorted(_extract_dependency_names()):
        dist = _find_distribution(dep)
        if dist is None:
            missing.append(dep)
            lines.append(f"- {dep}: metadata unavailable (not installed in this environment)")
            continue
        meta = dist.metadata
        version = dist.version
        lines.append(
            f"- {meta.get('Name', dep)} {version}: {_license_from_metadata(meta)}; "
            f"source: {_project_url_from_metadata(meta)}"
        )

    lines.extend(
        [
            "",
            "## Optional dependencies used by this release pipeline",
            "",
        ]
    )
    optional_requirements = ROOT / "thomas" / "optional_requirements.txt"
    optional_deps = (
        sorted(optional_requirements.read_text(encoding="utf-8").splitlines()) if optional_requirements.exists() else []
    )
    for dep in optional_deps:
        dep_name = _dependency_name(dep)
        if not dep_name or dep_name.lower() in _extract_dependency_names():
            continue
        dist = _find_distribution(dep_name)
        if dist is None:
            lines.append(f"- {dep_name}: metadata unavailable (not installed in this environment)")
            continue
        meta = dist.metadata
        lines.append(
            f"- {meta.get('Name', dep_name)}: {_license_from_metadata(meta)}; "
            f"source: {_project_url_from_metadata(meta)}"
        )

    if missing:
        lines.extend(
            [
                "",
                "## Note",
                "",
                "Some dependencies were not available in this environment when the release package was generated.",
                "Verify licenses manually before distributing binaries.",
                "",
                "Missing dependencies:",
                "",
            ]
        )
        lines.extend(f"- {name}" for name in sorted(missing))

    path = bundle_root / DEFAULT_NOTICE_FILENAME
    path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    return path


def _is_excluded(path: str) -> str | None:
    normalized = _normalize_path(path).lower()
    if not normalized:
        return "empty"
    if normalized in EXCLUDE_PATHS:
        return f"exact:{normalized}"
    for prefix in EXCLUDE_PREFIXES:
        p = prefix.lower().rstrip("/")
        if normalized == p or normalized.startswith(f"{p}/"):
            return f"prefix:{prefix}"

    base = Path(normalized).name
    if base in EXCLUDE_EXACT:
        return f"exact:{base}"
    if base.startswith(".env.") and base != ".env.example":
        return f"exact:{base}"
    for pattern in EXCLUDE_GLOBS:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(base, pattern):
            return f"glob:{pattern}"
    return None


def _copy_to_stage(paths: list[str], stage_dir: Path) -> tuple[int, list[str]]:
    copied = 0
    skipped: list[str] = []
    for rel in sorted(paths):
        source = ROOT / rel
        target = stage_dir / rel
        if not source.exists():
            skipped.append(rel)
            continue
        if source.is_symlink():
            skipped.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied, skipped


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(
    stage_dir: Path, included: list[str], excluded: list[tuple[str, str]], generated_version: str
) -> Path:
    files: list[dict[str, object]] = []
    for rel in sorted(included):
        file_path = stage_dir / rel
        if file_path.is_file():
            stat = file_path.stat()
            files.append(
                {
                    "path": rel.replace("\\", "/"),
                    "size": int(stat.st_size),
                    "sha256": _file_sha256(file_path),
                }
            )
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_version": generated_version,
        "root": str(ROOT),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "files": files,
        "excluded": [{"path": path, "reason": reason} for path, reason in excluded],
    }
    manifest_path = stage_dir / DEFAULT_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def _write_summary(stage_dir: Path, version: str, included: list[str], excluded: list[tuple[str, str]]) -> Path:
    excluded_by_reason: dict[str, int] = {}
    for _, reason in excluded:
        excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1
    lines = [
        "# Thomas User Release Bundle",
        "",
        "This package is filtered for public/GitHub deployment and removes local runtime artifacts, plans, tasks, and private context.",
        "",
        f"Release version: {version}",
        f"Included files: {len(included)}",
        f"Excluded items: {len(excluded)}",
        "",
        "## Exclusions by reason",
        "",
    ]
    for reason in sorted(excluded_by_reason):
        lines.append(f"- {reason}: {excluded_by_reason[reason]}")
    lines.extend(
        [
            "",
            "Included this bundle:",
            "- LICENSE",
            "- THIRD_PARTY_NOTICES.md",
            "- RELEASE_MANIFEST.json",
            "- RELEASE_SUMMARY.md",
            "",
        ]
    )
    summary_path = stage_dir / DEFAULT_SUMMARY_FILENAME
    summary_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
    return summary_path


def _zip_stage(stage_dir: Path, out_dir: Path, name: str) -> Path:
    zip_path = out_dir / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(stage_dir.rglob("*")):
            if not path.is_file():
                continue
            arcname = str(path.relative_to(stage_dir)).replace("\\", "/")
            zf.write(path, arcname)
    return zip_path


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a GitHub-safe release bundle.")
    parser.add_argument("--version", default=None, help="Release version (defaults to pyproject version).")
    parser.add_argument("--out-dir", default="dist/github-release", help="Output directory.")
    parser.add_argument(
        "--name",
        default=None,
        help="Release bundle directory/basename (defaults to thomas-user-release-<version>).",
    )
    parser.add_argument(
        "--include-untracked",
        dest="include_untracked",
        action="store_true",
        help="Include untracked files from git status (default excludes untracked content).",
    )
    parser.add_argument(
        "--no-untracked",
        dest="include_untracked",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(include_untracked=False)
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Build only the staged directory (skip zip).",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print candidate counts without creating files.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable summary JSON.")
    args = parser.parse_args(argv)

    version = args.version or _project_version()
    if not version:
        raise SystemExit("Release version could not be determined.")

    release_name = args.name or f"thomas-user-release-{version}"
    out_dir = (ROOT / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates, tracked_only = _iter_candidates(include_untracked=bool(args.include_untracked))
    included: list[str] = []
    excluded: list[tuple[str, str]] = []
    for rel in candidates:
        reason = _is_excluded(rel)
        if reason:
            excluded.append((rel, reason))
            continue
        source = ROOT / rel
        if source.is_file():
            included.append(rel)
    for required in RELEASE_ENSURE_FILES:
        if required in included:
            continue
        required_path = ROOT / required
        if required_path.exists() and required_path.is_file():
            included.append(required)

    payload = {
        "version": version,
        "out_dir": str(out_dir),
        "release_name": release_name,
        "total_candidates": len(candidates),
        "tracked_files": len(tracked_only),
        "include_untracked": bool(args.include_untracked),
        "selected_included": len(included),
        "selected_excluded": len(excluded),
    }
    if args.preview:
        payload["preview"] = True
        print(json.dumps(payload, sort_keys=True))
        return 0

    stage_dir = out_dir / release_name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    copied_count, skipped = _copy_to_stage(included, stage_dir)
    if skipped:
        payload["skipped_missing_or_symlink"] = skipped

    notice_path = _generate_third_party_notices(stage_dir)
    summary_path = _write_summary(stage_dir, version, included, excluded)
    manifest_includes = sorted(
        included
        + [
            str(notice_path.relative_to(stage_dir)),
            str(summary_path.relative_to(stage_dir)),
        ]
    )
    manifest_path = _build_manifest(stage_dir, manifest_includes, excluded, version)
    included.extend(
        [
            str(notice_path.relative_to(stage_dir)),
            str(manifest_path.relative_to(stage_dir)),
            str(summary_path.relative_to(stage_dir)),
        ]
    )

    zip_path = _zip_stage(stage_dir, out_dir, release_name) if not args.no_zip else None

    payload["output_dir"] = str(stage_dir)
    payload["manifest"] = str(manifest_path.relative_to(out_dir))
    payload["summary"] = str(summary_path.relative_to(out_dir))
    payload["notice"] = str(notice_path.relative_to(out_dir))
    payload["copied_files"] = copied_count
    payload["zip_path"] = str(zip_path) if zip_path else ""

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"Release bundle: {stage_dir}")
        print(f"- version: {version}")
        print(f"- included files: {copied_count}")
        print(f"- excluded files: {len(excluded)}")
        if zip_path:
            print(f"- zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
