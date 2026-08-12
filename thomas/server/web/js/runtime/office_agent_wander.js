/** Agent room assignment and bounded wandering. */

function officeDraftSpaceForRoomId(roomIdRaw) {
    const state = officeEnsureDraftMapState();
    const roomId = officeDraftNormalizeRoomId(roomIdRaw);
    return state.spaces.find((space) => officeDraftNormalizeRoomId(space?.roomId, space?.id) === roomId)
        || state.spaces.find((space) => safeString(space?.id) === 'lobby')
        || state.spaces[0]
        || null;
}

function officeDraftHomeRoomIdForAgent(agent) {
    const text = `${safeString(agent?.specialty)} ${safeString(agent?.personality)} ${safeString(agent?.name)}`.toLowerCase();
    if (/\b(code|software|debug|build|game|engineer|integration)\b/.test(text)) return 'room-engineering';
    if (/\b(research|docs|documentation|source)\b/.test(text)) return 'room-research';
    if (/\b(design|ui|visual|polish)\b/.test(text)) return 'room-design';
    if (/\b(content|video|social|copy)\b/.test(text)) return 'room-content';
    if (/\b(ops|deploy|reliability|monitor|automation)\b/.test(text)) return 'room-ops';
    if (/\b(support|ticket|customer|review)\b/.test(text)) return 'room-support';
    if (/\b(data|analysis|transform)\b/.test(text)) return 'room-research';
    if (/\b(plan|planning|strategy|roadmap)\b/.test(text)) return 'room-planning';
    return 'room-lobby';
}

function officeDraftAgentPinnedTargetActive(agent, now = performance.now()) {
    if (!agent || !safeString(agent.draftPinnedRoomId)) return false;
    const taskId = safeString(agent.taskId);
    if (safeString(agent.draftPinnedTaskId) !== taskId) return false;
    if (officeDraftAgentCommandActive(agent, now)) return true;
    if (taskId) return true;
    return (Number(agent.draftManualPinUntil) || 0) > (Number(now) || performance.now());
}

function officeDraftAgentEligibleForWander(agent, now = performance.now()) {
    if (!agent || safeString(agent.taskId)) return false;
    if (officeDraftAgentCommandActive(agent, now)) return false;
    if ((Number(agent.draftPausedUntil) || 0) > now) return false;
    if ((Number(agent.draftDropUntil) || 0) > now) return false;
    if ((Number(agent.draftManualPinUntil) || 0) > now) return false;
    if (agent?.draftMotion?.dragging) return false;
    const intent = safeString(agent.intent);
    const state = safeString(agent.state);
    if (intent === 'task' || state === 'working') return false;
    if (state === 'break' && (Number(agent.breakUntil) || 0) > now) return false;
    return true;
}

function officeDraftAgentWanderTargetActive(agent, now = performance.now()) {
    if (!officeDraftAgentEligibleForWander(agent, now)) return false;
    if (!safeString(agent?.draftWanderRoomId)) return false;
    const localX = Number(agent.draftWanderLocalX);
    const localY = Number(agent.draftWanderLocalY);
    return Number.isFinite(localX) && Number.isFinite(localY);
}

