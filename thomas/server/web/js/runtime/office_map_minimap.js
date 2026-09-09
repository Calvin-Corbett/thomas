/** Map plane, diagnostics, and minimap rendering. */

function officeDraftMapPlane() {
    return officeScene?.querySelector('[data-office-map-plane="1"]') || null;
}

function officeDraftDebugSnapshot() {
    const state = typeof officeEnsureDraftMapState === 'function' ? officeEnsureDraftMapState() : null;
    const plane = officeDraftMapPlane();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    const network = state ? officeDraftAutoHallwayNetwork(spaces) : null;
    const agentNodes = Array.from(plane?.querySelectorAll('[data-office-draft-agent-id]') || []);
    const layerNodes = Array.from(plane?.querySelectorAll('[data-office-draft-agent-layer]') || []);
    const animationStates = [...new Set(agentNodes.map((node) => safeString(node?.dataset?.officeAgentAnimation)).filter(Boolean))].sort();
    const draftRoutes = (officeState?.agents || []).map((agent) => {
        const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
        const route = motion && Array.isArray(motion.route)
            ? [
                { x: Math.round(Number(motion.x) || 0), y: Math.round(Number(motion.y) || 0) },
                ...motion.route.slice(Math.max(0, Number(motion.routeIndex) || 0)).map((point) => ({
                    x: Math.round(Number(point?.x) || 0),
                    y: Math.round(Number(point?.y) || 0),
                })),
            ]
            : [];
        return {
            agentId: safeString(agent?.id),
            points: route,
        };
    }).filter((entry) => entry.points.length > 1);
    const draftRouteWallViolations = [];
    const draftRouteObstacleViolations = [];
    let draftRouteSegmentsChecked = 0;
    for (const entry of draftRoutes) {
        for (let index = 0; index < entry.points.length - 1; index += 1) {
            if (draftRouteSegmentsChecked >= OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT) break;
            draftRouteSegmentsChecked += 1;
            const violation = officeDraftRouteSegmentWallViolation(entry.points[index], entry.points[index + 1], spaces, network);
            if (violation) {
                draftRouteWallViolations.push({
                    agentId: entry.agentId,
                    segmentIndex: index,
                    ...violation,
                });
            }
            const obstacleViolation = officeDraftRouteSegmentObstacleViolation(entry.points[index], entry.points[index + 1], spaces, network);
            if (obstacleViolation) {
                draftRouteObstacleViolations.push({
                    agentId: entry.agentId,
                    segmentIndex: index,
                    ...obstacleViolation,
                });
            }
        }
        if (draftRouteSegmentsChecked >= OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT) break;
    }
    const navStats = (officeState?.agents || []).map((agent) => officeDraftAgentNavStats(agent)).filter(Boolean);
    const isVisible = (el) => {
        if (!(el instanceof HTMLElement)) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity || 1) > 0.02
            && rect.width > 2
            && rect.height > 2
            && rect.right > 0
            && rect.bottom > 0
            && rect.left < window.innerWidth
            && rect.top < window.innerHeight;
    };
    return {
        schemaVersion: OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION,
        mapSize: OFFICE_DRAFT_MAP_SIZE,
        zoom: Math.round((Number(state?.zoom) || 0) * 1000) / 1000,
        panX: Math.round(Number(state?.panX) || 0),
        panY: Math.round(Number(state?.panY) || 0),
        lastInputMode: safeString(state?.lastInputMode),
        lastWheelDelta: Number(state?.lastWheelDelta) || 0,
        lastZoomDelta: Number(state?.lastZoomDelta) || 0,
        lastPanDeltaScreen: Number(state?.lastPanDeltaScreen) || 0,
        selectedSpaceId: safeString(state?.selectedSpaceId),
        focusSpaceId: state && typeof officeDraftInitialFocusSpace === 'function'
            ? safeString(officeDraftInitialFocusSpace(state)?.id)
            : '',
        spaces: spaces.length,
        roomAssets: spaces.reduce((count, space) => count + (Array.isArray(space?.assets) ? space.assets.length : 0), 0),
        catalogAssets: Object.keys(OFFICE_DRAFT_ASSET_LIBRARY || {}).length,
        floorPalettes: Object.keys(OFFICE_DRAFT_ROOM_FLOOR_PALETTES || {}).length,
        hallwaySegments: Number(network?.segments?.length) || 0,
        hallwayDoors: Number(network?.doors?.size) || 0,
        hallwayNodes: Number(network?.nodes?.length) || 0,
        hallwayPaths: plane?.querySelectorAll('[data-office-draft-hallway-path="floor"]').length || 0,
        hallwayPaintLayers: plane?.querySelectorAll('[data-office-draft-hallway-path]').length || 0,
        agentCount: officeState?.agents?.length || 0,
        agentNodes: agentNodes.length,
        visibleAgentNodes: agentNodes.filter(isVisible).length,
        draftAgentRoutes: draftRoutes.length,
        draftAgentRoutePoints: draftRoutes.reduce((count, route) => count + route.points.length, 0),
        draftAgentRouteSegmentsChecked: draftRouteSegmentsChecked,
        draftAgentWallViolations: draftRouteWallViolations.length,
        draftAgentObstacleViolations: draftRouteObstacleViolations.length,
        draftAgentNavVersion: OFFICE_DRAFT_AGENT_NAV_VERSION,
        draftAgentRouteResets: navStats.reduce((sum, stats) => sum + (Number(stats.routeResets) || 0), 0),
        draftAgentObstacleDetours: navStats.reduce((sum, stats) => sum + (Number(stats.obstacleDetours) || 0), 0),
        draftAgentStuckReplans: navStats.reduce((sum, stats) => sum + (Number(stats.stuckReplans) || 0), 0),
        draftAgentHardClamps: navStats.reduce((sum, stats) => sum + (Number(stats.hardClamps) || 0), 0),
        draftAgentWanderTargets: navStats.reduce((sum, stats) => sum + (Number(stats.wanderTargets) || 0), 0),
        draftAgentMaxJump: navStats.reduce((max, stats) => Math.max(max, Number(stats.maxJump) || 0), 0),
        draftAgentAnimationsAvailable: OFFICE_DRAFT_AGENT_ANIMATIONS.length,
        draftAgentAnimationStates: animationStates,
        draftAgentClickableNodes: agentNodes.filter((node) => node instanceof HTMLElement && window.getComputedStyle(node).pointerEvents !== 'none').length,
        draftAgentDragging: Boolean(state?.agentDragActive),
        draftAgentDragRenders: Number(state?.agentLayerRenderSources?.['agent-drag']) || 0,
        globalAgentLayers: layerNodes.filter((node) => safeString(node?.dataset?.officeDraftAgentLayer) === 'global').length,
        roomAgentLayers: layerNodes.filter((node) => safeString(node?.dataset?.officeDraftAgentLayer) !== 'global').length,
        minimapVisible: Boolean(officeMinimap instanceof HTMLElement && officeMinimap.style.display !== 'none'),
        minimapSize: state?.minimapSize || 0,
    };
}

