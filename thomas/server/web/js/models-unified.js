/* ============================================================
   Thomas Models Unified
   ============================================================
   Combines model-picker + models-manager into one module.
   Exports:
     - initModelsUnified()       — load metadata, wire indicator
     - openQuickModelPicker()    — lightweight modal for fast switching
     - renderModelsTab(container) — full model management for Settings
   ============================================================ */

import { getState, setState, subscribe } from './store.js';
import { fetchModelHandshake, pullLocalModel } from './api.js';
import { el, icon, debounce } from './utils.js';
import { createModal, createButton, showToast } from './components.js';

let _modelMeta = {};
let _quickModal = null;

// ── Shared helpers ─────────────────────────────────────────

function getHandshake(profileName) {
  try { return getState().models.handshakes.get(profileName) || null; } catch { return null; }
}

function setHandshake(profileName, record) {
  try { getState().models.handshakes.set(profileName, record); setState('models', {}); } catch { /* */ }
}

function getDiscovered(profileName) {
  const list = getState().models.discovered.get(profileName);
  return Array.isArray(list) ? list : [];
}

function profileList() {
  return Array.isArray(getState().models.profiles) ? getState().models.profiles : [];
}

function profileByName(name) {
  return profileList().find(p => p.name === name) || null;
}

function currentProfile() {
  const s = getState();
  return s.activeProfile || s.models.defaultProfile || 'local';
}

function isLocal(name) { return String(name || '').toLowerCase() === 'local'; }

async function ensureHandshake(profileName) {
  if (!profileName || profileName === 'local') return;
  const existing = getHandshake(profileName);
  if (existing && (existing.status === 'ok' || existing.status === 'auth_error' || existing.status === 'unsupported' || existing.status === 'offline')) return;
  try {
    setHandshake(profileName, { ok: false, status: 'checking', models: [], error: null, checkedAt: Date.now() });
    const res = await fetchModelHandshake(profileName);
    setHandshake(profileName, { ...res, checkedAt: Date.now() });
    if (Array.isArray(res.models)) {
      try { getState().models.discovered.set(profileName, res.models); setState('models', {}); } catch { /* */ }
    }
  } catch (e) {
    setHandshake(profileName, { ok: false, status: 'error', models: [], error: e?.message || String(e), checkedAt: Date.now() });
  }
}

async function refreshDiscovered(profileName) {
  try {
    setHandshake(profileName, { ok: false, status: 'checking', models: [], error: null, checkedAt: Date.now() });
    const hs = await fetchModelHandshake(profileName);
    setHandshake(profileName, { ...hs, checkedAt: Date.now() });
    const ids = Array.isArray(hs.models) ? hs.models : [];
    getState().models.discovered.set(profileName, ids);
    setState('models', {});
    if (hs.ok) showToast(ids.length > 0 ? `Connected (${ids.length} models)` : 'Connected (no /models list)', ids.length > 0 ? 'success' : 'info');
    else if (hs.status === 'auth_error') showToast('Auth failed. Set/refresh the API key in Settings.', 'error');
    else if (hs.status === 'unsupported') showToast('Provider does not support /models. Try a chat to confirm.', 'info');
    else if (hs.status === 'offline') showToast('Provider offline/unreachable.', 'error');
    else showToast(`Check failed: ${hs.error || hs.status || 'unknown'}`, 'error');
  } catch (e) {
    setHandshake(profileName, { ok: false, status: 'error', models: [], error: e?.message || String(e), checkedAt: Date.now() });
    showToast(`Check failed: ${e.message || String(e)}`, 'error');
  }
}

function chipClass(profileName) {
  const hs = getHandshake(profileName);
  const p = profileByName(profileName);
  if (profileName === currentProfile()) return 'chip chip-accent';
  if (hs?.status === 'ok') return 'chip chip-success';
  if (hs?.status === 'auth_error' || hs?.status === 'offline') return 'chip chip-danger';
  if (hs?.status === 'unsupported' || hs?.status === 'checking') return 'chip chip-warning';
  if (!p?.has_api_key && !isLocal(profileName)) return 'chip chip-warning';
  return 'chip';
}

function getMeta(modelId) {
  return _modelMeta?.[modelId] || _modelMeta?.[String(modelId).split(':')[0]] || {};
}

// ── Model card (shared by picker and models tab) ───────────

