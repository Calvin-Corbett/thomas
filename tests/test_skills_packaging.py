from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _skill_dirs() -> set[str]:
    return {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()}


def test_manifest_includes_top_level_skills() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include skills *" in manifest


def test_pyproject_data_files_include_all_skill_dirs() -> None:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    data_files = ((payload.get("tool") or {}).get("setuptools") or {}).get("data-files") or {}
    expected = _skill_dirs()
    actual = {key.split("/", 1)[1] for key in data_files if key.startswith("skills/")}
    assert actual == expected
    for name in expected:
        assert (ROOT / "skills" / name / "SKILL.md").exists()
