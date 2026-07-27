// Extracted from part-030b.js
// From payload


    const payload = {
        profile: {
            display_name: nextName,
            avatar_url: safeString(currentPreferences?.profile?.avatar_url),
        },
    };

    try {
        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }
        currentPreferences = await res.json();
        if (settingsDisplayName) settingsDisplayName.value = resolveAgentName(currentPreferences);
        refreshSettingsAvatarPreview();
        updateSidebarIdentity();
        notifyUser(`Agent renamed to ${getAgentName()}.`, {
            tone: 'success',
            durationMs: 2200,
            debugKind: 'settings',
        });
        emitOnboardingTelemetry('agent.renamed', {
            source: safeString(source) || 'rename',
            name: getAgentName(),
        });
        return true;
    } catch (error) {
        notifyUser(`Could not rename agent: ${safeString(error?.message) || 'unknown error'}`, {
            tone: 'error',
            durationMs: 3000,
            debugKind: 'error',
        });
        return false;
    }
}

async function promptRenameAgentIdentity() {
    const currentName = getAgentName();
    const prompted = window.prompt('Rename your assistant', currentName);
    if (prompted === null) return;
    const nextName = sanitizeAgentNameInput(prompted);
    if (!nextName) {
        notifyUser('Agent name cannot be blank.', {
            tone: 'warning',
            durationMs: 2400,
            debugKind: 'settings',
        });
        return;
    }
    await saveAgentIdentityName(nextName, { source: 'sidebar_pencil' });
}

async function loadSessionFromHistory(sid) {
    activeChatId = sid;
    saveStoredActiveChatId(activeChatId);
    rebuildChatHistorySelector();
    try {
        let sessionData = sidebarSessions.find((row) => safeString(row?.id) === safeString(sid)) || null;
        if (!sessionData) {
            await fetchChatHistory();
            sessionData = sidebarSessions.find((row) => safeString(row?.id) === safeString(sid)) || null;
        }
        if (!sessionData) {
            throw new Error(`Chat ${sid} not found.`);
        }

        const loadedHistory = normalizeConversationHistory(sessionData.messages);
        chatHistory = loadedHistory;
        chatMessagesInner.innerHTML = '';
        if (chatHistory.length > 0) {
            welcomeScreen.classList.add('hidden');
            chatScrollArea.classList.remove('hidden');
            let lastAssistantMessage = '';
            chatHistory.forEach((msg) => {
                renderMessage(msg);
                if (safeString(msg?.role) === 'assistant') {
                    lastAssistantMessage = safeString(msg?.content);
                }
            });
            if (lastAssistantMessage) {
                maybeShowAssistantFollowups();
            } else {
                showStarterSuggestionRail({ force: true });
            }
        } else {
            welcomeScreen.classList.remove('hidden');
            chatScrollArea.classList.add('hidden');
            maybeRenderSessionIntro();
            showStarterSuggestionRail({ force: true });
        }

        // Bind runtime to the persisted chat id so multiple tabs/windows
        // stay on one canonical session state for the same chat.
        sessionId = safeString(sid);
    } catch (e) { console.error("Error loading past session", e); }
    syncActiveChatSidebarEntry();
    renderSidebarChatList();
    pushDebugEvent('chat', `Loaded session ${safeString(sid)}`);
    await refreshTaskContinuity({ sessionOverride: sessionId || sid, force: true });
    _positionRobotDock();
    if (!document.querySelector('.chat-robot-landed')) {
        _landRobotAtComposerDock();
    }
}

async function fetchModels() {
    try {
        const res = await fetchJsonSafe('/api/models', { timeoutMs: 8000 });
        if (res.ok) {
            const data = res.data || {};
