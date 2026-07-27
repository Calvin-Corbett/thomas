// Extracted from part-004.js
// From errormsg

    if (!Boolean(res.data?.ok)) {
        const errorMsg = safeString(res.data?.error) || `Repair exited with code ${res.data?.exit_code}.`;
        const stderrTail = safeString(res.data?.stderr_tail);
        const finalMsg = stderrTail ? `${errorMsg}\n${stderrTail}` : errorMsg;
        setEasySetupStatus(easySetupDependencyStatus, `${finalMsg} Remediation: approve prompts and retry.`, 'error');
        emitOnboardingTelemetry('wizard.download_approval_failed', {
            trigger,
            error: errorMsg,
        });
        return false;
    }

    const reportPath = safeString(res.data?.report_path);
    setEasySetupStatus(
        easySetupDependencyStatus,
        reportPath
            ? `Repair completed. Report: ${reportPath}`
            : 'Repair completed successfully.',
        'ok'
    );
    emitOnboardingTelemetry('wizard.download_approved', {
        trigger,
        report_path: reportPath,
    });
    return true;
}

async function handleEasySetupApproveAll() {
    const ok = await runEasySetupRepair('approve_all');
    if (!ok) return;
    try {
        await loadEasySetupBootstrap();
    } catch {
        // Ignore refresh failures; keep existing plan.
    }
    easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
    easySetupState.dependenciesAction = 'approved';
    renderEasySetupDependencies();
    renderEasySetupReviewPanel();
    updateEasySetupNavigation();
    await persistOnboardingPrefs({
        current_step: 'downloads',
        answers: { dependency_action: 'approved' },
    });
}

function handleEasySetupReviewDownloads() {
    if (!easySetupReviewPanel) return;
    renderEasySetupReviewPanel();
    easySetupReviewPanel.classList.toggle('hidden');
}

async function handleEasySetupNext() {
    if (easySetupState.step === 1) {
        if (!safeString(easySetupState.selectedPath)) {
            setEasySetupStatus(easySetupConnectionStatus, 'Select a connection path first.', 'error');
            return;
        }
        setEasySetupStep(2);
        await persistOnboardingPrefs({ current_step: 'connect', dismissed_at: null });
        emitOnboardingTelemetry('wizard.step_advanced', { step: 'connect', path: easySetupState.selectedPath });
        return;
    }

    if (easySetupState.step === 2) {
        if (!easySetupState.verified) {
            setEasySetupStatus(
                easySetupConnectionStatus,
                'Connection must verify before continuing. Use "Verify connection".',
                'error'
            );
            return;
        }
        easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
        setEasySetupStep(3);
        await persistOnboardingPrefs({ current_step: 'downloads' });
        emitOnboardingTelemetry('wizard.step_advanced', { step: 'downloads', path: easySetupState.selectedPath });
        return;
    }

    if (easySetupState.step === 3) {
        const missing = missingRequiredDependencies(easySetupState.dependencyPlan).length;
        if (missing > 0 && safeString(easySetupState.dependenciesAction) === 'pending') {
            setEasySetupStatus(
                easySetupDependencyStatus,
                'Approve required downloads before continuing.',
                'error'
            );
            return;
        }
        setEasySetupStep(4);
        await persistOnboardingPrefs({ current_step: 'brain_ready' });
        emitOnboardingTelemetry('wizard.step_advanced', { step: 'brain_ready', path: easySetupState.selectedPath });
        return;
    }

    closeEasySetup();
    ensureChatVisible();
    beginOnboardingInterview();
}

async function handleEasySetupBack() {
    if (easySetupState.step <= 1) return;
    setEasySetupStep(easySetupState.step - 1);
    await persistOnboardingPrefs({ current_step: easySetupStepName(easySetupState.step) });
}

