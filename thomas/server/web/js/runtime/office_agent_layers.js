/** Agent-layer overlap resolution and population. */

function officeDraftLayerElementMap(layer) {
    if (!(layer instanceof HTMLElement)) return new Map();
    if (!(layer.__officeDraftAgentElements instanceof Map)) {
        layer.__officeDraftAgentElements = new Map();
        layer.querySelectorAll('[data-office-draft-agent-id]').forEach((node) => {
            const agentId = safeString(node?.dataset?.officeDraftAgentId);
            if (agentId && node instanceof HTMLElement) {
                layer.__officeDraftAgentElements.set(agentId, node);
            }
        });
    }
    return layer.__officeDraftAgentElements;
}

function officeDraftClampResolvedAgentItemToSpace(item) {
    if (!item?.node) return;
    const state = officeEnsureDraftMapState();
    const spaceId = safeString(item.node.dataset.officeDraftSpaceId);
    const space = (Array.isArray(state?.spaces) ? state.spaces : []).find((entry) => safeString(entry?.id) === spaceId);
    if (!space) return;
    const globalLayer = item.node.dataset.officeDraftAgentGlobal === '1';
    if (globalLayer && item.node.dataset.officeAgentRouteActive === '1') {
        const rect = officeDraftSpaceRect(space);
        const center = {
            x: Math.round((Number(item.x) || 0) + (OFFICE_DRAFT_AGENT_HITBOX_W / 2)),
            y: Math.round((Number(item.y) || 0) + (OFFICE_DRAFT_AGENT_HITBOX_H / 2)),
        };
        if (!officeDraftPointInsideRect(center, rect, 0)) return;
    }
    const baseX = globalLayer ? (Number(space.x) || 0) : 0;
    const baseY = globalLayer ? (Number(space.y) || 0) : 0;
    const minX = baseX + 32;
    const minY = baseY + 36;
    const maxX = baseX + Math.max(48, (Number(space.width) || 0) - OFFICE_DRAFT_AGENT_HITBOX_W - 28);
    const maxY = baseY + Math.max(64, (Number(space.height) || 0) - OFFICE_DRAFT_AGENT_HITBOX_H - 20);
    item.x = officeClamp(item.x, Math.min(minX, maxX), Math.max(minX, maxX));
    item.y = officeClamp(item.y, Math.min(minY, maxY), Math.max(minY, maxY));
}

function officeDraftSpreadDuplicateResolvedAgentItem(item, duplicateIndex = 1) {
    if (!item?.node) return;
    const state = officeEnsureDraftMapState();
    const spaceId = safeString(item.node.dataset.officeDraftSpaceId);
    const space = (Array.isArray(state?.spaces) ? state.spaces : []).find((entry) => safeString(entry?.id) === spaceId);
    if (!space) return;
    const globalLayer = item.node.dataset.officeDraftAgentGlobal === '1';
    const baseX = globalLayer ? (Number(space.x) || 0) : 0;
    const baseY = globalLayer ? (Number(space.y) || 0) : 0;
    const minX = baseX + 32;
    const minY = baseY + 36;
    const usableWidth = Math.max(OFFICE_DRAFT_AGENT_HITBOX_W, (Number(space.width) || 0) - OFFICE_DRAFT_AGENT_HITBOX_W - 60);
    const usableHeight = Math.max(OFFICE_DRAFT_AGENT_HITBOX_H, (Number(space.height) || 0) - OFFICE_DRAFT_AGENT_HITBOX_H - 56);
    const columns = Math.max(2, Math.min(5, Math.floor(usableWidth / 132)));
    const rows = Math.max(2, Math.min(5, Math.floor(usableHeight / 118)));
    const slot = Math.abs((Number(item.index) || 0) + (Number(duplicateIndex) || 1) * 7) % (columns * rows);
    item.x = minX + ((slot % columns) * 132);
    item.y = minY + (Math.floor(slot / columns) * 118);
    officeDraftClampResolvedAgentItemToSpace(item);
}

