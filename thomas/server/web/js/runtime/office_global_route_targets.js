/** Agent target spreading and cross-room routes. */

function officeDraftSpreadAgentTargetPoint(space, pointRaw, index = 0, total = 1, seed = 0, obstaclesRaw = null) {
    if (!space || !pointRaw) return pointRaw || { x: 0, y: 0 };
    const totalAgents = Math.max(1, Number(total) || 1);
    if (totalAgents <= 1) return pointRaw;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const slotIndex = Math.max(0, Number(index) || 0);
    const base = officeDraftClampWorldPointToWalkable(pointRaw, space, obstacles);
    const angleBase = (((slotIndex * 137.508) + (Math.abs(Number(seed) || 0) % 89)) % 360) * (Math.PI / 180);
    const radiusBase = 74 + ((slotIndex % 4) * 22) + (Math.floor(slotIndex / 4) * 18);
    const offsets = [
        { angle: angleBase, radius: radiusBase },
        { angle: angleBase + Math.PI * 0.5, radius: radiusBase * 0.9 },
        { angle: angleBase - Math.PI * 0.5, radius: radiusBase * 0.9 },
        { angle: angleBase + Math.PI, radius: radiusBase * 0.72 },
        { angle: angleBase + Math.PI * 0.25, radius: radiusBase * 1.12 },
        { angle: angleBase - Math.PI * 0.25, radius: radiusBase * 1.12 },
    ];
    let best = null;
    offsets.forEach((offset, offsetIndex) => {
        const candidateRaw = {
            x: base.x + (Math.cos(offset.angle) * offset.radius),
            y: base.y + (Math.sin(offset.angle) * offset.radius),
        };
        const candidate = officeDraftClampWorldPointToWalkable({
            x: Math.round(officeClamp(candidateRaw.x, bounds.left, bounds.right)),
            y: Math.round(officeClamp(candidateRaw.y, bounds.top, bounds.bottom)),
        }, space, obstacles);
        if (!officeDraftPointWalkableInSpace(candidate, space, obstacles)) return;
        const clearance = officeDraftPointObstacleClearance(candidate, obstacles);
        const score = Math.hypot(candidate.x - base.x, candidate.y - base.y)
            + (offsetIndex * 9)
            - (Math.min(220, clearance) * 1.45);
        if (!best || score < best.score) best = { point: candidate, score };
    });
    return best?.point || base;
}

