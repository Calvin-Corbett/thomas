/** Draft-map state, bounds, and viewport positioning. */

function officeDraftStoredLayoutIsLegacy(snapshotRaw) {
    if (!snapshotRaw || typeof snapshotRaw !== 'object') return false;
    if (Number(snapshotRaw.schemaVersion) < OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION) return true;
    if (Number(snapshotRaw.schemaVersion) >= OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION) return false;
    const spaces = Array.isArray(snapshotRaw.spaces) ? snapshotRaw.spaces : [];
    if (!spaces.length) return true;
    return spaces.length <= 1 && spaces.every((space) => !safeString(space?.roomId));
}

function officeDraftFitSpacesToMapBounds(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    if (!spaces.length) return spaces;
    const margin = 360;
    const bounds = spaces.reduce((acc, space) => {
        const x = Number(space?.x) || 0;
        const y = Number(space?.y) || 0;
        const width = Math.max(320, Number(space?.width) || 0);
        const height = Math.max(240, Number(space?.height) || 0);
        acc.minX = Math.min(acc.minX, x);
        acc.minY = Math.min(acc.minY, y);
        acc.maxX = Math.max(acc.maxX, x + width);
        acc.maxY = Math.max(acc.maxY, y + height);
        return acc;
    }, {
        minX: Number.POSITIVE_INFINITY,
        minY: Number.POSITIVE_INFINITY,
        maxX: Number.NEGATIVE_INFINITY,
        maxY: Number.NEGATIVE_INFINITY,
    });
    if (!Number.isFinite(bounds.minX) || !Number.isFinite(bounds.minY)) return spaces;
    const needsFit = bounds.minX < margin
        || bounds.minY < margin
        || bounds.maxX > (OFFICE_DRAFT_MAP_SIZE - margin)
        || bounds.maxY > (OFFICE_DRAFT_MAP_SIZE - margin);
    if (!needsFit) return spaces;
    const centerX = bounds.minX + ((bounds.maxX - bounds.minX) / 2);
    const centerY = bounds.minY + ((bounds.maxY - bounds.minY) / 2);
    const offsetX = (OFFICE_DRAFT_MAP_SIZE / 2) - centerX;
    const offsetY = (OFFICE_DRAFT_MAP_SIZE / 2) - centerY;
    return spaces.map((space) => {
        const width = Math.max(320, Number(space?.width) || 0);
        const height = Math.max(240, Number(space?.height) || 0);
        const maxX = Math.max(margin, OFFICE_DRAFT_MAP_SIZE - margin - width);
        const maxY = Math.max(margin, OFFICE_DRAFT_MAP_SIZE - margin - height);
        return {
            ...space,
            x: Math.round(Math.max(margin, Math.min(maxX, (Number(space?.x) || 0) + offsetX))),
            y: Math.round(Math.max(margin, Math.min(maxY, (Number(space?.y) || 0) + offsetY))),
        };
    });
}

function officeEnsureDraftMapState() {
    if (officeDraftMapState) return officeDraftMapState;
    const defaultLayout = officeDraftDefaultLayoutSnapshot();
    officeDraftMapState = {
        zoom: OFFICE_DRAFT_MAP_DEFAULT_ZOOM,
        panX: 0,
        panY: 0,
        pointerId: null,
        dragStartX: 0,
        dragStartY: 0,
        dragPanX: 0,
        dragPanY: 0,
        initialized: false,
        hasLiveViewport: false,
        agentFocusInitialized: false,
        userSelectedSpace: false,
        minimapMinimized: false,
        minimapPointerId: null,
        minimapDragStartX: 0,
        minimapDragStartY: 0,
        minimapOffsetX: 0,
        minimapOffsetY: 0,
        minimapDragOffsetX: 0,
        minimapDragOffsetY: 0,
        minimapLocked: true,
        minimapPointerMode: 'camera',
        minimapSize: OFFICE_DRAFT_MINIMAP_SIZE,
        minimapResizePointerId: null,
        minimapResizeStartX: 0,
        minimapResizeStartY: 0,
        minimapResizeStartSize: OFFICE_DRAFT_MINIMAP_SIZE,
        autosaveEnabled: officeDraftLoadAutosavePreference(),
        editorOpen: false,
        rosterOpen: false,
        expandedRosterAgentId: '',
        agentChatOpen: false,
        agentChatAgentId: '',
        agentChatDraftById: {},
        catalogSearch: '',
        catalogCategory: 'all',
        selectedSpaceId: defaultLayout.selectedSpaceId,
        selectedAssetId: null,
        assetPointerId: null,
        assetDragSpaceId: '',
        assetDragId: '',
        assetDragOffsetX: 0,
        assetDragOffsetY: 0,
        assetDragSnapshot: null,
        catalogPointerId: null,
        catalogPendingType: '',
        catalogPreviewSpaceId: '',
        catalogPreviewX: 0,
        catalogPreviewY: 0,
        rotationStep: 15,
        gridEnabled: true,
        hallwayNetworkCache: null,
        missionAgentLayerDirty: false,
        agentRoutePlansRemaining: null,
        agentRoutePlanDeferred: false,
        agentRoutePlanTimer: 0,
        nextAssetId: defaultLayout.nextAssetId,
        undoStack: [],
        spaces: officeDraftCloneLayoutPayload(defaultLayout.spaces) || [],
    };
    const storedLayout = officeDraftLoadStoredLayout();
    if (!officeDraftStoredLayoutIsLegacy(storedLayout)) {
        officeDraftApplySnapshot(storedLayout, officeDraftMapState, { persist: false, resetUndo: true });
    } else {
        officeDraftPersistLayout(officeDraftMapState, { force: true });
    }
    return officeDraftMapState;
}

