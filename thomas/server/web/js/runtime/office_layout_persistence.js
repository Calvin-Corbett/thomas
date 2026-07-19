/** Draft-layout persistence, undo, and placement. */

function officeDraftPersistLayout(stateRaw = officeEnsureDraftMapState(), options = {}) {
    const state = stateRaw || officeEnsureDraftMapState();
    if (options.force !== true && state.autosaveEnabled === false) return;
    try {
        if (!window?.localStorage) return;
        const snapshot = officeDraftLayoutSnapshot(state);
        window.localStorage.setItem(OFFICE_DRAFT_LAYOUT_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
        // Ignore storage failures so the editor stays usable.
    }
}

function officeDraftManualSaveLayout(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    officeDraftPersistLayout(state, { force: true });
    officeRenderDraftMapScene();
}

function officeDraftApplySnapshot(snapshotRaw, stateRaw = officeEnsureDraftMapState(), options = {}) {
    const state = stateRaw || officeEnsureDraftMapState();
    if (!snapshotRaw || !Array.isArray(snapshotRaw.spaces) || !snapshotRaw.spaces.length) return false;
    const normalizedSpaces = snapshotRaw.spaces.map((space, spaceIndex) => {
        const spaceId = safeString(space?.id) || `space-${spaceIndex + 1}`;
        return {
            id: spaceId,
            roomId: officeDraftNormalizeRoomId(space?.roomId, spaceId),
            name: safeString(space?.name) || 'Space',
            x: Math.round(Number(space?.x) || 0),
            y: Math.round(Number(space?.y) || 0),
            width: Math.max(320, Math.round(Number(space?.width) || 0)),
            height: Math.max(240, Math.round(Number(space?.height) || 0)),
            floorPalette: OFFICE_DRAFT_ROOM_FLOOR_PALETTES[safeString(space?.floorPalette)] ? safeString(space.floorPalette) : 'tan',
            robotX: Math.round(Number(space?.robotX) || 0),
            robotY: Math.round(Number(space?.robotY) || 0),
            assets: (Array.isArray(space?.assets) ? space.assets : []).map((asset, assetIndex) => {
                const type = OFFICE_DRAFT_ASSET_LIBRARY[safeString(asset?.type)] ? safeString(asset.type) : 'couch';
                return {
                    id: safeString(asset?.id) || `asset-${spaceIndex + 1}-${assetIndex + 1}`,
                    type,
                    x: Math.round(Number(asset?.x) || 0),
                    y: Math.round(Number(asset?.y) || 0),
                    rotation: officeDraftNormalizeRotation(asset?.rotation),
                    colorVariant: safeString(asset?.colorVariant) || officeDraftAssetDefaultColorVariant(type),
                    scale: officeDraftClampAssetScale(asset?.scale),
                };
            }),
        };
    });
    const boundedSpaces = officeDraftFitSpacesToMapBounds(normalizedSpaces);
    state.spaces = boundedSpaces;
    state.nextAssetId = Math.max(1, Number(snapshotRaw.nextAssetId) || 1);
    state.rotationStep = officeDraftRotationOptions().includes(Number(snapshotRaw.rotationStep)) ? Number(snapshotRaw.rotationStep) : 15;
    state.gridEnabled = snapshotRaw.gridEnabled !== false;
    state.selectedSpaceId = boundedSpaces.some((space) => safeString(space.id) === safeString(snapshotRaw.selectedSpaceId))
        ? safeString(snapshotRaw.selectedSpaceId)
        : safeString(boundedSpaces[0]?.id);
    const assetExists = boundedSpaces.some((space) => Array.isArray(space.assets) && space.assets.some((asset) => safeString(asset.id) === safeString(snapshotRaw.selectedAssetId)));
    state.selectedAssetId = assetExists ? safeString(snapshotRaw.selectedAssetId) : null;
    state.catalogPointerId = null;
    state.catalogPendingType = '';
    state.catalogPreviewSpaceId = '';
    state.catalogPreviewX = 0;
    state.catalogPreviewY = 0;
    state.assetPointerId = null;
    state.assetDragSpaceId = '';
    state.assetDragId = '';
    state.assetDragOffsetX = 0;
    state.assetDragOffsetY = 0;
    state.assetDragSnapshot = null;
    if (options.resetUndo) {
        state.undoStack = [];
    }
    if (options.persist !== false) {
        officeDraftPersistLayout(state);
    }
    return true;
}

function officeDraftCommitLayoutChange(previousSnapshot, stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    if (!previousSnapshot) {
        officeDraftPersistLayout(state);
        return false;
    }
    const before = JSON.stringify(previousSnapshot);
    const afterSnapshot = officeDraftLayoutSnapshot(state);
    const after = JSON.stringify(afterSnapshot);
    if (before === after) {
        officeDraftPersistLayout(state);
        return false;
    }
    if (!Array.isArray(state.undoStack)) {
        state.undoStack = [];
    }
    const lastSnapshot = state.undoStack[state.undoStack.length - 1] || null;
    if (!lastSnapshot || JSON.stringify(lastSnapshot) !== before) {
        state.undoStack.push(officeDraftCloneLayoutPayload(previousSnapshot));
        if (state.undoStack.length > OFFICE_DRAFT_UNDO_LIMIT) {
            state.undoStack.splice(0, state.undoStack.length - OFFICE_DRAFT_UNDO_LIMIT);
        }
    }
    officeDraftPersistLayout(state);
    return true;
}

function officeDraftUndoLastChange(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    if (!Array.isArray(state.undoStack) || !state.undoStack.length) return;
    const snapshot = state.undoStack.pop();
    if (!snapshot) return;
    officeDraftApplySnapshot(snapshot, state, { persist: true, resetUndo: false });
    officeRenderDraftMapScene();
}

function officeDraftPlaceAssetInSpace(space, assetType, worldX, worldY, options = {}) {
    if (!space || !OFFICE_DRAFT_ASSET_LIBRARY[safeString(assetType)]) return null;
    const dimensions = officeDraftAssetDimensions(assetType, options.scale || 1);
    const snapEnabled = options.gridEnabled !== false;
    const rotation = officeDraftNormalizeRotation(options.rotation || 0);
    const x = Math.max(24, Math.min(
        Number(space.width) - dimensions.width - 24,
        officeDraftSnap(Number(worldX) - Number(space.x) - (dimensions.width / 2), OFFICE_DRAFT_MAP_MINOR_GRID, snapEnabled),
    ));
    const y = Math.max(24, Math.min(
        Number(space.height) - dimensions.height - 24,
        officeDraftSnap(Number(worldY) - Number(space.y) - (dimensions.height / 2), OFFICE_DRAFT_MAP_MINOR_GRID, snapEnabled),
    ));
    return { x, y, rotation, scale: dimensions.scale };
}

function officeDraftMapClientToWorld(clientX, clientY) {
    const state = officeEnsureDraftMapState();
    const rect = officeSceneWrap?.getBoundingClientRect();
    const viewport = officeDraftMapViewportRect();
    const localX = rect ? clientX - rect.left : viewport.width / 2;
    const localY = rect ? clientY - rect.top : viewport.height / 2;
    return {
        x: state.panX + (localX / state.zoom),
        y: state.panY + (localY / state.zoom),
    };
}


