/** Automatic hallway network construction. */

function officeDraftChooseDoorXForRect(rect, edge) {
    const minX = Math.round(officeClamp(rect.left + 190, rect.left + 92, rect.right - 92));
    const maxX = Math.round(officeClamp(rect.right - 190, rect.left + 92, rect.right - 92));
    const fallbackX = Math.round(officeClamp(rect.centerX, minX, maxX));
    const space = rect?.space;
    if (!space) return fallbackX;
    const obstacles = officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const interiorY = Math.round(edge === 'top' ? bounds.top : bounds.bottom);
    const doorY = Math.round(edge === 'top' ? rect.top : rect.bottom);
    const probe = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const probeCandidates = [
        probe,
        { x: bounds.left, y: bounds.top },
        { x: bounds.right, y: bounds.top },
        { x: bounds.left, y: bounds.bottom },
        { x: bounds.right, y: bounds.bottom },
        { x: bounds.left + ((bounds.right - bounds.left) * 0.28), y: bounds.top + ((bounds.bottom - bounds.top) * 0.5) },
        { x: bounds.left + ((bounds.right - bounds.left) * 0.72), y: bounds.top + ((bounds.bottom - bounds.top) * 0.5) },
    ]
        .map((point) => officeDraftClampWorldPointToWalkable(point, space, obstacles))
        .filter((point, pointIndex, points) => (
            officeDraftPointWalkableInSpace(point, space, obstacles)
            && points.findIndex((entry) => officeDraftPointKey(entry, 8) === officeDraftPointKey(point, 8)) === pointIndex
        ));
    const candidates = [fallbackX, minX, maxX];
    for (let x = minX; x <= maxX; x += OFFICE_DRAFT_HALLWAY_SCAN_STEP) {
        candidates.push(Math.round(x));
    }
    obstacles.forEach((obstacle) => {
        candidates.push(
            Math.round(obstacle.left - OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP),
            Math.round(obstacle.right + OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP),
        );
    });
    let best = { x: fallbackX, score: Number.POSITIVE_INFINITY };
    const seen = new Set();
    candidates.forEach((candidateRaw) => {
        const x = Math.round(officeClamp(candidateRaw, minX, maxX));
        if (seen.has(x)) return;
        seen.add(x);
        const interior = { x, y: interiorY };
        const door = { x, y: doorY };
        const walkable = officeDraftPointWalkableInSpace(interior, space, obstacles);
        const corridorClear = !obstacles.some((obstacle) => officeDraftLineSegmentIntersectsRect(interior, door, obstacle));
        const interiorClear = walkable && officeDraftSegmentClearInSpace(probe, interior, space, obstacles);
        const reachableProbeCount = walkable
            ? probeCandidates.filter((entry) => officeDraftSegmentClearInSpace(entry, interior, space, obstacles)).length
            : 0;
        const blockedLaneCount = obstacles.filter((obstacle) => (
            x >= obstacle.left - 10
            && x <= obstacle.right + 10
            && (edge === 'top'
                ? obstacle.top > interiorY && obstacle.top < bounds.bottom
                : obstacle.bottom < interiorY && obstacle.bottom > bounds.top)
        )).length;
        const clearance = officeDraftPointObstacleClearance(interior, obstacles);
        const edgePenalty = Math.min(Math.abs(x - minX), Math.abs(maxX - x)) < 56 ? 180 : 0;
        const score = (walkable ? 0 : 100000)
            + (corridorClear ? 0 : 50000)
            + (interiorClear ? 0 : 1800)
            + (blockedLaneCount * 4200)
            + ((probeCandidates.length - reachableProbeCount) * 520)
            + (Math.max(0, 132 - clearance) * 42)
            + Math.abs(x - rect.centerX)
            + edgePenalty
            - Math.min(260, clearance);
        if (score < best.score) {
            best = { x, score };
        }
    });
    return best.x;
}

function officeDraftAddNetworkNode(nodes, point, kind = 'joint', id = '') {
    const x = Math.round(Number(point?.x) || 0);
    const y = Math.round(Number(point?.y) || 0);
    const key = `${x},${y}`;
    if (nodes.has(key)) return nodes.get(key);
    const node = { id: id || `node-${nodes.size + 1}`, x, y, kind };
    nodes.set(key, node);
    return node;
}

