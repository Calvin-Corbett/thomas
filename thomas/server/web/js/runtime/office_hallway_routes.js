/** Hallway graph construction and route utilities. */

function officeDraftPointKey(point, precision = 1) {
    const scale = Math.max(1, Number(precision) || 1);
    const x = Math.round((Number(point?.x) || 0) / scale) * scale;
    const y = Math.round((Number(point?.y) || 0) / scale) * scale;
    return `${Math.round(x)},${Math.round(y)}`;
}

function officeDraftRouteSolveDeadline(budgetMs = OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS) {
    return performance.now() + Math.max(4, Number(budgetMs) || OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS);
}

function officeDraftRouteDeadlineExceeded(deadlineRaw) {
    const deadline = Number(deadlineRaw) || 0;
    return deadline > 0 && performance.now() > deadline;
}

function officeDraftSegmentLength(segment) {
    if (!segment) return 0;
    return Math.hypot((Number(segment.x2) || 0) - (Number(segment.x1) || 0), (Number(segment.y2) || 0) - (Number(segment.y1) || 0));
}

function officeDraftPointOnSegment(point, segment, tolerance = 1) {
    if (!point || !segment) return false;
    const x = Number(point.x) || 0;
    const y = Number(point.y) || 0;
    const x1 = Number(segment.x1) || 0;
    const y1 = Number(segment.y1) || 0;
    const x2 = Number(segment.x2) || 0;
    const y2 = Number(segment.y2) || 0;
    const minX = Math.min(x1, x2) - tolerance;
    const maxX = Math.max(x1, x2) + tolerance;
    const minY = Math.min(y1, y2) - tolerance;
    const maxY = Math.max(y1, y2) + tolerance;
    if (x < minX || x > maxX || y < minY || y > maxY) return false;
    const dx = x2 - x1;
    const dy = y2 - y1;
    if (Math.abs(dx) < 0.001) return Math.abs(x - x1) <= tolerance;
    if (Math.abs(dy) < 0.001) return Math.abs(y - y1) <= tolerance;
    const cross = Math.abs(((x - x1) * dy) - ((y - y1) * dx));
    return cross <= tolerance * Math.max(1, Math.hypot(dx, dy));
}

function officeDraftProjectPointToSegment(point, segment) {
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    const x1 = Number(segment?.x1) || 0;
    const y1 = Number(segment?.y1) || 0;
    const x2 = Number(segment?.x2) || 0;
    const y2 = Number(segment?.y2) || 0;
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lengthSq = (dx * dx) + (dy * dy);
    if (lengthSq <= 0.001) return { x: Math.round(x1), y: Math.round(y1), distance: Math.hypot(x - x1, y - y1) };
    const t = officeClamp((((x - x1) * dx) + ((y - y1) * dy)) / lengthSq, 0, 1);
    const px = x1 + (dx * t);
    const py = y1 + (dy * t);
    return {
        x: Math.round(px),
        y: Math.round(py),
        distance: Math.hypot(x - px, y - py),
    };
}

function officeDraftSegmentIntersectionPoint(a, b) {
    if (!a || !b) return null;
    const aHorizontal = safeString(a.orientation) === 'h' || Math.abs((Number(a.y2) || 0) - (Number(a.y1) || 0)) < 0.001;
    const bHorizontal = safeString(b.orientation) === 'h' || Math.abs((Number(b.y2) || 0) - (Number(b.y1) || 0)) < 0.001;
    if (aHorizontal === bHorizontal) return null;
    const h = aHorizontal ? a : b;
    const v = aHorizontal ? b : a;
    const y = Number(h.y1) || 0;
    const x = Number(v.x1) || 0;
    const hMin = Math.min(Number(h.x1) || 0, Number(h.x2) || 0) - 1;
    const hMax = Math.max(Number(h.x1) || 0, Number(h.x2) || 0) + 1;
    const vMin = Math.min(Number(v.y1) || 0, Number(v.y2) || 0) - 1;
    const vMax = Math.max(Number(v.y1) || 0, Number(v.y2) || 0) + 1;
    if (x < hMin || x > hMax || y < vMin || y > vMax) return null;
    return { x: Math.round(x), y: Math.round(y) };
}

function officeDraftNearestHallwayPoint(point, networkRaw) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const segments = Array.isArray(network?.segments) ? network.segments.filter((segment) => officeDraftSegmentLength(segment) > 2) : [];
    let best = null;
    segments.forEach((segment) => {
        const projected = officeDraftProjectPointToSegment(point, segment);
        if (!best || projected.distance < best.distance) {
            best = { ...projected, segment };
        }
    });
    return best || { x: Number(point?.x) || 0, y: Number(point?.y) || 0, distance: 0, segment: null };
}

