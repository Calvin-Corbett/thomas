function officeCollectAgentPrefsSnapshot() {
    if (!officeState) return {};
    const snapshot = {};
    officeState.agents.forEach((agent) => {
        if (!agent) return;
        snapshot[agent.id] = {
            name: safeString(agent.name).slice(0, 24),
            color: /^#[0-9a-f]{6}$/i.test(safeString(agent.color)) ? safeString(agent.color) : '#9ad8ff',
            costume: safeString(agent.costume || 'none'),
            tint: safeString(agent.tint || 'blue'),
            specialty: safeString(agent.specialty || 'Generalist').slice(0, 64),
            personality: safeString(agent.personality || 'Helpful, direct, and persistent.').slice(0, 160),
            chatProfile: safeString(agent.chatProfile).slice(0, 80),
            chatModelId: safeString(agent.chatModelId).slice(0, 120),
            officeChatHistory: Array.isArray(agent.officeChatHistory)
                ? agent.officeChatHistory.slice(-18).map((entry) => ({
                    role: safeString(entry?.role).slice(0, 16),
                    text: safeString(entry?.text).slice(0, 600),
                    at: Number(entry?.at) || Date.now(),
                    timeLabel: safeString(entry?.timeLabel).slice(0, 24),
                })).filter((entry) => entry.text)
                : [],
        };
    });
    return snapshot;
}

function officePersistAgentPrefs() {
    if (!officeState) return;
    saveStoredOfficeAgentPrefs(officeCollectAgentPrefsSnapshot());
}

function setChatListExpanded(expanded, { persist = true } = {}) {
    chatListExpanded = Boolean(expanded);
    if (navChatBtn) navChatBtn.classList.toggle('chat-list-collapsed', !chatListExpanded);
    if (sidebarChatPanel) {
        sidebarChatPanel.classList.toggle('chat-list-collapsed', !chatListExpanded);
        sidebarChatPanel.classList.toggle('hidden', !(sidebarNavMode === 'chat' || sidebarNavMode === 'search'));
    }
    if (persist) saveStoredChatListExpanded(chatListExpanded);
}

function initContentWorkspace() {
    const state = contentEnsureState();
    if (!state) return;
    if (!state.controlsBound) {
        state.controlsBound = true;
        if (contentRefreshBtn) {
            contentRefreshBtn.addEventListener('click', async () => {
                const ok = await contentRefresh({ silent: true });
                if (ok) {
                    notifyUser('Content Hub refreshed from live mission data.', {
                        tone: 'success',
                        debugKind: 'success',
                        durationMs: 1700,
                    });
                } else {
                    notifyUser('Content Hub refresh failed.', {
                        tone: 'warning',
                        debugKind: 'warning',
                        durationMs: 2600,
                    });
                }
            });
        }
    }
    if (!state.payload) {
        state.payload = contentEmptyPayload();
    }
    contentRender();
    if (sidebarNavMode === 'content') {
        void contentRefresh({ silent: true });
    }
}

// 
//   SIDEBAR & NAVIGATION                                                   
//   Nav mode switching, chat list, office/content workspace init           
// 

// Deep-link consumer for "My Stuff" build deliverables: a "/?forge_code=<cid>"
// URL (the deep_link a deliverable carries back to its originating Code
// conversation) opens the Forge Code surface and resumes that conversation. The
// param is stripped afterward so a refresh does not re-trigger it. Fully
// defensive: a missing global or unknown id simply lands on the Code surface.
function maybeOpenForgeCodeDeepLink() {
    let cid = '';
    try {
        cid = new URLSearchParams(window.location.search).get('forge_code') || '';
    } catch (_e) {
        cid = '';
    }
    if (!cid) return;
    try {
        const url = new URL(window.location.href);
        url.searchParams.delete('forge_code');
        window.history.replaceState({}, '', url.pathname + url.search + url.hash);
    } catch (_e) { /* non-fatal: leave the URL as-is */ }
    setSidebarNavMode('evolution');
    // The Evolution shell + Code surface build on the next frame; open Code and
    // resume the conversation once they exist.
    window.setTimeout(() => {
        try {
            if (typeof forgeShowSide === 'function') forgeShowSide('code');
            if (typeof window.forgeCodeOpenConversation === 'function') {
                void window.forgeCodeOpenConversation(cid);
            }
        } catch (_e) { /* non-fatal */ }
    }, 60);
}

