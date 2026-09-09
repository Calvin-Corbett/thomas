/** Room doors, corridors, and connector rendering. */

function officeDraftWorldPointInSpace(point, space) {
    const rect = officeDraftSpaceRect(space);
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function officeDraftRouteSegmentWallViolation(a, b, spacesRaw, networkRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const network = networkRaw || officeDraftAutoHallwayNetwork(spaces);
    const segment = { x1: a?.x, y1: a?.y, x2: b?.x, y2: b?.y };
    const onHall = (point) => officeDraftNearestHallwayPoint(point, network).distance <= (OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH / 2) + 8;
    if (onHall(a) && onHall(b)) return null;
    const sharedSpace = spaces.find((space) => officeDraftWorldPointInSpace(a, space) && officeDraftWorldPointInSpace(b, space));
    if (sharedSpace) return null;
    const touchesDoor = spaces.some((space) => {
        const door = officeDraftSpaceDoorPoint(space, network);
        const doorSegment = { x1: door.worldX, y1: door.worldY, x2: door.outsideX, y2: door.outsideY };
        return officeDraftPointOnSegment(a, doorSegment, 4) && officeDraftPointOnSegment(b, doorSegment, 4);
    });
    if (touchesDoor) return null;
    const crossed = spaces.find((space) => officeDraftSegmentIntersectsRect(segment, officeDraftSpaceRect(space), 12));
    return crossed ? { spaceId: safeString(crossed.id), from: a, to: b } : null;
}

function officeDraftRouteSegmentObstacleViolation(a, b, spacesRaw, networkRaw = null) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const network = networkRaw || officeDraftAutoHallwayNetwork(spaces);
    if (officeDraftStepOnHallway(a, b, network)) return null;
    const sharedSpace = spaces.find((space) => officeDraftWorldPointInSpace(a, space) && officeDraftWorldPointInSpace(b, space));
    if (!sharedSpace) return null;
    const obstacles = officeDraftObstacleRects(sharedSpace);
    if (!obstacles.length) return null;
    const obstacle = obstacles.find((rect) => officeDraftLineSegmentIntersectsRect(a, b, rect));
    if (obstacle) {
        return {
            spaceId: safeString(sharedSpace.id),
            obstacleAssetId: safeString(obstacle.assetId),
            obstacleType: safeString(obstacle.type),
            from: a,
            to: b,
        };
    }
    return null;
}

function officeDraftSpaceDoorPoint(space, networkRaw = null) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeDraftMapState?.spaces || []);
    const spaceId = safeString(space?.id);
    const networkDoor = network?.doors instanceof Map ? network.doors.get(spaceId) : null;
    if (networkDoor) return { ...networkDoor };
    const rect = officeDraftSpaceRect(space);
    const center = {
        x: rect.centerX,
        y: rect.centerY,
    };
    const mapCenter = OFFICE_DRAFT_MAP_SIZE / 2;
    const dx = center.x - mapCenter;
    const dy = center.y - mapCenter;
    let edge = 'bottom';
    if (Math.abs(dx) > Math.abs(dy)) {
        edge = dx < 0 ? 'right' : 'left';
    } else {
        edge = dy < 0 ? 'bottom' : 'top';
    }
    const local = {
        x: rect.width / 2,
        y: rect.height / 2,
    };
    if (edge === 'left') local.x = 0;
    if (edge === 'right') local.x = rect.width;
    if (edge === 'top') local.y = 0;
    if (edge === 'bottom') local.y = rect.height;
    const normal = {
        x: edge === 'left' ? -1 : (edge === 'right' ? 1 : 0),
        y: edge === 'top' ? -1 : (edge === 'bottom' ? 1 : 0),
    };
    return {
        edge,
        localX: Math.round(local.x),
        localY: Math.round(local.y),
        worldX: Math.round(rect.x + local.x),
        worldY: Math.round(rect.y + local.y),
        outsideX: Math.round(rect.x + local.x + (normal.x * 260)),
        outsideY: Math.round(rect.y + local.y + (normal.y * 260)),
        normalX: normal.x,
        normalY: normal.y,
    };
}