function officeDraftBuildHallwayRouteGraph(networkRaw, extraPointsRaw = []) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const segments = Array.isArray(network?.segments) ? network.segments.filter((segment) => officeDraftSegmentLength(segment) > 2) : [];
    const pointByKey = new Map();
    const addPoint = (point) => {
        if (!point) return null;
        const normalized = {
            x: Math.round(Number(point.x) || 0),
            y: Math.round(Number(point.y) || 0),
        };
        const key = officeDraftPointKey(normalized);
        if (!pointByKey.has(key)) pointByKey.set(key, normalized);
        return pointByKey.get(key);
    };
    segments.forEach((segment) => {
        addPoint({ x: segment.x1, y: segment.y1 });
        addPoint({ x: segment.x2, y: segment.y2 });
    });
    for (let i = 0; i < segments.length; i += 1) {
        for (let j = i + 1; j < segments.length; j += 1) {
            addPoint(officeDraftSegmentIntersectionPoint(segments[i], segments[j]));
        }
    }
    (Array.isArray(extraPointsRaw) ? extraPointsRaw : []).forEach(addPoint);
    if (pointByKey.size > OFFICE_DRAFT_AGENT_HALLWAY_GRAPH_NODE_LIMIT) {
        return new Map();
    }
    const graph = new Map();
    const ensureNode = (point) => {
        const normalized = addPoint(point);
        if (!normalized) return '';
        const key = officeDraftPointKey(normalized);
        if (!graph.has(key)) {
            graph.set(key, {
                id: key,
                x: normalized.x,
                y: normalized.y,
                links: new Map(),
            });
        }
        return key;
    };
    const connect = (a, b) => {
        const aId = ensureNode(a);
        const bId = ensureNode(b);
        if (!aId || !bId || aId === bId) return;
        const aNode = graph.get(aId);
        const bNode = graph.get(bId);
        const distance = Math.hypot(aNode.x - bNode.x, aNode.y - bNode.y);
        if (distance <= 0.001) return;
        aNode.links.set(bId, distance);
        bNode.links.set(aId, distance);
    };
    segments.forEach((segment) => {
        const points = [...pointByKey.values()]
            .filter((point) => officeDraftPointOnSegment(point, segment, 2))
            .sort((a, b) => {
                if (safeString(segment.orientation) === 'v' || Math.abs((Number(segment.x2) || 0) - (Number(segment.x1) || 0)) < 0.001) {
                    return a.y - b.y;
                }
                return a.x - b.x;
            });
        for (let index = 0; index < points.length - 1; index += 1) {
            connect(points[index], points[index + 1]);
        }
    });
    return graph;
}

function officeDraftFindHallwayRoute(networkRaw, fromRaw, toRaw, deadlineRaw = 0) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return [fromRaw, toRaw];
    const from = officeDraftNearestHallwayPoint(fromRaw, network);
    const to = officeDraftNearestHallwayPoint(toRaw, network);
    const graph = officeDraftBuildHallwayRouteGraph(network, [from, to]);
    const startId = officeDraftPointKey(from);
    const endId = officeDraftPointKey(to);
    if (!graph.has(startId) || !graph.has(endId)) return [from, to];
    if (startId === endId) return [from];

    const distances = new Map([[startId, 0]]);
    const parent = new Map();
    const unsettled = new Set(graph.keys());
    let guard = 0;
    while (unsettled.size) {
        guard += 1;
        if (guard % 16 === 0 && officeDraftRouteDeadlineExceeded(deadlineRaw)) return [from, to];
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
        if (currentId === endId) break;
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
    if (!distances.has(endId)) return [from, to];
    const route = [];
    let cursor = endId;
    while (cursor) {
        const node = graph.get(cursor);
        if (node) route.push({ x: node.x, y: node.y });
        if (cursor === startId) break;
        cursor = parent.get(cursor);
    }
    route.reverse();
    return officeDraftDedupeRoute(route);
}

function officeDraftDedupeRoute(pointsRaw) {
    const points = [];
    (Array.isArray(pointsRaw) ? pointsRaw : []).forEach((point) => {
        if (!point) return;
        const next = {
            x: Math.round(Number(point.x) || 0),
            y: Math.round(Number(point.y) || 0),
        };
        const prev = points[points.length - 1];
        if (prev && Math.hypot(prev.x - next.x, prev.y - next.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) return;
        points.push(next);
    });
    return points;
}

function officeDraftRouteDistance(pointsRaw) {
    const points = Array.isArray(pointsRaw) ? pointsRaw : [];
    let distance = 0;
    for (let index = 0; index < points.length - 1; index += 1) {
        distance += Math.hypot(
            (Number(points[index + 1]?.x) || 0) - (Number(points[index]?.x) || 0),
            (Number(points[index + 1]?.y) || 0) - (Number(points[index]?.y) || 0),
        );
    }
    return distance;
}

function officeDraftRouteReached(routeRaw, targetRaw) {
    const route = Array.isArray(routeRaw) ? routeRaw : [];
    if (!route.length) return false;
    const last = route[route.length - 1];
    return Math.hypot((Number(last?.x) || 0) - (Number(targetRaw?.x) || 0), (Number(last?.y) || 0) - (Number(targetRaw?.y) || 0)) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON;
}

function officeDraftRouteHasBlockedSegment(routeRaw, spacesRaw, networkRaw = null) {
    const route = Array.isArray(routeRaw) ? routeRaw : [];
    if (route.length <= 1) return false;
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const network = networkRaw || officeDraftAutoHallwayNetwork(spaces);
    return route.some((point, index) => index > 0 && (
        officeDraftRouteSegmentWallViolation(route[index - 1], point, spaces, network)
        || officeDraftRouteSegmentObstacleViolation(route[index - 1], point, spaces, network)
    ));
}