function setSidebarNavMode(mode = 'chat', { persist = true } = {}) {
    const requestedMode = normalizeNavMode(mode);
    const previousMode = sidebarNavMode;
    sidebarNavMode = isUiEditorPreviewShell() && requestedMode === 'app_builder' ? 'chat' : requestedMode;
    const isSearch = sidebarNavMode === 'search';
    const isChat = sidebarNavMode === 'chat' || isSearch;
    const isOffice = sidebarNavMode === 'office';
    const showOfficePreview = false;
    const isMission = sidebarNavMode === 'mission';
    const isEvolution = sidebarNavMode === 'evolution';
    const isContent = sidebarNavMode === 'content';
    const isModule = MODULE_NAV_MODE_SET.has(sidebarNavMode);

    /* Body class so CSS can scope things to the chat page */
    document.body.classList.toggle('te-nav-chat', isChat);
    document.body.classList.toggle('office-active', isOffice);

    if (navChatBtn) navChatBtn.classList.toggle('active', isChat);
    const navOfficeBtnLive = document.getElementById('navOfficeBtn');
    if (navOfficeBtnLive) navOfficeBtnLive.classList.toggle('active', isOffice);
    if (navMissionBtn) navMissionBtn.classList.toggle('active', isMission);
    const navForgeBtnLive = document.getElementById('navForgeBtn');
    if (navForgeBtnLive) navForgeBtnLive.classList.toggle('active', isEvolution);
    if (navContentBtn) navContentBtn.classList.toggle('active', isContent);
    sidebarModeButtons.forEach((button) => {
        const buttonMode = normalizeNavMode(button.dataset.navMode);
        button.classList.toggle('active', buttonMode === sidebarNavMode);
    });
    moduleRenderInstalledPluginNav();
    if (searchOverlayBar) searchOverlayBar.classList.remove('hidden');
    if (sidebarChatPanel) {
        sidebarChatPanel.classList.toggle('hidden', !isChat);
        sidebarChatPanel.classList.toggle('chat-list-collapsed', !chatListExpanded);
    }
    if (officeWorkspace) {
        officeWorkspace.classList.toggle('hidden', !(isOffice || showOfficePreview));
        officeWorkspace.classList.toggle('chat-preview-active', showOfficePreview);
    }
    if (missionWorkspace) missionWorkspace.classList.toggle('hidden', !isMission);
    if (evolutionWorkspace) evolutionWorkspace.classList.toggle('hidden', !isEvolution);
    if (contentWorkspace) contentWorkspace.classList.toggle('hidden', !isContent);
    if (moduleWorkspace) moduleWorkspace.classList.toggle('hidden', !isModule);
    /* The main chat composer belongs to the chat view only. Without this it
       stays floating (position:absolute, z-index:20) on top of the workspace
       dashboards (Evolution/Mission/Office/Content/Module), which reads as a
       confusing second chat whose messages post to the now-hidden chat thread.
       Hide it whenever we are not in chat/search so each workspace owns its
       surface cleanly. */
    if (composerContainer) composerContainer.classList.toggle('hidden', !isChat);
    if (appRoot) {
        appRoot.classList.toggle('office-active', isOffice);
        appRoot.classList.toggle('office-preview-active', showOfficePreview);
        appRoot.classList.toggle('mission-active', isMission);
        appRoot.classList.toggle('evolution-active', isEvolution);
        appRoot.classList.toggle('content-active', isContent);
        appRoot.classList.toggle('module-active', isModule);
    }

    if (sidebar) {
        sidebar.classList.toggle('mode-search', isSearch);
        sidebar.classList.toggle('mode-chat', isChat);
        sidebar.classList.toggle('mode-office', isOffice);
        sidebar.classList.toggle('mode-mission', isMission);
        sidebar.classList.toggle('mode-evolution', isEvolution);
        sidebar.classList.toggle('mode-content', isContent);
        sidebar.classList.toggle('mode-module', isModule);
    }
    officeScheduleChatPreviewRefresh();

    if (isOffice || showOfficePreview) {
        initOfficeWorkspace();
        if (officeSceneWrap instanceof HTMLElement && isOffice) {
            window.setTimeout(() => {
                officeSceneWrap.focus();
            }, 0);
        }
    } else {
        const state = officeEnsureDraftMapState();
        state.pointerId = null;
        if (officeSceneWrap instanceof HTMLElement) {
            officeSceneWrap.style.cursor = 'grab';
        }
    }

    if (isMission) {
        missionEnterMode();
    } else {
        missionLeaveMode();
    }

    if (isEvolution) {
        if (typeof evolutionEnterMode === 'function') evolutionEnterMode();
    } else if (typeof evolutionLeaveMode === 'function') {
        evolutionLeaveMode();
    }

    if (isContent) {
        contentEnterMode();
    } else {
        contentLeaveMode();
    }

    if (isModule) {
        if (sidebarNavMode === 'channels' && previousMode !== 'channels') {
            const channelsState = moduleChannelsState();
            if (channelsState) channelsState.detailOpen = false;
        }
        moduleEnterMode(sidebarNavMode);
        if (sidebarNavMode === 'finance') void spendRefresh();
        if (sidebarNavMode === 'operations' || sidebarNavMode === 'dashboard') void goalsRefresh();
    } else {
        moduleLeaveMode();
    }

    if (!isChat) {
        chatGameClose({ clearMode: false });
        if (safeString(composerModeSelection?.kind) === 'game') {
            composerClearMode({ closeGame: false });
        }
    }

    setSidebarSearchScope(isModule ? 'general' : sidebarNavMode);

    if (persist && !isSearch) {
        saveStoredNavMode(sidebarNavMode);
    }
    normalizeMainContentScroll();
    updateTaskContinuityVisibility({ refresh: isChat });
    updateDebugDockSnapshot();
}

