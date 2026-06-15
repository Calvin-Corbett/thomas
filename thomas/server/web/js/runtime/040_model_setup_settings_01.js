/* ── Theme + font-size application ───────────────────────────── */

/* Default (Nebula) icon classes for composer buttons */
const _defaultIcons = {
    sendBtn:   { from: 'ph-arrow-up',    to: 'ph-arrow-up' },
    attachBtn: { from: 'ph-plus',         to: 'ph-plus' },
    micBtn:    { from: 'ph-microphone',   to: 'ph-microphone' }
};
/* Light-theme overrides — journal / stationery feel */
const _lightIcons = {
    sendBtn:   { to: 'ph-pen-nib' },
    attachBtn: { to: 'ph-paperclip' },
    micBtn:    { to: 'ph-waveform' }
};

/* All possible icon classes that could be on these buttons */
const _allIconClasses = [
    'ph-arrow-up','ph-pen-nib','ph-feather',
    'ph-plus','ph-paperclip',
    'ph-microphone','ph-waveform','ph-speaker-high'
];
const THOMAS_THEME_STORAGE_KEY = 'thomas_theme';

function normalizeThemePreference(theme) {
    const normalized = safeString(theme).toLowerCase();
    if (normalized === 'system') return 'auto';
    if (normalized === 'light' || normalized === 'dark' || normalized === 'auto') return normalized;
    return 'auto';
}

function storeThemePreference(theme) {
    try {
        window.localStorage?.setItem(THOMAS_THEME_STORAGE_KEY, normalizeThemePreference(theme));
    } catch (_) {}
}

function syncSpaceThemeState(theme) {
    const normalized = normalizeThemePreference(theme);
    const spaceApi = window.__teSpace;
    if (normalized === 'light' || normalized === 'dark') {
        if (typeof spaceApi?.remove === 'function') {
            spaceApi.remove();
        } else {
            document.body.classList.remove('te-space-active');
        }
        if (window.spaceCanvas) window.spaceCanvas.style.display = 'none';
        return;
    }
    if (typeof spaceApi?.inject === 'function') {
        spaceApi.inject();
    } else {
        document.body.classList.add('te-space-active');
    }
    if (window.spaceCanvas) window.spaceCanvas.style.display = '';
}

function _swapComposerIcons(iconMap) {
    Object.entries(iconMap).forEach(([btnId, cls]) => {
        const btn = document.getElementById(btnId);
        if (!btn) return;
        const i = btn.querySelector('i.ph');
        if (!i) return;
        /* Remove any previous swap classes, then add the target */
        _allIconClasses.forEach(c => i.classList.remove(c));
        i.classList.add(cls.to);
    });
}

function applyTheme(theme) {
    const normalizedTheme = normalizeThemePreference(theme);
    const body = document.body;
    body.classList.remove('te-theme-light', 'te-theme-dark');
    body.removeAttribute('data-theme');
    storeThemePreference(normalizedTheme);
    if (normalizedTheme === 'light') {
        body.classList.add('te-theme-light');
        body.setAttribute('data-theme', 'light');
        syncSpaceThemeState(normalizedTheme);
        _swapComposerIcons(_lightIcons);
        _injectLightThemeIntoIframes();
    } else if (normalizedTheme === 'dark') {
        body.classList.add('te-theme-dark');
        body.setAttribute('data-theme', 'dark');
        syncSpaceThemeState(normalizedTheme);
        _swapComposerIcons(_defaultIcons);
        _removeLightThemeFromIframes();
    } else {
        // 'auto' = Nebula Core — restore space
        syncSpaceThemeState(normalizedTheme);
        _swapComposerIcons(_defaultIcons);
        _removeLightThemeFromIframes();
    }
}

/* ── Iframe theme injection ─────────────────────────────────────
   Plugin workspaces (Life Manager, My Stuff, etc.) render inside
   same-origin iframes. Our main-document CSS can't reach them,
   so we inject a <style> block that adopts the journal palette. */
const _LIGHT_IFRAME_CSS = `
/* Injected by Thomas — light journal theme for plugin iframes */
:root, body, html {
    background: #ebe5d9 !important;
    color: #2c2420 !important;
    font-family: 'Georgia','Palatino Linotype','Palatino','Book Antiqua',serif !important;
}
*:not(.ph):not([class*="ph-"]) {
    font-family: 'Georgia','Palatino Linotype','Palatino','Book Antiqua',serif !important;
}
/* Kill ALL dark rgba backgrounds */
[style*="gradient"], [style*="rgba(8"], [style*="rgba(1"], [style*="rgba(3"],
[style*="rgba(6"], [style*="rgba(5"], [style*="rgb(5,"], [style*="rgb(8,"],
[style*="rgb(10,"], [style*="rgb(1"], [style*="rgb(2"], [style*="rgb(3"] {
    background: #ebe5d9 !important;
    background-image: none !important;
}
/* Broad overrides for common dark patterns */
section, div, main, article, header, footer, aside, nav {
    background-color: transparent !important;
    background-image: none !important;
}
/* Cards, tiles, panels */
[class*="-card"], [class*="-tile"], [class*="-panel"],
[class*="-section"], [class*="-block"], [class*="-widget"],
[class*="-hero"], [class*="-header"], [class*="-toolbar"],
[class*="-board"], [class*="-frame"], [class*="-view"],
[class*="stuff-"], [class*="lm-"], [class*="plugin-"] {
    background: #f4efe6 !important;
    background-image: none !important;
    color: #2c2420 !important;
    border-color: #c8bfab !important;
}
/* Body and wrapper backgrounds */
body, .app, .wrapper, .container, .content, .main,
[class*="-wrap"], [class*="-container"], [class*="-content"],
[class*="-page"], [class*="-screen"], [class*="-workspace"],
[class*="-dashboard"], [class*="-statusbar"] {
    background: #ebe5d9 !important;
    background-image: none !important;
    color: #2c2420 !important;
}
/* Text: always dark */
h1, h2, h3, h4, h5, h6, p, span, a, label, strong, em, li, td, th, dt, dd {
    color: #2c2420 !important;
    text-shadow: none !important;
}
/* Muted text */
small, .muted, .meta, .subtitle, [class*="-meta"], [class*="-sub"],
[class*="-muted"], [class*="-hint"], [class*="-note"] {
    color: #8a7a65 !important;
}
/* Buttons */
button, .btn, [class*="-btn"] {
    background: #e0d8ca !important;
    background-image: none !important;
    color: #3d3028 !important;
    border: 1px solid #c8bca8 !important;
    border-radius: 2px !important;
    text-shadow: none !important;
}
button:hover, .btn:hover { background: #d6cebf !important; }
/* Primary button — accent */
[class*="primary"], [class*="accent"] {
    background: #8a7250 !important;
    background-image: none !important;
    color: #f5f0e8 !important;
    border-color: #7a6240 !important;
}
/* Inputs */
input, select, textarea {
    background: #f0ebe2 !important;
    color: #2c2420 !important;
    border: 1px solid #c8bca8 !important;
    border-radius: 1px !important;
}
input::placeholder, textarea::placeholder { color: #a0907a !important; font-style: italic !important; }
/* Tables */
table, th, td { background: #f4efe6 !important; color: #2c2420 !important; border-color: #c8bfab !important; }
th { background: #e6dfd2 !important; font-weight: 700 !important; }
/* Badges */
[class*="-badge"], [class*="-pill"], [class*="-tag"], [class*="-status"] {
    background: #e0d8ca !important;
    color: #3d3028 !important;
    border: 1px solid #c8bca8 !important;
    text-shadow: none !important;
}
/* Scrollbar */
::-webkit-scrollbar-thumb { background: #c0ad90 !important; }
::-webkit-scrollbar-track { background: #e2dbd0 !important; }
/* Empty states */
[class*="-empty"], [class*="empty-"] {
    background: #f4efe6 !important;
    color: #8a7a65 !important;
}
`.trim();

function _injectLightThemeIntoIframes() {
    try {
        document.querySelectorAll('iframe').forEach(frame => {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc) return;
                /* Remove old injection if any */
                const old = doc.getElementById('thomas-light-theme-inject');
                if (old) old.remove();
                const style = doc.createElement('style');
                style.id = 'thomas-light-theme-inject';
                style.textContent = _LIGHT_IFRAME_CSS;
                (doc.head || doc.documentElement).appendChild(style);
            } catch(_) { /* cross-origin — skip */ }
        });
    } catch(_) {}
    /* Also re-run after a short delay for lazy-loaded iframes */
    clearTimeout(window._lightIframeTimer);
    window._lightIframeTimer = setTimeout(() => _injectLightThemeIntoIframes_once(), 1500);
}

function _injectLightThemeIntoIframes_once() {
    if (!document.body.classList.contains('te-theme-light')) return;
    try {
        document.querySelectorAll('iframe').forEach(frame => {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc || doc.getElementById('thomas-light-theme-inject')) return;
                const style = doc.createElement('style');
                style.id = 'thomas-light-theme-inject';
                style.textContent = _LIGHT_IFRAME_CSS;
                (doc.head || doc.documentElement).appendChild(style);
            } catch(_) {}
        });
    } catch(_) {}
}

/* Watch for new iframes being added to the DOM and inject light theme */
(function _watchForNewIframes() {
    const obs = new MutationObserver(muts => {
        if (!document.body.classList.contains('te-theme-light')) return;
        for (const m of muts) {
            for (const n of m.addedNodes) {
                if (n.tagName === 'IFRAME') {
                    n.addEventListener('load', () => _injectLightThemeIntoIframes_once());
                } else if (n.querySelectorAll) {
                    n.querySelectorAll('iframe').forEach(f => {
                        f.addEventListener('load', () => _injectLightThemeIntoIframes_once());
                    });
                }
            }
        }
    });
    obs.observe(document.body, { childList: true, subtree: true });
})();

function _removeLightThemeFromIframes() {
    clearTimeout(window._lightIframeTimer);
    try {
        document.querySelectorAll('iframe').forEach(frame => {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc) return;
                const el = doc.getElementById('thomas-light-theme-inject');
                if (el) el.remove();
            } catch(_) {}
        });
    } catch(_) {}
}

function applyFontSize(px) {
    document.documentElement.style.setProperty('--user-font-size', px + 'px');
    document.body.style.fontSize = px + 'px';
}

const MODEL_SPECIALTY_ROLES = [
    { id: 'research', label: 'Research' },
    { id: 'coding', label: 'Coding' },
    { id: 'planning', label: 'Planning' },
    { id: 'memory', label: 'Memory' },
    { id: 'tools', label: 'Tool use' },
    { id: 'creative', label: 'Creative' },
];
const COMPOSER_MODE_MODEL_ROLES = {
    research: 'research',
    create_image: 'creative',
    create_video: 'creative',
    create_song: 'creative',
};
let setupSpecialtyDraftProfiles = {};
let setupSpecialtyDraftModelIds = {};
let setupSpecialtySyncing = false;

