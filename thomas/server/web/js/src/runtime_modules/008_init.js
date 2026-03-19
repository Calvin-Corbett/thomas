// Extracted from part-004b.js
// From init


/**
 * Initialize the ultra-premium UI behaviors
 */
const BUILDER_MODE_STORAGE_KEY = 'thomas.builder_mode.enabled';

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

function updateWelcomeSupportRail(builderModeEnabled) {
    const supportCopy = document.getElementById('welcomeSupportCopy');
    if (supportCopy) {
        supportCopy.textContent = builderModeEnabled
            ? 'Builder controls are on. Thomas still keeps chat, tasks, and repair as the everyday path.'
            : 'Thomas keeps builder controls hidden until you turn them on. You can rerun Easy Setup or open Settings any time.';
    }

    const onboarding = typeof getOnboardingFromPrefs === 'function'
        ? (getOnboardingFromPrefs() || {})
        : (currentPreferences?.onboarding || {});
    const setupComplete = Boolean(onboarding?.setup_completed);
    const connectionMethod = safeString(onboarding?.connection_method).toLowerCase();
    const connectionLabel = humanizeConnectionPath(connectionMethod);
    const memoryEnabled = Boolean(currentPreferences?.memory?.enabled_global);
    const codexHealthy = connectionMethod !== 'codex' || Boolean(currentCodexStatus?.logged_in);
    let workspaceStatusLabel = 'Guarded';
    let workspaceStatusTone = 'warn';
    let workspaceMetaText = 'Easy Setup is still required before Thomas unlocks memory, tools, and automation.';

    const readinessStatus = document.getElementById('welcomeReadinessStatus');
    if (readinessStatus) {
        let statusText = 'Setup is not finished yet. Thomas is staying in guarded mode until verification passes.';
        let statusColor = 'var(--text-secondary)';
        if (setupComplete && codexHealthy) {
            statusText = `Ready for everyday use. Active path: ${connectionLabel}.`;
            statusColor = 'var(--success-ink, #8dd7a5)';
            workspaceStatusLabel = 'Ready';
            workspaceStatusTone = 'ok';
            workspaceMetaText = `Everyday path is ready. Active connection: ${connectionLabel}.`;
        } else if (setupComplete && connectionMethod === 'codex' && !codexHealthy) {
            statusText = 'ChatGPT / Codex needs sign-in again. Open Settings or rerun Easy Setup to recover.';
            statusColor = 'var(--warning-ink, #f7c46b)';
            workspaceStatusLabel = 'Repair';
            workspaceStatusTone = 'warn';
            workspaceMetaText = 'Connection needs repair. Open Settings or rerun Easy Setup to recover.';
        }
        readinessStatus.textContent = statusText;
        readinessStatus.style.color = statusColor;
    }

    if (moduleWorkspaceModePill) {
        let border = 'rgba(247, 196, 107, 0.42)';
        let ink = 'var(--warning-ink, #f7c46b)';
        if (workspaceStatusTone === 'ok') {
            border = 'rgba(104, 212, 163, 0.42)';
            ink = 'var(--success-ink, #8dd7a5)';
        } else if (workspaceStatusTone === 'error') {
            border = 'rgba(255, 143, 143, 0.42)';
            ink = 'var(--danger-ink, #ffb4b4)';
        }
        moduleWorkspaceModePill.textContent = workspaceStatusLabel;
        moduleWorkspaceModePill.style.borderColor = border;
        moduleWorkspaceModePill.style.color = ink;
    }
    if (moduleWorkspaceMeta) {
        moduleWorkspaceMeta.textContent = workspaceMetaText;
    }
    const settingsSetupStatusNote = document.getElementById('settingsSetupStatusNote');
    if (settingsSetupStatusNote) {
        settingsSetupStatusNote.textContent = workspaceMetaText;
        settingsSetupStatusNote.style.color = workspaceStatusTone === 'ok'
            ? 'var(--success-ink, #8dd7a5)'
            : 'var(--text-secondary)';
    }
    const settingsBuilderModeHint = document.getElementById('settingsBuilderModeHint');
    if (settingsBuilderModeHint) {
        settingsBuilderModeHint.textContent = builderModeEnabled
            ? 'Builder controls are visible. Turn them off when you want the simpler everyday shell.'
            : 'Builder controls stay hidden until you need them.';
    }
    if (rerunEasySetupBtn) {
        rerunEasySetupBtn.textContent = setupComplete ? 'Rerun Easy Setup' : 'Continue Easy Setup';
    }

    renderWelcomeReadinessPills([
        {
            label: 'Setup',
            value: setupComplete ? 'Ready' : 'Needs setup',
            tone: setupComplete ? 'ok' : 'warn',
        },
        {
            label: 'Connection',
            value: connectionLabel,
            tone: setupComplete && codexHealthy ? 'ok' : 'warn',
        },
        {
            label: 'Memory',
            value: memoryEnabled ? 'On' : 'Off',
            tone: memoryEnabled ? 'ok' : 'warn',
        },
        {
            label: 'Builder',
            value: builderModeEnabled ? 'On' : 'Hidden',
            tone: builderModeEnabled ? 'ok' : 'warn',
        },
    ]);

    const primaryButton = document.getElementById('welcomeEasySetupBtn');
    if (primaryButton) {
        primaryButton.textContent = setupComplete ? 'Rerun Easy Setup' : 'Continue Setup';
    }

    const builderButton = document.getElementById('welcomeBuilderModeBtn');
    if (builderButton) {
        builderButton.textContent = builderModeEnabled ? 'Hide Builder Controls' : 'Show Builder Controls';
    }
}

