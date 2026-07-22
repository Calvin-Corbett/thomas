/** Map transforms and full scene rendering. */

function officeConfigureDynamicUi(node, { id, label, policy, instanceKey = '', constraints = '' }) {
    if (!(node instanceof HTMLElement)) return node;
    node.dataset.uiId = id;
    node.dataset.uiLabel = label;
    node.dataset.uiPolicy = policy;
    if (instanceKey) node.dataset.uiInstanceKey = instanceKey;
    if (constraints) node.dataset.uiConstraints = constraints;
    return node;
}

function officeDecorateDraftAssetUiNode(node, space, asset) {
    if (!(node instanceof HTMLElement)) return node;
    const assetId = safeString(asset?.id);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[safeString(asset?.type)] || {};
    node.classList.add('office-live-asset');
    return officeConfigureDynamicUi(node, {
        id: 'virtual-office.asset',
        instanceKey: assetId,
        label: `${safeString(descriptor.label || asset?.type) || 'Office asset'} in ${safeString(space?.name) || 'office'}`,
        policy: 'protected live-map-item',
        constraints: 'no-move no-resize no-delete no-copy',
    });
}

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
    officeScene.classList.add('office-map-scene');
    officeScene.innerHTML = '';
    officeDraftDebugRenderMark('shell');
    const plane = document.createElement('div');
    plane.className = 'office-map-plane';
    plane.dataset.officeMapPlane = '1';
    officeConfigureDynamicUi(plane, {
        id: 'virtual-office.map-plane',
        label: 'Live office map',
        policy: 'protected live-map-root',
        constraints: 'no-move no-resize no-delete no-copy',
    });
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
        room.className = 'office-live-room';
        room.dataset.officeDraftSpaceId = safeString(space?.id);
        room.dataset.officeDraftOverview = overviewMode ? '1' : '0';
        room.dataset.officeDraftDetail = renderDetailedSpace ? '1' : '0';
        room.dataset.officeDraftSelected = isSelectedSpace ? '1' : '0';
        officeConfigureDynamicUi(room, {
            id: 'virtual-office.room',
            instanceKey: safeString(space?.id),
            label: `${safeString(space?.name) || 'Office'} room`,
            policy: 'protected live-map-group',
            constraints: 'no-move no-resize no-delete no-copy',
        });
        room.style.position = 'absolute';
        room.style.zIndex = '1';
        room.style.left = `${Math.round(Number(space?.x) || 0)}px`;
        room.style.top = `${Math.round(Number(space?.y) || 0)}px`;
        room.style.width = `${Math.round(Number(space?.width) || 0)}px`;
        room.style.height = `${Math.round(Number(space?.height) || 0)}px`;
        room.style.setProperty('--office-room-shell', overviewMode ? officeDraftOverviewColor(space, 'shell') : palette.shell);

        const roomInset = document.createElement('div');
        roomInset.className = 'office-live-room-floor';
        roomInset.style.setProperty('--office-room-floor-border', palette.floorBorder);
        roomInset.style.setProperty('--office-room-floor', overviewMode ? officeDraftOverviewColor(space, 'floor') : palette.floor);
        if (!overviewMode && safeString(palette.pattern)) {
            roomInset.style.setProperty('--office-room-pattern', palette.pattern);
            roomInset.style.setProperty('--office-room-pattern-size', safeString(palette.patternSize) || '120px 120px');
        }
        room.appendChild(roomInset);

        const roomLabel = document.createElement('button');
        roomLabel.type = 'button';
        roomLabel.className = 'office-room-label';
        roomLabel.dataset.officeDraftSpaceLabel = safeString(space?.id);
        roomLabel.dataset.officeDraftSelected = isSelectedSpace ? '1' : '0';
        officeConfigureDynamicUi(roomLabel, {
            id: 'virtual-office.room-label',
            instanceKey: safeString(space?.id),
            label: `${safeString(space?.name) || 'Office'} room label`,
            policy: 'protected controls',
        });
        roomLabel.textContent = safeString(space?.name) || 'Space';
        roomLabel.style.cursor = state.editorOpen ? 'pointer' : 'default';
        room.appendChild(roomLabel);

        const roomAssets = Array.isArray(space?.assets) ? space.assets : [];
        if (renderDetailedSpace) {
            roomAssets.forEach((asset) => {
                room.appendChild(officeDecorateDraftAssetUiNode(officeDraftCreateAssetElement(space, asset, state), space, asset));
            });
        } else {
            room.appendChild(officeDraftCreateOverviewAssetDots(space, roomAssets, state));
        }
        if (safeString(state.catalogPreviewSpaceId) === safeString(space?.id) && safeString(state.catalogPendingType)) {
            const pendingType = safeString(state.catalogPendingType);
            const previewAsset = {
                id: 'catalog-preview',
                type: pendingType,
                x: state.catalogPreviewX,
                y: state.catalogPreviewY,
                rotation: 0,
                colorVariant: officeDraftAssetDefaultColorVariant(pendingType),
                scale: 1,
                preview: true,
            };
            room.appendChild(officeDecorateDraftAssetUiNode(officeDraftCreateAssetElement(space, previewAsset, state), space, previewAsset));
        }

        plane.appendChild(room);
    });
    officeDraftDebugRenderMark('rooms');

    const agentLayer = document.createElement('div');
    agentLayer.className = 'office-agent-layer';
    agentLayer.dataset.officeDraftAgentLayer = 'global';
    officeConfigureDynamicUi(agentLayer, {
        id: 'virtual-office.agent-layer',
        label: 'Live agent presence',
        policy: 'protected live-map-group',
        constraints: 'no-move no-resize no-delete no-copy',
    });
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
        toolbar.className = 'office-map-toolbar';
        toolbar.dataset.officeMapToolbar = '1';
        officeConfigureDynamicUi(toolbar, {
            id: 'virtual-office.map-toolbar',
            label: 'Office map controls',
            policy: 'move resize',
            constraints: 'minWidth=360;minHeight=44;maxWidth=960;maxHeight=120',
        });

        const brandMark = document.createElement('span');
        brandMark.className = 'thomas-eyes-mark office-map-brand';
        brandMark.setAttribute('aria-hidden', 'true');
        brandMark.innerHTML = '<i></i><i></i>';
        officeConfigureDynamicUi(brandMark, {
            id: 'virtual-office.brand',
            label: 'Thomas eyes',
            policy: 'protected brand',
            constraints: 'no-move no-resize no-delete no-copy',
        });

        const configureToolbarButton = (button, id, label) => {
            button.className = 'office-control';
            officeConfigureDynamicUi(button, { id, label, policy: 'protected controls' });
        };

        const minimapBtn = document.createElement('button');
        minimapBtn.type = 'button';
        minimapBtn.dataset.officeMapToolbarMinimap = '1';
        configureToolbarButton(minimapBtn, 'virtual-office.action.minimap', 'Toggle minimap');
        minimapBtn.textContent = 'Minimap';
        minimapBtn.addEventListener('click', officeToggleDraftMinimapMinimized);

        const editorBtn = document.createElement('button');
        editorBtn.type = 'button';
        editorBtn.dataset.officeMapToolbarEditor = '1';
        configureToolbarButton(editorBtn, 'virtual-office.action.office-layout', 'Open office layout tools');
        editorBtn.textContent = 'Layout';
        editorBtn.addEventListener('click', officeToggleDraftEditor);

        const rosterBtn = document.createElement('button');
        rosterBtn.type = 'button';
        rosterBtn.dataset.officeMapToolbarRoster = '1';
        configureToolbarButton(rosterBtn, 'virtual-office.action.agent-roster', 'Open agent roster');
        rosterBtn.textContent = 'Agent Roster';
        rosterBtn.addEventListener('click', officeToggleDraftAgentRoster);

        const chatBtn = document.createElement('button');
        chatBtn.type = 'button';
        chatBtn.dataset.officeMapToolbarChat = '1';
        configureToolbarButton(chatBtn, 'virtual-office.action.agent-chat', 'Open agent chat');
        chatBtn.textContent = 'Chat';
        chatBtn.addEventListener('click', officeToggleDraftAgentChat);

        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.dataset.officeMapToolbarSave = '1';
        configureToolbarButton(saveBtn, 'virtual-office.action.save-layout', 'Save office layout');
        saveBtn.textContent = 'Save';
        saveBtn.addEventListener('click', officeDraftManualSaveLayout);

        const undoBtn = document.createElement('button');
        undoBtn.type = 'button';
        undoBtn.dataset.officeMapToolbarUndo = '1';
        configureToolbarButton(undoBtn, 'virtual-office.action.undo-layout', 'Undo office layout change');
        undoBtn.textContent = 'Back';
        undoBtn.addEventListener('click', officeDraftUndoLastChange);

        const badge = document.createElement('span');
        badge.className = 'office-map-badge';
        badge.dataset.officeMapBadge = '1';

        toolbar.appendChild(brandMark);
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
        resizeHandle.className = 'office-minimap-resize';
        resizeHandle.dataset.officeMinimapResize = '1';
        officeConfigureDynamicUi(resizeHandle, {
            id: 'virtual-office.action.resize-minimap',
            label: 'Resize minimap',
            policy: 'protected controls',
        });
        resizeHandle.setAttribute('aria-label', 'Resize minimap');
        officeMinimap.appendChild(resizeHandle);
    }
    const minimapHead = officeMinimap?.querySelector('.office-minimap-head');
    if (minimapHead instanceof HTMLElement && !minimapHead.querySelector('[data-office-minimap-lock="1"]')) {
        const lockButton = document.createElement('button');
        lockButton.type = 'button';
        lockButton.className = 'office-control office-minimap-lock';
        lockButton.dataset.officeMinimapLock = '1';
        officeConfigureDynamicUi(lockButton, {
            id: 'virtual-office.action.lock-minimap',
            label: 'Lock minimap position',
            policy: 'protected controls',
        });
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