function officeDraftAgentTargetWorldPoint(space, agent, index = 0, total = 1, targetAsset = null) {
    const rect = officeDraftSpaceRect(space);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|target`);
    const wanderTarget = officeDraftAgentWanderTargetWorld(space, agent);
    if (wanderTarget) return wanderTarget;
    if (targetAsset) {
        const commandAsset = officeDraftAgentCommandAsset(space, agent);
        const routeAware = commandAsset && safeString(commandAsset?.id) === safeString(targetAsset?.id);
        const approach = officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed, { routeAware });
        if (approach) return officeDraftSpreadAgentTargetPoint(space, approach, index, total, seed);
    }
    const totalAgents = Math.max(1, Number(total) || 1);
    const slotIndex = Math.max(0, Math.min(totalAgents - 1, Number(index) || 0));
    const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(totalAgents))));
    const rows = Math.max(1, Math.ceil(totalAgents / columns));
    const column = slotIndex % columns;
    const row = Math.floor(slotIndex / columns);
    const jitterX = ((seed % 5) - 2) * 18;
    const jitterY = ((Math.floor(seed / 5) % 5) - 2) * 14;
    const walkLeft = rect.left + 132;
    const walkRight = rect.right - 164;
    const walkTop = rect.top + 132;
    const walkBottom = rect.bottom - 190;
    let x = walkLeft + (((walkRight - walkLeft) / (columns + 1)) * (column + 1)) + jitterX;
    let y = walkTop + (((walkBottom - walkTop) / (rows + 1)) * (row + 1)) + jitterY;
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(x, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(y, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftRouteClearInSpace(routeRaw, space, obstaclesRaw = null) {
    const route = Array.isArray(routeRaw) ? routeRaw : [];
    if (route.length <= 1) return true;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    return route.every((point, index) => index === 0 || officeDraftSegmentClearInSpace(route[index - 1], point, space, obstacles));
}

function officeDraftFallbackAgentTargetWorldPoint(space, agent, index = 0, total = 1) {
    if (!space) return { x: 0, y: 0 };
    const cacheKey = [
        OFFICE_DRAFT_AGENT_NAV_VERSION,
        safeString(space?.id),
        Math.round(Number(space?.x) || 0),
        Math.round(Number(space?.y) || 0),
        Math.round(Number(space?.width) || 0),
        Math.round(Number(space?.height) || 0),
        safeString(agent?.id),
        (Array.isArray(space?.assets) ? space.assets : []).map((asset) => [
            safeString(asset?.id),
            safeString(asset?.type),
            Math.round(Number(asset?.x) || 0),
            Math.round(Number(asset?.y) || 0),
            officeDraftClampAssetScale(asset?.scale),
            officeDraftNormalizeRotation(asset?.rotation),
        ].join(':')).join(','),
    ].join('|');
    if (agent?.draftFallbackTargetCache?.key === cacheKey) {
        const cached = {
            x: Math.round(Number(agent.draftFallbackTargetCache.x) || 0),
            y: Math.round(Number(agent.draftFallbackTargetCache.y) || 0),
        };
        if (officeDraftPointWalkableInSpace(cached, space)) return cached;
    }
    const obstacles = officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const state = officeEnsureDraftMapState();
    const network = officeDraftAutoHallwayNetwork(state.spaces);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|fallback`);
    const anchor = officeDraftClampWorldPointToWalkable(officeDraftSpaceDoorInteriorPoint(space, network), space, obstacles);
    const center = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const spawn = officeDraftSpaceSpawnWorldPoint(space, agent, index, total);
    const candidates = [spawn, center, anchor];
    const xStops = [
        bounds.left + (bounds.right - bounds.left) * 0.28,
        bounds.left + (bounds.right - bounds.left) * 0.5,
        bounds.left + (bounds.right - bounds.left) * 0.72,
    ];
    const yStops = [
        bounds.top + (bounds.bottom - bounds.top) * 0.3,
        bounds.top + (bounds.bottom - bounds.top) * 0.52,
        bounds.top + (bounds.bottom - bounds.top) * 0.74,
    ];
    xStops.forEach((x) => {
        yStops.forEach((y) => candidates.push({ x, y }));
    });
    obstacles.forEach((rect) => {
        const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP + 22;
        const centerX = (rect.left + rect.right) / 2;
        const centerY = (rect.top + rect.bottom) / 2;
        candidates.push(
            { x: rect.left - gap, y: centerY },
            { x: rect.right + gap, y: centerY },
            { x: centerX, y: rect.top - gap },
            { x: centerX, y: rect.bottom + gap },
        );
    });
    let best = null;
    const seen = new Set();
    candidates.forEach((candidateRaw, candidateIndex) => {
        const candidate = officeDraftClampWorldPointToWalkable(candidateRaw, space, obstacles);
        const key = officeDraftPointKey(candidate, 8);
        if (seen.has(key) || !officeDraftPointWalkableInSpace(candidate, space, obstacles)) return;
        seen.add(key);
        if (Math.hypot(anchor.x - candidate.x, anchor.y - candidate.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON
            && !officeDraftSegmentClearInSpace(anchor, candidate, space, obstacles)) {
            return;
        }
        const clearance = officeDraftPointObstacleClearance(candidate, obstacles);
        const score = Math.hypot(anchor.x - candidate.x, anchor.y - candidate.y)
            + (Math.hypot(candidate.x - center.x, candidate.y - center.y) * 0.32)
            - (Math.min(220, clearance) * 1.8)
            + (((seed + candidateIndex) % 17) * 4);
        if (!best || score < best.score) {
            best = { point: candidate, score };
        }
    });
    const point = best?.point || anchor;
    const spreadPoint = officeDraftSpreadAgentTargetPoint(space, point, index, total, seed, obstacles);
    if (agent && typeof agent === 'object') {
        agent.draftFallbackTargetCache = {
            key: cacheKey,
            x: spreadPoint.x,
            y: spreadPoint.y,
        };
    }
    return spreadPoint;
}

function officeDraftFastRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw = null) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const startWorld = {
        x: Math.round(Number(startWorldRaw?.x) || 0),
        y: Math.round(Number(startWorldRaw?.y) || 0),
    };
    const targetWorld = {
        x: Math.round(Number(targetWorldRaw?.x) || 0),
        y: Math.round(Number(targetWorldRaw?.y) || 0),
    };
    const startSpace = officeDraftSpaceAtWorldPoint(startWorld.x, startWorld.y);
    const targetSpaceId = safeString(targetSpace?.id);
    if (startSpace && safeString(startSpace.id) === targetSpaceId) {
        const obstacles = officeDraftObstacleRects(startSpace);
        if (officeDraftSegmentClearInSpace(startWorld, targetWorld, startSpace, obstacles)) {
            return officeDraftDedupeRoute([startWorld, targetWorld]);
        }
        return officeDraftDedupeRoute(officeDraftFindOrthogonalLocalRoute(startSpace, startWorld, targetWorld, obstacles) || [startWorld, targetWorld]);
    }
    const route = [startWorld];
    let hallStart = officeDraftNearestHallwayPoint(startWorld, network);
    if (startSpace) {
        const startDoor = officeDraftSpaceDoorPoint(startSpace, network);
        const startInterior = officeDraftSpaceDoorInteriorPoint(startSpace, network);
        route.push(startInterior);
        route.push({ x: startDoor.worldX, y: startDoor.worldY });
        route.push({ x: startDoor.outsideX, y: startDoor.outsideY });
        hallStart = { x: startDoor.outsideX, y: startDoor.outsideY };
    } else if (hallStart.distance > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        route.push({ x: hallStart.x, y: hallStart.y });
    }
    const targetDoor = officeDraftSpaceDoorPoint(targetSpace, network);
    const hallEnd = { x: targetDoor.outsideX, y: targetDoor.outsideY };
    if (Math.hypot(hallStart.x - hallEnd.x, hallStart.y - hallEnd.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        if (Math.abs(hallStart.x - hallEnd.x) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON
            && Math.abs(hallStart.y - hallEnd.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
            route.push({ x: Math.round(hallEnd.x), y: Math.round(hallStart.y) });
        }
        route.push(hallEnd);
    }
    const targetInterior = officeDraftSpaceDoorInteriorPoint(targetSpace, network);
    route.push({ x: targetDoor.worldX, y: targetDoor.worldY });
    route.push(targetInterior);
    if (officeDraftSegmentClearInSpace(targetInterior, targetWorld, targetSpace)) {
        route.push(targetWorld);
    } else {
        route.push(officeDraftClampWorldPointToWalkable(targetWorld, targetSpace));
    }
    return officeDraftDedupeRoute(route);
}

function officeDraftRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw = null) {
    if (safeString(officeEnsureDraftMapState()?.agentRoutePlanningSource) === 'route-plan') {
        return officeDraftFastRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw);
    }
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const deadline = officeDraftRouteSolveDeadline(OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS * 1.8);
    const startWorld = {
        x: Math.round(Number(startWorldRaw?.x) || 0),
        y: Math.round(Number(startWorldRaw?.y) || 0),
    };
    const targetWorld = {
        x: Math.round(Number(targetWorldRaw?.x) || 0),
        y: Math.round(Number(targetWorldRaw?.y) || 0),
    };
    const startSpace = officeDraftSpaceAtWorldPoint(startWorld.x, startWorld.y);
    const targetSpaceId = safeString(targetSpace?.id);
    if (startSpace && safeString(startSpace.id) === targetSpaceId) {
        return officeDraftFindLocalRoute(startSpace, startWorld, targetWorld, null, deadline);
    }
    const route = [startWorld];
    let hallStart = officeDraftNearestHallwayPoint(startWorld, network);
    if (startSpace) {
        const startDoor = officeDraftSpaceDoorPoint(startSpace, network);
        const startInterior = officeDraftSpaceDoorInteriorPoint(startSpace, network);
        const localExit = officeDraftFindLocalRoute(startSpace, startWorld, startInterior, null, deadline);
        if (!officeDraftRouteReached(localExit, startInterior)) {
            return officeDraftDedupeRoute([startWorld]);
        }
        localExit.slice(1).forEach((point) => route.push(point));
        route.push({ x: startDoor.worldX, y: startDoor.worldY });
        route.push({ x: startDoor.outsideX, y: startDoor.outsideY });
        hallStart = { x: startDoor.outsideX, y: startDoor.outsideY };
    } else if (hallStart.distance > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        route.push({ x: hallStart.x, y: hallStart.y });
    }
    const targetDoor = officeDraftSpaceDoorPoint(targetSpace, network);
    const hallEnd = { x: targetDoor.outsideX, y: targetDoor.outsideY };
    const hallwayRoute = officeDraftFindHallwayRoute(network, hallStart, hallEnd, deadline);
    hallwayRoute.forEach((point, pointIndex) => {
        if (pointIndex === 0 && route.length && Math.hypot(route[route.length - 1].x - point.x, route[route.length - 1].y - point.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) return;
        route.push(point);
    });
    route.push({ x: targetDoor.worldX, y: targetDoor.worldY });
    const targetInterior = officeDraftSpaceDoorInteriorPoint(targetSpace, network);
    route.push(targetInterior);
    if (officeDraftRouteDeadlineExceeded(deadline)) return officeDraftDedupeRoute(route);
    const localEntry = officeDraftFindLocalRoute(targetSpace, targetInterior, targetWorld, null, deadline);
    if (!officeDraftRouteReached(localEntry, targetWorld)) {
        return officeDraftDedupeRoute(route);
    }
    localEntry.slice(1).forEach((point) => route.push(point));
    return officeDraftDedupeRoute(route);
}