function normalizeModelSpecialtyRole(roleRaw = '') {
    return safeString(roleRaw).toLowerCase().replace(/[\s-]+/g, '_');
}

function modelSpecialtyLabel(roleRaw = '') {
    const role = normalizeModelSpecialtyRole(roleRaw);
    const found = MODEL_SPECIALTY_ROLES.find((entry) => entry.id === role);
    return found?.label || role || 'Specialty';
}

function currentModelPreferenceMaps() {
    const modelPrefs = currentPreferences?.advanced?.model || {};
    return {
        roleProfiles: { ...(modelPrefs.role_profiles || {}) },
        roleModelIds: { ...(modelPrefs.role_model_ids || {}) },
    };
}

function resetSpecialtyDraftsFromPreferences() {
    const { roleProfiles, roleModelIds } = currentModelPreferenceMaps();
    setupSpecialtyDraftProfiles = { ...roleProfiles };
    setupSpecialtyDraftModelIds = { ...roleModelIds };
}

function buildSpecialtyPreferencePatch() {
    const { roleProfiles, roleModelIds } = currentModelPreferenceMaps();
    const nextProfiles = { ...setupSpecialtyDraftProfiles };
    const nextModelIds = { ...setupSpecialtyDraftModelIds };
    for (const role of Object.keys(roleProfiles)) {
        if (!safeString(nextProfiles[role])) nextProfiles[role] = null;
    }
    for (const role of Object.keys(roleModelIds)) {
        if (!safeString(nextModelIds[role])) nextModelIds[role] = null;
    }
    return {
        role_profiles: nextProfiles,
        role_model_ids: nextModelIds,
    };
}

function resolveComposerModelRole() {
    const modeId = normalizeModelSpecialtyRole(composerModeSelection?.id);
    return COMPOSER_MODE_MODEL_ROLES[modeId] || '';
}

function resolveSpecialtyModelSelection(roleRaw = '', fallbackProfileRaw = '') {
    const role = normalizeModelSpecialtyRole(roleRaw);
    const modelPrefs = currentPreferences?.advanced?.model || {};
    const roleProfiles = modelPrefs.role_profiles || {};
    const roleModelIds = modelPrefs.role_model_ids || {};
    const fallbackProfile = safeString(fallbackProfileRaw)
        || safeString(modelSelector?.value)
        || safeString(setupProviderSelector?.value)
        || safeString(modelPrefs.active_profile);
    const profile = safeString(roleProfiles[role]) || fallbackProfile;
    const modelId = safeString(roleModelIds[role]) || resolveActiveModelIdForProfile(profile);
    return { role, profile, modelId };
}

function populateSelectOptions(selectEl, modelIds, preferredValue = '') {
    if (!selectEl) return;
    const preferred = safeString(preferredValue);
    selectEl.innerHTML = '';
    const seen = new Set();
    for (const id of modelIds) {
        const clean = safeString(id);
        if (!clean || seen.has(clean)) continue;
        seen.add(clean);
        const opt = document.createElement('option');
        opt.value = clean;
        opt.textContent = clean;
        selectEl.appendChild(opt);
    }
    if (preferred && !seen.has(preferred)) {
        const opt = document.createElement('option');
        opt.value = preferred;
        opt.textContent = preferred;
        selectEl.insertBefore(opt, selectEl.firstChild);
        seen.add(preferred);
    }
    if (preferred && seen.has(preferred)) {
        selectEl.value = preferred;
    } else if (selectEl.options.length > 0) {
        selectEl.value = selectEl.options[0].value;
    }
}

function renderSpecialtyProviderOptions() {
    if (!setupSpecialtyProviderSelector) return;
    const currentValue = safeString(setupSpecialtyProviderSelector.value);
    setupSpecialtyProviderSelector.innerHTML = '';
    const inherit = document.createElement('option');
    inherit.value = '';
    inherit.textContent = 'Inherit base model';
    setupSpecialtyProviderSelector.appendChild(inherit);
    for (const profile of availableModelProfiles || []) {
        const name = safeString(profile?.name);
        if (!name) continue;
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        setupSpecialtyProviderSelector.appendChild(opt);
    }
    if (currentValue && Array.from(setupSpecialtyProviderSelector.options).some((opt) => opt.value === currentValue)) {
        setupSpecialtyProviderSelector.value = currentValue;
    }
}

function syncSpecialtyModelControls() {
    if (!setupSpecialtyRoleSelector || !setupSpecialtyProviderSelector || !setupSpecialtyModelSelector) return;
    setupSpecialtySyncing = true;
    try {
        const role = normalizeModelSpecialtyRole(setupSpecialtyRoleSelector.value) || 'research';
        renderSpecialtyProviderOptions();
        const explicitProfile = safeString(setupSpecialtyDraftProfiles[role]);
        setupSpecialtyProviderSelector.value = explicitProfile;
        const baseProfile = safeString(setupProviderSelector?.value)
            || safeString(modelSelector?.value)
            || safeString(currentPreferences?.advanced?.model?.active_profile);
        const effectiveProfile = explicitProfile || baseProfile;
        const profileInfo = (availableModelProfiles || []).find((entry) => safeString(entry?.name) === effectiveProfile) || {};
        const defaultModel = defaultModelIdForProfile(effectiveProfile);
        const preferredModel = explicitProfile
            ? (safeString(setupSpecialtyDraftModelIds[role]) || resolveStoredModelSelection(effectiveProfile, { allowLocalBackup: true }))
            : (resolveActiveModelIdForProfile(baseProfile) || defaultModel);
        const suggestions = KNOWN_MODEL_SUGGESTIONS[safeString(profileInfo?.provider)] || [];
        populateSelectOptions(setupSpecialtyModelSelector, [preferredModel, defaultModel, ...suggestions], preferredModel);
        setupSpecialtyModelSelector.disabled = !explicitProfile;
        if (setupSpecialtyStatus) {
            setupSpecialtyStatus.textContent = explicitProfile
                ? `${modelSpecialtyLabel(role)} uses ${explicitProfile} / ${safeString(setupSpecialtyModelSelector.value) || preferredModel}.`
                : `${modelSpecialtyLabel(role)} inherits the base model.`;
        }
    } finally {
        setupSpecialtySyncing = false;
    }
}

function updateSpecialtyDraftFromControls() {
    if (setupSpecialtySyncing || !setupSpecialtyRoleSelector) return;
    const role = normalizeModelSpecialtyRole(setupSpecialtyRoleSelector.value) || 'research';
    const profile = safeString(setupSpecialtyProviderSelector?.value);
    if (!profile) {
        delete setupSpecialtyDraftProfiles[role];
        delete setupSpecialtyDraftModelIds[role];
        syncSpecialtyModelControls();
        return;
    }
    setupSpecialtyDraftProfiles[role] = profile;
    const modelId = safeString(setupSpecialtyModelSelector?.value)
        || resolveStoredModelSelection(profile, { allowLocalBackup: true });
    if (modelId) setupSpecialtyDraftModelIds[role] = modelId;
    syncSpecialtyModelControls();
}