function officeDraftSpaceDoorInteriorPoint(space, networkRaw = null) {
    const door = officeDraftSpaceDoorPoint(space, networkRaw);
    return officeDraftClampWorldPointToWalkable({
        x: Number(door.worldX) - ((Number(door.normalX) || 0) * OFFICE_DRAFT_AGENT_ROOM_MARGIN),
        y: Number(door.worldY) - ((Number(door.normalY) || 0) * OFFICE_DRAFT_AGENT_ROOM_MARGIN),
    }, space);
}

function officeDraftCorridorPath(from, to) {
    const network = officeDraftAutoHallwayNetwork(officeDraftMapState?.spaces || [from, to]);
    const a = officeDraftSpaceDoorPoint(from, network);
    const b = officeDraftSpaceDoorPoint(to, network);
    const midX = Math.round((a.outsideX + b.outsideX) / 2);
    const midY = Math.round((a.outsideY + b.outsideY) / 2);
    const horizontalBias = Math.abs(a.outsideX - b.outsideX) >= Math.abs(a.outsideY - b.outsideY);
    const bendA = horizontalBias ? `${midX} ${a.outsideY}` : `${a.outsideX} ${midY}`;
    const bendB = horizontalBias ? `${midX} ${b.outsideY}` : `${b.outsideX} ${midY}`;
    return {
        d: `M ${a.worldX} ${a.worldY} L ${a.outsideX} ${a.outsideY} L ${bendA} L ${bendB} L ${b.outsideX} ${b.outsideY} L ${b.worldX} ${b.worldY}`,
        fromDoor: a,
        toDoor: b,
    };
}

function officeDraftConnectorPairs(spaces) {
    const byId = new Map((Array.isArray(spaces) ? spaces : []).map((space) => [safeString(space?.id), space]));
    const defaultPairs = [
        ['planning-hub', 'software-lab'],
        ['software-lab', 'research-bay'],
        ['design-loft', 'content-studio'],
        ['content-studio', 'ops-command'],
        ['ops-command', 'support-desk'],
        ['planning-hub', 'design-loft'],
        ['software-lab', 'content-studio'],
        ['research-bay', 'ops-command'],
        ['cafeteria', 'lounge'],
        ['lounge', 'focus-pods'],
        ['focus-pods', 'lobby'],
        ['content-studio', 'lounge'],
        ['support-desk', 'focus-pods'],
    ].filter(([a, b]) => byId.has(a) && byId.has(b));
    const pairs = [...defaultPairs];
    const connected = new Set(defaultPairs.flat());
    const lobby = byId.get('lobby') || spaces.find((space) => officeDraftNormalizeRoomId(space?.roomId, space?.id) === 'room-lobby');
    if (lobby) {
        spaces.forEach((space) => {
            const id = safeString(space?.id);
            if (!id || id === safeString(lobby.id) || connected.has(id)) return;
            pairs.push([id, safeString(lobby.id)]);
        });
    }
    return pairs;
}