function humanizeConnectionPath(pathRaw) {
    const path = safeString(pathRaw).toLowerCase();
    if (path === 'codex') return 'ChatGPT / Codex';
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
        if (tone === 'ok') {
            border = 'rgba(104, 212, 163, 0.38)';
            ink = 'var(--success-ink, #8dd7a5)';
        } else if (tone === 'error') {
            border = 'rgba(255, 143, 143, 0.38)';
            ink = 'var(--danger-ink, #ffb4b4)';
        } else if (tone === 'warn') {
            border = 'rgba(247, 196, 107, 0.38)';
            ink = 'var(--warning-ink, #f7c46b)';
        }
        pill.setAttribute(
            'style',
            [
                'display:inline-flex',
                'align-items:center',
                'gap:6px',
                'padding:6px 10px',
                'border-radius:999px',
                `border:1px solid ${border}`,
                'background:rgba(15, 23, 42, 0.34)',
                `color:${ink}`,
                'font-size:0.82rem',
            ].join(';')
        );
        pill.textContent = `${safeString(item?.label)}: ${safeString(item?.value)}`;
        pills.appendChild(pill);
    });
}

async function runUserFacingSetupRepairNow() {
    const repairBtn = document.getElementById('welcomeRepairBtn');
    if (repairBtn && repairBtn.dataset.busy === '1') return;
    if (repairBtn) {
        repairBtn.dataset.busy = '1';
        repairBtn.textContent = 'Repairing...';
        repairBtn.setAttribute('disabled', 'disabled');
    }

    const restoreButton = () => {
        if (!repairBtn) return;
        repairBtn.dataset.busy = '0';
        repairBtn.textContent = 'Repair Setup';
        repairBtn.removeAttribute('disabled');
    };

    const setStatus = (message, tone = 'warn') => {
        const readinessStatus = document.getElementById('welcomeReadinessStatus');
        if (!readinessStatus) return;
        readinessStatus.textContent = safeString(message);
        if (tone === 'ok') {
            readinessStatus.style.color = 'var(--success-ink, #8dd7a5)';
        } else if (tone === 'error') {
            readinessStatus.style.color = 'var(--danger-ink, #ffb4b4)';
        } else {
            readinessStatus.style.color = 'var(--warning-ink, #f7c46b)';
        }
    };

    setStatus('Running repair check. Thomas may ask for installer approval.', 'warn');

    try {
        const res = await fetchJsonSafe('/api/setup/repair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                auto_install_tools: true,
                skip_install: false,
                skip_doctor: false,
            }),
        });

        if (!res.ok || !res.data) {
            const reason = safeString(res.data?.error) || safeString(res.text) || 'Repair call failed.';
            setStatus(`Repair failed: ${reason}`, 'error');
            notifyUser(`Setup repair failed: ${reason}`, {
                tone: 'error',
                durationMs: 3200,
                debugKind: 'error',
            });
            return;
        }

        if (!Boolean(res.data?.ok)) {
            const errorMsg = safeString(res.data?.error) || `Repair exited with code ${res.data?.exit_code}.`;
            const stderrTail = safeString(res.data?.stderr_tail);
            const finalMsg = stderrTail ? `${errorMsg} ${stderrTail}` : errorMsg;
            setStatus(`Repair failed: ${finalMsg}`, 'error');
            notifyUser(`Setup repair failed: ${errorMsg}`, {
                tone: 'error',
                durationMs: 3200,
                debugKind: 'error',
            });
            return;
        }

        if (typeof refreshIdentityState === 'function') {
            await refreshIdentityState();
        }
        const reportPath = safeString(res.data?.report_path);
        const successText = reportPath
            ? `Repair completed. Report: ${reportPath}`
            : 'Repair completed successfully.';
        updateWelcomeSupportRail(loadStoredBuilderMode());
        setStatus(successText, 'ok');
        notifyUser('Setup repair completed.', {
            tone: 'success',
            durationMs: 2200,
            debugKind: 'setup',
        });
    } catch (error) {
        const reason = safeString(error?.message) || 'unknown repair error';
        setStatus(`Repair failed: ${reason}`, 'error');
        notifyUser(`Setup repair failed: ${reason}`, {
            tone: 'error',
            durationMs: 3200,
            debugKind: 'error',
        });
    } finally {
        restoreButton();
    }
}

