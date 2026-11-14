/* Live plugin kernel inside the existing Marketplace surface. */
function marketplaceKernelInstall() {
    const marketplaceRenderSurface = moduleRenderMarketplaceSurface;
    moduleRenderMarketplaceSurface = function (container) {
        const rendered = marketplaceRenderSurface(container);
        const surface = container?.querySelector('.marketplace-surface');
        if (surface && !surface.querySelector('[data-marketplace-kernel]')) {
            const node = document.createElement('section');
            node.className = 'marketplace-kernel';
            node.dataset.marketplaceKernel = '';
            node.setAttribute('aria-label', 'Live plugin kernel');
            node.setAttribute('aria-live', 'polite');
            surface.querySelector('.marketplace-sticky-head')?.insertAdjacentElement('afterend', node);
            marketplaceKernelMount(node);
        }
        return rendered;
    };
}
window.__thomasRuntimeReady.then(marketplaceKernelInstall);

const MARKETPLACE_KERNEL_SEAMS = ['tools', 'llm', 'sessions', 'agent_loop', 'fs', 'sandbox'];
const marketplaceKernelState = { status: null, message: 'Loading live plugin status…', busy: false, loading: false, node: null, notice: null, content: null };

function marketplaceKernelRenderCurrent() {
    const state = marketplaceKernelState;
    if (!state.node?.isConnected) return;
    state.notice.textContent = state.message;
    state.content.innerHTML = state.status ? marketplaceKernelMarkup(state.status)
        : '<p>Live plugin status is unavailable. Try refreshing it.</p><button type="button" class="marketplace-command-btn" data-kernel-refresh>Refresh status</button>';
    if (state.busy) state.node.querySelectorAll('[data-kernel-action], [data-kernel-refresh], [data-kernel-sync]')
        .forEach(control => { control.disabled = true; });
}

function marketplaceKernelSetMessage(message) {
    marketplaceKernelState.message = message;
    if (marketplaceKernelState.node?.isConnected) marketplaceKernelState.notice.textContent = message;
}

function marketplaceKernelText(value) {
    return escapeHtml(String(value ?? ''));
}

function marketplaceKernelLabel(value) {
    return String(value ?? '').replace(/_/g, ' ');
}

async function marketplaceKernelRequest(path, payload) {
    const options = { cache: 'no-store' };
    if (payload) {
        options.method = 'POST';
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(payload);
    }
    const response = await fetch(`/api/plugins/kernel${path}`, options);
    const raw = await response.text();
    let data;
    try { data = JSON.parse(raw); } catch (_) { data = null; }
    if (!response.ok) {
        const detail = data?.error || data?.message || (data ? '' : raw.trim());
        throw new Error(detail || `Plugin kernel request failed (HTTP ${response.status}).`);
    }
    return data || {};
}

