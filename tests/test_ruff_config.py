from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parent.parent


def test_ruff_ignore_list_has_no_removed_rule_ids() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignore = set(pyproject["tool"]["ruff"]["lint"]["ignore"])

    # Ruff removed this rule, so keeping it in ignore emits warning noise on every run.
    removed_rule_ids = {"UP038"}

    assert ignore.isdisjoint(removed_rule_ids)