function initModelSetup() {
    const closeModelSetupModal = () => {
        closeSetupProviderMenu();
        modelSetupModal.classList.remove('active');
        modelSetupModal.style.display = 'none';
    };

    const openModelSetupModal = () => {
        modelSetupModal.classList.add('active');
        modelSetupModal.style.display = 'flex';

        // Seed from current live selection first, then fall back to persisted preferences.
        const savedProfile = safeString(modelSelector.value)
            || safeString(currentPreferences?.advanced?.model?.active_profile);
        setupProviderSelector.value = savedProfile;
        renderSetupProviderPickerMenu(savedProfile, { preserveExpanded: false });
        resetSpecialtyDraftsFromPreferences();

        // Restore segmented controls from preferences
        const savedAutonomy = safeString(currentPreferences?.autonomy?.default_level).replace('L', '');
        if (savedAutonomy) {
            activeAutonomyLevel = parseInt(savedAutonomy, 10) || 1;
            setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
        }
        const prefsEconomy = safeString(currentPreferences?.advanced?.runtime?.default_token_economy);
        const econRevMap = { cheap: 'cheap', optimal: 'balanced', max: 'max' };
        if (prefsEconomy && econRevMap[prefsEconomy]) {
            activeTokenEconomy = econRevMap[prefsEconomy];
            setSegmentedControlSelection('setupEconomyGroup', activeTokenEconomy);
        }

        if (typeof _syncProviderUI === 'function') _syncProviderUI(savedProfile);
        syncSpecialtyModelControls();
        if (setupProviderPickerBtn) {
            setupProviderPickerBtn.focus();
        } else if (setupProviderSelector) {
            setupProviderSelector.focus();
        }
    };

    // Open Trigger
    modelSetupBtn.addEventListener('click', () => {
        openModelSetupModal();
    });
    modelSetupBtn.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            openModelSetupModal();
        }
    });

    // Close Triggers
    closeModelSetupBtn.addEventListener('click', () => {
        closeModelSetupModal();
    });

    document.getElementById('modelSetupBackdrop').addEventListener('click', () => {
        closeModelSetupModal();
    });

    // Personality Dropdown Logic (Show/Hide Custom Textarea)
    setupPersonalitySelector.addEventListener('change', (e) => {
        if (e.target.value === 'custom') {
            customPersonalityGroup.classList.remove('hidden');
        } else {
            customPersonalityGroup.classList.add('hidden');
        }
    });

    // Segmented Controls (Autonomy & Economy)
    const bindSegmentedControl = (groupId, updateCallback) => {
        const group = document.getElementById(groupId);
        group.querySelectorAll('.segment').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // Clear active
                group.querySelectorAll('.segment').forEach(b => b.classList.remove('active'));
                // Set active
                const target = e.currentTarget;
                target.classList.add('active');
                updateCallback(target.dataset.level);
            });
        });
    };

    bindSegmentedControl('setupAutonomyGroup', val => {
        autonomyLevelManuallySet = true;
        activeAutonomyLevel = parseInt(val, 10);
        renderChatComposerSubbar();
    });
    bindSegmentedControl('setupEconomyGroup', val => {
        activeTokenEconomy = val;
        renderChatComposerSubbar();
    });
    bindSegmentedControl('setupReasoningEffortGroup', val => {
        activeReasoningEffort = normalizeReasoningEffort(val);
        renderChatComposerSubbar();
    });

    if (setupProviderPickerBtn) {
        setupProviderPickerBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (setupProviderMenu && !setupProviderMenu.classList.contains('hidden')) {
                closeSetupProviderMenu({ preserveExpanded: true });
            } else {
                openSetupProviderMenu();
            }
        });
        setupProviderPickerBtn.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                openSetupProviderMenu();
            }
        });
    }

    if (setupProviderMenu) {
        setupProviderMenu.addEventListener('click', async (event) => {
            event.stopPropagation();
            const moreButton = event.target.closest('.setup-provider-more');
            if (moreButton) {
                event.preventDefault();
                setupProviderMenuShowMore = true;
                renderSetupProviderPickerMenu(safeString(setupProviderSelector?.value), { preserveExpanded: true });
                if (setupProviderPickerBtn) setupProviderPickerBtn.setAttribute('aria-expanded', 'true');
                return;
            }
            const optionButton = event.target.closest('.setup-provider-option');
            if (!optionButton) return;
            event.preventDefault();
            const nextProfile = safeString(optionButton.dataset.profile);
            if (!nextProfile || !setupProviderSelector) return;
            if (safeString(optionButton.dataset.state) === 'inactive') {
                await handoffInactiveProviderToEasySetup(nextProfile);
                return;
            }
            setupProviderSelector.value = nextProfile;
            renderSetupProviderPickerMenu(nextProfile, { preserveExpanded: true });
            closeSetupProviderMenu();
            setupProviderSelector.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }

    document.addEventListener('click', (event) => {
        if (!setupProviderPicker || !setupProviderMenu || setupProviderMenu.classList.contains('hidden')) return;
        if (setupProviderPicker.contains(event.target)) return;
        closeSetupProviderMenu();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSetupProviderMenu();
        }
    });

    // Provider change: sync model select and reasoning effort.
    const _syncProviderUI = (profileName) => {
        const p = availableModelProfiles.find(m => m.name === profileName);
        const allowLocalBackup = !safeString(currentPreferences?.advanced?.model?.active_profile);

        renderSetupProviderPickerMenu(profileName, { preserveExpanded: true });

        // --- Model <select> ---
        if (p && setupModelSelector) {
            const defaultModel = safeString(p.model).split('/').pop() || '';
            const preferredModel = resolveStoredModelSelection(profileName, { allowLocalBackup }) || defaultModel;
            _populateModelSelect([preferredModel, defaultModel, ...(KNOWN_MODEL_SUGGESTIONS[p.provider] || [])]);
            setupModelSelector.value = preferredModel;
            activeModelOverride = preferredModel;
            _discoverProfileModels(profileName, defaultModel);
        }

        // --- Reasoning effort ---
        syncSetupReasoningVisibility(profileName);
        syncSpecialtyModelControls();
        renderChatComposerSubbar();
    };

    // Populate model <select> with deduped options
    function _populateModelSelect(modelIds) {
        if (!setupModelSelector) return;
        const currentVal = setupModelSelector.value;
        setupModelSelector.innerHTML = '';
        const seen = new Set();
        for (const id of modelIds) {
            const clean = safeString(id);
            if (!clean || seen.has(clean)) continue;
            seen.add(clean);
            const opt = document.createElement('option');
            opt.value = clean;
            opt.textContent = clean;
            setupModelSelector.appendChild(opt);
        }
        if (currentVal && seen.has(currentVal)) setupModelSelector.value = currentVal;
    }

    // Async model discovery from server
    async function _discoverProfileModels(profileName, defaultModel) {
        try {
            const inFlightSelection = safeString(setupModelSelector?.value);
            const res = await fetch(`/api/models/${encodeURIComponent(profileName)}/ids`);
            if (!res.ok) return;
            const data = await res.json();
            const discovered = Array.isArray(data.models) ? data.models : [];
            const provider = (availableModelProfiles.find(m => m.name === profileName) || {}).provider || '';
            const staticFallbacks = KNOWN_MODEL_SUGGESTIONS[provider] || [];
            const merged = [defaultModel, ...discovered, ...staticFallbacks];
            _populateModelSelect(merged);

            // Preserve the in-flight user selection; otherwise prefer saved profile model.
            if (inFlightSelection && setupModelSelector.querySelector(`option[value="${CSS.escape(inFlightSelection)}"]`)) {
                setupModelSelector.value = inFlightSelection;
                activeModelOverride = inFlightSelection;
                return;
            }

            const savedModelId = safeString(currentPreferences?.advanced?.model?.model_id);
            const savedProfile = safeString(currentPreferences?.advanced?.model?.active_profile);
            if (
                savedModelId
                && savedProfile === profileName
                && setupModelSelector.querySelector(`option[value="${CSS.escape(savedModelId)}"]`)
            ) {
                setupModelSelector.value = savedModelId;
                activeModelOverride = savedModelId;
            }
        } catch (e) {
            console.warn('Model discovery failed for', profileName, e);
        }
    }

    setupProviderSelector.addEventListener('change', (e) => _syncProviderUI(safeString(e.target.value)));

    // Model selector change tracking
    if (setupModelSelector) {
        setupModelSelector.addEventListener('change', (e) => {
            activeModelOverride = safeString(e.target.value);
            syncSpecialtyModelControls();
        });
    }

    if (setupSpecialtyRoleSelector) {
        setupSpecialtyRoleSelector.addEventListener('change', () => syncSpecialtyModelControls());
    }
    if (setupSpecialtyProviderSelector) {
        setupSpecialtyProviderSelector.addEventListener('change', () => updateSpecialtyDraftFromControls());
    }
    if (setupSpecialtyModelSelector) {
        setupSpecialtyModelSelector.addEventListener('change', () => updateSpecialtyDraftFromControls());
    }
    if (setupSpecialtyClearBtn) {
        setupSpecialtyClearBtn.addEventListener('click', () => {
            if (!setupSpecialtyRoleSelector) return;
            const role = normalizeModelSpecialtyRole(setupSpecialtyRoleSelector.value) || 'research';
            delete setupSpecialtyDraftProfiles[role];
            delete setupSpecialtyDraftModelIds[role];
            syncSpecialtyModelControls();
        });
    }

    // Apply Button  persist ALL settings
    applyModelSetupBtn.addEventListener('click', async () => {
        // 1. Capture current UI state
        const selectedProfile = setupProviderSelector.value;
        const selectedModel = setupModelSelector ? safeString(setupModelSelector.value) : '';
        activeModelOverride = selectedModel;
        modelSelector.value = selectedProfile;

        // 2. Update header label + localStorage backup
        modelSetupCurrentLabel.textContent = _profileHeaderLabel(selectedProfile);
        try { window.localStorage.setItem('thomas_active_profile', selectedProfile); } catch (_) {}
        try { window.localStorage.setItem('thomas_active_model_id', selectedModel); } catch (_) {}

        // 3. Build preferences patch (map UI values to preferences schema)
        const economyMap = { cheap: 'cheap', balanced: 'optimal', max: 'max' };
        const specialtyPatch = buildSpecialtyPreferencePatch();
        const patch = {
            memory: { enabled_global: Boolean(setupMemoryToggle && setupMemoryToggle.checked) },
            autonomy: { default_level: 'L' + activeAutonomyLevel },
            advanced: {
                model: {
                    active_profile: selectedProfile,
                    model_id: selectedModel,
                    role_profiles: specialtyPatch.role_profiles,
                    role_model_ids: specialtyPatch.role_model_ids,
                    reasoning_effort: normalizeReasoningEffort(activeReasoningEffort) || 'medium',
                },
                runtime: {
                    default_token_economy: economyMap[activeTokenEconomy] || 'optimal',
                },
            },
        };

        // 4. PATCH to server
        try {
            const res = await fetch('/api/preferences', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
            });
            if (!res.ok) {
                const details = await res.text();
                throw new Error(details || `HTTP ${res.status}`);
            }
            currentPreferences = await res.json();
            updateSidebarIdentity();
            notifyUser('Model setup saved.', {
                tone: 'success',
                durationMs: 1800,
                debugKind: 'settings',
            });
            closeModelSetupModal();
        } catch (e) {
            console.error('Failed to persist model setup:', e);
            notifyUser(
                `Could not save model setup: ${safeString(e?.message) || 'unknown error'}`,
                {
                    tone: 'error',
                    durationMs: 3200,
                    debugKind: 'error',
                }
            );
        }
    });

    // Restart Server button
    if (restartServerBtn) {
        restartServerBtn.addEventListener('click', async () => {
            if (!confirm('Restart the Thomas server? Active requests will be interrupted.')) return;
            try {
                const restartReq = await fetchJsonSafe('/api/server/restart', { method: 'POST', timeoutMs: 5000 });
                if (!restartReq.ok) {
                    const reason = safeString(restartReq?.text) || `HTTP ${restartReq.status || 0}`;
                    throw new Error(reason || 'Restart request failed');
                }

                closeModelSetupModal();
                if (restartOverlay) restartOverlay.classList.remove('hidden');

                // Poll /api/health until server comes back (max 30s, poll every 500ms)
                const restartStatus = document.getElementById('restartStatus');
                for (let i = 0; i < 60; i++) {
                    if (restartStatus) restartStatus.textContent = `Waiting\u2026 ${Math.floor(i * 0.5)}s`;
                    await new Promise(r => setTimeout(r, 500));
                    const probe = await fetchJsonSafe('/api/health', { timeoutMs: 1500 });
                    if (probe.ok) {
                        if (restartStatus) restartStatus.textContent = 'Reconnecting\u2026';
                        if (restartOverlay) restartOverlay.classList.add('hidden');
                        await fetchModels();
                        // Re-import conversation into a fresh server session
                        if (chatHistory.length > 0) {
                            try {
                                const importPayload = {
                                    profile: (setupProviderSelector && setupProviderSelector.value) || 'local',
                                    conversation: chatHistory.map(m => ({
                                        role: safeString(m.role),
                                        content: safeString(m.content),
                                    })),
                                };
                                const importRes = await fetchJsonSafe('/api/session/import', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(importPayload),
                                    timeoutMs: 5000,
                                });
                                if (importRes.ok) {
                                    const imported = importRes.data && typeof importRes.data === 'object' ? importRes.data : {};
                                    if (safeString(imported.session_id)) {
                                        sessionId = safeString(imported.session_id);
                                    }
                                }
                            } catch (_e) { console.warn('Session re-import after restart failed:', _e); }
                        }
                        return;
                    }
                }

                if (restartOverlay) restartOverlay.classList.add('hidden');
                alert('Server did not come back within 30 seconds. Check manually.');
            } catch (e) {
                if (restartOverlay) restartOverlay.classList.add('hidden');
                const reason = safeString(e?.message) || 'Restart request failed.';
                alert(`Restart failed: ${reason}`);
                console.error('Restart request failed:', e);
            }
        });
    }
}

