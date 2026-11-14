/* Start the requested document without waiting for unrelated model/history work. */
(function (global) {
  'use strict';

  function tabRequest(search) {
    const query = new URLSearchParams(search || '');
    const mode = query.get('tab_mode');
    const child = ['chat', 'code', 'work'].includes(mode);
    return { child, mode: child ? mode : '', chat: child && mode === 'chat' ? String(query.get('tab_chat') || '') : '' };
  }

  async function loadModels(deps) {
    const state = deps.state;
    const profile = state.profile, modelId = state.modelId;
    const roleProfiles = state.roleProfiles, roleModelIds = state.roleModelIds;
    try {
      const response = await deps.fetch('/api/models');
      if (!response.ok) return false;
      const data = await response.json();
      deps.setProfiles(Array.isArray(data.profiles) ? data.profiles : []);
      const prefs = data.preferences || {};
      const bridge = global.ThomasChatModelSelection;
      if (!bridge || !bridge.loadRoles || !bridge.loadRoles(prefs)) {
        if (state.roleProfiles === roleProfiles) state.roleProfiles = Object.assign({}, prefs.role_profiles || {});
        if (state.roleModelIds === roleModelIds) state.roleModelIds = Object.assign({}, prefs.role_model_ids || {});
        state.rolePreferencesReady = true;
      }
      // Saved role choices are ready independently of the slower model catalog.
      await deps.hydrateProfileModels();
      const active = String(prefs.active_profile || data.default || '').trim().toLowerCase();
      // The same rule the model menu draws with (profileIsUsable in
      // chat_model_picker.js). `claude_plan` is the Anthropic profile served by
      // your Claude plan's own sign-in: it needs no key, so a boot that did not
      // know that picked something else on every reload -- switching you off
      // the plan you had chosen, without saying so.
      const usable = p => !!p && (!!p.has_api_key || !!p.keyless_ok || !!p.claude_plan
        || p.provider === 'openai_codex' || p.name === 'local');
      const profiles = deps.getProfiles();
      let pick = profiles.find(p => String(p.name || '').trim().toLowerCase() === active);
      if (!usable(pick)) pick = profiles.find(usable) || profiles[0];
      // A selection made while metadata was loading belongs to the person using
      // this document. A late default may populate the menu but cannot replace it.
      if (pick && state.profile === profile && state.modelId === modelId) {
        const savedId = String(prefs.model_id || '').trim();
        const sameProfile = String(pick.name || '').trim().toLowerCase() === active;
        const saved = sameProfile && Array.isArray(pick.models)
          ? pick.models.find(model => String(model.id || '') === savedId && model.available !== false) : undefined;
        if (sameProfile && savedId && !saved) {
          // The connection stopped offering the saved model. setProfile(pick,
          // undefined) would silently substitute its default; keepId keeps the
          // saved id instead so the menu shows it as "no longer offered"
          // (renderModelMenu in chat_model_picker.js) rather than switching the
          // model on load -- and still runs setProfile's own effort
          // reconciliation and ThomasChatModelSelection.changed notification,
          // which a direct state assignment here skipped.
          deps.setProfile(pick, undefined, { persist: false, keepId: savedId });
        } else {
          deps.setProfile(pick, saved, { persist: false });
        }
      }
      deps.renderModelMenu();
      return true;
    } catch (error) {
      console.warn('Unable to load model choices.', error);
      return false;
    }
  }

  function start(deps) {
    const requested = tabRequest(deps.search);
    const mode = requested.mode || deps.getMode() || 'chat';
    const isCurrent = deps.captureConversation();
    const untouched = () => {
      const state = deps.state;
      return isCurrent() && (deps.getMode() || 'chat') === mode && !state.messages.length
        && !state.sessionId && !state.streaming && !state.input && !deps.getInput()
        && !(state.docs || []).length && !(state.images || []).length;
    };
    // Start these before awaiting either: a slow provider's model catalog must
    // not delay saved Chat history, or any part of Build and Work activation.
    const models = loadModels(deps);
    const chat = (async () => {
      if (mode !== 'chat') return;
      await deps.refreshChats();
      if (!untouched()) return;
      let lastChat = '', lastSession = '';
      if (requested.child) {
        lastChat = requested.chat;
      } else {
        try {
          lastChat = deps.storage.getItem('thomas_last_chat') || '';
          lastSession = deps.storage.getItem('thomas_last_session') || '';
        } catch (error) { console.warn('Unable to read saved Chat selection.', error); }
      }
      const rows = deps.getChats();
      // A fresh send updates its session before the history row has an ID.
      const row = rows.find(c => lastSession && c.sessionId === lastSession)
        || rows.find(c => lastChat && c.id === lastChat);
      if (row) { deps.selectChat(row.id); return; }
      // Media generation can persist a brand-new session before the recent-chat
      // summary has indexed it. Restore the canonical session directly instead
      // of allocating a blank replacement and overwriting the remembered ID.
      if (!requested.child && lastSession && deps.restoreSession) {
        const restored = await deps.restoreSession(lastSession);
        if (restored) return;
      }
      // Explicit child Chat with no matching tab_chat starts its own session.
      // It never falls back to another tab's globally remembered selection.
      await deps.ensureSession();
    })().catch(error => { console.warn('Unable to initialize Chat history.', error); });
    return { models, chat, ready: Promise.all([models, chat]) };
  }

  function notifyReady() {
    const origin = global.location && global.location.origin;
    if (!global.parent || global.parent === global || !origin || origin === 'null') return false;
    global.parent.postMessage({ type: 'thomas:surface-ready' }, origin);
    return true;
  }

  global.ThomasChatBoot = { start, loadModels, tabRequest, notifyReady };
})(window);
