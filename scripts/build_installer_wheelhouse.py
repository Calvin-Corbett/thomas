#!/usr/bin/env python3
"""Build the offline dependency wheelhouse bundled into the Windows installer."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WINDOWS_PYTHON_VERSIONS = ("310", "311", "312", "313")


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _installer_requirements(pyproject: dict[str, Any]) -> list[str]:
    project = pyproject["project"]
    optional = project.get("optional-dependencies", {})
    build_system = pyproject.get("build-system", {})

    requirements: list[str] = []
    requirements.extend(str(item) for item in build_system.get("requires", []))
    requirements.extend(["pip", "wheel"])
    requirements.extend(str(item) for item in project.get("dependencies", []))
    requirements.extend(str(item) for item in optional.get("server", []))
    requirements.extend(str(item) for item in optional.get("repl", []))
    # pip download evaluates environment markers against the build interpreter in
    # this cross-version mode, so include the Python 3.10 compatibility wheel
    # explicitly. Python 3.11+ will simply ignore it during install.
    requirements.append("tomli==2.0.1")

    seen: set[str] = set()
    deduped: list[str] = []
    for requirement in requirements:
        normalized = requirement.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _run_download(dest: Path, requirements_file: Path, python_version: str, platform: str) -> None:
    abi = f"cp{python_version}"
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(dest),
        "--requirement",
        str(requirements_file),
        "--only-binary=:all:",
        "--platform",
        platform,
        "--implementation",
        "cp",
        "--python-version",
        python_version,
        "--abi",
        abi,
    ]
    print("[thomas] downloading installer wheelhouse for cp{0} {1}".format(python_version, platform))
    subprocess.run(cmd, cwd=ROOT, check=True)


def build_wheelhouse(dest: Path, python_versions: list[str], platform: str) -> dict[str, Any]:
    pyproject = _load_pyproject()
    requirements = _installer_requirements(pyproject)

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    requirements_file = dest / "requirements.txt"
    requirements_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")

    for python_version in python_versions:
        _run_download(dest, requirements_file, python_version, platform)

    wheels = sorted(path.name for path in dest.glob("*.whl"))
    if not wheels:
        raise RuntimeError("wheelhouse build produced no wheel files")

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "platform": platform,
        "python_versions": python_versions,
        "requirement_count": len(requirements),
        "wheel_count": len(wheels),
        "requirements": requirements,
        "wheels": wheels,
    }
    (dest / "WHEELHOUSE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (dest / "README.txt").write_text(
        "\n".join(
            [
                "Thomas Windows installer offline wheelhouse",
                "",
                "These wheels let first-run setup install Thomas dependencies without downloading from PyPI.",
                "The first-run wizard falls back to the online package index only if this bundle cannot be used.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, help="Destination directory for downloaded wheels")
    parser.add_argument(
        "--python-version",
        action="append",
        default=[],
        help="CPython version tag to download for, for example 312. Repeatable.",
    )
    parser.add_argument("--platform", default="win_amd64", help="Wheel platform tag")
    args = parser.parse_args(argv)

    python_versions = args.python_version or list(DEFAULT_WINDOWS_PYTHON_VERSIONS)
    manifest = build_wheelhouse(Path(args.dest), python_versions, args.platform)
    print(
        "[thomas] wheelhouse ready: {0} wheels for {1}".format(
            manifest["wheel_count"],
            ", ".join(manifest["python_versions"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