function setBuilderMode(enabled, { persist = true, syncSettings = true } = {}) {
    const builderModeEnabled = Boolean(enabled);
    if (persist) {
        saveStoredBuilderMode(builderModeEnabled);
    }

    if (appRoot) {
        appRoot.classList.toggle('builder-mode-active', builderModeEnabled);
    }

    const builderButtons = Array.from(document.querySelectorAll('.sidebar-nav [data-nav-mode]'));
    builderButtons.forEach((button) => {
        button.classList.toggle('hidden', !builderModeEnabled);
        button.setAttribute('aria-hidden', builderModeEnabled ? 'false' : 'true');
    });

    const builderDivider = document.querySelector('.sidebar-nav-divider');
    if (builderDivider) {
        builderDivider.classList.toggle('hidden', !builderModeEnabled);
        builderDivider.setAttribute('aria-hidden', builderModeEnabled ? 'false' : 'true');
    }

    if (debugDockToggleBtn) {
        debugDockToggleBtn.classList.toggle('hidden', !builderModeEnabled);
        debugDockToggleBtn.setAttribute('aria-hidden', builderModeEnabled ? 'false' : 'true');
    }

    if (!builderModeEnabled) {
        if (typeof setDebugDockOpen === 'function') {
            setDebugDockOpen(false, { recordEvent: false });
        }
        if (sidebarNavMode === 'app_builder' || sidebarNavMode === 'marketplace') {
            ensureSettingsUiClosed();
            setSidebarNavMode('chat');
            setSidebarSearchScope('chat');
        }
    }

    if (syncSettings && settingsAdvancedToggle) {
        settingsAdvancedToggle.checked = builderModeEnabled;
    }
    if (settingsSuite) {
        settingsSuite.classList.toggle('advanced-mode', builderModeEnabled);
    }
    if (typeof updateSettingsSectionNavVisibility === 'function') {
        updateSettingsSectionNavVisibility();
    }

    ensureConnectionDefaultsShell(builderModeEnabled);
    updateWelcomeSupportRail(builderModeEnabled);
}

function ensureWelcomeSupportRail() {
    const welcomeScreen = document.getElementById('welcomeScreen');
    if (!welcomeScreen) return;

    let supportRail = document.getElementById('welcomeSupportRail');
    if (!supportRail) {
        supportRail = document.createElement('section');
        supportRail.id = 'welcomeSupportRail';
        supportRail.setAttribute(
            'style',
            [
                'margin-top:18px',
                'padding:16px',
                'border-radius:16px',
                'border:1px solid rgba(148, 163, 184, 0.22)',
                'background:rgba(15, 23, 42, 0.38)',
                'display:grid',
                'gap:12px',
                'max-width:860px',
            ].join(';')
        );
        supportRail.innerHTML = [
            '<div style="display:grid;gap:6px;">',
            '<strong style="font-size:0.98rem;">Safe by default</strong>',
            '<p id="welcomeSupportCopy" style="margin:0;color:var(--text-secondary);line-height:1.5;"></p>',
            '<p id="welcomeReadinessStatus" style="margin:0;color:var(--text-secondary);line-height:1.5;"></p>',
            '<div id="welcomeReadinessPills" style="display:flex;flex-wrap:wrap;gap:8px;"></div>',
            '</div>',
            '<div style="display:flex;flex-wrap:wrap;gap:10px;">',
            '<button type="button" class="btn-primary" id="welcomeEasySetupBtn">Run Easy Setup</button>',
            '<button type="button" class="settings-mini-btn" id="welcomeRepairBtn">Repair Setup</button>',
            '<button type="button" class="settings-mini-btn" id="welcomeSettingsBtn">Open Settings</button>',
            '<button type="button" class="settings-mini-btn" id="welcomeBuilderModeBtn">Show Builder Controls</button>',
            '</div>',
        ].join('');
        welcomeScreen.appendChild(supportRail);

        const welcomeEasySetupBtn = document.getElementById('welcomeEasySetupBtn');
        if (welcomeEasySetupBtn) {
            welcomeEasySetupBtn.addEventListener('click', async () => {
                await openEasySetup({ source: 'welcome_support', force: true, restart: true });
            });
        }

        const welcomeRepairBtn = document.getElementById('welcomeRepairBtn');
        if (welcomeRepairBtn) {
            welcomeRepairBtn.addEventListener('click', async () => {
                await runUserFacingSetupRepairNow();
            });
        }

        const welcomeSettingsBtn = document.getElementById('welcomeSettingsBtn');
        if (welcomeSettingsBtn) {
            welcomeSettingsBtn.addEventListener('click', () => {
                if (settingsBtn) settingsBtn.click();
            });
        }

        const welcomeBuilderModeBtn = document.getElementById('welcomeBuilderModeBtn');
        if (welcomeBuilderModeBtn) {
            welcomeBuilderModeBtn.addEventListener('click', () => {
                setBuilderMode(!loadStoredBuilderMode());
            });
        }
    }
}

