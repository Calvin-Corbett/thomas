/** Map binding and pointer navigation controls. */

function officeBindDraftMapControls() {
    if (!(officeSceneWrap instanceof HTMLElement) || officeSceneWrap.dataset.officeDraftMapBound === '1') return;
    officeSceneWrap.dataset.officeDraftMapBound = '1';
    officeSceneWrap.addEventListener('pointerdown', officeHandleDraftMapPointerDown);
    officeSceneWrap.addEventListener('pointermove', officeHandleDraftMapPointerMove);
    officeSceneWrap.addEventListener('pointerup', officeHandleDraftMapPointerUp);
    officeSceneWrap.addEventListener('pointercancel', officeHandleDraftMapPointerUp);
    officeSceneWrap.addEventListener('mousemove', officeHandleDraftMapMouseMove, { passive: true });
    officeSceneWrap.addEventListener('wheel', officeHandleDraftMapWheel, { passive: false });
    officeSceneWrap.addEventListener('keydown', officeHandleDraftMapKeydown);
    officeSceneWrap.addEventListener('click', officeHandleDraftMapClick);
    window.addEventListener('resize', officeHandleDraftMapResize);
    if (officeMinimap instanceof HTMLElement) {
        officeMinimap.addEventListener('pointerdown', officeHandleDraftMinimapPointerDown);
        officeMinimap.addEventListener('pointermove', officeHandleDraftMinimapPointerMove);
        officeMinimap.addEventListener('pointerup', officeHandleDraftMinimapPointerUp);
        officeMinimap.addEventListener('pointercancel', officeHandleDraftMinimapPointerUp);
    }
    const minimapResizeHandle = officeMinimap?.querySelector('[data-office-minimap-resize="1"]');
    if (minimapResizeHandle instanceof HTMLElement) {
        minimapResizeHandle.addEventListener('pointerdown', officeHandleDraftMinimapResizePointerDown);
        minimapResizeHandle.addEventListener('pointermove', officeHandleDraftMinimapResizePointerMove);
        minimapResizeHandle.addEventListener('pointerup', officeHandleDraftMinimapResizePointerUp);
        minimapResizeHandle.addEventListener('pointercancel', officeHandleDraftMinimapResizePointerUp);
    }
    if (officeFollowToggleBtn instanceof HTMLElement) {
        officeFollowToggleBtn.addEventListener('click', officeToggleDraftMinimapMinimized);
    }
}

function officeDraftMapWheelPassesThrough(event) {
    const target = event?.target;
    if (!(target instanceof Element)) return false;
    if (officeMinimap instanceof HTMLElement && officeMinimap.contains(target)) return true;
    if (target.closest('[data-office-map-toolbar="1"]')) return true;
    if (target.closest('[data-office-editor-panel="1"]')) return true;
    if (target.closest('[data-office-agent-roster-panel="1"]')) return true;
    if (target.closest('[data-office-agent-chat-panel="1"]')) return true;
    if (target.closest('input, select, textarea, [contenteditable="true"]')) return true;
    return false;
}

function officeHandleDraftMapMouseMove(event) {
    if (officeDraftMapWheelPassesThrough(event)) return;
    const state = officeEnsureDraftMapState();
    if (state.pointerId !== null || state.assetPointerId !== null || state.catalogPointerId !== null || state.agentPointerId !== null) return;
    const now = performance.now();
    if ((now - (Number(state.lastPointerIntentAt) || 0)) < 80) return;
    state.lastPointerIntentAt = now;
    state.agentLayerQuietUntil = Math.max(Number(state.agentLayerQuietUntil) || 0, now + OFFICE_DRAFT_AGENT_POINTER_QUIET_MS);
    state.routePlanQuietUntil = Math.max(Number(state.routePlanQuietUntil) || 0, now + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS);
    if (state.agentRoutePlanTimer) {
        window.clearTimeout(state.agentRoutePlanTimer);
        state.agentRoutePlanTimer = 0;
        officeDraftScheduleDeferredRoutePlan(state, now);
    }
}