function officeRenderDraftRoomConnectors(plane, state) {
    if (!(plane instanceof HTMLElement) || !state) return;
    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    if (!spaces.length) return;
    const network = officeDraftAutoHallwayNetwork(spaces);
    const hallwayPath = officeDraftSegmentPath(network.segments);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('data-office-draft-connectors', '1');
    svg.setAttribute('data-office-draft-hallways', '1');
    svg.setAttribute('width', String(OFFICE_DRAFT_MAP_SIZE));
    svg.setAttribute('height', String(OFFICE_DRAFT_MAP_SIZE));
    svg.style.position = 'absolute';
    svg.style.left = '0';
    svg.style.top = '0';
    svg.style.width = `${OFFICE_DRAFT_MAP_SIZE}px`;
    svg.style.height = `${OFFICE_DRAFT_MAP_SIZE}px`;
    svg.style.pointerEvents = 'none';
    svg.style.zIndex = '0';
    if (hallwayPath) {
        const shadow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        shadow.setAttribute('data-office-draft-hallway-path', 'shadow');
        shadow.setAttribute('d', hallwayPath);
        shadow.setAttribute('fill', 'none');
        shadow.setAttribute('stroke', 'rgba(21, 31, 45, 0.5)');
        shadow.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_OUTER_WIDTH + 26));
        shadow.setAttribute('stroke-linecap', 'round');
        shadow.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(shadow);
        const outer = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        outer.setAttribute('data-office-draft-hallway-path', 'outer');
        outer.setAttribute('d', hallwayPath);
        outer.setAttribute('fill', 'none');
        outer.setAttribute('stroke', 'rgba(111, 130, 153, 0.96)');
        outer.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_OUTER_WIDTH));
        outer.setAttribute('stroke-linecap', 'round');
        outer.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(outer);
        const curb = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        curb.setAttribute('data-office-draft-hallway-path', 'curb');
        curb.setAttribute('d', hallwayPath);
        curb.setAttribute('fill', 'none');
        curb.setAttribute('stroke', 'rgba(226, 236, 246, 0.34)');
        curb.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_OUTER_WIDTH - 16));
        curb.setAttribute('stroke-linecap', 'round');
        curb.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(curb);
        const floor = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        floor.setAttribute('data-office-draft-hallway-path', 'floor');
        floor.setAttribute('d', hallwayPath);
        floor.setAttribute('fill', 'none');
        floor.setAttribute('stroke', 'rgba(190, 203, 216, 0.98)');
        floor.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH));
        floor.setAttribute('stroke-linecap', 'round');
        floor.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(floor);
        const lane = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        lane.setAttribute('data-office-draft-hallway-path', 'lane');
        lane.setAttribute('d', hallwayPath);
        lane.setAttribute('fill', 'none');
        lane.setAttribute('stroke', 'rgba(222, 232, 242, 0.22)');
        lane.setAttribute('stroke-width', String(Math.max(34, OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH - 48)));
        lane.setAttribute('stroke-linecap', 'round');
        lane.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(lane);
        const tile = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        tile.setAttribute('data-office-draft-hallway-path', 'tile');
        tile.setAttribute('d', hallwayPath);
        tile.setAttribute('fill', 'none');
        tile.setAttribute('stroke', 'rgba(255, 255, 255, 0.22)');
        tile.setAttribute('stroke-width', '34');
        tile.setAttribute('stroke-linecap', 'round');
        tile.setAttribute('stroke-linejoin', 'round');
        tile.setAttribute('stroke-dasharray', '18 52');
        svg.appendChild(tile);
        const centerLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        centerLine.setAttribute('data-office-draft-hallway-path', 'center');
        centerLine.setAttribute('d', hallwayPath);
        centerLine.setAttribute('fill', 'none');
        centerLine.setAttribute('stroke', 'rgba(248, 252, 255, 0.34)');
        centerLine.setAttribute('stroke-width', '8');
        centerLine.setAttribute('stroke-linecap', 'round');
        centerLine.setAttribute('stroke-linejoin', 'round');
        centerLine.setAttribute('stroke-dasharray', '64 54');
        svg.appendChild(centerLine);
    }
    network.nodes.forEach((node) => {
        if (safeString(node.kind) !== 'junction') return;
        const joint = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        joint.setAttribute('data-office-draft-hallway-node', safeString(node.kind));
        joint.setAttribute('cx', String(node.x));
        joint.setAttribute('cy', String(node.y));
        joint.setAttribute('r', '74');
        joint.setAttribute('fill', 'rgba(178, 190, 204, 0.98)');
        joint.setAttribute('stroke', 'rgba(80, 96, 116, 0.72)');
        joint.setAttribute('stroke-width', '10');
        svg.appendChild(joint);
    });
    network.doors.forEach((door) => {
        const pad = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        pad.setAttribute('data-office-draft-door-pad', safeString(door.spaceId));
        pad.setAttribute('x', String(door.worldX - 84));
        pad.setAttribute('y', String(door.worldY - 46));
        pad.setAttribute('width', '168');
        pad.setAttribute('height', '92');
        pad.setAttribute('rx', '28');
        pad.setAttribute('fill', 'rgba(238, 246, 255, 0.24)');
        pad.setAttribute('stroke', 'rgba(249, 252, 255, 0.42)');
        pad.setAttribute('stroke-width', '4');
        svg.appendChild(pad);
    });
    plane.appendChild(svg);
}


