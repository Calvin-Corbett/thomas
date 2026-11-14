"""Freeze output requirements before generation, then verify the actual files."""

from pathlib import Path

import pytest

from thomas.core import acceptance_contract as ac


def outputs(prompt: str, root: Path):
    return [item for item in ac.build_contract(prompt, root) if item.kind == ac.KIND_OUTPUT_PATH]


def test_nested_data_reference_does_not_require_a_dummy_root_copy(
    tmp_path: Path,
) -> None:
    items = outputs("Create dashboard/quotes.json. The dashboard fetches quotes.json.", tmp_path)
    assert [item.target for item in items] == [str(tmp_path / "dashboard/quotes.json")]
    assert not ac.evaluate_contract(items, workspace=tmp_path)[0].satisfied
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard/quotes.json").write_text('{"stations": [1]}', encoding="utf-8")
    checked = ac.evaluate_contract(items, workspace=tmp_path)
    assert all(item.checked and item.satisfied for item in checked)
    assert not (tmp_path / "quotes.json").exists()


@pytest.mark.parametrize("root_name", ["./quotes.json", "`quotes.json`"])
def test_explicit_root_output_remains_required(tmp_path: Path, root_name: str) -> None:
    items = outputs(f"Create dashboard/quotes.json and {root_name}.", tmp_path)
    assert {item.target for item in items} == {
        str(tmp_path / "dashboard/quotes.json"),
        str(tmp_path / "quotes.json"),
    }
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard/quotes.json").write_text("{}", encoding="utf-8")
    checked = ac.evaluate_contract(items, workspace=tmp_path)
    assert sum(item.satisfied for item in checked) == 1


def test_distinct_qualified_outputs_are_not_collapsed(tmp_path: Path) -> None:
    items = outputs(
        "Write desktop/quotes.json and mobile/quotes.json; both consume quotes.json.",
        tmp_path,
    )
    assert {item.target for item in items} == {
        str(tmp_path / "desktop/quotes.json"),
        str(tmp_path / "mobile/quotes.json"),
    }


def test_unqualified_output_without_a_qualified_reference_is_required(
    tmp_path: Path,
) -> None:
    items = outputs("Write quotes.json with verified results.", tmp_path)
    assert [item.target for item in items] == [str(tmp_path / "quotes.json")]


@pytest.mark.parametrize("before", [None, "", "existing HTML"])
def test_owned_output_is_required_even_when_bare_or_already_present(tmp_path: Path, before: str | None) -> None:
    if before is not None:
        (tmp_path / "index.html").write_text(before, encoding="utf-8")
    prompt = "Create index.html. It must load styles.css and js/game.js with defer."
    items = ac.build_contract(prompt, tmp_path, owned_output="index.html")
    assigned = [item for item in items if item.kind == ac.KIND_OUTPUT_PATH]
    assert [item.target for item in assigned] == [str(tmp_path / "index.html")]
    assert assigned[0].source == "assignment"
    checked = ac.evaluate_contract(assigned, workspace=tmp_path)
    assert checked[0].checked and checked[0].satisfied is bool(before)
    (tmp_path / "index.html").write_text('<script src="js/game.js" defer></script>', encoding="utf-8")
    assert all(item.satisfied for item in ac.evaluate_contract(assigned, workspace=tmp_path))
    assert not (tmp_path / "js/game.js").exists()
    assert not (tmp_path / "styles.css").exists()


def test_owned_output_scope_preserves_context_commands_and_semantic_requirements(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.json").write_text('{"speed_count": 2}', encoding="utf-8")
    prompt = "Create index.html using config.json. It must load js/game.js. Run `python verify.py`."
    learned = [
        ac.ContractItem(
            "output:old.js",
            ac.KIND_OUTPUT_PATH,
            "Prior dependency",
            target=str(tmp_path / "old.js"),
        ),
        ac.ContractItem("remember:labels", ac.KIND_LEARNED, "Keep accessible labels"),
    ]
    options = {"learned": ac.items_to_dicts(learned)}
    ordinary = ac.build_contract(prompt, tmp_path, **options)
    assigned = ac.build_contract(prompt, tmp_path, owned_output="index.html", **options)
    assert [item.to_dict() for item in assigned if item.kind != ac.KIND_OUTPUT_PATH] == [
        item.to_dict() for item in ordinary if item.kind != ac.KIND_OUTPUT_PATH
    ]
    assert {item.kind for item in assigned} >= {
        ac.KIND_DATA_FIELD,
        ac.KIND_COMMAND,
        ac.KIND_REQUIREMENT,
        ac.KIND_LEARNED,
    }
    assert [item.target for item in assigned if item.kind == ac.KIND_OUTPUT_PATH] == [str(tmp_path / "index.html")]
    assert {item.target for item in ordinary if item.kind == ac.KIND_OUTPUT_PATH} == {
        str(tmp_path / "js/game.js"),
        str(tmp_path / "old.js"),
    }


def test_owned_target_does_not_resolve_to_another_file_with_the_same_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "other").mkdir()
    (tmp_path / "other/index.html").write_text("another helper's page", encoding="utf-8")
    items = ac.build_contract("Create docs/index.html.", tmp_path, owned_output="docs/index.html")
    assigned = [item for item in items if item.kind == ac.KIND_OUTPUT_PATH]
    assert [item.target for item in assigned] == [str(tmp_path / "docs/index.html")]
    assert not ac.evaluate_contract(assigned, workspace=tmp_path)[0].satisfied


def test_ordinary_project_contract_still_requires_all_named_outputs(
    tmp_path: Path,
) -> None:
    prompt = "Create pages/index.html. It must load js/game.js and `styles.css`."
    items = outputs(prompt, tmp_path)
    assert {item.target for item in items} == {
        str(tmp_path / "pages/index.html"),
        str(tmp_path / "js/game.js"),
        str(tmp_path / "styles.css"),
    }
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages/index.html").write_text("a page", encoding="utf-8")
    checked = ac.evaluate_contract(items, workspace=tmp_path)
    assert set(ac.contract_verdict(checked).unmet) == {
        "output:js/game.js",
        "output:styles.css",
    }