function ensureSettingsEverydaySupport() {
    const settingsHeading = document.querySelector('#settingsModal .settings-suite-left h2');
    if (settingsHeading) {
        settingsHeading.textContent = 'Settings';
    }

    const advancedToggleWrap = document.querySelector('#settingsModal .advanced-toggle-wrap');
    const advancedToggleLabel = advancedToggleWrap?.querySelector('span');
    if (advancedToggleLabel) {
        advancedToggleLabel.textContent = 'Builder Controls';
    }
    if (advancedToggleWrap && !document.getElementById('settingsBuilderModeHint')) {
        const hint = document.createElement('div');
        hint.id = 'settingsBuilderModeHint';
        hint.className = 'settings-inline-note';
        hint.setAttribute('style', 'max-width:22ch;line-height:1.35;');
        advancedToggleWrap.appendChild(hint);
    }

    const sections = Array.from(document.querySelectorAll('#settingsSections .settings-section'));
    const headingText = (section) => safeString(section?.querySelector('.settings-section-head h3')?.textContent).trim().toLowerCase();

    const everydaySection = sections.find((section) => new Set(['basic', 'everyday defaults']).has(headingText(section)));
    if (everydaySection) {
        const title = everydaySection.querySelector('.settings-section-head h3');
        const copy = everydaySection.querySelector('.settings-section-head p');
        if (title) title.textContent = 'Everyday Defaults';
        if (copy) copy.textContent = 'Keep Thomas calm, useful, and safe for regular daily use.';
    }

    const setupSection = sections.find((section) => new Set(['onboarding', 'setup and repair']).has(headingText(section)));
    if (!setupSection) return;
    const setupTitle = setupSection.querySelector('.settings-section-head h3');
    const setupCopy = setupSection.querySelector('.settings-section-head p');
    if (setupTitle) setupTitle.textContent = 'Setup And Repair';
    if (setupCopy) {
        setupCopy.textContent = 'Reconnect providers, rerun Easy Setup, or repair the guarded path Thomas uses for everyday work.';
    }

    const actions = setupSection.querySelector('.settings-inline-actions');
    if (!actions) return;
    if (!document.getElementById('settingsRepairSetupBtn')) {
        const repairBtn = document.createElement('button');
        repairBtn.type = 'button';
        repairBtn.id = 'settingsRepairSetupBtn';
        repairBtn.className = 'settings-mini-btn';
        repairBtn.textContent = 'Repair Setup';
        repairBtn.addEventListener('click', async () => {
            await runUserFacingSetupRepairNow();
        });
        const tip = actions.querySelector('.settings-inline-note');
        if (tip) {
            actions.insertBefore(repairBtn, tip);
        } else {
            actions.appendChild(repairBtn);
        }
    }
    if (!document.getElementById('settingsSetupStatusNote')) {
        const statusNote = document.createElement('p');
        statusNote.id = 'settingsSetupStatusNote';
        statusNote.className = 'settings-inline-note';
        statusNote.style.marginTop = '10px';
        setupSection.appendChild(statusNote);
    }
}

