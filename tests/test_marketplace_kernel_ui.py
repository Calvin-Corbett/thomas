"""Keep live kernel controls wired into the existing Marketplace renderer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "thomas/server/web/js/runtime"


def test_marketplace_kernel_smoke_avoids_unrelated_extension_pages() -> None:
    from thomas.tools.web_preflight import browser_smoke_files

    pages = browser_smoke_files(
        ROOT, ["thomas/server/web/js/runtime/marketplace_kernel.js", "thomas/server/web/index.html"]
    )
    assert not pages, f"Served Marketplace controls should not smoke unrelated offline pages: {pages}"


def test_marketplace_loads_and_mounts_live_kernel() -> None:
    shell = (ROOT / "thomas/server/web/index.html").read_text(encoding="utf-8")
    surface = (RUNTIME / "036_workbench_editors_08.js").read_text(encoding="utf-8")
    kernel = (RUNTIME / "marketplace_kernel.js").read_text(encoding="utf-8")
    loader = (ROOT / "thomas/server/web/js/app_runtime_loader.js").read_text(encoding="utf-8")
    manifest = loader.split("var RUNTIME_SCRIPTS = [", 1)[1].split("];", 1)[0]
    # Every file in js/runtime/ loads through the manifest. A second <script> tag
    # for the kernel would run its top-level consts twice and fail.
    assert "'marketplace_kernel.js'" in manifest
    assert "marketplace_kernel.js" not in shell
    assert "window.__thomasRuntimeReady.then(marketplaceKernelInstall)" in kernel
    assert 'class="marketplace-surface"' in surface
    assert "moduleRenderMarketplaceSurface = function (container)" in kernel
    assert "marketplaceKernelMount(node)" in kernel


def test_kernel_markup_and_route_errors() -> None:
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const src = fs.readFileSync('thomas/server/web/js/runtime/marketplace_kernel.js', 'utf8');
const context = {
    window: {__thomasRuntimeReady: {then: install => install()}},
    moduleRenderMarketplaceSurface: () => null,
    escapeHtml: text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    fetch: async (url, options) => {
        if (url.endsWith('/reload')) return {ok: false, status: 400, text: async () => 'reload failed: broken plugin'};
        return {ok: true, text: async () => JSON.stringify({ok: true, runtime: {plugins: []}})};
    },
};
vm.createContext(context);
vm.runInContext(src, context);
(async () => {
    // Execute the installed Marketplace wrapper, not just inspect its source.
    let mountCalls = 0;
    const surface = {
        querySelector: selector => selector === '.marketplace-sticky-head'
            ? {insertAdjacentElement: (_position, node) => { node.isConnected = true; }} : null,
    };
    context.document = {
        createElement: () => ({dataset: {}, setAttribute() {}}),
    };
    context.marketplaceKernelMount = node => { assert.strictEqual(node.isConnected, true); mountCalls++; };
    const container = {querySelector: selector => selector === '.marketplace-surface' ? surface : null};
    context.moduleRenderMarketplaceSurface(container);
    assert.strictEqual(mountCalls, 1, 'Marketplace must mount the live controls');
    const render = vm.runInContext('marketplaceKernelMarkup', context);
    const html = render({hot_swap: true, kernel: {seams: {tools: true}, mounted: []}, systems: {}, runtime: {plugins: []}});
    assert.strictEqual((html.match(/class="marketplace-kernel-cell"/g) || []).length, 10);
    assert.match(html, /No kernel plugin is installed and supervised here/);
    assert.match(html, /thomas plugins install-from-local-path &lt;folder&gt;/);
    assert.match(html, /python -m thomas plugins install-from-local-path &lt;folder&gt;/);
    assert.match(html, /Sync installed plugins/);
    assert.match(html, /To turn parts of Thomas off and on, go to Settings, then Plugins\./);
    assert.match(html, /import bundles into other plugin systems/);
    assert.match(html, /data-kernel-sync/);
    const mounted = render({hot_swap: true, kernel: {seams: {}, mounted: ['demo']}, systems: {}, runtime: {plugins: [{name: 'demo', state: 'mounted', hooks: ['before_tool']}]}});
    assert.match(mounted, /data-kernel-action="unplug"/);
    assert.match(mounted, /data-kernel-action="replug"/);
    assert.match(mounted, /data-kernel-action="reload"/);
    assert.match(mounted, /Hooks: before_tool/);
    const idle = render({hot_swap: true, kernel: {seams: {}, mounted: ['idle']}, systems: {}, runtime: {plugins: [{name: 'idle', state: 'mounted', hooks: []}]}});
    assert.match(idle, /Contributing no hooks: idle/);
    const unplugged = render({hot_swap: true, kernel: {seams: {}, mounted: []}, systems: {}, runtime: {plugins: [{name: 'demo', state: 'unplugged', hooks: []}]}});
    assert.match(unplugged, /No active hooks while not mounted/);
    assert.doesNotMatch(unplugged, /Hooks: before_tool/);
    const request = vm.runInContext('marketplaceKernelRequest', context);
    await assert.rejects(request('/reload', {name: 'demo'}), /reload failed: broken plugin/);
    const sync = await request('/sync', {});
    assert.strictEqual(sync.ok, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    try:
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15, check=False
        )
    except FileNotFoundError:
        pytest.skip("Node is needed to execute the Marketplace browser script")
    assert result.returncode == 0, result.stderr


def test_kernel_action_feedback_survives_rerender_and_failed_refresh() -> None:
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('thomas/server/web/js/runtime/marketplace_kernel.js', 'utf8');
let failRefresh = false;
let finishAction;
const pendingAction = new Promise(resolve => { finishAction = resolve; });
const context = {
    window: {__thomasRuntimeReady: {then: install => install()}},
    escapeHtml: value => String(value),
    fetch: async (url) => {
        if (url.endsWith('/unplug')) return pendingAction;
        if (url.endsWith('/reload')) return {ok: false, status: 500, text: async () => JSON.stringify({error: 'reload rejected'})};
        if (failRefresh) throw new Error('kernel offline');
        return {ok: true, text: async () => JSON.stringify({hot_swap: true, kernel: {seams: {}, mounted: ['demo']},
            systems: {}, runtime: {plugins: [{name: 'demo', state: 'mounted', hooks: ['before_tool']}]}})};
    },
};
let current;
const head = {insertAdjacentElement: (_where, node) => {node.isConnected = true; current = node;}};
context.moduleRenderMarketplaceSurface = () => {
    if (current) current.isConnected = false;
    return null;
};
context.document = {createElement: tag => ({tag, dataset: {}, children: [], innerHTML: '', textContent: '',
    setAttribute() {}, append(child) { this.children.push(child); },
    addEventListener(_event, handler) { this.click = handler; },
    contains() { return true; },
    querySelectorAll() { return []; },
})};
const surface = {querySelector: selector => selector === '.marketplace-sticky-head' ? head : null};
const container = {querySelector: selector => selector === '.marketplace-surface' ? surface : null};
vm.createContext(context);
vm.runInContext(source, context);
const draw = () => { context.moduleRenderMarketplaceSurface(container); return current; };
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    let node = draw();
    await tick();
    assert.match(node.children[1].innerHTML, /Hooks: before_tool/);
    const button = {disabled: false, dataset: {kernelAction: 'unplug', kernelName: 'demo'},
        closest() {return this;}, hasAttribute() {return false;}};
    const action = node.click({target: button});
    node = draw();
    assert.match(node.children[0].textContent, /unplug demo/i);
    finishAction({ok: true, text: async () => JSON.stringify({ok: true, outcome: 'unplugged'})});
    await action;
    assert.match(node.children[0].textContent, /demo: unplugged/i);
    node = draw();
    assert.match(node.children[0].textContent, /demo: unplugged/i);
    assert.match(node.children[1].innerHTML, /Hooks: before_tool/);
    failRefresh = true;
    const refresh = {disabled: false, dataset: {}, closest() {return this;}, hasAttribute() {return false;}};
    await node.click({target: refresh});
    assert.match(node.children[0].textContent, /Could not read plugin kernel: kernel offline/);
    assert.match(node.children[1].innerHTML, /Hooks: before_tool/);
    assert.match(node.children[1].innerHTML, /data-kernel-refresh>Refresh status<\/button>/, 'failed refresh must restore the refresh control');
    assert.match(node.children[1].innerHTML, /data-kernel-action="unplug"[^>]*>Unplug<\/button>/, 'failed refresh must restore active plugin controls');
    node = draw();
    assert.match(node.children[0].textContent, /kernel offline/);
    await tick();
    assert.match(node.children[0].textContent, /kernel offline/);
    assert.match(node.children[1].innerHTML, /Hooks: before_tool/);
    failRefresh = false;
    await node.click({target: refresh});
    assert.match(node.children[0].textContent, /Plugin status refreshed/);
    assert.match(node.children[1].innerHTML, /data-kernel-refresh>Refresh status<\/button>/);
    const reload = {disabled: false, dataset: {kernelAction: 'reload', kernelName: 'demo'},
        closest() {return this;}, hasAttribute() {return false;}};
    await node.click({target: reload});
    assert.match(node.children[0].textContent, /reload demo failed: reload rejected/);
    node = draw();
    assert.match(node.children[0].textContent, /reload demo failed: reload rejected/);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