function officeDraftResolveAgentElementOverlaps(layer) {
    if (!(layer instanceof HTMLElement)) return;
    const items = Array.from(layer.querySelectorAll('[data-office-draft-agent-id]'))
        .map((node, index) => {
            if (!(node instanceof HTMLElement)) return null;
            const transform = safeString(node.style.transform);
            const match = transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px,\s*0(?:px)?\)(.*)$/);
            if (!match) return null;
            return {
                node,
                index,
                x: Number(match[1]) || 0,
                y: Number(match[2]) || 0,
                suffix: safeString(match[3]),
                adjusted: false,
            };
        })
        .filter(Boolean);
    if (items.length <= 1) return;
    const minX = 132;
    const minY = 118;
    for (let pass = 0; pass < 5; pass += 1) {
        for (let leftIndex = 0; leftIndex < items.length; leftIndex += 1) {
            for (let rightIndex = leftIndex + 1; rightIndex < items.length; rightIndex += 1) {
                const left = items[leftIndex];
                const right = items[rightIndex];
                const dx = right.x - left.x;
                const dy = right.y - left.y;
                if (Math.abs(dx) >= minX || Math.abs(dy) >= minY) continue;
                const pushX = dx === 0 ? (right.index % 2 === 0 ? 1 : -1) : Math.sign(dx);
                const pushY = dy === 0 ? (right.index % 3 === 0 ? 1 : -1) : Math.sign(dy);
                const adjustX = Math.min(70, ((minX - Math.abs(dx)) / 2) + 10);
                const adjustY = Math.min(62, ((minY - Math.abs(dy)) / 2) + 8);
                left.x -= pushX * adjustX;
                right.x += pushX * adjustX;
                left.y -= pushY * adjustY;
                right.y += pushY * adjustY;
                left.adjusted = true;
                right.adjusted = true;
                officeDraftClampResolvedAgentItemToSpace(left);
                officeDraftClampResolvedAgentItemToSpace(right);
            }
        }
    }
    const occupied = new Map();
    items.forEach((item) => {
        officeDraftClampResolvedAgentItemToSpace(item);
        let key = `${Math.round(item.x)}:${Math.round(item.y)}:${safeString(item.node.dataset.officeDraftSpaceId)}`;
        let duplicateIndex = Number(occupied.get(key)) || 0;
        while (duplicateIndex > 0 && duplicateIndex < 10) {
            officeDraftSpreadDuplicateResolvedAgentItem(item, duplicateIndex);
            item.adjusted = true;
            key = `${Math.round(item.x)}:${Math.round(item.y)}:${safeString(item.node.dataset.officeDraftSpaceId)}`;
            duplicateIndex = Number(occupied.get(key)) || 0;
        }
        occupied.set(key, (Number(occupied.get(key)) || 0) + 1);
        if (item.adjusted) {
            item.node.dataset.officeAgentOverlapResolved = '1';
            item.node.style.setProperty('transition', 'none', 'important');
        } else if (item.node.dataset.officeAgentOverlapResolved === '1') {
            delete item.node.dataset.officeAgentOverlapResolved;
            item.node.style.removeProperty('transition');
        }
        officeDraftSetStyleValue(item.node, 'transform', `translate3d(${Math.round(item.x)}px, ${Math.round(item.y)}px, 0)${item.suffix}`);
    });
}

function officePopulateDraftAgentLayer(layer, space, state, now = performance.now(), agentsOverride = null) {
    if (!(layer instanceof HTMLElement)) return;
    const agents = Array.isArray(agentsOverride) ? agentsOverride : officeDraftAgentsForSpace(space);
    const elementMap = officeDraftLayerElementMap(layer);
    const seen = new Set();
    agents.forEach((agent, index) => {
        const agentId = safeString(agent?.id);
        if (!agentId) return;
        seen.add(agentId);
        let el = elementMap.get(agentId);
        if (!(el instanceof HTMLElement) || !layer.contains(el)) {
            el = officeDraftCreateAgentElement(space, agent, index, agents.length, state, { skipInitialUpdate: true });
            elementMap.set(agentId, el);
            layer.appendChild(el);
        }
        el.dataset.officeDraftSpaceId = safeString(space.id);
        officeDraftUpdateAgentElement(el, space, agent, index, agents.length, state, now);
    });
    Array.from(elementMap.entries()).forEach(([agentId, node]) => {
        if (!seen.has(agentId)) {
            if (node instanceof HTMLElement) node.remove();
            elementMap.delete(agentId);
        }
    });
    officeDraftResolveAgentElementOverlaps(layer);
}