function officeDraftMapViewportRect() {
    if (!officeSceneWrap) {
        return { width: 1280, height: 720 };
    }
    const rect = officeSceneWrap.getBoundingClientRect();
    return {
        width: Math.max(320, rect.width || officeSceneWrap.clientWidth || 1280),
        height: Math.max(240, rect.height || officeSceneWrap.clientHeight || 720),
    };
}

function officeClampDraftMapPan(panXRaw, panYRaw, zoomRaw) {
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, Number(zoomRaw) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM));
    const viewport = officeDraftMapViewportRect();
    const viewportWorldWidth = viewport.width / zoom;
    const viewportWorldHeight = viewport.height / zoom;
    const freeWorldX = Math.max(0, viewportWorldWidth - OFFICE_DRAFT_MAP_SIZE);
    const freeWorldY = Math.max(0, viewportWorldHeight - OFFICE_DRAFT_MAP_SIZE);
    const padX = Math.max(2400, viewportWorldWidth * 0.35, (freeWorldX / 2) + 1800);
    const padY = Math.max(2400, viewportWorldHeight * 0.35, (freeWorldY / 2) + 1800);
    const minPanX = -padX;
    const minPanY = -padY;
    const maxPanX = (OFFICE_DRAFT_MAP_SIZE - viewportWorldWidth) + padX;
    const maxPanY = (OFFICE_DRAFT_MAP_SIZE - viewportWorldHeight) + padY;
    return {
        panX: Math.min(Math.max(minPanX, Number(panXRaw) || 0), maxPanX),
        panY: Math.min(Math.max(minPanY, Number(panYRaw) || 0), maxPanY),
    };
}

function officeDraftInitialFocusSpace(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    const selectedSpace = spaces.find((space) => safeString(space?.id) === safeString(state.selectedSpaceId))
        || spaces[0]
        || null;
    if (!spaces.length || typeof officeDraftAgentAssignmentMap !== 'function') return selectedSpace;
    const assignments = officeDraftAgentAssignmentMap(state);
    const selectedAgents = assignments.get(safeString(selectedSpace?.id)) || [];
    if (selectedAgents.length) return selectedSpace;
    let bestSpace = selectedSpace;
    let bestScore = 0;
    spaces.forEach((space) => {
        const spaceId = safeString(space?.id);
        const roomId = officeDraftNormalizeRoomId(space?.roomId, spaceId);
        const agents = assignments.get(spaceId) || [];
        if (!agents.length) return;
        const score = agents.reduce((total, agent) => {
            const agentState = safeString(agent?.state);
            let value = 1;
            if (safeString(agent?.taskId)) value += 8;
            if (agentState === 'working' || agentState === 'walking') value += 5;
            if (agentState === 'break') value += 2;
            if (safeString(agent?.id) === safeString(officeState?.selectedAgentId)) value += 20;
            return total + value;
        }, roomId === 'room-lobby' ? 0 : 2);
        if (score > bestScore) {
            bestScore = score;
            bestSpace = space;
        }
    });
    return bestSpace || selectedSpace;
}