async function persistMemorySetting(isEnabled) {
    try {
        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                memory: { enabled_global: isEnabled }
            })
        });
        if (res.ok) {
            currentPreferences = await res.json();
            updateSidebarIdentity();
        }
    } catch (e) {
        console.error("Failed to save memory preference:", e);
    }
}

function applyWorkspaceVisibility(ws) {
    const map = {
        mission: 'navMissionBtn',
        app_builder: 'navUiEditorBtn',
        my_stuff: 'navMyStuffBtn',
        channels: 'navChannelsBtn',
        token_economy: 'navTokenEconomyBtn',
        marketplace: 'navMarketplaceBtn',
    };
    Object.entries(map).forEach(([key, btnId]) => {
        const btn = document.getElementById(btnId);
        if (btn) btn.style.display = (ws && ws[key] === false) ? 'none' : '';
    });
}

function openSettingsModal() {
    if (!settingsModal) return;
    setDebugDockOpen(false, { recordEvent: false });
    settingsModal.classList.remove('hidden');
    if (appRoot) appRoot.classList.add('settings-active');
    settingsReturnNavMode = normalizeNavMode(sidebarNavMode);
    if (settingsBtn) settingsBtn.classList.add('active');
    loadSettings();
}

function isSettingsScreenOpen() {
    return Boolean(settingsModal && !settingsModal.classList.contains('hidden'));
}

function ensureSettingsUiClosed({ restoreNav = false } = {}) {
    if (!settingsModal) return;
    if (isSettingsScreenOpen()) {
        closeSettingsModal({ restoreNav });
        return;
    }
    settingsModal.classList.add('hidden');
    if (appRoot) appRoot.classList.remove('settings-active');
    if (settingsBtn) settingsBtn.classList.remove('active');
}

function closeSettingsModal({ restoreNav = true } = {}) {
    if (!settingsModal) return;
    settingsModal.classList.add('hidden');
    if (appRoot) appRoot.classList.remove('settings-active');
    if (settingsBtn) settingsBtn.classList.remove('active');
    if (restoreNav) {
        setSidebarNavMode(settingsReturnNavMode || loadStoredNavMode(), { persist: false });
    }

    const hasMessages = Boolean(chatMessagesInner && chatMessagesInner.children.length > 0);
    if (welcomeScreen) welcomeScreen.classList.toggle('hidden', hasMessages);
    if (chatScrollArea) chatScrollArea.classList.toggle('hidden', !hasMessages);
}

function toInt(value, fallback, min, max) {
    const n = Number.parseInt(String(value), 10);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(min, Math.min(max, n));
}

function toFloat(value, fallback, min, max) {
    const n = Number.parseFloat(String(value));
    if (!Number.isFinite(n)) return fallback;
    return Math.max(min, Math.min(max, n));
}

function bindRangeValue(inputEl, valueEl, formatter) {
    if (!inputEl || !valueEl) return;
    const update = () => {
        valueEl.textContent = formatter(Number(inputEl.value));
    };
    inputEl.addEventListener('input', update);
    update();
}

function applyApiKeyPlaceholders(apiKeys = {}) {
    const mapping = {
        openai: settingApiKeyOpenai,
        anthropic: settingApiKeyAnthropic,
        google: settingApiKeyGoogle,
        elevenlabs: settingApiKeyElevenlabs,
        azure_openai: settingApiKeyAzureOpenai,
        custom: settingApiKeyCustom,
    };
    Object.entries(mapping).forEach(([provider, input]) => {
        if (!input) return;
        input.value = '';
        input.placeholder = safeString(apiKeys[provider]) || 'Not set';
    });
}

function renderPowerPcRecommendationBadge(localPlan) {
    if (!settingAdvPowerPcBadge) return;
    const tier = safeString(localPlan?.device_tier).toLowerCase();
    const mode = safeString(localPlan?.recommended_mode).toLowerCase();
    if (!(tier === 'power' && mode === 'local_preferred')) {
        settingAdvPowerPcBadge.classList.add('hidden');
        settingAdvPowerPcBadge.textContent = '';
        return;
    }
    const modelIds = (Array.isArray(localPlan?.recommended_models) ? localPlan.recommended_models : [])
        .map((row) => safeString(row?.id))
        .filter(Boolean)
        .slice(0, 3);
    const modelText = modelIds.length > 0 ? ` Suggested local models: ${modelIds.join(', ')}.` : '';
    settingAdvPowerPcBadge.textContent = `Power PC mode recommended. This machine is suited for local-preferred runtime.${modelText}`;
    settingAdvPowerPcBadge.classList.remove('hidden');
}

async function refreshPowerPcRecommendationBadge() {
    if (!settingAdvPowerPcBadge) return;
    settingAdvPowerPcBadge.classList.add('hidden');
    settingAdvPowerPcBadge.textContent = '';
    try {
        const res = await fetchJsonSafe('/api/local/recommendations');
        if (!res.ok || !res.data) return;
        renderPowerPcRecommendationBadge(res.data?.local_plan);
    } catch {
        // Non-blocking UI hint only.
    }
}

function normalizeChatMode(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    return new Set(['auto', 'fast', 'thinking']).has(mode) ? mode : '';
}

function _profileHeaderLabel(profileName) {
    const p = availableModelProfiles.find(m => m.name === profileName);
    if (!p) return profileName;
    const activeProfile = activeProfileNameForPersistence();
    const model = (activeProfile === safeString(profileName) ? safeString(activeModelOverride) : '')
        || safeString(p.model).split('/').pop()
        || profileName;
    const activeEffort = activeProfile === safeString(profileName)
        ? normalizeReasoningEffort(activeReasoningEffort)
        : '';
    const effort = activeEffort
        || getPersistedReasoningEffort(profileName)
        || normalizeReasoningEffort(p.reasoning_effort);
    return effort ? `${model} (${effort})` : model;
}

function applyProfileSelection(profileRaw, { allowLocalBackup = false } = {}) {
    const profile = safeString(profileRaw);
    if (!profile) return;
    if (setupProviderSelector) setupProviderSelector.value = profile;
    if (modelSelector) modelSelector.value = profile;
    const modelId = resolveStoredModelSelection(profile, { allowLocalBackup });
    activeModelOverride = modelId;
    if (setupModelSelector) {
        if (modelId && !setupModelSelector.querySelector(`option[value="${CSS.escape(modelId)}"]`)) {
            const opt = document.createElement('option');
            opt.value = modelId;
            opt.textContent = modelId;
            setupModelSelector.appendChild(opt);
        }
        if (modelId) {
            setupModelSelector.value = modelId;
        }
    }
    syncSetupReasoningVisibility(profile);
    renderSetupProviderPickerMenu(profile, { preserveExpanded: false });
    try { window.localStorage.setItem('thomas_active_profile', profile); } catch (_) {}
    if (modelId) {
        try { window.localStorage.setItem('thomas_active_model_id', modelId); } catch (_) {}
    } else {
        try { window.localStorage.removeItem('thomas_active_model_id'); } catch (_) {}
    }
    if (modelSetupCurrentLabel) modelSetupCurrentLabel.textContent = _profileHeaderLabel(profile);
    renderChatComposerSubbar();
}

function setSegmentedControlSelection(groupId, levelRaw) {
    const group = document.getElementById(groupId);
    if (!group) return;
    const level = safeString(levelRaw);
    group.querySelectorAll('.segment').forEach((segmentBtn) => {
        const isActive = safeString(segmentBtn.dataset.level) === level;
        segmentBtn.classList.toggle('active', isActive);
    });
}

function applyUiStatePatchEvent(evt) {
    if (!evt || typeof evt !== 'object') return;
    const rawPatch = evt.applied_patch && typeof evt.applied_patch === 'object'
        ? evt.applied_patch
        : (evt.patch && typeof evt.patch === 'object' ? evt.patch : null);
    if (!rawPatch) return;

    applyProfileSelection(rawPatch.activeProfile);

    const mode = normalizeChatMode(rawPatch.mode);
    if (mode) {
        activeChatMode = mode;
        if (settingAdvDefaultMode) settingAdvDefaultMode.value = mode;
    }

    const settings = rawPatch.settings;
    if (!settings || typeof settings !== 'object') return;

    const autonomyLevel = Number.parseInt(String(settings.autonomyLevel ?? ''), 10);
    if (Number.isFinite(autonomyLevel)) {
        const nextLevel = Math.max(1, Math.min(4, autonomyLevel));
        activeAutonomyLevel = nextLevel;
        setSegmentedControlSelection('setupAutonomyGroup', String(nextLevel));
        if (settingAutonomy) settingAutonomy.value = `L${nextLevel}`;
    }

    const themeRaw = safeString(settings.theme).toLowerCase();
    if (themeRaw) {
        const themeValue = themeRaw === 'system' ? 'auto' : themeRaw;
        if (settingTheme && new Set(['auto', 'light', 'dark']).has(themeValue)) {
            settingTheme.value = themeValue;
        }
    }
}

function refreshSettingsAvatarPreview() {
    const name = safeString(settingsDisplayName?.value) || resolveAgentName(currentPreferences);
    const avatarBase = pendingAvatarOverride !== null
        ? pendingAvatarOverride
        : safeString(currentPreferences?.profile?.avatar_url);
    const avatarUrl = safeString(avatarBase) || safeString(currentCodexStatus?.avatar_url);
    setAvatarVisual(settingsProfileAvatar, {
        text: initialsFromName(name),
        imageUrl: avatarUrl,
    });
}

async function refreshIdentityState() {
    try {
        const [prefsRes, codexStatus] = await Promise.all([
            fetch('/api/preferences'),
            fetchPreferredCodexIdentityStatus(),
        ]);
        if (prefsRes.ok) {
            currentPreferences = await prefsRes.json();
            if (!currentPreferences || typeof currentPreferences !== 'object') currentPreferences = {};
        applyTheme(safeString(currentPreferences?.appearance?.theme) || 'auto');
        applyFontSize(toInt(currentPreferences?.appearance?.font_size, 16, 12, 28));
        const prefAutonomyRaw = safeString(currentPreferences?.autonomy?.default_level).replace(/^l/i, '');
        const prefAutonomy = Number.parseInt(prefAutonomyRaw, 10);
        if (Number.isFinite(prefAutonomy)) {
            activeAutonomyLevel = Math.max(1, Math.min(4, prefAutonomy));
            setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
            if (settingAutonomy) settingAutonomy.value = `L${activeAutonomyLevel}`;
        }
        }
        currentCodexStatus = codexStatus || null;
    } catch (e) {
        console.error('Failed to load identity state', e);
    } finally {
        applyInterfaceMotionPreference();
        updateSidebarIdentity();
        setDebugDockOpen(false, { recordEvent: false });
        updateDebugDockSnapshot();
    }
}

