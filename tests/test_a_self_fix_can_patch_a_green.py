"""A self-fix worker can patch its own green copy with diff.create -- fix round 1, C2.

Review of ce9f2f43: `diff.create` (thomas/tools/diff.py) and the diff transaction
(thomas/tools/diff_transaction.py) checked runtime protection against the tool's OWN
sandbox root, unlike `fs.write_file`, which checks against the real project (widened
to the sandbox only when the sandbox sits INSIDE that tree). A green is a private copy
OUTSIDE the project tree, so a green path named `thomas/server/x.js` matched the
protected directory `thomas/server` by name alone and was BLOCKED -- even though the
same write through `fs.write_file` was allowed. Round 1 pointed self-development
workers at `diff.create` for exactly this reason, so until this landed, a Chat
self-fix of a core file had only `replace_whole_file: true` left as a route around
the truncation guard -- the rewrite-from-memory the guard exists to stop.

Both tools now check `_runtime_protection_roots(sandbox_root, project_root)`, the
same roots `fs.write_file` already used. `_PROJECT_ROOT` (in thomas/tools/filesystem.py
and thomas/tools/diff.py) is monkeypatched to an isolated temp "project" so this test
never touches the real running checkout, but the registry is still built the one real
way the chat worker builds it (`thomas.server.app_helpers._build_tools`) -- no tool is
constructed by hand.
"""

from __future__ import annotations

import dataclasses

import pytest

from thomas.core.config import load_config
from thomas.server.app_helpers import _build_tools
from thomas.tools import diff as diff_module
from thomas.tools import filesystem as filesystem_module

_GREEN_Y_PATCH = (
    "--- a/thomas/server/y.js\n+++ b/thomas/server/y.js\n@@ -1,1 +1,1 @@\n-GREEN Y ORIGINAL\n+GREEN Y PATCHED\n"
)


def _registry_for(sandbox):
    cfg = load_config()
    run_cfg = dataclasses.replace(
        cfg, tools=dataclasses.replace(cfg.tools, sandbox_root=str(sandbox), allow_shell=True)
    )
    return _build_tools(run_cfg)


@pytest.fixture
def project_and_green(tmp_path, monkeypatch):
    """An isolated fake project and a green OUTSIDE it, each holding thomas/server/*.js."""
    project = tmp_path / "project"
    green = tmp_path / "green_root" / "work" / "exec-test"
    for root in (project, green):
        (root / "thomas" / "server").mkdir(parents=True)
        (root / "thomas" / "server" / "x.js").write_text("ORIGINAL X\n", encoding="utf-8")
        (root / "thomas" / "server" / "y.js").write_text("GREEN Y ORIGINAL\n", encoding="utf-8")
    monkeypatch.setattr(filesystem_module, "_PROJECT_ROOT", project)
    monkeypatch.setattr(diff_module, "_PROJECT_ROOT", project)
    return project, green


