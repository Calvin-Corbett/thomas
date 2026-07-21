from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
LOADER = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_loader.js"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canvas_runtime_is_split_and_keeps_one_authoritative_renderer() -> None:
    engine = _text(RUNTIME / "048_ui_studio_canvas.js")
    contract = _text(RUNTIME / "canvas_workspace_contract.js")
    runtime = _text(RUNTIME / "canvas_workspace_runtime.js")

    assert len(engine.splitlines()) < 1500
    assert len(contract.splitlines()) <= 300
    assert len(runtime.splitlines()) <= 300
    assert "function buildChrome" not in engine
    assert "installAppBuilderCanvas" not in engine
    assert "function buildChrome" in runtime
    assert "moduleRenderWorkbenchAppBuilderCanvas" in runtime
    assert "workspaceRuntime.install(window.UI_STUDIO)" in engine
    loader = _text(LOADER)
    contract_position = loader.index("'canvas_workspace_contract.js'")
    runtime_position = loader.index("'canvas_workspace_runtime.js'")
    engine_position = loader.index("'048_ui_studio_canvas.js'")
    assert contract_position < runtime_position < engine_position


def test_canvas_registers_shared_edit_regions_and_protects_real_actions() -> None:
    contract = _text(RUNTIME / "canvas_workspace_contract.js")
    runtime = _text(RUNTIME / "canvas_workspace_runtime.js")
    engine = _text(RUNTIME / "048_ui_studio_canvas.js")
    owned = contract + runtime + engine

    for semantic_id in (
        "canvas.toolbar",
        "canvas.stage",
        "canvas.inspector",
        "canvas.layers",
        "canvas.properties",
        "canvas.preview",
    ):
        assert semantic_id in contract
    for attribute in (
        "data-ui-id",
        "data-ui-label",
        "data-ui-component",
        "data-ui-policy",
        "data-ui-constraints",
        "data-ui-instance-key",
    ):
        assert attribute in contract
    assert "protected controls" in contract
    assert "root protected" in contract
    assert "instanceKey: n.id" in engine
    assert "layer-lock-' + n.id" in engine
    assert "thomas-ui-edit-entry" not in owned
    assert "Edit UI" not in owned


def test_canvas_unwraps_safe_fetch_data_and_destroys_every_global_resource() -> None:
    engine = _text(RUNTIME / "048_ui_studio_canvas.js")
    runtime = _text(RUNTIME / "canvas_workspace_runtime.js")

    assert "res && res.data" in engine
    assert "payload && payload.spec" in engine
    assert "payload && payload.nodes" in engine
    assert "if (destroyed) return;" in engine
    assert "cancelAnimationFrame(initialFrame)" in engine
    assert "clearTimeout(autosaveTimer)" in engine
    assert "clearTimeout(offlineAiTimer)" in engine
    assert "removeEventListener('pointerup', onPointerUp)" in engine
    assert "removeEventListener('keydown', onKeyDown)" in engine
    assert "destroyController(resolveWorkbench())" in runtime
    assert "destroyController(workbench);" in runtime


def test_canvas_css_uses_current_chat_theme_tokens() -> None:
    css = _text(ROOT / "thomas" / "server" / "web" / "css" / "ui_studio_canvas.css")
    panels = _text(ROOT / "thomas" / "server" / "web" / "css" / "ui_studio_canvas_panels.css")

    for token in ("--c-bg", "--c-surface", "--c-hover", "--c-text", "--c-dim", "--c-muted", "--c-accent"):
        assert token in css
    assert "var(--c-accent-soft" in css
    assert "var(--c-accent-soft" in panels
    assert "@media (max-width: 980px)" in css
    assert "@media (max-width: 620px)" in panels


def test_canvas_contract_and_teardown_execute_in_node() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    contract_path = json.dumps(str(RUNTIME / "canvas_workspace_contract.js"))
    runtime_path = json.dumps(str(RUNTIME / "canvas_workspace_runtime.js"))
    script = """
const fs = require('fs');
global.window = {};
eval(fs.readFileSync(__CONTRACT_PATH__, 'utf8'));
const attrs = {};
window.ThomasCanvasWorkspaceContract.annotate({setAttribute(k, v) { attrs[k] = v; }}, 'layer', {instanceKey: 'Node ABC', label: 'Hero layer'});
const payload = window.ThomasCanvasWorkspaceContract.responseData({ok: true, data: {spec: {id: 'safe-fetch'}}});
let destroyed = 0; let prior = 0;
const wb = {uiStudioCanvas: {destroy() { destroyed += 1; }}};
window.moduleEnsureRuntime = () => ({workbench: {app_builder: wb}});
window.moduleWorkbenchTeardown = () => { prior += 1; };
eval(fs.readFileSync(__RUNTIME_PATH__, 'utf8'));
window.ThomasCanvasWorkspaceRuntime.install({mount() { return null; }});
window.moduleWorkbenchTeardown('app_builder');
console.log(JSON.stringify({attrs, payload, destroyed, prior, renderer: typeof window.moduleRenderWorkbenchAppBuilder}));
"""
    script = script.replace("__CONTRACT_PATH__", contract_path).replace("__RUNTIME_PATH__", runtime_path)
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    observed = json.loads(result.stdout)

    assert observed["attrs"]["data-ui-id"] == "canvas.layer.node-abc"
    assert observed["attrs"]["data-ui-instance-key"] == "Node ABC"
    assert observed["attrs"]["data-ui-label"] == "Hero layer"
    assert observed["payload"]["spec"]["id"] == "safe-fetch"
    assert observed["destroyed"] == 1
    assert observed["prior"] == 1
    assert observed["renderer"] == "function"
