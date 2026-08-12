"""Thomas is selectable on purpose -- and unreachable by accident.

The reported regression was a Code task binding Thomas's own source tree when no
project was chosen. The intended behaviour is not "never bind Thomas" -- Thomas
editing himself is legitimate -- it is that doing so must be a deliberate click,
never what you fall into by not choosing.

Every test below is really one assertion: does this input reach Thomas's source,
and did the caller actually ask for it?
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects
from thomas.forge.anvil.forge_code_project_options import (
    SCRATCH_ID,
    THOMAS_ID,
    ProjectOption,
    describe_selection,
    project_options,
    resolve_selection,
    thomas_option,
)


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    return tmp_path


def _thomas_root() -> Path | None:
    opt = thomas_option()
    return Path(opt.root) if opt else None


def test_picker_offers_scratch_first_and_thomas_as_a_named_option(catalog: Path) -> None:
    options = project_options(catalog)
    assert options[0].id == SCRATCH_ID
    assert options[0].is_default is True

    thomas = next((o for o in options if o.id == THOMAS_ID), None)
    assert thomas is not None, "Thomas must be offerable -- he can edit himself on request"
    assert thomas.label == "Thomas"
    assert thomas.requires_explicit_choice is True
    assert thomas.is_default is False


def test_thomas_option_warns_what_it_means(catalog: Path) -> None:
    thomas = next(o for o in project_options(catalog) if o.id == THOMAS_ID)
    assert "Thomas's own source" in thomas.warning
    assert "right now" in thomas.warning  # the consequence, at click time


def test_choosing_thomas_explicitly_binds_thomas() -> None:
    """The whole point: this must actually work when asked for."""
    root = _thomas_root()
    if root is None:
        pytest.skip("Thomas source root not resolvable in this environment")
    assert resolve_selection(THOMAS_ID, catalog_root=root) == root


@pytest.mark.parametrize("selection", ["", None, SCRATCH_ID, "  ", "unknown-id"])
def test_not_choosing_never_binds_thomas(selection, catalog: Path) -> None:
    """The regression, stated directly."""
    thomas_root = _thomas_root()
    resolved = resolve_selection(selection, catalog_root=catalog)
    if thomas_root is not None:
        assert resolved != thomas_root


def test_a_path_pointing_at_thomas_does_not_bind_thomas(catalog: Path) -> None:
    """A stale client value must not smuggle Thomas in through the path field."""
    thomas_root = _thomas_root()
    if thomas_root is None:
        pytest.skip("Thomas source root not resolvable in this environment")

    resolved = resolve_selection("project", catalog_root=catalog, requested_project=str(thomas_root))
    assert resolved != thomas_root
    assert resolved == forge_code_projects.default_scratch_project(catalog)


def test_a_path_inside_thomas_does_not_bind_thomas(catalog: Path) -> None:
    thomas_root = _thomas_root()
    if thomas_root is None:
        pytest.skip("Thomas source root not resolvable in this environment")

    resolved = resolve_selection("project", catalog_root=catalog, requested_project=str(thomas_root / "thomas"))
    assert resolved != thomas_root
    try:
        assert not resolved.resolve().is_relative_to(thomas_root.resolve())
    except AttributeError:  # pragma: no cover - older Python
        assert not str(resolved).lower().startswith(str(thomas_root).lower())


def test_case_and_whitespace_still_count_as_choosing_thomas() -> None:
    root = _thomas_root()
    if root is None:
        pytest.skip("Thomas source root not resolvable in this environment")
    assert resolve_selection("  Thomas  ", catalog_root=root) == root
    assert resolve_selection("THOMAS", catalog_root=root) == root


def test_describe_selection_names_thomas_so_the_ui_can_show_it() -> None:
    root = _thomas_root()
    if root is None:
        pytest.skip("Thomas source root not resolvable in this environment")
    assert describe_selection(root) == "Thomas"


def test_describe_selection_names_an_ordinary_project(tmp_path: Path) -> None:
    assert describe_selection(tmp_path / "my-app") == "my-app"


def test_options_serialise_for_the_picker(catalog: Path) -> None:
    payload = [o.as_dict() for o in project_options(catalog)]
    assert {"id", "label", "root", "kind", "is_default", "requires_explicit_choice", "warning"} <= set(payload[0])
    assert isinstance(payload, list)


def test_option_is_immutable() -> None:
    opt = ProjectOption(id="x", label="X", root="/tmp/x", kind="scratch")
    with pytest.raises((AttributeError, TypeError)):
        opt.id = "y"  # type: ignore[misc]