function officeDraftContentBounds(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces.filter(Boolean) : [];
    if (!spaces.length) return null;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    spaces.forEach((space) => {
        const x = Number(space.x) || 0;
        const y = Number(space.y) || 0;
        const w = Number(space.width) || 0;
        const h = Number(space.height) || 0;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + w);
        maxY = Math.max(maxY, y + h);
    });
    if (!Number.isFinite(minX) || !Number.isFinite(maxX)) return null;
    return {
        minX, minY, maxX, maxY,
        width: maxX - minX,
        height: maxY - minY,
        cx: (minX + maxX) / 2,
        cy: (minY + maxY) / 2,
    };
}

function officeDraftFocusSpaceZoom(space, viewport) {
    const width = Math.max(320, Number(space?.width) || 0);
    const height = Math.max(240, Number(space?.height) || 0);
    const shortestSide = Math.min(width, height);
    const padding = Math.max(92, Math.min(160, shortestSide * 0.14));
    const fitZoom = Math.min(
        viewport.width / (width + (padding * 2)),
        viewport.height / (height + (padding * 2)),
    );
    const responsiveFloor = viewport.width < 640 ? 0.38 : (viewport.width < 900 ? 0.5 : 0.64);
    return Math.max(
        responsiveFloor,
        Math.min(1.05, OFFICE_DRAFT_MAP_MAX_ZOOM, fitZoom),
    );
}

function officeDraftApplyFocusedViewport(state, focusSpace, viewport) {
    if (!focusSpace) return false;
    state.zoom = officeDraftFocusSpaceZoom(focusSpace, viewport);
    const focusX = (Number(focusSpace.x) || 0) + ((Number(focusSpace.width) || 0) / 2);
    const focusY = (Number(focusSpace.y) || 0) + ((Number(focusSpace.height) || 0) / 2);
    const clamped = officeClampDraftMapPan(
        focusX - (viewport.width / (2 * state.zoom)),
        focusY - (viewport.height / (2 * state.zoom)),
        state.zoom,
    );
    state.panX = clamped.panX;
    state.panY = clamped.panY;
    return true;
}

function officeCenterDraftMapViewport() {
    const state = officeEnsureDraftMapState();
    const viewport = officeDraftMapViewportRect();
    const focusSpace = officeDraftInitialFocusSpace(state);
    if (focusSpace && !state.initialized && safeString(focusSpace.id) !== safeString(state.selectedSpaceId)) {
        state.selectedSpaceId = safeString(focusSpace.id);
    }
    // Use the full-floor view only when it stays legible. On ordinary desktop
    // screens the complete map is much wider than the viewport; centering its
    // bounds at the minimum zoom turns real agents and tools into a field of
    // indistinct furniture. In that case, frame the active room and keep the
    // minimap as the whole-office navigator.
    if (!state.initialized) {
        const bounds = officeDraftContentBounds(state);
        if (bounds && bounds.width > 0 && bounds.height > 0) {
            const pad = 420;
            const fitZoom = Math.min(
                viewport.width / (bounds.width + pad),
                viewport.height / (bounds.height + pad),
            );
            const OFFICE_DRAFT_LEGIBLE_MIN_ZOOM = 0.5;
            if (fitZoom >= OFFICE_DRAFT_LEGIBLE_MIN_ZOOM) {
                state.zoom = Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, fitZoom);
                const fitClamped = officeClampDraftMapPan(
                    bounds.cx - (viewport.width / (2 * state.zoom)),
                    bounds.cy - (viewport.height / (2 * state.zoom)),
                    state.zoom,
                );
                state.panX = fitClamped.panX;
                state.panY = fitClamped.panY;
                return;
            }
            if (officeDraftApplyFocusedViewport(state, focusSpace, viewport)) return;
        }
    }
    const focusX = focusSpace
        ? (Number(focusSpace.x) || 0) + ((Number(focusSpace.width) || 0) / 2)
        : (OFFICE_DRAFT_MAP_SIZE / 2);
    const focusY = focusSpace
        ? (Number(focusSpace.y) || 0) + ((Number(focusSpace.height) || 0) / 2)
        : (OFFICE_DRAFT_MAP_SIZE / 2);
    const clamped = officeClampDraftMapPan(
        focusX - (viewport.width / (2 * state.zoom)),
        focusY - (viewport.height / (2 * state.zoom)),
        state.zoom,
    );
    state.panX = clamped.panX;
    state.panY = clamped.panY;
}

function officeDraftMapViewportWorldRect() {
    const state = officeEnsureDraftMapState();
    const viewport = officeDraftMapViewportRect();
    return {
        x: state.panX,
        y: state.panY,
        width: viewport.width / state.zoom,
        height: viewport.height / state.zoom,
    };
}