function officeDraftDrawMiniHallwayNetwork(ctx, network, scale) {
    const segments = Array.isArray(network?.segments) ? network.segments : [];
    if (!segments.length) return;
    const drawSegments = (strokeStyle, lineWidth) => {
        ctx.beginPath();
        segments.forEach((segment) => {
            ctx.moveTo(segment.x1 * scale, segment.y1 * scale);
            ctx.lineTo(segment.x2 * scale, segment.y2 * scale);
        });
        ctx.strokeStyle = strokeStyle;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
    };
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    drawSegments('rgba(80, 96, 116, 0.92)', Math.max(3, OFFICE_DRAFT_HALLWAY_OUTER_WIDTH * scale));
    drawSegments('rgba(174, 187, 202, 0.98)', Math.max(2, OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH * scale));
    drawSegments('rgba(236, 245, 255, 0.32)', Math.max(1, 10 * scale));
    (Array.isArray(network?.nodes) ? network.nodes : []).forEach((node) => {
        if (safeString(node?.kind) !== 'junction') return;
        ctx.fillStyle = 'rgba(165, 177, 192, 0.96)';
        ctx.strokeStyle = 'rgba(39, 53, 74, 0.78)';
        ctx.lineWidth = Math.max(1, 10 * scale);
        ctx.beginPath();
        ctx.arc(node.x * scale, node.y * scale, Math.max(1.6, 46 * scale), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
    });
    ctx.restore();
}

function officeRenderDraftMapMinimap() {
    if (!(officeMinimapCanvas instanceof HTMLCanvasElement)) return;
    const state = officeEnsureDraftMapState();
    if (state.minimapMinimized) return;
    const size = state.minimapSize;
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const targetSize = Math.round(size * dpr);
    if (officeMinimapCanvas.width !== targetSize || officeMinimapCanvas.height !== targetSize) {
        officeMinimapCanvas.width = targetSize;
        officeMinimapCanvas.height = targetSize;
    }
    const ctx = officeMinimapCanvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, targetSize, targetSize);
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#09111d';
    ctx.fillRect(0, 0, size, size);

    const scale = size / OFFICE_DRAFT_MAP_SIZE;
    const minor = Math.max(4, Math.round(OFFICE_DRAFT_MAP_MINOR_GRID * scale));
    const major = Math.max(20, Math.round(OFFICE_DRAFT_MAP_MAJOR_GRID * scale));

    ctx.strokeStyle = 'rgba(92, 116, 158, 0.16)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= size; x += minor) {
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, size);
        ctx.stroke();
    }
    for (let y = 0; y <= size; y += minor) {
        ctx.beginPath();
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(size, y + 0.5);
        ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(182, 217, 255, 0.28)';
    for (let x = 0; x <= size; x += major) {
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, size);
        ctx.stroke();
    }
    for (let y = 0; y <= size; y += major) {
        ctx.beginPath();
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(size, y + 0.5);
        ctx.stroke();
    }

    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    const byId = new Map(spaces.map((space) => [safeString(space?.id), space]));
    const network = officeDraftAutoHallwayNetwork(spaces);
    officeDraftDrawMiniHallwayNetwork(ctx, network, scale);

    spaces.forEach((space) => {
        const palette = officeDraftRoomPalette(space?.floorPalette);
        const x = (Number(space?.x) || 0) * scale;
        const y = (Number(space?.y) || 0) * scale;
        const width = Math.max(4, (Number(space?.width) || 0) * scale);
        const height = Math.max(4, (Number(space?.height) || 0) * scale);
        ctx.fillStyle = safeString(space?.id) === safeString(state.selectedSpaceId)
            ? 'rgba(92, 158, 255, 0.42)'
            : 'rgba(221, 231, 244, 0.22)';
        ctx.strokeStyle = palette.floorBorder || 'rgba(236, 245, 255, 0.28)';
        ctx.lineWidth = safeString(space?.id) === safeString(state.selectedSpaceId) ? 2 : 1;
        ctx.beginPath();
        ctx.roundRect(x, y, width, height, 4);
        ctx.fill();
        ctx.stroke();
    });

    const assignments = officeDraftAgentAssignmentMap(state);
    assignments.forEach((agents, spaceId) => {
        const space = byId.get(spaceId);
        if (!space || !Array.isArray(agents)) return;
        agents.slice(0, 18).forEach((agent, index) => {
            const placement = officeDraftAgentPlacement(space, agent, index, agents.length, performance.now());
            const worldX = ((Number(space.x) || 0) + placement.x) * scale;
            const worldY = ((Number(space.y) || 0) + placement.y) * scale;
            ctx.fillStyle = /^#[0-9a-f]{6}$/i.test(safeString(agent?.color)) ? safeString(agent.color) : '#9ad8ff';
            ctx.strokeStyle = 'rgba(6, 10, 18, 0.82)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(worldX, worldY, Math.max(2, 4 * scale), 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        });
    });

    const viewport = officeDraftMapViewportWorldRect();
    const viewX = viewport.x * scale;
    const viewY = viewport.y * scale;
    const viewW = Math.max(6, viewport.width * scale);
    const viewH = Math.max(6, viewport.height * scale);
    ctx.fillStyle = 'rgba(236, 246, 255, 0.08)';
    ctx.strokeStyle = 'rgba(244, 250, 255, 0.92)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.rect(viewX, viewY, Math.min(size - viewX, viewW), Math.min(size - viewY, viewH));
    ctx.fill();
    ctx.stroke();
}

function officeDraftOverviewMode(state) {
    if (!state || state.editorOpen) return false;
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    return zoom <= 0.32;
}


