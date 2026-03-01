// Extracted from part-008.js
// From finalprompt

    setGeneratingState(true);
    pushDebugEvent('chat', 'Started chat request');

    let finalPrompt = setupPersonalitySelector.value;
    if (finalPrompt === 'custom') {
        finalPrompt = setupCustomPrompt.value.trim();
    }

    const modelMessage = composerBuildMessageForModel(text);
    const selectedProfile = setupProviderSelector.value || modelSelector.value;
    const studioChatContext = typeof moduleStudioBuildChatContext === 'function' ? moduleStudioBuildChatContext() : { enabled: false, preferredProfile: '', context: {} };
    const preferredProfile = safeString(studioChatContext.preferredProfile);
    const resolvedProfile = preferredProfile || selectedProfile;
    if (preferredProfile && preferredProfile !== safeString(selectedProfile) && typeof applyProfileSelection === 'function') {
        applyProfileSelection(preferredProfile);
    }
    const requestedMode = normalizeChatMode(activeChatMode) || 'auto';
    const payload = {
        message: modelMessage || text,
        docs: docsToSend,
        images: imagesToSend,
        session_id: sessionId,
        profile: resolvedProfile,
        model: resolvedProfile,
        model_id: activeModelOverride || undefined,
        mode: requestedMode,
        autonomy_level: activeAutonomyLevel,
        token_economy: activeTokenEconomy,
        reasoning_effort: activeReasoningEffort || undefined,
        system_prompt: finalPrompt || undefined,
    };
    if (studioChatContext.enabled) {
        payload.asset_studio_mode = 'comfy_studio';
        payload.asset_studio_context = studioChatContext.context || {};
    }

    await streamChatResponse(payload, { userContext: suggestionUserContext });
}

async function handleSend() {
    composerCloseActionsMenu();
    const text = composerTextarea.value.trim();
    if (!text && pendingDocs.length === 0 && pendingImages.length === 0) return;
    composerInputLockUntil = Date.now() + 1600;

    if (isOnboardingSlashCommand(text) && pendingDocs.length === 0 && pendingImages.length === 0) {
        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        ensureChatVisible();
        renderMessage({ role: 'user', content: text });
        renderMessage({ role: 'assistant', content: 'Opening Easy Setup. We will verify your connection before setup continues.' });
        openEasySetup({ source: 'slash', force: true });
        return;
    }

    if (!isOnboardingComplete()) {
        if (easySetupState.interviewStarted) {
