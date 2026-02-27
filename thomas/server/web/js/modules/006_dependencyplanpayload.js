// Extracted from part-003b.js
// From dependencyplanpayload

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
    } else {
        easySetupState.interviewAnswers = { ...(onboarding?.answers || {}) };
        const restoredDependencyAction = safeString(onboarding?.answers?.dependency_action);
        easySetupState.dependenciesAction = restoredDependencyAction === 'approved' ? 'approved' : 'pending';
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
                easySetupRecommendedHint.textContent = `Recommended: ${recommendedPath}. ${quickStartReason}`;
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
