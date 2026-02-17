/* ============================================================
   Thomas Settings
   ============================================================
   Tabbed settings modal: Appearance, Providers, Models,
   Prompts, Voice, About.
   ============================================================ */

import { getState, setState, subscribe } from './store.js';
import { saveSettings, saveSetting } from './db.js';
import { el, applyTheme } from './utils.js';
import { createModal, createTabs, createButton, showToast } from './components.js';
import { updateCodeTheme } from './chat.js';
import { fetchSecrets, setProfileApiKey, clearProfileApiKey, fetchModelHandshake, fetchModels } from './api.js';
import { setComposerText } from './composer.js';
import { openSetupWizard, createTestAllPanel } from './setup-wizard.js';

let _currentModal = null;

export function initSettings() {
  document.getElementById('settingsBtn')?.addEventListener('click', () => openSettings());

  subscribe('ui', () => {
    const s = getState().ui;
    if (s.settingsOpen && !_currentModal) openSettings(s.settingsTab || 'appearance');
  });
}

/**
 * Open the settings modal, optionally to a specific tab.
 * @param {string} [initialTab='appearance'] - Tab id to open to.
 */
export function openSettings(initialTab = 'appearance') {
  if (_currentModal) {
    if (typeof _currentModal.switchTab === 'function') _currentModal.switchTab(initialTab);
    return;
  }

  const settings = getState().settings;

  // ──── Shared helpers (used by Providers tab) ─────────────
  const KEY_PORTALS = {
    openai: { loginUrl: 'https://platform.openai.com/login', url: 'https://platform.openai.com/api-keys', label: 'Open OpenAI API Keys', loginLabel: 'Sign in (Google)', note: 'Step 1: sign in to the OpenAI Platform (Google/Gmail supported). Step 2: create an API key and paste it here.' },
    anthropic: { url: 'https://console.anthropic.com/settings/keys', label: 'Open Anthropic API Keys', note: 'Create an API key in the Anthropic Console, then paste it here.' },
    mistral: { url: 'https://console.mistral.ai/api-keys/', label: 'Open Mistral API Keys', note: 'Create a key in the Mistral Console, then paste it here.' },
    groq: { url: 'https://console.groq.com/keys', label: 'Open Groq API Keys', note: 'Create a key in the Groq Console, then paste it here.' },
    together: { url: 'https://api.together.ai/settings/api-keys', label: 'Open Together API Keys', note: 'Create a key in Together settings, then paste it here.' },
    openrouter: { url: 'https://openrouter.ai/keys', label: 'Open OpenRouter Keys', note: 'Create a key in OpenRouter, then paste it here.' },
    deepinfra: { url: 'https://deepinfra.com/dash/api_keys', label: 'Open DeepInfra API Keys', note: 'Create a key in DeepInfra dashboard, then paste it here.' },
    fireworks: { url: 'https://fireworks.ai/account/api-keys', label: 'Open Fireworks API Keys', note: 'Create a key in Fireworks, then paste it here.' },
    perplexity: { url: 'https://www.perplexity.ai/settings/api', label: 'Open Perplexity API Keys', note: 'Create a key in Perplexity settings, then paste it here.' },
    xai: { url: 'https://console.x.ai/', label: 'Open xAI Console', note: 'Create an API key in the xAI console, then paste it here.' },
    cerebras: { url: 'https://cloud.cerebras.ai/', label: 'Open Cerebras Cloud', note: 'Create an API key in Cerebras Cloud, then paste it here.' },
  };

  function getKeyPortal(n) { return KEY_PORTALS[String(n || '').toLowerCase()] || null; }
  function openExternal(url) { try { window.open(String(url), '_blank', 'noopener,noreferrer'); } catch { /* */ } }
  function openPopup(url, name = 'thomasAuth') { try { const w = window.open(String(url), name, 'popup,width=920,height=720'); if (!w) openExternal(url); try { w.opener = null; } catch { /* */ } } catch { openExternal(url); } }

  // ──── Build body with tabs ───────────────────────────────
  const body = el('div');

  // Tab panels
  const panels = {};
  const tabIds = ['appearance', 'providers', 'models', 'prompts', 'voice', 'about'];
  for (const id of tabIds) {
    const panel = el('div', { className: `tab-panel ${id === initialTab ? 'active' : ''}`, dataset: { tab: id } });
    panels[id] = panel;
  }

  let setActiveTab = () => {};
  const switchTab = (id) => {
    const target = tabIds.includes(id) ? id : 'appearance';
    setActiveTab(target);
    for (const [tabId, panel] of Object.entries(panels)) {
      panel.classList.toggle('active', tabId === target);
    }
    setState('ui', { settingsTab: target });
  };

  // Tab bar
  const tabs = createTabs({
    tabs: [
      { id: 'appearance', label: 'Appearance' },
      { id: 'providers', label: 'Providers' },
      { id: 'models', label: 'Models' },
      { id: 'prompts', label: 'Prompts' },
      { id: 'voice', label: 'Voice' },
      { id: 'about', label: 'About' },
    ],
    activeId: initialTab,
    onSwitch: switchTab,
  });
  const tabBar = tabs.container;
  setActiveTab = tabs.setActive;

  body.appendChild(tabBar);
  for (const panel of Object.values(panels)) body.appendChild(panel);
  switchTab(initialTab);

  // ════════════════════════════════════════════════════════
  //  TAB: Appearance
  // ════════════════════════════════════════════════════════
  const appearancePanel = panels.appearance;

  // Theme
  const themeSection = el('div', { style: { marginBottom: 'var(--space-4)' } });
  themeSection.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-2)' } }, 'Theme'));
  const themeRow = el('div', { className: 'segmented' });
  for (const opt of ['light', 'dark', 'system']) {
    const btn = el('button', { className: `segmented-btn ${settings.theme === opt ? 'active' : ''}`, dataset: { theme: opt } }, opt);
    btn.addEventListener('click', () => {
      setState('settings', { theme: opt });
      saveSetting('theme', opt);
      applyTheme(opt);
      updateCodeTheme(opt === 'dark' || (opt === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches));
      themeRow.querySelectorAll('.segmented-btn').forEach(b => b.classList.toggle('active', b.dataset.theme === opt));
    });
    themeRow.appendChild(btn);
  }
  themeSection.appendChild(themeRow);
  appearancePanel.appendChild(themeSection);

  // GPU VRAM
  const vramSection = el('div', { style: { marginBottom: 'var(--space-4)' } });
  vramSection.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-2)' } }, 'GPU VRAM (GB)'));
  vramSection.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-2)' } },
    'Used for model picker "fits your GPU" badges. Set to your GPU\'s VRAM.'));
  const vramInput = el('input', { className: 'input input-sm', type: 'number', value: String(settings.gpuVram || 10), min: '1', max: '128', step: '1', style: { width: '100px' } });
  vramInput.addEventListener('change', () => { const v = parseInt(vramInput.value) || 10; setState('settings', { gpuVram: v }); saveSetting('gpuVram', v); });
  vramSection.appendChild(vramInput);
  appearancePanel.appendChild(vramSection);

  // Inspector default
  const inspectorSection = el('div');
  inspectorSection.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-2)' } }, 'Show Inspector by default'));
  const inspToggle = el('button', { className: `toggle ${settings.showInspector ? 'active' : ''}`, type: 'button', role: 'switch', 'aria-checked': settings.showInspector ? 'true' : 'false' });
  inspToggle.addEventListener('click', () => {
    const next = !getState().settings.showInspector;
    setState('settings', { showInspector: next });
    saveSetting('showInspector', next);
    inspToggle.classList.toggle('active', next);
    inspToggle.setAttribute('aria-checked', next ? 'true' : 'false');
    document.getElementById('app')?.classList.toggle('inspector-open', next);
  });
  inspectorSection.appendChild(inspToggle);
  appearancePanel.appendChild(inspectorSection);

  // Tool details in chat
  const toolDetailsSection = el('div', { style: { marginTop: 'var(--space-3)' } });
  toolDetailsSection.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-2)' } }, 'Tool details in chat'));
  toolDetailsSection.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-2)' } },
    'Show or hide tool/command details in the chat by default.'));
  const toolDetailsToggle = el('button', { className: `toggle ${settings.showToolDetails ? 'active' : ''}`, type: 'button', role: 'switch', 'aria-checked': settings.showToolDetails ? 'true' : 'false' });
  toolDetailsToggle.addEventListener('click', () => {
    const next = !getState().settings.showToolDetails;
    setState('settings', { showToolDetails: next });
    saveSetting('showToolDetails', next);
    toolDetailsToggle.classList.toggle('active', next);
    toolDetailsToggle.setAttribute('aria-checked', next ? 'true' : 'false');
  });
  toolDetailsSection.appendChild(toolDetailsToggle);
  appearancePanel.appendChild(toolDetailsSection);

  // ════════════════════════════════════════════════════════
  //  TAB: Providers
  // ════════════════════════════════════════════════════════
  const providersPanel = panels.providers;

  const providersHint = el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)', lineHeight: '1.6' } },
    'Add cloud API keys here. Keys are stored locally on this machine by the Thomas server and are never returned back to the browser.');
  providersPanel.appendChild(providersHint);

  const provSearchInput = el('input', { className: 'input input-sm', type: 'text', placeholder: 'Search providers...', style: { marginBottom: 'var(--space-3)' } });
  providersPanel.appendChild(provSearchInput);

  let providerFilter = 'all';
  const filterRow = el('div', { className: 'segmented', style: { marginBottom: 'var(--space-3)' } });
  for (const opt of [{ id: 'all', label: 'all' }, { id: 'needs', label: 'needs key' }, { id: 'ready', label: 'key set' }]) {
    const btn = el('button', { className: `segmented-btn ${providerFilter === opt.id ? 'active' : ''}`, dataset: { filter: opt.id } }, opt.label);
    btn.addEventListener('click', () => {
      providerFilter = opt.id;
      filterRow.querySelectorAll('.segmented-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === opt.id));
      renderProviders();
    });
    filterRow.appendChild(btn);
  }
  providersPanel.appendChild(filterRow);

  // Quick actions
  const quickActions = el('div', { style: { display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-3)', flexWrap: 'wrap' } });
  quickActions.appendChild(createButton({ label: 'Setup Wizard', variant: 'ghost', size: 'sm', onClick: () => { _currentModal?.close(); _currentModal = null; setTimeout(() => openSetupWizard(), 100); } }));
  providersPanel.appendChild(quickActions);

  // Test All panel
  const testAllPanel = createTestAllPanel();
  testAllPanel.style.marginBottom = 'var(--space-3)';
  testAllPanel.style.padding = 'var(--space-3)';
  testAllPanel.style.background = 'var(--surface-raised)';
  testAllPanel.style.borderRadius = 'var(--radius-lg)';
  providersPanel.appendChild(testAllPanel);

  const providersList = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' } });
  providersPanel.appendChild(providersList);

  // Providers rendering logic
  let secretsData = null;

  function shortUrl(u) { try { return new URL(u).host + new URL(u).pathname.replace(/\/$/, ''); } catch { return u; } }
  function chip(text, variant = '') { return el('span', { className: `chip ${variant ? 'chip-' + variant : ''}`.trim(), style: { fontSize: '10px' } }, text); }
  function getHandshake(n) { try { return getState().models.handshakes.get(n) || null; } catch { return null; } }
  function setHandshake(n, r) { try { getState().models.handshakes.set(n, r); setState('models', {}); } catch { /* */ } }
  function getProfiles() { const p = (getState().models.profiles || []).slice(); p.sort((a, b) => { if (a.name === 'local') return -1; if (b.name === 'local') return 1; return (a.name || '').localeCompare(b.name || ''); }); return p; }
  function findSecretRow(name) { return (secretsData?.profiles || []).find(r => r.name === name) || null; }

  function renderProviders() {
    const filter = (provSearchInput.value || '').trim().toLowerCase();
    providersList.innerHTML = '';
    const profiles = getProfiles();
    if (profiles.length === 0) { providersList.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-xs)' } }, 'No profiles found.')); return; }

    for (const p of profiles) {
      const name = p.name || '', provider = p.provider || '', baseUrl = p.base_url || '', model = p.model || '';
      if (filter && !`${name} ${provider} ${baseUrl} ${model}`.toLowerCase().includes(filter)) continue;

      const srow = findSecretRow(name);
      const hasKey = !!(srow?.has_key || p.has_api_key), persisted = !!srow?.persisted;
      const source = srow?.source || (p.has_api_key ? 'config' : 'none');
      const hs = getHandshake(name);

      if (providerFilter === 'needs' && name !== 'local' && hasKey) continue;
      if (providerFilter === 'ready' && name !== 'local' && !hasKey) continue;

      const card = el('div', { className: 'card', style: { padding: 'var(--space-3)' } });
      const top = el('div', { style: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 'var(--space-3)' } });
      const left = el('div', { style: { minWidth: '0' } });
      left.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)' } }, name));
      left.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: '2px' } }, `${provider} - ${shortUrl(baseUrl)}`));
      left.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: '6px', fontFamily: 'var(--font-mono)' } }, model));
      top.appendChild(left);

      const right = el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end', alignItems: 'center' } });
      const activeProfile = getState().activeProfile || getState().models.defaultProfile || '';
      if (name && name === activeProfile) right.appendChild(chip('Active', 'accent'));
      if (name === 'local') {
        right.appendChild(chip('Local', 'success'));
      } else {
        right.appendChild(hasKey ? chip('Key set', 'success') : chip('Key missing', 'danger'));
        if (hasKey) {
          if (persisted) right.appendChild(chip('Saved', 'accent'));
          else if (source === 'secret_store') right.appendChild(chip('Session', 'warning'));
          else if (source === 'config') right.appendChild(chip('Config', 'warning'));
        }
        if (hs) {
          if (hs.status === 'checking') right.appendChild(chip('Checking', 'warning'));
          else if (hs.ok) right.appendChild(chip(`Connected${Array.isArray(hs.models) && hs.models.length ? ` (${hs.models.length})` : ''}`, 'success'));
          else if (hs.status === 'auth_error') right.appendChild(chip('Auth failed', 'danger'));
          else if (hs.status === 'unsupported') right.appendChild(chip('No /models', 'warning'));
          else if (hs.status === 'offline') right.appendChild(chip('Offline', 'danger'));
        }
      }
      top.appendChild(right);
      card.appendChild(top);

      const actions = el('div', { style: { display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', marginTop: 'var(--space-3)' } });
      if (name && name !== activeProfile) {
        actions.appendChild(createButton({ label: 'Use', variant: 'ghost', size: 'sm', onClick: () => { setState('activeProfile', name); setState('activeModelId', ''); showToast(`Using profile: ${name}`, 'success'); renderProviders(); } }));
      }
      if (name !== 'local') {
        const portal = getKeyPortal(name);
        if (portal?.loginUrl) actions.appendChild(createButton({ label: portal.loginLabel || 'Sign in', variant: 'ghost', size: 'sm', onClick: () => openPopup(portal.loginUrl) }));
        if (portal?.url) actions.appendChild(createButton({ label: 'Get key', variant: 'ghost', size: 'sm', onClick: () => openExternal(portal.url) }));
        actions.appendChild(createButton({ label: hasKey ? 'Update key' : 'Set key', variant: 'primary', size: 'sm', onClick: () => openKeyModal(name) }));
        if (hasKey) {
          actions.appendChild(createButton({ label: 'Clear', variant: 'danger', size: 'sm', onClick: async () => {
            if (!confirm(`Clear API key for "${name}"?`)) return;
            try { await clearProfileApiKey(name); showToast(`Cleared key for ${name}`, 'success'); await refreshSecrets(); } catch (e) { showToast(`Failed: ${e.message || String(e)}`, 'error'); }
          }}));
        }
        actions.appendChild(createButton({ label: 'Check', variant: 'ghost', size: 'sm', onClick: async () => {
          try {
            setHandshake(name, { ok: false, status: 'checking', models: [], error: null, checkedAt: Date.now() });
            const res = await fetchModelHandshake(name);
            setHandshake(name, { ...res, checkedAt: Date.now() });
            try { if (Array.isArray(res.models)) getState().models.discovered.set(name, res.models); setState('models', {}); } catch { /* */ }
            if (res.ok) { const c = (res.models || []).length; showToast(c > 0 ? `Connected (${c} models)` : 'Connected (no /models list)', c > 0 ? 'success' : 'info'); }
            else if (res.status === 'auth_error') showToast('Auth failed. Set/refresh the API key for this provider.', 'error');
            else if (res.status === 'unsupported') showToast('This provider does not support /models. Try a chat to confirm it works.', 'info');
            else if (res.status === 'offline') showToast('Provider appears offline/unreachable. Check base_url/network.', 'error');
            else showToast(`Check failed: ${res.error || res.status || 'unknown error'}`, 'error');
          } catch (e) { setHandshake(name, { ok: false, status: 'error', models: [], error: e?.message || String(e), checkedAt: Date.now() }); showToast(`Check failed: ${e.message || String(e)}`, 'error'); }
        }}));
      }
      card.appendChild(actions);
      providersList.appendChild(card);
    }
    if (!providersList.firstChild) providersList.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-xs)', padding: '6px 0' } }, 'No matches.'));
  }

  async function refreshSecrets() {
    try {
      secretsData = await fetchSecrets();
      const enc = secretsData?.storage?.encryption, scope = secretsData?.storage?.scope;
      if (enc) {
        const label = enc === 'dpapi' ? `Storage: encrypted (${scope || 'current_user'})` : `Storage: ${enc}`;
        providersHint.textContent = `Add cloud API keys here. ${label}. Keys are never returned back to the browser.`;
      }
    } catch (e) {
      secretsData = null;
      const msg = String(e?.message || e || '');
      providersHint.textContent = msg.includes('only available from localhost')
        ? 'Add cloud API keys here. (Open this UI via http://127.0.0.1 or http://localhost to manage keys.)'
        : `Add cloud API keys here. (Server offline: ${msg})`;
    }
    renderProviders();
  }

  function openKeyModal(profileName) {
    const keyBody = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' } });
    const portal = getKeyPortal(profileName);
    if (portal?.url) {
      const row = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)', flexWrap: 'wrap' } });
      row.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: '1.6', flex: '1 1 220px' } }, portal.note || `Create an API key for "${profileName}", then paste it here.`));
      const btns = el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' } });
      if (portal.loginUrl) btns.appendChild(createButton({ label: portal.loginLabel || 'Sign in', variant: 'ghost', size: 'sm', onClick: () => openPopup(portal.loginUrl) }));
      btns.appendChild(createButton({ label: portal.label || 'Open key page', variant: 'ghost', size: 'sm', onClick: () => openExternal(portal.url) }));
      row.appendChild(btns);
      keyBody.appendChild(row);
    } else {
      keyBody.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: '1.6' } }, `Paste the API key for "${profileName}". This will be sent to the local Thomas server.`));
    }

    const input = el('input', { className: 'input', type: 'password', placeholder: 'API key', autocomplete: 'off', spellcheck: 'false' });
    keyBody.appendChild(input);

    let persist = true;
    const rememberRow = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)' } });
    rememberRow.appendChild(el('div', { style: { fontSize: 'var(--text-sm)' } }, 'Remember on this machine'));
    const rememberToggle = el('button', { className: `toggle ${persist ? 'active' : ''}`, type: 'button', role: 'switch', 'aria-checked': 'true' });
    rememberToggle.addEventListener('click', () => { persist = !persist; rememberToggle.classList.toggle('active', persist); rememberToggle.setAttribute('aria-checked', persist ? 'true' : 'false'); });
    rememberRow.appendChild(rememberToggle);
    keyBody.appendChild(rememberRow);

    const saveBtn = createButton({ label: 'Save', variant: 'primary', onClick: async () => {
      const k = (input.value || '').trim();
      if (!k) { showToast('Paste an API key first.', 'error'); return; }
      try {
        await setProfileApiKey(profileName, k, persist);
        input.value = '';
        showToast(`Saved key for ${profileName}`, 'success');
        try { const m = await fetchModels(); setState('models', { profiles: m.profiles || [], defaultProfile: m.default || null }); } catch { /* */ }
        await refreshSecrets();
        try { setHandshake(profileName, { ok: false, status: 'checking', models: [], error: null, checkedAt: Date.now() }); const hs = await fetchModelHandshake(profileName); setHandshake(profileName, { ...hs, checkedAt: Date.now() }); if (Array.isArray(hs.models)) { try { getState().models.discovered.set(profileName, hs.models); setState('models', {}); } catch { /* */ } } } catch { /* */ }
        keyModal.close();
      } catch (e) { showToast(`Failed: ${e.message || String(e)}`, 'error'); }
    }});
    const cancelBtn = createButton({ label: 'Cancel', variant: 'ghost', onClick: () => { input.value = ''; keyModal.close(); } });
    const keyModal = createModal({ title: `API Key: ${profileName}`, body: keyBody, footer: [cancelBtn, saveBtn] });
    document.getElementById('modals')?.appendChild(keyModal.backdrop);
    requestAnimationFrame(() => input.focus());
  }

  provSearchInput.addEventListener('input', renderProviders);
  refreshSecrets();

  // ════════════════════════════════════════════════════════
  //  TAB: Models (rendered by models-unified.js)
  // ════════════════════════════════════════════════════════
  const modelsPanel = panels.models;
  modelsPanel.appendChild(el('div', {
    style: { color: 'var(--text-muted)', fontSize: 'var(--text-sm)', padding: 'var(--space-4)', textAlign: 'center' },
  }, 'Loading model tools...'));

  // Dispatch event so models-unified.js can replace this panel body
  try { window.dispatchEvent(new CustomEvent('thomas:settings-models-tab', { detail: { container: modelsPanel } })); } catch { /* */ }

  // ════════════════════════════════════════════════════════
  //  TAB: Prompts
  // ════════════════════════════════════════════════════════
  const promptsPanel = panels.prompts;
  promptsPanel.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)', lineHeight: '1.6' } },
    'Save prompts/snippets you reuse often. Insert them into the composer in one click.'));

  const promptsTop = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' } });
  const promptsSearch = el('input', { className: 'input input-sm', type: 'text', placeholder: 'Search prompts...' });
  promptsSearch.style.maxWidth = '260px';
  const addPromptBtn = createButton({ label: 'Add prompt', variant: 'primary', size: 'sm', onClick: () => openPromptEditor(null) });
  promptsTop.appendChild(promptsSearch);
  promptsTop.appendChild(addPromptBtn);
  promptsPanel.appendChild(promptsTop);

  const promptsList = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' } });
  promptsPanel.appendChild(promptsList);

  function getPrompts() { const a = getState().settings.promptLibrary; return Array.isArray(a) ? a : []; }
  function savePrompts(next) { setState('settings', { promptLibrary: next }); saveSetting('promptLibrary', next); }

  function renderPrompts() {
    const q = (promptsSearch.value || '').trim().toLowerCase();
    promptsList.innerHTML = '';
    let prompts = getPrompts().slice();
    prompts.sort((a, b) => String(a.title || '').localeCompare(String(b.title || '')));
    if (q) prompts = prompts.filter(p => `${p.title || ''} ${p.text || ''}`.toLowerCase().includes(q));

    if (prompts.length === 0) { promptsList.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-xs)' } }, q ? 'No matches.' : 'No prompts yet.')); return; }

    for (const p of prompts) {
      const card = el('div', { className: 'card', style: { padding: 'var(--space-3)' } });
      card.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)' } }, p.title || 'Untitled'));
      card.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', whiteSpace: 'pre-wrap', maxHeight: '48px', overflow: 'hidden' } }, (p.text || '').slice(0, 160)));
      const actions = el('div', { style: { display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', marginTop: 'var(--space-3)' } });
      actions.appendChild(createButton({ label: 'Insert', variant: 'ghost', size: 'sm', onClick: () => { setComposerText(String(p.text || '')); showToast('Inserted prompt', 'success'); _currentModal?.close(); } }));
      actions.appendChild(createButton({ label: 'Edit', variant: 'ghost', size: 'sm', onClick: () => openPromptEditor(p) }));
      actions.appendChild(createButton({ label: 'Delete', variant: 'danger', size: 'sm', onClick: () => { if (!confirm(`Delete prompt "${p.title || 'Untitled'}"?`)) return; savePrompts(getPrompts().filter(x => x.id !== p.id)); renderPrompts(); } }));
      card.appendChild(actions);
      promptsList.appendChild(card);
    }
  }

  function openPromptEditor(existing) {
    const isEdit = !!existing;
    const edBody = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' } });
    const titleInput = el('input', { className: 'input', type: 'text', placeholder: 'Title' });
    const textInput = el('textarea', { className: 'textarea', placeholder: 'Prompt text...', rows: '8' });
    titleInput.value = existing?.title || '';
    textInput.value = existing?.text || '';
    edBody.appendChild(titleInput);
    edBody.appendChild(textInput);

    const edCancel = createButton({ label: 'Cancel', variant: 'ghost', onClick: () => edModal.close() });
    const edSave = createButton({ label: 'Save', variant: 'primary', onClick: () => {
      const t = (titleInput.value || '').trim() || 'Untitled';
      const content = String(textInput.value || '').trimEnd();
      const id = existing?.id || (Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
      const next = getPrompts().filter(p => p.id !== id);
      next.push({ id, title: t, text: content });
      savePrompts(next);
      renderPrompts();
      edModal.close();
    }});
    const edModal = createModal({ title: isEdit ? 'Edit prompt' : 'New prompt', body: edBody, footer: [edCancel, edSave] });
    document.getElementById('modals')?.appendChild(edModal.backdrop);
    requestAnimationFrame(() => titleInput.focus());
  }

  promptsSearch.addEventListener('input', renderPrompts);
  renderPrompts();

  // ════════════════════════════════════════════════════════
  //  TAB: Voice
  // ════════════════════════════════════════════════════════
  const voicePanel = panels.voice;
  voicePanel.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)', lineHeight: '1.6' } },
    'Optional: read assistant replies out loud (browser text-to-speech).'));

  // TTS toggle
  const ttsRow = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' } });
  ttsRow.appendChild(el('div', { style: { fontSize: 'var(--text-sm)' } }, 'Speak assistant replies'));
  const ttsToggle = el('button', { className: `toggle ${getState().settings.ttsEnabled ? 'active' : ''}`, type: 'button', role: 'switch', 'aria-checked': getState().settings.ttsEnabled ? 'true' : 'false' });
  ttsToggle.addEventListener('click', () => {
    const next = !getState().settings.ttsEnabled;
    setState('settings', { ttsEnabled: next }); saveSetting('ttsEnabled', next);
    ttsToggle.classList.toggle('active', next); ttsToggle.setAttribute('aria-checked', next ? 'true' : 'false');
  });
  ttsRow.appendChild(ttsToggle);
  voicePanel.appendChild(ttsRow);

  // Voice conversation mode
  const canStt = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  voicePanel.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', marginBottom: 'var(--space-2)', lineHeight: '1.6' } },
    canStt ? 'Hands-free: press the mic once to talk. Thomas will reply out loud, then listen again. Double-click mic for full voice mode.' : 'Hands-free voice mode requires a browser that supports SpeechRecognition (Chrome/Edge).'));

  let autoSendToggle = null;

  const convoRow = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' } });
  convoRow.appendChild(el('div', { style: { fontSize: 'var(--text-sm)' } }, 'Voice conversation mode'));
  const convoToggle = el('button', { className: `toggle ${getState().settings.voiceConversation ? 'active' : ''}`, type: 'button', role: 'switch', disabled: !canStt, 'aria-checked': getState().settings.voiceConversation ? 'true' : 'false' });
  convoToggle.addEventListener('click', () => {
    const next = !getState().settings.voiceConversation;
    setState('settings', { voiceConversation: next }); saveSetting('voiceConversation', next);
    convoToggle.classList.toggle('active', next); convoToggle.setAttribute('aria-checked', next ? 'true' : 'false');
    if (next && !getState().settings.ttsEnabled) { setState('settings', { ttsEnabled: true }); saveSetting('ttsEnabled', true); ttsToggle.classList.toggle('active', true); ttsToggle.setAttribute('aria-checked', 'true'); }
    if (autoSendToggle) autoSendToggle.disabled = !next;
  });
  convoRow.appendChild(convoToggle);
  voicePanel.appendChild(convoRow);

  const autoSendRow = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' } });
  autoSendRow.appendChild(el('div', { style: { fontSize: 'var(--text-sm)' } }, 'Auto-send after talking'));
  autoSendToggle = el('button', { className: `toggle ${getState().settings.voiceAutoSend !== false ? 'active' : ''}`, type: 'button', role: 'switch', disabled: !getState().settings.voiceConversation, 'aria-checked': getState().settings.voiceAutoSend !== false ? 'true' : 'false' });
  autoSendToggle.addEventListener('click', () => {
    const next = getState().settings.voiceAutoSend === false;
    setState('settings', { voiceAutoSend: next }); saveSetting('voiceAutoSend', next);
    autoSendToggle.classList.toggle('active', next); autoSendToggle.setAttribute('aria-checked', next ? 'true' : 'false');
  });
  autoSendRow.appendChild(autoSendToggle);
  voicePanel.appendChild(autoSendRow);

  // Speech rate
  const rateRow = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' } });
  rateRow.appendChild(el('div', { style: { fontSize: 'var(--text-sm)' } }, 'Speech rate'));
  const rate = el('input', { type: 'range', min: '0.7', max: '1.3', step: '0.1', value: String(getState().settings.ttsRate || 1.0) });
  rate.style.maxWidth = '220px';
  rate.addEventListener('input', () => { const v = parseFloat(rate.value) || 1.0; setState('settings', { ttsRate: v }); saveSetting('ttsRate', v); });
  rateRow.appendChild(rate);
  voicePanel.appendChild(rateRow);

  // Voice selector
  const canTts = !!(window.speechSynthesis && window.SpeechSynthesisUtterance);
  const voiceRow = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)', marginTop: 'var(--space-2)' } });
  voiceRow.appendChild(el('div', { style: { fontSize: 'var(--text-sm)' } }, 'Voice'));
  const voiceSelect = el('select', { className: 'select input-sm', disabled: !canTts, style: { maxWidth: '260px' } });
  voiceSelect.appendChild(el('option', { value: '' }, 'Default'));
  voiceRow.appendChild(voiceSelect);
  voicePanel.appendChild(voiceRow);

  function populateVoices() {
    if (!canTts) return;
    const voices = window.speechSynthesis.getVoices?.() || [];
    const selected = getState().settings.ttsVoice || '', keep = voiceSelect.value;
    voiceSelect.innerHTML = '';
    voiceSelect.appendChild(el('option', { value: '' }, 'Default'));
    for (const v of voices) voiceSelect.appendChild(el('option', { value: v.voiceURI || v.name || '' }, `${v.name || 'Voice'} (${v.lang || 'unknown'})`));
    const nextVal = keep || selected || '';
    voiceSelect.value = Array.from(voiceSelect.options).some(o => o.value === nextVal) ? nextVal : '';
  }
  if (canTts) { try { populateVoices(); } catch { /* */ } try { window.speechSynthesis.onvoiceschanged = () => populateVoices(); } catch { /* */ } }
  voiceSelect.addEventListener('change', () => { const v = String(voiceSelect.value || '') || null; setState('settings', { ttsVoice: v }); saveSetting('ttsVoice', v); });

  // ════════════════════════════════════════════════════════
  //  TAB: About
  // ════════════════════════════════════════════════════════
  const aboutPanel = panels.about;
  aboutPanel.innerHTML = `
    <div style="font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.8;">
      <div style="font-size: var(--text-lg); font-weight: var(--font-bold); margin-bottom: var(--space-3);"><span id="aboutVersion">Thomas</span></div>
      Local-first AI coding assistant<br/>
      Built for developers who want control over their AI tools.<br/><br/>
      <div style="font-size: var(--text-xs); color: var(--text-muted);">
        Keyboard shortcut: <kbd style="padding: 1px 6px; background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: var(--radius-xs); font-family: var(--font-mono); font-size: 11px;">Ctrl+K</kbd> opens the command palette
      </div>
    </div>
  `;
  fetch('/api/version').then(r => r.ok ? r.json() : null).then(j => {
    const v = j?.version ? `Thomas v${j.version}` : 'Thomas';
    aboutPanel.querySelector('#aboutVersion')?.replaceChildren(document.createTextNode(v));
  }).catch(() => { /* */ });

  // ──── Create the modal ──────────────────────────────────
  const modal = createModal({
    title: 'Settings',
    body,
    wide: true,
    onClose: () => { _currentModal = null; setState('ui', { settingsOpen: false }); },
  });

  modal.switchTab = (tabId) => switchTab(tabId);
  _currentModal = modal;
  document.getElementById('modals')?.appendChild(modal.backdrop);
}
