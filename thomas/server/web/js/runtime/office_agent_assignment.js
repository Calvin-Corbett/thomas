/** Agent assignment and interaction targeting. */

function officeDraftRoomIdForAgent(agent) {
    if (!agent) return 'room-lobby';
    const now = performance.now();
    if (officeDraftAgentPinnedTargetActive(agent, now)) {
        return officeDraftNormalizeRoomId(agent.draftPinnedRoomId);
    }
    const taskId = safeString(agent.taskId);
    const task = officeState?.tasks?.find((entry) => (
        safeString(entry?.id) === taskId
        && safeString(entry?.assignedAgentId) === safeString(agent?.id)
        && safeString(entry?.status) !== 'done'
    ));
    if (task?.roomId) return officeDraftNormalizeRoomId(task.roomId);
    const homeRoomId = officeDraftHomeRoomIdForAgent(agent);
    const wanderTarget = !taskId ? officeDraftEnsureAgentWanderTarget(agent, now) : null;
    if (wanderTarget?.space) return officeDraftNormalizeRoomId(wanderTarget.space.roomId, wanderTarget.space.id);
    const remoteRoomId = officeDraftNormalizeRoomId(agent.remoteRoomId);
    if (!taskId) return homeRoomId;
    if (!task && remoteRoomId === 'room-support' && homeRoomId !== 'room-support') return homeRoomId;
    if (agent.remoteRoomId && safeString(agent.intent) === 'task') return officeDraftNormalizeRoomId(agent.remoteRoomId);
    const currentRoom = officeCurrentRoomForAgent(agent);
    if (!task && officeDraftNormalizeRoomId(currentRoom?.id) === 'room-support' && homeRoomId !== 'room-support') return homeRoomId;
    if (currentRoom?.id) return officeDraftNormalizeRoomId(currentRoom.id);
    if (agent.remoteRoomId) return officeDraftNormalizeRoomId(agent.remoteRoomId);
    return 'room-lobby';
}

function officeDraftSpaceForAgent(agent) {
    return officeDraftSpaceForRoomId(officeDraftRoomIdForAgent(agent));
}

function officeDraftAgentsForSpace(space) {
    if (!officeState || !Array.isArray(officeState.agents)) return [];
    const spaceId = safeString(space?.id);
    return officeState.agents.filter((agent) => safeString(officeDraftSpaceForAgent(agent)?.id) === spaceId);
}

function officeDraftAgentAssignmentMap(state = officeEnsureDraftMapState()) {
    const assignments = new Map();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    spaces.forEach((space) => {
        const spaceId = safeString(space?.id);
        if (spaceId) assignments.set(spaceId, []);
    });
    const fallbackSpace = spaces.find((space) => safeString(space?.id) === 'lobby') || spaces[0] || null;
    (officeState?.agents || []).forEach((agent) => {
        const targetSpace = officeDraftSpaceForAgent(agent) || fallbackSpace;
        const spaceId = safeString(targetSpace?.id);
        if (!spaceId) return;
        if (!assignments.has(spaceId)) assignments.set(spaceId, []);
        assignments.get(spaceId).push(agent);
    });
    return assignments;
}

function officeDraftAgentCommandActive(agent, now = performance.now()) {
    return Boolean(agent && (Number(agent.draftCommandUntil) || 0) > (Number(now) || performance.now()));
}

function officeDraftAgentCommandAsset(space, agent, now = performance.now()) {
    if (!officeDraftAgentCommandActive(agent, now)) return null;
    const commandAssetId = safeString(agent?.draftCommandAssetId);
    if (!commandAssetId || !Array.isArray(space?.assets)) return null;
    return space.assets.find((asset) => safeString(asset?.id) === commandAssetId) || null;
}