function marketplaceKernelMarkup(status) {
    const kernel = status.kernel || {};
    const runtime = status.runtime || {};
    const plugins = Array.isArray(runtime.plugins) ? runtime.plugins : [];
    const services = Array.isArray(status.system_services) ? status.system_services : [];
    const systems = status.systems || {};
    const seams = kernel.seams || {};
    const names = Array.isArray(kernel.mounted) ? kernel.mounted : [];
    const idle = Array.isArray(runtime.contributing_no_hooks) ? runtime.contributing_no_hooks : [];
    const mountedPlugins = plugins.filter(plugin => plugin.state === 'mounted');
    const idleNames = mountedPlugins.filter(plugin => !plugin.hooks?.length).map(plugin => plugin.name);
    const idleAll = [...new Set([...idle, ...idleNames])];
    const mountedNames = [...new Set([...names, ...mountedPlugins.map(plugin => plugin.name)])];
    const systemNames = {
        installed_plugins: 'Installed plugin runtime',
        extension_packs: 'Extension packs',
        agent_plugins: 'Agent plugin installer',
        desktop_plugins: 'Desktop plugin installer',
    };
    return `
        <div class="marketplace-kernel-heading">
            <div><span class="marketplace-kernel-eyebrow">Live kernel · no restart</span><h2>Plugged in</h2>
                <p>Inspect the six seams, plugin systems, and installed plugins answering right now. To turn parts of Thomas off and on, go to Settings, then Plugins.</p></div>
            <div class="marketplace-kernel-actions"><button type="button" class="marketplace-command-btn" data-kernel-refresh>Refresh status</button>
                <button type="button" class="marketplace-command-btn" data-kernel-sync ${!status.hot_swap ? 'disabled' : ''}>Sync installed plugins</button></div>
        </div>
        ${!status.hot_swap ? '<p class="marketplace-kernel-notice">Live swapping is unavailable: plugins are not supervised in this process.</p>' : ''}
        <div class="marketplace-kernel-layout">
            <section aria-label="Kernel seams"><h3>Six kernel seams</h3><div class="marketplace-kernel-grid">
                ${MARKETPLACE_KERNEL_SEAMS.map(name => `<div class="marketplace-kernel-cell"><strong>${marketplaceKernelText(marketplaceKernelLabel(name))}</strong><span class="marketplace-kernel-state ${seams[name] ? 'is-on' : ''}">${seams[name] ? 'Filled' : 'Unfilled'}</span></div>`).join('')}
            </div></section>
            <section aria-label="Plugin systems"><h3>Plugin systems</h3><div class="marketplace-kernel-grid">
                ${Object.entries(systemNames).map(([key, label]) => {
                    const system = systems[key] || {};
                    const service = services.find(row => row.service === key || (key === 'extension_packs' && row.service === 'extension_catalog') || (key === 'agent_plugins' && row.service === 'agent_plugin_installer') || (key === 'desktop_plugins' && row.service === 'desktop_plugin_installer'));
                    const provider = service?.provider?.provider || system.provider || '';
                    return `<div class="marketplace-kernel-cell"><strong>${label}</strong><span class="marketplace-kernel-state ${system.mounted_on_kernel ? 'is-on' : ''}">${system.mounted_on_kernel ? 'Mounted' : 'Not mounted'}</span>${provider ? `<small>Provider: ${marketplaceKernelText(provider)}</small>` : ''}${key === 'extension_packs' ? `<small>${marketplaceKernelText(system.count ?? 0)} packs · ${system.hooks_execute ? 'hooks execute' : 'catalog only; hooks do not execute'}</small>` : ''}</div>`;
                }).join('')}
            </div></section>
        </div>
        <section aria-label="Mounted kernel plugins"><h3>Mounted on the kernel</h3>
            <p>${mountedNames.length ? mountedNames.map(marketplaceKernelText).join(', ') : 'No plugins mounted on the kernel.'}</p>
            <p>${idleAll.length ? `Contributing no hooks: ${idleAll.map(marketplaceKernelText).join(', ')}` : 'No mounted installed plugins contribute zero hooks.'}</p>
        </section>
        <section aria-label="Installed plugin controls"><h3>Installed plugins</h3>
            ${plugins.length ? `<div class="marketplace-kernel-plugins">${plugins.map(plugin => {
                const name = String(plugin.name ?? '');
                const state = String(plugin.state ?? 'absent');
                return `<article class="marketplace-kernel-plugin"><div><strong>${marketplaceKernelText(name)}</strong> <span class="marketplace-kernel-state ${state === 'mounted' ? 'is-on' : ''}">${marketplaceKernelText(state)}</span>
                    <p>${state !== 'mounted' ? 'No active hooks while not mounted' : plugin.hooks?.length ? `Hooks: ${plugin.hooks.map(marketplaceKernelText).join(', ')}` : 'Mounted, contributing no hooks'}</p>
                    ${plugin.error ? `<p class="marketplace-kernel-error">${marketplaceKernelText(plugin.error)}</p>` : ''}</div>
                    <div class="marketplace-kernel-actions">
                        <button type="button" class="marketplace-command-btn" data-kernel-action="unplug" data-kernel-name="${marketplaceKernelText(name)}" ${state !== 'mounted' || !status.hot_swap ? 'disabled' : ''}>Unplug</button>
                        <button type="button" class="marketplace-command-btn" data-kernel-action="replug" data-kernel-name="${marketplaceKernelText(name)}" ${state === 'mounted' || !status.hot_swap ? 'disabled' : ''}>Replug</button>
                        <button type="button" class="marketplace-command-btn" data-kernel-action="reload" data-kernel-name="${marketplaceKernelText(name)}" ${!status.hot_swap ? 'disabled' : ''}>Reload</button>
                    </div></article>`;
            }).join('')}</div>` : '<p>No kernel plugin is installed and supervised here. Run <code>thomas plugins install-from-local-path &lt;folder&gt;</code> in a terminal (or <code>python -m thomas plugins install-from-local-path &lt;folder&gt;</code> if the CLI launcher is unavailable), then select “Sync installed plugins” above. Marketplace’s “Install From File” and “Install from URL” import bundles into other plugin systems.</p>'}
        </section>`;
}

