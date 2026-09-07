// easy_setup_connection_flow.js - the Easy Setup wizard's profile activation,
// connection test, repair, approval and step navigation handlers.
//
// Moved verbatim out of 007_easy_setup_onboarding_05.js, which sat at 1340
// lines against the 1200-line hard limit. Runtime scripts are classic scripts
// sharing one global scope and are all loaded before the runtime is ready, so
// the handlers here keep every name they call from the earlier files.

async function activateEasySetupProfile() {
    const profile = resolveEasySetupSelectedProfile();
    if (!profile) return;
    const modelId = resolveEasySetupSelectedModelId(profile);

    // Immediate in-memory + UI state (so the label flips before the round-trip).
    if (modelId) activeModelOverride = modelId;
    if (setupProviderSelector) setupProviderSelector.value = profile;
    if (modelSelector) modelSelector.value = profile;
    try { window.localStorage.setItem('thomas_active_profile', profile); } catch (_) {}
    if (modelId) {
        try { window.localStorage.setItem('thomas_active_model_id', modelId); } catch (_) {}
    }

    try {
        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                advanced: {
                    model: {
                        active_profile: profile,
                        model_id: modelId || safeString(currentPreferences?.advanced?.model?.model_id),
                    },
                },
            }),
        });
        if (res.ok) {
            try { currentPreferences = await res.json(); } catch (_) {}
        }
    } catch (e) {
        console.error('Failed to activate easy-setup profile', e);
    }

    // Refresh model state + every user-facing label so the new model shows now.
    try { await fetchModels(); } catch (_) {}
    if (modelSetupCurrentLabel) modelSetupCurrentLabel.textContent = _profileHeaderLabel(profile);
    try { renderChatComposerSubbar(); } catch (_) {}
    try { updateSetupProviderPickerButton(profile); } catch (_) {}
}

async function persistOnboardingPrefs(overrides = {}) {
    const existing = getOnboardingFromPrefs();
    const mergedAnswers = {
        ...(existing.answers || {}),
        ...(easySetupState.interviewAnswers || {}),
        ...(overrides.answers || {}),
        connection_path: safeString(easySetupState.selectedPath),
        dependency_action: safeString(easySetupState.dependenciesAction) || 'pending',
        animation_fidelity: normalizeAnimationFidelity(
            Object.prototype.hasOwnProperty.call(overrides.answers || {}, 'animation_fidelity')
                ? overrides.answers.animation_fidelity
                : easySetupState.animationFidelity,
            recommendedAnimationFidelity(),
        ),
        advanced_chat_physics: Object.prototype.hasOwnProperty.call(overrides.answers || {}, 'advanced_chat_physics')
            ? Boolean(overrides.answers.advanced_chat_physics)
            : Boolean(easySetupState.chatPhysicsEnabled),
    };
    const dependencyPlanPayload = overrides.dependency_plan !== undefined
        ? overrides.dependency_plan
        : {
            path: safeString(easySetupState.selectedPath),
            items: Array.isArray(easySetupState.dependencyPlan) ? easySetupState.dependencyPlan : [],
        };

    const onboardingPatch = {
        version: ONBOARDING_VERSION,
        setup_completed: Boolean(
            Object.prototype.hasOwnProperty.call(overrides, 'setup_completed')
                ? overrides.setup_completed
                : existing.setup_completed
        ),
        current_step: Object.prototype.hasOwnProperty.call(overrides, 'current_step')
            ? overrides.current_step
            : easySetupStepName(easySetupState.step),
        connection_method: Object.prototype.hasOwnProperty.call(overrides, 'connection_method')
            ? overrides.connection_method
            : (safeString(easySetupState.selectedPath) || existing.connection_method || null),
        dependency_plan: dependencyPlanPayload,
        answers: mergedAnswers,
    };

    if (Object.prototype.hasOwnProperty.call(overrides, 'completed_at')) {
        onboardingPatch.completed_at = overrides.completed_at;
    }
    if (Object.prototype.hasOwnProperty.call(overrides, 'dismissed_at')) {
        onboardingPatch.dismissed_at = overrides.dismissed_at;
    }

    try {
        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ onboarding: onboardingPatch }),
        });
        if (!res.ok) return null;
        currentPreferences = await res.json();
        return currentPreferences?.onboarding || null;
    } catch {
        return null;
    }
}

