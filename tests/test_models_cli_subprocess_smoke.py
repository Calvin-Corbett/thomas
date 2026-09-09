from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _write_min_config(path: Path) -> Path:
    cfg = path / "thomas.toml"
    cfg.write_text(
        """
default_model = "local"

[memory]
root = "./runtime"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:9/v1"
model = "qwen2.5-coder:7b"
""".strip(),
        encoding="utf-8",
    )
    return cfg


def _run_cli(repo_root: Path, cfg: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "thomas", "-c", str(cfg), "models", *args]
    return subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def test_models_scan_subprocess_has_no_raw_traceback(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = _write_min_config(tmp_path)

    result = _run_cli(repo_root, cfg, "scan", "--timeout", "1")
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode == 0, output
    assert "Traceback" not in output
    assert "Context' object is not iterable" not in output


def test_models_scan_and_discover_subprocess_parity(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = _write_min_config(tmp_path)

    scan = _run_cli(repo_root, cfg, "scan", "--timeout", "1")
    discover = _run_cli(repo_root, cfg, "discover", "--timeout", "1")

    scan_output = f"{scan.stdout}\n{scan.stderr}"
    discover_output = f"{discover.stdout}\n{discover.stderr}"

    assert scan.returncode == discover.returncode, (scan_output, discover_output)
    assert scan.stdout == discover.stdout, (scan_output, discover_output)
    assert "Traceback" not in scan_output
    assert "Traceback" not in discover_output
