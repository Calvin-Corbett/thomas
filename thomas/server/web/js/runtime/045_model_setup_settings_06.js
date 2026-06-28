function loadStoredBuilderMode() {
    try {
        if (!window?.localStorage) return false;
        return window.localStorage.getItem(BUILDER_MODE_STORAGE_KEY) === '1';
    } catch {
        return false;
    }
}

function saveStoredBuilderMode(enabled) {
    try {
        if (!window?.localStorage) return;
        window.localStorage.setItem(BUILDER_MODE_STORAGE_KEY, enabled ? '1' : '0');
    } catch {
        // Ignore storage failures.
    }
}

function humanizeConnectionPath(pathRaw) {
    const path = safeString(pathRaw).toLowerCase();
    if (path === 'codex') return 'ChatGPT (OpenAI)';
    if (path === 'manual') return 'Provider API key';
    if (path === 'local') return 'Local Ollama';
    if (path) return path;
    return 'Not connected';
}

function renderWelcomeReadinessPills(items) {
    const pills = document.getElementById('welcomeReadinessPills');
    if (!pills) return;
    pills.innerHTML = '';
    (Array.isArray(items) ? items : []).forEach((item) => {
        const pill = document.createElement('span');
        const tone = safeString(item?.tone).toLowerCase();
        let border = 'rgba(148, 163, 184, 0.24)';
        let ink = 'var(--text-secondary)';
        if (tone === 'ok') { border = 'rgba(104, 212, 163, 0.38)'; ink = 'var(--success-ink, #8dd7a5)'; }
        else if (tone === 'error') { border = 'rgba(255, 143, 143, 0.38)'; ink = 'var(--danger-ink, #ffb4b4)'; }
        else if (tone === 'warn') { border = 'rgba(247, 196, 107, 0.38)'; ink = 'var(--warning-ink, #f7c46b)'; }
        pill.setAttribute('style', ['display:inline-flex','align-items:center','gap:6px','padding:6px 10px','border-radius:999px',`border:1px solid ${border}`,'background:rgba(15, 23, 42, 0.34)',`color:${ink}`,'font-size:0.82rem'].join(';'));
        pill.textContent = `${safeString(item?.label)}: ${safeString(item?.value)}`;
        pills.appendChild(pill);
    });
}

function updateWelcomeSupportRail(builderModeEnabled) {
    const supportCopy = document.getElementById('welcomeSupportCopy');
    if (supportCopy) {
        supportCopy.textContent = builderModeEnabled
            ? 'Builder controls are on. Thomas still keeps chat, tasks, and repair as the everyday path.'
            : 'Thomas keeps builder controls hidden until you turn them on. You can rerun Easy Setup or open Settings any time.';
    }
    const readinessStatus = document.getElementById('welcomeReadinessStatus');
    if (readinessStatus) {
        readinessStatus.textContent = builderModeEnabled ? 'Builder Mode Active' : 'Everyday Mode';
    }
    const builderButton = document.getElementById('welcomeBuilderModeBtn');
    if (builderButton) {
        builderButton.textContent = builderModeEnabled ? 'Hide Builder Controls' : 'Show Builder Controls';
    }
}

function setBuilderMode(enabled, { persist = true, syncSettings = true } = {}) {
    const builderModeEnabled = Boolean(enabled);
    if (persist) saveStoredBuilderMode(builderModeEnabled);
    if (appRoot) appRoot.classList.toggle('builder-mode-active', builderModeEnabled);
    const builderButtons = Array.from(document.querySelectorAll('.sidebar-nav [data-nav-mode]'));
    builderButtons.forEach((button) => {
        button.classList.toggle('hidden', !builderModeEnabled);
        button.setAttribute('aria-hidden', builderModeEnabled ? 'false' : 'true');
    });
    const builderDivider = document.querySelector('.sidebar-nav-divider');
    if (builderDivider) {
        builderDivider.classList.toggle('hidden', !builderModeEnabled);
    }
    if (debugDockToggleBtn) {
        debugDockToggleBtn.classList.toggle('hidden', !builderModeEnabled);
    }
    if (!builderModeEnabled) {
        if (typeof setDebugDockOpen === 'function') setDebugDockOpen(false, { recordEvent: false });
        if (sidebarNavMode === 'app_builder' || sidebarNavMode === 'marketplace') {
            ensureSettingsUiClosed();
            setSidebarNavMode('chat');
            setSidebarSearchScope('chat');
        }
    }
    if (syncSettings && settingsAdvancedToggle) settingsAdvancedToggle.checked = builderModeEnabled;
    if (settingsSuite) settingsSuite.classList.toggle('advanced-mode', builderModeEnabled);
    if (typeof updateSettingsSectionNavVisibility === 'function') updateSettingsSectionNavVisibility();
    ensureConnectionDefaultsShell(builderModeEnabled);
    updateWelcomeSupportRail(builderModeEnabled);
}

function ensureConnectionDefaultsShell(builderModeEnabled) {
    const modelSetupBtn = document.querySelector('[data-nav-mode="model_setup"]');
    if (modelSetupBtn) {
        modelSetupBtn.title = 'Connection and defaults';
        modelSetupBtn.setAttribute('aria-label', 'Open connection and defaults');
    }
    if (typeof syncModelSetupCurrentLabel === 'function') {
        syncModelSetupCurrentLabel();
    } else if (modelSetupCurrentLabel && new Set(['loading...', 'model setup', 'connection & defaults']).has(safeString(modelSetupCurrentLabel.textContent).toLowerCase())) {
        modelSetupCurrentLabel.textContent = 'Connection & Defaults';
    }
}

function applyProductShellCopy() {
    const sidebarDivider = document.querySelector('.sidebar-nav-divider');
    if (sidebarDivider) sidebarDivider.textContent = 'Build And Extend';
    const welcomeSubtitle = document.querySelector('#welcomeScreen .welcome-subtitle');
    if (welcomeSubtitle) welcomeSubtitle.textContent = 'Ready when you are. Start a chat, explore past conversations, or customize your workspace.';
    const navLabels = { 'chat': 'Chat', 'search': 'Find', 'app_builder': 'Build', 'channels': 'Channels', 'marketplace': 'Extend', 'office': 'Office', 'tasks': 'Tasks', 'repair': 'Repair' };
    document.querySelectorAll('.sidebar-nav [role="button"], .sidebar-nav button').forEach((item) => {
        const mode = safeString(item?.getAttribute('data-nav-mode')).toLowerCase();
        if (navLabels[mode]) {
            const label = item.querySelector('span:last-child');
            if (label) label.textContent = navLabels[mode];
        }
    });
}