function closeEasySetup() {
    if (!easySetupModal) return;
    easySetupModal.classList.remove('active');
    easySetupModal.style.display = 'none';
}

function hasEasySetupDismissRecord() {
    const onboarding = getOnboardingFromPrefs();
    return Boolean(safeString(onboarding?.dismissed_at));
}

function blockEasySetupClose(source = 'close_request') {
    const message = withAgentName('Setup is required before {{agent}} can run. Complete Easy Setup to continue.');
    if (easySetupState.step === 1 && easySetupRecommendedHint) {
        easySetupRecommendedHint.textContent = message;
    } else {
        const target = easySetupState.step >= 3 ? easySetupDependencyStatus : easySetupConnectionStatus;
        setEasySetupStatus(target, message, 'error');
    }
    emitOnboardingTelemetry('wizard.close_blocked', {
        source: safeString(source),
        step: easySetupStepName(easySetupState.step),
        path: safeString(easySetupState.selectedPath),
    });
}

function requestEasySetupClose(source = 'close_request') {
    if (easySetupState.required && source !== 'footer_skip') {
        blockEasySetupClose(source);
        return;
    }
    if (source === 'footer_skip' && easySetupState.required) {
        easySetupState.required = false;
        void persistOnboardingPrefs({
            dismissed_at: onboardingNowIso(),
        });
        emitOnboardingTelemetry('wizard.skipped', {
            source: safeString(source),
            step: easySetupStepName(easySetupState.step),
            path: safeString(easySetupState.selectedPath),
        });
    }
    closeEasySetup();
    emitOnboardingTelemetry('wizard.closed', {
        source: safeString(source),
        step: easySetupStepName(easySetupState.step),
        path: safeString(easySetupState.selectedPath),
    });
}

