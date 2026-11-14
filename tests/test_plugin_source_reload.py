"""A reload that says ``reloaded`` is running the file that is on disk.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`, phase 3.5.

**The defect, and why the suite could not see it.** ``SourceFileLoader`` runs
cached bytecode whenever the ``.pyc`` header's source mtime — in whole seconds —
and source size both match the file. An agent rewriting its own plugin lands
inside that window routinely, and the reload then reports success while the
previous version keeps answering. Measured on the live app: ``outcome: reloaded``
thirteen times while the hook kept stamping ``loop36`` instead of ``loop49``.

Every test here runs with ``sys.dont_write_bytecode`` **False**, because
``tests/conftest.py`` sets it True and that is what hid the defect: the suite
passed while ``python -m thomas.server``, ``thomas serve`` and the caged server's
scheduled task all wrote ``.pyc`` files and reloaded into them.

The stale cache is constructed rather than waited for — see
``tests/plugin_bytecode_helpers.py`` — and ``test_the_stale_bytecode_trap_is_real``
checks the trap itself, so the rest cannot pass for the wrong reason. The same
proof over ``POST /api/plugins/kernel/reload`` is in
``tests/test_plugin_reload_over_http.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from tests.plugin_bytecode_helpers import (
    NEW_MARK,
    OLD_MARK,
    PACKAGE_INIT,
    PLUGIN_SOURCE,
    mark_the_stock_loader_produces,
    set_stale_pyc_trap,
    write_manifest,
    write_plugin,
)
from thomas.agent.kernel_wiring import default_kernel
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner
from thomas.server.plugin_supervisor import PluginSupervisor


@pytest.fixture
def writing_bytecode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bytecode writing ON, which is how every real launch runs."""
    monkeypatch.setattr(sys, "dont_write_bytecode", False)


@pytest.fixture
def plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_PLUGIN_ENABLEMENT_STORE", str(tmp_path / "enablement.json"))
    from thomas.plugins.runtime import clear_cache

    clear_cache()
    root = tmp_path / "plugins"
    root.mkdir()
    return root


def _supervised(root: Path) -> tuple[PluginSupervisor, object]:
    kernel = default_kernel()
    supervisor = PluginSupervisor(kernel=kernel, install_root=str(root)).start()
    return supervisor, make_plugin_hook_runner(install_root=str(root), kernel=kernel)


def _marks(runner) -> list[str]:
    return list(asyncio.run(runner("before_tool", {})).get("marks", []))


# ---------------------------------------------------------------------------
# the trap
# ---------------------------------------------------------------------------


def test_the_stale_bytecode_trap_is_real(writing_bytecode: None, plugin_root: Path) -> None:
    """Guards the tests below rather than the product.

    If this stopped reproducing, every other test here would pass without
    exercising anything.
    """
    package = write_plugin(plugin_root, "demo_stamp", OLD_MARK)
    init = package / "__init__.py"

    set_stale_pyc_trap(init, PLUGIN_SOURCE.format(name="demo_stamp", mark=NEW_MARK))

    assert init.read_text(encoding="utf-8").count(NEW_MARK) == 1
    assert mark_the_stock_loader_produces(init) == OLD_MARK, "the stock loader should still run the .pyc"


# ---------------------------------------------------------------------------
# the reload
# ---------------------------------------------------------------------------


def test_a_reload_runs_the_new_source_even_when_the_pyc_looks_current(
    writing_bytecode: None,
    plugin_root: Path,
) -> None:
    package = write_plugin(plugin_root, "demo_stamp", OLD_MARK)
    write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == [OLD_MARK]

    set_stale_pyc_trap(package / "__init__.py", PLUGIN_SOURCE.format(name="demo_stamp", mark=NEW_MARK))

    assert supervisor.reload("demo_stamp") == "reloaded"
    assert _marks(runner) == [NEW_MARK], "reported reloaded while the old code answered"


def test_sync_picks_up_the_edit_the_way_the_running_app_does(
    writing_bytecode: None,
    plugin_root: Path,
) -> None:
    """``sync`` is the operation a self-edit goes through with nothing else asked."""
    package = write_plugin(plugin_root, "demo_stamp", OLD_MARK)
    write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == [OLD_MARK]

    set_stale_pyc_trap(package / "__init__.py", PLUGIN_SOURCE.format(name="demo_stamp", mark=NEW_MARK))

    assert supervisor.sync()["reloaded"] == ["demo_stamp"]
    assert _marks(runner) == [NEW_MARK]


def test_an_edit_in_a_submodule_lands_even_when_its_bytecode_looks_current(
    writing_bytecode: None,
    plugin_root: Path,
) -> None:
    """One level down, where the package's own import goes to the path finder.

    ``from . import rule`` is not resolved by the loader that imported the
    package; it goes to ``sys.meta_path``. Without a finder that answers for
    plugin prefixes, this is the same defect with an extra step.
    """
    package = plugin_root / "demo_stamp"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(PACKAGE_INIT.format(name="demo_stamp"), encoding="utf-8")
    rule = package / "rule.py"
    rule.write_text(f'MARK = "{OLD_MARK}"\n', encoding="utf-8")
    write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)
    assert _marks(runner) == [OLD_MARK]

    set_stale_pyc_trap(rule, f'MARK = "{NEW_MARK}"\n')

    # No ``force``: the content fingerprint sees a same-length edit at an
    # unchanged mtime, which is the other thing a timestamp comparison misses.
    assert supervisor.reload("demo_stamp") == "reloaded"
    assert _marks(runner) == [NEW_MARK]


def test_loading_a_plugin_leaves_no_bytecode_to_go_stale(
    writing_bytecode: None,
    plugin_root: Path,
) -> None:
    """The other half: the loader writes no cache, so none can be reused later."""
    package = write_plugin(plugin_root, "demo_stamp", OLD_MARK)
    write_manifest(plugin_root, "demo_stamp")

    supervisor, runner = _supervised(plugin_root)

    assert _marks(runner) == [OLD_MARK]
    assert supervisor.mounted_names() == ["demo_stamp"]
    assert not (package / "__pycache__").exists(), "a plugin load wrote bytecode"
