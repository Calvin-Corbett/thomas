/* Shared settings helpers extracted from the main settings runtime. */

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
    runtimeSection.appendChild(row);
    return row.querySelector('#settingAdvChatPhysicsEnabled');
}

function syncAdvancedChatPhysicsSettingUi() {
    const toggle = ensureAdvancedChatPhysicsSettingUi();
    if (!(toggle instanceof HTMLInputElement)) return;
    const fidelity = normalizeAnimationFidelity(
        settingAdvAnimationFidelity?.value,
        animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {}),
    );
    const enabled = isAnimationFidelityEnabled(fidelity);
    toggle.disabled = !enabled;
    const row = toggle.closest('.switch-row');
    if (row) {
        row.classList.toggle('disabled', !enabled);
    }
}