async function fetchPreferredCodexIdentityStatus() {
    const nativeCodexRes = await fetchJsonSafe('/api/openai-codex/status?profile=chatgpt');
    if (nativeCodexRes.ok) return nativeCodexRes.data || null;
    if (nativeCodexRes.status === 404 || nativeCodexRes.status === 405) {
        const legacyCodexRes = await fetchJsonSafe('/api/codex/status');
        return legacyCodexRes.ok ? (legacyCodexRes.data || null) : null;
    }
    return null;
}

function ensureAdvancedChatPhysicsSettingUi() {
    if (!(settingsSections instanceof HTMLElement)) return null;
    let toggle = getSettingAdvChatPhysicsToggle();
    if (toggle instanceof HTMLInputElement) return toggle;
    const sections = Array.from(settingsSections.querySelectorAll('.settings-section'));
    const runtimeSection = sections.find((section) => (
        safeString(section?.querySelector('.settings-section-head h3')?.textContent).trim().toLowerCase() === 'advanced runtime + quality'
    ));
    if (!(runtimeSection instanceof HTMLElement)) return null;
    const row = document.createElement('div');
    row.className = 'switch-row';
    row.id = 'settingAdvChatPhysicsRow';
    row.innerHTML = `
        <div>
            <strong>Advanced Chat Physics</strong>
            <p>Run the chat-world robots on a Phaser Arcade Physics layer with real colliders and grounded bodies.</p>
        </div>
        <label class="toggle-switch">
            <input type="checkbox" id="settingAdvChatPhysicsEnabled">
            <span class="slider round"></span>
        </label>
    `;
    const anchor = settingAdvAnimationFidelity?.closest?.('.form-group')
        || runtimeSection.querySelector('.settings-grid')
        || runtimeSection.lastElementChild;
    if (anchor?.parentNode) {
        anchor.parentNode.insertBefore(row, anchor.nextSibling);
    } else {
        runtimeSection.appendChild(row);
    }
    return getSettingAdvChatPhysicsToggle();
}

function syncAdvancedChatPhysicsSettingUi() {
    const toggle = ensureAdvancedChatPhysicsSettingUi();
    if (!(toggle instanceof HTMLInputElement)) return;
    const fidelity = normalizeAnimationFidelity(
        settingAdvAnimationFidelity?.value,
        animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {}),
    );
    const available = fidelity !== ANIMATION_FIDELITY_MINIMAL;
    if (!available) {
        toggle.checked = false;
    }
    toggle.disabled = !available;
    toggle.closest('.switch-row')?.classList.toggle('is-disabled', !available);
}

