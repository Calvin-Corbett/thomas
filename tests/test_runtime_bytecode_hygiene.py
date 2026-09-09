from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_runtime_launchers_disable_repo_bytecode_writes() -> None:
    assert 'PYTHONDONTWRITEBYTECODE = "1"' in _read("scripts/run-ui.ps1")
    assert 'PYTHONDONTWRITEBYTECODE", "1"' in _read("sitecustomize.py")