function marketplaceKernelMount(node) {
    if (!node) return;
    const notice = document.createElement('p');
    notice.className = 'marketplace-kernel-feedback';
    notice.setAttribute('role', 'status');
    notice.setAttribute('aria-live', 'polite');
    node.append(notice);
    const content = document.createElement('div');
    node.append(content);
    const state = marketplaceKernelState;
    state.node = node;
    state.notice = notice;
    state.content = content;
    marketplaceKernelRenderCurrent();
    async function refresh() {
        try {
            const data = await marketplaceKernelRequest('');
            state.status = data;
            marketplaceKernelRenderCurrent();
            return true;
        } catch (error) {
            marketplaceKernelSetMessage(`Could not read plugin kernel: ${error.message}`);
            return false;
        }
    }
    node.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-kernel-action], [data-kernel-refresh], [data-kernel-sync]');
        if (!button || !node.contains(button) || button.disabled || marketplaceKernelState.busy) return;
        marketplaceKernelState.busy = true;
        marketplaceKernelRenderCurrent();
        const action = button.dataset.kernelAction || (button.hasAttribute('data-kernel-sync') ? 'sync' : 'refresh');
        const name = button.dataset.kernelName;
        marketplaceKernelSetMessage(action === 'refresh' ? 'Refreshing plugin status…' : `${marketplaceKernelLabel(action)} ${name || 'installed plugins'}…`);
        try {
            if (action === 'refresh') {
                if (await refresh()) marketplaceKernelSetMessage('Plugin status refreshed.');
                return;
            }
            const result = await marketplaceKernelRequest(`/${action}`, action === 'sync' ? {} : { name });
            const outcome = result.outcome || result.state || 'unknown';
            const updated = await refresh();
            const statusNote = updated ? '' : ' Live status could not be refreshed.';
            marketplaceKernelSetMessage(action === 'sync'
                ? `Sync ${result.ok ? 'complete' : 'failed'}: ${Object.entries(result.changes || {}).map(([key, values]) => `${key}: ${values.join(', ') || 'none'}`).join('; ')}.${statusNote}`
                : result.ok
                    ? `${name}: ${marketplaceKernelLabel(outcome)}.${outcome === 'unchanged' ? ' The code on disk has not changed.' : ' Live status updated.'}${statusNote}`
                    : `${name}: ${marketplaceKernelLabel(outcome)}. ${action} did not take effect; check the plugin error below.${statusNote}`);
        } catch (error) {
            await refresh();
            marketplaceKernelSetMessage(`${marketplaceKernelLabel(action)} ${name || 'installed plugins'} failed: ${error.message}`);
        } finally {
            marketplaceKernelState.busy = false;
            marketplaceKernelRenderCurrent();
        }
    });
    if (!state.loading && !state.busy) {
        state.loading = true;
        void refresh().then((updated) => {
            state.loading = false;
            if (updated && state.message === 'Loading live plugin status…') marketplaceKernelSetMessage('');
        });
    }
}