function ensureConnectionDefaultsShell(builderModeEnabled = false) {
    if (modelSetupBtn) {
        modelSetupBtn.title = 'Connection and defaults';
        modelSetupBtn.setAttribute('aria-label', 'Open connection and defaults');
    }
    if (modelSetupCurrentLabel && safeString(modelSetupCurrentLabel.textContent).trim().toLowerCase() === 'loading...') {
        modelSetupCurrentLabel.textContent = 'Connection loading...';
    }

    const modalHeading = document.querySelector('#modelSetupModal .modal-header h2');
    if (modalHeading) {
        modalHeading.textContent = 'Connection And Defaults';
    }
    const modalBody = document.querySelector('#modelSetupModal .modal-body');
    if (modalBody && !document.getElementById('modelSetupEverydaySupport')) {
        const support = document.createElement('div');
        support.id = 'modelSetupEverydaySupport';
        support.setAttribute(
            'style',
            [
                'display:grid',
                'gap:8px',
                'margin-bottom:14px',
                'padding:12px 14px',
                'border-radius:14px',
                'border:1px solid rgba(148, 163, 184, 0.18)',
                'background:rgba(15, 23, 42, 0.28)',
            ].join(';')
        );
        support.innerHTML = [
            '<p id="modelSetupEverydayCopy" style="margin:0;color:var(--text-secondary);line-height:1.45;"></p>',
            '<div style="display:flex;flex-wrap:wrap;gap:8px;">',
            '<button type="button" class="settings-mini-btn" id="modelSetupEasySetupBtn">Use Easy Setup</button>',
            '</div>',
        ].join('');
        modalBody.prepend(support);
        const easySetupBtn = document.getElementById('modelSetupEasySetupBtn');
        if (easySetupBtn) {
            easySetupBtn.addEventListener('click', async () => {
                if (modelSetupModal) modelSetupModal.style.display = 'none';
                await openEasySetup({ source: 'model_setup_shell', force: true, restart: true });
            });
        }
    }
    const supportCopy = document.getElementById('modelSetupEverydayCopy');
    if (supportCopy) {
        supportCopy.textContent = builderModeEnabled
            ? 'Builder controls are visible. Connection, memory, and task defaults still drive Thomas for everyday use.'
            : 'Pick the connection Thomas uses by default. Use Easy Setup when you want guided verification and repair.';
    }

    const providerLabel = document.querySelector('label[for="setupProviderSelector"]');
    if (providerLabel) providerLabel.textContent = 'Connection';
    const modelLabel = document.querySelector('label[for="setupModelSelector"]');
    if (modelLabel) modelLabel.textContent = builderModeEnabled ? 'Specific Model' : 'Specific Model (Builder)';
    const reasoningLabel = document.querySelector('#setupReasoningGroup label');
    if (reasoningLabel) reasoningLabel.textContent = 'Reasoning Depth';
    const personalityLabel = document.querySelector('label[for="setupPersonalitySelector"]');
    if (personalityLabel) personalityLabel.textContent = 'Response Style';
    const customPromptLabel = document.querySelector('label[for="setupCustomPrompt"]');
    if (customPromptLabel) customPromptLabel.textContent = 'Custom Style Instructions';
    const autonomyLabel = document.querySelector('#setupAutonomyGroup')?.closest('.form-group')?.querySelector('label');
    if (autonomyLabel) autonomyLabel.textContent = 'Task Initiative';
    const economyLabel = document.querySelector('#setupEconomyGroup')?.closest('.form-group')?.querySelector('label');
    if (economyLabel) economyLabel.textContent = 'Speed Vs Quality';
    const memoryStrong = document.querySelector('#setupMemoryToggle')?.closest('.switch-group')?.querySelector('.switch-label strong');
    if (memoryStrong) memoryStrong.textContent = 'Memory';
    const memoryCopy = document.querySelector('#setupMemoryToggle')?.closest('.switch-group')?.querySelector('.switch-label span');
    if (memoryCopy) memoryCopy.textContent = 'Remember context between chats.';
    if (restartServerBtn) {
        restartServerBtn.textContent = 'Restart Thomas';
        restartServerBtn.title = 'Restart Thomas';
    }
    if (applyModelSetupBtn) {
        applyModelSetupBtn.textContent = 'Save Defaults';
    }
    const showAllProviders = document.getElementById('setupShowAllProviders');
    if (showAllProviders) {
        showAllProviders.textContent = 'Show all builder profiles';
    }
    if (setupModelOverrideGroup) {
        setupModelOverrideGroup.classList.toggle('hidden', !builderModeEnabled);
    }
    const reasoningGroup = document.getElementById('setupReasoningGroup');
    if (reasoningGroup && !builderModeEnabled) {
        reasoningGroup.style.display = 'none';
    }
}

