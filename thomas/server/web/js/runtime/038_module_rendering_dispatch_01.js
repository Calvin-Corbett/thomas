function initModuleWorkspace() {
    const state = moduleEnsureRuntime();
    if (!state || state.controlsBound) return;
    state.controlsBound = true;
    if (moduleWorkspace) {
        moduleWorkspace.addEventListener('scroll', moduleSyncSurfaceScrollState, { passive: true });
        window.setTimeout(moduleSyncSurfaceScrollState, 0);
    }

    const itemActionHandler = async (event) => {
        const target = event.target instanceof Element ? event.target.closest('.module-item-btn[data-module-action-id]') : null;
        if (!target) return;
        const mode = MODULE_NAV_MODE_SET.has(target.dataset.moduleMode) ? target.dataset.moduleMode : (state.activeMode || 'dashboard');
        const section = safeString(target.dataset.moduleSection).toLowerCase() || 'queue';
        const itemId = safeString(target.dataset.moduleItemId);
        const actionId = safeString(target.dataset.moduleActionId).toLowerCase();
        const actionLabel = safeString(target.dataset.moduleActionLabel) || 'Action';
        const actionUrl = safeString(target.dataset.moduleActionUrl);
                if (mode === 'marketplace' && itemId) {
            if (target instanceof HTMLButtonElement) target.disabled = true;
            try {
                if (actionId === 'enable' || actionId === 'disable') {
                    const result = await moduleSetMarketplacePluginEnabled(itemId, actionId === 'enable');
                    if (!result?.ok) throw new Error(result?.error || `${actionLabel} failed.`);
                    await moduleRefreshMarketplace({ force: true });
                    if (actionId === 'enable' && result?.plugin?.mode_id) {
                        setSidebarNavMode(result.plugin.mode_id);
                    }
                    moduleRecordActivity(mode, `${actionLabel} completed for ${itemId || 'item'}.`, 'ok');
                    moduleTouch(mode);
                    moduleRender(mode, { touch: false });
                    notifyUser(`${actionLabel} completed.`, { tone: 'success', durationMs: 1500, debugKind: actionId || 'module-action' });
                    return;
                }
                if (actionId === 'open') {
                    const currentApp = Array.isArray(state.marketplace?.apps)
                        ? state.marketplace.apps.find((app) => safeString(app?.module_id) === itemId)
                        : null;
                    if (!currentApp) {
                        throw new Error('This workspace is no longer in the marketplace catalog.');
                    }
                    let modeId = safeString(currentApp?.mode_id);
                    if (currentApp?.installed && !currentApp?.enabled) {
                        const enableResult = await moduleSetMarketplacePluginEnabled(itemId, true);
                        if (!enableResult?.ok) throw new Error(enableResult?.error || 'Open failed.');
                        await moduleRefreshMarketplace({ force: true });
                        modeId = safeString(enableResult?.plugin?.mode_id || modeId);
                    } else {
                        await moduleRefreshMarketplace({ force: true });
                    }
                    if (!modeId) {
                        throw new Error('This workspace is installed, but it does not expose an app surface yet.');
                    }
                    setSidebarNavMode(modeId);
                    moduleRecordActivity(mode, `${actionLabel} completed for ${itemId || 'item'}.`, 'ok');
                    moduleTouch(mode);
                    moduleRender(mode, { touch: false });
                    notifyUser(`${actionLabel} completed.`, { tone: 'success', durationMs: 1500, debugKind: actionId || 'module-action' });
                    return;
                }
                if (actionId === 'install') {
                    const currentApp = Array.isArray(state.marketplace?.apps)
                        ? state.marketplace.apps.find((app) => safeString(app?.module_id) === itemId)
                        : null;
                    const installPayload = {};
                    if (safeString(currentApp?.install?.store_url)) installPayload.store_url = safeString(currentApp.install.store_url);
                    if (safeString(currentApp?.install?.channel)) installPayload.channel = safeString(currentApp.install.channel);
                    const result = await moduleInstallMarketplacePlugin(itemId, installPayload);
                    if (!result?.ok) throw new Error(result?.error || `${actionLabel} failed.`);
                    await moduleRefreshMarketplace({ force: true });
                    if (result?.plugin?.mode_id) {
                        setSidebarNavMode(result.plugin.mode_id);
                    }
                    moduleRecordActivity(mode, `${actionLabel} completed for ${itemId || 'item'}.`, 'ok');
                    moduleTouch(mode);
                    moduleRender('marketplace', { touch: false });
                    notifyUser(`${actionLabel} completed.`, { tone: 'success', durationMs: 1500, debugKind: actionId || 'module-action' });
                    return;
                }
                if (actionId === 'uninstall') {
                    const result = await moduleUninstallMarketplacePlugin(itemId);
                    if (!result?.ok) throw new Error(result?.error || `${actionLabel} failed.`);
                    await moduleRefreshMarketplace({ force: true });
                    if (safeString(sidebarNavMode) === safeString(moduleInstalledPluginForMode(sidebarNavMode)?.mode_id)) {
                        setSidebarNavMode('marketplace');
                    }
                    moduleRecordActivity(mode, `${actionLabel} completed for ${itemId || 'item'}.`, 'ok');
                    moduleTouch(mode);
                    moduleRender('marketplace', { touch: false });
                    notifyUser(`${actionLabel} completed.`, { tone: 'success', durationMs: 1500, debugKind: actionId || 'module-action' });
                    return;
                }
                if (actionId === 'download' || actionId === 'latest') {
                    if (!actionUrl) {
                        throw new Error('No action URL is configured for this item.');
                    }
                    const opened = window.open(actionUrl, '_blank', 'noopener,noreferrer');
                    if (!opened) {
                        window.location.href = actionUrl;
                    } else {
                        opened.opener = null;
                    }
                    moduleRecordActivity(mode, `${actionLabel} opened for ${itemId || 'item'}.`, 'ok');
                    moduleTouch(mode);
                    moduleRender(mode, { touch: false });
                    notifyUser(`${actionLabel} opened.`, { tone: 'info', durationMs: 1500, debugKind: actionId || 'module-action' });
                    return;
                }
            } catch (error) {
                moduleRecordActivity(mode, `${actionLabel} failed for ${itemId || 'item'}.`, 'error');
                notifyUser(error?.message || `${actionLabel} failed.`, { tone: 'error', durationMs: 2200, debugKind: actionId || 'module-action' });
                return;
            } finally {
                if (target instanceof HTMLButtonElement) target.disabled = false;
            }
        }
        if (MODULE_ITEM_DISMISS_ACTIONS.has(actionId)) {
            moduleHideItem(mode, section, itemId);
        }
        moduleRecordActivity(mode, `${actionLabel} ran for ${itemId || 'item'}.`, MODULE_ITEM_DISMISS_ACTIONS.has(actionId) ? 'warn' : 'ok');
        moduleTouch(mode);
        moduleRender(mode, { touch: false });
        notifyUser(`${actionLabel} executed.`, { tone: 'info', durationMs: 1500, debugKind: actionId || 'module-action' });
    };

    if (moduleQueueList) {
        moduleQueueList.addEventListener('click', itemActionHandler);
        moduleQueueList.addEventListener('input', (event) => {
            const target = event.target instanceof Element ? event.target.closest('input[data-module-marketplace-search][data-module-mode]') : null;
            if (!(target instanceof HTMLInputElement)) return;
            const mode = MODULE_NAV_MODE_SET.has(target.dataset.moduleMode) ? target.dataset.moduleMode : (state.activeMode || 'dashboard');
            if (mode !== 'marketplace') return;
            if (!state.marketplace || typeof state.marketplace !== 'object') return;
            const nextSearch = safeString(target.value);
            if (safeString(state.marketplace.search) === nextSearch) return;
            const selectionStart = typeof target.selectionStart === 'number' ? target.selectionStart : nextSearch.length;
            const selectionEnd = typeof target.selectionEnd === 'number' ? target.selectionEnd : selectionStart;
            state.marketplace.search = nextSearch;
            state.marketplace.searchSelectionStart = selectionStart;
            state.marketplace.searchSelectionEnd = selectionEnd;
            state.marketplace.focusSearchUntil = Date.now() + 2000;
            moduleTouch(mode);
            moduleRender(mode, { touch: false });
            window.requestAnimationFrame(() => {
                const searchInput = moduleQueueList.querySelector('input[data-module-marketplace-search][data-module-mode="marketplace"]');
                if (!(searchInput instanceof HTMLInputElement)) return;
                searchInput.focus({ preventScroll: true });
                const nextStart = Math.max(0, Math.min(selectionStart, searchInput.value.length));
                const nextEnd = Math.max(nextStart, Math.min(selectionEnd, searchInput.value.length));
                try {
                    searchInput.setSelectionRange(nextStart, nextEnd);
                } catch (_error) {}
            });
        });
        moduleQueueList.addEventListener('click', (event) => {
            const clearButton = event.target instanceof Element ? event.target.closest('[data-module-marketplace-clear][data-module-mode]') : null;
            if (!clearButton) return;
            const mode = MODULE_NAV_MODE_SET.has(clearButton.dataset.moduleMode) ? clearButton.dataset.moduleMode : (state.activeMode || 'dashboard');
            if (mode !== 'marketplace') return;
            if (state.marketplace && typeof state.marketplace === 'object') {
                state.marketplace.search = '';
                state.marketplace.searchSelectionStart = 0;
                state.marketplace.searchSelectionEnd = 0;
                state.marketplace.focusSearchUntil = Date.now() + 2000;
            }
            const searchInput = moduleQueueList.querySelector('input[data-module-marketplace-search][data-module-mode="marketplace"]');
            if (searchInput instanceof HTMLInputElement) {
                searchInput.value = '';
            }
            moduleTouch(mode);
            moduleRender(mode, { touch: false });
            window.requestAnimationFrame(() => {
                const nextInput = moduleQueueList.querySelector('input[data-module-marketplace-search][data-module-mode="marketplace"]');
                if (!(nextInput instanceof HTMLInputElement)) return;
                nextInput.focus({ preventScroll: true });
                try {
                    nextInput.setSelectionRange(0, 0);
                } catch (_error) {}
            });
        });
        moduleQueueList.addEventListener('click', async (event) => {
            const refreshButton = event.target instanceof Element ? event.target.closest('[data-module-marketplace-refresh][data-module-mode]') : null;
            if (!refreshButton) return;
            const mode = MODULE_NAV_MODE_SET.has(refreshButton.dataset.moduleMode) ? refreshButton.dataset.moduleMode : (state.activeMode || 'dashboard');
            if (mode !== 'marketplace') return;
            if (refreshButton instanceof HTMLButtonElement) refreshButton.disabled = true;
            try {
                await moduleRefreshMarketplace({ force: true });
            } finally {
                if (refreshButton instanceof HTMLButtonElement) refreshButton.disabled = false;
            }
            moduleTouch(mode);
            moduleRender(mode, { touch: false });
        });
        moduleQueueList.addEventListener('click', (event) => {
            const filterButton = event.target instanceof Element ? event.target.closest('[data-module-marketplace-filter][data-module-mode]') : null;
            if (!filterButton) return;
            const mode = MODULE_NAV_MODE_SET.has(filterButton.dataset.moduleMode) ? filterButton.dataset.moduleMode : (state.activeMode || 'dashboard');
            if (mode !== 'marketplace' || !state.marketplace || typeof state.marketplace !== 'object') return;
            const nextFilter = safeString(filterButton.dataset.moduleMarketplaceFilter).toLowerCase() || 'all';
            if (safeString(state.marketplace.filter).toLowerCase() === nextFilter) return;
            state.marketplace.filter = nextFilter;
            state.marketplace.selectedId = '';
            moduleRender(mode, { touch: false });
        });
        moduleQueueList.addEventListener('click', (event) => {
            const selectButton = event.target instanceof Element ? event.target.closest('[data-module-marketplace-select][data-module-mode]') : null;
            if (!selectButton) return;
            const mode = MODULE_NAV_MODE_SET.has(selectButton.dataset.moduleMode) ? selectButton.dataset.moduleMode : (state.activeMode || 'dashboard');
            if (mode !== 'marketplace' || !state.marketplace || typeof state.marketplace !== 'object') return;
            const nextId = safeString(selectButton.dataset.moduleMarketplaceSelect);
            if (!nextId || safeString(state.marketplace.selectedId) === nextId) return;
            state.marketplace.selectedId = nextId;
            moduleRender(mode, { touch: false });
        });
                moduleQueueList.addEventListener('click', async (event) => {
            const copyButton = event.target instanceof Element ? event.target.closest('[data-module-marketplace-copy-id][data-module-mode]') : null;
            if (!copyButton) return;
            const mode = MODULE_NAV_MODE_SET.has(copyButton.dataset.moduleMode) ? copyButton.dataset.moduleMode : (state.activeMode || 'dashboard');
            if (mode !== 'marketplace') return;
            const pluginId = safeString(copyButton.dataset.moduleMarketplaceCopyId);
            if (!pluginId) return;
            try {
                await navigator.clipboard.writeText(pluginId);
                notifyUser('Plugin ID copied.', { tone: 'success', durationMs: 1200, debugKind: 'copy-plugin-id' });
            } catch (_error) {
                notifyUser('Copy failed.', { tone: 'error', durationMs: 1600, debugKind: 'copy-plugin-id' });
            }
        });
        moduleQueueList.addEventListener('click', (event) => {
            const importButton = event.target instanceof Element ? event.target.closest('[data-marketplace-import][data-module-mode]') : null;
            if (!importButton) return;
            const fileInput = moduleQueueList.querySelector('input[data-marketplace-import-input]');
            if (fileInput instanceof HTMLInputElement) {
                fileInput.click();
            }
        });
        moduleQueueList.addEventListener('change', async (event) => {
            const input = event.target;
            if (!(input instanceof HTMLInputElement) || !input.matches('input[data-marketplace-import-input]')) return;
            const file = input.files && input.files[0] ? input.files[0] : null;
            if (!file) return;
            const result = await moduleImportMarketplacePlugin(file);
            input.value = '';
            if (!result?.ok) {
                notifyUser(result?.error || 'Import failed.', { tone: 'error', durationMs: 2200, debugKind: 'marketplace-import' });
                return;
            }
            await moduleRefreshMarketplace({ force: true });
            if (result?.plugin?.mode_id) {
                setSidebarNavMode(result.plugin.mode_id);
            } else {
                moduleRender('marketplace', { touch: false });
            }
            notifyUser('Plugin imported.', { tone: 'success', durationMs: 1500, debugKind: 'marketplace-import' });
        });
        moduleQueueList.addEventListener('input', (event) => {
            const target = event.target instanceof Element ? event.target.closest('input[data-channels-search]') : null;
            if (!(target instanceof HTMLInputElement)) return;
            const channelsState = moduleChannelsState();
            if (!channelsState) return;
            channelsState.search = safeString(target.value);
        });
        moduleQueueList.addEventListener('click', (event) => {
            const tile = event.target instanceof Element ? event.target.closest('[data-channel-card-select]') : null;
            if (!tile) return;
            const channelsState = moduleChannelsState();
            if (!channelsState) return;
            const nextId = safeString(tile.getAttribute('data-channel-card-select')).toLowerCase();
            if (!nextId) return;
            channelsState.selectedChannelId = nextId;
            channelsState.detailOpen = true;
            moduleRender('channels', { touch: false });
        });
        moduleQueueList.addEventListener('dragstart', (event) => {
            const tile = event.target instanceof Element ? event.target.closest('[data-channel-card-id]') : null;
            if (!(tile instanceof HTMLElement)) return;
            moduleChannelsDraggedCardId = safeString(tile.getAttribute('data-channel-card-id')).toLowerCase();
            tile.classList.add('is-dragging');
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', moduleChannelsDraggedCardId);
            }
        });
        moduleQueueList.addEventListener('dragend', () => {
            moduleChannelsDraggedCardId = '';
            moduleQueueList.querySelectorAll('.module-channel-card.is-dragging').forEach((node) => node.classList.remove('is-dragging'));
            modulePersistChannelsCatalogOrderFromDom();
        });
        moduleQueueList.addEventListener('dragover', (event) => {
            const draggedId = moduleChannelsDraggedCardId || (event.dataTransfer ? safeString(event.dataTransfer.getData('text/plain')).toLowerCase() : '');
            if (!draggedId) return;
            const grid = event.target instanceof Element ? event.target.closest('[data-channel-grid]') : null;
            const target = event.target instanceof Element ? event.target.closest('[data-channel-card-id]') : null;
            if (!(grid instanceof HTMLElement) || !(target instanceof HTMLElement)) return;
            const dragged = Array.from(grid.querySelectorAll('[data-channel-card-id]')).find((node) => safeString(node.getAttribute('data-channel-card-id')).toLowerCase() === draggedId);
            if (!(dragged instanceof HTMLElement) || dragged === target) return;
            event.preventDefault();
            const rect = target.getBoundingClientRect();
            const after = event.clientX > rect.left + (rect.width / 2);
            grid.insertBefore(dragged, after ? target.nextSibling : target);
        });
        moduleQueueList.addEventListener('drop', (event) => {
            const grid = event.target instanceof Element ? event.target.closest('[data-channel-grid]') : null;
            if (!(grid instanceof HTMLElement)) return;
            event.preventDefault();
            modulePersistChannelsCatalogOrderFromDom();
            moduleChannelsDraggedCardId = '';
            moduleRender('channels', { touch: false });
        });
        moduleQueueList.addEventListener('click', async (event) => {
            const actionButton = event.target instanceof Element ? event.target.closest('[data-channels-action]') : null;
            if (!actionButton) return;
            const actionId = safeString(actionButton.dataset.channelsAction).toLowerCase();
            const channelsState = moduleChannelsState();
            if (!channelsState) return;
            if (actionButton instanceof HTMLButtonElement) actionButton.disabled = true;
            try {
                if (actionId === 'refresh') {
                    await moduleRefreshChannels({ force: true });
                    notifyUser('Discord channel state refreshed.', { tone: 'success', durationMs: 1400, debugKind: 'channels-refresh' });
                    return;
                }
                if (actionId === 'back_to_catalog') {
                    channelsState.detailOpen = false;
                    moduleRender('channels', { touch: false });
                    return;
                }
                if (actionId === 'clear_search') {
                    channelsState.search = '';
                    const searchInput = moduleQueueList.querySelector('input[data-channels-search]');
                    if (searchInput instanceof HTMLInputElement) searchInput.value = '';
                    await moduleRefreshChannels({ force: true });
                    return;
                }
                if (actionId === 'search') {
                    await moduleRefreshChannels({ force: true });
                    return;
                }
                if (actionId === 'configure_channel') {
                    const channelId = safeString(actionButton.dataset.channelsChannelId).toLowerCase();
                    const entry = MODULE_CHANNEL_CATALOG.find((item) => item.id === channelId) || MODULE_CHANNEL_CATALOG[0];
                    const prompt = moduleBuildChannelsConfigurePrompt(entry);
                    if (composerTextarea instanceof HTMLTextAreaElement && typeof handleSend === 'function') {
                        setSidebarNavMode('chat');
                        composerTextarea.value = prompt;
                        composerTextarea.dispatchEvent(new Event('input'));
                        composerTextarea.focus();
                        await handleSend();
                        notifyUser(`${safeString(entry?.title) || 'Channel'} setup prompt sent to Thomas.`, {
                            tone: 'success',
                            durationMs: 1800,
                            debugKind: 'channels-configure',
                        });
                        return;
                    }
                    throw new Error('Chat composer is not available right now.');
                }
                if (actionId === 'toggle_enabled') {
                    const nextEnabled = !(channelsState?.status?.bridge?.enabled);
                    await moduleFetchJsonSafe('/api/channels/discord/enabled', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: nextEnabled }),
                    });
                    await moduleRefreshChannels({ force: true });
                    notifyUser(`Discord channel turned ${nextEnabled ? 'on' : 'off'}.`, {
                        tone: nextEnabled ? 'success' : 'warning',
                        durationMs: 1500,
                        debugKind: 'channels-enabled',
                    });
                    return;
                }
                if (actionId === 'start' || actionId === 'stop' || actionId === 'restart') {
                    await moduleFetchJsonSafe(`/api/channels/discord/${actionId}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({}),
                    });
                    await moduleRefreshChannels({ force: true });
                    notifyUser(`Discord bridge ${actionId} completed.`, {
                        tone: actionId === 'stop' ? 'warning' : 'success',
                        durationMs: 1500,
                        debugKind: `channels-${actionId}`,
                    });
                    return;
                }
                if (actionId === 'voice_probe') {
                    channelsState.voiceProbeRunning = true;
                    moduleRender('channels', { touch: false });
                    const payload = await moduleFetchJsonSafe('/api/channels/discord/voice-probe', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            wake: 'Hey Thomas, how are you?',
                            speaker_name: 'Thomas Channels UI Probe',
                            speaker_id: safeString(channelsState?.status?.config?.owner_user_ids?.[0]) || 'owner-probe',
                        }),
                    });
                    channelsState.voiceProbeResult = payload?.probe ? { ...payload.probe, duration_ms: payload?.duration_ms } : null;
                    channelsState.status = payload?.discord || channelsState.status;
                    channelsState.detailOpen = true;
                    notifyUser(
                        payload?.probe?.reply_matches_transcript
                            ? 'Discord wake probe matched the spoken transcript.'
                            : 'Discord wake probe completed, but the transcript needs review.',
                        {
                            tone: payload?.probe?.reply_matches_transcript ? 'success' : 'warning',
                            durationMs: 2200,
                            debugKind: 'channels-voice-probe',
                        },
                    );
                    return;
                }
                if (actionId === 'save_voice_settings') {
                    const bridgeRunning = Boolean(channelsState?.status?.bridge?.running);
                    const runtimePayload = {};
                    moduleQueueList.querySelectorAll('[data-channels-runtime-field]').forEach((field) => {
                        const key = safeString(field.getAttribute('data-channels-runtime-field'));
                        if (!key) return;
                        if (field instanceof HTMLInputElement && field.type === 'checkbox') {
                            runtimePayload[key] = Boolean(field.checked);
                            return;
                        }
                        const value = field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement
                            ? safeString(field.value)
                            : '';
                        runtimePayload[key] = value;
                    });
                    const voiceConfigPayload = {};
                    moduleQueueList.querySelectorAll('[data-channels-voice-config-field]').forEach((field) => {
                        const key = safeString(field.getAttribute('data-channels-voice-config-field'));
                        if (!key) return;
                        const value = field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement
                            ? safeString(field.value)
                            : '';
                        voiceConfigPayload[key] = value;
                    });
                    if (Object.keys(voiceConfigPayload).length) {
                        await moduleFetchJsonSafe('/api/channels/discord/config', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(voiceConfigPayload),
                        });
                    }
                    await moduleFetchJsonSafe('/api/channels/discord/runtime', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(runtimePayload),
                    });
                    await moduleRefreshChannels({ force: true });
                    notifyUser(
                        bridgeRunning
                            ? 'Discord voice and speech settings saved and reapplied.'
                            : 'Discord voice and speech settings saved for the next bridge launch.',
                        {
                        tone: 'success',
                        durationMs: 1700,
                        debugKind: 'channels-voice-settings',
                        },
                    );
                    return;
                }
                if (actionId === 'save_config') {
                    const payload = {};
                    moduleQueueList.querySelectorAll('[data-channels-config-field]').forEach((field) => {
                        const key = safeString(field.getAttribute('data-channels-config-field'));
                        if (!key) return;
                        if (field instanceof HTMLInputElement && field.type === 'checkbox') {
                            payload[key] = Boolean(field.checked);
                            return;
                        }
                        const value = field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement
                            ? safeString(field.value)
                            : '';
                        if (!value && (key === 'bot_token' || key === 'thomas_api_token')) return;
                        payload[key] = value;
                    });
                    await moduleFetchJsonSafe('/api/channels/discord/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    await moduleRefreshChannels({ force: true });
                    notifyUser('Discord bridge config saved.', { tone: 'success', durationMs: 1500, debugKind: 'channels-config' });
                    return;
                }
            } catch (error) {
                notifyUser(safeString(error?.message) || 'Discord channels action failed.', {
                    tone: 'error',
                    durationMs: 2200,
                    debugKind: 'channels-action',
                });
            } finally {
                channelsState.voiceProbeRunning = false;
                if (actionButton instanceof HTMLButtonElement) actionButton.disabled = false;
            }
        });
        moduleQueueList.addEventListener('click', async (event) => {
            const sessionButton = event.target instanceof Element ? event.target.closest('[data-channels-session-id]') : null;
            if (!sessionButton) return;
            const sessionId = safeString(sessionButton.getAttribute('data-channels-session-id'));
            if (!sessionId) return;
            await moduleLoadChannelsSession(sessionId);
        });
    }
    if (moduleHealthList) moduleHealthList.addEventListener('click', itemActionHandler);
    if (moduleActivityList) moduleActivityList.addEventListener('click', itemActionHandler);
    if (moduleTriageMessages) moduleTriageMessages.addEventListener('click', itemActionHandler);

    if (moduleActionsGrid) {
        moduleActionsGrid.addEventListener('click', (event) => {
            const target = event.target instanceof Element ? event.target.closest('.module-action-btn[data-module-action-id]') : null;
            if (!target) return;
            const mode = MODULE_NAV_MODE_SET.has(target.dataset.moduleMode) ? target.dataset.moduleMode : (state.activeMode || 'dashboard');
            const label = safeString(target.dataset.moduleActionLabel) || 'Action';
            const actionId = safeString(target.dataset.moduleActionId).toLowerCase();
            if (mode === 'vibe_code') {
                if (actionId === 'switch_chat') {
                    setSidebarNavMode('chat');
                    if (composerTextarea) composerTextarea.focus();
                    notifyUser('Switched to chat. Send a message to animate the flow.', { tone: 'info', durationMs: 1700, debugKind: 'vibe-code' });
                    return;
                }
                if (actionId === 'disconnect_edges') {
                    const disconnected = vibeCodeSetVisibleEdgesDisconnected(true);
                    vibeCodeRender();
                    moduleRecordActivity(mode, `Disconnected ${disconnected} visible edge${disconnected === 1 ? '' : 's'}.`, 'warn');
                    moduleTouch(mode);
                    moduleRender(mode, { touch: false });
                    notifyUser(`${disconnected} visible edge${disconnected === 1 ? '' : 's'} disconnected.`, { tone: 'warning', durationMs: 1600, debugKind: 'vibe-code' });
                    return;
                }
                if (actionId === 'reconnect_edges') {
                    const reconnected = vibeCodeSetVisibleEdgesDisconnected(false);
                    vibeCodeRender();
                    moduleRecordActivity(mode, `Reconnected ${reconnected} visible edge${reconnected === 1 ? '' : 's'}.`, 'ok');
                    moduleTouch(mode);
                    moduleRender(mode, { touch: false });
                    notifyUser(`${reconnected} visible edge${reconnected === 1 ? '' : 's'} reconnected.`, { tone: 'success', durationMs: 1500, debugKind: 'vibe-code' });
                    return;
                }
                if (actionId === 'reset_trace') {
                    vibeCodeState.activeTraceId = '';
                    vibeCodeRender();
                    moduleRecordActivity(mode, 'Cleared active trace view.', 'warn');
                    moduleTouch(mode);
                    moduleRender(mode, { touch: false });
                    notifyUser('Active trace reset.', { tone: 'info', durationMs: 1500, debugKind: 'vibe-code' });
                    return;
                }
            }
            moduleRecordActivity(mode, `${label} queued from ${moduleSeed(mode).title}.`, 'ok');
            moduleTouch(mode);
            moduleRender(mode, { touch: false });
            notifyUser(`${label} queued.`, { tone: 'success', durationMs: 1500, debugKind: actionId || 'module-action' });
        });
    }

    if (moduleTriageFilters) {
        moduleTriageFilters.addEventListener('click', (event) => {
            const target = event.target instanceof Element ? event.target.closest('[data-module-filter]') : null;
            if (!target) return;
            const mode = MODULE_NAV_MODE_SET.has(target.dataset.moduleMode) ? target.dataset.moduleMode : (state.activeMode || 'dashboard');
            const filter = safeString(target.dataset.moduleFilter).toLowerCase() || 'all';
            state.triageFilters[mode] = filter;
            moduleTouch(mode);
            moduleRender(mode, { touch: false });
        });
    }

    if (moduleSubnavList) {
        moduleSubnavList.addEventListener('click', (event) => {
            const target = event.target instanceof Element ? event.target.closest('.module-subnav-chip[data-module-section-label]') : null;
            if (!target) return;
            const mode = MODULE_NAV_MODE_SET.has(target.dataset.moduleMode) ? target.dataset.moduleMode : (state.activeMode || 'dashboard');
            const sectionLabel = safeString(target.dataset.moduleSectionLabel) || 'Section';
            state.subnavFocus[mode] = sectionLabel;
            moduleRecordActivity(mode, `Focused ${sectionLabel}.`, 'ok');
            moduleTouch(mode);
            moduleRender(mode, { touch: false });
        });
    }

    state.timerId = window.setInterval(() => {
        if (!MODULE_NAV_MODE_SET.has(sidebarNavMode)) return;
        moduleRender(sidebarNavMode);
    }, MODULE_REFRESH_INTERVAL_MS);

    moduleRender('dashboard', { touch: false });
}

function isUiEditorPreviewShell() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        return params.get('ui_editor_preview') === '1';
    } catch {
        return false;
    }
}

function loadRequestedNavModeFromUrl() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        if (params.get('ui_editor_preview') === '1') {
            return 'chat';
        }
        if (params.has('thomas_deep_link') || (params.has('plugin_id') && params.has('store'))) {
            return 'marketplace';
        }
        if (!params.has('nav')) return '';
        return normalizeNavMode(params.get('nav'));
    } catch {
        return '';
    }
}

function loadRequestedPluginInstallDeepLinkFromUrl() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        const deepLink = safeString(params.get('thomas_deep_link'));
        if (deepLink) return deepLink;
        const pluginId = safeString(params.get('plugin_id'));
        const store = safeString(params.get('store'));
        const channel = safeString(params.get('channel')) || 'stable';
        if (!pluginId || !store) return '';
        return `thomas://install-plugin?plugin_id=${encodeURIComponent(pluginId)}&store=${encodeURIComponent(store)}&channel=${encodeURIComponent(channel)}`;
    } catch {
        return '';
    }
}

function clearRequestedPluginInstallFromUrl() {
    try {
        const url = new URL(window.location.href);
        let changed = false;
        ['thomas_deep_link', 'plugin_id', 'store', 'channel'].forEach((key) => {
            if (url.searchParams.has(key)) {
                url.searchParams.delete(key);
                changed = true;
            }
        });
        if (!changed) return;
        if (safeString(url.searchParams.get('nav')).toLowerCase() === 'marketplace') {
            url.searchParams.delete('nav');
        }
        const nextSearch = url.searchParams.toString();
        const nextUrl = `${url.pathname}${nextSearch ? `?${nextSearch}` : ''}${url.hash || ''}`;
        window.history.replaceState(window.history.state, document.title, nextUrl);
    } catch {
        // Ignore URL rewrite failures.
    }
}

function resolveBootNavMode() {
    const requested = loadRequestedNavModeFromUrl();
    if (requested) return requested;
    const stored = loadStoredNavMode();
    return stored === 'app_builder' ? 'chat' : stored;
}

function loadStoredNavMode() {
    try {
        const requested = loadRequestedNavModeFromUrl();
        if (requested) return requested;
        if (!window?.localStorage) return 'chat';
        return normalizeNavMode(window.localStorage.getItem(UI_NAV_MODE_STORAGE_KEY));
    } catch {
        return 'chat';
    }
}

function saveStoredNavMode(modeRaw) {
    const mode = normalizeNavMode(modeRaw);
    try {
        if (!window?.localStorage || isUiEditorPreviewShell()) return;
        window.localStorage.setItem(UI_NAV_MODE_STORAGE_KEY, mode);
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredSidebarCollapsed() {
    try {
        if (!window?.localStorage) return false;
        return window.localStorage.getItem(UI_SIDEBAR_COLLAPSED_STORAGE_KEY) === '1';
    } catch {
        return false;
    }
}

function saveStoredSidebarCollapsed(collapsed) {
    try {
        if (!window?.localStorage) return;
        window.localStorage.setItem(UI_SIDEBAR_COLLAPSED_STORAGE_KEY, collapsed ? '1' : '0');
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredChatListExpanded() {
    try {
        if (!window?.localStorage) return true;
        const raw = window.localStorage.getItem(UI_CHAT_LIST_EXPANDED_STORAGE_KEY);
        if (raw === null) return true;
        return raw !== '0';
    } catch {
        return true;
    }
}

function saveStoredChatListExpanded(expanded) {
    try {
        if (!window?.localStorage) return;
        window.localStorage.setItem(UI_CHAT_LIST_EXPANDED_STORAGE_KEY, expanded ? '1' : '0');
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredActiveChatId() {
    try {
        if (!window?.localStorage) return '';
        return safeString(window.localStorage.getItem(UI_ACTIVE_CHAT_STORAGE_KEY));
    } catch {
        return '';
    }
}

function saveStoredActiveChatId(chatIdRaw) {
    try {
        if (!window?.localStorage) return;
        const chatId = safeString(chatIdRaw);
        if (chatId) {
            window.localStorage.setItem(UI_ACTIVE_CHAT_STORAGE_KEY, chatId);
        } else {
            window.localStorage.removeItem(UI_ACTIVE_CHAT_STORAGE_KEY);
        }
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredOfficeCameraState() {
    try {
        if (!window?.localStorage) return null;
        const raw = safeString(window.localStorage.getItem(OFFICE_CAMERA_STORAGE_KEY));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        const zoom = Number(parsed.zoom);
        const panX = Number(parsed.panX);
        const panY = Number(parsed.panY);
        const followAgentId = safeString(parsed.followAgentId);
        if (!Number.isFinite(zoom) || !Number.isFinite(panX) || !Number.isFinite(panY)) {
            return null;
        }
        return {
            zoom: officeClamp(zoom, OFFICE_ZOOM_MIN, OFFICE_ZOOM_MAX),
            panX,
            panY,
            followAgentId,
        };
    } catch {
        return null;
    }
}

function saveStoredOfficeCameraState(snapshot) {
    try {
        if (!window?.localStorage || !snapshot || typeof snapshot !== 'object') return;
        const payload = {
            zoom: officeClamp(Number(snapshot.zoom) || 1, OFFICE_ZOOM_MIN, OFFICE_ZOOM_MAX),
            panX: Number(snapshot.panX) || 0,
            panY: Number(snapshot.panY) || 0,
            followAgentId: safeString(snapshot.followAgentId || ''),
        };
        window.localStorage.setItem(OFFICE_CAMERA_STORAGE_KEY, JSON.stringify(payload));
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredOfficeLayoutState() {
    try {
        if (!window?.localStorage) return null;
        const raw = safeString(window.localStorage.getItem(OFFICE_LAYOUT_STORAGE_KEY));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        return {
            dynamicRooms: Array.isArray(parsed.dynamicRooms) ? parsed.dynamicRooms : [],
            dynamicRoomBySlug: parsed.dynamicRoomBySlug && typeof parsed.dynamicRoomBySlug === 'object'
                ? parsed.dynamicRoomBySlug
                : {},
        };
    } catch {
        return null;
    }
}

function saveStoredOfficeLayoutState(snapshot) {
    try {
        if (!window?.localStorage || !snapshot || typeof snapshot !== 'object') return;
        const payload = {
            dynamicRooms: Array.isArray(snapshot.dynamicRooms) ? snapshot.dynamicRooms : [],
            dynamicRoomBySlug: snapshot.dynamicRoomBySlug && typeof snapshot.dynamicRoomBySlug === 'object'
                ? snapshot.dynamicRoomBySlug
                : {},
        };
        window.localStorage.setItem(OFFICE_LAYOUT_STORAGE_KEY, JSON.stringify(payload));
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredOfficeAgentPrefs() {
    try {
        if (!window?.localStorage) return null;
        const raw = safeString(window.localStorage.getItem(OFFICE_AGENT_PREFS_STORAGE_KEY));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        return parsed;
    } catch {
        return null;
    }
}

function saveStoredOfficeAgentPrefs(snapshot) {
    try {
        if (!window?.localStorage || !snapshot || typeof snapshot !== 'object') return;
        window.localStorage.setItem(OFFICE_AGENT_PREFS_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
        // Ignore storage failures.
    }
}

function loadStoredOfficeRuntimeState() {
    try {
        if (!window?.localStorage) return null;
        const raw = safeString(window.localStorage.getItem(OFFICE_RUNTIME_STORAGE_KEY));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        if (Number(parsed.version) !== OFFICE_RUNTIME_SCHEMA_VERSION) return null;
        return parsed;
    } catch {
        return null;
    }
}

function saveStoredOfficeRuntimeState(snapshot) {
    try {
        if (!window?.localStorage || !snapshot || typeof snapshot !== 'object') return;
        window.localStorage.setItem(OFFICE_RUNTIME_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
        // Ignore storage failures.
    }
}

function officeRuntimeTimerRemaining(now, targetRaw) {
    const target = Number(targetRaw) || 0;
    if (target <= 0) return 0;
    return Math.max(0, Math.round(target - now));
}

function officeRuntimeTimerRestore(now, remainingRaw) {
    const remaining = Math.max(0, Number(remainingRaw) || 0);
    if (!remaining) return 0;
    return now + remaining;
}

function officeCollectRuntimeSnapshot(now = performance.now()) {
    if (!officeState) return null;
    const timerNow = Number(now) || performance.now();
    return {
        version: OFFICE_RUNTIME_SCHEMA_VERSION,
        savedAtEpoch: Date.now(),
        savedAtPerf: timerNow,
        selectedAgentId: safeString(officeState.selectedAgentId),
        followAgentId: safeString(officeState.followAgentId),
        taskCounter: Number(officeState.taskCounter) || 0,
        chatLines: Array.isArray(officeState.chatLines)
            ? officeState.chatLines
                .slice(-OFFICE_MAX_CHAT_LINES)
                .map((line) => ({
                    message: safeString(line?.message),
                    tone: safeString(line?.tone) || 'system',
                    at: Number(line?.at) || Date.now(),
                }))
                .filter((line) => Boolean(line.message))
            : [],
        tasks: Array.isArray(officeState.tasks)
            ? officeState.tasks.map((task) => ({
                id: safeString(task?.id),
                title: safeString(task?.title),
                rawText: safeString(task?.rawText),
                source: safeString(task?.source),
                roomId: safeString(task?.roomId),
                roomLabel: safeString(task?.roomLabel),
                status: safeString(task?.status).toLowerCase(),
                assignedAgentId: safeString(task?.assignedAgentId),
                createdAt: Number(task?.createdAt) || 0,
                startedAt: Number(task?.startedAt) || 0,
                completedAt: Number(task?.completedAt) || 0,
            })).filter((task) => Boolean(task.id))
            : [],
        agents: Array.isArray(officeState.agents)
            ? officeState.agents.map((agent) => {
                const timers = {};
                OFFICE_RUNTIME_TIMER_FIELDS.forEach((field) => {
                    timers[field] = officeRuntimeTimerRemaining(timerNow, agent?.[field]);
                });
                return {
                    id: safeString(agent?.id),
                    name: safeString(agent?.name).slice(0, 24),
                    color: safeString(agent?.color),
                    costume: safeString(agent?.costume || 'none').toLowerCase(),
                    tint: safeString(agent?.tint || officeAgentTintFromColor(agent?.color)).toLowerCase(),
                    specialty: safeString(agent?.specialty || 'Generalist').slice(0, 64),
                    personality: safeString(agent?.personality || 'Helpful, direct, and persistent.').slice(0, 160),
                    source: safeString(agent?.source || 'seed'),
                    remoteIds: agent?.remoteIds && typeof agent.remoteIds === 'object' ? { ...agent.remoteIds } : {},
                    remoteRoomId: safeString(agent?.remoteRoomId),
                    remoteStatus: safeString(agent?.remoteStatus),
                    lastMissionSummary: safeString(agent?.lastMissionSummary).slice(0, 180),
                    x: Number(agent?.x) || 0,
                    y: Number(agent?.y) || 0,
                    targetX: Number(agent?.targetX) || 0,
                    targetY: Number(agent?.targetY) || 0,
                    speed: Number(agent?.speed) || 0,
                    facing: Number(agent?.facing) || 1,
                    laneBias: Number(agent?.laneBias) || 0,
                    state: safeString(agent?.state).toLowerCase(),
                    intent: safeString(agent?.intent).toLowerCase(),
                    taskId: safeString(agent?.taskId),
                    workStreak: Number(agent?.workStreak) || 0,
                    yieldResumeIntent: safeString(agent?.yieldResumeIntent),
                    runawayPhase: safeString(agent?.runawayPhase),
                    runawayExitX: Number(agent?.runawayExitX) || 0,
                    runawayExitY: Number(agent?.runawayExitY) || 0,
                    currentNodeId: safeString(agent?.currentNodeId),
                    routeWaypoints: Array.isArray(agent?.routeWaypoints)
                        ? agent.routeWaypoints.slice(0, 24).map((point) => ({
                            x: Number(point?.x) || 0,
                            y: Number(point?.y) || 0,
                            nodeId: safeString(point?.nodeId),
                        }))
                        : [],
                    routeDestinationNodeId: safeString(agent?.routeDestinationNodeId),
                    reservedLaneEdgeKey: safeString(agent?.reservedLaneEdgeKey),
                    timers,
                };
            }).filter((agent) => Boolean(agent.id))
            : [],
    };
}

function officeApplyRuntimeSnapshot(snapshotRaw, now = performance.now()) {
    if (!officeState || !snapshotRaw || typeof snapshotRaw !== 'object') return false;
    if (Number(snapshotRaw.version) !== OFFICE_RUNTIME_SCHEMA_VERSION) return false;
    const timerNow = Number(now) || performance.now();
    let changed = false;

    const taskList = [];
    const rawTasks = Array.isArray(snapshotRaw.tasks) ? snapshotRaw.tasks : [];
    rawTasks.slice(0, OFFICE_MAX_TASKS).forEach((taskRaw) => {
        const id = safeString(taskRaw?.id);
        if (!id) return;
        const room = officeRoomById(safeString(taskRaw?.roomId)) || officeRoomById('room-lobby');
        const statusRaw = safeString(taskRaw?.status).toLowerCase();
        const status = new Set(['queued', 'active', 'done']).has(statusRaw) ? statusRaw : 'queued';
        taskList.push({
            id,
            title: officeTaskTitle(safeString(taskRaw?.title || taskRaw?.rawText || id)),
            rawText: safeString(taskRaw?.rawText || taskRaw?.title || id),
            source: safeString(taskRaw?.source) || 'runtime-restore',
            roomId: room?.id || 'room-lobby',
            roomLabel: room?.label || 'Main Lobby',
            status,
            assignedAgentId: safeString(taskRaw?.assignedAgentId),
            createdAt: Number(taskRaw?.createdAt) || Date.now(),
            startedAt: Number(taskRaw?.startedAt) || 0,
            completedAt: Number(taskRaw?.completedAt) || 0,
        });
    });
    if (taskList.length) {
        officeState.tasks = taskList;
        officeState.tasksDirty = true;
        changed = true;
    }

    const knownTaskIds = new Set(officeState.tasks.map((task) => task.id));
    const allowedStates = new Set(['idle', 'walking', 'working', 'break', 'yield', 'runaway']);
    const agentById = new Map(officeState.agents.map((agent) => [agent.id, agent]));
    const rawAgents = Array.isArray(snapshotRaw.agents) ? snapshotRaw.agents : [];
    rawAgents.forEach((saved) => {
        const id = safeString(saved?.id);
        if (!id) return;
        const agent = agentById.get(id);
        if (!agent) return;
        const x = officeClamp(Number(saved?.x) || agent.x, 1, 99);
        const y = officeClamp(Number(saved?.y) || agent.y, 1, 99);
        const safePosition = officeNearestWalkablePoint(x, y, agent.x, agent.y);
        agent.x = safePosition.x;
        agent.y = safePosition.y;
        const targetX = officeClamp(Number(saved?.targetX) || agent.x, 1, 99);
        const targetY = officeClamp(Number(saved?.targetY) || agent.y, 1, 99);
        const safeTarget = officeNearestWalkablePoint(targetX, targetY, agent.x, agent.y);
        agent.targetX = safeTarget.x;
        agent.targetY = safeTarget.y;
        agent.name = safeString(saved?.name).slice(0, 24) || agent.name;
        const color = safeString(saved?.color);
        if (/^#[0-9a-f]{6}$/i.test(color)) {
            agent.color = color;
        }
        const costume = safeString(saved?.costume).toLowerCase();
        if (new Set(OFFICE_AGENT_COSTUME_POOL).has(costume)) {
            agent.costume = costume;
        }
        agent.tint = safeString(saved?.tint).toLowerCase() || officeAgentTintFromColor(agent.color);
        agent.specialty = safeString(saved?.specialty || agent.specialty || 'Generalist').slice(0, 64);
        agent.personality = safeString(saved?.personality || agent.personality || 'Helpful, direct, and persistent.').slice(0, 160);
        agent.source = safeString(saved?.source || agent.source || 'seed');
        agent.remoteIds = saved?.remoteIds && typeof saved.remoteIds === 'object' ? { ...saved.remoteIds } : (agent.remoteIds || {});
        agent.remoteRoomId = safeString(saved?.remoteRoomId || agent.remoteRoomId);
        agent.remoteStatus = safeString(saved?.remoteStatus || agent.remoteStatus);
        agent.lastMissionSummary = safeString(saved?.lastMissionSummary || agent.lastMissionSummary).slice(0, 180);
        agent.speed = officeClamp(Number(saved?.speed) || agent.speed, 1.3, 5.2);
        agent.facing = Number(saved?.facing) >= 0 ? 1 : -1;
        agent.laneBias = officeClamp(Number(saved?.laneBias) || 0, -1, 1);
        const state = safeString(saved?.state).toLowerCase();
        agent.state = allowedStates.has(state) ? state : 'idle';
        agent.intent = safeString(saved?.intent).toLowerCase() || (agent.state === 'working' ? 'task' : 'wander');
        const taskId = safeString(saved?.taskId);
        agent.taskId = knownTaskIds.has(taskId) ? taskId : '';
        agent.workStreak = Math.max(0, Number(saved?.workStreak) || 0);
        agent.yieldResumeIntent = safeString(saved?.yieldResumeIntent) || '';
        agent.runawayPhase = safeString(saved?.runawayPhase) || '';
        agent.runawayExitX = officeClamp(Number(saved?.runawayExitX) || 0, OFFICE_RUNAWAY_EXIT_MARGIN, 100 - OFFICE_RUNAWAY_EXIT_MARGIN);
        agent.runawayExitY = officeClamp(Number(saved?.runawayExitY) || 0, OFFICE_RUNAWAY_EXIT_MARGIN, 100 - OFFICE_RUNAWAY_EXIT_MARGIN);
        agent.currentNodeId = officeState.navMap.has(safeString(saved?.currentNodeId))
            ? safeString(saved?.currentNodeId)
            : officeFindNearestNode(officeState.navMap, agent.x, agent.y);
        agent.routeWaypoints = Array.isArray(saved?.routeWaypoints)
            ? saved.routeWaypoints.slice(0, 24).map((point) => ({
                x: officeClamp(Number(point?.x) || agent.x, 0, 100),
                y: officeClamp(Number(point?.y) || agent.y, 0, 100),
                nodeId: safeString(point?.nodeId),
            }))
            : [];
        const destination = safeString(saved?.routeDestinationNodeId);
        agent.routeDestinationNodeId = officeState.navMap.has(destination) ? destination : '';
        agent.reservedLaneEdgeKey = safeString(saved?.reservedLaneEdgeKey);
        agent.speech = null;
        const timers = saved?.timers && typeof saved.timers === 'object' ? saved.timers : {};
        OFFICE_RUNTIME_TIMER_FIELDS.forEach((field) => {
            agent[field] = officeRuntimeTimerRestore(timerNow, timers[field]);
        });
        agent.lastMoveX = agent.x;
        agent.lastMoveY = agent.y;
        changed = true;
    });

    const selectedAgentId = safeString(snapshotRaw.selectedAgentId);
    if (selectedAgentId && officeState.agents.some((agent) => agent.id === selectedAgentId)) {
        officeState.selectedAgentId = selectedAgentId;
        changed = true;
    }
    const followAgentId = safeString(snapshotRaw.followAgentId);
    if (followAgentId && officeState.agents.some((agent) => agent.id === followAgentId)) {
        officeState.followAgentId = followAgentId;
        changed = true;
    }
    if (Array.isArray(snapshotRaw.chatLines) && snapshotRaw.chatLines.length) {
        officeState.chatLines = snapshotRaw.chatLines
            .map((line) => ({
                message: safeString(line?.message),
                tone: safeString(line?.tone) || 'system',
                at: Number(line?.at) || Date.now(),
            }))
            .filter((line) => Boolean(line.message))
            .slice(-OFFICE_MAX_CHAT_LINES);
        changed = true;
    }
    officeState.taskCounter = Math.max(
        Number(officeState.taskCounter) || 0,
        Number(snapshotRaw.taskCounter) || 0,
        officeState.tasks.length,
    );
    officeState.lastWallClockTickAt = Date.now();
    return changed;
}

function officePersistRuntimeState(now = performance.now(), { force = false } = {}) {
    if (!officeState) return;
    const snapshotNow = Number(now) || performance.now();
    const elapsed = snapshotNow - (officeState.lastRuntimePersistAt || 0);
    if (!force && elapsed < OFFICE_RUNTIME_PERSIST_INTERVAL_MS) return;
    const snapshot = officeCollectRuntimeSnapshot(snapshotNow);
    if (!snapshot) return;
    saveStoredOfficeRuntimeState(snapshot);
    officeState.lastRuntimePersistAt = snapshotNow;
}

function officeSanitizeDynamicRoomSnapshot(roomRaw, index = 0) {
    const room = roomRaw && typeof roomRaw === 'object' ? roomRaw : {};
    const roomId = safeString(room.id) || `room-dynamic-${index + 1}`;
    const x = officeClamp(Number(room.x) || 58, 1, 93);
    const y = officeClamp(Number(room.y) || 58, 1, 95);
    const w = officeClamp(Number(room.w) || 8, 4.8, 18);
    const h = officeClamp(Number(room.h) || 8, 4.8, 18);
    const doorX = officeClamp(Number(room.doorX) || (x + (w / 2)), x, x + w);
    const doorY = officeClamp(Number(room.doorY) || (y + h), y, y + h + 2.2);
    const hallId = safeString(room.hallId) || officeNearestHallId(doorX, doorY);
    return {
        id: roomId,
        label: safeString(room.label) || `Task Pod ${index + 1}`,
        meta: safeString(room.meta) || 'Auto-generated feature room',
        x,
        y,
        w,
        h,
        kind: safeString(room.kind) || 'work',
        theme: safeString(room.theme) || 'dynamic',
        doorX,
        doorY,
        hallId,
        dynamic: true,
    };
}

function officeCollectLayoutSnapshot() {
    if (!officeState) return { dynamicRooms: [], dynamicRoomBySlug: {} };
    const dynamicRooms = officeState.rooms
        .filter((room) => room?.dynamic)
        .map((room) => ({
            id: room.id,
            label: room.label,
            meta: room.meta,
            x: Number(room.x) || 0,
            y: Number(room.y) || 0,
            w: Number(room.w) || 0,
            h: Number(room.h) || 0,
            kind: room.kind || 'work',
            theme: room.theme || 'dynamic',
            doorX: Number(room.doorX) || 0,
            doorY: Number(room.doorY) || 0,
            hallId: room.hallId || '',
        }));
    const dynamicRoomBySlug = {};
    officeState.dynamicRoomBySlug.forEach((roomId, slug) => {
        if (!slug || !roomId) return;
        dynamicRoomBySlug[slug] = roomId;
    });
    return { dynamicRooms, dynamicRoomBySlug };
}

function officePersistLayoutState() {
    if (!officeState) return;
    saveStoredOfficeLayoutState(officeCollectLayoutSnapshot());
}

function officeApplyStoredAgentPrefs(agents, prefsRaw) {
    if (!Array.isArray(agents) || !agents.length) return;
    const prefs = prefsRaw && typeof prefsRaw === 'object' ? prefsRaw : null;
    if (!prefs) return;
    const usedNames = new Set();
    agents.forEach((agent) => {
        const saved = prefs[safeString(agent.id)];
        if (!saved || typeof saved !== 'object') return;
        const proposedName = safeString(saved.name).slice(0, 24);
        const lowered = proposedName.toLowerCase();
        if (proposedName && !usedNames.has(lowered)) {
            agent.name = proposedName;
            usedNames.add(lowered);
        } else {
            usedNames.add(safeString(agent.name).toLowerCase());
        }
        const color = safeString(saved.color);
        if (/^#[0-9a-f]{6}$/i.test(color)) {
            agent.color = color;
        }
        const costume = safeString(saved.costume).toLowerCase();
        if (new Set(OFFICE_AGENT_COSTUME_POOL || ['none', 'cap', 'visor', 'headset', 'bowtie']).has(costume)) {
            agent.costume = costume;
        }
        const tint = safeString(saved.tint).toLowerCase();
        if (tint) {
            agent.tint = tint;
        } else {
            agent.tint = officeAgentTintFromColor(agent.color);
        }
        agent.specialty = safeString(saved.specialty || agent.specialty || 'Generalist').slice(0, 64);
        agent.personality = safeString(saved.personality || agent.personality || 'Helpful, direct, and persistent.').slice(0, 160);
        agent.chatProfile = safeString(saved.chatProfile || agent.chatProfile).slice(0, 80);
        agent.chatModelId = safeString(saved.chatModelId || agent.chatModelId).slice(0, 120);
        if (Array.isArray(saved.officeChatHistory)) {
            agent.officeChatHistory = saved.officeChatHistory.slice(-18).map((entry) => ({
                role: safeString(entry?.role || 'agent').slice(0, 16),
                text: safeString(entry?.text).replace(/\s+/g, ' ').trim().slice(0, 600),
                at: Number(entry?.at) || Date.now(),
                timeLabel: safeString(entry?.timeLabel).slice(0, 24)
                    || new Date(Number(entry?.at) || Date.now()).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
            })).filter((entry) => entry.text);
        }
    });
}