function officeHandleDraftMapPointerDown(event) {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (event.target instanceof Element) {
        if (officeMinimap instanceof HTMLElement && officeMinimap.contains(event.target)) return;
        if (event.target.closest('[data-office-map-toolbar="1"]')) return;
        const agentTarget = event.target.closest('[data-office-draft-agent-id]');
        if (agentTarget instanceof HTMLElement) {
            officeDraftHandleAgentPointerDown(event, agentTarget.dataset.officeDraftAgentId);
            return;
        }
        if (event.target.closest('[data-office-agent-roster-panel="1"]')) return;
        if (event.target.closest('[data-office-agent-chat-panel="1"]')) return;
        if (event.target.closest('[data-office-editor-panel="1"]')) {
            const catalogBtn = event.target.closest('[data-office-editor-catalog-asset]');
            if (catalogBtn instanceof HTMLElement && state.editorOpen) {
                officeDraftBeginCatalogPlacement(catalogBtn.dataset.officeEditorCatalogAsset, event.pointerId, event.clientX, event.clientY);
                officeSceneWrap.style.cursor = 'grabbing';
                officeSceneWrap.setPointerCapture(event.pointerId);
            }
            return;
        }
        if (state.editorOpen) {
            if (event.target.closest('[data-office-draft-space-label]')) return;
            const assetEl = event.target.closest('[data-office-draft-asset-id]');
            if (assetEl instanceof HTMLElement) {
                const assetRef = officeDraftFindAsset(assetEl.dataset.officeDraftAssetId);
                const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
                if (assetRef && worldPoint) {
                    state.assetPointerId = event.pointerId;
                    state.assetDragSpaceId = safeString(assetRef.space?.id);
                    state.assetDragId = safeString(assetRef.asset?.id);
                    state.assetDragSnapshot = officeDraftLayoutSnapshot(state);
                    state.selectedSpaceId = safeString(assetRef.space?.id);
                    state.selectedAssetId = safeString(assetRef.asset?.id);
                    state.assetDragOffsetX = worldPoint.x - (Number(assetRef.space?.x) + Number(assetRef.asset?.x));
                    state.assetDragOffsetY = worldPoint.y - (Number(assetRef.space?.y) + Number(assetRef.asset?.y));
                    officeSceneWrap.style.cursor = 'grabbing';
                    officeSceneWrap.setPointerCapture(event.pointerId);
                    officeRenderDraftMapScene();
                    return;
                }
            }
        }
    }
    if (state.editorOpen !== true) {
        const preferredAgentId = safeString(state.hoveredAgentId);
        const nearbyAgentId = officeDraftNearestAgentIdAtClient(
            event.clientX,
            event.clientY,
            preferredAgentId ? 124 : 56,
            preferredAgentId,
        );
        if (nearbyAgentId) {
            officeDraftHandleAgentPointerDown(event, nearbyAgentId);
            return;
        }
    }
    state.pointerId = event.pointerId;
    state.dragStartX = event.clientX;
    state.dragStartY = event.clientY;
    state.dragPanX = state.panX;
    state.dragPanY = state.panY;
    officeDraftCancelAgentHoverRender(state);
    state.lastPanAt = performance.now();
    state.lastInputMode = 'pan';
    if (state.sceneRenderDeferred) {
        officeDraftScheduleSceneRenderAfterInput(state, state.lastPanAt);
    }
    event.preventDefault();
    officeSceneWrap.style.cursor = 'grabbing';
    officeSceneWrap.setPointerCapture(event.pointerId);
}

function officeHandleDraftMapPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (officeDraftHandleAgentPointerMove(event)) return;
    if (state.pointerId !== event.pointerId
        && state.catalogPointerId !== event.pointerId
        && state.assetPointerId !== event.pointerId
        && Number(event.buttons) === 0) {
        officeDraftCancelAgentHoverRender(state);
    }
    if (state.catalogPointerId === event.pointerId && safeString(state.catalogPendingType)) {
        const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
        const previewSpace = worldPoint ? officeDraftSpaceAtWorldPoint(worldPoint.x, worldPoint.y) : null;
        const previewPlacement = previewSpace && worldPoint
            ? officeDraftPlaceAssetInSpace(previewSpace, state.catalogPendingType, worldPoint.x, worldPoint.y, { gridEnabled: state.gridEnabled })
            : null;
        if (previewSpace && previewPlacement) {
            state.catalogPreviewSpaceId = safeString(previewSpace.id);
            state.catalogPreviewX = previewPlacement.x;
            state.catalogPreviewY = previewPlacement.y;
            state.selectedSpaceId = safeString(previewSpace.id);
            if (officeSceneWrap instanceof HTMLElement) {
                officeSceneWrap.style.cursor = 'copy';
            }
        } else {
            state.catalogPreviewSpaceId = '';
            state.catalogPreviewX = 0;
            state.catalogPreviewY = 0;
            if (officeSceneWrap instanceof HTMLElement) {
                officeSceneWrap.style.cursor = 'not-allowed';
            }
        }
        officeRenderDraftMapScene();
        return;
    }
    if (state.assetPointerId === event.pointerId && state.assetDragId) {
        const assetRef = officeDraftFindAsset(state.assetDragId);
        const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
        if (assetRef && worldPoint) {
            const descriptor = officeDraftAssetDimensions(assetRef.asset?.type, assetRef.asset?.scale);
            assetRef.asset.x = Math.max(24, Math.min(
                Number(assetRef.space?.width) - descriptor.width - 24,
                officeDraftSnap(
                    worldPoint.x - Number(assetRef.space?.x) - state.assetDragOffsetX,
                    OFFICE_DRAFT_MAP_MINOR_GRID,
                    state.gridEnabled,
                ),
            ));
            assetRef.asset.y = Math.max(24, Math.min(
                Number(assetRef.space?.height) - descriptor.height - 24,
                officeDraftSnap(
                    worldPoint.y - Number(assetRef.space?.y) - state.assetDragOffsetY,
                    OFFICE_DRAFT_MAP_MINOR_GRID,
                    state.gridEnabled,
                ),
            ));
            officeRenderDraftMapScene();
        }
        return;
    }
    if (state.pointerId !== event.pointerId) return;
    event.preventDefault();
    const deltaX = event.clientX - state.dragStartX;
    const deltaY = event.clientY - state.dragStartY;
    state.panX = state.dragPanX - (deltaX / state.zoom);
    state.panY = state.dragPanY - (deltaY / state.zoom);
    state.lastPanAt = performance.now();
    state.lastPanDeltaScreen = Math.round(Math.hypot(deltaX, deltaY));
    state.lastInputMode = 'pan';
    officeApplyDraftMapTransform({ deferMinimap: true });
}

function officeHandleDraftMapPointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (officeDraftHandleAgentPointerUp(event)) return;
    if (state.catalogPointerId !== null && event.pointerId === state.catalogPointerId) {
        if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
            officeSceneWrap.releasePointerCapture(event.pointerId);
        }
        const pendingType = safeString(state.catalogPendingType);
        const previousSnapshot = officeDraftLayoutSnapshot(state);
        const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
        const previewSpace = worldPoint ? officeDraftSpaceAtWorldPoint(worldPoint.x, worldPoint.y) : null;
        const previewPlacement = previewSpace && worldPoint
            ? officeDraftPlaceAssetInSpace(previewSpace, pendingType, worldPoint.x, worldPoint.y, { gridEnabled: state.gridEnabled })
            : null;
        if (pendingType && previewSpace && previewPlacement) {
            const assetId = `${pendingType}-${state.nextAssetId++}`;
            const asset = {
                id: assetId,
                type: pendingType,
                x: previewPlacement.x,
                y: previewPlacement.y,
                rotation: previewPlacement.rotation,
                colorVariant: officeDraftAssetDefaultColorVariant(pendingType),
                scale: previewPlacement.scale,
            };
            previewSpace.assets = Array.isArray(previewSpace.assets) ? [...previewSpace.assets, asset] : [asset];
            state.selectedSpaceId = safeString(previewSpace.id);
            state.selectedAssetId = assetId;
        }
        state.catalogPointerId = null;
        state.catalogPendingType = '';
        state.catalogPreviewSpaceId = '';
        state.catalogPreviewX = 0;
        state.catalogPreviewY = 0;
        if (officeSceneWrap instanceof HTMLElement) {
            officeSceneWrap.style.cursor = 'grab';
        }
        officeDraftCommitLayoutChange(previousSnapshot, state);
        officeRenderDraftMapScene();
        return;
    }
    if (state.assetPointerId !== null && event.pointerId === state.assetPointerId) {
        if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
            officeSceneWrap.releasePointerCapture(event.pointerId);
        }
        state.assetPointerId = null;
        state.assetDragSpaceId = '';
        state.assetDragId = '';
        officeDraftCommitLayoutChange(state.assetDragSnapshot, state);
        state.assetDragSnapshot = null;
        if (officeSceneWrap instanceof HTMLElement) {
            officeSceneWrap.style.cursor = 'grab';
        }
        officeRenderDraftMapScene();
        return;
    }
    if (state.pointerId !== null && event.pointerId !== state.pointerId) return;
    const panMoved = Number(state.lastPanDeltaScreen) || 0;
    if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
        officeSceneWrap.releasePointerCapture(event.pointerId);
    }
    state.pointerId = null;
    state.lastPanAt = performance.now();
    state.agentLayerQuietUntil = state.lastPanAt + OFFICE_DRAFT_AGENT_PAN_QUIET_MS + 80;
    state.routePlanQuietUntil = state.lastPanAt + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS;
    if (panMoved > 8) {
        state.suppressAgentClickUntil = performance.now() + 320;
    }
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grab';
    }
    officeRenderDraftMapMinimapThrottled(true);
    window.clearTimeout(state.panSettleTimer);
    state.panSettleTimer = window.setTimeout(() => {
        state.agentLayerQuietUntil = 0;
        officeDraftFlushSceneOrAgentLayerAfterInput(state, 'pan-settle');
    }, OFFICE_DRAFT_AGENT_PAN_QUIET_MS);
}