async function openEasySetup({ source = 'manual', force = false, restart = false } = {}) {
    if (!easySetupModal) return;
    if (!currentPreferences) {
        await refreshIdentityState();
    }

    const onboarding = getOnboardingFromPrefs();
    const setupCompleted = Boolean(onboarding?.setup_completed);
    if (!force && setupCompleted) {
        return;
    }
    easySetupState.required = !setupCompleted && !hasEasySetupDismissRecord();
    hideAssistantSuggestions({ force: true });

    easySetupState.source = safeString(source) || 'manual';
    easySetupState.onboardingSessionId = createOnboardingTelemetrySessionId();
    easySetupState.telemetryStartedAtMs = Date.now();
    if (restart) {
        easySetupState.interviewAnswers = {};
        easySetupState.interviewStarted = false;
        easySetupState.interviewStage = 'idle';
        easySetupState.interviewIndex = -1;
        easySetupState.interviewSkipChosen = false;
        easySetupState.dependenciesAction = 'pending';
        easySetupState.selectedPath = '';
        easySetupState.animationFidelity = recommendedAnimationFidelity();
        easySetupState.chatPhysicsEnabled = false;
    } else {
        easySetupState.interviewAnswers = { ...(onboarding?.answers || {}) };
        const restoredDependencyAction = safeString(onboarding?.answers?.dependency_action);
        easySetupState.dependenciesAction = restoredDependencyAction === 'approved' ? 'approved' : 'pending';
        easySetupState.animationFidelity = normalizeAnimationFidelity(
            onboarding?.answers?.animation_fidelity
            || currentPreferences?.advanced?.interface?.animation_fidelity,
            animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {}),
        );
        easySetupState.chatPhysicsEnabled = Boolean(
            Object.prototype.hasOwnProperty.call(onboarding?.answers || {}, 'advanced_chat_physics')
                ? onboarding?.answers?.advanced_chat_physics
                : currentPreferences?.advanced?.interface?.advanced_chat_physics,
        );
    }

    try {
        const bootstrap = await loadEasySetupBootstrap();
        const recommendedPath = mapRecommendedPath(bootstrap);
        if (!safeString(easySetupState.selectedPath)) {
            easySetupState.selectedPath = safeString(onboarding?.connection_method) || recommendedPath || 'manual';
        }
        easySetupState.dependencyPlan = buildEasySetupDependencyPlan(bootstrap, easySetupState.selectedPath);

        if (easySetupRecommendedHint) {
            const quickStartReason = safeString(bootstrap?.quick_start?.reason);
            if (recommendedPath) {
                const recommendedLabel = typeof humanizeConnectionPath === 'function'
                    ? humanizeConnectionPath(recommendedPath)
                    : recommendedPath;
                easySetupRecommendedHint.textContent = `Recommended: ${recommendedLabel}. ${quickStartReason}`;
            } else {
                easySetupRecommendedHint.textContent = quickStartReason || 'Select the path you want. We will verify before applying.';
            }
        }
    } catch (err) {
        if (easySetupRecommendedHint) {
            easySetupRecommendedHint.textContent = `Bootstrap check failed: ${safeString(err?.message) || 'unable to detect local readiness'}`;
        }
    }

    refreshEasySetupProfileOptions();
    renderEasySetupPathCards();
    syncEasySetupConnectionBlocks();
    setEasySetupStatus(easySetupConnectionStatus, 'Run connection test to continue.');
    setEasySetupDependencyDefaultStatus();

    const desiredStep = restart ? 1 : stepFromOnboardingName(onboarding?.current_step);
    setEasySetupStep(desiredStep);
    easySetupModal.classList.add('active');
    easySetupModal.style.display = 'flex';
    emitOnboardingTelemetry('wizard.opened', {
        source: easySetupState.source,
        path: safeString(easySetupState.selectedPath),
        step: easySetupStepName(easySetupState.step),
    });
}

async function maybeAutoOpenEasySetup() {
    if (isOnboardingComplete()) {
        return;
    }
    if (hasEasySetupDismissRecord()) {
        return;
    }
    await openEasySetup({ source: 'auto', force: false, restart: false });
}

function handleEasySetupPathSelect(path) {
    easySetupState.selectedPath = safeString(path);
    easySetupState.verified = false;
    easySetupState.verifiedProfile = '';
    easySetupState.codexModels = [];
    easySetupState.dependenciesAction = 'pending';
    easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
    renderEasySetupPathCards();
    syncEasySetupConnectionBlocks();
    setEasySetupStatus(easySetupConnectionStatus, 'Path selected. Run connection test.');
    setEasySetupDependencyDefaultStatus();
    updateEasySetupNavigation();
}