function officeDraftPrimaryInteractionAsset(space, agent, index = 0, total = 1) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const assets = Array.isArray(space?.assets) ? space.assets : [];
    const state = safeString(agent?.state);
    const intent = safeString(agent?.intent);
    const directedActivity = state === 'working' || state === 'break' || intent === 'task' || intent === 'break';
    const choose = (candidates) => {
        const usable = (Array.isArray(candidates) ? candidates : []).filter(Boolean);
        if (!usable.length) return null;
        const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|asset`);
        const spreadOffset = Math.max(0, Number(index) || 0) * (Math.max(1, Math.floor(usable.length / Math.max(1, Number(total) || 1))) || 3);
        return usable[(seed + spreadOffset) % usable.length];
    };
    const commandAsset = officeDraftAgentCommandAsset(space, agent);
    if (commandAsset) return commandAsset;
    if (!directedActivity && !new Set(['room-coffee', 'room-break', 'room-pods']).has(roomId)) return null;
    if ((roomId === 'room-coffee' || roomId === 'room-break' || state === 'break') && assets.some((asset) => safeString(asset?.type) === 'vending_machine')) {
        return choose(assets.filter((asset) => safeString(asset?.type) === 'vending_machine' || safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(asset?.type)]?.interaction) === 'drink'));
    }
    if (roomId === 'room-break' && assets.some((asset) => safeString(asset?.type) === 'couch')) {
        return choose(assets.filter((asset) => new Set(['couch', 'bean_bag', 'round_table', 'arcade_cabinet']).has(safeString(asset?.type))));
    }
    if (roomId === 'room-pods' && assets.some((asset) => safeString(asset?.type) === 'focus_pod')) {
        return choose(assets.filter((asset) => safeString(asset?.type) === 'focus_pod'));
    }
    const primaryTypesByRoom = {
        'room-engineering': ['workstation', 'desk', 'standing_desk', 'lab_bench', 'code_terminal', 'dual_monitor'],
        'room-planning': ['whiteboard', 'conference_table', 'kanban_board', 'blueprint_table'],
        'room-research': ['bookshelf', 'research_terminal', 'map_table', 'microscope'],
        'room-design': ['drafting_table', 'whiteboard', 'monitor_stand', 'pinboard'],
        'room-content': ['podcast_desk', 'microphone', 'workstation', 'desk', 'green_screen'],
        'room-ops': ['server_rack', 'security_console', 'server_console', 'network_switch', 'data_wall'],
        'room-support': ['desk', 'ticket_kiosk', 'dispatch_board', 'printer'],
        'room-lobby': ['reception_counter', 'package_station', 'bench', 'charging_dock'],
    };
    const primaryTypes = primaryTypesByRoom[roomId] || [];
    const primaryAsset = primaryTypes.length
        ? choose(assets.filter((asset) => primaryTypes.includes(safeString(asset?.type))))
        : null;
    if (primaryAsset) return primaryAsset;
    const workTypes = new Set([
        'workstation', 'desk', 'whiteboard', 'server_rack', 'bookshelf', 'round_table',
        'conference_table', 'kanban_board', 'blueprint_table', 'lab_bench', 'wall_monitor',
        'security_console', 'standing_desk', 'drafting_table', 'mail_sorter', 'printer',
        'reception_counter', 'package_station', 'router_node',
    ]);
    return choose(assets.filter((asset) => {
        const type = safeString(asset?.type);
        const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[type]?.interaction);
        return workTypes.has(type) || new Set(['work', 'monitor', 'present', 'plan', 'design', 'sort', 'dispatch']).has(interaction);
    })) || choose(assets);
}

function officeDraftAgentPinnedTargetWorld(space, agent) {
    if (!space || !agent) return null;
    if (!officeDraftAgentPinnedTargetActive(agent)) return null;
    if (safeString(agent.draftPinnedRoomId) !== officeDraftNormalizeRoomId(space?.roomId, space?.id)) return null;
    const rect = officeDraftSpaceRect(space);
    const localX = Number(agent.draftPinnedLocalX);
    const localY = Number(agent.draftPinnedLocalY);
    if (!Number.isFinite(localX) || !Number.isFinite(localY)) return null;
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(rect.left + localX, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(rect.top + localY, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftAgentNavStats(agent) {
    if (!agent) return null;
    if (!agent.draftNavStats || typeof agent.draftNavStats !== 'object') {
        agent.draftNavStats = {
            version: OFFICE_DRAFT_AGENT_NAV_VERSION,
            routeResets: 0,
            obstacleDetours: 0,
            stuckReplans: 0,
            hardClamps: 0,
            maxJump: 0,
            lastJump: 0,
        };
    }
    agent.draftNavStats.version = OFFICE_DRAFT_AGENT_NAV_VERSION;
    return agent.draftNavStats;
}

function officeDraftWalkableBounds(space) {
    const rect = officeDraftSpaceRect(space);
    const margin = OFFICE_DRAFT_AGENT_ROOM_MARGIN;
    return {
        left: Math.round(rect.left + margin),
        top: Math.round(rect.top + margin),
        right: Math.round(rect.right - margin),
        bottom: Math.round(rect.bottom - margin),
    };
}

function officeDraftPointInsideRect(point, rect, padding = 0) {
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    return x >= (Number(rect?.left) - padding)
        && x <= (Number(rect?.right) + padding)
        && y >= (Number(rect?.top) - padding)
        && y <= (Number(rect?.bottom) + padding);
}

function officeDraftLineSegmentIntersectsRect(a, b, rect, padding = 0) {
    if (!rect) return false;
    if (officeDraftPointInsideRect(a, rect, padding) || officeDraftPointInsideRect(b, rect, padding)) return true;
    const left = Number(rect.left) - padding;
    const right = Number(rect.right) + padding;
    const top = Number(rect.top) - padding;
    const bottom = Number(rect.bottom) + padding;
    const x1 = Number(a?.x) || 0;
    const y1 = Number(a?.y) || 0;
    const x2 = Number(b?.x) || 0;
    const y2 = Number(b?.y) || 0;
    const dx = x2 - x1;
    const dy = y2 - y1;
    let t0 = 0;
    let t1 = 1;
    const clip = (p, q) => {
        if (Math.abs(p) < 0.000001) return q >= 0;
        const r = q / p;
        if (p < 0) {
            if (r > t1) return false;
            if (r > t0) t0 = r;
            return true;
        }
        if (r < t0) return false;
        if (r < t1) t1 = r;
        return true;
    };
    return clip(-dx, x1 - left)
        && clip(dx, right - x1)
        && clip(-dy, y1 - top)
        && clip(dy, bottom - y1)
        && t0 <= t1;
}

function officeDraftPointObstacleClearance(point, obstaclesRaw = []) {
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : [];
    if (!obstacles.length) return 9999;
    let best = Number.POSITIVE_INFINITY;
    obstacles.forEach((rect) => {
        const x = Number(point?.x) || 0;
        const y = Number(point?.y) || 0;
        if (officeDraftPointInsideRect(point, rect)) {
            best = 0;
            return;
        }
        const dx = x < rect.left ? rect.left - x : (x > rect.right ? x - rect.right : 0);
        const dy = y < rect.top ? rect.top - y : (y > rect.bottom ? y - rect.bottom : 0);
        best = Math.min(best, Math.hypot(dx, dy));
    });
    return Number.isFinite(best) ? best : 9999;
}


