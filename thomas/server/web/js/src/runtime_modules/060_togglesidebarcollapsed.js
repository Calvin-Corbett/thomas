// Extracted from part-031.js
// From togglesidebarcollapsed

            void refreshTaskContinuity({ force: true });
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
    window.addEventListener('resize', syncLayoutOffsets);

    const stripNavChatRobot = () => {
        if (!(navChatBtn instanceof HTMLElement)) return;
        const label = navChatBtn.querySelector('.nav-chat-label');
        if (!(label instanceof HTMLElement)) return;
        label.querySelectorAll('.nav-chat-robot-wrap, .nav-chat-robot, .pixel-agent').forEach((node) => node.remove());
        Array.from(label.children).forEach((child) => {
            if (child.tagName === 'I') {
                child.remove();
            }
        });
    };

    stripNavChatRobot();
    if (typeof MutationObserver === 'function' && navChatBtn instanceof HTMLElement) {
        const navChatRobotObserver = new MutationObserver(() => {
            stripNavChatRobot();
        });
        navChatRobotObserver.observe(navChatBtn, { childList: true, subtree: true });
    }
    const toggleSidebarCollapsed = () => {
        if (!sidebar || isSidebarAnimating()) return;
        startSidebarAnimationLock();
        sidebar.classList.toggle('collapsed');
        saveStoredSidebarCollapsed(Boolean(sidebar.classList.contains('collapsed')));
        syncLayoutOffsets();
        pushDebugEvent('layout', sidebar.classList.contains('collapsed') ? 'Collapsed sidebar' : 'Expanded sidebar');
    };

    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', toggleSidebarCollapsed);
    }
    if (sidebarCollapseBtn) {
        sidebarCollapseBtn.addEventListener('click', toggleSidebarCollapsed);
    }

    if (newChatSidebar) {
        newChatSidebar.addEventListener('click', (event) => {
            const wantsNewChat = Boolean(event && (event.shiftKey || event.metaKey || event.ctrlKey));
            if (wantsNewChat) {
                ensureSettingsUiClosed();
                createNewSessionAndRefresh();
                if (globalSearchInput) globalSearchInput.value = '';
                setSidebarNavMode('chat');
                setSidebarSearchScope('chat');
                return;
            }
            void promptRenameAgentIdentity();
        });
    }

    if (navChatBtn) {
        navChatBtn.addEventListener('click', (event) => {
            const isCaretClick = Boolean(event.target instanceof Element && event.target.closest('.nav-chat-caret'));
            if (isCaretClick) {
                event.preventDefault();
                event.stopPropagation();
                if (sidebarNavMode !== 'chat') {
                    ensureSettingsUiClosed();
                    setSidebarNavMode('chat');
                    setSidebarSearchScope('chat');
                }
                setChatListExpanded(!chatListExpanded);
                return;
            }
            ensureSettingsUiClosed();
            setSidebarNavMode('chat');
            setSidebarSearchScope('chat');
            if (globalSearchInput) globalSearchInput.focus();
        });
    }

    if (navOfficeBtn) {
        navOfficeBtn.addEventListener('click', () => {
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