async function handleEasySetupConnectionTest() {
    if (!safeString(easySetupState.selectedPath)) {
        setEasySetupStatus(easySetupConnectionStatus, 'Pick a connection path first.', 'error');
        return;
    }

    easySetupState.verified = false;
    easySetupState.verifiedProfile = '';
    setEasySetupStatus(easySetupConnectionStatus, 'Running live connection checks...');

    try {
        if (easySetupState.selectedPath === 'codex') {
            const nativeProfile = findEasySetupNativeCodexProfile();
            if (nativeProfile?.name) {
                const profileName = safeString(nativeProfile.name);
                const statusUrl = `/api/openai-codex/status?profile=${encodeURIComponent(profileName)}`;
                let statusRes = await fetchJsonSafe(statusUrl);
                let loggedIn = Boolean(statusRes.data?.logged_in);
                if (!loggedIn) {
                    const loginRes = await fetchJsonSafe('/api/openai-codex/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ profile: profileName }),
                        timeoutMs: 310000,
                    });
                    loggedIn = Boolean(loginRes.data?.ok && loginRes.data?.logged_in !== false);
                    if (!loggedIn) {
                        const pending = Boolean(loginRes.data?.pending || loginRes.data?.needs_paste);
                        const errText = safeString(loginRes.data?.error) || 'ChatGPT OAuth login failed.';
                        const pasteHint = pending ? ' Finish the browser sign-in, then retry connection test.' : '';
                        throw new Error(`${errText}${pasteHint} Remediation: complete ChatGPT sign-in and retry.`);
                    }
                    statusRes = await fetchJsonSafe(statusUrl);
                }

                const modelsRes = await fetchJsonSafe(`/api/openai-codex/models?profile=${encodeURIComponent(profileName)}`);
                easySetupState.codexModels = (Array.isArray(modelsRes.data?.models) ? modelsRes.data.models : [])
                    .map((model) => safeString(model?.id || model))
                    .filter(Boolean);

                const validateRes = await fetchJsonSafe(`/api/models/${encodeURIComponent(profileName)}/validate?tool_smoke=0`);
                if (!validateRes.ok || !Boolean(validateRes.data?.ok)) {
                    const reason = safeString(validateRes.data?.error) || safeString(validateRes.text) || 'ChatGPT profile validation failed.';
                    throw new Error(`${reason} Remediation: run auto repair and retry.`);
                }
                easySetupState.verifiedProfile = profileName;
                easySetupState.verified = true;
                const codexName = safeString(statusRes.data?.display_name) || safeString(statusRes.data?.email) || 'ChatGPT account';
                setEasySetupStatus(
                    easySetupConnectionStatus,
                    `Connected as ${codexName}. Models detected: ${easySetupState.codexModels.length}.`,
                    'ok'
                );
                if (easySetupCodexMeta) {
                    easySetupCodexMeta.textContent = `Signed in with ChatGPT. Detected ${easySetupState.codexModels.length} model(s).`;
                }
            } else {
                // No profile on this Thomas speaks to ChatGPT (provider openai_codex),
                // and the routes that sign in need one. Say so now. This branch used
                // to call three addresses that do not exist and wait five minutes
                // before blaming the sign-in (owner directive, 2026-09-01).
                throw new Error('No ChatGPT profile is configured on this Thomas, so there is nothing to sign in to. Remediation: add a ChatGPT (openai_codex) profile under Models and Providers, then retry.');
            }
        } else if (easySetupState.selectedPath === 'manual') {
            const profile = safeString(easySetupManualProfile?.value);
            if (!profile) {
                throw new Error('No manual profile is configured. Add a cloud model profile first.');
            }
            const apiKey = safeString(easySetupManualApiKey?.value);
            if (apiKey) {
                const secretRes = await fetchJsonSafe(`/api/secrets/${encodeURIComponent(profile)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        api_key: apiKey,
                        persist: Boolean(easySetupManualPersist?.checked),
                    }),
                });
                if (!secretRes.ok) {
                    const reason = safeString(secretRes.text) || `Could not save key for profile "${profile}".`;
                    throw new Error(`${reason} Remediation: verify key format and profile.`);
                }
            }

            const validateRes = await fetchJsonSafe(`/api/models/${encodeURIComponent(profile)}/validate?tool_smoke=0`);
            if (!validateRes.ok || !Boolean(validateRes.data?.ok)) {
                const reason = safeString(validateRes.data?.error) || safeString(validateRes.text) || 'Profile validation failed.';
                throw new Error(`${reason} Remediation: verify provider key and endpoint.`);
            }

            easySetupState.verified = true;
            easySetupState.verifiedProfile = profile;
            setEasySetupStatus(
                easySetupConnectionStatus,
                `Manual profile "${profile}" validated.`,
                'ok'
            );
        } else {
            const profile = safeString(easySetupLocalProfile?.value) || 'local';
            const validateRes = await fetchJsonSafe(`/api/models/${encodeURIComponent(profile)}/validate?tool_smoke=0`);
            if (!validateRes.ok || !Boolean(validateRes.data?.ok)) {
                const reason = safeString(validateRes.data?.error) || safeString(validateRes.text) || 'Local validation failed.';
                throw new Error(`${reason} Remediation: install/start Ollama or run auto repair.`);
            }
            setEasySetupStatus(easySetupConnectionStatus, `Local profile "${profile}" validated. Syncing recommended local models...`);
            const localSync = await runEasySetupLocalModelSync(profile);
            easySetupState.verified = true;
            easySetupState.verifiedProfile = profile;
            const syncSummary = safeString(localSync?.summary);
            setEasySetupStatus(
                easySetupConnectionStatus,
                syncSummary ? `Local profile "${profile}" validated. ${syncSummary}` : `Local profile "${profile}" validated.`,
                'ok'
            );
        }
    } catch (err) {
        easySetupState.verified = false;
        easySetupState.verifiedProfile = '';
        setEasySetupStatus(easySetupConnectionStatus, safeString(err?.message) || 'Connection check failed.', 'error');
    }

    easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
    setEasySetupDependencyDefaultStatus();
    // BUG 2 FIX: a verified profile must become the active model immediately so
    // the pick persists (and survives reload), not just get configured.
    if (easySetupState.verified) {
        await activateEasySetupProfile();
    }
    updateEasySetupNavigation();
    await persistOnboardingPrefs({
        current_step: 'connect',
        connection_method: safeString(easySetupState.selectedPath) || null,
    });
    emitOnboardingTelemetry('wizard.connection_tested', {
        path: safeString(easySetupState.selectedPath),
        verified: Boolean(easySetupState.verified),
        profile: safeString(easySetupState.verifiedProfile),
    });
}

async function runEasySetupRepair(trigger = 'repair') {
    setEasySetupStatus(easySetupDependencyStatus, 'Running setup repair. You may need to approve system installer prompts.');
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
        setEasySetupStatus(easySetupDependencyStatus, `${reason} Remediation: run repair from command line and retry.`, 'error');
        emitOnboardingTelemetry('wizard.download_approval_failed', {
            trigger,
            error: reason,
        });
        return false;
    }

    if (!Boolean(res.data?.ok)) {
        const errorMsg = safeString(res.data?.error) || `Repair exited with code ${res.data?.exit_code}.`;
        /* The wizard speaks plainly; exit codes and stderr stay in telemetry. */
        setEasySetupStatus(easySetupDependencyStatus, "Setup couldn't finish installing what Thomas needs. Approve the prompts and retry.", 'error');
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
                'Connection must verify before continuing. Use "Connect and Test".',
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
        await persistOnboardingPrefs({ current_step: 'preferences' });
        emitOnboardingTelemetry('wizard.step_advanced', { step: 'preferences', path: easySetupState.selectedPath });
        return;
    }

    if (easySetupState.step === 4) {
        easySetupState.animationFidelity = normalizeAnimationFidelity(
            easySetupState.animationFidelity,
            recommendedAnimationFidelity(),
        );
        if (easySetupState.animationFidelity === ANIMATION_FIDELITY_MINIMAL) {
            easySetupState.chatPhysicsEnabled = false;
        }
        setEasySetupStep(5);
        await persistOnboardingPrefs({
            current_step: 'brain_ready',
            answers: {
                animation_fidelity: easySetupState.animationFidelity,
                advanced_chat_physics: easySetupState.chatPhysicsEnabled,
            },
        });
        emitOnboardingTelemetry('wizard.step_advanced', {
            step: 'brain_ready',
            path: easySetupState.selectedPath,
            animation_fidelity: easySetupState.animationFidelity,
            advanced_chat_physics: easySetupState.chatPhysicsEnabled,
        });
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
