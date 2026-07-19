/** Wheel, keyboard, resize, and minimap controls. */

function officeHandleDraftMapWheel(event) {
    if (officeDraftMapWheelPassesThrough(event)) return;
    event.preventDefault();
    event.stopPropagation();
    const state = officeEnsureDraftMapState();
    officeDraftCancelAgentHoverRender(state);
    const viewport = officeDraftMapViewportRect();
    const rect = officeSceneWrap?.getBoundingClientRect();
    const pointerX = rect ? event.clientX - rect.left : viewport.width / 2;
    const pointerY = rect ? event.clientY - rect.top : viewport.height / 2;
    const anchorWorldX = state.panX + (pointerX / state.zoom);
    const anchorWorldY = state.panY + (pointerY / state.zoom);
    const deltaUnit = event.deltaMode === 1 ? 14 : (event.deltaMode === 2 ? 120 : 1);
    const clampedDelta = Math.max(-180, Math.min(180, (Number(event.deltaY) || 0) * deltaUnit));
    const previousZoom = state.zoom;
    const zoomFactor = Math.exp(-clampedDelta * 0.0009);
    state.zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, state.zoom * zoomFactor));
    state.panX = anchorWorldX - (pointerX / state.zoom);
    state.panY = anchorWorldY - (pointerY / state.zoom);
    state.lastWheelDelta = Math.round(clampedDelta);
    state.lastZoomDelta = Math.round((state.zoom - previousZoom) * 10000) / 10000;
    state.lastWheelAt = performance.now();
    state.lastInputMode = 'wheel';
    state.agentLayerQuietUntil = state.lastWheelAt + OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS + 80;
    state.routePlanQuietUntil = state.lastWheelAt + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS;
    if (state.sceneRenderDeferred) {
        officeDraftScheduleSceneRenderAfterInput(state, state.lastWheelAt);
    }
    officeApplyDraftMapTransform({ deferMinimap: true });
    window.clearTimeout(state.wheelSettleTimer);
    state.wheelSettleTimer = window.setTimeout(() => {
        state.agentLayerQuietUntil = 0;
        officeDraftFlushSceneOrAgentLayerAfterInput(state, 'wheel-settle');
        officeRenderDraftMapMinimapThrottled(true);
    }, OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS);
}

function officeHandleDraftMapKeydown(event) {
    const state = officeEnsureDraftMapState();
    if (event.target instanceof Element && event.target.closest('input, select, textarea, [contenteditable="true"]')) return;
    if ((event.ctrlKey || event.metaKey) && safeString(event.key).toLowerCase() === 'z') {
        officeDraftUndoLastChange(event);
        return;
    }
    if (state.editorOpen && state.selectedAssetId) {
        const assetRef = officeDraftFindAsset(state.selectedAssetId);
        if (assetRef) {
            if (event.key === 'a' || event.key === 'A') {
                const previousSnapshot = officeDraftLayoutSnapshot(state);
                assetRef.asset.rotation = officeDraftNormalizeRotation((assetRef.asset.rotation || 0) - state.rotationStep);
                officeDraftCommitLayoutChange(previousSnapshot, state);
                event.preventDefault();
                officeRenderDraftMapScene();
                return;
            } else if (event.key === 'd' || event.key === 'D') {
                const previousSnapshot = officeDraftLayoutSnapshot(state);
                assetRef.asset.rotation = officeDraftNormalizeRotation((assetRef.asset.rotation || 0) + state.rotationStep);
                officeDraftCommitLayoutChange(previousSnapshot, state);
                event.preventDefault();
                officeRenderDraftMapScene();
                return;
            }
        }
    }
    const step = 160 / state.zoom;
    if (event.key === 'ArrowLeft') state.panX -= step;
    else if (event.key === 'ArrowRight') state.panX += step;
    else if (event.key === 'ArrowUp') state.panY -= step;
    else if (event.key === 'ArrowDown') state.panY += step;
    else return;
    event.preventDefault();
    officeApplyDraftMapTransform();
}

function officeHandleDraftMapResize() {
    const state = officeEnsureDraftMapState();
    const clamped = officeClampDraftMapPan(state.panX, state.panY, state.zoom);
    state.panX = clamped.panX;
    state.panY = clamped.panY;
    officeApplyDraftMapTransform();
}