function setSidebarSearchScope(scope = 'chat') {
    const normalizedScope = safeString(scope).toLowerCase();
    if (normalizedScope === 'office' || normalizedScope === 'mission' || normalizedScope === 'content' || normalizedScope === 'general') {
        sidebarSearchScope = normalizedScope;
    } else if (normalizedScope === 'search' || MODULE_NAV_MODE_SET.has(normalizedScope)) {
        sidebarSearchScope = 'general';
    } else {
        sidebarSearchScope = 'chat';
    }

    let label = 'Search chats';
    if (sidebarSearchScope === 'office') label = 'Search office';
    if (sidebarSearchScope === 'mission') label = 'Search mission control';
    if (sidebarSearchScope === 'content') label = 'Search content hub';
    if (sidebarSearchScope === 'general') label = withAgentName('Search {{agent}}');

    if (globalSearchInput) globalSearchInput.placeholder = label;
    if (sidebarSearchModeLabel) sidebarSearchModeLabel.textContent = label;
    if (sidebarChatHeaderLabel) sidebarChatHeaderLabel.textContent = 'Recent Chats';
    renderSidebarChatList();
    updateDebugDockSnapshot();
}

function renderSidebarChatList() {
    if (!sidebarChatList) return;
    const chatSearchEnabled = sidebarSearchScope === 'chat' || sidebarSearchScope === 'general';
    const queryLower = chatSearchEnabled ? safeString(globalSearchInput?.value).toLowerCase() : '';
    const activeId = safeString(activeChatId) || safeString(sessionId);
    sidebarChatList.innerHTML = '';

    const filteredSessions = sidebarSessions.filter((session) => {
        if (!queryLower) return true;
        const haystack = `${safeString(session?.title)} ${safeString(session?.preview)} ${safeString(session?.model)} ${safeString(session?.id)}`.toLowerCase();
        return haystack.includes(queryLower);
    });

    filteredSessions.forEach((session) => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'sidebar-chat-row';
        if (safeString(session?.id) === activeId) {
            row.classList.add('active');
        }
        row.innerHTML = `
            <span class="sidebar-chat-row-title">${escapeHtml(formatSidebarSessionTitle(session))}</span>
            <span class="sidebar-chat-row-meta">${escapeHtml(formatSidebarSessionMeta(session))}</span>
        `;
        row.addEventListener('click', () => {
            const sid = safeString(session?.id);
            if (!sid) return;
            void loadSessionFromHistory(sid);
        });
        sidebarChatList.appendChild(row);
    });

    if (!sidebarChatList.children.length) {
        const empty = document.createElement('div');
        empty.className = 'sidebar-chat-empty';
        if (queryLower) {
            empty.textContent = 'No matches yet. Try another search term.';
        } else if (sidebarSearchScope === 'general') {
            empty.textContent = withAgentName('Search {{agent}} to find chats and relevant items.');
        } else if (sidebarHistoryLoadState === 'pending') {
            // "No chats yet." is a claim about the data, and before the history
            // fetch answers there IS no data -- this render path runs from mode
            // and scope switches that never wait for fetchChatHistory. Measured
            // 2026-08-05: the empty claim showed over hundreds of real chats.
            empty.textContent = 'Loading chats…';
        } else if (sidebarHistoryLoadState === 'error') {
            empty.textContent = 'Chat history could not be loaded. Reload to retry.';
        } else {
            empty.textContent = 'No chats yet. Start one from New Chat.';
        }
        sidebarChatList.appendChild(empty);
    }
}