function ensureChatEverydaySupport() {
    if (globalSearchInput && safeString(globalSearchInput.placeholder).trim().toLowerCase() === 'search chats') {
        globalSearchInput.placeholder = 'Find past chats';
    }
    if (sidebarSearchModeLabel && safeString(sidebarSearchModeLabel.textContent).trim().toLowerCase() === 'search chats') {
        sidebarSearchModeLabel.textContent = 'Find past chats';
    }

    const chatSearchInput = document.getElementById('chatSearchInput');
    if (chatSearchInput) {
        chatSearchInput.placeholder = 'Find messages in this chat';
    }

    const taskTitle = document.querySelector('#taskContinuityPanel .task-continuity-title');
    if (taskTitle) {
        taskTitle.textContent = 'Current Task';
    }
    if (taskContinuityRefreshBtn) {
        taskContinuityRefreshBtn.title = 'Refresh task status';
    }
    if (taskContinuityStatusPill && safeString(taskContinuityStatusPill.textContent).trim().toLowerCase() === 'in_progress') {
        taskContinuityStatusPill.textContent = 'Idle';
    }
    if (taskContinuityGoal && safeString(taskContinuityGoal.textContent).trim().toLowerCase() === 'no active task tracked yet.') {
        taskContinuityGoal.textContent = 'No active task yet. Start with a question or describe something you want done.';
    }
    if (taskContinuityProgress && safeString(taskContinuityProgress.textContent).trim().toLowerCase() === 'waiting for first update.') {
        taskContinuityProgress.textContent = 'Thomas will show progress and blockers here when a task is running.';
    }

    if (assistantSuggestionTitle && safeString(assistantSuggestionTitle.textContent).trim().toLowerCase() === 'suggestions') {
        assistantSuggestionTitle.textContent = 'Try asking';
    }

    if (composerTextarea) {
        const placeholderTemplate = 'Message {{agent}}';
        const placeholder = typeof withAgentName === 'function'
            ? withAgentName(placeholderTemplate)
            : placeholderTemplate.replace('{{agent}}', 'Thomas');
        composerTextarea.placeholder = placeholder;
        composerTextarea.setAttribute('data-agent-placeholder-template', placeholderTemplate);
    }
}

function applyProductShellCopy() {
    const sidebarDivider = document.querySelector('.sidebar-nav-divider');
    if (sidebarDivider) {
        sidebarDivider.textContent = 'Build And Extend';
    }

    const welcomeSubtitle = document.querySelector('#welcomeScreen .welcome-subtitle');
    if (welcomeSubtitle) {
        welcomeSubtitle.textContent = 'Start with chat. Add memory, tools, and automation when you are ready.';
    }

    const welcomeCardCopy = [
        {
            prompt: 'Help me plan my day and turn it into a checklist I can actually follow.',
            title: 'Plan my day',
            desc: 'Turn ideas into a clear checklist with next steps',
        },
        {
            prompt: 'Search the web for the latest AI news and summarize the top three stories in plain English.',
            title: 'Research something',
            desc: 'Look things up, compare options, and summarize what matters',
        },
        {
            prompt: 'Help me organize the files in my current directory into clear folders by type.',
            title: 'Organize files',
            desc: 'Sort, rename, and clean up files without guesswork',
        },
        {
            prompt: 'Show me how to start simple with Thomas, then add memory and automation only when I need them.',
            title: 'Grow safely',
            desc: 'Add memory, tools, or automation one step at a time',
        },
    ];
    const welcomeCards = Array.from(document.querySelectorAll('#welcomeScreen .welcome-card'));
    welcomeCards.forEach((card, index) => {
        const next = welcomeCardCopy[index];
        if (!next) return;
        card.setAttribute('data-prompt', next.prompt);
        const title = card.querySelector('.welcome-card-title');
        const desc = card.querySelector('.welcome-card-desc');
        if (title) title.textContent = next.title;
        if (desc) desc.textContent = next.desc;
    });

    const moduleWorkspaceSubtitle = document.getElementById('moduleWorkspaceSubtitle');
    if (moduleWorkspaceSubtitle) {
        moduleWorkspaceSubtitle.textContent = 'Start with what matters now. Open deeper control surfaces only when you need them.';
    }

    const step1Title = document.querySelector('#easySetupStep1 h3');
    if (step1Title) {
        step1Title.textContent = 'Start with a safe connection';
    }
    const step1Copy = document.getElementById('easySetupConnectionPathCopy');
    if (step1Copy) {
        const connectionCopy = 'Pick the simplest safe connection for {{agent}}. Thomas verifies it before unlocking chat, memory, or automation.';
        step1Copy.textContent = connectionCopy.replace('{{agent}}', 'Thomas');
        step1Copy.setAttribute('data-agent-template', connectionCopy);
    }

    const codexPathCard = document.querySelector('#easySetupPathGrid [data-path="codex"] span');
    if (codexPathCard) {
        codexPathCard.textContent = 'Fastest guided start with ChatGPT sign-in and Codex access.';
    }
    const manualPathCard = document.querySelector('#easySetupPathGrid [data-path="manual"] span');
    if (manualPathCard) {
        manualPathCard.textContent = 'Bring your own provider key and verify it before Thomas uses it.';
    }
    const localPathCard = document.querySelector('#easySetupPathGrid [data-path="local"] span');
    if (localPathCard) {
        localPathCard.textContent = 'Keep models on this machine with a locally verified Ollama setup.';
    }

    const step2Title = document.querySelector('#easySetupStep2 h3');
    if (step2Title) {
        step2Title.textContent = 'Verify your setup';
    }
    const step2Copy = document.querySelector('#easySetupStep2 .easy-setup-step-head p');
    if (step2Copy) {
        step2Copy.textContent = 'Thomas checks the selected path before it unlocks chat, memory, and automation.';
    }
    const codexNote = document.querySelector('#easySetupCodexBlock .easy-setup-note');
    if (codexNote) {
        codexNote.textContent = 'Thomas checks sign-in, confirms model access, and validates a Codex profile.';
    }
    const localNote = document.querySelector('#easySetupLocalBlock .easy-setup-note');
    if (localNote) {
        localNote.textContent = 'Thomas checks Ollama reachability first, then validates the local profile.';
    }
    const testConnectionButton = document.getElementById('easySetupTestConnectionBtn');
    if (testConnectionButton) {
        testConnectionButton.textContent = 'Verify connection';
    }

    const step4Title = document.querySelector('#easySetupStep4 h3');
    if (step4Title) {
        step4Title.textContent = 'Ready for everyday use';
    }
    const step4Copy = document.querySelector('#easySetupStep4 .easy-setup-step-head p');
    if (step4Copy) {
        step4Copy.textContent = 'Your connection is verified. Continue in chat for a short personalization pass, or finish and start using Thomas.';
    }
    const step4Note = document.querySelector('#easySetupStep4 .easy-setup-note');
    if (step4Note) {
        step4Note.textContent = 'You can personalize more later. Builder controls stay available when you want them.';
    }

    ensureConnectionDefaultsShell(loadStoredBuilderMode());
    ensureSettingsEverydaySupport();
    ensureWelcomeSupportRail();
    ensureChatEverydaySupport();

    if (settingsAdvancedToggle && !settingsAdvancedToggle.dataset.builderModeBound) {
        settingsAdvancedToggle.dataset.builderModeBound = '1';
        settingsAdvancedToggle.addEventListener('change', () => {
            setBuilderMode(Boolean(settingsAdvancedToggle.checked), { syncSettings: false });
        });
    }

    setBuilderMode(loadStoredBuilderMode(), { persist: false });
}