@pytest.mark.asyncio
async def test_diff_create_succeeds_on_the_greens_own_copy(project_and_green):
    _project, green = project_and_green
    registry = _registry_for(green)

    result = await registry.execute(
        "diff.create", {"file": "thomas/server/x.js", "old_str": "ORIGINAL X\n", "new_str": "PATCHED X\n"}
    )

    assert result.ok is True, result.error
    assert (green / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "PATCHED X\n"


@pytest.mark.asyncio
async def test_diff_apply_patch_succeeds_on_the_greens_own_copy(project_and_green):
    _project, green = project_and_green
    registry = _registry_for(green)

    result = await registry.execute("diff.apply_patch", {"patch": _GREEN_Y_PATCH})

    assert result.ok is True, result.error
    assert (green / "thomas" / "server" / "y.js").read_text(encoding="utf-8") == "GREEN Y PATCHED\n"


@pytest.mark.asyncio
async def test_fs_write_file_still_succeeds_on_the_greens_own_copy(project_and_green):
    _project, green = project_and_green
    registry = _registry_for(green)

    result = await registry.execute("fs.write_file", {"path": "thomas/server/x.js", "content": "REWRITTEN X\n"})

    assert result.ok is True, result.error
    assert (green / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "REWRITTEN X\n"


@pytest.mark.asyncio
async def test_diff_create_is_still_refused_on_the_real_project_by_relative_path(project_and_green):
    project, _green = project_and_green
    registry = _registry_for(project)  # a worker sandboxed directly in the project itself

    result = await registry.execute(
        "diff.create", {"file": "thomas/server/x.js", "old_str": "ORIGINAL X\n", "new_str": "TAMPERED X\n"}
    )

    assert result.ok is False
    assert "protected runtime" in (result.error or "")
    assert (project / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "ORIGINAL X\n"


@pytest.mark.asyncio
async def test_diff_create_is_still_refused_on_the_real_project_by_absolute_path(project_and_green):
    project, green = project_and_green
    # Sandboxed in the green, but naming the project's file by its absolute path.
    registry = _registry_for(green)

    result = await registry.execute(
        "diff.create",
        {
            "file": str(project / "thomas" / "server" / "x.js"),
            "old_str": "ORIGINAL X\n",
            "new_str": "TAMPERED X\n",
        },
    )

    assert result.ok is False
    assert (project / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "ORIGINAL X\n"


@pytest.mark.asyncio
async def test_diff_create_is_still_refused_reaching_the_project_with_dot_dot_from_a_nested_sandbox(project_and_green):
    project, _green = project_and_green
    # A worker sandboxed one level INSIDE the project (e.g. a nested subworkspace)
    # tries to climb back out to the project's own protected file with `..`.
    nested = project / "subworkspace"
    nested.mkdir()
    registry = _registry_for(nested)

    result = await registry.execute(
        "diff.create",
        {"file": "../thomas/server/x.js", "old_str": "ORIGINAL X\n", "new_str": "TAMPERED X\n"},
    )

    assert result.ok is False
    assert (project / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "ORIGINAL X\n"


@pytest.mark.asyncio
async def test_diff_create_is_still_refused_climbing_dot_dot_from_the_green_itself(project_and_green):
    """I3 gap: a `..` climb from the worker's actual green, landing exactly on
    the project's file. The green lives outside the project tree, and
    `_safe_path`'s sandbox confinement refuses the escape before runtime
    protection is even consulted. Fix round 3: the climb used to go six levels
    up, past the project, to a file that does not exist, so it was refused
    even with the confinement removed."""
    project, green = project_and_green
    registry = _registry_for(green)
    climb = "../../../project/thomas/server/x.js"  # exec-test -> work -> green_root -> the project's parent
    assert (green / climb).resolve() == (project / "thomas" / "server" / "x.js").resolve()

    result = await registry.execute(
        "diff.create",
        {"file": climb, "old_str": "ORIGINAL X\n", "new_str": "TAMPERED X\n"},
    )

    assert result.ok is False
    assert "escapes sandbox" in (result.error or ""), result.error
    assert (project / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "ORIGINAL X\n"


@pytest.mark.asyncio
async def test_diff_apply_patch_is_still_refused_on_the_real_project(project_and_green):
    project, _green = project_and_green
    registry = _registry_for(project)

    result = await registry.execute("diff.apply_patch", {"patch": _GREEN_Y_PATCH})

    assert result.ok is False
    assert (project / "thomas" / "server" / "y.js").read_text(encoding="utf-8") == "GREEN Y ORIGINAL\n"


@pytest.mark.asyncio
async def test_fs_write_file_behaves_the_same_as_diff_create_on_the_real_project(project_and_green):
    """fs.write_file already got this right (ce9f2f43); diff.create now matches it."""
    project, _green = project_and_green
    registry = _registry_for(project)

    result = await registry.execute("fs.write_file", {"path": "thomas/server/x.js", "content": "TAMPERED X\n"})

    assert result.ok is False
    assert "protected runtime" in (result.error or "")
    assert (project / "thomas" / "server" / "x.js").read_text(encoding="utf-8") == "ORIGINAL X\n"