function slugifySettingsLabel(label) {
    return safeString(label)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

function isSettingsSectionVisible(section) {
    return Boolean(section && section.getClientRects().length > 0);
}

function setActiveSettingsSectionNav(sectionId) {
    settingsSectionEntries.forEach((entry) => {
        const isActive = Boolean(sectionId) && entry.section.id === sectionId && !entry.link.classList.contains('hidden');
        entry.link.classList.toggle('active', isActive);
        entry.link.setAttribute('aria-current', isActive ? 'true' : 'false');
    });
}

function getVisibleSettingsSectionEntries() {
    return settingsSectionEntries.filter((entry) => !entry.link.classList.contains('hidden') && isSettingsSectionVisible(entry.section));
}

function updateSettingsNavEmptyState() {
    if (!settingsNavEmpty) return;
    const hasVisibleEntries = settingsSectionEntries.some((entry) => !entry.link.classList.contains('hidden'));
    settingsNavEmpty.classList.toggle('hidden', hasVisibleEntries);
}

function updateSettingsSectionNavActive() {
    if (!settingsSections) return;
    const visibleEntries = getVisibleSettingsSectionEntries();
    if (visibleEntries.length === 0) {
        setActiveSettingsSectionNav('');
        return;
    }

    /* If scrolled to (or very near) the bottom, highlight the last section */
    const atBottom = settingsSections.scrollTop + settingsSections.clientHeight >= settingsSections.scrollHeight - 40;
    if (atBottom) {
        setActiveSettingsSectionNav(visibleEntries[visibleEntries.length - 1].section.id);
        return;
    }

    const activeOffset = settingsSections.scrollTop + 56;
    let activeEntry = visibleEntries[0];
    visibleEntries.forEach((entry) => {
        if (entry.section.offsetTop <= activeOffset) {
            activeEntry = entry;
        }
    });
    setActiveSettingsSectionNav(activeEntry.section.id);
}

function queueSettingsSectionNavActiveUpdate() {
    if (settingsNavTicking) return;
    settingsNavTicking = true;
    requestAnimationFrame(() => {
        settingsNavTicking = false;
        updateSettingsSectionNavActive();
    });
}

function updateSettingsSectionNavVisibility() {
    const query = safeString(settingsSectionSearch?.value).toLowerCase();
    const advancedModeEnabled = Boolean(settingsSuite?.classList.contains('advanced-mode'));

    settingsSectionEntries.forEach((entry) => {
        const advancedOnly = entry.section.classList.contains('settings-advanced-only');
        const inMode = advancedModeEnabled || !advancedOnly;
        const matches = !query || entry.labelLower.includes(query);
        entry.link.classList.toggle('hidden', !(inMode && matches));
    });

    updateSettingsNavEmptyState();
    queueSettingsSectionNavActiveUpdate();
}

function scrollToSettingsSection(sectionId) {
    if (!settingsSections || !sectionId) return;
    const section = document.getElementById(sectionId);
    if (!isSettingsSectionVisible(section)) return;
    const top = Math.max(0, section.offsetTop - 8);
    settingsSections.scrollTo({ top, behavior: 'smooth' });
    setActiveSettingsSectionNav(sectionId);
}

function buildSettingsSectionNav() {
    if (!settingsSectionNav || !settingsSections) return;
    settingsSectionNav.innerHTML = '';
    settingsSectionEntries = [];

    const seenIds = new Set();
    const sections = Array.from(settingsSections.querySelectorAll('.settings-section'));
    sections.forEach((section, index) => {
        const heading = section.querySelector('.settings-section-head h3');
        const label = safeString(heading?.textContent) || `Section ${index + 1}`;
        const baseId = safeString(section.id) || `settings-${slugifySettingsLabel(label) || `section-${index + 1}`}`;
        let sectionId = baseId;
        let suffix = 2;
        while (seenIds.has(sectionId)) {
            sectionId = `${baseId}-${suffix}`;
            suffix += 1;
        }
        seenIds.add(sectionId);
        section.id = sectionId;

        const link = document.createElement('button');
        link.type = 'button';
        link.className = 'settings-nav-link';
        link.textContent = label;
        link.dataset.sectionId = sectionId;
        link.setAttribute('aria-current', 'false');
        link.addEventListener('click', () => scrollToSettingsSection(sectionId));
        settingsSectionNav.appendChild(link);

        settingsSectionEntries.push({
            section,
            link,
            labelLower: label.toLowerCase(),
        });
    });

    updateSettingsSectionNavVisibility();
}

function initSettingsSectionNavigation() {
    if (settingsNavBound || !settingsSectionNav || !settingsSections) return;
    settingsNavBound = true;
    buildSettingsSectionNav();

    if (settingsSectionSearch) {
        settingsSectionSearch.addEventListener('input', updateSettingsSectionNavVisibility);
    }

    settingsSections.addEventListener('scroll', queueSettingsSectionNavActiveUpdate, { passive: true });
    window.addEventListener('resize', queueSettingsSectionNavActiveUpdate);
}

// 
//   INITIAL STATE & BOOT                                                   
//   loadInitialState(), session creation, profile loading, preference sync 
// 

async function maybeHandleBootPluginInstall() {
    if (bootPluginInstallPromise) {
        return bootPluginInstallPromise;
    }
    if (bootPluginInstallHandled) {
        return null;
    }
    const deepLink = loadRequestedPluginInstallDeepLinkFromUrl();
    if (!deepLink) {
        return null;
    }
    bootPluginInstallHandled = true;
    clearRequestedPluginInstallFromUrl();
    bootPluginInstallPromise = (async () => {
        setSidebarNavMode('marketplace');
        notifyUser('Installing plugin from Thomas website...', {
            tone: 'info',
            durationMs: 1800,
            debugKind: 'marketplace-install',
        });
        const result = await moduleInstallMarketplacePluginFromDeepLink(deepLink);
        const learnedStoreUrl = moduleWritePreferredMarketplaceStoreUrl(
            safeString(result?.request?.store || result?.plugin?.source?.store_url)
        );
        const runtime = moduleEnsureRuntime();
        if (runtime?.marketplace && learnedStoreUrl) {
            runtime.marketplace.storeUrl = learnedStoreUrl;
            runtime.marketplace.pendingStoreUrl = learnedStoreUrl;
        }
        await moduleRefreshMarketplace({ force: true, storeUrl: learnedStoreUrl });
        if (!result?.ok) {
            setSidebarNavMode('marketplace');
            moduleRender('marketplace', { touch: false });
            const reason = safeString(result?.error) || 'Unable to install plugin.';
            notifyUser(`Plugin install failed: ${reason} Use Download ZIP and Install From File in Marketplace if needed.`, {
                tone: 'error',
                durationMs: 4800,
                debugKind: 'marketplace-install',
            });
            return result;
        }
        const modeId = safeString(result?.plugin?.mode_id);
        if (modeId) {
            setSidebarNavMode(modeId);
        } else {
            setSidebarNavMode('marketplace');
            moduleRender('marketplace', { touch: false });
        }
        const displayName = safeString(result?.plugin?.display_name) || 'Plugin';
        notifyUser(`${displayName} installed from the Thomas store.`, {
            tone: 'success',
            durationMs: 2200,
            debugKind: 'marketplace-install',
        });
        return result;
    })().finally(() => {
        bootPluginInstallPromise = null;
    });
    return bootPluginInstallPromise;
}

async function loadInitialState() {
    let loadedFromHistory = false;
    try {
        await refreshIdentityState();
        await fetchModels();
        await fetchChatHistory();

        const storedActiveChatId = loadStoredActiveChatId();
        const hasStoredSession = Boolean(storedActiveChatId)
            && sidebarSessions.some((row) => safeString(row?.id) === safeString(storedActiveChatId));
        if (hasStoredSession) {
            await loadSessionFromHistory(storedActiveChatId);
            loadedFromHistory = true;
        } else if (storedActiveChatId) {
            saveStoredActiveChatId('');
        }

        if (!loadedFromHistory && sidebarSessions.length > 0) {
            const latestSessionId = safeString(sidebarSessions[0]?.id);
            if (latestSessionId) {
                await loadSessionFromHistory(latestSessionId);
                loadedFromHistory = true;
            }
        }

        if (!loadedFromHistory) {
            await createNewSessionAndRefresh();
        }
    } catch (e) {
        console.error("Failed to boot session:", e);
        await createNewSessionAndRefresh();
    } finally {
        _positionRobotDock();
        if (!document.querySelector('.chat-robot-landed')) {
            _landRobotAtComposerDock();
        }
        await maybeAutoOpenEasySetup();
        await maybeHandleBootPluginInstall();
    }
}

async function fetchChatHistory() {
    try {
        const res = await fetchJsonSafe('/api/chats');
        if (res.ok) {
            const data = res.data || {};
            const chatRows = Array.isArray(data?.chats) ? data.chats : [];
            if (chatRows.length > 0) {
                sidebarSessions = chatRows
                    .map((row) => mapPersistedChatToSidebarSession(row))
                    .filter(Boolean);
            } else {
                const legacySessions = Array.isArray(data?.sessions) ? data.sessions : [];
                sidebarSessions = legacySessions
                    .map((row) => mapLegacySidebarSession(row))
                    .filter(Boolean);
            }
            sidebarSessions.sort((a, b) => Number(b?.updatedAt || 0) - Number(a?.updatedAt || 0));
            sidebarHistoryLoadState = 'loaded';
            // This wholesale replacement used to DROP the conversation the user
            // just started: the server list only learns about a chat once its
            // first turn is persisted, so a refresh racing the first reply made
            // the active chat vanish from Recent (measured 2026-08-05). If the
            // active conversation has real messages and the server does not
            // know it yet, re-seat it instead of trusting the stale list.
            const activeId = safeString(activeChatId) || safeString(sessionId);
            const activeHasMessages = Array.isArray(chatHistory) && chatHistory.length > 0;
            const activeMissing = Boolean(activeId)
                && activeHasMessages
                && !sidebarSessions.some((row) => safeString(row?.id) === activeId);
            if (activeMissing) {
                syncActiveChatSidebarEntry({ touchUpdatedAt: false });
            }
            rebuildChatHistorySelector();
            renderSidebarChatList();
            updateDebugDockSnapshot();
        } else if (sidebarHistoryLoadState !== 'loaded') {
            // A refused answer is a failure to name, not an empty history. A
            // later failed REFRESH keeps 'loaded' -- the rows on screen are
            // still real.
            sidebarHistoryLoadState = 'error';
            renderSidebarChatList();
        }
    } catch (e) {
        if (sidebarHistoryLoadState !== 'loaded') {
            sidebarHistoryLoadState = 'error';
            renderSidebarChatList();
        }
        console.error("Failed to fetch chat history:", e);
    }
}

async function createNewSessionAndRefresh() {
    // Abort any in-flight generation so a still-streaming reply from the old chat
    // can't bleed into the new one (live persona testing: starting a new chat while
    // a prior task was still streaming mis-titled the new chat and dropped its prompt).
    abortInFlightChatGeneration();
    try {
        const res = await fetchJsonSafe('/api/session/new', { method: 'POST' });
        const data = res.data || {};
        if (res.ok && data.session_id) {
            sessionId = data.session_id;
            activeChatId = data.session_id;
            saveStoredActiveChatId(activeChatId);
            pushDebugEvent('chat', `Created session ${sessionId}`);
            // Clear current UI chat
            chatHistory = [];
            chatMessagesInner.innerHTML = '';
            welcomeScreen.classList.remove('hidden');
            chatScrollArea.classList.add('hidden');
            maybeRenderSessionIntro();
            showStarterSuggestionRail({ force: true });
            await fetchChatHistory();
            await refreshTaskContinuity({ sessionOverride: sessionId, force: true });
        }
    } catch (e) { console.error("Error creating new session:", e); }
}

async function saveAgentIdentityName(nameRaw, { source = 'rename' } = {}) {
    const nextName = sanitizeAgentNameInput(nameRaw);
    if (!nextName) {
        notifyUser('Agent name cannot be empty.', {
            tone: 'warning',
            durationMs: 2400,
            debugKind: 'settings',
        });
        return false;
    }

    const currentName = getAgentName();
    if (nextName === currentName) return true;

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

// Cancel an in-flight streaming generation (used when switching/creating chats so
// a prior reply can't bleed into a different chat). Best-effort and side-effect-safe.
function abortInFlightChatGeneration() {
    try {
        if (typeof currentAbortController !== 'undefined' && currentAbortController) {
            currentAbortController.abort();
            currentAbortController = null;
        }
    } catch (_) { /* best-effort */ }
    try {
        if (typeof setGeneratingState === 'function') setGeneratingState(false);
    } catch (_) { /* best-effort */ }
}

async function loadSessionFromHistory(sid) {
    // Abort any in-flight generation before switching chats so the prior reply
    // can't stream into the chat we're switching to.
    abortInFlightChatGeneration();
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
    syncActiveChatSidebarEntry({ touchUpdatedAt: false });
    renderSidebarChatList();
    pushDebugEvent('chat', `Loaded session ${safeString(sid)}`);
    // Rebuild the deliverable chips from the durable task ledger so a reload/chat-switch
    // no longer loses them (the per-message strip state is in-memory only).
    if (typeof reconcileSessionDeliverables === 'function') {
        void reconcileSessionDeliverables(sid);
    }
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
            availableModelProfiles = Array.isArray(data.profiles) ? data.profiles : [];
            if (data.preferences && typeof data.preferences === 'object') {
                currentPreferences = currentPreferences && typeof currentPreferences === 'object' ? currentPreferences : {};
                currentPreferences.advanced = currentPreferences.advanced && typeof currentPreferences.advanced === 'object'
                    ? currentPreferences.advanced
                    : {};
                currentPreferences.advanced.model = {
                    ...(currentPreferences.advanced.model || {}),
                    ...data.preferences,
                };
            }
            modelSelector.innerHTML = '';
            setupProviderSelector.innerHTML = '';

            // Partition into connected vs. additional providers for the setup picker.
            const active = availableModelProfiles.filter(m => m.has_api_key);

            for (const m of availableModelProfiles) {
                // Legacy "codex" profile is hidden from the picker — the real
                // ChatGPT OAuth path is the "openai_codex" profile.
                if (safeString(m.name).toLowerCase() === 'codex') continue;

                const displayName = formatProviderDisplay(m.name) || m.name;

                const providerOption = document.createElement('option');
                providerOption.value = m.name;          // internal value unchanged
                providerOption.textContent = displayName;
                setupProviderSelector.appendChild(providerOption);

                const legacyOption = document.createElement('option');
                legacyOption.value = m.name;            // internal value unchanged
                legacyOption.textContent = displayName;
                modelSelector.appendChild(legacyOption);
            }

            // Determine target profile: saved active preference > localStorage backup > server default > first connected
            const savedProfile = safeString(currentPreferences?.advanced?.model?.active_profile)
                || safeString(window.localStorage.getItem('thomas_active_profile'));
            const savedProfileMeta = savedProfile ? availableModelProfiles.find(m => m.name === savedProfile) : null;
            const hasPersistedProfile = Boolean(safeString(currentPreferences?.advanced?.model?.active_profile));
            const savedProfileReady = savedProfileMeta && (savedProfileMeta.has_api_key || savedProfileMeta.active);
            const targetProfile = savedProfileReady
                ? savedProfile
                : (data.default || (active[0] && active[0].name) || (availableModelProfiles[0] && availableModelProfiles[0].name) || '');

            applyProfileSelection(targetProfile, { allowLocalBackup: !hasPersistedProfile });
            renderSetupProviderPickerMenu(targetProfile, { preserveExpanded: false });
            renderChatComposerSubbar();

            refreshEasySetupProfileOptions();
            updateDebugDockSnapshot();
        }
    } catch (e) { console.error("Failed to fetch models", e); }
    if (typeof syncModelSetupCurrentLabel === 'function') syncModelSetupCurrentLabel({ force: true });
}