function officeDraftAgentWanderTargetWorld(space, agent, now = performance.now()) {
    if (!space || !officeDraftAgentWanderTargetActive(agent, now)) return null;
    if (safeString(agent.draftWanderSpaceId) !== safeString(space.id)
        && officeDraftNormalizeRoomId(agent.draftWanderRoomId) !== officeDraftNormalizeRoomId(space.roomId, space.id)) {
        return null;
    }
    const rect = officeDraftSpaceRect(space);
    const localX = Number(agent.draftWanderLocalX);
    const localY = Number(agent.draftWanderLocalY);
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(rect.left + localX, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(rect.top + localY, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftWanderCandidateAssets(space) {
    const preferredTypes = new Set([
        'vending_machine', 'coffee_bar', 'couch', 'bean_bag', 'round_table', 'arcade_cabinet',
        'bookshelf', 'whiteboard', 'workstation', 'standing_desk', 'desk', 'conference_table',
        'kanban_board', 'map_table', 'microscope', 'data_wall', 'server_rack', 'focus_pod',
        'bench', 'reception_counter', 'ticket_kiosk', 'tablet_stand',
    ]);
    return (Array.isArray(space?.assets) ? space.assets : []).filter((asset) => {
        const type = safeString(asset?.type);
        const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[type]?.interaction);
        return preferredTypes.has(type) || Boolean(interaction);
    });
}

function officeDraftChooseWanderSpace(agent, now = performance.now()) {
    const state = officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces.filter(Boolean) : [];
    if (!spaces.length) return null;
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    const currentSpace = motion && Number.isFinite(Number(motion.x)) && Number.isFinite(Number(motion.y))
        ? officeDraftSpaceAtWorldPoint(Number(motion.x), Number(motion.y))
        : null;
    const homeRoomId = officeDraftHomeRoomIdForAgent(agent);
    const lastRoomId = officeDraftNormalizeRoomId(agent?.draftWanderLastRoomId);
    const sequence = Number(agent?.draftWanderSequence) || 0;
    const seed = officeStableHash(`${safeString(agent?.id)}|wander-space|${sequence}|${Math.floor((Number(now) || performance.now()) / 7000)}`);
    const commonRooms = new Set(['room-lobby', 'room-coffee', 'room-break', 'room-pods', 'room-planning']);
    let best = null;
    spaces.forEach((space, index) => {
        const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
        const assetCount = officeDraftWanderCandidateAssets(space).length;
        const center = officeDraftSpaceCenter(space);
        const from = currentSpace ? officeDraftSpaceCenter(currentSpace) : center;
        const distance = Math.hypot(center.x - from.x, center.y - from.y);
        let score = ((seed + (index * 193)) % 1000) + (distance * 0.05);
        if (roomId === homeRoomId) score -= 170;
        if (commonRooms.has(roomId)) score -= 125;
        if (assetCount) score -= Math.min(160, 34 + (assetCount * 14));
        if (currentSpace && safeString(currentSpace.id) === safeString(space.id)) score += 130;
        if (lastRoomId && roomId === lastRoomId && spaces.length > 2) score += 220;
        if (!best || score < best.score) best = { space, score };
    });
    return best?.space || spaces[0] || null;
}

function officeDraftChooseWanderFreePoint(space, agent, seed = 0) {
    if (!space) return null;
    const obstacles = officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const center = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const network = officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const door = officeDraftClampWorldPointToWalkable(officeDraftSpaceDoorInteriorPoint(space, network), space, obstacles);
    const candidates = [center, door];
    for (let index = 0; index < 12; index += 1) {
        const hash = officeStableHash(`${safeString(agent?.id)}|wander-point|${safeString(space?.id)}|${seed}|${index}`);
        const xRatio = 0.18 + (((hash % 997) / 997) * 0.64);
        const yRatio = 0.2 + ((((Math.floor(hash / 997)) % 991) / 991) * 0.6);
        candidates.push({
            x: Math.round(bounds.left + ((bounds.right - bounds.left) * xRatio)),
            y: Math.round(bounds.top + ((bounds.bottom - bounds.top) * yRatio)),
        });
    }
    let best = null;
    candidates.forEach((candidateRaw, index) => {
        const candidate = officeDraftClampWorldPointToWalkable(candidateRaw, space, obstacles);
        if (!officeDraftPointWalkableInSpace(candidate, space, obstacles)) return;
        const clearance = officeDraftPointObstacleClearance(candidate, obstacles);
        const centerDistance = Math.hypot(candidate.x - center.x, candidate.y - center.y);
        const doorDistance = Math.hypot(candidate.x - door.x, candidate.y - door.y);
        const score = (index * 18) + (centerDistance * 0.12) + (doorDistance * 0.04) - (Math.min(260, clearance) * 1.6);
        if (!best || score < best.score) best = { point: candidate, score };
    });
    return best?.point || center;
}

function officeDraftSetAgentWanderTarget(agent, space, targetWorld, options = {}, now = performance.now()) {
    if (!agent || !space || !targetWorld) return null;
    const roomId = officeDraftNormalizeRoomId(space.roomId, space.id);
    const sequence = (Number(agent.draftWanderSequence) || 0) + 1;
    agent.draftWanderSequence = sequence;
    agent.draftWanderRoomId = roomId;
    agent.draftWanderSpaceId = safeString(space.id);
    agent.draftWanderLocalX = Math.round(Number(targetWorld.x) - (Number(space.x) || 0));
    agent.draftWanderLocalY = Math.round(Number(targetWorld.y) - (Number(space.y) || 0));
    agent.draftWanderAssetId = safeString(options.assetId);
    agent.draftWanderAssetType = safeString(options.assetType);
    agent.draftWanderAction = safeString(options.action || 'wander') || 'wander';
    agent.draftWanderLastRoomId = roomId;
    agent.draftWanderArrivedAt = 0;
    agent.draftWanderNextAt = 0;
    agent.draftWanderDwellMs = OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS
        + (officeStableHash(`${safeString(agent.id)}|wander-dwell|${sequence}`) % Math.max(1, OFFICE_DRAFT_AGENT_WANDER_DWELL_MAX_MS - OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS));
    agent.intent = 'wander';
    if (!new Set(['idle', 'break']).has(safeString(agent.state))) agent.state = 'idle';
    delete agent.draftTargetPointCache;
    delete agent.draftFallbackTargetCache;
    const motion = agent.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (motion && Number(motion.navVersion) === OFFICE_DRAFT_AGENT_NAV_VERSION) {
        motion.targetX = Math.round(Number(targetWorld.x) || 0);
        motion.targetY = Math.round(Number(targetWorld.y) || 0);
        motion.targetSignature = '';
        motion.needsReplan = true;
        motion.routeRetryAfter = 0;
        motion.lastProgressAt = Number(now) || performance.now();
    }
    const stats = officeDraftAgentNavStats(agent);
    if (stats) stats.wanderTargets = (Number(stats.wanderTargets) || 0) + 1;
    return { space, targetWorld, action: agent.draftWanderAction };
}

function officeDraftEnsureAgentWanderTarget(agent, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!officeDraftAgentEligibleForWander(agent, currentNow)) return null;
    const activeSpace = officeDraftAgentWanderTargetActive(agent, currentNow)
        ? officeDraftSpaceForRoomId(agent.draftWanderRoomId)
        : null;
    const activeTarget = activeSpace ? officeDraftAgentWanderTargetWorld(activeSpace, agent, currentNow) : null;
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (activeSpace && activeTarget) {
        const routeActive = Array.isArray(motion?.route) && motion.route.length > 0 && Number(motion.routeIndex) < motion.route.length;
        const distance = motion && Number.isFinite(Number(motion.x)) && Number.isFinite(Number(motion.y))
            ? Math.hypot((Number(motion.x) || 0) - activeTarget.x, (Number(motion.y) || 0) - activeTarget.y)
            : 9999;
        if (routeActive || distance > Math.max(OFFICE_DRAFT_AGENT_ROUTE_EPSILON * 2.5, 26)) {
            return { space: activeSpace, targetWorld: activeTarget, action: safeString(agent.draftWanderAction || 'wander') };
        }
        if (!Number(agent.draftWanderArrivedAt)) {
            agent.draftWanderArrivedAt = currentNow;
            agent.draftWanderNextAt = currentNow + Math.max(OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS, Number(agent.draftWanderDwellMs) || 0);
        }
        if ((Number(agent.draftWanderNextAt) || 0) > currentNow) {
            return { space: activeSpace, targetWorld: activeTarget, action: safeString(agent.draftWanderAction || 'wander') };
        }
    }
    const space = officeDraftChooseWanderSpace(agent, currentNow);
    if (!space) return null;
    const seed = officeStableHash(`${safeString(agent.id)}|wander|${Number(agent.draftWanderSequence) || 0}|${Math.floor(currentNow / 1000)}`);
    const assets = officeDraftWanderCandidateAssets(space);
    const targetAsset = assets.length ? assets[seed % assets.length] : null;
    const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(targetAsset?.type)]?.interaction);
    const targetWorld = targetAsset
        ? officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed, { routeAware: false })
        : officeDraftChooseWanderFreePoint(space, agent, seed);
    const action = officeDraftInferCommandActionFromInteraction(interaction)
        || (targetAsset ? 'inspect' : 'wander');
    return officeDraftSetAgentWanderTarget(agent, space, targetWorld, {
        assetId: safeString(targetAsset?.id),
        assetType: safeString(targetAsset?.type),
        action,
    }, currentNow);
}


