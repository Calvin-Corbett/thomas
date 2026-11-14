/* The browser bar owns the model choice shared by its live chat documents. */
(function () {
  'use strict';
  let host = null;
  let blockedInput = null;

  function current() {
    return host ? host.getCurrent() : { profile: '', modelId: '' };
  }

  // Only confirmed preference writes are broadcast. Keep per-role updates so
  // an older boot response cannot replace a choice saved while it was loading.
  const roleUpdates = new Map();
  let roleOwner = null;
  const roleEvent = 'thomas:role-model-saved';

  function applyRoleUpdate(event) {
    const change = event.detail || {};
    if (!host || !host.state || typeof change.role !== 'string'
        || typeof change.profile !== 'string' || typeof change.modelId !== 'string') return;
    roleUpdates.set(change.role, change);
    const profiles = { ...host.state.roleProfiles }, models = { ...host.state.roleModelIds };
    if (change.profile) { profiles[change.role] = change.profile; models[change.role] = change.modelId; }
    else { delete profiles[change.role]; delete models[change.role]; }
    host.state.roleProfiles = profiles;
    host.state.roleModelIds = models;
  }

  function roleContext() {
    try {
      if (window.parent !== window) {
        const parentSelection = window.parent.ThomasModelSelection;
        const parentRoles = parentSelection && parentSelection.roleContext && parentSelection.roleContext();
        if (parentRoles && parentRoles.roleProfiles) return parentRoles;
      }
    } catch (_) { /* Cross-origin embeds keep their own saved preferences. */ }
    const state = host && host.state;
    if (!state || !state.rolePreferencesReady) return {};
    return { roleProfiles: { ...state.roleProfiles }, roleModelIds: { ...state.roleModelIds } };
  }

  function loadRoles(preferences) {
    if (!host || !host.state) return false;
    host.state.roleProfiles = { ...(preferences.role_profiles || {}) };
    host.state.roleModelIds = { ...(preferences.role_model_ids || {}) };
    for (const change of roleUpdates.values()) applyRoleUpdate({ detail: change });
    host.state.rolePreferencesReady = true;
    // A late child boot may have fetched before a save in the browser bar.
    Object.assign(host.state, roleContext());
    return true;
  }

  function roleSaved(role, profile, modelId) {
    if (!roleOwner) return;
    roleOwner.dispatchEvent(new roleOwner.CustomEvent(roleEvent, { detail: { role, profile, modelId } }));
  }

  function connectRoles() {
    if (!host.state || !window.addEventListener) return;
    roleOwner = window;
    try {
      if (window.parent !== window && window.parent.ThomasModelSelection) roleOwner = window.parent;
    } catch (_) { /* Standalone cross-origin embeds own their role state. */ }
    roleOwner.addEventListener(roleEvent, applyRoleUpdate);
    window.addEventListener('pagehide', () => roleOwner.removeEventListener(roleEvent, applyRoleUpdate), { once: true });
  }

  function available(profileName, modelId) {
    const profile = host && host.getProfiles().find(row => row.name === profileName);
    return profile && host.profileModelOptions(profile)
      .find(row => String(row.id || '') === String(modelId || '') && row.available !== false);
  }

  function select(profileName, modelId) {
    if (!host) return false;
    const profile = host.getProfiles().find(row => row.name === profileName);
    const model = available(profileName, modelId);
    if (!model) return false;
    host.setProfile(profile, model, { persist: false });
    host.renderModelMenu();
    const selected = current();
    return selected.profile === profileName && String(selected.modelId) === String(modelId);
  }

  function changed(persisted) {
    let selected = current();
    // A document can finish booting after the parent broadcast. Its stale
    // preferences response must not undo the browser bar's current choice.
    if (!persisted && window.parent !== window) {
      try {
        const parentSelection = window.parent.ThomasModelSelection;
        const desired = parentSelection && parentSelection.current();
        if (desired && (desired.profile !== selected.profile || desired.modelId !== selected.modelId)) {
          select(desired.profile, desired.modelId);
          selected = current();
        }
      } catch (_) { /* Standalone cross-origin embeds keep their own choice. */ }
    }
    const wrap = document.querySelector('[data-model-switch]');
    if (wrap) {
      wrap.dataset.modelProfile = selected.profile;
      wrap.dataset.modelId = selected.modelId;
    }
    if (persisted) window.dispatchEvent(new CustomEvent('thomas:model-selected', { detail: selected }));
    if (blockedInput) { blockedInput.setCustomValidity(''); blockedInput = null; }
    if (host && host.selectionChanged) host.selectionChanged();
  }

  function ensureCurrent(input) {
    let desired = current();
    try {
      if (window.parent !== window && window.parent.ThomasModelSelection) {
        desired = window.parent.ThomasModelSelection.current();
      }
    } catch (_) { /* A standalone cross-origin embed owns its selection. */ }
    const selected = current();
    const matches = desired.profile === selected.profile && desired.modelId === selected.modelId;
    if (desired.profile && desired.modelId && available(desired.profile, desired.modelId)
        && (matches || select(desired.profile, desired.modelId))) {
      if (blockedInput) { blockedInput.setCustomValidity(''); blockedInput = null; }
      return true;
    }
    const control = input || document.getElementById('tc-input');
    if (control && control.setCustomValidity) {
      control.setCustomValidity('The selected model is not ready in this tab. Refresh this tab or choose a model again, then resend.');
      blockedInput = control;
      if (control.reportValidity) control.reportValidity();
    }
    return false;
  }

  window.ThomasChatModelSelection = {
    connect(adapter) {
      host = adapter;
      window.ThomasModelSelection = { current, select, roleContext };
      connectRoles();
    },
    changed,
    ensureCurrent,
    roleContext,
    loadRoles,
    roleSaved,
  };
})();
