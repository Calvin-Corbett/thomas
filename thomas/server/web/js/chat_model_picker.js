/* Chat model picker. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Model selector ----------
    function profileModelOptions(p) {
      if (p && Array.isArray(p.models) && p.models.length) return p.models;
      return [{ id: String(p && (p.model || p.name) || 'model'), display_name: String(p && (p.model || p.name) || 'model'), is_default: true, available: true }];
    }

    // One live list for every connection (thomas/models/catalog.py). It replaced a
    // per-profile ChatGPT fetch that answered from a hand-typed list, which is why
    // GPT-6 never showed here.
    // The list as it was last seen is applied at once (the menu is not empty while the live one loads); the live
    // one replaces it, and a failed fetch leaves it in place rather than blanking the menu.
    const CATALOG_KEY = 'thomas_models_catalog_v1';
    async function hydrateProfileModels() {
      try {
        const saved = JSON.parse(localStorage.getItem(CATALOG_KEY) || 'null');
        if (saved && Array.isArray(saved.models)) applyCatalog(saved);
      } catch (e) { /* an unreadable copy is ignored */ }
      let data = null;
      try {
        const r = await fetch('/api/models/catalog');
        if (r.ok) data = await r.json();
      } catch (e) {}
      if (data) {
        try { localStorage.setItem(CATALOG_KEY, JSON.stringify(data)); } catch (e) { /* just not remembered */ }
        applyCatalog(data);
      } else if (!deps.state.catalog) {
        applyCatalog(null);
      }
    }

    function applyCatalog(data) {
      deps.state.catalog = data || null;
      const rows = data && Array.isArray(data.models) ? data.models : [];
      deps.profilesData.forEach(p => {
        // A keyless cloud profile (OpenRouter, DeepInfra, ...) never gets live
        // rows here: the server already refuses to ask it (thomas/models/sources),
        // but a stale cached catalog from before that fix could still carry its
        // public list. Gate on usability here too so it never floods the menu.
        if (!profileIsUsable(p)) return;
        const mine = rows.filter(m => m.profile === p.name && m.source === 'live' && !m.hidden);
        if (mine.length) p.models = mine.map(m => Object.assign({}, m, { is_default: m.id === p.model, available: true }));
      });
    }

    async function checkForNewModels() {
      deps.state.catalogChecking = true; renderModelMenu();
      try {
        const r = await fetch('/api/models/catalog/refresh', { method: 'POST' });
        if (r.ok) applyCatalog(await r.json());
      } catch (e) {}
      deps.state.catalogChecking = false; renderModelMenu();
    }

    function checkedLabel() {
      const providers = (deps.state.catalog && deps.state.catalog.providers) || {};
      // A working keyless or public provider must never mask a failed usable
      // one (e.g. ChatGPT): only usable profiles' state counts toward the line.
      const usableNames = new Set(deps.profilesData.filter(profileIsUsable).map(p => p.name));
      const states = Object.keys(providers).filter(name => usableNames.has(name)).map(name => providers[name]);
      const failing = states.find(s => {
        const attempted = Date.parse((s && s.last_attempt_at) || '') || 0;
        const checked = Date.parse((s && s.checked_at) || '') || 0;
        return !!(s && s.error) && attempted > checked;
      });
      // failing.error is server text rendered via textContent by the caller.
      if (failing) return failing.error;
      const times = states.map(s => Date.parse(s.checked_at || '')).filter(t => !isNaN(t));
      if (!times.length) return 'Not checked yet';
      const mins = Math.max(0, Math.round((Date.now() - Math.max(...times)) / 60000));
      if (mins < 1) return 'Checked just now';
      return mins < 60 ? `Checked ${mins} min ago` : `Checked ${Math.round(mins / 60)} h ago`;
    }

    function retirementNote(m) {
      if (!m.retires_at) return '';
      const when = new Date(m.retires_at);
      const day = isNaN(when) ? '' : when.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      return `Retires ${day}${m.replacement ? ' - switch to ' + m.replacement : ''}`;
    }

    function persistModelSelection(profileName, modelId) {
      fetch('/api/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ advanced: { model: { active_profile: profileName, model_id: modelId } } }),
      }).catch(() => {});
    }

    function setProfile(p, modelOption, options) {
      if (!p) return;
      // keepId (chat_boot.js, on load): the saved model this connection stopped
      // offering. There is no modelOption to fall back on a default from, so the
      // usual choice search is skipped -- but every other consequence of picking
      // a profile (effort reconciliation, the cross-tab `changed` notification)
      // still runs, the same as any other selection.
      const keepId = !modelOption && options && typeof options.keepId === 'string' && options.keepId ? options.keepId : '';
      let choice = null;
      if (!keepId) {
        const models = profileModelOptions(p);
        choice = modelOption || models.find(m => m.is_default && m.available !== false) || models.find(m => m.available !== false) || models[0];
        if (!choice || choice.available === false) return;
      }
      deps.state.profile = p.name;
      deps.state.modelId = keepId || choice.id || p.model || '';
      deps.state.modelLabel = keepId ? keepId.split('/').pop() : String(choice.display_name || choice.id || p.model || p.name || 'model').split('/').pop();
      const el = document.getElementById('tc-model'); if (el) el.textContent = deps.state.modelLabel;
      const effortControl = p.chat_controls && p.chat_controls.model && p.chat_controls.model.reasoning_effort;
      const validEfforts = effortControl && Array.isArray(effortControl.options) ? effortControl.options.map(o => String(o.value)) : [];
      if (validEfforts.length && !validEfforts.includes(String(deps.state.dials.effort))) {
        deps.state.dials.effort = String(effortControl.default_value || 'medium'); deps.saveDials();
      }
      if (modelOption && (!options || options.persist !== false)) persistModelSelection(deps.state.profile, deps.state.modelId);
      if (window.ThomasChatModelSelection) window.ThomasChatModelSelection.changed(!!modelOption && (!options || options.persist !== false));
    }

    function toggleModelMenu() {
      deps.state.modelMenuOpen = !deps.state.modelMenuOpen;
      if (deps.state.modelMenuOpen) deps.state.modelKeysOpen = false;
      document.getElementById('tc-model-menu').style.display = deps.state.modelMenuOpen ? 'block' : 'none';
      if (deps.state.modelMenuOpen) renderModelMenu();
    }

    function closeModelMenu() { deps.state.modelMenuOpen = false; document.getElementById('tc-model-menu').style.display = 'none'; }

    // Which vendor a profile belongs to. Grouped by FAMILY rather than listed
    // flat because the flat list was one row per model across every profile,
    // and with only one provider holding a key the four models that actually
    // work were buried among fifteen that cannot run — so the picker read as
    // "you have one model" when it has four.
    const MODEL_FAMILIES = [
      // Matched on the profile NAME, never on `provider`: `openai_compat` is a
      // wire protocol, not a vendor, and almost every profile here speaks it —
      // Gemini, Mistral, Groq and xAI included. Matching the provider put all
      // of them under "OpenAI".
      { id: 'openai',    label: 'OpenAI',      match: p => /^(openai|openai_codex|litellm)$/.test(p.name) },
      { id: 'anthropic', label: 'Anthropic',   match: p => p.name === 'anthropic' || String(p.provider) === 'anthropic' },
      { id: 'google',    label: 'Google',      match: p => p.name === 'gemini' },
      { id: 'xai',       label: 'xAI',         match: p => p.name === 'xai' },
      { id: 'meta',      label: 'Meta Llama',  match: p => /^(groq|together|deepinfra|fireworks|cerebras)$/.test(p.name) },
      { id: 'mistral',   label: 'Mistral',     match: p => p.name === 'mistral' },
      { id: 'local',     label: 'On this PC',  match: p => p.name === 'local' },
    ];

    function modelFamilyOf(p) {
      const hit = MODEL_FAMILIES.find(f => { try { return f.match(p); } catch (e) { return false; } });
      return hit || { id: 'other', label: 'Other providers' };
    }

    // `claude_plan` (from /api/models): the Anthropic profile with no key, on a
    // machine where the Claude CLI is installed. That profile is served by your
    // Claude plan's own sign-in, the same engine Build uses, so it is ready
    // without a key — it used to read "needs key" and could not be selected.
    function profileIsUsable(p) { return !!p.has_api_key || !!p.keyless_ok || !!p.claude_plan || p.provider === 'openai_codex' || p.name === 'local'; }

    // Whether a key box belongs under this profile: it has none stored and a key
    // is the only thing that would open it. Spelled out rather than as
    // `!profileIsUsable(p)`, which stopped meaning the same thing the moment a
    // keyless Claude plan became usable — the box would have vanished with it.
    function profileTakesKey(p) { return !p.has_api_key && !p.keyless_ok && p.provider !== 'openai_codex' && p.name !== 'local'; }

    // ---- The dropdown: a header (title, reload) and one list. ----

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text != null) node.textContent = text;
      return node;
    }

    // The connector's failure text, or '' when the last check was fine. It is the
    // reload icon's tooltip only; the panel itself carries no status line.
    function catalogFailure() {
      const text = checkedLabel();
      return /^(Not checked yet|Checked )/.test(text) ? '' : text;
    }

    function paintMenuHead() {
      const reload = document.getElementById('tc-model-reload');
      if (!reload) return;
      reload.classList.toggle('is-spinning', !!deps.state.catalogChecking);
      reload.disabled = !!deps.state.catalogChecking;
      const problem = catalogFailure();
      if (problem) reload.setAttribute('data-problem', '1'); else reload.removeAttribute('data-problem');
      reload.title = problem ? `Check for new models - ${problem}` : 'Check for new models';
    }

    function bindMenuHead() {
      const menu = document.getElementById('tc-model-menu');
      if (!menu || menu.dataset.bound) return;
      menu.dataset.bound = '1';
      const reload = document.getElementById('tc-model-reload');
      if (reload) reload.addEventListener('click', ev => { ev.stopPropagation(); checkForNewModels(); });
    }

    function checkRow(label, current, disabled, note, title) {
      const b = el('button', 'tc-mm-row' + (current ? ' is-current' : ''));
      b.type = 'button'; b.disabled = !!disabled;
      if (title) b.title = title;
      b.appendChild(el('span', 'tc-mm-name', label));
      if (note) b.appendChild(el('span', 'tc-mm-note', note));
      b.appendChild(el('span', 'tc-mm-check', current ? '✓' : ''));
      return b;
    }

    function renderModelRows(wrap) {
      // Only what can run is listed, flat, in the declared provider order so the
      // list does not reshuffle when a key is added. Providers still waiting for a
      // key sit behind the one "Connect a provider" row at the foot.
      const buildOnly = deps.state.surfaceMode === 'code';
      let hiddenForBuild = 0;
      const byFamily = new Map();
      const keyless = [];
      deps.profilesData.forEach(p => {
        const fam = modelFamilyOf(p);
        if (!byFamily.has(fam.id)) byFamily.set(fam.id, []);
        if (profileTakesKey(p)) keyless.push({ p, label: fam.label });
        profileModelOptions(p).forEach(m => {
          if (buildOnly && !deps.buildCanRunModel(p, m)) { hiddenForBuild += 1; return; }
          // A model this connection cannot run stays listed, greyed and saying so, rather than vanishing.
          if (profileIsUsable(p)) byFamily.get(fam.id).push({ p, m });
        });
        // A saved model the connection stopped offering stays visible, marked,
        // instead of the menu quietly switching you to something else.
        if (p.name === deps.state.profile && deps.state.modelId && Array.isArray(p.models)
            && !p.models.some(m => String(m.id) === String(deps.state.modelId))) {
          byFamily.get(fam.id).push({ p, gone: true, m: { id: deps.state.modelId, display_name: deps.state.modelLabel || deps.state.modelId } });
        }
      });
      [...MODEL_FAMILIES, { id: 'other' }].forEach(f => (byFamily.get(f.id) || []).forEach(({ p, m, gone }) => {
        const sel = p.name === deps.state.profile && String(m.id || '') === String(deps.state.modelId || '');
        const name = String(m.display_name || m.id || p.name).split('/').pop();
        const off = gone || m.available === false;
        const note = gone ? 'no longer offered'
          : m.available === false ? 'unavailable on this connection'
          : (m.retires_at ? retirementNote(m) : '');
        const row = checkRow(name, sel, off, note, m.unavailable_reason ? String(m.unavailable_reason) : `${p.claude_plan ? 'Your Claude plan' : p.name}`);
        if (!off) row.addEventListener('click', () => { setProfile(p, m); closeModelMenu(); });
        wrap.appendChild(row);
      }));
      if (buildOnly && hiddenForBuild) wrap.appendChild(el('div', 'tc-mm-hint', deps.hiddenForBuildNote(hiddenForBuild)));
      if (!keyless.length) return;
      // Without this the providers that need a key are a dead end: the only code
      // that can POST one is here.
      const open = !!deps.state.modelKeysOpen;
      const toggle = checkRow('Connect a provider…', false, false, '', 'Add an API key');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.addEventListener('click', () => { deps.state.modelKeysOpen = !open; renderModelMenu(); });
      wrap.appendChild(toggle);
      if (open) keyless.forEach(({ p, label }) => {
        wrap.appendChild(el('div', 'tc-mm-hint', label));
        wrap.appendChild(deps.buildKeyRow(p));
      });
    }

    function renderModelMenu() {
      const wrap = document.getElementById('tc-model-options'); if (!wrap) return;
      bindMenuHead();
      wrap.innerHTML = '';
      renderModelRows(wrap);
      const more = checkRow('Advanced…', false, false, '', 'Choose a model for each kind of job');
      more.classList.add('tc-mm-advanced');
      more.addEventListener('click', () => { closeModelMenu(); if (deps.openAdvancedModels) deps.openAdvancedModels(); });
      wrap.appendChild(more);
      paintMenuHead();
      deps.refreshAccountLine();
    }
    return { profileModelOptions, hydrateProfileModels, persistModelSelection, setProfile, toggleModelMenu, closeModelMenu, modelFamilyOf, profileIsUsable, renderModelMenu, checkForNewModels };
  }
  window.ThomasChatModelPicker = { create };
})();