function officePopulateDraftGlobalAgentLayer(layer, state, now = performance.now(), assignmentsOverride = null, renderSource = 'direct') {
    if (!(layer instanceof HTMLElement) || !officeState) return;
    const currentNow = Number(now) || performance.now();
    if (state?.agentLayerForceRender !== true
        && state?.agentPointerId === null
        && state?.agentLayerQuietMotionRender !== true
        && officeDraftAgentRenderQuietActive(state, currentNow)) {
        return;
    }
    state.agentLayerRenderCount = (Number(state.agentLayerRenderCount) || 0) + 1;
    const sourceKey = safeString(renderSource) || 'direct';
    state.agentLayerRenderSources = state.agentLayerRenderSources && typeof state.agentLayerRenderSources === 'object'
        ? state.agentLayerRenderSources
        : {};
    state.agentLayerRenderSources[sourceKey] = (Number(state.agentLayerRenderSources[sourceKey]) || 0) + 1;
    const assignments = assignmentsOverride instanceof Map ? assignmentsOverride : officeDraftAgentAssignmentMap(state);
    const elementMap = officeDraftLayerElementMap(layer);
    const allAgents = Array.isArray(officeState.agents) ? officeState.agents.filter(Boolean) : [];
    const routePlanPendingAgents = sourceKey === 'route-plan'
        ? allAgents.filter((agent) => officeDraftAgentHasPendingRoutePlan(agent, currentNow))
        : [];
    const routePlanCursor = routePlanPendingAgents.length
        ? Math.max(0, Number(state.agentRoutePlanCursor) || 0) % routePlanPendingAgents.length
        : 0;
    const renderAgents = sourceKey === 'route-plan' && routePlanPendingAgents.length
        ? [routePlanPendingAgents[routePlanCursor]]
        : (sourceKey === 'route-plan' ? [] : allAgents);
    const routePlanHasMoreAgents = sourceKey === 'route-plan' && routePlanPendingAgents.length > 1;
    if (sourceKey === 'route-plan') {
        state.agentRoutePlanCursor = routePlanPendingAgents.length
            ? (routePlanCursor + 1) % routePlanPendingAgents.length
            : 0;
        state.lastRoutePlanRenderAt = currentNow;
    }
    const seen = new Set(allAgents.map((agent) => safeString(agent?.id)).filter(Boolean));
    const fallbackSpace = (Array.isArray(state?.spaces) ? state.spaces : []).find((space) => safeString(space?.id) === 'lobby')
        || (Array.isArray(state?.spaces) ? state.spaces[0] : null)
        || null;
    const groupIndexByAgentId = new Map();
    assignments.forEach((agents) => {
        (Array.isArray(agents) ? agents : []).forEach((agent, index) => {
            groupIndexByAgentId.set(safeString(agent?.id), index);
        });
    });
    const previousRouteBudget = state.agentRoutePlansRemaining;
    const previousSkipRoutePlanning = state.agentLayerSkipRoutePlanning;
    const skipRoutePlanning = previousSkipRoutePlanning === true;
    const routePlanningSource = new Set(['route-plan', 'agent-chat-command']).has(sourceKey);
    if (!routePlanningSource || state.agentLayerQuietMotionRender === true) {
        state.agentLayerSkipRoutePlanning = true;
    }
    state.agentRoutePlansRemaining = (skipRoutePlanning || state.agentLayerQuietMotionRender === true || !routePlanningSource)
        ? 0
        : OFFICE_DRAFT_AGENT_ROUTE_PLANS_PER_RENDER;
    state.agentRoutePlanDeferred = false;
    const previousRoutePlanningSource = state.agentRoutePlanningSource;
    state.agentRoutePlanningSource = sourceKey;
    const chunkStartedAt = performance.now();
    const allowChunking = safeString(renderSource) !== 'scene' && renderAgents.length > 4;
    const chunkBudget = state.agentLayerForceRender === true
        ? OFFICE_DRAFT_AGENT_LAYER_FORCE_CHUNK_BUDGET_MS
        : OFFICE_DRAFT_AGENT_LAYER_CHUNK_BUDGET_MS;
    const priorityAgentIds = new Set([
        safeString(state.agentDragAgentId),
        safeString(state.hoveredAgentId),
        safeString(state.expandedRosterAgentId),
        safeString(officeState.selectedAgentId),
    ].filter(Boolean));
    const priorityAgents = allowChunking
        ? renderAgents.filter((agent) => priorityAgentIds.has(safeString(agent?.id)))
        : [];
    const normalAgents = allowChunking
        ? renderAgents.filter((agent) => !priorityAgentIds.has(safeString(agent?.id)))
        : renderAgents;
    const startCursor = allowChunking
        ? Math.max(0, Number(state.agentLayerRenderCursor) || 0) % Math.max(1, normalAgents.length)
        : 0;
    const orderedAgents = allowChunking
        ? priorityAgents.concat(normalAgents.slice(startCursor), normalAgents.slice(0, startCursor))
        : renderAgents;
    let processed = 0;
    let completedAllAgents = true;
    try {
        for (let step = 0; step < orderedAgents.length; step += 1) {
            const agent = orderedAgents[step];
            const agentId = safeString(agent?.id);
            if (!agentId) continue;
            const space = officeDraftSpaceForAgent(agent) || fallbackSpace;
            if (!space) continue;
            const group = assignments.get(safeString(space.id)) || [agent];
            const index = groupIndexByAgentId.has(agentId) ? groupIndexByAgentId.get(agentId) : Math.max(0, group.findIndex((entry) => safeString(entry?.id) === agentId));
            let el = elementMap.get(agentId);
            if (!(el instanceof HTMLElement) || !layer.contains(el)) {
                el = officeDraftCreateAgentElement(space, agent, Math.max(0, index), group.length || 1, state, { skipInitialUpdate: true });
                el.dataset.officeDraftAgentGlobal = '1';
                elementMap.set(agentId, el);
                layer.appendChild(el);
            }
            el.dataset.officeDraftSpaceId = safeString(space.id);
            officeDraftUpdateAgentElement(el, space, agent, Math.max(0, index), group.length || 1, state, currentNow);
            processed += 1;
            if (allowChunking
                && processed > 0
                && performance.now() - chunkStartedAt > chunkBudget
                && step < orderedAgents.length - 1) {
                completedAllAgents = false;
                break;
            }
        }
    } finally {
        const routeDeferred = state.agentRoutePlanDeferred === true;
        state.agentRoutePlansRemaining = previousRouteBudget;
        state.agentRoutePlanDeferred = routeDeferred || routePlanHasMoreAgents;
        state.agentRoutePlanningSource = previousRoutePlanningSource || '';
        state.agentLayerSkipRoutePlanning = previousSkipRoutePlanning === true;
    }
    if (state.agentRoutePlanDeferred) {
        officeDraftScheduleDeferredRoutePlan(state, currentNow);
    }
    if (allowChunking && !completedAllAgents) {
        const normalProcessed = Math.max(0, processed - priorityAgents.length);
        state.agentLayerRenderCursor = (startCursor + normalProcessed) % Math.max(1, normalAgents.length);
        if (!state.agentLayerChunkTimer) {
            state.agentLayerChunkTimer = window.setTimeout(() => {
                state.agentLayerChunkTimer = 0;
                officeRenderDraftAgentLayerOnly(performance.now(), { force: false, source: 'agent-layer-chunk' });
            }, Math.max(24, OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS));
        }
    } else {
        state.agentLayerRenderCursor = 0;
    }
    Array.from(elementMap.entries()).forEach(([agentId, node]) => {
        if (!seen.has(agentId)) {
            if (node instanceof HTMLElement) node.remove();
            elementMap.delete(agentId);
        }
    });
    if (!allowChunking || completedAllAgents) {
        officeDraftResolveAgentElementOverlaps(layer);
    }
}


