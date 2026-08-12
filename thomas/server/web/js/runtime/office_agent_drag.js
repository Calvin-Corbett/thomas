/** Agent click, drag, and drop interactions. */

function officeDraftHandleAgentClick(event, agentId) {
    const state = officeEnsureDraftMapState();
    if ((Number(state.suppressAgentClickUntil) || 0) > performance.now()) return;
    if (!officeState) return;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    officeState.selectedAgentId = agent.id;
    state.expandedRosterAgentId = agent.id;
    officeDraftPauseAgentForUser(agent, space, performance.now());
    officeDraftOpenAgentChat(agent.id, { prime: false });
    officeSyncCustomizerFields();
    officePersistAgentPrefs();
    if (typeof officePersistRuntimeState === 'function') {
        officePersistRuntimeState(performance.now(), { force: true });
    }
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-click' });
}

function officeDraftAgentMotionForDrag(agent, space, now = performance.now()) {
    const targetAsset = officeDraftPrimaryInteractionAsset(space, agent);
    return officeDraftEnsureAgentMotion(agent, space, 0, 1, targetAsset, now);
}

function officeDraftRenderSingleAgentElement(agent, stateRaw = null, now = performance.now(), renderSource = 'single-agent') {
    if (!agent || !officeState) return;
    const state = stateRaw || officeEnsureDraftMapState();
    const layer = officeScene?.querySelector('[data-office-draft-agent-layer="global"]');
    if (!(layer instanceof HTMLElement)) return;
    const assignments = officeDraftAgentAssignmentMap(state);
    const fallbackSpace = (Array.isArray(state?.spaces) ? state.spaces : []).find((space) => safeString(space?.id) === 'lobby')
        || (Array.isArray(state?.spaces) ? state.spaces[0] : null)
        || null;
    const space = officeDraftSpaceForAgent(agent) || fallbackSpace;
    if (!space) return;
    const group = assignments.get(safeString(space.id)) || [agent];
    const index = Math.max(0, group.findIndex((entry) => safeString(entry?.id) === safeString(agent?.id)));
    const elementMap = officeDraftLayerElementMap(layer);
    let el = elementMap.get(safeString(agent.id));
    if (!(el instanceof HTMLElement) || !layer.contains(el)) {
        el = officeDraftCreateAgentElement(space, agent, index, group.length || 1, state, { skipInitialUpdate: true });
        el.dataset.officeDraftAgentGlobal = '1';
        elementMap.set(safeString(agent.id), el);
        layer.appendChild(el);
    }
    el.dataset.officeDraftSpaceId = safeString(space.id);
    officeDraftUpdateAgentElement(el, space, agent, index, group.length || 1, state, now);
    state.agentLayerRenderSources = state.agentLayerRenderSources && typeof state.agentLayerRenderSources === 'object'
        ? state.agentLayerRenderSources
        : {};
    const source = safeString(renderSource) || 'single-agent';
    state.agentLayerRenderSources[source] = (Number(state.agentLayerRenderSources[source]) || 0) + 1;
}

function officeDraftHandleAgentPointerDown(event, agentId) {
    if (!(officeSceneWrap instanceof HTMLElement) || !officeState) return;
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (state.agentPointerId !== null) return true;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    const motion = officeDraftAgentMotionForDrag(agent, space, performance.now());
    const world = officeDraftMapClientToWorld(event.clientX, event.clientY);
    if (!world) return;
    event.preventDefault();
    event.stopPropagation();
    state.agentPointerId = event.pointerId;
    state.agentDragAgentId = agent.id;
    state.agentDragStartClientX = event.clientX;
    state.agentDragStartClientY = event.clientY;
    state.agentDragOffsetX = world.x - (Number(motion.x) || world.x);
    state.agentDragOffsetY = world.y - (Number(motion.y) || world.y);
    state.agentDragActive = false;
    state.lastInputMode = 'agent';
    state.agentLayerQuietUntil = 0;
    officeState.selectedAgentId = agent.id;
    state.expandedRosterAgentId = agent.id;
    if (officeSceneWrap instanceof HTMLElement && typeof officeSceneWrap.setPointerCapture === 'function') {
        officeSceneWrap.setPointerCapture(event.pointerId);
    } else if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    return true;
}

function officeDraftClampAgentDropPointToSpace(worldPoint, space) {
    const rect = officeDraftSpaceRect(space);
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(Number(worldPoint?.x) || rect.centerX, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(Number(worldPoint?.y) || rect.centerY, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftClampAgentDragPoint(worldPoint, fallbackSpace = null) {
    const bounded = {
        x: Math.round(officeClamp(Number(worldPoint?.x) || 0, 80, OFFICE_DRAFT_MAP_SIZE - 140)),
        y: Math.round(officeClamp(Number(worldPoint?.y) || 0, 92, OFFICE_DRAFT_MAP_SIZE - 170)),
    };
    const space = officeDraftSpaceAtWorldPoint(bounded.x, bounded.y) || fallbackSpace;
    if (space) return officeDraftClampAgentDropPointToSpace(bounded, space);
    const snapped = officeDraftNearestHallwayPoint(bounded, officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces));
    return { x: Math.round(snapped.x), y: Math.round(snapped.y) };
}

function officeDraftHandleAgentPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.agentPointerId !== event.pointerId || !safeString(state.agentDragAgentId)) return false;
    const agent = officeGetAgentById(state.agentDragAgentId);
    if (!agent) return true;
    const world = officeDraftMapClientToWorld(event.clientX, event.clientY);
    if (!world) return true;
    const moved = Math.hypot(event.clientX - state.agentDragStartClientX, event.clientY - state.agentDragStartClientY);
    if (moved > 7) {
        state.agentDragActive = true;
    }
    if (!state.agentDragActive) return true;
    event.preventDefault();
    event.stopPropagation();
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    const motion = officeDraftAgentMotionForDrag(agent, space, performance.now());
    const dragPoint = officeDraftClampAgentDragPoint({
        x: world.x - (Number(state.agentDragOffsetX) || 0),
        y: world.y - (Number(state.agentDragOffsetY) || 0),
    }, space);
    motion.dragging = true;
    motion.route = [];
    motion.routeIndex = 0;
    motion.targetSignature = '';
    motion.targetX = dragPoint.x;
    motion.targetY = dragPoint.y;
    motion.x = dragPoint.x;
    motion.y = dragPoint.y;
    motion.needsReplan = false;
    agent.draftPausedUntil = 0;
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grabbing';
    }
    officeDraftRenderSingleAgentElement(agent, state, performance.now(), 'agent-drag');
    return true;
}

function officeDraftHandleAgentPointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (state.agentPointerId !== event.pointerId || !safeString(state.agentDragAgentId)) return false;
    const agent = officeGetAgentById(state.agentDragAgentId);
    const wasDragging = Boolean(state.agentDragActive);
    if (officeSceneWrap instanceof HTMLElement && typeof officeSceneWrap.hasPointerCapture === 'function' && officeSceneWrap.hasPointerCapture(event.pointerId)) {
        officeSceneWrap.releasePointerCapture(event.pointerId);
    } else if (event.currentTarget instanceof HTMLElement && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (agent) {
        const now = performance.now();
        const currentSpace = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
        const motion = officeDraftAgentMotionForDrag(agent, currentSpace, now);
        motion.dragging = false;
        if (wasDragging) {
            const world = officeDraftMapClientToWorld(event.clientX, event.clientY) || { x: motion.x, y: motion.y };
            const dropSpace = officeDraftSpaceAtWorldPoint(world.x, world.y);
            if (dropSpace) {
                const dropPoint = officeDraftClampAgentDropPointToSpace(world, dropSpace);
                const roomId = officeDraftNormalizeRoomId(dropSpace.roomId, dropSpace.id);
                agent.remoteRoomId = roomId;
                agent.draftPinnedRoomId = roomId;
                agent.draftPinnedTaskId = safeString(agent.taskId);
                agent.draftPinnedLocalX = Math.round(dropPoint.x - (Number(dropSpace.x) || 0));
                agent.draftPinnedLocalY = Math.round(dropPoint.y - (Number(dropSpace.y) || 0));
                agent.draftManualPinUntil = now + OFFICE_DRAFT_AGENT_MANUAL_PIN_MS;
                agent.draftWanderRoomId = '';
                agent.draftWanderSpaceId = '';
                agent.draftWanderNextAt = 0;
                agent.draftWanderArrivedAt = 0;
                agent.draftDropUntil = now + 1250;
                agent.draftPausedUntil = now + 900;
                motion.x = dropPoint.x;
                motion.y = dropPoint.y;
                motion.route = [];
                motion.routeIndex = 0;
                motion.targetSignature = officeDraftAgentTargetSignature(dropSpace, agent, dropPoint, null);
                motion.targetX = dropPoint.x;
                motion.targetY = dropPoint.y;
                motion.needsReplan = false;
                agent.draftLastSpaceId = safeString(dropSpace.id);
                if (typeof officeSpeak === 'function') {
                    officeSpeak(agent, `Placed in ${safeString(dropSpace.name) || 'this room'}.`, { priority: true, durationMs: 1800 });
                }
                if (typeof officeBusEmit === 'function') {
                    officeBusEmit('agent.draft_drop', {
                        agentId: safeString(agent.id),
                        roomId,
                        spaceId: safeString(dropSpace.id),
                    }, now);
                }
            } else {
                const snapped = officeDraftNearestHallwayPoint(world, officeDraftAutoHallwayNetwork(state.spaces));
                motion.x = snapped.x;
                motion.y = snapped.y;
                motion.route = [];
                motion.routeIndex = 0;
                motion.targetSignature = `hall:${snapped.x},${snapped.y}`;
                motion.targetX = snapped.x;
                motion.targetY = snapped.y;
                motion.needsReplan = false;
                agent.draftManualPinUntil = now + OFFICE_DRAFT_AGENT_MANUAL_PIN_MS;
                agent.draftWanderRoomId = '';
                agent.draftWanderSpaceId = '';
                agent.draftWanderNextAt = 0;
                agent.draftWanderArrivedAt = 0;
                agent.draftPausedUntil = now + 900;
            }
            state.suppressAgentClickUntil = now + 360;
            if (typeof officePersistRuntimeState === 'function') {
                officePersistRuntimeState(now, { force: true });
            }
        }
    }
    state.agentPointerId = null;
    state.agentDragAgentId = '';
    state.agentDragActive = false;
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grab';
    }
    if (wasDragging) {
        event.preventDefault();
        event.stopPropagation();
        officeDraftRenderSingleAgentElement(agent, state, performance.now(), 'agent-drop');
        officeRenderDraftMapMinimapThrottled(true);
        window.setTimeout(() => {
            officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-drop-settle' });
        }, Math.max(120, OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS * 2));
    } else if (agent) {
        event.preventDefault();
        event.stopPropagation();
        officeDraftHandleAgentClick(event, safeString(agent.id));
        state.suppressAgentClickUntil = performance.now() + 320;
    }
    return true;
}


