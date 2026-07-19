/** Map transforms and full scene rendering. */

function officeRenderDraftMapMinimapThrottled(force = false) {
    const state = officeEnsureDraftMapState();
    const now = performance.now();
    if (force) {
        if (state.minimapRenderTimer) {
            window.clearTimeout(state.minimapRenderTimer);
            state.minimapRenderTimer = 0;
        }
        state.lastMinimapRenderAt = now;
        officeRenderDraftMapMinimap();
        return;
    }
    if (state.minimapRenderTimer) return;
    state.minimapRenderTimer = window.setTimeout(() => {
        state.minimapRenderTimer = 0;
        state.lastMinimapRenderAt = performance.now();
        officeRenderDraftMapMinimap();
    }, 90);
}

function officeApplyDraftMapTransform(options = {}) {
    const state = officeEnsureDraftMapState();
    const plane = officeDraftMapPlane();
    if (!(plane instanceof HTMLElement)) return;
    const clamped = officeClampDraftMapPan(state.panX, state.panY, state.zoom);
    state.panX = clamped.panX;
    state.panY = clamped.panY;
    const offsetX = -(state.panX * state.zoom);
    const offsetY = -(state.panY * state.zoom);
    plane.style.transform = `translate3d(${offsetX.toFixed(2)}px, ${offsetY.toFixed(2)}px, 0) scale(${state.zoom.toFixed(4)})`;
    officeApplyDraftMapGridBackground(state, offsetX, offsetY);
    const badge = officeWorkspace?.querySelector('[data-office-map-badge="1"]');
    if (badge instanceof HTMLElement) {
        badge.textContent = `${Math.round(state.zoom * 100)}% · ${OFFICE_DRAFT_MAP_SIZE.toLocaleString()} x ${OFFICE_DRAFT_MAP_SIZE.toLocaleString()} grid`;
    }
    officeRenderDraftMapMinimapThrottled(options?.deferMinimap !== true);
}

