/** Draft-layout selection, geometry, and color primitives. */

function officeDraftRoomPalette(paletteId) {
    return OFFICE_DRAFT_ROOM_FLOOR_PALETTES[safeString(paletteId)] || OFFICE_DRAFT_ROOM_FLOOR_PALETTES.tan;
}

function officeDraftSelectedSpace() {
    const state = officeEnsureDraftMapState();
    return state.spaces.find((space) => safeString(space?.id) === safeString(state.selectedSpaceId)) || state.spaces[0] || null;
}

function officeDraftFindSpace(spaceId) {
    const state = officeEnsureDraftMapState();
    return state.spaces.find((space) => safeString(space?.id) === safeString(spaceId)) || null;
}

function officeDraftFindAsset(assetId) {
    const state = officeEnsureDraftMapState();
    for (const space of state.spaces) {
        const asset = Array.isArray(space?.assets) ? space.assets.find((item) => safeString(item?.id) === safeString(assetId)) : null;
        if (asset) {
            return { space, asset };
        }
    }
    return null;
}

function officeDraftSpaceAtWorldPoint(worldX, worldY) {
    const state = officeEnsureDraftMapState();
    return state.spaces.find((space) => (
        Number(worldX) >= Number(space?.x)
        && Number(worldX) <= Number(space?.x) + Number(space?.width)
        && Number(worldY) >= Number(space?.y)
        && Number(worldY) <= Number(space?.y) + Number(space?.height)
    )) || null;
}

function officeDraftRotationOptions() {
    return [15, 30, 45];
}

function officeDraftNormalizeRotation(value) {
    const normalized = Number(value) || 0;
    const wrapped = ((normalized % 360) + 360) % 360;
    return Math.round(wrapped);
}

function officeDraftSnap(value, gridSize, enabled = true) {
    if (!enabled) return Math.round(Number(value) || 0);
    const size = Math.max(1, Number(gridSize) || 1);
    return Math.round((Number(value) || 0) / size) * size;
}

function officeDraftCloneLayoutPayload(payload) {
    try {
        return JSON.parse(JSON.stringify(payload));
    } catch {
        return null;
    }
}

function officeDraftClampAssetScale(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 1;
    return Math.min(OFFICE_DRAFT_ASSET_SCALE_MAX, Math.max(OFFICE_DRAFT_ASSET_SCALE_MIN, Math.round(numeric * 20) / 20));
}

function officeDraftAssetDimensions(assetType, scaleRaw = 1) {
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[safeString(assetType)] || OFFICE_DRAFT_ASSET_LIBRARY.couch;
    const scale = officeDraftClampAssetScale(scaleRaw);
    const renderScale = scale * (Number(OFFICE_DRAFT_ASSET_RENDER_SCALE) || 1);
    return {
        width: Math.round(descriptor.width * renderScale),
        height: Math.round(descriptor.height * renderScale),
        scale: renderScale,
        layoutScale: scale,
    };
}

function officeDraftAssetDefaultColorVariant(assetType) {
    const type = safeString(assetType) || 'couch';
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || OFFICE_DRAFT_ASSET_LIBRARY.couch;
    const colorways = OFFICE_DRAFT_ASSET_COLORWAYS[type]
        || OFFICE_DRAFT_ASSET_COLORWAYS[safeString(descriptor?.colorGroup)]
        || OFFICE_DRAFT_ASSET_COLORWAYS.couch
        || {};
    const preferred = safeString(descriptor?.defaultColorVariant);
    if (preferred && colorways[preferred]) return preferred;
    const first = Object.keys(colorways)[0];
    return first || 'caramel';
}

function officeDraftAssetColorway(assetType, colorId) {
    const type = safeString(assetType) || 'couch';
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || OFFICE_DRAFT_ASSET_LIBRARY.couch;
    const colorways = OFFICE_DRAFT_ASSET_COLORWAYS[type]
        || OFFICE_DRAFT_ASSET_COLORWAYS[safeString(descriptor?.colorGroup)]
        || OFFICE_DRAFT_ASSET_COLORWAYS.couch;
    const fallbackId = officeDraftAssetDefaultColorVariant(type);
    return colorways[safeString(colorId)] || colorways[fallbackId] || colorways.caramel || Object.values(colorways)[0];
}

function officeDraftNormalizeRoomId(roomIdRaw, fallbackRaw = '') {
    const roomId = safeString(roomIdRaw);
    if (roomId && officeRoomById(roomId)) return roomId;
    const fallback = safeString(fallbackRaw);
    if (fallback && officeRoomById(fallback)) return fallback;
    return 'room-lobby';
}

function officeDraftLayoutSnapshot(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    return {
        schemaVersion: OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION,
        selectedSpaceId: safeString(state.selectedSpaceId),
        selectedAssetId: safeString(state.selectedAssetId),
        rotationStep: officeDraftRotationOptions().includes(Number(state.rotationStep)) ? Number(state.rotationStep) : 15,
        gridEnabled: state.gridEnabled !== false,
        nextAssetId: Math.max(1, Number(state.nextAssetId) || 1),
        spaces: (Array.isArray(state.spaces) ? state.spaces : []).map((space) => ({
            id: safeString(space?.id),
            roomId: officeDraftNormalizeRoomId(space?.roomId, space?.id),
            name: safeString(space?.name) || 'Space',
            x: Math.round(Number(space?.x) || 0),
            y: Math.round(Number(space?.y) || 0),
            width: Math.max(320, Math.round(Number(space?.width) || 0)),
            height: Math.max(240, Math.round(Number(space?.height) || 0)),
            floorPalette: safeString(space?.floorPalette) || 'tan',
            robotX: Math.round(Number(space?.robotX) || 0),
            robotY: Math.round(Number(space?.robotY) || 0),
            assets: (Array.isArray(space?.assets) ? space.assets : []).map((asset) => ({
                id: safeString(asset?.id),
                type: safeString(asset?.type) || 'couch',
                x: Math.round(Number(asset?.x) || 0),
                y: Math.round(Number(asset?.y) || 0),
                rotation: officeDraftNormalizeRotation(asset?.rotation),
                colorVariant: safeString(asset?.colorVariant) || officeDraftAssetDefaultColorVariant(asset?.type),
                scale: officeDraftClampAssetScale(asset?.scale),
            })),
        })),
    };
}

function officeDraftLoadStoredLayout() {
    try {
        if (!window?.localStorage) return null;
        const raw = window.localStorage.getItem(OFFICE_DRAFT_LAYOUT_STORAGE_KEY);
        if (!raw) return null;
        return officeDraftCloneLayoutPayload(JSON.parse(raw));
    } catch {
        return null;
    }
}

function officeDraftLoadAutosavePreference() {
    try {
        if (!window?.localStorage) return true;
        return window.localStorage.getItem(OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY) !== '0';
    } catch {
        return true;
    }
}

function officeDraftSetAutosavePreference(enabledRaw, stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    const enabled = enabledRaw !== false;
    state.autosaveEnabled = enabled;
    try {
        if (window?.localStorage) {
            window.localStorage.setItem(OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY, enabled ? '1' : '0');
        }
    } catch {
        // Ignore preference storage failures.
    }
    if (enabled) {
        officeDraftPersistLayout(state, { force: true });
    }
}


