/** Walkable bounds, obstacles, and spawn points. */

const OFFICE_DRAFT_WALL_MOUNTED_ASSET_TYPES = new Set([
    'acoustic_panel',
    'data_wall',
    'dispatch_board',
    'green_screen',
    'kanban_board',
    'pinboard',
    'room_sign',
    'sticky_note_wall',
    'wall_clock',
    'wall_monitor',
    'whiteboard',
]);

function officeDraftAssetBlocksNavigation(asset) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(descriptor.shape);
    if (!type) return false;
    if (OFFICE_DRAFT_WALL_MOUNTED_ASSET_TYPES.has(type)) return false;
    if (new Set(['rug', 'carpet']).has(type)) return false;
    if (new Set(['rug']).has(shape)) return false;
    return true;
}

function officeDraftAssetObstacleRect(space, asset, marginRaw = OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN) {
    if (!space || !asset || !officeDraftAssetBlocksNavigation(asset)) return null;
    const dims = officeDraftAssetDimensions(asset.type, asset.scale);
    const margin = Math.max(0, Number(marginRaw) || 0);
    const left = (Number(space.x) || 0) + (Number(asset.x) || 0);
    const top = (Number(space.y) || 0) + (Number(asset.y) || 0);
    return {
        assetId: safeString(asset.id),
        type: safeString(asset.type),
        left: Math.round(left - margin),
        top: Math.round(top - margin),
        right: Math.round(left + dims.width + margin),
        bottom: Math.round(top + dims.height + margin),
    };
}

function officeDraftObstacleRects(space) {
    if (!space || !Array.isArray(space.assets)) return [];
    return space.assets
        .map((asset) => officeDraftAssetObstacleRect(space, asset))
        .filter(Boolean);
}

function officeDraftPointInWalkableBounds(point, space) {
    const bounds = officeDraftWalkableBounds(space);
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    return x >= bounds.left && x <= bounds.right && y >= bounds.top && y <= bounds.bottom;
}

function officeDraftPointWalkableInSpace(point, space, obstaclesRaw = null) {
    if (!officeDraftPointInWalkableBounds(point, space)) return false;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    return !obstacles.some((rect) => officeDraftPointInsideRect(point, rect));
}

function officeDraftClampWorldPointToWalkable(pointRaw, space, obstaclesRaw = null) {
    if (!space) return {
        x: Math.round(Number(pointRaw?.x) || 0),
        y: Math.round(Number(pointRaw?.y) || 0),
    };
    const bounds = officeDraftWalkableBounds(space);
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const raw = {
        x: Math.round(officeClamp(Number(pointRaw?.x) || ((bounds.left + bounds.right) / 2), bounds.left, bounds.right)),
        y: Math.round(officeClamp(Number(pointRaw?.y) || ((bounds.top + bounds.bottom) / 2), bounds.top, bounds.bottom)),
    };
    if (officeDraftPointWalkableInSpace(raw, space, obstacles)) return raw;
    const candidates = [raw, officeDraftSpaceCenter(space)];
    obstacles.forEach((rect) => {
        const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
        const centerX = (rect.left + rect.right) / 2;
        const centerY = (rect.top + rect.bottom) / 2;
        candidates.push(
            { x: rect.left - gap, y: rect.top - gap },
            { x: rect.right + gap, y: rect.top - gap },
            { x: rect.left - gap, y: rect.bottom + gap },
            { x: rect.right + gap, y: rect.bottom + gap },
            { x: rect.left - gap, y: centerY },
            { x: rect.right + gap, y: centerY },
            { x: centerX, y: rect.top - gap },
            { x: centerX, y: rect.bottom + gap },
        );
    });
    for (let radius = 52; radius <= 420; radius += 52) {
        for (let step = 0; step < 16; step += 1) {
            const angle = (Math.PI * 2 * step) / 16;
            candidates.push({
                x: raw.x + (Math.cos(angle) * radius),
                y: raw.y + (Math.sin(angle) * radius),
            });
        }
    }
    let best = null;
    candidates.forEach((candidate) => {
        const clamped = {
            x: Math.round(officeClamp(Number(candidate?.x) || raw.x, bounds.left, bounds.right)),
            y: Math.round(officeClamp(Number(candidate?.y) || raw.y, bounds.top, bounds.bottom)),
        };
        if (!officeDraftPointWalkableInSpace(clamped, space, obstacles)) return;
        const distance = Math.hypot(clamped.x - raw.x, clamped.y - raw.y);
        if (!best || distance < best.distance) {
            best = { ...clamped, distance };
        }
    });
    return best ? { x: best.x, y: best.y } : raw;
}