async function loadSettings() {
    try {
        const [prefsRes, codexStatus] = await Promise.all([
            fetchJsonSafe('/api/preferences'),
            fetchPreferredCodexIdentityStatus(),
        ]);
        if (!prefsRes.ok) {
            throw new Error(`Failed to load preferences (${prefsRes.status})`);
        }

        currentPreferences = prefsRes.data || {};
        currentCodexStatus = codexStatus || null;
        applyTheme(safeString(currentPreferences?.appearance?.theme) || 'auto');
        applyFontSize(toInt(currentPreferences?.appearance?.font_size, 16, 12, 28));
        applyInterfaceMotionPreference();

        const appearance = currentPreferences.appearance || {};
        const profile = currentPreferences.profile || {};
        const memory = currentPreferences.memory || {};
        const notifications = currentPreferences.notifications || {};
        const autonomy = currentPreferences.autonomy || {};
        const voice = currentPreferences.voice || {};
        const advanced = currentPreferences.advanced || {};
        const advModel = advanced.model || {};
        const advTools = advanced.tools || {};
        const advMemory = advanced.memory || {};
        const advCost = advanced.cost || {};
        const advRuntime = advanced.runtime || {};
        const advFailover = advanced.failover || {};
        const advPrivacy = advanced.privacy || {};
        const advInterface = advanced.interface || {};
        const thomads = currentPreferences.thomads || {};

        if (settingsAdvancedToggle && settingsSuite) {
            settingsAdvancedToggle.checked = false;
            settingsSuite.classList.remove('advanced-mode');
        }
        ensureThomadsSettingsSection();
        refreshThomadsSettingsSectionNav();
        if (settingsSectionSearch) settingsSectionSearch.value = '';
        if (settingsSections) settingsSections.scrollTop = 0;
        updateSettingsSectionNavVisibility();

        if (settingTheme) settingTheme.value = safeString(appearance.theme) || 'auto';
        applyTheme(safeString(appearance.theme) || 'auto');
        const autonomyDefaultLevel = safeString(autonomy.default_level) || 'L1';
        if (settingAutonomy) settingAutonomy.value = autonomyDefaultLevel;
        const autonomyNumeric = Number.parseInt(autonomyDefaultLevel.replace(/^l/i, ''), 10);
        if (Number.isFinite(autonomyNumeric)) {
            activeAutonomyLevel = Math.max(1, Math.min(4, autonomyNumeric));
            setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
        }

        if (settingFontSize) {
            const fontSize = toInt(appearance.font_size, 16, 12, 28);
            settingFontSize.value = String(fontSize);
            if (settingFontSizeValue) settingFontSizeValue.textContent = `${fontSize}px`;
            applyFontSize(fontSize);
        }

        if (settingBubbleStyle) settingBubbleStyle.value = safeString(appearance.bubble_style) || 'rounded';
        if (settingMemoryEnabled) settingMemoryEnabled.checked = Boolean(memory.enabled_global);
        if (setupMemoryToggle) setupMemoryToggle.checked = Boolean(memory.enabled_global);
        if (settingDesktopNotifications) settingDesktopNotifications.checked = Boolean(notifications.desktop);

        if (settingVoice) settingVoice.value = safeString(voice.tts_voice) || 'default';
        if (settingMicDeviceId) settingMicDeviceId.value = safeString(voice.mic_device_id);
        if (settingWakeWordEnabled) settingWakeWordEnabled.checked = Boolean(voice.wake_word_enabled);

        if (settingVoiceSpeed) {
            const voiceSpeed = toFloat(voice.speed, 1.0, 0.5, 2.0);
            settingVoiceSpeed.value = String(voiceSpeed);
            settingVoiceSpeed.dispatchEvent(new Event('input'));
        }

        if (settingConcurrencyLimit) {
            settingConcurrencyLimit.value = String(toInt(autonomy.concurrency_limit, 2, 1, 64));
        }

        if (settingWebPush) settingWebPush.checked = Boolean(notifications.web_push);
        if (settingTelegram) settingTelegram.checked = Boolean(notifications.telegram);

        if (settingAdvTemperature) {
            settingAdvTemperature.value = String(toFloat(advModel.temperature, 0.7, 0, 2));
            settingAdvTemperature.dispatchEvent(new Event('input'));
        }
        if (settingAdvTopP) {
            settingAdvTopP.value = String(toFloat(advModel.top_p, 1, 0, 1));
            settingAdvTopP.dispatchEvent(new Event('input'));
        }
        if (settingAdvFrequencyPenalty) {
            settingAdvFrequencyPenalty.value = String(toFloat(advModel.frequency_penalty, 0, -2, 2));
            settingAdvFrequencyPenalty.dispatchEvent(new Event('input'));
        }
        if (settingAdvPresencePenalty) {
            settingAdvPresencePenalty.value = String(toFloat(advModel.presence_penalty, 0, -2, 2));
            settingAdvPresencePenalty.dispatchEvent(new Event('input'));
        }
        if (settingAdvMaxOutputTokens) settingAdvMaxOutputTokens.value = String(toInt(advModel.max_output_tokens, 4096, 128, 32768));
        if (settingAdvReasoningEffort) settingAdvReasoningEffort.value = normalizeReasoningEffort(advModel.reasoning_effort) || 'medium';
        if (settingAdvReasoningBudget) settingAdvReasoningBudget.value = String(toInt(advModel.reasoning_token_budget, 4096, 128, 65536));
        if (settingAdvDeterministicSeed) settingAdvDeterministicSeed.value = advModel.deterministic_seed === null || advModel.deterministic_seed === undefined ? '' : String(advModel.deterministic_seed);
        if (settingAdvJsonMode) settingAdvJsonMode.checked = Boolean(advModel.json_mode);
        if (settingAdvStopSequences) settingAdvStopSequences.value = safeString(advModel.stop_sequences);
        const runtimeDefaultMode = normalizeChatMode(safeString(advRuntime.default_mode) || 'auto') || 'auto';
        if (settingAdvDefaultMode) settingAdvDefaultMode.value = runtimeDefaultMode;
        activeChatMode = runtimeDefaultMode;

        const runtimeDefaultEconomy = safeString(advRuntime.default_token_economy) || 'optimal';
        if (settingAdvDefaultTokenEconomy) settingAdvDefaultTokenEconomy.value = runtimeDefaultEconomy;
        const economyForComposer = runtimeDefaultEconomy === 'optimal' ? 'balanced' : runtimeDefaultEconomy;
        if (new Set(['cheap', 'balanced', 'max']).has(economyForComposer)) {
            activeTokenEconomy = economyForComposer;
            setSegmentedControlSelection('setupEconomyGroup', economyForComposer);
        }
        if (settingAdvMaxAgentIterations) settingAdvMaxAgentIterations.value = String(toInt(advRuntime.max_agent_iterations, 0, 0, 200));
        if (settingAdvLocalBackgroundAgents) settingAdvLocalBackgroundAgents.checked = Boolean(advRuntime.local_background_agents_enabled);
        if (settingAdvLocalGpuHeadroom) settingAdvLocalGpuHeadroom.value = String(toInt(advRuntime.local_background_min_gpu_headroom_pct, 35, 5, 95));
        void refreshPowerPcRecommendationBadge();
        if (settingAdvQualityEnforce) settingAdvQualityEnforce.checked = Boolean(advRuntime.quality_enforce);
        if (settingAdvQualityRequireVerification) settingAdvQualityRequireVerification.checked = Boolean(advRuntime.quality_require_verification_for_coding);
        if (settingAdvQualityRequireTests) settingAdvQualityRequireTests.checked = Boolean(advRuntime.quality_require_tests_for_code_edits);
        if (settingAdvQualityRequireMonolithGuard) settingAdvQualityRequireMonolithGuard.checked = Boolean(advRuntime.quality_require_monolith_guard_for_coding);

        if (settingAdvAutoToolThreshold) {
            settingAdvAutoToolThreshold.value = String(toFloat(advTools.auto_tool_threshold, 0.45, 0, 1));
            settingAdvAutoToolThreshold.dispatchEvent(new Event('input'));
        }
        if (settingAdvToolTimeoutS) settingAdvToolTimeoutS.value = String(toInt(advTools.tool_timeout_s, 120, 5, 1800));
        if (settingAdvMaxParallelTools) settingAdvMaxParallelTools.value = String(toInt(advTools.max_parallel_tools, 6, 1, 32));
        if (settingAdvRequireCommandApproval) settingAdvRequireCommandApproval.checked = Boolean(advTools.require_command_approval);
        const advSecurity = advanced.security || {};
        if (settingAdvBreakglassWindowEnabled) settingAdvBreakglassWindowEnabled.checked = Boolean(advSecurity.breakglass_window_enabled);
        if (settingAdvBreakglassWindowHours) settingAdvBreakglassWindowHours.value = String(toFloat(advSecurity.breakglass_window_hours, 3, 0.25, 12));
        // The approval window is a security pref, so it saves through its own
        // step-up-authed route (a tap), NOT the general settings PATCH. Bind once.
        if (settingAdvBreakglassWindowEnabled && !settingAdvBreakglassWindowEnabled.dataset.bgwBound) {
            settingAdvBreakglassWindowEnabled.dataset.bgwBound = '1';
            const saveBreakglassWindow = async () => {
                try {
                    const res = await fetch('/api/security/breakglass-window', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            enabled: Boolean(settingAdvBreakglassWindowEnabled.checked),
                            hours: toFloat(settingAdvBreakglassWindowHours?.value, 3, 0.25, 12),
                        }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.ok && data.ok) {
                        notifyUser('Approval window updated.', { tone: 'success', durationMs: 1800, debugKind: 'settings' });
                    } else {
                        notifyUser('Approval window unchanged: ' + (data.reason || ('HTTP ' + res.status)), { tone: 'warning', durationMs: 3200, debugKind: 'settings' });
                    }
                } catch (e) {
                    notifyUser('Could not reach the approval-window endpoint.', { tone: 'error', durationMs: 3000, debugKind: 'error' });
                }
            };
            settingAdvBreakglassWindowEnabled.addEventListener('change', saveBreakglassWindow);
            if (settingAdvBreakglassWindowHours) settingAdvBreakglassWindowHours.addEventListener('change', saveBreakglassWindow);
        }
        if (settingAdvAllowShell) settingAdvAllowShell.checked = Boolean(advTools.allow_shell);
        if (settingAdvAllowFileWrite) settingAdvAllowFileWrite.checked = Boolean(advTools.allow_file_write);
        if (settingAdvAllowNetwork) settingAdvAllowNetwork.checked = Boolean(advTools.allow_network);
        if (settingAdvAllowBrowser) settingAdvAllowBrowser.checked = Boolean(advTools.allow_browser);
        if (settingAdvAllowChannels) settingAdvAllowChannels.checked = Boolean(advTools.allow_channels);
        if (settingAdvAllowGit) settingAdvAllowGit.checked = Boolean(advTools.allow_git);
        if (settingAdvAllowedPaths) settingAdvAllowedPaths.value = safeString(advTools.allowed_paths);
        if (settingAdvBlockedCommands) settingAdvBlockedCommands.value = safeString(advTools.blocked_commands);

        if (settingAdvIncludeGlobalMemory) settingAdvIncludeGlobalMemory.checked = Boolean(advMemory.include_global_memory);
        if (settingAdvRetrievalTopK) settingAdvRetrievalTopK.value = String(toInt(advMemory.retrieval_top_k, 8, 1, 64));
        if (settingAdvMaxPackTokens) settingAdvMaxPackTokens.value = String(toInt(advMemory.max_pack_tokens, 1200, 200, 64000));
        if (settingAdvDecayHalfLifeHours) settingAdvDecayHalfLifeHours.value = String(toFloat(advMemory.decay_half_life_hours, 240, 1, 87600));
        if (settingAdvAutoSummarizeThreshold) settingAdvAutoSummarizeThreshold.value = String(toInt(advMemory.auto_summarize_threshold, 80, 10, 2000));
        if (settingAdvMemoryDecayDays) settingAdvMemoryDecayDays.value = String(toInt(advMemory.memory_decay_days, 90, 1, 3650));
        if (settingAdvAutoCompactEnabled) settingAdvAutoCompactEnabled.checked = Boolean(advMemory.auto_compact_enabled);
        if (settingAdvAutoCompactEpisodeThreshold) settingAdvAutoCompactEpisodeThreshold.value = String(toInt(advMemory.auto_compact_episode_threshold, 2000, 10, 1000000));
        if (settingAdvAutoCompactMinIntervalHours) settingAdvAutoCompactMinIntervalHours.value = String(toFloat(advMemory.auto_compact_min_interval_hours, 24, 0.1, 8760));
        if (settingAdvAutoOptimizeEnabled) settingAdvAutoOptimizeEnabled.checked = Boolean(advMemory.auto_optimize_enabled);
        if (settingAdvAutoOptimizeWasteThreshold) settingAdvAutoOptimizeWasteThreshold.value = String(toFloat(advMemory.auto_optimize_waste_threshold, 0.22, 0, 1));
        if (settingAdvAutoOptimizeMinIntervalHours) settingAdvAutoOptimizeMinIntervalHours.value = String(toFloat(advMemory.auto_optimize_min_interval_hours, 12, 0.1, 8760));
        if (settingAdvContradictionPolicy) settingAdvContradictionPolicy.value = safeString(advMemory.contradiction_policy) || 'ask';
        if (settingAdvContextPruneStrategy) settingAdvContextPruneStrategy.value = safeString(advMemory.context_prune_strategy) || 'balanced';
        if (settingAdvIncludeProfileMemory) settingAdvIncludeProfileMemory.checked = Boolean(advMemory.include_profile_memory);
        if (settingAdvIncludeThreadMemory) settingAdvIncludeThreadMemory.checked = Boolean(advMemory.include_thread_memory);
        if (settingAdvPinsOnly) settingAdvPinsOnly.checked = Boolean(advMemory.pins_only);
        if (settingAdvPinnedContext) settingAdvPinnedContext.value = safeString(advMemory.pinned_context);

        if (settingAdvSessionTokenBudget) settingAdvSessionTokenBudget.value = String(toInt(advCost.session_token_budget, 200000, 1000, 5000000));
        if (settingAdvDailyTokenBudget) settingAdvDailyTokenBudget.value = String(toInt(advCost.daily_token_budget, 2000000, 10000, 50000000));
        if (settingAdvMaxRetries) settingAdvMaxRetries.value = String(toInt(advCost.max_retries, 2, 0, 20));
        if (settingAdvRetryBackoffMs) settingAdvRetryBackoffMs.value = String(toInt(advCost.retry_backoff_ms, 800, 0, 120000));
        if (settingAdvThrottleOnBudget) settingAdvThrottleOnBudget.checked = Boolean(advCost.throttle_on_budget);
        if (settingAdvLowCostMode) settingAdvLowCostMode.checked = Boolean(advCost.low_cost_mode);
        if (settingAdvProviderFailoverChain) settingAdvProviderFailoverChain.value = safeString(advCost.provider_failover_chain);
        if (settingAdvModelFailoverChain) settingAdvModelFailoverChain.value = safeString(advCost.model_failover_chain);
        if (settingAdvFailoverEnabled) settingAdvFailoverEnabled.checked = Boolean(advFailover.enabled);
        if (settingAdvChatAutoFailover) settingAdvChatAutoFailover.checked = Boolean(advFailover.chat_auto_failover);
        if (settingAdvFallbackOnAuthError) settingAdvFallbackOnAuthError.checked = Boolean(advFailover.fallback_on_auth_error);
        if (settingAdvFailoverCooldownSeconds) settingAdvFailoverCooldownSeconds.value = String(toInt(advFailover.cooldown_seconds, 300, 0, 86400));

        if (settingAdvRetentionDays) settingAdvRetentionDays.value = String(toInt(advPrivacy.retention_days, 90, 1, 3650));
        if (settingAdvTelemetryEnabled) settingAdvTelemetryEnabled.checked = Boolean(advPrivacy.telemetry_enabled);
        if (settingAdvRedactSecretsInLogs) settingAdvRedactSecretsInLogs.checked = Boolean(advPrivacy.redact_secrets_in_logs);
        if (settingAdvPiiGuardStrict) settingAdvPiiGuardStrict.checked = Boolean(advPrivacy.pii_guard_strict);
        if (settingAdvLocalOnlyMode) settingAdvLocalOnlyMode.checked = Boolean(advPrivacy.local_only_mode);
        if (settingAdvAuditLogEnabled) settingAdvAuditLogEnabled.checked = Boolean(advPrivacy.audit_log_enabled);
        if (settingAdvExportOnExit) settingAdvExportOnExit.checked = Boolean(advPrivacy.export_on_exit);

        if (settingAdvUiDensity) settingAdvUiDensity.value = safeString(advInterface.ui_density) || 'comfortable';
        if (settingAdvCodeTheme) settingAdvCodeTheme.value = safeString(advInterface.code_theme) || 'atom-one-dark';
        if (settingAdvEventLogVerbosity) settingAdvEventLogVerbosity.value = safeString(advInterface.event_log_verbosity) || 'standard';
        if (settingAdvShowTimestamps) settingAdvShowTimestamps.checked = Boolean(advInterface.show_timestamps);
        if (settingAdvShowTokenMeter) settingAdvShowTokenMeter.checked = Boolean(advInterface.show_token_meter);
        const animationFidelity = animationFidelityFromInterfacePrefs(advInterface);
        if (settingAdvAnimationFidelity) settingAdvAnimationFidelity.value = animationFidelity;
        if (settingAdvAnimationsEnabled) settingAdvAnimationsEnabled.checked = isAnimationFidelityEnabled(animationFidelity);
        const settingAdvChatPhysicsEnabled = ensureAdvancedChatPhysicsSettingUi();
        if (settingAdvChatPhysicsEnabled instanceof HTMLInputElement) {
            settingAdvChatPhysicsEnabled.checked = Boolean(advInterface.advanced_chat_physics);
        }
        if (settingAdvDebugPanelEnabled) settingAdvDebugPanelEnabled.checked = Boolean(advInterface.debug_panel_enabled);
        if (settingAdvLabsFlags) settingAdvLabsFlags.value = safeString(advInterface.labs_flags);
        syncAdvancedChatPhysicsSettingUi();

        // ── New Settings: Workspaces ──
        const workspaces = currentPreferences.workspaces || {};
        if (settingWsMission) settingWsMission.checked = workspaces.mission !== false;
        if (settingWsAppBuilder) settingWsAppBuilder.checked = workspaces.app_builder !== false;
        if (settingWsMyStuff) settingWsMyStuff.checked = workspaces.my_stuff !== false;
        if (settingWsChannels) settingWsChannels.checked = workspaces.channels !== false;
        if (settingWsTokenEconomy) settingWsTokenEconomy.checked = workspaces.token_economy !== false;
        if (settingWsMarketplace) settingWsMarketplace.checked = workspaces.marketplace !== false;
        if (settingWsOffice) settingWsOffice.checked = Boolean(workspaces.office);

        // ── New Settings: Token Economy ──
        const teSettings = currentPreferences.token_economy || {};
        if (settingTeMonthlyBudget) settingTeMonthlyBudget.value = String(toInt(teSettings.monthly_budget, 5000000, 0, 100000000));
        if (settingTeBudgetAlertPct) settingTeBudgetAlertPct.value = safeString(teSettings.budget_alert_pct) || '75';
        if (settingTeShowSidebarSpend) settingTeShowSidebarSpend.checked = teSettings.show_sidebar_spend !== false;
        if (settingTeAutoSummarize) settingTeAutoSummarize.checked = Boolean(teSettings.auto_summarize);

        // ── New Settings: Channels ──
        const chSettings = currentPreferences.channels || {};
        if (settingChDefaultChannel) settingChDefaultChannel.value = safeString(chSettings.default_channel) || 'none';
        if (settingChMaxMessageLength) settingChMaxMessageLength.value = String(toInt(chSettings.max_message_length, 4000, 100, 10000));
        if (settingChAutoRoute) settingChAutoRoute.checked = chSettings.auto_route !== false;
        if (settingChNotifications) settingChNotifications.checked = chSettings.notifications !== false;
        if (settingChAllowUploads) settingChAllowUploads.checked = chSettings.allow_uploads !== false;

        // ── New Settings: Marketplace & Plugins ──
        const mpSettings = currentPreferences.marketplace || {};
        if (settingMpAutoUpdate) settingMpAutoUpdate.checked = mpSettings.auto_update !== false;
        if (settingMpShowDomainModules) settingMpShowDomainModules.checked = Boolean(mpSettings.show_domain_modules);
        if (settingMpPluginNetworkAccess) settingMpPluginNetworkAccess.checked = mpSettings.plugin_network_access !== false;

        // ── New Settings: Data & Storage ──
        const dataSettings = currentPreferences.data || {};
        if (settingDataPersistHistory) settingDataPersistHistory.checked = dataSettings.persist_history !== false;
        if (settingDataAutoArchive) settingDataAutoArchive.checked = Boolean(dataSettings.auto_archive);

        // Populate About section
        const aboutVersion = document.getElementById('settingAboutVersion');
        const aboutRuntime = document.getElementById('settingAboutRuntime');
        const aboutModel = document.getElementById('settingAboutModel');
        if (aboutVersion) aboutVersion.textContent = safeString(currentPreferences._version) || 'dev';
        if (aboutRuntime) aboutRuntime.textContent = safeString(currentPreferences._runtime) || 'aiohttp';
        if (aboutModel) aboutModel.textContent = safeString(currentPreferences._active_model) || '—';

        applyApiKeyPlaceholders(currentPreferences.api_keys || {});

        const displayName = resolveAgentName(currentPreferences);
        if (settingsDisplayName) settingsDisplayName.value = displayName;
        if (settingProfileType) {
            const profileType = safeString(profile.profile_type).toLowerCase();
            settingProfileType.value = new Set(['adaptive', 'coder', 'non_coder']).has(profileType) ? profileType : 'adaptive';
        }
        pendingAvatarOverride = null;
        refreshSettingsAvatarPreview();

        if (settingsAccountMeta) {
            if (currentCodexStatus?.logged_in) {
                const plan = safeString(currentCodexStatus.plan_type) || 'plan';
                const email = safeString(currentCodexStatus.email) || 'account';
                settingsAccountMeta.textContent = `Connected as ${email} (${plan})`;
            } else {
                settingsAccountMeta.textContent = 'Not connected. Profile will use local settings only.';
            }
        }
        const settingThomadsConfig = getSettingThomadsConfigInput();
        if (settingThomadsConfig) {
            if (typeof thomads === 'object' && thomads !== null && !Array.isArray(thomads)) {
                settingThomadsConfig.value = JSON.stringify(thomads, null, 2);
            } else {
                settingThomadsConfig.value = '{}';
            }
        }
        // Apply workspace visibility based on loaded settings
        applyWorkspaceVisibility(currentPreferences.workspaces);
    } catch (e) {
        console.error("Failed to load settings", e);
        notifyUser('Could not load settings right now. Check backend and retry.', {
            tone: 'error',
            debugKind: 'error',
            durationMs: 3200,
        });
    }
}

