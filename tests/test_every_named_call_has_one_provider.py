"""Every named call has exactly one provider, and a server will not start without it.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 8. A named call swaps an import for a
name, so nothing but these tests stands between a provider that was dropped and a call that fails during a turn.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.plugins import carve

from thomas.core import plugin_manifest
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.kernel import late, seams
from thomas.server import app_core

ROOT = Path(__file__).resolve().parents[1]
FIX = "FIX: run `python -m scripts.plugins.carve`."
PROVIDERS = {
    seams.TOOL_SET: "thomas.server.app_helpers",
    seams.FOLLOW_SELF_CHANGE: "thomas.server.self_change_status",
    seams.PROJECT_QUEUE_TICK: "thomas.server.self_project_queue_tick",
    seams.START_DELEGATION: "thomas.server.chat_offers",
    seams.STEER_DELEGATION: "thomas.server.chat_offers",
    seams.DELEGATION_RECORD: "thomas.server.chat_offers",
    seams.BUILD_SETTINGS: "thomas.server.chat_offers",
    seams.FOLLOW_AFTER_RESTART: "thomas.server.chat_offers",
}
_PROVIDES = re.compile(r"late\.provide\(\s*seams\.(\w+)")


def _python_files() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z", "*.py"], cwd=ROOT, capture_output=True, check=True, timeout=120)
    return [raw.decode("utf-8") for raw in listed.stdout.split(b"\0") if raw]


def _provided_in_source() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _python_files():
        if not path.startswith("tests/"):
            text = (ROOT / path).read_text("utf-8", "replace")
            for name in _PROVIDES.findall(text):
                found.setdefault(getattr(seams, name), []).append(path[:-3].replace("/", "."))
    return found


def test_each_named_call_has_the_one_provider_written_here() -> None:
    assert _provided_in_source() == {name: [module] for name, module in PROVIDERS.items()}


def test_every_name_in_the_kernel_is_listed_here() -> None:
    assert set(PROVIDERS) == set(seams.CALLS)


def test_each_manifest_says_what_its_code_offers_and_asks_for_by_name() -> None:
    sources = {
        path: (ROOT / path).read_text("utf-8", "replace") for path in _python_files() if not path.startswith("tests/")
    }
    manifests = plugin_manifest.load(ROOT)
    for manifest in manifests:
        assert (manifest.provides, manifest.uses) == carve.named_calls(manifest, sources), f"{manifest.name}: {FIX}"
    assert sorted(name for manifest in manifests for name in manifest.provides) == sorted(seams.CALLS)


def test_a_server_will_not_start_while_a_named_call_is_unprovided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    app_core.create_app(config)  # everything provided: this one starts

    monkeypatch.delitem(late._provided, seams.TOOL_SET)
    with pytest.raises(late.NotProvided, match=seams.TOOL_SET):
        app_core.create_app(config)


def test_a_server_without_its_optional_routes_still_finds_every_provider(tmp_path: Path) -> None:
    """A route family that cannot load logs a warning and the server starts without it, so no provider may need one.

    In a process of its own: in this one, whatever any earlier test imported has already provided the call.
    """
    start = (
        "import sys\n"
        "from thomas.core.config import AppConfig, MemoryConfig, ModelConfig\n"
        "from thomas.server import app_core, app_routes_init\n"
        "app_routes_init.register_optional_route_families = lambda *args, **kwargs: None\n"
        "app_routes_init.register_late_route_families = lambda *args, **kwargs: None\n"
        "models = {'local': ModelConfig(name='local', model='dummy')}\n"
        "memory = MemoryConfig(root=sys.argv[1])\n"
        "app_core.create_app(AppConfig(models=models, default_model='local', memory=memory))\n"
    )
    started = subprocess.run(
        [sys.executable, "-c", start, str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert started.returncode == 0, started.stderr[-1500:]
