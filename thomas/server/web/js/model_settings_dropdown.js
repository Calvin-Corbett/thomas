/**
 * Model Settings Gear Dropdown
 *
 * Adds a gear icon next to the MODEL dropdown *inside* the Model Setup modal.
 * Clicking it reveals an inline panel showing connection details
 * for the active model profile:
 *   - Codex/OAuth profiles: logged-in email, plan, logout button
 *   - API-key profiles: masked key, source, change/clear buttons
 *   - Local profiles: endpoint URL, connection status
 *
 * All data comes from existing API routes:
 *   GET  /api/models          — profile list and metadata
 *   GET  /api/secrets         — credential status per profile
 *   GET  /api/codex/status    — Codex auth state
 *   POST /api/codex/login     — initiate ChatGPT OAuth
 *   POST /api/codex/logout    — clear Codex session
 */

(function initModelSettingsDropdown() {
    'use strict';

    /* ── Wait for Model Setup modal to appear ─────────────────────── */

    let injected = false;

    function tryInject() {
        if (injected) return;
        const modal = document.getElementById('modelSetupModal');
        if (!modal) return;
        const modelSelect = modal.querySelector('#setupModelSelector');
        if (!modelSelect) return;
        if (document.getElementById('modelSettingsGearBtn')) { injected = true; return; }
        injectGearButton(modelSelect);
        injected = true;
    }

    // Use MutationObserver to detect when the modal becomes visible
    const observer = new MutationObserver(() => {
        const modal = document.getElementById('modelSetupModal');
        if (modal && modal.classList.contains('active')) {
            tryInject();
        }
    });

    function startObserving() {
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class'],
        });
        // Also try immediately in case modal is already open
        tryInject();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startObserving);
    } else {
        startObserving();
    }

    /* ── Inject Gear Button next to MODEL dropdown ─────────────────── */

    function injectGearButton(modelSelect) {
        const formGroup = modelSelect.closest('.form-group');
        if (!formGroup) return;

        // Wrap the select and gear in a flex row
        const selectRow = document.createElement('div');
        selectRow.className = 'msd-select-row';

        // The select is already in the form-group. We'll wrap it.
        const selectParent = modelSelect.parentElement;
        selectParent.insertBefore(selectRow, modelSelect);
        selectRow.appendChild(modelSelect);

        const btn = document.createElement('button');
        btn.id = 'modelSettingsGearBtn';
        btn.type = 'button';
        btn.className = 'model-settings-gear-btn';
        btn.title = 'Connection settings';
        btn.setAttribute('aria-label', 'Model connection settings');
        btn.setAttribute('aria-haspopup', 'true');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '<i class="ph ph-gear-six"></i>';
        selectRow.appendChild(btn);

        // Create the inline panel (below the select row, still inside form-group)
        const panel = document.createElement('div');
        panel.id = 'modelSettingsPanel';
        panel.className = 'model-settings-panel';
        panel.setAttribute('role', 'region');
        panel.setAttribute('aria-label', 'Model connection details');
        formGroup.appendChild(panel);

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const open = panel.classList.toggle('open');
            btn.classList.toggle('active', open);
            btn.setAttribute('aria-expanded', String(open));
            if (open) loadPanelContent(panel);
        });

        // Refresh when provider changes
        const providerSelect = document.getElementById('setupProviderSelector');
        if (providerSelect) {
            providerSelect.addEventListener('change', () => {
                if (panel.classList.contains('open')) {
                    setTimeout(() => loadPanelContent(panel), 200);
                }
            });
        }
    }

    /* ── Load Panel Content ────────────────────────────────────────── */

    async function loadPanelContent(panel) {
        panel.innerHTML = '<div class="msd-loading"><i class="ph ph-spinner msd-spin"></i> Loading…</div>';

        try {
            const [modelsRes, secretsRes] = await Promise.all([
                fetch('/api/models').then(r => r.json()),
                fetch('/api/secrets').then(r => r.json()),
            ]);

            const profiles = Array.isArray(modelsRes) ? modelsRes
                : Array.isArray(modelsRes.profiles) ? modelsRes.profiles
                : [];
            const secrets = Array.isArray(secretsRes) ? secretsRes
                : Array.isArray(secretsRes.profiles) ? secretsRes.profiles
                : [];

            // Figure out which profile is currently active
            const setupProvider = document.getElementById('setupProviderSelector');
            const activeProfile = (setupProvider?.value || '').trim();

            // Build a secrets lookup
            const secretMap = {};
            for (const s of secrets) {
                if (s && s.name) secretMap[s.name] = s;
            }

            // Find the active profile data
            const profile = profiles.find(p => p.name === activeProfile) || profiles[0];
            if (!profile) {
                panel.innerHTML = '<div class="msd-empty">No model profiles configured.</div>';
                return;
            }

            const secret = secretMap[profile.name] || {};
            const provider = (profile.provider || '').toLowerCase();

            if (provider === 'codex') {
                await renderCodexProfile(panel, profile);
            } else if (provider.includes('openai') || provider.includes('anthropic') || provider.includes('groq') || provider.includes('google') || provider.includes('compat')) {
                renderApiKeyProfile(panel, profile, secret);
            } else {
                renderLocalProfile(panel, profile);
            }
        } catch (err) {
            panel.innerHTML = `<div class="msd-error">Could not load settings.<br><small>${escHtml(err.message)}</small></div>`;
        }
    }

    /* ── Codex / OAuth Profile ─────────────────────────────────────── */

    async function renderCodexProfile(panel, profile) {
        let status = { logged_in: false };
        try {
            status = await fetch('/api/openai-codex/status').then(r => r.json());
        } catch { /* fall through */ }

        if (status.logged_in) {
            panel.innerHTML = `
                <div class="msd-header">
                    <span class="msd-provider-badge msd-badge-codex">Codex</span>
                    <span class="msd-status msd-status-ok"><i class="ph ph-check-circle"></i> Connected</span>
                </div>
                <div class="msd-body">
                    <div class="msd-row">
                        <span class="msd-label">Account</span>
                        <span class="msd-value">${escHtml(status.email || status.display_name || 'ChatGPT User')}</span>
                    </div>
                    ${status.plan_type ? `<div class="msd-row"><span class="msd-label">Plan</span><span class="msd-value">${escHtml(status.plan_type)}</span></div>` : ''}
                    <div class="msd-row">
                        <span class="msd-label">Model</span>
                        <span class="msd-value">${escHtml(profile.model || 'default')}</span>
                    </div>
                </div>
                <div class="msd-actions">
                    <button type="button" class="msd-btn msd-btn-secondary" id="msdSwitchAccount">Switch Account</button>
                    <button type="button" class="msd-btn msd-btn-danger" id="msdLogout">Log Out</button>
                </div>`;

            panel.querySelector('#msdLogout')?.addEventListener('click', async () => {
                await codexLogout(panel);
            });
            panel.querySelector('#msdSwitchAccount')?.addEventListener('click', async () => {
                await codexLogout(panel);
                await codexLogin(panel);
            });
        } else {
            panel.innerHTML = `
                <div class="msd-header">
                    <span class="msd-provider-badge msd-badge-codex">Codex</span>
                    <span class="msd-status msd-status-off"><i class="ph ph-x-circle"></i> Not connected</span>
                </div>
                <div class="msd-body">
                    <p class="msd-hint">Sign in with your ChatGPT account to use Codex models.</p>
                </div>
                <div class="msd-actions">
                    <button type="button" class="msd-btn msd-btn-primary" id="msdLogin">Sign In with ChatGPT</button>
                </div>`;

            panel.querySelector('#msdLogin')?.addEventListener('click', () => codexLogin(panel));
        }
    }

    async function codexLogout(panel) {
        const actions = panel.querySelector('.msd-actions');
        if (actions) actions.innerHTML = '<span class="msd-loading"><i class="ph ph-spinner msd-spin"></i> Logging out…</span>';
        try {
            await fetch('/api/openai-codex/logout', { method: 'POST' });
        } catch { /* ignore */ }
        await loadPanelContent(panel);
    }

    async function codexLogin(panel) {
        const actions = panel.querySelector('.msd-actions');
        if (actions) actions.innerHTML = '<span class="msd-loading"><i class="ph ph-spinner msd-spin"></i> Opening browser…</span>';
        try {
            await fetch('/api/openai-codex/login', { method: 'POST' });
        } catch { /* ignore */ }
        await loadPanelContent(panel);
    }

    /* ── API Key Profile ───────────────────────────────────────────── */

    function renderApiKeyProfile(panel, profile, secret) {
        const hasKey = Boolean(secret.has_key);
        const source = secret.source || 'none';
        const rotation = secret.rotation_status || 'unknown';
        const providerName = formatProviderName(profile.provider);

        let rotationHtml = '';
        if (hasKey && rotation === 'due_soon') {
            rotationHtml = `<div class="msd-row"><span class="msd-label">Key Rotation</span><span class="msd-value msd-warn"><i class="ph ph-warning"></i> Due soon</span></div>`;
        } else if (hasKey && rotation === 'expired') {
            rotationHtml = `<div class="msd-row"><span class="msd-label">Key Rotation</span><span class="msd-value msd-danger"><i class="ph ph-warning-circle"></i> Overdue</span></div>`;
        }

        panel.innerHTML = `
            <div class="msd-header">
                <span class="msd-provider-badge">${escHtml(providerName)}</span>
                <span class="msd-status ${hasKey ? 'msd-status-ok' : 'msd-status-off'}">
                    <i class="ph ph-${hasKey ? 'check-circle' : 'x-circle'}"></i>
                    ${hasKey ? 'Key loaded' : 'No API key'}
                </span>
            </div>
            <div class="msd-body">
                <div class="msd-row">
                    <span class="msd-label">Endpoint</span>
                    <span class="msd-value msd-mono">${escHtml(truncUrl(profile.base_url))}</span>
                </div>
                <div class="msd-row">
                    <span class="msd-label">Model</span>
                    <span class="msd-value">${escHtml(profile.model || 'default')}</span>
                </div>
                ${hasKey ? `<div class="msd-row"><span class="msd-label">Key Source</span><span class="msd-value">${escHtml(source)}</span></div>` : ''}
                ${rotationHtml}
            </div>
            <div class="msd-actions">
                ${hasKey
                    ? '<button type="button" class="msd-btn msd-btn-secondary" id="msdChangeKey">Change Key</button><button type="button" class="msd-btn msd-btn-danger" id="msdClearKey">Remove Key</button>'
                    : '<button type="button" class="msd-btn msd-btn-primary" id="msdSetKey">Add API Key</button>'
                }
            </div>`;

        panel.querySelector('#msdSetKey')?.addEventListener('click', () => showKeyInput(panel, profile.name, false));
        panel.querySelector('#msdChangeKey')?.addEventListener('click', () => showKeyInput(panel, profile.name, true));
        panel.querySelector('#msdClearKey')?.addEventListener('click', async () => {
            await fetch(`/api/secrets/${encodeURIComponent(profile.name)}`, { method: 'DELETE' });
            await loadPanelContent(panel);
        });
    }

    function showKeyInput(panel, profileName, isChange) {
        const actions = panel.querySelector('.msd-actions');
        if (!actions) return;
        actions.innerHTML = `
            <div class="msd-key-input-wrap">
                <input type="password" id="msdKeyInput" class="msd-key-input"
                       placeholder="${isChange ? 'New API key…' : 'Paste API key…'}" autocomplete="off" />
                <button type="button" class="msd-btn msd-btn-primary msd-btn-sm" id="msdSaveKey">Save</button>
                <button type="button" class="msd-btn msd-btn-ghost msd-btn-sm" id="msdCancelKey">Cancel</button>
            </div>`;

        const input = panel.querySelector('#msdKeyInput');
        input?.focus();

        panel.querySelector('#msdSaveKey')?.addEventListener('click', async () => {
            const key = input?.value?.trim();
            if (!key) return;
            await fetch(`/api/secrets/${encodeURIComponent(profileName)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key }),
            });
            await loadPanelContent(panel);
        });

        panel.querySelector('#msdCancelKey')?.addEventListener('click', () => loadPanelContent(panel));

        input?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') panel.querySelector('#msdSaveKey')?.click();
            if (e.key === 'Escape') panel.querySelector('#msdCancelKey')?.click();
        });
    }

    /* ── Local / Ollama Profile ────────────────────────────────────── */

    function renderLocalProfile(panel, profile) {
        panel.innerHTML = `
            <div class="msd-header">
                <span class="msd-provider-badge msd-badge-local">Local</span>
                <span class="msd-status msd-status-ok"><i class="ph ph-desktop-tower"></i> Local endpoint</span>
            </div>
            <div class="msd-body">
                <div class="msd-row">
                    <span class="msd-label">Endpoint</span>
                    <span class="msd-value msd-mono">${escHtml(profile.base_url || 'localhost')}</span>
                </div>
                <div class="msd-row">
                    <span class="msd-label">Model</span>
                    <span class="msd-value">${escHtml(profile.model || 'default')}</span>
                </div>
            </div>
            <div class="msd-actions">
                <button type="button" class="msd-btn msd-btn-secondary" id="msdTestConnection">Test Connection</button>
            </div>`;

        panel.querySelector('#msdTestConnection')?.addEventListener('click', async () => {
            const btn = panel.querySelector('#msdTestConnection');
            if (btn) btn.innerHTML = '<i class="ph ph-spinner msd-spin"></i> Testing…';
            try {
                const res = await fetch(`/api/models/${encodeURIComponent(profile.name)}/handshake`).then(r => r.json());
                if (btn) {
                    if (res.ok || res.reachable) {
                        btn.innerHTML = '<i class="ph ph-check-circle"></i> Connected';
                        btn.classList.add('msd-btn-success');
                    } else {
                        btn.innerHTML = '<i class="ph ph-x-circle"></i> Unreachable';
                        btn.classList.add('msd-btn-danger-solid');
                    }
                }
            } catch {
                if (btn) {
                    btn.innerHTML = '<i class="ph ph-x-circle"></i> Error';
                    btn.classList.add('msd-btn-danger-solid');
                }
            }
        });
    }

    /* ── Helpers ────────────────────────────────────────────────────── */

    function escHtml(s) {
        const d = document.createElement('div');
        d.textContent = String(s || '');
        return d.innerHTML;
    }

    function truncUrl(url) {
        if (!url) return '—';
        try {
            const u = new URL(url);
            return u.host + (u.pathname !== '/' ? u.pathname.replace(/\/+$/, '') : '');
        } catch {
            return String(url).slice(0, 40);
        }
    }

    function formatProviderName(provider) {
        const names = {
            openai_compat: 'OpenAI',
            openai: 'OpenAI',
            anthropic: 'Anthropic',
            google: 'Google',
            groq: 'Groq',
            codex: 'Codex',
        };
        return names[(provider || '').toLowerCase()] || provider || 'Provider';
    }
})();
