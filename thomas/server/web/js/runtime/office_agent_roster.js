/** Occupied-room focus and roster editing. */

function officeDraftMaybeFocusOccupiedRoom(state, assignments) {
    if (!state || state.userSelectedSpace === true) return false;
    if (state.agentFocusInitialized === true) return false;
    if (state.pointerId !== null || state.assetPointerId !== null || state.catalogPointerId !== null) return false;
    const assignmentMap = assignments instanceof Map ? assignments : officeDraftAgentAssignmentMap(state);
    const totalAgents = Array.from(assignmentMap.values()).reduce((count, agents) => count + (Array.isArray(agents) ? agents.length : 0), 0);
    if (!totalAgents) return false;
    const selectedAgents = assignmentMap.get(safeString(state.selectedSpaceId)) || [];
    if (selectedAgents.length) {
        state.agentFocusInitialized = true;
        return false;
    }
    const focusSpace = typeof officeDraftInitialFocusSpace === 'function'
        ? officeDraftInitialFocusSpace(state)
        : null;
    if (!focusSpace || safeString(focusSpace.id) === safeString(state.selectedSpaceId)) {
        state.agentFocusInitialized = true;
        return false;
    }
    state.agentFocusInitialized = true;
    state.selectedSpaceId = safeString(focusSpace.id);
    officeCenterDraftMapViewport();
    officeRenderDraftMapScene();
    return true;
}

function officeDraftAgentRenderQuietActive(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if (state.pointerId !== null || state.assetPointerId !== null || state.catalogPointerId !== null || state.agentDragActive) return true;
    if ((Number(state.agentLayerQuietUntil) || 0) > currentNow) return true;
    if ((currentNow - (Number(state.lastPanAt) || 0)) < OFFICE_DRAFT_AGENT_PAN_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastWheelAt) || 0)) < OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastPointerIntentAt) || 0)) < OFFICE_DRAFT_AGENT_POINTER_QUIET_MS) return true;
    return false;
}

function officeDraftSceneRenderQuietActive(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if (state.pointerId !== null && state.lastInputMode === 'pan') return true;
    if ((currentNow - (Number(state.lastPanAt) || 0)) < OFFICE_DRAFT_AGENT_PAN_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastWheelAt) || 0)) < OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastPointerIntentAt) || 0)) < OFFICE_DRAFT_AGENT_POINTER_QUIET_MS) return true;
    return false;
}

function officeDraftInputMotionRenderAllowed(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if (state.assetPointerId !== null || state.catalogPointerId !== null || state.agentDragActive) return false;
    const hasActivePan = state.pointerId !== null && state.lastInputMode === 'pan';
    const recentlyPanned = (currentNow - (Number(state.lastPanAt) || 0)) < OFFICE_DRAFT_AGENT_PAN_QUIET_MS;
    const recentlyWheeled = (currentNow - (Number(state.lastWheelAt) || 0)) < OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS;
    if (!hasActivePan && !recentlyPanned && !recentlyWheeled) return false;
    return (currentNow - (Number(state.lastQuietAgentRenderAt) || 0)) >= OFFICE_DRAFT_AGENT_INPUT_RENDER_INTERVAL_MS;
}

function officeDraftCancelAgentHoverRender(stateRaw = null) {
    const state = stateRaw || officeEnsureDraftMapState();
    window.clearTimeout(state.agentHoverRenderTimer);
    state.agentHoverRenderTimer = 0;
    state.hoveredAgentId = '';
    if (state.agentRoutePlanTimer) {
        window.clearTimeout(state.agentRoutePlanTimer);
        state.agentRoutePlanTimer = 0;
    }
}

function officeDraftScheduleSceneRenderAfterInput(state, now = performance.now()) {
    if (!state) return;
    const currentNow = Number(now) || performance.now();
    const panDelay = Math.max(0, OFFICE_DRAFT_AGENT_PAN_QUIET_MS - (currentNow - (Number(state.lastPanAt) || 0)));
    const wheelDelay = Math.max(0, OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS - (currentNow - (Number(state.lastWheelAt) || 0)));
    const pointerDelay = Math.max(0, OFFICE_DRAFT_AGENT_POINTER_QUIET_MS - (currentNow - (Number(state.lastPointerIntentAt) || 0)));
    const delay = Math.max(90, panDelay, wheelDelay, pointerDelay) + 80;
    state.sceneRenderDeferred = true;
    window.clearTimeout(state.sceneRenderTimer);
    state.sceneRenderTimer = window.setTimeout(() => {
        const timerNow = performance.now();
        if (officeDraftSceneRenderQuietActive(state, timerNow)) {
            officeDraftScheduleSceneRenderAfterInput(state, timerNow);
            return;
        }
        state.sceneRenderDeferred = false;
        officeRenderDraftMapScene({ force: true });
    }, delay);
}

function officeDraftFlushSceneOrAgentLayerAfterInput(state, source) {
    const currentState = state || officeEnsureDraftMapState();
    if (currentState.sceneRenderDeferred) {
        window.clearTimeout(currentState.sceneRenderTimer);
        currentState.sceneRenderDeferred = false;
        officeRenderDraftMapScene({ force: true });
        return;
    }
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source });
}