function ensureThomadsSettingsSection() {
    if (!settingsSections) return false;
    if (document.getElementById('settingThomadsConfig')) return false;

    const sections = Array.from(settingsSections.querySelectorAll('.settings-section'));
    const headingText = (section) => safeString(section?.querySelector('.settings-section-head h3')?.textContent).trim().toLowerCase();
    const modelBehaviorSection = sections.find((row) => headingText(row) === 'advanced model behavior');
    const apiIntegrationsSection = sections.find((row) => headingText(row) === 'advanced api integrations');
    if (!modelBehaviorSection && !apiIntegrationsSection) return false;

    const thomadsSection = document.createElement('section');
    thomadsSection.className = 'settings-section settings-advanced-only';
    thomadsSection.innerHTML = "<div class='settings-section-head'><h3>Thomads</h3><p>Custom Thomas settings stored as JSON.</p></div><div class='form-group settings-top-gap'><label for='settingThomadsConfig'>Thomads Settings (JSON)</label><textarea id='settingThomadsConfig' class='form-control settings-textarea' rows='8' placeholder='{\"enable_x\": true}'></textarea></div><p class='settings-inline-note'>Enter valid JSON only. Leave empty to clear all Thomads settings.</p>";
    const insertBefore = modelBehaviorSection ? modelBehaviorSection : (apiIntegrationsSection ? apiIntegrationsSection.nextElementSibling : null);
    if (insertBefore) {
        settingsSections.insertBefore(thomadsSection, insertBefore);
    } else {
        settingsSections.appendChild(thomadsSection);
    }
    return true;
}

function getSettingThomadsConfigInput() {
    return document.getElementById('settingThomadsConfig');
}

function refreshThomadsSettingsSectionNav() {
    if (typeof buildSettingsSectionNav === 'function') {
        buildSettingsSectionNav();
        return;
    }
    if (typeof initSettingsSectionNavigation === 'function' && !settingsNavBound) {
        initSettingsSectionNavigation();
    }
}

function collectApiKeysPatch() {
    const mapping = {
        openai: settingApiKeyOpenai,
        anthropic: settingApiKeyAnthropic,
        google: settingApiKeyGoogle,
        elevenlabs: settingApiKeyElevenlabs,
        azure_openai: settingApiKeyAzureOpenai,
        custom: settingApiKeyCustom,
    };
    const patch = {};
    Object.entries(mapping).forEach(([provider, input]) => {
        if (!input) return;
        const raw = safeString(input.value);
        if (!raw) return;
        patch[provider] = raw.toLowerCase() === 'clear' ? '' : raw;
    });
    return Object.keys(patch).length > 0 ? patch : null;
}

function collectThomadsPatch() {
    const settingThomadsConfig = getSettingThomadsConfigInput();
    if (!settingThomadsConfig) return null;
    const raw = safeString(settingThomadsConfig.value).trim();
    if (!raw) return null;

    let parsed;
    try {
        parsed = JSON.parse(raw);
    } catch (error) {
        throw new Error('Invalid JSON in Thomads settings. Enter valid JSON.');
    }

    if (parsed === null) {
        return null;
    }
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Thomads settings must be a JSON object.');
    }

    return Object.keys(parsed).length > 0 ? parsed : {};
}