function officeToggleDraftMinimapMinimized(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.minimapMinimized = !state.minimapMinimized;
    officePrepareDraftMapShell();
    officeRenderDraftMapMinimap();
}

function officeToggleDraftMinimapLocked(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.minimapLocked = state.minimapLocked !== true;
    state.minimapPointerId = null;
    state.minimapResizePointerId = null;
    officePrepareDraftMapShell();
}

function officeDraftPanCameraToMinimapEvent(event) {
    if (!(officeMinimapCanvas instanceof HTMLCanvasElement)) return;
    const state = officeEnsureDraftMapState();
    const rect = officeMinimapCanvas.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return;
    const localX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const localY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    const viewport = officeDraftMapViewportRect();
    const worldX = (localX / rect.width) * OFFICE_DRAFT_MAP_SIZE;
    const worldY = (localY / rect.height) * OFFICE_DRAFT_MAP_SIZE;
    state.panX = worldX - (viewport.width / (state.zoom * 2));
    state.panY = worldY - (viewport.height / (state.zoom * 2));
    state.lastInputMode = 'minimap';
    state.lastPanAt = performance.now();
    officeApplyDraftMapTransform({ deferMinimap: true });
    officeRenderDraftMapMinimapThrottled(true);
}

function officeHandleDraftMinimapPointerDown(event) {
    if (event.button !== 0) return;
    if (event.target instanceof Element) {
        if (event.target.closest('[data-office-minimap-lock="1"]')) return;
        if (event.target.closest('#officeFollowToggleBtn')) return;
        if (event.target.closest('[data-office-minimap-resize="1"]')) return;
    }
    event.preventDefault();
    event.stopPropagation();
    const state = officeEnsureDraftMapState();
    state.minimapPointerId = event.pointerId;
    state.minimapDragStartX = event.clientX;
    state.minimapDragStartY = event.clientY;
    state.minimapDragOffsetX = state.minimapOffsetX;
    state.minimapDragOffsetY = state.minimapOffsetY;
    state.minimapPointerMode = event.target instanceof Element
        && event.target.closest('.office-minimap-head')
        && state.minimapLocked !== true
        ? 'panel'
        : 'camera';
    if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (state.minimapPointerMode === 'camera') {
        officeDraftPanCameraToMinimapEvent(event);
    }
    officePrepareDraftMapShell();
}

function officeHandleDraftMinimapPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapPointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    if (state.minimapPointerMode === 'panel' && state.minimapLocked !== true) {
        state.minimapOffsetX = state.minimapDragOffsetX + (event.clientX - state.minimapDragStartX);
        state.minimapOffsetY = state.minimapDragOffsetY + (event.clientY - state.minimapDragStartY);
        officePrepareDraftMapShell();
        return;
    }
    officeDraftPanCameraToMinimapEvent(event);
}

function officeHandleDraftMinimapPointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapPointerId !== null && event.pointerId !== state.minimapPointerId) return;
    if (event.currentTarget instanceof HTMLElement && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.preventDefault();
    event.stopPropagation();
    state.minimapPointerId = null;
    state.minimapPointerMode = 'camera';
    officePrepareDraftMapShell();
}

function officeHandleDraftMinimapResizePointerDown(event) {
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (state.minimapLocked) return;
    event.preventDefault();
    event.stopPropagation();
    state.minimapResizePointerId = event.pointerId;
    state.minimapResizeStartX = event.clientX;
    state.minimapResizeStartY = event.clientY;
    state.minimapResizeStartSize = state.minimapSize;
    if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
}

function officeHandleDraftMinimapResizePointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapResizePointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const delta = Math.max(event.clientX - state.minimapResizeStartX, event.clientY - state.minimapResizeStartY);
    state.minimapSize = Math.max(150, Math.min(420, state.minimapResizeStartSize + delta));
    officePrepareDraftMapShell();
    officeRenderDraftMapMinimap();
}

function officeHandleDraftMinimapResizePointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapResizePointerId !== null && event.pointerId !== state.minimapResizePointerId) return;
    if (event.currentTarget instanceof HTMLElement && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.preventDefault();
    event.stopPropagation();
    state.minimapResizePointerId = null;
}

// 
