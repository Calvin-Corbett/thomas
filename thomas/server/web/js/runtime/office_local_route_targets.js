/** Local routes and asset approach targets. */

function officeDraftFindLocalRoute(space, startRaw, targetRaw, obstaclesRaw = null, deadlineRaw = 0) {
    if (!space) return officeDraftDedupeRoute([startRaw, targetRaw]);
    const deadline = Number(deadlineRaw) || officeDraftRouteSolveDeadline();
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const start = officeDraftClampWorldPointToWalkable(startRaw, space, obstacles);
    const target = officeDraftClampWorldPointToWalkable(targetRaw, space, obstacles);
    if (officeDraftRouteDeadlineExceeded(deadline)) return [start];
    if (Math.hypot(start.x - target.x, start.y - target.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        return [target];
    }
    if (officeDraftSegmentClearInSpace(start, target, space, obstacles)) {
        return officeDraftDedupeRoute([start, target]);
    }
    const orthogonalRoute = officeDraftFindOrthogonalLocalRoute(space, start, target, obstacles);
    if (orthogonalRoute && orthogonalRoute.length > 1) return orthogonalRoute;
    if (officeDraftRouteDeadlineExceeded(deadline)) return [start];
    const points = officeDraftLocalNavCandidatePoints(space, start, target, obstacles);
    const startId = officeDraftPointKey(start, 6);
    const targetId = officeDraftPointKey(target, 6);
    const graph = new Map();
    const ensureNode = (point) => {
        const key = officeDraftPointKey(point, 6);
        if (!graph.has(key)) graph.set(key, { id: key, x: point.x, y: point.y, links: new Map() });
        return graph.get(key);
    };
    points.forEach(ensureNode);
    const edgeCandidates = [];
    for (let i = 0; i < points.length; i += 1) {
        if (i % 8 === 0 && officeDraftRouteDeadlineExceeded(deadline)) return [start];
        for (let j = i + 1; j < points.length; j += 1) {
            const a = points[i];
            const b = points[j];
            const distance = Math.hypot(a.x - b.x, a.y - b.y);
            const aligned = Math.abs(a.x - b.x) <= 3 || Math.abs(a.y - b.y) <= 3;
            const endpointBonus = i < 2 || j < 2 ? 220 : 0;
            edgeCandidates.push({ a, b, distance, score: distance - (aligned ? 180 : 0) - endpointBonus });
        }
    }
    if (officeDraftRouteDeadlineExceeded(deadline)) return [start];
    edgeCandidates.sort((a, b) => a.score - b.score);
    let edgeIndex = 0;
    for (const edge of edgeCandidates.slice(0, OFFICE_DRAFT_AGENT_LOCAL_EDGE_LIMIT)) {
        edgeIndex += 1;
        if (edgeIndex % 32 === 0 && officeDraftRouteDeadlineExceeded(deadline)) return [start];
        if (!officeDraftSegmentClearInSpace(edge.a, edge.b, space, obstacles)) continue;
        const aNode = ensureNode(edge.a);
        const bNode = ensureNode(edge.b);
        const distance = Math.hypot(aNode.x - bNode.x, aNode.y - bNode.y);
        aNode.links.set(bNode.id, distance);
        bNode.links.set(aNode.id, distance);
    }
    if (!graph.has(startId) || !graph.has(targetId)) {
        return officeDraftFindGridLocalRoute(space, start, target, obstacles, deadline) || [start];
    }
    const distances = new Map([[startId, 0]]);
    const parent = new Map();
    const unsettled = new Set(graph.keys());
    let guard = 0;
    while (unsettled.size) {
        guard += 1;
        if (guard % 16 === 0 && officeDraftRouteDeadlineExceeded(deadline)) return [start];
        let currentId = '';
        let currentDistance = Number.POSITIVE_INFINITY;
        unsettled.forEach((nodeId) => {
            const distance = distances.has(nodeId) ? distances.get(nodeId) : Number.POSITIVE_INFINITY;
            if (distance < currentDistance) {
                currentDistance = distance;
                currentId = nodeId;
            }
        });
        if (!currentId || !Number.isFinite(currentDistance)) break;
        unsettled.delete(currentId);
        if (currentId === targetId) break;
        const node = graph.get(currentId);
        node?.links?.forEach((weight, nextId) => {
            if (!unsettled.has(nextId)) return;
            const nextDistance = currentDistance + weight;
            if (nextDistance < (distances.get(nextId) ?? Number.POSITIVE_INFINITY)) {
                distances.set(nextId, nextDistance);
                parent.set(nextId, currentId);
            }
        });
    }
    if (!distances.has(targetId)) {
        return officeDraftFindGridLocalRoute(space, start, target, obstacles, deadline) || [start];
    }
    const route = [];
    let cursor = targetId;
    while (cursor) {
        const node = graph.get(cursor);
        if (node) route.push({ x: node.x, y: node.y });
        if (cursor === startId) break;
        cursor = parent.get(cursor);
    }
    route.reverse();
    return officeDraftDedupeRoute(route);
}

function officeDraftAssetApproachCandidates(space, asset, seed = 0, obstaclesRaw = null) {
    if (!space || !asset) return [];
    const rect = officeDraftSpaceRect(space);
    const dims = officeDraftAssetDimensions(asset.type, asset.scale);
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const standOff = Math.max(98, OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN + OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP);
    const spread = Math.max(56, Math.min(96, Math.round(Math.max(dims.width, dims.height) * 0.28)));
    const assetLeft = rect.left + (Number(asset.x) || 0);
    const assetTop = rect.top + (Number(asset.y) || 0);
    const assetRight = assetLeft + dims.width;
    const assetBottom = assetTop + dims.height;
    const centerX = assetLeft + (dims.width / 2);
    const centerY = assetTop + (dims.height / 2);
    const sideSpecs = [
        { name: 'bottom', axis: 'x', x: centerX, y: assetBottom + standOff },
        { name: 'right', axis: 'y', x: assetRight + standOff, y: centerY },
        { name: 'left', axis: 'y', x: assetLeft - standOff, y: centerY },
        { name: 'top', axis: 'x', x: centerX, y: assetTop - standOff },
    ];
    const sideOffset = Math.abs(Math.round(Number(seed) || 0)) % sideSpecs.length;
    const orderedSides = sideSpecs.slice(sideOffset).concat(sideSpecs.slice(0, sideOffset));
    const spreadValues = [0, -spread, spread, -(spread * 1.7), spread * 1.7];
    const candidates = [];
    const seen = new Set();
    orderedSides.forEach((side, sideIndex) => {
        spreadValues.forEach((spreadValue, spreadIndex) => {
            const raw = {
                x: side.axis === 'x' ? side.x + spreadValue : side.x,
                y: side.axis === 'y' ? side.y + spreadValue : side.y,
            };
            const bounded = {
                x: Math.round(officeClamp(raw.x, rect.left + 92, rect.right - 136)),
                y: Math.round(officeClamp(raw.y, rect.top + 112, rect.bottom - 172)),
            };
            const point = officeDraftClampWorldPointToWalkable(bounded, space, obstacles);
            if (!officeDraftPointWalkableInSpace(point, space, obstacles)) return;
            const key = officeDraftPointKey(point, 8);
            if (seen.has(key)) return;
            seen.add(key);
            candidates.push({
                point,
                raw: bounded,
                side: side.name,
                sideIndex,
                spreadIndex,
            });
        });
    });
    return candidates;
}

function officeDraftAssetApproachAnchor(space, obstaclesRaw = null) {
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const state = officeEnsureDraftMapState();
    const network = officeDraftAutoHallwayNetwork(state.spaces);
    const doorInterior = officeDraftClampWorldPointToWalkable(officeDraftSpaceDoorInteriorPoint(space, network), space, obstacles);
    if (officeDraftPointWalkableInSpace(doorInterior, space, obstacles)) return doorInterior;
    return officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
}

function officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed = 0, options = {}) {
    if (!space || !targetAsset) return null;
    const allowRouteSearch = options?.routeAware === true;
    const obstacles = officeDraftObstacleRects(space);
    const cacheKey = [
        OFFICE_DRAFT_AGENT_NAV_VERSION,
        safeString(space?.id),
        Math.round(Number(space?.x) || 0),
        Math.round(Number(space?.y) || 0),
        Math.round(Number(space?.width) || 0),
        Math.round(Number(space?.height) || 0),
        safeString(targetAsset?.id),
        Math.round(Number(targetAsset?.x) || 0),
        Math.round(Number(targetAsset?.y) || 0),
        officeDraftClampAssetScale(targetAsset?.scale),
        officeDraftNormalizeRotation(targetAsset?.rotation),
    ].join('|');
    if (agent?.draftTargetPointCache?.key === cacheKey) {
        const cached = {
            x: Math.round(Number(agent.draftTargetPointCache.x) || 0),
            y: Math.round(Number(agent.draftTargetPointCache.y) || 0),
        };
        const cachedRouteAware = agent.draftTargetPointCache.routeAware === true;
        if (officeDraftPointWalkableInSpace(cached, space, obstacles)
            && (cachedRouteAware || !allowRouteSearch)) {
            return cached;
        }
    }
    const anchor = officeDraftAssetApproachAnchor(space, obstacles);
    const center = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const targetDims = officeDraftAssetDimensions(targetAsset.type, targetAsset.scale);
    const targetRect = officeDraftSpaceRect(space);
    const targetCenter = {
        x: targetRect.left + (Number(targetAsset.x) || 0) + (targetDims.width / 2),
        y: targetRect.top + (Number(targetAsset.y) || 0) + (targetDims.height / 2),
    };
    let best = null;
    let routeSearches = 0;
    const deadline = allowRouteSearch ? officeDraftRouteSolveDeadline(OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS) : 0;
    officeDraftAssetApproachCandidates(space, targetAsset, seed, obstacles).forEach((candidate) => {
        const point = candidate.point;
        const anchorClear = officeDraftSegmentClearInSpace(anchor, point, space, obstacles);
        const shouldRouteSearch = allowRouteSearch
            && !anchorClear
            && routeSearches < 8
            && !officeDraftRouteDeadlineExceeded(deadline);
        let localRoute = anchorClear ? [anchor, point] : null;
        if (shouldRouteSearch) {
            routeSearches += 1;
            localRoute = officeDraftFindLocalRoute(space, anchor, point, obstacles, deadline);
        }
        const localRouteClear = Array.isArray(localRoute)
            && officeDraftRouteReached(localRoute, point)
            && officeDraftRouteClearInSpace(localRoute, space, obstacles);
        const centerClear = anchorClear || localRouteClear || officeDraftSegmentClearInSpace(center, point, space, obstacles);
        const clearance = officeDraftPointObstacleClearance(point, obstacles);
        const diversitySlot = Math.abs(Number(seed) || 0) % 13;
        const candidateSlot = ((candidate.sideIndex * 5) + candidate.spreadIndex) % 13;
        const assetDistance = Math.hypot(point.x - targetCenter.x, point.y - targetCenter.y);
        const routeDistance = localRouteClear ? officeDraftRouteDistance(localRoute) : Math.hypot(point.x - anchor.x, point.y - anchor.y);
        const score = (anchorClear ? 0 : (localRouteClear ? 280 : (centerClear ? 780 : 1900)))
            + (Math.max(0, 132 - clearance) * 7)
            + (routeDistance * 0.42)
            + (assetDistance * 0.62)
            + (Math.max(0, assetDistance - 230) * 8)
            + (candidate.sideIndex * 18)
            + (candidate.spreadIndex * 7)
            + (Math.abs(diversitySlot - candidateSlot) * 20)
            + (Math.hypot(point.x - candidate.raw.x, point.y - candidate.raw.y) * 3);
        if (!best || score < best.score) {
            best = { point, score, routeAware: localRouteClear || anchorClear };
        }
    });
    if (!best) return null;
    if (agent && typeof agent === 'object') {
        agent.draftTargetPointCache = {
            key: cacheKey,
            x: best.point.x,
            y: best.point.y,
            routeAware: allowRouteSearch && best.routeAware === true,
        };
    }
    return best.point;
}


