"""Artifact proof helpers for the Exhaustive runtime."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath


def _expected_paths(values: Sequence[object] | None) -> tuple[list[str], int]:
    expected: list[str] = []
    invalid_count = 0
    for value in values or ():
        raw = str(value or "").strip().replace("\\", "/")
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or Path(raw).is_absolute() or ".." in path.parts:
            invalid_count += 1
            continue
        normalized = path.as_posix().removeprefix("./").casefold()
        if normalized and normalized not in expected:
            expected.append(normalized)
    return expected, invalid_count


def _artifact_evidence(
    expected_artifacts: Sequence[object] | None,
    work_dir: str,
) -> tuple[bool, list[str], list[str]]:
    """Read back nonempty artifacts named by a structured task contract."""

    expected, invalid_count = _expected_paths(expected_artifacts)
    root = Path(work_dir)
    if not root.is_dir():
        return False, [], ["workspace_missing"]
    # Hidden-file test against the path WITHIN the workspace. Against the
    # absolute path any dotted ancestor disqualified everything below it -- and
    # Thomas keeps his workspaces under ~/.thomas -- so the evidence list came
    # back empty and a run that produced real artifacts could not prove it.
    rows = [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]
    relative = {path.relative_to(root).as_posix().casefold(): path for path in rows}
    evidence = sorted(relative)
    issues: list[str] = ["invalid_expected_path"] * invalid_count

    for name in expected:
        if name not in relative and not any(path.endswith("/" + name) for path in relative):
            issues.append(f"missing:{name}")
    for name, path in relative.items():
        try:
            if path.stat().st_size <= 0:
                issues.append(f"empty:{name}")
            elif name.endswith(".pdf") and not path.read_bytes().startswith(b"%PDF"):
                issues.append(f"invalid_pdf:{name}")
        except OSError:
            issues.append(f"unreadable:{name}")
    return bool(relative) and not issues, evidence, issues