function init() {
    if (appRoot) {
        appRoot.classList.remove('debug-dock-open');
        appRoot.classList.remove('settings-active');
        appRoot.classList.remove('chat-game-open');
    }
    if (settingsModal) {
        settingsModal.classList.add('hidden');
    }
    initComposer();
    initActions();
    initChatSearch();
    initChatGame();
    initFeatures();
    initEasySetup();
    applyProductShellCopy();
    loadInitialState()
        .then(() => {
            updateWelcomeSupportRail(loadStoredBuilderMode());
        })
        .catch((error) => {
            console.error('Boot initialization failed', error);
            updateWelcomeSupportRail(loadStoredBuilderMode());
            notifyUser('Thomas had trouble loading. Retrying startup tasks.', {
                tone: 'warning',
                durationMs: 2600,
                debugKind: 'error',
            });
        });
    initComposerDeepLink();
    syncChatComposerOffset();
    window.addEventListener('resize', () => syncChatComposerOffset(), { passive: true });
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => syncChatComposerOffset());
    }
    if (composerContainer && 'ResizeObserver' in window) {
        const resizeObs = new ResizeObserver(() => syncChatComposerOffset());
        resizeObs.observe(composerContainer);
    }
}

function syncChatComposerOffset() {
    if (!(chatMessagesInner instanceof HTMLElement) || !(composerContainer instanceof HTMLElement)) return;
    const rect = composerContainer.getBoundingClientRect();
    const offset = Math.max(200, Math.ceil(rect.height) + 34);
    chatMessagesInner.style.setProperty('--composer-offset', `${offset}px`);
}

/**
 * Composer behaviors: Auto-expand, Enter-to-send
 */
function composerSyncSendButtonState() {
    if (isGenerating) return;
    const canSend = composerTextarea.value.trim().length > 0 || pendingDocs.length > 0 || pendingImages.length > 0;
    sendBtn.disabled = !canSend;
    sendBtn.style.color = canSend ? 'var(--text-primary)' : '';
}