function initEasySetup() {
    if (!easySetupModal) return;

    if (easySetupDismissBtn) {
        easySetupDismissBtn.textContent = 'Skip for now';
        easySetupDismissBtn.classList.remove('hidden');
    }
    if (easySetupCloseBtn) {
        easySetupCloseBtn.classList.add('hidden');
    }

    if (easySetupPathGrid) {
        easySetupPathGrid.querySelectorAll('[data-path]').forEach((btn) => {
            btn.addEventListener('click', () => {
                handleEasySetupPathSelect(btn.getAttribute('data-path'));
            });
        });
    }

    if (easySetupCloseBtn) easySetupCloseBtn.addEventListener('click', () => requestEasySetupClose('close_button'));
    if (easySetupBackdrop) easySetupBackdrop.addEventListener('click', () => requestEasySetupClose('backdrop'));
    if (easySetupDismissBtn) easySetupDismissBtn.addEventListener('click', () => requestEasySetupClose('footer_skip'));
    if (easySetupBackBtn) {
        easySetupBackBtn.addEventListener('click', () => {
            handleEasySetupBack();
        });
    }
    if (easySetupNextBtn) {
        easySetupNextBtn.addEventListener('click', () => {
            handleEasySetupNext();
        });
    }
    if (easySetupTestConnectionBtn) {
        easySetupTestConnectionBtn.addEventListener('click', () => {
            handleEasySetupConnectionTest();
        });
    }
    if (easySetupAutoRepairBtn) {
        easySetupAutoRepairBtn.addEventListener('click', async () => {
            const ok = await runEasySetupRepair('connect_step');
            if (ok) {
                try {
                    await loadEasySetupBootstrap();
                } catch {
                    // Best effort only.
                }
                easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
                renderEasySetupDependencies();
                updateEasySetupNavigation();
            }
        });
    }
    if (easySetupApproveAllBtn) {
        easySetupApproveAllBtn.addEventListener('click', () => {
            handleEasySetupApproveAll();
        });
    }
    if (easySetupReviewDownloadsBtn) easySetupReviewDownloadsBtn.addEventListener('click', handleEasySetupReviewDownloads);
    if (rerunEasySetupBtn) {
        rerunEasySetupBtn.addEventListener('click', async () => {
            if (isSettingsScreenOpen()) closeSettingsModal();
            await openEasySetup({ source: 'settings', force: true, restart: true });
        });
    }

    syncEasySetupConnectionBlocks();
    setEasySetupStatus(easySetupConnectionStatus, 'Choose a path, then verify it.');
    setEasySetupDependencyDefaultStatus();
    setEasySetupStep(1);
}

function renderOnboardingChoiceBubble(prompt, options, onChoose) {
    if (safeString(prompt)) {
        renderMessage({ role: 'assistant', content: prompt });
    }
    setAssistantSuggestions({
        title: 'Onboarding choices',
        context: 'onboarding',
        dismissible: false,
        options: (options || []).map((option) => ({
            ...option,
            keep_after_choose: false,
            onChoose: async () => {
                if (typeof onChoose === 'function') {
                    await onChoose(option);
                }
            },
        })),
    });
}

function deriveOnboardingDefaults(answers) {
    const experience = safeString(answers?.experience) || 'builder';
    const autonomyPref = safeString(answers?.autonomy) || 'balanced';
    const costPref = safeString(answers?.cost_quality) || 'balanced';
    const memoryPref = safeString(answers?.memory) || 'remember';
    const personalityPref = safeString(answers?.personality) || 'balanced';
    const workflowPref = safeString(answers?.workflow) || 'build_features';
    const togglesPref = safeString(answers?.default_toggles) || 'safe_defaults';

    let autonomyLevel = 2;
    if (experience === 'new') autonomyLevel = 1;
    if (experience === 'expert') autonomyLevel = 4;
    if (autonomyPref === 'guided') autonomyLevel -= 1;
    if (autonomyPref === 'aggressive') autonomyLevel += 1;
    autonomyLevel = Math.max(1, Math.min(4, autonomyLevel));

    let tokenEconomy = 'optimal';
    if (costPref === 'low_cost') tokenEconomy = 'cheap';
    if (costPref === 'max_quality') tokenEconomy = 'max';

    const memoryEnabled = memoryPref === 'remember';
    const sessionOnlyMemory = memoryPref === 'session_only';
    const requireCommandApproval = togglesPref === 'safe_defaults' || workflowPref === 'ops_reliability';
    const allowNetwork = togglesPref !== 'safe_defaults';
    const showTokenMeter = togglesPref === 'power_mode';
    const debugPanelEnabled = togglesPref === 'power_mode';
    const desktopNotifications = togglesPref !== 'quiet_mode';
    const showTimestamps = personalityPref === 'direct_technical' || workflowPref === 'ops_reliability';
    const uiDensity = togglesPref === 'power_mode' ? 'compact' : 'comfortable';
    const defaultMode = workflowPref === 'research' ? 'thinking' : 'auto';
    let profileType = 'adaptive';
    if (experience === 'new' || personalityPref === 'calm_guide') profileType = 'non_coder';
    if (experience === 'expert' || personalityPref === 'direct_technical') profileType = 'coder';

    return {
        autonomyLevel,
        tokenEconomy,
        memoryEnabled,
        sessionOnlyMemory,
        requireCommandApproval,
        allowNetwork,
        showTokenMeter,
        debugPanelEnabled,
        desktopNotifications,
        showTimestamps,
        uiDensity,
        defaultMode,
        profileType,
    };
}