async function saveSettings() {
    try {
        saveSettingsBtn.textContent = 'Saving...';
        const profileAvatarValue = pendingAvatarOverride !== null
            ? safeString(pendingAvatarOverride)
            : safeString(currentPreferences?.profile?.avatar_url);
        const deterministicSeedRaw = safeString(settingAdvDeterministicSeed?.value);
        const deterministicSeed = deterministicSeedRaw ? toInt(deterministicSeedRaw, 0, 0, 2147483647) : null;
        const animationFidelity = normalizeAnimationFidelity(
            settingAdvAnimationFidelity?.value,
            animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {}),
        );
        const settingAdvChatPhysicsEnabled = getSettingAdvChatPhysicsToggle();
        const patch = {
            profile: {
                display_name: safeString(settingsDisplayName?.value),
                avatar_url: profileAvatarValue,
                profile_type: safeString(settingProfileType?.value) || 'adaptive',
            },
            appearance: {
                theme: safeString(settingTheme?.value) || 'auto',
                font_size: toInt(settingFontSize?.value, 16, 12, 28),
                bubble_style: safeString(settingBubbleStyle?.value) || 'rounded',
            },
            memory: {
                enabled_global: Boolean(settingMemoryEnabled?.checked),
            },
            notifications: {
                desktop: Boolean(settingDesktopNotifications?.checked),
                web_push: Boolean(settingWebPush?.checked),
                telegram: Boolean(settingTelegram?.checked),
            },
            autonomy: {
                default_level: safeString(settingAutonomy?.value) || 'L1',
                concurrency_limit: toInt(settingConcurrencyLimit?.value, 2, 1, 64),
            },
            voice: {
                tts_voice: safeString(settingVoice?.value) || 'default',
                speed: toFloat(settingVoiceSpeed?.value, 1, 0.5, 2),
                wake_word_enabled: Boolean(settingWakeWordEnabled?.checked),
                mic_device_id: safeString(settingMicDeviceId?.value),
            },
            advanced: {
                model: {
                    active_profile: safeString(setupProviderSelector?.value) || safeString(currentPreferences?.advanced?.model?.active_profile),
                    model_id: resolveActiveModelIdForProfile(safeString(setupProviderSelector?.value) || safeString(modelSelector?.value) || safeString(currentPreferences?.advanced?.model?.active_profile)) || safeString(currentPreferences?.advanced?.model?.model_id),
                    temperature: toFloat(settingAdvTemperature?.value, 0.7, 0, 2),
                    top_p: toFloat(settingAdvTopP?.value, 1, 0, 1),
                    frequency_penalty: toFloat(settingAdvFrequencyPenalty?.value, 0, -2, 2),
                    presence_penalty: toFloat(settingAdvPresencePenalty?.value, 0, -2, 2),
                    max_output_tokens: toInt(settingAdvMaxOutputTokens?.value, 4096, 128, 32768),
                    reasoning_effort: normalizeReasoningEffort(settingAdvReasoningEffort?.value) || 'medium',
                    reasoning_token_budget: toInt(settingAdvReasoningBudget?.value, 4096, 128, 65536),
                    json_mode: Boolean(settingAdvJsonMode?.checked),
                    deterministic_seed: deterministicSeed,
                    stop_sequences: safeString(settingAdvStopSequences?.value),
                },
                runtime: {
                    default_mode: safeString(settingAdvDefaultMode?.value) || 'auto',
                    default_token_economy: safeString(settingAdvDefaultTokenEconomy?.value) || 'optimal',
                    max_agent_iterations: toInt(settingAdvMaxAgentIterations?.value, 0, 0, 200),
                    local_background_agents_enabled: Boolean(settingAdvLocalBackgroundAgents?.checked),
                    local_background_min_gpu_headroom_pct: toInt(settingAdvLocalGpuHeadroom?.value, 35, 5, 95),
                    quality_enforce: Boolean(settingAdvQualityEnforce?.checked),
                    quality_require_verification_for_coding: Boolean(settingAdvQualityRequireVerification?.checked),
                    quality_require_tests_for_code_edits: Boolean(settingAdvQualityRequireTests?.checked),
                    quality_require_monolith_guard_for_coding: Boolean(settingAdvQualityRequireMonolithGuard?.checked),
                },
                tools: {
                    auto_tool_threshold: toFloat(settingAdvAutoToolThreshold?.value, 0.45, 0, 1),
                    require_command_approval: Boolean(settingAdvRequireCommandApproval?.checked),
                    allow_shell: Boolean(settingAdvAllowShell?.checked),
                    allow_file_write: Boolean(settingAdvAllowFileWrite?.checked),
                    allow_network: Boolean(settingAdvAllowNetwork?.checked),
                    allow_browser: Boolean(settingAdvAllowBrowser?.checked),
                    allow_channels: Boolean(settingAdvAllowChannels?.checked),
                    allow_git: Boolean(settingAdvAllowGit?.checked),
                    tool_timeout_s: toInt(settingAdvToolTimeoutS?.value, 120, 5, 1800),
                    max_parallel_tools: toInt(settingAdvMaxParallelTools?.value, 6, 1, 32),
                    allowed_paths: safeString(settingAdvAllowedPaths?.value),
                    blocked_commands: safeString(settingAdvBlockedCommands?.value),
                },
                memory: {
                    include_global_memory: Boolean(settingAdvIncludeGlobalMemory?.checked),
                    include_profile_memory: Boolean(settingAdvIncludeProfileMemory?.checked),
                    include_thread_memory: Boolean(settingAdvIncludeThreadMemory?.checked),
                    pins_only: Boolean(settingAdvPinsOnly?.checked),
                    max_pack_tokens: toInt(settingAdvMaxPackTokens?.value, 1200, 200, 64000),
                    decay_half_life_hours: toFloat(settingAdvDecayHalfLifeHours?.value, 240, 1, 87600),
                    retrieval_top_k: toInt(settingAdvRetrievalTopK?.value, 8, 1, 64),
                    auto_summarize_threshold: toInt(settingAdvAutoSummarizeThreshold?.value, 80, 10, 2000),
                    memory_decay_days: toInt(settingAdvMemoryDecayDays?.value, 90, 1, 3650),
                    auto_compact_enabled: Boolean(settingAdvAutoCompactEnabled?.checked),
                    auto_compact_episode_threshold: toInt(settingAdvAutoCompactEpisodeThreshold?.value, 2000, 10, 1000000),
                    auto_compact_min_interval_hours: toFloat(settingAdvAutoCompactMinIntervalHours?.value, 24, 0.1, 8760),
                    auto_optimize_enabled: Boolean(settingAdvAutoOptimizeEnabled?.checked),
                    auto_optimize_waste_threshold: toFloat(settingAdvAutoOptimizeWasteThreshold?.value, 0.22, 0, 1),
                    auto_optimize_min_interval_hours: toFloat(settingAdvAutoOptimizeMinIntervalHours?.value, 12, 0.1, 8760),
                    contradiction_policy: safeString(settingAdvContradictionPolicy?.value) || 'ask',
                    context_prune_strategy: safeString(settingAdvContextPruneStrategy?.value) || 'balanced',
                    pinned_context: safeString(settingAdvPinnedContext?.value),
                },
                cost: {
                    session_token_budget: toInt(settingAdvSessionTokenBudget?.value, 200000, 1000, 5000000),
                    daily_token_budget: toInt(settingAdvDailyTokenBudget?.value, 2000000, 10000, 50000000),
                    throttle_on_budget: Boolean(settingAdvThrottleOnBudget?.checked),
                    low_cost_mode: Boolean(settingAdvLowCostMode?.checked),
                    max_retries: toInt(settingAdvMaxRetries?.value, 2, 0, 20),
                    retry_backoff_ms: toInt(settingAdvRetryBackoffMs?.value, 800, 0, 120000),
                    provider_failover_chain: safeString(settingAdvProviderFailoverChain?.value),
                    model_failover_chain: safeString(settingAdvModelFailoverChain?.value),
                },
                failover: {
                    enabled: Boolean(settingAdvFailoverEnabled?.checked),
                    chat_auto_failover: Boolean(settingAdvChatAutoFailover?.checked),
                    fallback_on_auth_error: Boolean(settingAdvFallbackOnAuthError?.checked),
                    cooldown_seconds: toInt(settingAdvFailoverCooldownSeconds?.value, 300, 0, 86400),
                },
                privacy: {
                    telemetry_enabled: Boolean(settingAdvTelemetryEnabled?.checked),
                    redact_secrets_in_logs: Boolean(settingAdvRedactSecretsInLogs?.checked),
                    pii_guard_strict: Boolean(settingAdvPiiGuardStrict?.checked),
                    local_only_mode: Boolean(settingAdvLocalOnlyMode?.checked),
                    audit_log_enabled: Boolean(settingAdvAuditLogEnabled?.checked),
                    retention_days: toInt(settingAdvRetentionDays?.value, 90, 1, 3650),
                    export_on_exit: Boolean(settingAdvExportOnExit?.checked),
                },
                interface: {
                    ui_density: safeString(settingAdvUiDensity?.value) || 'comfortable',
                    show_timestamps: Boolean(settingAdvShowTimestamps?.checked),
                    show_token_meter: Boolean(settingAdvShowTokenMeter?.checked),
                    animation_fidelity: animationFidelity,
                    animations_enabled: isAnimationFidelityEnabled(animationFidelity),
                    advanced_chat_physics: isAnimationFidelityEnabled(animationFidelity) && Boolean(settingAdvChatPhysicsEnabled?.checked),
                    code_theme: safeString(settingAdvCodeTheme?.value) || 'atom-one-dark',
                    debug_panel_enabled: Boolean(settingAdvDebugPanelEnabled?.checked),
                    event_log_verbosity: safeString(settingAdvEventLogVerbosity?.value) || 'standard',
                    labs_flags: safeString(settingAdvLabsFlags?.value),
                },
            },
        };

        const apiKeysPatch = collectApiKeysPatch();
        if (apiKeysPatch) {
            patch.api_keys = apiKeysPatch;
        }

        const thomadsPatch = collectThomadsPatch();
        if (thomadsPatch !== null) {
            patch.thomads = thomadsPatch;
        }

        // ── New Settings patches ──
        patch.workspaces = {
            mission: Boolean(settingWsMission?.checked),
            app_builder: Boolean(settingWsAppBuilder?.checked),
            my_stuff: Boolean(settingWsMyStuff?.checked),
            channels: Boolean(settingWsChannels?.checked),
            token_economy: Boolean(settingWsTokenEconomy?.checked),
            marketplace: Boolean(settingWsMarketplace?.checked),
            office: Boolean(settingWsOffice?.checked),
        };
        patch.token_economy = {
            monthly_budget: toInt(settingTeMonthlyBudget?.value, 5000000, 0, 100000000),
            budget_alert_pct: safeString(settingTeBudgetAlertPct?.value) || '75',
            show_sidebar_spend: Boolean(settingTeShowSidebarSpend?.checked),
            auto_summarize: Boolean(settingTeAutoSummarize?.checked),
        };
        patch.channels = {
            default_channel: safeString(settingChDefaultChannel?.value) || 'none',
            max_message_length: toInt(settingChMaxMessageLength?.value, 4000, 100, 10000),
            auto_route: Boolean(settingChAutoRoute?.checked),
            notifications: Boolean(settingChNotifications?.checked),
            allow_uploads: Boolean(settingChAllowUploads?.checked),
        };
        patch.marketplace = {
            auto_update: Boolean(settingMpAutoUpdate?.checked),
            show_domain_modules: Boolean(settingMpShowDomainModules?.checked),
            plugin_network_access: Boolean(settingMpPluginNetworkAccess?.checked),
        };
        patch.data = {
            persist_history: Boolean(settingDataPersistHistory?.checked),
            auto_archive: Boolean(settingDataAutoArchive?.checked),
        };

        // Apply workspace visibility immediately
        applyWorkspaceVisibility(patch.workspaces);

        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patch)
        });
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }

        currentPreferences = await res.json();
        applyTheme(safeString(currentPreferences?.appearance?.theme) || 'auto');
        applyFontSize(toInt(currentPreferences?.appearance?.font_size, 16, 12, 28));
        applyInterfaceMotionPreference();
        updateSidebarIdentity();
        applyApiKeyPlaceholders(currentPreferences.api_keys || {});
        if (setupMemoryToggle) {
            setupMemoryToggle.checked = Boolean(currentPreferences?.memory?.enabled_global);
        }
        /* Preserve current debug-dock open/closed state on save —
           don't force-open it just because the pref is enabled.
           Only sync the toggle if it was *just* enabled or disabled. */
        updateDebugDockSnapshot();

        saveSettingsBtn.textContent = 'Saved!';
        notifyUser('Settings saved.', {
            tone: 'success',
            durationMs: 1700,
            dedupeMs: 1000,
            debugKind: 'settings',
        });
        setTimeout(() => {
            saveSettingsBtn.textContent = 'Save Settings';
        }, 1000);
    } catch (e) {
        console.error("Failed to save settings", e);
        notifyUser('Could not save settings. Check connection and try again.', {
            tone: 'error',
            debugKind: 'error',
            durationMs: 3200,
        });
        saveSettingsBtn.textContent = 'Error';
        setTimeout(() => {
            saveSettingsBtn.textContent = 'Save Settings';
        }, 1200);
    }
}

// Boot
let __thomasHasBootstrapped = false;
