/* ============================================================
   Thomas Setup Wizard
   ============================================================
   First-run (or on-demand) wizard that walks the user through
   connecting AI providers. Shows a clean card for each provider
   with: paste key → test → done, all in one flow.

   Also provides a "Test All Providers" panel accessible from
   Settings.
   ============================================================ */

import { getState, setState } from './store.js';
import { saveSetting } from './db.js';
import { el, icon } from './utils.js';
import { createModal, createButton, showToast } from './components.js';
import { fetchSecrets, setProfileApiKey, fetchModelHandshake, fetchModels } from './api.js';

// ─── Provider metadata ────────────────────────────────────
const PROVIDERS = [
  { name: 'local', label: 'Local (Ollama)', desc: 'Run models on your own GPU. No API key needed.', icon: '🖥️', noKey: true, priority: 1 },
  { name: 'openrouter', label: 'OpenRouter', desc: 'One key for 200+ models. Best starting point for cloud.', icon: '🔀', priority: 2, signup: 'https://openrouter.ai/keys', free: true },
  { name: 'groq', label: 'Groq', desc: 'Ultra-fast inference. Free tier available.', icon: '⚡', priority: 3, signup: 'https://console.groq.com/keys', free: true },
  { name: 'openai', label: 'OpenAI', desc: 'GPT-4o, GPT-4o-mini. Pay per token.', icon: '🟢', priority: 4, signup: 'https://platform.openai.com/api-keys' },
  { name: 'anthropic', label: 'Anthropic', desc: 'Claude Sonnet, Opus, Haiku.', icon: '🟠', priority: 5, signup: 'https://console.anthropic.com/settings/keys' },
  { name: 'together', label: 'Together', desc: 'Open-source models. Good Llama support.', icon: '🤝', priority: 6, signup: 'https://api.together.ai/settings/api-keys' },
  { name: 'mistral', label: 'Mistral', desc: 'Mistral Large, Codestral, Devstral.', icon: '🌊', priority: 7, signup: 'https://console.mistral.ai/api-keys/' },
  { name: 'xai', label: 'xAI', desc: 'Grok models.', icon: '🅧', priority: 8, signup: 'https://console.x.ai/' },
  { name: 'deepinfra', label: 'DeepInfra', desc: 'Cheap inference for open-source models.', icon: '🔥', priority: 9, signup: 'https://deepinfra.com/dash/api_keys' },
  { name: 'fireworks', label: 'Fireworks', desc: 'Fast serverless inference.', icon: '🎆', priority: 10, signup: 'https://fireworks.ai/account/api-keys' },
  { name: 'perplexity', label: 'Perplexity', desc: 'Search-augmented AI.', icon: '🔍', priority: 11, signup: 'https://www.perplexity.ai/settings/api' },
  { name: 'cerebras', label: 'Cerebras', desc: 'Hardware-accelerated inference.', icon: '🧠', priority: 12, signup: 'https://cloud.cerebras.ai/' },
];

function getProviderMeta(name) {
  return PROVIDERS.find(p => p.name === name) || null;
}

// ─── State tracking for wizard ────────────────────────────
// status: 'idle' | 'testing' | 'success' | 'auth_error' | 'offline' | 'error'
const _providerStatus = new Map();

function setStatus(name, status, detail = '') {
  _providerStatus.set(name, { status, detail, at: Date.now() });
}

function getStatus(name) {
  return _providerStatus.get(name) || { status: 'idle', detail: '' };
}

