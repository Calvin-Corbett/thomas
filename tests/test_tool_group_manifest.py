"""A built-in tool group registers from its manifest, and the registry is unchanged."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from thomas.core.config import load_config
from thomas.server import tool_groups
from thomas.server.app_helpers import _build_tools
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.registry import ToolRegistry

CODE_TOOLS = {
    "code.search",
    "code.find_definition",
    "code.find_references",
    "code.project_structure",
    "code.semantic_search",
}


def _fingerprint(registry: ToolRegistry) -> str:
    """Insertion order, categories, concrete classes and the model-facing specs."""
    tools = registry.list_tools()
    return json.dumps(
        {
            "insertion_order": list(registry._tools),
            "kinds": {tool.name: [tool.category, type(tool).__qualname__] for tool in tools},
            "specs": registry.get_openai_specs(),
        },
        sort_keys=True,
        default=str,
    )


def _real_registry(tmp_path: Path) -> ToolRegistry:
    return _build_tools(load_config(tmp_path / "thomas.toml"))


def _direct(tmp_path: Path) -> ToolRegistry:
    registry = ToolRegistry()
    register_code_search_tools(registry, tmp_path)
    return registry


def _register_from_manifest(tmp_path: Path, registry: ToolRegistry | None = None, fallback=None):
    registry = ToolRegistry() if registry is None else registry
    used = tool_groups.register_tool_group(
        registry,
        "code-search",
        {"sandbox": tmp_path},
        fallback=fallback or (lambda: register_code_search_tools(registry, tmp_path)),
    )
    return registry, used


def test_real_registry_is_identical_with_and_without_the_manifest(tmp_path, monkeypatch):
    via_manifest = _real_registry(tmp_path)
    monkeypatch.setattr(tool_groups, "_MANIFEST_DIR", tmp_path / "no-manifests-here")
    via_fallback = _real_registry(tmp_path)

    assert {tool.name for tool in via_manifest.list_tools()} >= CODE_TOOLS
    assert _fingerprint(via_manifest) == _fingerprint(via_fallback)


def test_the_copy_keeps_the_groups_own_insertion_order_not_the_sorted_one(tmp_path):
    via_manifest, used = _register_from_manifest(tmp_path)
    direct = _direct(tmp_path)

    assert used is True
    assert list(direct._tools) != sorted(direct._tools)  # the order is observable, so it must be kept
    assert list(via_manifest._tools) == list(direct._tools)
    assert _fingerprint(via_manifest) == _fingerprint(_direct(tmp_path))


def test_the_tools_get_the_sandbox_the_host_gave(tmp_path):
    other = tmp_path / "somewhere-else"
    other.mkdir()
    registry = ToolRegistry()
    tool_groups.register_tool_group(registry, "code-search", {"sandbox": other}, fallback=lambda: None)

    assert {name: registry.get(name)._root for name in CODE_TOOLS} == dict.fromkeys(CODE_TOOLS, other)


def test_build_tools_reads_the_manifest_rather_than_the_fallback(tmp_path, monkeypatch):
    seen: list[bool] = []
    real = tool_groups.register_tool_group

    def spy(*args, **kwargs):
        seen.append(real(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr("thomas.server.app_helpers.register_tool_group", spy)
    _real_registry(tmp_path)
    assert seen == [True]


def test_the_manifest_path_does_not_also_run_the_fallback(tmp_path):
    ran: list[str] = []
    _, used = _register_from_manifest(tmp_path, fallback=lambda: ran.append("fallback"))
    assert used is True
    assert ran == []


def test_manifest_names_exactly_what_the_direct_registration_provides(tmp_path):
    manifest = tool_groups.load_manifest("code-search")
    assert {tool.name for tool in _direct(tmp_path).list_tools()} == set(manifest.tools) == CODE_TOOLS


def _swap_manifest(tmp_path, monkeypatch, text: str) -> None:
    (tmp_path / "code-search.toml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(tool_groups, "_MANIFEST_DIR", tmp_path)


_GOOD = """
id = "tools.code-search"
[group]
register = "thomas.tools.code_search:register_code_search_tools"
needs = ["sandbox"]
[provides]
tools = {tools}
"""

_ALL_TOOLS = str(sorted(CODE_TOOLS)).replace("'", '"')


@pytest.mark.parametrize(
    "text",
    [
        "this is not toml [",
        "id = 'x'",  # no [group]
        _GOOD.format(tools='["code.search"]'),  # fewer tools than the function registers
        _GOOD.format(tools='["code.search", "code.nope"]'),  # a tool nothing registers
        _GOOD.replace("thomas.tools.code_search", "os").format(tools="[]"),  # not a thomas module
        _GOOD.replace("register_code_search_tools", "no_such_function").format(tools='["code.search"]'),
        _GOOD.replace('"sandbox"', '"missing_host_value"').format(tools='["code.search"]'),
    ],
)
def test_a_bad_manifest_falls_back_warns_and_registers_the_same_tools(tmp_path, monkeypatch, caplog, text):
    _swap_manifest(tmp_path, monkeypatch, text)
    real = ToolRegistry()
    with caplog.at_level(logging.DEBUG, logger=tool_groups.__name__):
        registry, used = _register_from_manifest(tmp_path, real)

    assert used is False
    assert _fingerprint(registry) == _fingerprint(_direct(tmp_path))
    assert [r.levelno for r in caplog.records if r.name == tool_groups.__name__] == [logging.WARNING]


def test_a_manifest_that_disagrees_leaves_the_registry_to_the_fallback_alone(tmp_path, monkeypatch):
    _swap_manifest(tmp_path, monkeypatch, _GOOD.format(tools='["code.search"]'))
    registry = ToolRegistry()
    seen_by_fallback: list[list[str]] = []
    _register_from_manifest(tmp_path, registry, lambda: seen_by_fallback.append(list(registry._tools)))
    assert seen_by_fallback == [[]]  # nothing was copied before the fallback ran


def test_a_missing_manifest_falls_back_quietly(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(tool_groups, "_MANIFEST_DIR", tmp_path)
    called: list[str] = []
    with caplog.at_level(logging.DEBUG, logger=tool_groups.__name__):
        used = tool_groups.register_tool_group(ToolRegistry(), "code-search", {}, lambda: called.append("fallback"))
    assert used is False
    assert called == ["fallback"]
    assert [r.levelno for r in caplog.records if r.name == tool_groups.__name__] == [logging.DEBUG]


def test_the_manifest_loads_when_tomllib_is_missing_and_tomli_is_there(monkeypatch):
    real = tool_groups._toml()
    monkeypatch.setitem(sys.modules, "tomllib", None)  # `import tomllib` now raises ImportError
    monkeypatch.setitem(sys.modules, "tomli", real)  # the python 3.10 dependency
    assert tool_groups.load_manifest("code-search").tools == CODE_TOOLS


def test_no_toml_parser_at_all_is_a_fallback_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "tomllib", None)
    monkeypatch.setitem(sys.modules, "tomli", None)
    registry, used = _register_from_manifest(tmp_path)
    assert used is False
    assert _fingerprint(registry) == _fingerprint(_direct(tmp_path))


@pytest.mark.parametrize(
    "register",
    [
        "os:register_x",  # outside thomas
        "thomas.core.config:load_config",  # inside thomas, not a tool module
        "thomas.server.app_helpers:register_x",  # thomas but not thomas.tools
        "thomas.tools.code_search:build_something",  # not a register_ function
        "thomas.tools.code_search",  # no function
        "thomastools.code_search:register_x",  # prefix without the dot
    ],
)
def test_a_manifest_can_only_call_a_register_function_in_a_tools_module(tmp_path, monkeypatch, register):
    text = _GOOD.replace("thomas.tools.code_search:register_code_search_tools", register).format(tools=_ALL_TOOLS)
    _swap_manifest(tmp_path, monkeypatch, text)
    with pytest.raises(ValueError, match="register must be"):
        tool_groups.load_manifest("code-search")


def test_build_group_refuses_a_disallowed_function_even_with_a_hand_made_manifest():
    manifest = tool_groups.ToolGroupManifest("x", "thomas.core.config:load_config", (), frozenset({"a"}))
    with pytest.raises(ValueError, match="register must be"):
        tool_groups.build_group(manifest, {})


@pytest.mark.parametrize("name", ["../code-search", "Code-Search", "code_search", "code search", "", "a/b", "a.b"])
def test_a_group_name_must_be_lowercase_words_and_dashes(name):
    with pytest.raises(ValueError, match=r"\[a-z0-9-\]\+"):
        tool_groups.load_manifest(name)


# ---- the pin: the code, not the manifest, says what a group is -----------------------------------------------------


def _other_group_names(tmp_path: Path) -> tuple[str, list[str]]:
    from thomas.tools.diff import register_diff_tools

    registry = ToolRegistry()
    register_diff_tools(registry, tmp_path)
    return "thomas.tools.diff:register_diff_tools", sorted(tool.name for tool in registry.list_tools())


def _refused(tmp_path, monkeypatch, caplog, text: str, unwanted: set[str] = frozenset()) -> None:
    _swap_manifest(tmp_path, monkeypatch, text)
    with caplog.at_level(logging.DEBUG, logger=tool_groups.__name__):
        registry, used = _register_from_manifest(tmp_path)
    assert used is False
    assert _fingerprint(registry) == _fingerprint(_direct(tmp_path)), "only the built-in code search is registered"
    assert not unwanted & {tool.name for tool in registry.list_tools()}
    assert [r.levelno for r in caplog.records if r.name == tool_groups.__name__] == [logging.WARNING]


def test_the_expected_tool_names_are_pinned_in_code_and_match_the_real_group(tmp_path):
    pin = tool_groups.PINNED_GROUPS["code-search"]
    assert pin.tools == CODE_TOOLS == {tool.name for tool in _direct(tmp_path).list_tools()}
    assert pin.register == "thomas.tools.code_search:register_code_search_tools" and pin.needs == ("sandbox",)


def test_a_manifest_naming_another_register_function_and_its_own_tool_names_is_refused(tmp_path, monkeypatch, caplog):
    register, names = _other_group_names(tmp_path)
    text = _GOOD.replace("thomas.tools.code_search:register_code_search_tools", register).format(
        tools=str(names).replace("'", '"')
    )
    _refused(tmp_path, monkeypatch, caplog, text, unwanted=set(names))


def test_a_manifest_declaring_a_smaller_or_different_tool_set_is_refused(tmp_path, monkeypatch, caplog):
    _refused(tmp_path, monkeypatch, caplog, _GOOD.format(tools='["code.search"]'))


def test_a_manifest_asking_for_other_host_values_is_refused(tmp_path, monkeypatch, caplog):
    _refused(
        tmp_path, monkeypatch, caplog, _GOOD.replace('["sandbox"]', '["sandbox", "extra"]').format(tools=_ALL_TOOLS)
    )


def test_a_manifest_cannot_add_a_group_the_code_does_not_pin(tmp_path, monkeypatch):
    (tmp_path / "brand-new.toml").write_text(
        _GOOD.replace("tools.code-search", "tools.brand-new").format(tools=_ALL_TOOLS), encoding="utf-8"
    )
    monkeypatch.setattr(tool_groups, "_MANIFEST_DIR", tmp_path)
    with pytest.raises(ValueError, match="not pinned in code"):
        tool_groups.load_manifest("brand-new")
    ran: list[str] = []
    assert (
        tool_groups.register_tool_group(
            ToolRegistry(), "brand-new", {"sandbox": tmp_path}, lambda: ran.append("fallback")
        )
        is False
    )
    assert ran == ["fallback"]


def test_a_hand_made_manifest_that_differs_from_the_pin_is_refused_by_build_group(tmp_path):
    register, names = _other_group_names(tmp_path)
    manifest = tool_groups.ToolGroupManifest("tools.code-search", register, ("sandbox",), frozenset(names))
    with pytest.raises(ValueError, match="differs from the code's pin"):
        tool_groups.build_group(manifest, {"sandbox": tmp_path})


def _pin_manifest(**changes):
    pin = tool_groups.PINNED_GROUPS["code-search"]
    base = {"id": "tools.code-search", "register": pin.register, "needs": pin.needs, "tools": pin.tools}
    return tool_groups.ToolGroupManifest(**{**base, **changes})


def test_the_pin_check_is_exact_in_every_dimension_on_its_own(tmp_path):
    tool_groups._check_pin("code-search", _pin_manifest())  # the real one passes
    register, names = _other_group_names(tmp_path)
    for change in (
        {"register": register},  # only the function differs
        {"tools": frozenset(CODE_TOOLS - {"code.search"})},  # only the tool names differ
        {"tools": frozenset(CODE_TOOLS | {"code.extra"})},
        {"needs": ("sandbox", "extra")},  # only the host values differ
        {"needs": ()},
        {"id": "tools.other"},  # only the id differs
    ):
        with pytest.raises(ValueError):
            tool_groups._check_pin("code-search", _pin_manifest(**change))