function officeRenderDraftAgentLayerOnly(now = performance.now(), options = {}) {
    if (!officeState || !officeDraftMapPlane()) return;
    const state = officeEnsureDraftMapState();
    const force = options?.force === true;
    const missionDirty = state.missionAgentLayerDirty === true;
    const source = safeString(options?.source) || (missionDirty ? 'mission-stream-deferred' : (force ? 'force' : 'tick'));
    const quietActive = !force && officeDraftAgentRenderQuietActive(state, now);
    const quietMotionRender = quietActive && officeDraftInputMotionRenderAllowed(state, now);
    if (source === 'route-plan' && officeDraftRoutePlanQuietActive(state, now)) {
        officeDraftScheduleDeferredRoutePlan(state, now);
        return;
    }
    if (quietActive && !quietMotionRender) return;
    if (quietMotionRender) {
        state.lastQuietAgentRenderAt = Number(now) || performance.now();
    }
    const lastAt = Number(officeState.lastDraftAgentRenderAt) || 0;
    const previousRenderCost = Math.max(0, Number(officeState.lastDraftAgentRenderDurationMs) || 0);
    const dynamicRenderInterval = previousRenderCost > OFFICE_DRAFT_AGENT_RENDER_OVERLOAD_MS
        ? Math.min(
            OFFICE_DRAFT_AGENT_RENDER_BACKOFF_MAX_MS,
            Math.max(OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS, Math.round(previousRenderCost * 1.7)),
        )
        : OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS;
    if (!force && (Number(now) || performance.now()) - lastAt < dynamicRenderInterval) return;
    officeState.lastDraftAgentRenderAt = Number(now) || performance.now();
    const assignments = officeDraftAgentAssignmentMap(state);
    if (officeDraftMaybeFocusOccupiedRoom(state, assignments)) return;
    const layer = officeScene?.querySelector('[data-office-draft-agent-layer="global"]');
    state.agentLayerForceRender = force;
    state.agentLayerQuietMotionRender = quietMotionRender;
    const renderStartedAt = performance.now();
    try {
        officePopulateDraftGlobalAgentLayer(layer, state, now, assignments, quietMotionRender ? 'quiet-motion' : source);
    } finally {
        officeState.lastDraftAgentRenderDurationMs = Math.max(0, performance.now() - renderStartedAt);
        state.agentLayerForceRender = false;
        state.agentLayerQuietMotionRender = false;
        state.missionAgentLayerDirty = false;
    }
    if (state.rosterOpen && ((Number(now) || performance.now()) - (Number(officeState.lastDraftRosterRenderAt) || 0)) > 1600) {
        officeState.lastDraftRosterRenderAt = Number(now) || performance.now();
        officeRenderDraftAgentRosterPanel();
    }
}

function officeToggleDraftAgentRoster(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.rosterOpen = !state.rosterOpen;
    officeRenderDraftMapScene();
}

function officeDraftUpdateRosterField(agentId, field, valueRaw) {
    if (!officeState) return;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    const value = safeString(valueRaw);
    if (field === 'name') {
        agent.name = value.slice(0, 24) || agent.name;
    } else if (field === 'specialty') {
        agent.specialty = value.slice(0, 64) || 'Generalist';
    } else if (field === 'personality') {
        agent.personality = value.slice(0, 160) || 'Helpful, direct, and persistent.';
    } else if (field === 'chatProfile') {
        agent.chatProfile = value.slice(0, 80);
        agent.chatModelId = officeDraftDefaultChatModelId(value) || safeString(agent.chatModelId).slice(0, 120);
    } else if (field === 'chatModelId') {
        agent.chatModelId = value.slice(0, 120);
    } else if (field === 'color' && /^#[0-9a-f]{6}$/i.test(value)) {
        agent.color = value;
        agent.tint = officeAgentTintFromColor(value);
    } else if (field === 'costume' && new Set(OFFICE_AGENT_COSTUME_POOL).has(value)) {
        agent.costume = value;
    }
    officeState.selectedAgentId = agent.id;
    officePersistAgentPrefs();
    officeRenderAgentSelector(agent.id);
    officeRenderDraftMapScene();
}

function officeBindDraftRosterPanel(panel) {
    if (!(panel instanceof HTMLElement)) return;
    const backBtn = panel.querySelector('[data-office-roster-back="1"]');
    if (backBtn instanceof HTMLElement) {
        backBtn.addEventListener('click', (event) => {
            event.preventDefault();
            const state = officeEnsureDraftMapState();
            state.expandedRosterAgentId = '';
            officeRenderDraftMapScene();
        });
    }
    panel.querySelectorAll('[data-office-roster-expand]').forEach((node) => {
        node.addEventListener('click', (event) => {
            event.preventDefault();
            const agentId = safeString(node.dataset.officeRosterExpand);
            const state = officeEnsureDraftMapState();
            state.expandedRosterAgentId = agentId;
            if (officeState) officeState.selectedAgentId = agentId;
            officeRenderDraftMapScene();
        });
    });
    panel.querySelectorAll('[data-office-roster-field]').forEach((node) => {
        node.addEventListener('change', () => {
            officeDraftUpdateRosterField(
                safeString(node.dataset.officeRosterAgentId),
                safeString(node.dataset.officeRosterField),
                node.value,
            );
        });
    });
}