// ─── Test a single provider ──────────────────────────────
async function testProvider(name, opts = {}) {
  const { onUpdate } = opts;
  setStatus(name, 'testing');
  if (onUpdate) onUpdate(name, 'testing');

  try {
    // Update handshake in store so model picker sees it too
    try {
      getState().models.handshakes.set(name, { ok: false, status: 'checking', models: [], error: null, checkedAt: Date.now() });
      setState('models', {});
    } catch { /* ignore */ }

    const res = await fetchModelHandshake(name);

    // Cache discovered models
    if (Array.isArray(res.models) && res.models.length > 0) {
      try {
        getState().models.discovered.set(name, res.models);
        setState('models', {});
      } catch { /* ignore */ }
    }

    // Update handshake in store
    try {
      getState().models.handshakes.set(name, { ...res, checkedAt: Date.now() });
      setState('models', {});
    } catch { /* ignore */ }

    const status = res.ok ? 'success' : (res.status || 'error');
    const detail = res.ok
      ? `Connected${res.models?.length ? ` — ${res.models.length} models` : ''}`
      : (res.error || res.status || 'Unknown error');

    setStatus(name, status, detail);
    if (onUpdate) onUpdate(name, status, detail);
    return { ok: res.ok, status, detail, models: res.models || [] };
  } catch (e) {
    const detail = e?.message || String(e);
    setStatus(name, 'error', detail);
    if (onUpdate) onUpdate(name, 'error', detail);
    return { ok: false, status: 'error', detail, models: [] };
  }
}

// ─── Test all configured providers ────────────────────────
async function testAllProviders(opts = {}) {
  const { onUpdate, onComplete } = opts;
  const profiles = getState().models.profiles || [];
  const results = new Map();

  // Test in parallel (with a concurrency limit of 4)
  const queue = profiles.filter(p => p.name !== 'local' && p.has_api_key).map(p => p.name);

  // Also test local
  const localProfile = profiles.find(p => p.name === 'local');
  if (localProfile) {
    queue.unshift('local');
  }

  const running = new Set();
  const allDone = [];

  async function runOne(name) {
    running.add(name);
    const result = await testProvider(name, { onUpdate });
    results.set(name, result);
    running.delete(name);
    allDone.push(name);
  }

  // Simple concurrency limiter
  const batches = [];
  for (let i = 0; i < queue.length; i += 4) {
    batches.push(queue.slice(i, i + 4));
  }
  for (const batch of batches) {
    await Promise.all(batch.map(name => runOne(name)));
  }

  if (onComplete) onComplete(results);
  return results;
}

// ─── Status badge element ─────────────────────────────────
function statusBadge(status, detail = '') {
  const badges = {
    idle:       { text: 'Not tested', cls: '', emoji: '⬜' },
    testing:    { text: 'Testing...', cls: 'chip-warning', emoji: '🔄' },
    success:    { text: 'Connected', cls: 'chip-success', emoji: '✅' },
    ok:         { text: 'Connected', cls: 'chip-success', emoji: '✅' },
    auth_error: { text: 'Auth failed', cls: 'chip-danger', emoji: '🔑' },
    offline:    { text: 'Offline', cls: 'chip-danger', emoji: '📡' },
    unsupported:{ text: 'No /models', cls: 'chip-warning', emoji: '⚠️' },
    error:      { text: 'Error', cls: 'chip-danger', emoji: '❌' },
  };

  const b = badges[status] || badges.error;
  const badge = el('span', {
    className: `chip ${b.cls}`.trim(),
    style: { fontSize: '11px', transition: 'all 200ms ease' },
    title: detail || b.text,
  }, `${b.emoji} ${detail || b.text}`);

  if (status === 'testing') {
    badge.style.animation = 'pulse 1.2s ease-in-out infinite';
  }

  return badge;
}