function renderModelCard(modelId, profileName, { onClick, showUseBtn = false, showAlternatives = false } = {}) {
  const meta = getMeta(modelId);
  const settings = getState().settings;
  const gpuVram = settings.gpuVram || 10;
  const cfgModel = profileByName(profileName)?.model || '';
  const isSelected = modelId === (getState().activeModelId || cfgModel);

  const card = el('div', {
    className: 'card card-clickable',
    style: isSelected ? { borderColor: 'var(--accent)', boxShadow: '0 0 0 1px var(--accent)' } : {},
  });

  // Top row
  const topRow = el('div', { style: { display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' } });
  topRow.appendChild(el('strong', { style: { fontSize: 'var(--text-sm)' } }, meta.displayName || modelId));
  if (meta.provider || profileName) topRow.appendChild(el('span', { className: 'chip', style: { fontSize: '10px' } }, meta.provider || profileName));
  if (isSelected) topRow.appendChild(el('span', { className: 'chip chip-accent', style: { fontSize: '10px' } }, 'Active'));
  card.appendChild(topRow);

  // Tags
  const tags = meta.tags || [];
  if (tags.length > 0) {
    const tagsRow = el('div', { style: { display: 'flex', gap: 'var(--space-1)', flexWrap: 'wrap', marginBottom: 'var(--space-2)' } });
    for (const tag of tags) {
      const variants = { coding: 'accent', chat: '', reasoning: 'warning', vision: 'success', 'tool-use': 'accent' };
      tagsRow.appendChild(el('span', { className: `chip ${variants[tag] ? 'chip-' + variants[tag] : ''}`, style: { fontSize: '10px' } }, tag));
    }
    card.appendChild(tagsRow);
  }

  // Info row: VRAM + context + speed + quality
  const infoRow = el('div', { style: { display: 'flex', gap: 'var(--space-4)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } });
  if (meta.vramEstimateGB) {
    const fits = meta.vramEstimateGB <= gpuVram * 0.85;
    const maybe = meta.vramEstimateGB <= gpuVram;
    const badge = fits ? '\u2705' : maybe ? '\u26A0\uFE0F' : '\u274C';
    infoRow.appendChild(el('span', {}, `${badge} ${meta.vramEstimateGB}GB VRAM`));
  }
  if (meta.contextLength) infoRow.appendChild(el('span', {}, `${(meta.contextLength / 1000).toFixed(0)}K ctx`));
  if (meta.speedTier) {
    const speeds = { fast: '\u26A1', medium: '\uD83D\uDD04', slow: '\uD83D\uDC22' };
    infoRow.appendChild(el('span', {}, `${speeds[meta.speedTier] || ''} ${meta.speedTier}`));
  }
  if (meta.qualityTier) {
    const count = ({ excellent: 4, good: 3, decent: 2, basic: 1 }[meta.qualityTier] || 2);
    infoRow.appendChild(el('span', {}, '\u2605'.repeat(count)));
  }
  card.appendChild(infoRow);

  if (meta.bestAt) card.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: 'var(--space-2)' } }, meta.bestAt));

  // Alternatives
  if (showAlternatives) {
    const better = Array.isArray(meta.better) ? meta.better : [];
    const smaller = Array.isArray(meta.smaller) ? meta.smaller : [];
    if (better.length > 0 || smaller.length > 0) {
      const wrap = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px', marginTop: 'var(--space-2)' } });
      function addRow(label, ids) {
        if (!ids || ids.length === 0) return;
        const row = el('div', { style: { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' } });
        row.appendChild(el('span', { style: { fontSize: '11px', color: 'var(--text-muted)' } }, `${label}:`));
        for (const id of ids.slice(0, 3)) {
          const m = getMeta(id);
          const btn = el('button', { className: 'chip', type: 'button', style: { cursor: 'pointer' } }, m.displayName || id);
          btn.addEventListener('click', (e) => { e.stopPropagation(); setState('activeProfile', profileName); setState('activeModelId', id); if (onClick) onClick(); });
          row.appendChild(btn);
        }
        wrap.appendChild(row);
      }
      addRow('Better', better);
      addRow('Smaller', smaller);
      card.appendChild(wrap);
    }
  }

  // Use button (for models tab)
  if (showUseBtn && !isSelected) {
    const actions = el('div', { style: { display: 'flex', gap: '8px', marginTop: 'var(--space-2)' } });
    actions.appendChild(createButton({ label: 'Use', variant: 'primary', size: 'sm', onClick: () => {
      setState('activeProfile', profileName);
      setState('activeModelId', modelId);
      showToast(`Now using ${modelId}`, 'success');
      if (onClick) onClick();
    }}));
    card.appendChild(actions);
  }

  // Click to select (for quick picker)
  if (!showUseBtn && onClick) {
    card.addEventListener('click', () => {
      setState('activeProfile', profileName);
      setState('activeModelId', modelId);
      if (onClick) onClick();
    });
  }

  return card;
}

// ── Indicator text ─────────────────────────────────────────

function updateIndicator() {
  const state = getState();
  const text = document.getElementById('modelIndicatorText');
  const chevron = document.getElementById('modelIndicatorChevron');
  if (text) {
    const profile = state.activeProfile || state.models.defaultProfile || 'local';
    const modelId = state.activeModelId || '';
    text.textContent = modelId || profile;
  }
  if (chevron) chevron.replaceChildren(icon('chevronDown'));
}

// ── Init ───────────────────────────────────────────────────

export async function initModelsUnified() {
  try {
    const res = await fetch('/static/models.json');
    if (res.ok) _modelMeta = await res.json();
  } catch { _modelMeta = {}; }

  document.getElementById('modelIndicator')?.addEventListener('click', () => openQuickModelPicker());

  subscribe('activeProfile', updateIndicator);
  subscribe('activeModelId', updateIndicator);
  updateIndicator();

  // Listen for settings models tab event
  window.addEventListener('thomas:settings-models-tab', (ev) => {
    const container = ev?.detail?.container;
    if (container) renderModelsTab(container);
  });

  // If Settings was opened before this module finished booting, hydrate now.
  try {
    const existing = document.querySelector('.tab-panel[data-tab="models"]');
    if (existing) renderModelsTab(existing);
  } catch { /* ignore */ }
}

// ── Quick Model Picker (lightweight modal) ─────────────────

export async function openQuickModelPicker({ search = '' } = {}) {
  if (_quickModal) return;

  const state = getState();
  const profiles = state.models.profiles || [];
  const active = currentProfile();
  let unsubModels = null;

  // Ensure handshake for current profile
  await ensureHandshake(active);

  // Background handshakes for keyed profiles
  for (const p of profiles) {
    if (!p?.name || p.name === 'local' || !p.has_api_key) continue;
    ensureHandshake(p.name);
  }

  const body = el('div');

  // Search
  const searchInput = el('input', { className: 'input input-sm', type: 'text', placeholder: 'Search models...', style: { marginBottom: 'var(--space-3)' } });
  body.appendChild(searchInput);

  // Profile chips
  if (profiles.length > 1) {
    let showAll = false;
    const toggleRow = el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: 'var(--space-2)' } });
    toggleRow.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)' } }, 'Profiles'));
    const showAllBtn = el('button', { className: 'chip', type: 'button', style: { cursor: 'pointer' } }, 'connected only');
    toggleRow.appendChild(showAllBtn);
    body.appendChild(toggleRow);

    const profileRow = el('div', { style: { display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-3)', flexWrap: 'wrap' } });

    function shouldShow(p) {
      if (!p?.name) return false;
      if (showAll) return true;
      if (p.name === 'local' || p.name === active) return true;
      return getHandshake(p.name)?.status === 'ok';
    }

    function renderProfiles() {
      profileRow.innerHTML = '';
      for (const p of profiles) {
        if (!shouldShow(p)) continue;
        const btn = el('button', { className: chipClass(p.name), style: { cursor: 'pointer' }, type: 'button' }, p.name);
        btn.addEventListener('click', () => {
          setState('activeProfile', p.name);
          _quickModal?.close();
          _quickModal = null;
          openQuickModelPicker();
        });
        profileRow.appendChild(btn);
      }
    }

    showAllBtn.addEventListener('click', () => {
      showAll = !showAll;
      showAllBtn.textContent = showAll ? 'show all' : 'connected only';
      renderProfiles();
    });

    renderProfiles();
    body.appendChild(profileRow);
    unsubModels = subscribe('models', () => { try { renderProfiles(); } catch { /* */ } });
  }

  // Status hint
  const statusHint = el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', lineHeight: '1.6', marginBottom: 'var(--space-2)' } }, '');
  if (active !== 'local') {
    const hs = getHandshake(active);
    if (hs?.status && hs.status !== 'ok') {
      if (hs.status === 'auth_error') statusHint.textContent = 'Not connected (auth failed). Set/refresh the API key in Settings.';
      else if (hs.status === 'offline') statusHint.textContent = 'Provider unreachable.';
      else if (hs.status === 'unsupported') statusHint.textContent = 'Provider does not support /models.';
      else if (hs.status === 'checking') statusHint.textContent = 'Checking provider...';
      else statusHint.textContent = `Provider status: ${hs.status}`;
    }
  }
  if (statusHint.textContent) body.appendChild(statusHint);

  // Model cards
  const cardsContainer = el('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' } });
  body.appendChild(cardsContainer);

  function renderCards(filter = '') {
    cardsContainer.innerHTML = '';
    const fl = filter.toLowerCase();
    const profileModel = profileByName(active)?.model;
    const discovered = getDiscovered(active);
    const allModels = [...new Set([profileModel, ...discovered].filter(Boolean))];
    const filtered = allModels.filter(id => !fl || id.toLowerCase().includes(fl));

    if (filtered.length === 0) {
      cardsContainer.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-sm)', padding: 'var(--space-4)', textAlign: 'center' } }, 'No models found'));
      return;
    }

    for (const modelId of filtered) {
      cardsContainer.appendChild(renderModelCard(modelId, active, {
        showAlternatives: true,
        onClick: () => { _quickModal?.close(); _quickModal = null; },
      }));
    }
  }

  searchInput.addEventListener('input', debounce(() => renderCards(searchInput.value), 150));
  if (search) searchInput.value = search;
  renderCards(searchInput.value);

  // Footer link to full models management
  const footer = el('div', { style: { display: 'flex', justifyContent: 'center', paddingTop: 'var(--space-2)' } });
  const manageLink = el('button', {
    type: 'button',
    style: { background: 'none', border: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 'var(--text-xs)', textDecoration: 'underline' },
  }, 'Manage all models...');
  manageLink.addEventListener('click', () => {
    _quickModal?.close();
    _quickModal = null;
    // Lazy import to avoid circular dependency
    import('./settings.js').then(mod => mod.openSettings('models')).catch(() => {});
  });
  footer.appendChild(manageLink);
  body.appendChild(footer);

  const modal = createModal({
    title: 'Model Picker',
    body,
    onClose: () => {
      _quickModal = null;
      if (unsubModels) { try { unsubModels(); } catch { /* */ } unsubModels = null; }
    },
  });

  _quickModal = modal;
  document.getElementById('modals')?.appendChild(modal.backdrop);
  requestAnimationFrame(() => { searchInput.focus(); if (searchInput.value) searchInput.select(); });
}