function officeDraftSpaceSpawnWorldPoint(space, agent, index = 0, total = 1) {
    const rect = officeDraftSpaceRect(space);
    const totalAgents = Math.max(1, Number(total) || 1);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|spawn`);
    const baseX = Number(space?.robotX) || (rect.width / 2);
    const baseY = Number(space?.robotY) || (rect.height / 2);
    return officeDraftClampWorldPointToWalkable({
        x: rect.left + baseX + ((index - ((totalAgents - 1) / 2)) * 84),
        y: rect.top + baseY + (((seed % 5) - 2) * 34),
    }, space);
}

function officeDraftCheapAgentTargetWorldPoint(space, agent, index = 0, total = 1) {
    const bounds = officeDraftWalkableBounds(space);
    const left = Math.min(bounds.left, bounds.right);
    const right = Math.max(bounds.left, bounds.right);
    const top = Math.min(bounds.top, bounds.bottom);
    const bottom = Math.max(bounds.top, bounds.bottom);
    const totalAgents = Math.max(1, Number(total) || 1);
    const slotIndex = Math.max(0, Math.min(totalAgents - 1, Number(index) || 0));
    const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(totalAgents))));
    const rows = Math.max(1, Math.ceil(totalAgents / columns));
    const column = slotIndex % columns;
    const row = Math.floor(slotIndex / columns);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|cheap-target`);
    const jitterX = ((seed % 5) - 2) * 14;
    const jitterY = ((Math.floor(seed / 5) % 5) - 2) * 12;
    return {
        x: Math.round(officeClamp(left + (((right - left) / (columns + 1)) * (column + 1)) + jitterX, left, right)),
        y: Math.round(officeClamp(top + (((bottom - top) / (rows + 1)) * (row + 1)) + jitterY, top, bottom)),
    };
}

function officeDraftInitialMotionSpaceForAgent(agent, targetSpace) {
    const state = officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    const byId = (spaceId) => spaces.find((space) => safeString(space?.id) === safeString(spaceId)) || null;
    const lastSpace = byId(agent?.draftLastSpaceId);
    if (lastSpace) return lastSpace;
    const currentRoom = typeof officeCurrentRoomForAgent === 'function' ? officeCurrentRoomForAgent(agent) : null;
    const currentSpace = currentRoom?.id ? officeDraftSpaceForRoomId(currentRoom.id) : null;
    if (currentSpace && safeString(currentSpace.id) !== safeString(targetSpace?.id)) return currentSpace;
    const homeSpace = officeDraftSpaceForRoomId(officeDraftHomeRoomIdForAgent(agent));
    if (homeSpace && safeString(homeSpace.id) !== safeString(targetSpace?.id)) return homeSpace;
    const lobby = byId('lobby');
    if (lobby && safeString(lobby.id) !== safeString(targetSpace?.id)) return lobby;
    return targetSpace || lobby || spaces[0] || null;
}

function officeDraftInitialMotionWorldPoint(agent, targetSpace, targetWorld, index = 0, total = 1) {
    const sourceSpace = officeDraftInitialMotionSpaceForAgent(agent, targetSpace);
    if (!sourceSpace) return targetWorld;
    if (officeDraftAgentWanderTargetActive(agent)) {
        return officeDraftSpaceSpawnWorldPoint(sourceSpace, agent, index, total);
    }
    if (!safeString(agent?.taskId)
        && !officeDraftAgentCommandActive(agent)
        && safeString(agent?.intent) !== 'task') {
        return targetWorld;
    }
    return officeDraftSpaceSpawnWorldPoint(sourceSpace, agent, index, total);
}