// ─── Provider card for wizard ─────────────────────────────
function createProviderCard(providerMeta, profile, secretRow, opts = {}) {
  const { onKeySet, minimal } = opts;
  const name = providerMeta.name;
  const hasKey = !!(secretRow?.has_key || profile?.has_api_key);
  const isLocal = name === 'local';

  const card = el('div', {
    className: 'card',
    style: { padding: 'var(--space-3)', transition: 'border-color 200ms ease' },
    dataset: { provider: name },
  });

  // Top row: icon + name + status
  const top = el('div', { style: { display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' } });
  top.appendChild(el('span', { style: { fontSize: '20px' } }, providerMeta.icon));
  top.appendChild(el('strong', { style: { fontSize: 'var(--text-sm)', flex: '1' } }, providerMeta.label));

  // Status badge container (updated dynamically)
  const statusContainer = el('span', { className: 'wizard-status' });
  const currentStatus = getStatus(name);
  if (currentStatus.status !== 'idle') {
    statusContainer.replaceChildren(statusBadge(currentStatus.status, currentStatus.detail));
  } else if (isLocal) {
    statusContainer.replaceChildren(statusBadge('idle', 'Click Test to check'));
  } else if (hasKey) {
    statusContainer.replaceChildren(statusBadge('idle', 'Key set — test it'));
  }
  top.appendChild(statusContainer);
  card.appendChild(top);

  // Description
  card.appendChild(el('div', {
    style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-2)', lineHeight: '1.5' }
  }, providerMeta.desc));

  if (providerMeta.free) {
    card.appendChild(el('span', {
      className: 'chip chip-success',
      style: { fontSize: '10px', marginBottom: 'var(--space-2)' },
    }, '🆓 Free tier'));
  }

  // Actions row
  const actions = el('div', { style: { display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', alignItems: 'center' } });

  if (!isLocal) {
    // Key input inline (more streamlined than a separate modal)
    const keyInput = el('input', {
      className: 'input input-sm',
      type: 'password',
      placeholder: hasKey ? '••••• (key set, paste to replace)' : 'Paste API key...',
      autocomplete: 'off',
      spellcheck: 'false',
      style: { flex: '1', minWidth: '160px', maxWidth: '320px' },
    });
    actions.appendChild(keyInput);

    // Save + Test button
    const saveTestBtn = createButton({
      label: hasKey ? '🔄 Test' : '💾 Save & Test',
      variant: 'primary',
      size: 'sm',
      onClick: async () => {
        const key = (keyInput.value || '').trim();

        if (key) {
          // Save the key first
          try {
            saveTestBtn.disabled = true;
            saveTestBtn.textContent = 'Saving...';
            await setProfileApiKey(name, key, true);
            keyInput.value = '';
            keyInput.placeholder = '••••• (key set, paste to replace)';
            showToast(`Key saved for ${providerMeta.label}`, 'success');

            // Refresh models list
            try {
              const m = await fetchModels();
              setState('models', { profiles: m.profiles || [], defaultProfile: m.default || null });
            } catch { /* ignore */ }
          } catch (e) {
            showToast(`Failed to save: ${e.message || String(e)}`, 'error');
            saveTestBtn.disabled = false;
            saveTestBtn.textContent = hasKey ? '🔄 Test' : '💾 Save & Test';
            return;
          }
        } else if (!hasKey) {
          showToast('Paste an API key first', 'error');
          keyInput.focus();
          return;
        }

        // Test it
        statusContainer.replaceChildren(statusBadge('testing'));
        saveTestBtn.disabled = true;
        saveTestBtn.textContent = 'Testing...';
        card.style.borderColor = 'var(--warning)';

        const result = await testProvider(name, {
          onUpdate: (_, status, detail) => {
            statusContainer.replaceChildren(statusBadge(status, detail));
          },
        });

        saveTestBtn.disabled = false;
        saveTestBtn.textContent = '🔄 Test';

        if (result.ok) {
          card.style.borderColor = 'var(--success)';
          setTimeout(() => { card.style.borderColor = ''; }, 3000);
          if (onKeySet) onKeySet(name, result);
        } else {
          card.style.borderColor = 'var(--danger)';
          setTimeout(() => { card.style.borderColor = ''; }, 3000);
        }
      },
    });
    actions.appendChild(saveTestBtn);

    // Get key link
    if (providerMeta.signup) {
      actions.appendChild(createButton({
        label: '🔑 Get key',
        variant: 'ghost',
        size: 'sm',
        onClick: () => {
          try { window.open(providerMeta.signup, '_blank', 'noopener,noreferrer'); } catch { /* ignore */ }
        },
      }));
    }
  } else {
    // Local: just a test button
    const testLocalBtn = createButton({
      label: '🔄 Test Ollama',
      variant: 'primary',
      size: 'sm',
      onClick: async () => {
        statusContainer.replaceChildren(statusBadge('testing'));
        testLocalBtn.disabled = true;
        testLocalBtn.textContent = 'Testing...';
        card.style.borderColor = 'var(--warning)';

        const result = await testProvider(name, {
          onUpdate: (_, status, detail) => {
            statusContainer.replaceChildren(statusBadge(status, detail));
          },
        });

        testLocalBtn.disabled = false;
        testLocalBtn.textContent = '🔄 Test Ollama';

        if (result.ok) {
          card.style.borderColor = 'var(--success)';
          setTimeout(() => { card.style.borderColor = ''; }, 3000);
        } else {
          card.style.borderColor = 'var(--danger)';
          setTimeout(() => { card.style.borderColor = ''; }, 3000);
        }
      },
    });
    actions.appendChild(testLocalBtn);
  }

  card.appendChild(actions);
  return { card, statusContainer };
}

// ─── Setup Wizard Modal ───────────────────────────────────
export function openSetupWizard() {
  const profiles = getState().models.profiles || [];
  const profileMap = new Map(profiles.map(p => [p.name, p]));

  const body = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' } });

  // Header
  body.appendChild(el('div', { style: { fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: 'var(--space-2)' } },
    'Connect your AI providers. Paste an API key, hit Test, done. Keys are encrypted and stored locally on this machine.'
  ));

  // Quick stats bar
  const statsBar = el('div', {
    style: { display: 'flex', gap: 'var(--space-3)', padding: 'var(--space-2) var(--space-3)', background: 'var(--surface-raised)', borderRadius: 'var(--radius-lg)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' },
  });
  const connectedCount = el('span', {}, '⬜ 0 connected');
  const totalCount = el('span', {}, `📋 ${profiles.length} providers configured`);
  statsBar.appendChild(connectedCount);
  statsBar.appendChild(totalCount);
  body.appendChild(statsBar);

  let connectedN = 0;
  function updateStats() {
    connectedCount.textContent = `✅ ${connectedN} connected`;
  }

  // Test All button
  const testAllRow = el('div', { style: { display: 'flex', gap: 'var(--space-2)', alignItems: 'center' } });
  const testAllBtn = createButton({
    label: '🧪 Test All Configured',
    variant: 'primary',
    size: 'sm',
    onClick: async () => {
      testAllBtn.disabled = true;
      testAllBtn.textContent = '🔄 Testing all...';
      connectedN = 0;

      await testAllProviders({
        onUpdate: (name, status, detail) => {
          if (status === 'success' || status === 'ok') connectedN++;
          updateStats();
        },
        onComplete: (results) => {
          testAllBtn.disabled = false;
          testAllBtn.textContent = '🧪 Test All Configured';
          const ok = Array.from(results.values()).filter(r => r.ok).length;
          const fail = results.size - ok;
          showToast(`Done: ${ok} connected, ${fail} failed`, ok > 0 ? 'success' : 'error');
          updateStats();
        },
      });
    },
  });
  testAllRow.appendChild(testAllBtn);
  testAllRow.appendChild(el('span', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }, 'Tests all providers that have API keys set'));
  body.appendChild(testAllRow);

  // Provider cards (sorted by priority — recommended first)
  const cardsContainer = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' } });

  // Fetch secrets for has_key info, then render
  fetchSecrets().then(secretsData => {
    const secretMap = new Map((secretsData?.profiles || []).map(s => [s.name, s]));

    const sorted = PROVIDERS.filter(pm => profileMap.has(pm.name)).sort((a, b) => a.priority - b.priority);

    for (const pm of sorted) {
      const profile = profileMap.get(pm.name);
      const secret = secretMap.get(pm.name);
      const { card } = createProviderCard(pm, profile, secret, {
        onKeySet: (name, result) => {
          if (result.ok) {
            connectedN++;
            updateStats();
          }
        },
      });
      cardsContainer.appendChild(card);
    }

    // Any profiles NOT in our PROVIDERS list (custom user profiles)
    for (const p of profiles) {
      if (PROVIDERS.some(pm => pm.name === p.name)) continue;
      const secret = secretMap.get(p.name);
      const customMeta = {
        name: p.name,
        label: p.name,
        desc: `${p.provider} — ${p.base_url}`,
        icon: '🔧',
        noKey: false,
        priority: 99,
      };
      const { card } = createProviderCard(customMeta, p, secret, {
        onKeySet: (name, result) => {
          if (result.ok) {
            connectedN++;
            updateStats();
          }
        },
      });
      cardsContainer.appendChild(card);
    }
  }).catch(err => {
    cardsContainer.appendChild(el('div', { style: { color: 'var(--danger)', fontSize: 'var(--text-sm)' } },
      `Failed to load secrets: ${err?.message || String(err)}. Check server URL and access token settings.`
    ));
  });

  body.appendChild(cardsContainer);

  // Tip
  body.appendChild(el('div', {
    style: { fontSize: '11px', color: 'var(--text-muted)', lineHeight: '1.6', padding: 'var(--space-2) 0', borderTop: '1px solid var(--border)' }
  }, '💡 Tip: OpenRouter is the easiest way to get started — one key gives you access to OpenAI, Anthropic, Meta, and 200+ other models. Groq offers free ultra-fast inference.'));

  const doneBtn = createButton({
    label: 'Done',
    variant: 'primary',
    onClick: () => {
      modal.close();
      // Mark setup as completed
      setState('settings', { setupCompleted: true });
      saveSetting('setupCompleted', true);
    },
  });

  const modal = createModal({
    title: '🚀 Provider Setup',
    body,
    footer: [doneBtn],
  });

  document.getElementById('modals')?.appendChild(modal.backdrop);
}

// ─── Test All Panel (for Settings) ────────────────────────
export function createTestAllPanel() {
  const panel = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' } });

  const header = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)' } });
  header.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)' } }, '🧪 Provider Health Check'));

  const testBtn = createButton({
    label: 'Test All',
    variant: 'primary',
    size: 'sm',
    onClick: async () => {
      testBtn.disabled = true;
      testBtn.textContent = 'Testing...';
      resultsList.innerHTML = '';

      await testAllProviders({
        onUpdate: (name, status, detail) => {
          // Update or add row
          let row = resultsList.querySelector(`[data-provider="${name}"]`);
          if (!row) {
            row = el('div', {
              dataset: { provider: name },
              style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)', padding: '4px 0' },
            });
            row.appendChild(el('span', { style: { fontSize: 'var(--text-xs)' } }, name));
            row.appendChild(el('span', { className: 'test-result' }));
            resultsList.appendChild(row);
          }
          row.querySelector('.test-result')?.replaceChildren(statusBadge(status, detail));
        },
        onComplete: (results) => {
          testBtn.disabled = false;
          testBtn.textContent = 'Test All';
          const ok = Array.from(results.values()).filter(r => r.ok).length;
          showToast(`Health check: ${ok}/${results.size} providers connected`, ok > 0 ? 'success' : 'error');
        },
      });
    },
  });
  header.appendChild(testBtn);
  panel.appendChild(header);

  const resultsList = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } });
  panel.appendChild(resultsList);

  return panel;
}

// ─── First-run detection ──────────────────────────────────
export function shouldShowSetupWizard() {
  const settings = getState().settings;
  if (settings.setupCompleted) return false;

  // Check if any cloud provider has a key set
  const profiles = getState().models.profiles || [];
  const hasAnyCloudKey = profiles.some(p => p.name !== 'local' && p.has_api_key);

  // Show wizard if no cloud keys are configured
  return !hasAnyCloudKey;
}

// ─── Init: called from app.js ─────────────────────────────
export function initSetupWizard() {
  // Auto-show on first run (slight delay so UI is rendered first)
  setTimeout(() => {
    if (shouldShowSetupWizard()) {
      openSetupWizard();
    }
  }, 1200);
}

// Re-export for use in settings
export { testProvider, testAllProviders, statusBadge, PROVIDERS };
