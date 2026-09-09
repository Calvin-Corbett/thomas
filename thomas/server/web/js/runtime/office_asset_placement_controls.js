/** Office editor placement and layer controls. */

function officeToggleDraftEditor(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.editorOpen = !state.editorOpen;
    state.selectedAssetId = null;
    officeDraftPersistLayout(state);
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-click' });
}

function officeDraftAddCatalogAsset(assetType) {
    const state = officeEnsureDraftMapState();
    const descriptor = officeDraftAssetDimensions(assetType, 1);
    const space = officeDraftSelectedSpace();
    if (!descriptor || !space) return;
    const previousSnapshot = officeDraftLayoutSnapshot(state);
    const assetId = `${safeString(assetType)}-${state.nextAssetId++}`;
    const offset = Math.max(0, (Array.isArray(space.assets) ? space.assets.length : 0) * 42);
    const asset = {
        id: assetId,
        type: safeString(assetType),
        x: Math.max(24, Math.min(space.width - descriptor.width - 24, Math.round((space.width - descriptor.width) / 2) + offset)),
        y: Math.max(24, Math.min(space.height - descriptor.height - 24, Math.round((space.height - descriptor.height) / 2) + 100)),
        rotation: 0,
        colorVariant: officeDraftAssetDefaultColorVariant(assetType),
        scale: 1,
    };
    space.assets = Array.isArray(space.assets) ? [...space.assets, asset] : [asset];
    state.selectedAssetId = assetId;
    officeDraftCommitLayoutChange(previousSnapshot, state);
    officeRenderDraftMapScene();
}

function officeDraftBeginCatalogPlacement(assetType, pointerId, clientX, clientY) {
    const state = officeEnsureDraftMapState();
    state.catalogPointerId = pointerId;
    state.catalogPendingType = safeString(assetType);
    state.catalogPreviewSpaceId = '';
    state.catalogPreviewX = 0;
    state.catalogPreviewY = 0;
    state.selectedAssetId = null;
    const worldPoint = officeDraftMapClientToWorld(clientX, clientY);
    const previewSpace = worldPoint ? officeDraftSpaceAtWorldPoint(worldPoint.x, worldPoint.y) : null;
    const previewPlacement = previewSpace && worldPoint
        ? officeDraftPlaceAssetInSpace(previewSpace, state.catalogPendingType, worldPoint.x, worldPoint.y, { gridEnabled: state.gridEnabled })
        : null;
    if (previewSpace && previewPlacement) {
        state.catalogPreviewSpaceId = safeString(previewSpace.id);
        state.catalogPreviewX = previewPlacement.x;
        state.catalogPreviewY = previewPlacement.y;
        state.selectedSpaceId = safeString(previewSpace.id);
    }
    officeRenderDraftMapScene();
}

function officeDraftMoveSelectedAssetLayer(actionRaw) {
    const state = officeEnsureDraftMapState();
    const assetRef = state.selectedAssetId ? officeDraftFindAsset(state.selectedAssetId) : null;
    const assets = Array.isArray(assetRef?.space?.assets) ? assetRef.space.assets : null;
    if (!assetRef?.asset || !assets) return false;
    const currentIndex = assets.findIndex((asset) => safeString(asset?.id) === safeString(assetRef.asset.id));
    if (currentIndex < 0) return false;
    const action = safeString(actionRaw);
    let nextIndex = currentIndex;
    if (action === 'back') nextIndex = 0;
    else if (action === 'front') nextIndex = assets.length - 1;
    else if (action === 'down') nextIndex = Math.max(0, currentIndex - 1);
    else if (action === 'up') nextIndex = Math.min(assets.length - 1, currentIndex + 1);
    if (nextIndex === currentIndex) return false;
    const previousSnapshot = officeDraftLayoutSnapshot(state);
    const [asset] = assets.splice(currentIndex, 1);
    assets.splice(nextIndex, 0, asset);
    officeDraftCommitLayoutChange(previousSnapshot, state);
    return true;
}

function officeDraftNearestAgentIdAtClient(clientXRaw, clientYRaw, maxDistanceRaw = 82, preferredAgentIdRaw = '') {
    const clientX = Number(clientXRaw);
    const clientY = Number(clientYRaw);
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return '';
    const maxDistance = Math.max(24, Number(maxDistanceRaw) || 82);
    const preferredAgentId = safeString(preferredAgentIdRaw);
    let best = null;
    document.querySelectorAll('[data-office-draft-agent-id]').forEach((node) => {
        if (!(node instanceof HTMLElement)) return;
        const agentId = safeString(node.dataset.officeDraftAgentId);
        const rect = node.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) return;
        const centerX = rect.left + (rect.width / 2);
        const centerY = rect.top + (rect.height / 2);
        const dx = clientX - centerX;
        const dy = clientY - centerY;
        const distance = Math.hypot(dx, dy);
        const hitRadius = Math.max(maxDistance, (Math.max(rect.width, rect.height) / 2) + 24);
        const insideExpandedRect = clientX >= rect.left - 34
            && clientX <= rect.right + 34
            && clientY >= rect.top - 34
            && clientY <= rect.bottom + 34;
        if (distance > hitRadius && !insideExpandedRect) return;
        const score = distance - (agentId && agentId === preferredAgentId ? maxDistance + 1000 : 0);
        if (!best || score < best.score) {
            best = { agentId, distance, score };
        }
    });
    return safeString(best?.agentId);
}