function officeRenderDraftMapScene(options = {}) {
    if (!officeScene || !officeScenePanzoom) return;
    const state = officeEnsureDraftMapState();
    const renderNow = performance.now();
    officeDraftDebugRenderMark('start');
    if (options?.force !== true && officeDraftSceneRenderQuietActive(state, renderNow)) {
        officeDraftScheduleSceneRenderAfterInput(state, renderNow);
        return;
    }
    if (options?.force === true) {
        window.clearTimeout(state.sceneRenderTimer);
        state.sceneRenderDeferred = false;
    }
    officePrepareDraftMapShell();
    officeScenePanzoom.style.position = 'absolute';
    officeScenePanzoom.style.inset = '0';
    officeScenePanzoom.style.width = '100%';
    officeScenePanzoom.style.height = '100%';
    officeScenePanzoom.style.overflow = 'hidden';
    officeScenePanzoom.style.transformOrigin = 'top left';
    officeScenePanzoom.style.willChange = 'transform';
    officeScenePanzoom.style.setProperty('--office-zoom', '1');
    officeScenePanzoom.style.setProperty('--office-pan-x', '0px');
    officeScenePanzoom.style.setProperty('--office-pan-y', '0px');
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.setProperty('--office-pan-x', '0px');
        officeSceneWrap.style.setProperty('--office-pan-y', '0px');
    }
    officeScene.style.position = 'relative';
    officeScene.style.width = '100%';
    officeScene.style.height = '100%';
    officeScene.style.overflow = 'hidden';
    officeScene.style.backgroundColor = '#0a1321';
    officeScene.innerHTML = '';
    officeDraftDebugRenderMark('shell');
    const plane = document.createElement('div');
    plane.dataset.officeMapPlane = '1';
    plane.style.position = 'absolute';
    plane.style.left = '0';
    plane.style.top = '0';
    plane.style.width = `${OFFICE_DRAFT_MAP_SIZE}px`;
    plane.style.height = `${OFFICE_DRAFT_MAP_SIZE}px`;
    plane.style.transformOrigin = 'top left';
    plane.style.willChange = 'transform';
    plane.style.contain = 'layout paint style';
    plane.style.background = 'transparent';
    officeRenderDraftRoomConnectors(plane, state);
    officeDraftDebugRenderMark('connectors');
    const initialAgentAssignments = officeDraftAgentAssignmentMap(state);
    const overviewMode = officeDraftOverviewMode(state);
    const viewportWorldRect = officeDraftMapViewportWorldRect();
    const viewportPadding = officeDraftViewportPadding(state);
    state.spaces.forEach((space) => {
        const palette = officeDraftRoomPalette(space?.floorPalette);
        const isSelectedSpace = safeString(space?.id) === safeString(state.selectedSpaceId);
        const spaceNearViewport = officeDraftSpaceIntersectsViewport(space, viewportWorldRect, viewportPadding);
        const renderDetailedSpace = !overviewMode && spaceNearViewport;
        const room = document.createElement('section');
        room.dataset.officeDraftSpaceId = safeString(space?.id);
        room.dataset.officeDraftOverview = overviewMode ? '1' : '0';
        room.dataset.officeDraftDetail = renderDetailedSpace ? '1' : '0';
        room.style.position = 'absolute';
        room.style.zIndex = '1';
        room.style.left = `${Math.round(Number(space?.x) || 0)}px`;
        room.style.top = `${Math.round(Number(space?.y) || 0)}px`;
        room.style.width = `${Math.round(Number(space?.width) || 0)}px`;
        room.style.height = `${Math.round(Number(space?.height) || 0)}px`;
        room.style.border = isSelectedSpace ? '4px solid rgba(122, 181, 255, 0.82)' : '4px solid rgba(158, 196, 255, 0.62)';
        room.style.borderRadius = overviewMode ? '30px' : '46px';
        room.style.background = overviewMode ? officeDraftOverviewColor(space, 'shell') : palette.shell;
        room.style.overflow = 'visible';
        room.style.boxShadow = isSelectedSpace
            ? 'inset 0 0 0 1px rgba(215, 232, 255, 0.08), 0 0 0 2px rgba(110, 169, 255, 0.14), 0 18px 42px rgba(0, 0, 0, 0.22)'
            : 'inset 0 0 0 1px rgba(215, 232, 255, 0.05), 0 16px 38px rgba(0, 0, 0, 0.2)';

        const roomInset = document.createElement('div');
        roomInset.style.position = 'absolute';
        roomInset.style.left = '24px';
        roomInset.style.top = '24px';
        roomInset.style.right = '24px';
        roomInset.style.bottom = '24px';
        roomInset.style.borderRadius = overviewMode ? '22px' : '32px';
        roomInset.style.border = `1px solid ${palette.floorBorder}`;
        roomInset.style.background = overviewMode ? officeDraftOverviewColor(space, 'floor') : palette.floor;
        if (!overviewMode && safeString(palette.pattern)) {
            roomInset.style.backgroundImage = `${palette.pattern}, ${palette.floor}`;
            roomInset.style.backgroundSize = `${safeString(palette.patternSize) || '120px 120px'}, auto`;
        }
        room.appendChild(roomInset);

        const roomLabel = document.createElement('button');
        roomLabel.type = 'button';
        roomLabel.dataset.officeDraftSpaceLabel = safeString(space?.id);
        roomLabel.textContent = safeString(space?.name) || 'Space';
        roomLabel.style.position = 'absolute';
        roomLabel.style.left = '42px';
        roomLabel.style.top = '-32px';
        roomLabel.style.padding = '10px 18px';
        roomLabel.style.borderRadius = '18px 18px 10px 10px';
        roomLabel.style.border = isSelectedSpace ? '2px solid rgba(128, 185, 255, 0.72)' : '2px solid rgba(214, 228, 247, 0.28)';
        roomLabel.style.background = isSelectedSpace ? 'rgba(80, 128, 205, 0.9)' : 'rgba(43, 59, 88, 0.92)';
        roomLabel.style.color = 'rgba(245, 248, 255, 0.96)';
        roomLabel.style.fontSize = overviewMode ? '1rem' : '1.2rem';
        roomLabel.style.fontWeight = '700';
        roomLabel.style.letterSpacing = '0.12em';
        roomLabel.style.textTransform = 'uppercase';
        roomLabel.style.cursor = state.editorOpen ? 'pointer' : 'default';
        room.appendChild(roomLabel);

        const roomAssets = Array.isArray(space?.assets) ? space.assets : [];
        if (renderDetailedSpace) {
            roomAssets.forEach((asset) => {
                room.appendChild(officeDraftCreateAssetElement(space, asset, state));
            });
        } else {
            room.appendChild(officeDraftCreateOverviewAssetDots(space, roomAssets, state));
        }
        if (safeString(state.catalogPreviewSpaceId) === safeString(space?.id) && safeString(state.catalogPendingType)) {
            const pendingType = safeString(state.catalogPendingType);
            room.appendChild(officeDraftCreateAssetElement(space, {
                id: 'catalog-preview',
                type: pendingType,
                x: state.catalogPreviewX,
                y: state.catalogPreviewY,
                rotation: 0,
                colorVariant: officeDraftAssetDefaultColorVariant(pendingType),
                scale: 1,
                preview: true,
            }, state));
        }

        plane.appendChild(room);
    });
    officeDraftDebugRenderMark('rooms');

    const agentLayer = document.createElement('div');
    agentLayer.dataset.officeDraftAgentLayer = 'global';
    agentLayer.style.position = 'absolute';
    agentLayer.style.inset = '0';
    agentLayer.style.pointerEvents = state.editorOpen ? 'none' : 'auto';
    agentLayer.style.zIndex = '4';
    agentLayer.style.overflow = 'visible';
    state.agentLayerForceRender = true;
    const previousSkipRoutePlanning = state.agentLayerSkipRoutePlanning;
    state.agentLayerSkipRoutePlanning = true;
    try {
        officeDraftDebugRenderMark('agents-before');
        officePopulateDraftGlobalAgentLayer(agentLayer, state, renderNow, initialAgentAssignments, 'scene');
        officeDraftDebugRenderMark('agents-after');
        if (officeState) officeState.lastDraftAgentRenderAt = renderNow;
    } finally {
        state.agentLayerForceRender = false;
        state.agentLayerSkipRoutePlanning = previousSkipRoutePlanning === true;
    }
    plane.appendChild(agentLayer);
    officeDraftDebugRenderMark('agent-layer');
    if (state.agentRoutePlanDeferred) {
        state.routePlanQuietUntil = Math.max(
            Number(state.routePlanQuietUntil) || 0,
            renderNow + OFFICE_DRAFT_AGENT_ROUTE_PLAN_BOOT_QUIET_MS,
        );
        officeDraftScheduleDeferredRoutePlan(state, renderNow);
    }

    officeScene.appendChild(plane);
    officeDraftDebugRenderMark('plane-appended');
    if (officeSceneWrap instanceof HTMLElement && !officeSceneWrap.querySelector('[data-office-map-toolbar="1"]')) {
        const toolbar = document.createElement('div');
        toolbar.dataset.officeMapToolbar = '1';

        const minimapBtn = document.createElement('button');
        minimapBtn.type = 'button';
        minimapBtn.dataset.officeMapToolbarMinimap = '1';
        minimapBtn.textContent = 'Minimap';
        minimapBtn.addEventListener('click', officeToggleDraftMinimapMinimized);

        const editorBtn = document.createElement('button');
        editorBtn.type = 'button';
        editorBtn.dataset.officeMapToolbarEditor = '1';
        editorBtn.textContent = 'Office Editor';
        editorBtn.addEventListener('click', officeToggleDraftEditor);

        const rosterBtn = document.createElement('button');
        rosterBtn.type = 'button';
        rosterBtn.dataset.officeMapToolbarRoster = '1';
        rosterBtn.textContent = 'Agent Roster';
        rosterBtn.addEventListener('click', officeToggleDraftAgentRoster);

        const chatBtn = document.createElement('button');
        chatBtn.type = 'button';
        chatBtn.dataset.officeMapToolbarChat = '1';
        chatBtn.textContent = 'Chat';
        chatBtn.addEventListener('click', officeToggleDraftAgentChat);

        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.dataset.officeMapToolbarSave = '1';
        saveBtn.textContent = 'Save';
        saveBtn.addEventListener('click', officeDraftManualSaveLayout);

        const undoBtn = document.createElement('button');
        undoBtn.type = 'button';
        undoBtn.dataset.officeMapToolbarUndo = '1';
        undoBtn.textContent = 'Back';
        undoBtn.addEventListener('click', officeDraftUndoLastChange);

        const badge = document.createElement('span');
        badge.dataset.officeMapBadge = '1';

        toolbar.appendChild(minimapBtn);
        toolbar.appendChild(editorBtn);
        toolbar.appendChild(rosterBtn);
        toolbar.appendChild(chatBtn);
        toolbar.appendChild(saveBtn);
        toolbar.appendChild(undoBtn);
        toolbar.appendChild(badge);
        officeSceneWrap.appendChild(toolbar);
    }
    if (officeMinimap instanceof HTMLElement && !officeMinimap.querySelector('[data-office-minimap-resize="1"]')) {
        const resizeHandle = document.createElement('div');
        resizeHandle.dataset.officeMinimapResize = '1';
        resizeHandle.setAttribute('aria-label', 'Resize minimap');
        officeMinimap.appendChild(resizeHandle);
    }
    const minimapHead = officeMinimap?.querySelector('.office-minimap-head');
    if (minimapHead instanceof HTMLElement && !minimapHead.querySelector('[data-office-minimap-lock="1"]')) {
        const lockButton = document.createElement('button');
        lockButton.type = 'button';
        lockButton.dataset.officeMinimapLock = '1';
        lockButton.textContent = 'Lock';
        lockButton.addEventListener('click', officeToggleDraftMinimapLocked);
        minimapHead.prepend(lockButton);
    }
    officeRenderDraftMapEditorPanel();
    officeRenderDraftAgentRosterPanel();
    officeRenderDraftAgentChatPanel();
    officePrepareDraftMapShell();
    officeApplyDraftMapTransform();
    const attachedAgentLayer = officeScene.querySelector('[data-office-draft-agent-layer="global"]');
    if (attachedAgentLayer instanceof HTMLElement) {
        officeDraftResolveAgentElementOverlaps(attachedAgentLayer);
    }
    officeRenderDraftMapMinimap();
    officeDraftDebugRenderMark('done');
}