function officeDraftSegmentPath(segments) {
    return (Array.isArray(segments) ? segments : [])
        .filter((segment) => segment && Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1) > 2)
        .map((segment) => `M ${Math.round(segment.x1)} ${Math.round(segment.y1)} L ${Math.round(segment.x2)} ${Math.round(segment.y2)}`)
        .join(' ');
}

function officeDraftHallwayNetworkSignature(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw.filter(Boolean) : [];
    return spaces
        .map((space) => {
            const rect = officeDraftSpaceRect(space);
            const assetSignature = (Array.isArray(space?.assets) ? space.assets : [])
                .filter((asset) => officeDraftAssetBlocksNavigation(asset))
                .map((asset) => [
                    safeString(asset?.id),
                    safeString(asset?.type),
                    Math.round(Number(asset?.x) || 0),
                    Math.round(Number(asset?.y) || 0),
                    officeDraftClampAssetScale(asset?.scale),
                    officeDraftNormalizeRotation(asset?.rotation),
                ].join(','))
                .join(';');
            return [
                safeString(rect.id),
                Math.round(rect.left),
                Math.round(rect.top),
                Math.round(rect.right),
                Math.round(rect.bottom),
                assetSignature,
            ].join(':');
        })
        .join('|');
}

function officeDraftAutoHallwayNetwork(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw.filter(Boolean) : [];
    const cacheState = officeDraftMapState && spacesRaw === officeDraftMapState.spaces
        ? officeDraftMapState
        : null;
    const signature = cacheState ? officeDraftHallwayNetworkSignature(spaces) : '';
    if (
        cacheState
        && cacheState.hallwayNetworkCache
        && cacheState.hallwayNetworkCache.signature === signature
        && cacheState.hallwayNetworkCache.network
    ) {
        return cacheState.hallwayNetworkCache.network;
    }
    const rects = spaces.map(officeDraftSpaceRect).filter((rect) => rect.id);
    const rows = officeDraftClusterSpaceRows(spaces);
    const lanes = [];
    if (rows.length >= 2) {
        for (let index = 0; index < rows.length - 1; index += 1) {
            const current = rows[index];
            const next = rows[index + 1];
            const gap = next.top - current.bottom;
            const laneY = Math.round(gap > 140
                ? current.bottom + (gap / 2)
                : current.centerY + ((next.centerY - current.centerY) / 2));
            lanes.push({
                id: `hall-row-${index}`,
                y: Math.round(officeClamp(laneY, 260, OFFICE_DRAFT_MAP_SIZE - 260)),
                minX: Math.round(Math.max(220, Math.min(current.left, next.left) - 360)),
                maxX: Math.round(Math.min(OFFICE_DRAFT_MAP_SIZE - 220, Math.max(current.right, next.right) + 360)),
                doorXs: [],
            });
        }
    }
    if (!lanes.length && rects.length) {
        const bounds = rects.reduce((acc, rect) => ({
            left: Math.min(acc.left, rect.left),
            right: Math.max(acc.right, rect.right),
            top: Math.min(acc.top, rect.top),
            bottom: Math.max(acc.bottom, rect.bottom),
        }), {
            left: Number.POSITIVE_INFINITY,
            right: Number.NEGATIVE_INFINITY,
            top: Number.POSITIVE_INFINITY,
            bottom: Number.NEGATIVE_INFINITY,
        });
        lanes.push({
            id: 'hall-row-0',
            y: Math.round(officeClamp(bounds.bottom + 240, 260, OFFICE_DRAFT_MAP_SIZE - 260)),
            minX: Math.round(Math.max(220, bounds.left - 360)),
            maxX: Math.round(Math.min(OFFICE_DRAFT_MAP_SIZE - 220, bounds.right + 360)),
            doorXs: [],
        });
    }

    const laneForRect = (rect) => {
        if (!lanes.length) return null;
        const candidates = lanes
            .map((lane) => {
                const outside = lane.y <= rect.top - 64 || lane.y >= rect.bottom + 64;
                return {
                    lane,
                    outside,
                    distance: Math.min(Math.abs(lane.y - rect.top), Math.abs(lane.y - rect.bottom)),
                };
            })
            .sort((a, b) => {
                if (a.outside !== b.outside) return a.outside ? -1 : 1;
                return a.distance - b.distance;
            });
        return candidates[0]?.lane || lanes[0];
    };

    const doors = new Map();
    rects.forEach((rect) => {
        const lane = laneForRect(rect);
        if (!lane) return;
        const edge = lane.y < rect.centerY ? 'top' : 'bottom';
        const doorX = officeDraftChooseDoorXForRect(rect, edge);
        const doorY = Math.round(edge === 'top' ? rect.top : rect.bottom);
        const normalY = edge === 'top' ? -1 : 1;
        const outsideY = Math.round(lane.y);
        const door = {
            edge,
            localX: Math.round(doorX - rect.x),
            localY: Math.round(doorY - rect.y),
            worldX: doorX,
            worldY: doorY,
            outsideX: doorX,
            outsideY,
            normalX: 0,
            normalY,
            laneId: lane.id,
            spaceId: rect.id,
        };
        doors.set(rect.id, door);
        lane.minX = Math.min(lane.minX, doorX - 220);
        lane.maxX = Math.max(lane.maxX, doorX + 220);
        lane.doorXs.push(doorX);
    });

    const connectors = [];
    for (let index = 0; index < lanes.length - 1; index += 1) {
        const laneA = lanes[index];
        const laneB = lanes[index + 1];
        const x = officeDraftChooseVerticalConnectorX(laneA, laneB, rects);
        connectors.push({
            id: `hall-connector-${index}`,
            x,
            y1: Math.min(laneA.y, laneB.y),
            y2: Math.max(laneA.y, laneB.y),
        });
        laneA.minX = Math.min(laneA.minX, x - 180);
        laneA.maxX = Math.max(laneA.maxX, x + 180);
        laneB.minX = Math.min(laneB.minX, x - 180);
        laneB.maxX = Math.max(laneB.maxX, x + 180);
    }

    const segments = [];
    const nodes = new Map();
    lanes.forEach((lane) => {
        const x1 = Math.round(officeClamp(lane.minX, 180, OFFICE_DRAFT_MAP_SIZE - 180));
        const x2 = Math.round(officeClamp(lane.maxX, 180, OFFICE_DRAFT_MAP_SIZE - 180));
        const segment = { kind: 'trunk', orientation: 'h', x1, y1: lane.y, x2, y2: lane.y, laneId: lane.id };
        segments.push(segment);
        officeDraftAddNetworkNode(nodes, { x: x1, y: lane.y }, 'end');
        officeDraftAddNetworkNode(nodes, { x: x2, y: lane.y }, 'end');
    });
    connectors.forEach((connector) => {
        const segment = {
            kind: 'connector',
            orientation: 'v',
            x1: connector.x,
            y1: connector.y1,
            x2: connector.x,
            y2: connector.y2,
            connectorId: connector.id,
        };
        segments.push(segment);
        officeDraftAddNetworkNode(nodes, { x: connector.x, y: connector.y1 }, 'junction', `${connector.id}-a`);
        officeDraftAddNetworkNode(nodes, { x: connector.x, y: connector.y2 }, 'junction', `${connector.id}-b`);
    });
    doors.forEach((door) => {
        segments.push({
            kind: 'door',
            orientation: door.normalY ? 'v' : 'h',
            x1: door.worldX,
            y1: door.worldY,
            x2: door.outsideX,
            y2: door.outsideY,
            spaceId: door.spaceId,
        });
        officeDraftAddNetworkNode(nodes, { x: door.outsideX, y: door.outsideY }, 'door', `${door.spaceId}-hall`);
    });

    const network = {
        lanes,
        connectors,
        doors,
        segments,
        nodes: [...nodes.values()],
    };
    if (cacheState) {
        cacheState.hallwayNetworkCache = { signature, network };
    }
    return network;
}


