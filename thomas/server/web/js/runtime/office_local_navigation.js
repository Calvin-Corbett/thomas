/** Orthogonal and grid local navigation. */

function officeDraftSegmentClearInSpace(a, b, space, obstaclesRaw = null) {
    if (!space) return true;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    if (!officeDraftPointWalkableInSpace(a, space, obstacles) || !officeDraftPointWalkableInSpace(b, space, obstacles)) return false;
    return !obstacles.some((rect) => officeDraftLineSegmentIntersectsRect(a, b, rect));
}

function officeDraftLocalNavCandidatePoints(space, start, target, obstaclesRaw = null) {
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const rawPoints = [
        start,
        target,
        officeDraftSpaceCenter(space),
        { x: start.x, y: target.y },
        { x: target.x, y: start.y },
        { x: bounds.left, y: bounds.top },
        { x: bounds.right, y: bounds.top },
        { x: bounds.left, y: bounds.bottom },
        { x: bounds.right, y: bounds.bottom },
    ];
    obstacles.forEach((rect) => {
        const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
        const centerX = (rect.left + rect.right) / 2;
        const centerY = (rect.top + rect.bottom) / 2;
        rawPoints.push(
            { x: rect.left - gap, y: rect.top - gap },
            { x: rect.right + gap, y: rect.top - gap },
            { x: rect.left - gap, y: rect.bottom + gap },
            { x: rect.right + gap, y: rect.bottom + gap },
            { x: rect.left - gap, y: centerY },
            { x: rect.right + gap, y: centerY },
            { x: centerX, y: rect.top - gap },
            { x: centerX, y: rect.bottom + gap },
            { x: start.x, y: rect.top - gap },
            { x: start.x, y: rect.bottom + gap },
            { x: rect.left - gap, y: start.y },
            { x: rect.right + gap, y: start.y },
            { x: target.x, y: rect.top - gap },
            { x: target.x, y: rect.bottom + gap },
            { x: rect.left - gap, y: target.y },
            { x: rect.right + gap, y: target.y },
        );
    });
    const byKey = new Map();
    rawPoints.forEach((point) => {
        const clamped = {
            x: Math.round(officeClamp(Number(point?.x) || 0, bounds.left, bounds.right)),
            y: Math.round(officeClamp(Number(point?.y) || 0, bounds.top, bounds.bottom)),
        };
        if (!officeDraftPointWalkableInSpace(clamped, space, obstacles)) return;
        const key = officeDraftPointKey(clamped, 6);
        if (!byKey.has(key)) byKey.set(key, clamped);
    });
    const startKey = officeDraftPointKey(start, 6);
    const targetKey = officeDraftPointKey(target, 6);
    return [...byKey.values()]
        .sort((a, b) => {
            const aKey = officeDraftPointKey(a, 6);
            const bKey = officeDraftPointKey(b, 6);
            if (aKey === startKey || aKey === targetKey) return -1;
            if (bKey === startKey || bKey === targetKey) return 1;
            const aScore = Math.hypot(a.x - start.x, a.y - start.y) + Math.hypot(a.x - target.x, a.y - target.y);
            const bScore = Math.hypot(b.x - start.x, b.y - start.y) + Math.hypot(b.x - target.x, b.y - target.y);
            return aScore - bScore;
        })
        .slice(0, OFFICE_DRAFT_AGENT_LOCAL_CANDIDATE_LIMIT);
}

function officeDraftFindOrthogonalLocalRoute(space, start, target, obstaclesRaw = null) {
    if (!space) return null;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
    const xCandidates = [start.x, target.x, (bounds.left + bounds.right) / 2, bounds.left, bounds.right];
    const yCandidates = [start.y, target.y, (bounds.top + bounds.bottom) / 2, bounds.top, bounds.bottom];
    obstacles.forEach((rect) => {
        xCandidates.push(rect.left - gap, rect.right + gap, (rect.left + rect.right) / 2);
        yCandidates.push(rect.top - gap, rect.bottom + gap, (rect.top + rect.bottom) / 2);
    });
    const clampPoint = (point) => officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(Number(point?.x) || 0, bounds.left, bounds.right)),
        y: Math.round(officeClamp(Number(point?.y) || 0, bounds.top, bounds.bottom)),
    }, space, obstacles);
    const candidatePaths = [];
    const addPath = (pointsRaw) => {
        const points = officeDraftDedupeRoute((Array.isArray(pointsRaw) ? pointsRaw : []).map(clampPoint));
        if (points.length < 2) return;
        const clear = points.every((point, index) => index === 0 || officeDraftSegmentClearInSpace(points[index - 1], point, space, obstacles));
        if (clear) candidatePaths.push(points);
    };
    yCandidates.forEach((yRaw) => {
        const y = Math.round(officeClamp(Number(yRaw) || start.y, bounds.top, bounds.bottom));
        addPath([start, { x: start.x, y }, { x: target.x, y }, target]);
    });
    xCandidates.forEach((xRaw) => {
        const x = Math.round(officeClamp(Number(xRaw) || start.x, bounds.left, bounds.right));
        addPath([start, { x, y: start.y }, { x, y: target.y }, target]);
    });
    if (!candidatePaths.length) return null;
    return candidatePaths.sort((a, b) => officeDraftRouteDistance(a) - officeDraftRouteDistance(b))[0];
}