function initComposer() {
    composerTextarea.addEventListener('input', () => {
        // Auto-resize
        composerTextarea.style.height = 'auto';
        composerTextarea.style.height = (composerTextarea.scrollHeight) + 'px';

        // Toggle send button state
        composerSyncSendButtonState();

        // Slash command palette
        _updateSlashPalette();
        syncChatComposerOffset();
    });

    composerTextarea.addEventListener('keydown', (e) => {
        // Slash palette navigation
        if (_slashPaletteVisible) {
            if (e.key === 'ArrowDown') { e.preventDefault(); _slashPaletteNav(1); return; }
            if (e.key === 'ArrowUp') { e.preventDefault(); _slashPaletteNav(-1); return; }
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _slashPaletteSelect(); return; }
            if (e.key === 'Escape') { e.preventDefault(); _hideSlashPalette(); return; }
            if (e.key === 'Tab') { e.preventDefault(); _slashPaletteSelect(); return; }
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) {
                sendBtn.click();
            }
        }
    });

    // â”€â”€ Paste images from clipboard â”€â”€
    composerTextarea.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (!file) continue;
                const reader = new FileReader();
                reader.onload = (re) => {
                    pendingImages.push({ data_url: re.target.result, name: file.name || 'pasted-image.png' });
                    renderAttachmentsPreview();
                    composerSyncSendButtonState();
                    showToast('Image pasted');
                };
                reader.readAsDataURL(file);
                break; // only handle first image
            }
        }
    });

    // â”€â”€ Drag-and-drop files onto composer â”€â”€
    const composerArea = composerTextarea.closest('.composer') || composerTextarea.parentElement;
    if (composerArea) {
        let _dragCounter = 0;

        // Create drop overlay
        const dropOverlay = document.createElement('div');
        dropOverlay.className = 'composer-drop-overlay';
        dropOverlay.innerHTML = '<span><i class="ph ph-upload-simple"></i> Drop files here</span>';
        composerArea.style.position = composerArea.style.position || 'relative';
        composerArea.appendChild(dropOverlay);

        composerArea.addEventListener('dragenter', (e) => {
            e.preventDefault();
            _dragCounter++;
            dropOverlay.classList.add('visible');
        });
        composerArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            _dragCounter--;
            if (_dragCounter <= 0) {
                _dragCounter = 0;
                dropOverlay.classList.remove('visible');
            }
        });
        composerArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });
        composerArea.addEventListener('drop', async (e) => {
            e.preventDefault();
            _dragCounter = 0;
            dropOverlay.classList.remove('visible');

            const files = e.dataTransfer?.files;
            if (!files || files.length === 0) return;

            for (const file of files) {
                if (file.type.startsWith('image/')) {
                    const reader = new FileReader();
                    reader.onload = (re) => {
                        pendingImages.push({ data_url: re.target.result, name: file.name });
                        renderAttachmentsPreview();
                        composerSyncSendButtonState();
                    };
                    reader.readAsDataURL(file);
                } else {
                    try {
                        const text = await file.text();
                        pendingDocs.push({ name: file.name, text: text });
                        renderAttachmentsPreview();
                        composerSyncSendButtonState();
                    } catch (err) {
                        console.warn('Failed to read dropped file:', err);
                    }
                }
            }
            showToast(`${files.length} file(s) attached`);
        });
    }
}

// â”€â”€ Slash Command Palette â”€â”€
const SLASH_COMMANDS = [
    { cmd: '/research',  desc: 'Deep research mode â€” thorough web search + synthesis' },
    { cmd: '/image',     desc: 'Generate an image from a description' },
    { cmd: '/code',      desc: 'Code-focused mode â€” programming assistance' },
    { cmd: '/write',     desc: 'Writing mode â€” essays, emails, creative text' },
    { cmd: '/analyze',   desc: 'Analyze documents, data, or complex topics' },
    { cmd: '/status',    desc: 'Show live engine status and runtime details' },
    { cmd: '/issues',    desc: 'Run code issue detection and automated fixes' },
    { cmd: '/upgrade',   desc: 'Run self-upgrade engine cycle' },
    { cmd: '/sync',      desc: 'Run workspace sync cycle (commit / housekeeping)' },
    { cmd: '/ui-audit',  desc: 'Run UI workflow review and polish checks' },
    { cmd: '/clear',     desc: 'Clear the conversation and start fresh' },
    { cmd: '/export',    desc: 'Export this conversation as markdown or JSON' },
    { cmd: '/help',      desc: 'Show available commands and keyboard shortcuts' },