async function applyOnboardingCompletion({ skippedInterview = false } = {}) {
    const onboardingAnswers = {
        ...(getOnboardingFromPrefs()?.answers || {}),
        ...(easySetupState.interviewAnswers || {}),
        interview_skipped: Boolean(skippedInterview),
        connection_path: safeString(easySetupState.selectedPath),
        dependency_action: safeString(easySetupState.dependenciesAction) || 'pending',
    };
    const derived = deriveOnboardingDefaults(onboardingAnswers);
    const completedAt = onboardingNowIso();

    const patch = {
        autonomy: { default_level: `L${derived.autonomyLevel}` },
        memory: { enabled_global: derived.memoryEnabled },
        notifications: { desktop: derived.desktopNotifications },
        profile: { profile_type: derived.profileType },
        advanced: {
            runtime: {
                default_mode: derived.defaultMode,
                default_token_economy: derived.tokenEconomy,
            },
            tools: {
                require_command_approval: derived.requireCommandApproval,
                allow_network: derived.allowNetwork,
            },
            interface: {
                show_timestamps: derived.showTimestamps,
                show_token_meter: derived.showTokenMeter,
                debug_panel_enabled: derived.debugPanelEnabled,
                ui_density: derived.uiDensity,
            },
        },
        onboarding: {
            setup_completed: true,
            version: ONBOARDING_VERSION,
            completed_at: completedAt,
            dismissed_at: null,
            current_step: 'completed',
            connection_method: safeString(easySetupState.selectedPath) || null,
            dependency_plan: {
                path: safeString(easySetupState.selectedPath),
                items: Array.isArray(easySetupState.dependencyPlan) ? easySetupState.dependencyPlan : [],
            },
            answers: onboardingAnswers,
        },
    };

    const res = await fetch('/api/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
    });
    if (!res.ok) {
        const reason = await res.text();
        throw new Error(reason || `Failed to finalize onboarding (${res.status})`);
    }
    currentPreferences = await res.json();

    if (derived.sessionOnlyMemory && sessionId) {
        await fetch(`/api/preferences?thread_id=${encodeURIComponent(sessionId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ memory: { thread_enabled: true } }),
        }).catch(() => { });
    }

    activeAutonomyLevel = derived.autonomyLevel;
    activeTokenEconomy = derived.tokenEconomy === 'optimal' ? 'balanced' : derived.tokenEconomy;
    activeChatMode = normalizeChatMode(derived.defaultMode) || 'auto';
    setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
    setSegmentedControlSelection('setupEconomyGroup', activeTokenEconomy);
    if (settingAdvDefaultMode) settingAdvDefaultMode.value = activeChatMode;
    if (setupMemoryToggle) setupMemoryToggle.checked = Boolean(currentPreferences?.memory?.enabled_global);
    if (settingMemoryEnabled) settingMemoryEnabled.checked = Boolean(currentPreferences?.memory?.enabled_global);
    if (typeof updateWelcomeSupportRail === 'function') {
        updateWelcomeSupportRail(loadStoredBuilderMode());
    }
    updateSidebarIdentity();
    easySetupState.interviewStarted = false;
    easySetupState.interviewStage = 'idle';
    easySetupState.interviewIndex = -1;
    hideAssistantSuggestions({ force: true });
    showStarterSuggestionRail({ force: true });

    emitOnboardingTelemetry('completed', {
        skipped_interview: Boolean(skippedInterview),
        connection_method: safeString(easySetupState.selectedPath),
        autonomy_level: derived.autonomyLevel,
        token_economy: derived.tokenEconomy,
    });
}

function buildSetupSafetyMessage() {
    return [
        'Fair concern. Setup is designed to be explicit and user-controlled:',
        withAgentName('- No silent installs: {{agent}} only runs dependency installs after your approval.'),
        '- Dependency step shows why each tool is needed and where it comes from.',
        '- You can choose the lowest-download path: Manual API Key.',
        '- Safe defaults keep command approval on so actions stay supervised.',