// ── Full Models Tab (for Settings modal) ───────────────────

export function renderModelsTab(container) {
  container.innerHTML = '';

  let _pullAbort = null;
  let _pullingModelId = '';
  let _unsub = null;

  // Active model bar
  const activeBar = el('div', { className: 'card', style: { padding: 'var(--space-3)', marginBottom: 'var(--space-3)' } });
  container.appendChild(activeBar);

  // Profile chips
  const profileRow = el('div', { style: { display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' } });
  profileRow.appendChild(el('span', { style: { fontSize: '11px', color: 'var(--text-muted)', marginRight: '4px' } }, 'Profiles:'));
  container.appendChild(profileRow);

  // Search
  const searchInput = el('input', { className: 'input input-sm', type: 'text', placeholder: 'Search models...', style: { marginBottom: 'var(--space-3)' } });
  container.appendChild(searchInput);

  // Two-column grid
  const grid = el('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-3)' } });
  const availableCol = el('div');
  const recommendedCol = el('div');
  grid.appendChild(availableCol);
  grid.appendChild(recommendedCol);
  container.appendChild(grid);

  // Pull progress
  const progressWrap = el('div', { style: { display: 'none', marginTop: 'var(--space-3)' } });
  const progressHeader = el('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' } });
  const progressTitle = el('strong', { style: { fontSize: 'var(--text-sm)' } }, 'Pull progress');
  const cancelPullBtn = createButton({ label: 'Cancel', variant: 'danger', size: 'sm' });
  progressHeader.appendChild(progressTitle);
  progressHeader.appendChild(el('div', { style: { flex: '1' } }));
  progressHeader.appendChild(cancelPullBtn);
  const progressPre = el('pre', {
    style: { margin: '0', padding: '10px 12px', borderRadius: 'var(--radius-lg)', border: '1px solid var(--code-border)', background: 'var(--code-bg)', color: 'var(--code-text)', fontFamily: 'var(--font-mono)', fontSize: '12px', maxHeight: '220px', overflowY: 'auto', whiteSpace: 'pre-wrap' },
  }, '');
  progressWrap.appendChild(progressHeader);
  progressWrap.appendChild(progressPre);
  container.appendChild(progressWrap);

  cancelPullBtn.addEventListener('click', () => { if (_pullAbort) try { _pullAbort.abort(); } catch { /* */ } });

  function appendProgress(line) {
    const cur = progressPre.textContent || '';
    const next = (cur + (cur ? '\n' : '') + line).split('\n');
    progressPre.textContent = next.slice(-120).join('\n');
    progressPre.scrollTop = progressPre.scrollHeight;
  }

  function formatProgressLine(d) {
    if (!d || typeof d !== 'object') return String(d || '');
    const status = d.status ? String(d.status) : '';
    if (typeof d.completed === 'number' && typeof d.total === 'number' && d.total > 0) return `${status} (${Math.floor((d.completed / d.total) * 100)}%)`;
    if (status) return status;
    return JSON.stringify(d);
  }

  async function startPull(modelId, { useAfter = false } = {}) {
    if (!modelId) return;
    if (_pullAbort) try { _pullAbort.abort(); } catch { /* */ }
    _pullingModelId = modelId;
    progressWrap.style.display = 'block';
    progressPre.textContent = '';
    appendProgress(`Starting pull: ${modelId}`);

    const ac = new AbortController();
    _pullAbort = ac;
    let finalOk = null;
    try {
      await pullLocalModel(modelId, (ev) => {
        if (ev?.type === 'progress') appendProgress(formatProgressLine(ev.data));
        else if (ev?.type === 'error') { appendProgress(`ERROR: ${ev.error || 'unknown error'}`); finalOk = false; }
        else if (ev?.type === 'done') { finalOk = !!ev.ok; appendProgress(finalOk ? 'Done.' : 'Failed.'); }
        else appendProgress(JSON.stringify(ev));
      }, ac.signal);
      if (finalOk === false) { showToast(`Pull failed: ${modelId}`, 'error'); return; }
      showToast(`Pulled ${modelId}`, 'success');
      await refreshDiscovered('local');
      if (useAfter) { setState('activeProfile', 'local'); setState('activeModelId', modelId); showToast(`Now using ${modelId}`, 'info'); }
    } catch (e) {
      if (String(e?.name || '') === 'AbortError') { appendProgress('Cancelled.'); showToast('Pull cancelled', 'info'); }
      else { appendProgress(`ERROR: ${e.message || String(e)}`); showToast(`Pull failed: ${e.message || String(e)}`, 'error'); }
    } finally {
      _pullingModelId = '';
      _pullAbort = null;
      render();
    }
  }

  function renderActiveBar() {
    activeBar.innerHTML = '';
    const profile = currentProfile();
    const modelId = getState().activeModelId || profileByName(profile)?.model || '';
    const meta = getMeta(modelId);
    activeBar.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' } }, 'Active model'));
    const row = el('div', { style: { display: 'flex', alignItems: 'center', gap: 'var(--space-2)' } });
    row.appendChild(el('strong', { style: { fontSize: 'var(--text-sm)' } }, meta.displayName || modelId || '(none)'));
    row.appendChild(el('span', { className: 'chip chip-accent', style: { fontSize: '10px' } }, profile));
    activeBar.appendChild(row);
  }

  function renderProfiles() {
    profileRow.innerHTML = '';
    profileRow.appendChild(el('span', { style: { fontSize: '11px', color: 'var(--text-muted)', marginRight: '4px' } }, 'Profiles:'));
    const active = currentProfile();
    for (const p of profileList()) {
      const btn = el('button', { className: chipClass(p.name), style: { cursor: 'pointer' }, type: 'button' }, p.name);
      btn.addEventListener('click', () => {
        setState('activeProfile', p.name);
        render();
        refreshDiscovered(p.name);
      });
      profileRow.appendChild(btn);
    }
  }

  function renderAvailable(profileName, filter) {
    availableCol.innerHTML = '';
    availableCol.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)', marginBottom: '8px' } }, 'Available'));

    const discovered = getDiscovered(profileName);
    const cfgModel = profileByName(profileName)?.model;
    const all = [...new Set([cfgModel, ...discovered].filter(Boolean))];
    const fl = (filter || '').toLowerCase();
    const filtered = all.filter(id => !fl || String(id).toLowerCase().includes(fl));

    if (filtered.length === 0) {
      availableCol.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-sm)', padding: '10px 0' } }, 'No models found'));
      return;
    }

    const list = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } });
    for (const modelId of filtered.slice(0, 220)) {
      list.appendChild(renderModelCard(modelId, profileName, {
        showUseBtn: true,
        onClick: () => render(),
      }));
    }
    availableCol.appendChild(list);
  }

  function renderRecommended(profileName, filter) {
    recommendedCol.innerHTML = '';
    recommendedCol.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)', marginBottom: '8px' } }, 'Recommended (Local)'));

    const local = isLocal(profileName);
    const installed = new Set(getDiscovered('local'));
    const cfgModel = profileByName('local')?.model;
    if (cfgModel) installed.add(cfgModel);

    const fl = (filter || '').toLowerCase();
    const ids = Object.keys(_modelMeta || {}).filter(id => (_modelMeta[id]?.provider || '') === 'local');
    const filtered = ids.filter(id => !fl || id.toLowerCase().includes(fl) || String((_modelMeta[id]?.displayName || '')).toLowerCase().includes(fl));

    // Manual pull
    const manual = el('div', { className: 'card', style: { marginBottom: '10px' } });
    manual.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: '6px' } }, 'Pull by id (Ollama tag)'));
    const manualRow = el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } });
    const manualInput = el('input', { className: 'input input-sm', type: 'text', placeholder: 'e.g. qwen3-coder:30b-instruct', style: { flex: '1' } });
    const manualPull = createButton({ label: 'Pull', variant: 'primary', size: 'sm', disabled: !local, onClick: () => { const v = (manualInput.value || '').trim(); if (v) startPull(v); } });
    manualRow.appendChild(manualInput);
    manualRow.appendChild(manualPull);
    manual.appendChild(manualRow);
    if (!local) manual.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' } }, 'Switch to the local profile to pull models.'));
    recommendedCol.appendChild(manual);

    if (filtered.length === 0) {
      recommendedCol.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-sm)', padding: '10px 0' } }, 'No recommendations found'));
      return;
    }

    const list = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } });
    for (const modelId of filtered.slice(0, 80)) {
      const meta = getMeta(modelId);
      const isInstalled = installed.has(modelId);

      const card = el('div', { className: 'card' });
      const top = el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' } });
      top.appendChild(el('strong', { style: { fontSize: 'var(--text-sm)' } }, meta.displayName || modelId));
      if (meta.vramEstimateGB) top.appendChild(el('span', { className: 'chip', style: { fontSize: '10px' } }, `${meta.vramEstimateGB}GB`));
      if (isInstalled) top.appendChild(el('span', { className: 'chip chip-success', style: { fontSize: '10px' } }, 'Installed'));
      card.appendChild(top);

      card.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' } }, modelId));
      if (meta.bestAt) card.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: '6px' } }, meta.bestAt));

      const actions = el('div', { style: { display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' } });
      if (isInstalled) {
        actions.appendChild(createButton({ label: 'Use', variant: 'primary', size: 'sm', onClick: () => {
          setState('activeProfile', 'local');
          setState('activeModelId', modelId);
          showToast(`Now using ${modelId}`, 'success');
          render();
        }}));
      } else {
        actions.appendChild(createButton({ label: _pullingModelId === modelId ? 'Pulling...' : 'Pull', variant: 'primary', size: 'sm', disabled: !local || !!_pullingModelId, onClick: () => startPull(modelId) }));
        actions.appendChild(createButton({ label: 'Pull + Use', variant: 'ghost', size: 'sm', disabled: !local || !!_pullingModelId, onClick: () => startPull(modelId, { useAfter: true }) }));
      }
      card.appendChild(actions);
      list.appendChild(card);
    }
    recommendedCol.appendChild(list);
  }

  function render() {
    renderActiveBar();
    renderProfiles();
    const profileName = currentProfile();
    const filter = searchInput.value || '';
    renderAvailable(profileName, filter);
    renderRecommended(profileName, filter);
    if (!_pullingModelId) { cancelPullBtn.disabled = true; } else { cancelPullBtn.disabled = false; }
  }

  searchInput.addEventListener('input', debounce(render, 120));
  _unsub = subscribe('activeProfile', render);

  render();
  refreshDiscovered(currentProfile());
}