function officeDraftFindGridLocalRoute(space, start, target, obstaclesRaw = null, deadlineRaw = 0) {
    if (!space) return null;
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const stepSize = Math.max(44, OFFICE_DRAFT_AGENT_LOCAL_SAMPLE_STEP + 14);
    const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
    const xs = new Set([bounds.left, bounds.right, start.x, target.x]);
    const ys = new Set([bounds.top, bounds.bottom, start.y, target.y]);
    for (let x = bounds.left; x <= bounds.right; x += stepSize) xs.add(Math.round(x));
    for (let y = bounds.top; y <= bounds.bottom; y += stepSize) ys.add(Math.round(y));
    obstacles.forEach((rect) => {
        [rect.left - gap, rect.right + gap, (rect.left + rect.right) / 2].forEach((x) => {
            xs.add(Math.round(officeClamp(x, bounds.left, bounds.right)));
        });
        [rect.top - gap, rect.bottom + gap, (rect.top + rect.bottom) / 2].forEach((y) => {
            ys.add(Math.round(officeClamp(y, bounds.top, bounds.bottom)));
        });
    });
    let xValues = [...xs].sort((a, b) => a - b);
    let yValues = [...ys].sort((a, b) => a - b);
    if (xValues.length * yValues.length > OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT) {
        const compactXs = new Set([bounds.left, bounds.right, start.x, target.x]);
        const compactYs = new Set([bounds.top, bounds.bottom, start.y, target.y]);
        for (let x = bounds.left; x <= bounds.right; x += stepSize) compactXs.add(Math.round(x));
        for (let y = bounds.top; y <= bounds.bottom; y += stepSize) compactYs.add(Math.round(y));
        xValues = [...compactXs].sort((a, b) => a - b);
        yValues = [...compactYs].sort((a, b) => a - b);
    }
    if (xValues.length * yValues.length > OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT) {
        return null;
    }
    const graph = new Map();
    const keyFor = (xIndex, yIndex) => `${xIndex},${yIndex}`;
    const nodeIdAt = new Map();
    xValues.forEach((x, xIndex) => {
        if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return;
        yValues.forEach((y, yIndex) => {
            if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return;
            const point = { x: Math.round(x), y: Math.round(y) };
            if (!officeDraftPointWalkableInSpace(point, space, obstacles)) return;
            const id = officeDraftPointKey(point, 4);
            graph.set(id, { id, x: point.x, y: point.y, links: new Map(), xIndex, yIndex });
            nodeIdAt.set(keyFor(xIndex, yIndex), id);
        });
    });
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
    const connect = (a, b) => {
        if (!a || !b || a.id === b.id) return;
        if (!officeDraftSegmentClearInSpace(a, b, space, obstacles)) return;
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        a.links.set(b.id, distance);
        b.links.set(a.id, distance);
    };
    graph.forEach((node) => {
        if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return;
        for (let dx = -1; dx <= 1; dx += 1) {
            for (let dy = -1; dy <= 1; dy += 1) {
                if (dx === 0 && dy === 0) continue;
                const neighborId = nodeIdAt.get(keyFor(node.xIndex + dx, node.yIndex + dy));
                if (!neighborId) continue;
                connect(node, graph.get(neighborId));
            }
        }
    });
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
    const startId = officeDraftPointKey(start, 4);
    const targetId = officeDraftPointKey(target, 4);
    if (!graph.has(startId) || !graph.has(targetId)) return null;
    const distances = new Map([[startId, 0]]);
    const parent = new Map();
    const unsettled = new Set(graph.keys());
    let guard = 0;
    while (unsettled.size) {
        guard += 1;
        if (guard % 16 === 0 && officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
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
    if (!distances.has(targetId)) return null;
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