function initFeatures() {
    if (!document.getElementById('navOfficeBtn')) {
        const navWrap = document.getElementById('workspaceNavItems');
        if (navWrap instanceof HTMLElement) {
            const button = document.createElement('button');
            button.className = 'nav-item';
            button.id = 'navOfficeBtn';
            button.dataset.navMode = 'office';
            button.innerHTML = '<i class="ph ph-buildings"></i> Virtual Office ';
            navWrap.insertBefore(button, navWrap.firstChild);
        }
    }
    initOfficeWorkspace();
    initMissionWorkspace();
    initContentWorkspace();
    initModuleWorkspace();
    void moduleRefreshInstalledPluginNav({ force: true });
    void moduleRefreshMarketplace({ force: true });
    setDebugDockOpen(false, { recordEvent: false });
    const restoredMode = resolveBootNavMode();
    chatListExpanded = loadStoredChatListExpanded();
    applyResponsiveSidebarState();
    setChatListExpanded(chatListExpanded, { persist: false });
    setSidebarNavMode(restoredMode, { persist: false });
    maybeOpenForgeCodeDeepLink();
    if (taskContinuityRefreshBtn) {
        taskContinuityRefreshBtn.addEventListener('click', () => {
            void refreshTaskContinuity({ force: true });
        });
    }
    const taskContinuityToggleBtn = ensureTaskContinuityToggleUi();
    if (taskContinuityToggleBtn) {
        taskContinuityToggleBtn.addEventListener('click', () => {
            const nextCollapsed = !taskContinuityPanel.classList.contains('is-collapsed');
            setTaskContinuityCollapsed(nextCollapsed, { remember: true });
        });
    }
    updateTaskContinuityVisibility({ refresh: true });
    initDebugDockTabs();
    renderDebugEventLog();
    renderDebugConsoleLog();
    renderDebugNetworkLog();
    renderDebugLivePanels();
    updateDebugNetworkSummary();
    startDebugConsoleCapture();
    startDebugNetworkCapture();
    syncLayoutOffsets();
    if (mainContent) {
        mainContent.addEventListener('scroll', normalizeMainContentScroll, { passive: true });
    }
    normalizeMainContentScroll();
    window.addEventListener('resize', () => {
        applyResponsiveSidebarState();
        syncLayoutOffsets();
    });

    const toggleSidebarCollapsed = () => {
        if (!sidebar || isSidebarAnimating()) return;
        startSidebarAnimationLock();
        sidebar.classList.toggle('collapsed');
        if (!isCompactWebLayout()) {
            saveStoredSidebarCollapsed(Boolean(sidebar.classList.contains('collapsed')));
        }
        syncLayoutOffsets();
        pushDebugEvent('layout', sidebar.classList.contains('collapsed') ? 'Collapsed sidebar' : 'Expanded sidebar');
    };

    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', toggleSidebarCollapsed);
    }
    if (sidebarCollapseBtn) {
        sidebarCollapseBtn.addEventListener('click', toggleSidebarCollapsed);
    }

    // Convert pencil button to New Chat button
    if (newChatSidebar) {
        newChatSidebar.innerHTML = '<i class="ph ph-plus"></i>';
        newChatSidebar.title = 'New Chat';
        newChatSidebar.setAttribute('aria-label', 'Start new chat');
        newChatSidebar.addEventListener('click', (event) => {
            ensureSettingsUiClosed();
            createNewSessionAndRefresh();
            if (globalSearchInput) globalSearchInput.value = '';
            setSidebarNavMode('chat');
            setSidebarSearchScope('chat');
        });
    }

    if (navChatBtn) {
        navChatBtn.addEventListener('click', (event) => {
            const isCaretClick = Boolean(event.target instanceof Element && event.target.closest('.nav-chat-caret'));
            if (isCaretClick) {
                event.preventDefault();
                event.stopPropagation();
            }
            ensureSettingsUiClosed();
            if (sidebarNavMode !== 'chat') {
                setSidebarNavMode('chat');
                setSidebarSearchScope('chat');
            }
            setChatListExpanded(!chatListExpanded);
        });
    }

    const navOfficeBtnLive = document.getElementById('navOfficeBtn');
    if (navOfficeBtnLive) {
        navOfficeBtnLive.addEventListener('click', () => {
            ensureSettingsUiClosed();
            setSidebarNavMode('office');
        });
    }

    if (navMissionBtn) {
        navMissionBtn.addEventListener('click', () => {
            ensureSettingsUiClosed();
            setSidebarNavMode('mission');
        });
    }

    const navForgeBtn = document.getElementById('navForgeBtn');
    if (navForgeBtn) {
        navForgeBtn.addEventListener('click', () => {
            ensureSettingsUiClosed();
            setSidebarNavMode('evolution');
        });
    }

    if (navContentBtn) {
        navContentBtn.addEventListener('click', () => {
            ensureSettingsUiClosed();
            setSidebarNavMode('content');
        });
    }

    if (navInfiniteBtn) {
        navInfiniteBtn.addEventListener('click', () => {
            ensureSettingsUiClosed();
            window.open('/companion', '_blank', 'noopener');
        });
    }

        if (sidebarModeButtons.length) {
        sidebarModeButtons.forEach((button) => {
            button.addEventListener('click', () => {
                const mode = normalizeNavMode(button.dataset.navMode);
                if (!MODULE_NAV_MODE_SET.has(mode)) return;
                ensureSettingsUiClosed();
                setSidebarNavMode(mode);
            });
        });
    }

    if (workspaceNavItems) {
        workspaceNavItems.addEventListener('click', (event) => {
            const button = event.target instanceof Element ? event.target.closest('[data-nav-mode]') : null;
            if (!button) return;
            const mode = normalizeNavMode(button.dataset.navMode);
            if (!MODULE_NAV_MODE_SET.has(mode)) return;
            ensureSettingsUiClosed();
            setSidebarNavMode(mode);
        });
    }
    if (pluginNavItems) {
        pluginNavItems.addEventListener('click', (event) => {
            const button = event.target instanceof Element ? event.target.closest('[data-nav-mode]') : null;
            if (!button) return;
            const mode = normalizeNavMode(button.dataset.navMode);
            if (!MODULE_NAV_MODE_SET.has(mode)) return;
            ensureSettingsUiClosed();
            setSidebarNavMode(mode);
        });
    }

    if (globalSearchInput) {
        globalSearchInput.addEventListener('input', () => {
            renderSidebarChatList();
        });
    }

    if (debugDockToggleBtn) {
        debugDockToggleBtn.addEventListener('click', () => {
            if (isDebugDockAnimating()) return;
            const open = Boolean(appRoot?.classList.contains('debug-dock-open'));
            setDebugDockOpen(!open);
        });
    }

    if (debugDockCloseBtn) {
        debugDockCloseBtn.addEventListener('click', () => {
            if (isDebugDockAnimating()) return;
            setDebugDockOpen(false);
        });
    }

    if (debugDockRefreshBtn) {
        debugDockRefreshBtn.addEventListener('click', () => {
            void refreshDebugLiveData({ force: true, reason: 'manual' });
        });
    }

    if (debugCopySnapshotBtn) {
        debugCopySnapshotBtn.addEventListener('click', () => {
            void copyDebugSnapshotToClipboard();
        });
    }

    if (debugOnboardingRepairBtn) {
        debugOnboardingRepairBtn.addEventListener('click', () => {
            void runDebugOnboardingRepairNow();
        });
    }

    if (debugClearEventsBtn) {
        debugClearEventsBtn.addEventListener('click', () => {
            debugEvents = [];
            renderDebugEventLog();
            pushDebugEvent('tools', 'Cleared debug events');
        });
    }

    if (debugClearConsoleBtn) {
        debugClearConsoleBtn.addEventListener('click', () => {
            debugConsoleEntries = [];
            renderDebugConsoleLog();
            updateDebugDockSnapshot();
            pushDebugEvent('tools', 'Cleared console diagnostics');
        });
    }

    if (debugClearNetworkBtn) {
        debugClearNetworkBtn.addEventListener('click', () => {
            debugNetworkEntries = [];
            renderDebugNetworkLog();
            updateDebugNetworkSummary();
            updateDebugDockSnapshot();
            pushDebugEvent('tools', 'Cleared network diagnostics');
        });
    }

    window.addEventListener('resize', syncLayoutOffsets);

    if (chatHistorySelector) {
        chatHistorySelector.addEventListener('change', () => {
            const selectedSession = chatHistorySelector.value;
            if (selectedSession === 'new') {
                createNewSessionAndRefresh();
            } else {
                loadSessionFromHistory(selectedSession);
            }
        });
    }

    if (settingsAdvancedToggle && settingsSuite) {
        settingsAdvancedToggle.addEventListener('change', () => {
            settingsSuite.classList.toggle('advanced-mode', settingsAdvancedToggle.checked);
            updateSettingsSectionNavVisibility();
        });
    }
    initSettingsSectionNavigation();

    bindRangeValue(settingFontSize, settingFontSizeValue, (v) => `${Math.round(v)}px`);
    bindRangeValue(settingVoiceSpeed, settingVoiceSpeedValue, (v) => `${v.toFixed(2)}x`);
    bindRangeValue(settingAdvTemperature, settingAdvTemperatureValue, (v) => v.toFixed(2));
    bindRangeValue(settingAdvTopP, settingAdvTopPValue, (v) => v.toFixed(2));
    bindRangeValue(settingAdvFrequencyPenalty, settingAdvFrequencyPenaltyValue, (v) => v.toFixed(1));
    bindRangeValue(settingAdvPresencePenalty, settingAdvPresencePenaltyValue, (v) => v.toFixed(1));
    bindRangeValue(settingAdvAutoToolThreshold, settingAdvAutoToolThresholdValue, (v) => v.toFixed(2));

    if (changeAvatarBtn && settingsAvatarInput) {
        changeAvatarBtn.addEventListener('click', () => {
            settingsAvatarInput.click();
        });
    }

    if (settingsAvatarInput) {
        settingsAvatarInput.addEventListener('change', () => {
            const file = settingsAvatarInput.files && settingsAvatarInput.files[0];
            if (!file) return;
            if (!file.type.startsWith('image/')) {
                notifyUser('Please choose an image file for your profile photo.', {
                    tone: 'warning',
                    debugKind: 'warning',
                    durationMs: 2800,
                });
                settingsAvatarInput.value = '';
                return;
            }
            const reader = new FileReader();
            reader.onload = (event) => {
                pendingAvatarOverride = safeString(event.target?.result);
                refreshSettingsAvatarPreview();
            };
            reader.readAsDataURL(file);
            settingsAvatarInput.value = '';
        });
    }

    if (removeAvatarBtn) {
        removeAvatarBtn.addEventListener('click', () => {
            pendingAvatarOverride = '';
            refreshSettingsAvatarPreview();
        });
    }

    if (settingsDisplayName) {
        settingsDisplayName.addEventListener('input', refreshSettingsAvatarPreview);
    }

    if (settingsBtn && settingsModal) {
        settingsBtn.addEventListener('click', () => {
            openSettingsModal();
        });
    }

    if (closeSettingsBtn && settingsModal) {
        closeSettingsBtn.addEventListener('click', closeSettingsModal);
    }

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveSettings);
    }

    initModelSetup();
    startRuntimeGuardMonitor();
    pushDebugEvent('runtime', 'UI initialized');
}

// 
//   MODEL SETUP & SETTINGS                                                 
//   Model selector, profile switching, settings form, save/load prefs      
// 

