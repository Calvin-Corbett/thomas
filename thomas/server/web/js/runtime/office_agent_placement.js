/** World and walk placement for office agents. */

function officeDraftAgentWorldPlacement(space, agent, index, total, now = performance.now(), targetAsset = null) {
    if (!space || !agent) return null;
    const currentNow = Number(now) || performance.now();
    const state = officeEnsureDraftMapState();
    const skipRoutePlanning = state?.agentLayerSkipRoutePlanning === true;
    const cachedMotion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (skipRoutePlanning && cachedMotion && Number(cachedMotion.navVersion) === OFFICE_DRAFT_AGENT_NAV_VERSION
        && Number.isFinite(Number(cachedMotion.x)) && Number.isFinite(Number(cachedMotion.y))) {
        const cachedRouteActive = Array.isArray(cachedMotion.route)
            && cachedMotion.route.length > 0
            && Number(cachedMotion.routeIndex) < cachedMotion.route.length;
        if (cachedRouteActive) {
            officeDraftAdvanceAgentMotion(agent, cachedMotion, currentNow);
        } else {
            officeDraftAdvanceAgentCheapMotion(agent, cachedMotion, currentNow);
        }
        const distanceToTarget = Math.hypot(
            (Number(cachedMotion.x) || 0) - (Number(cachedMotion.targetX) || Number(cachedMotion.x) || 0),
            (Number(cachedMotion.y) || 0) - (Number(cachedMotion.targetY) || Number(cachedMotion.y) || 0),
        );
        const routeStillActive = Array.isArray(cachedMotion.route)
            && cachedMotion.route.length > 0
            && Number(cachedMotion.routeIndex) < cachedMotion.route.length;
        if (!routeStillActive && (cachedMotion.needsReplan === true || distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON)) {
            state.agentRoutePlanDeferred = true;
        }
        return {
            x: Math.round(Number(cachedMotion.x) || 0),
            y: Math.round(Number(cachedMotion.y) || 0),
            routeActive: routeStillActive
                || cachedMotion.needsReplan === true
                || distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON,
        };
    }
    if (skipRoutePlanning) {
        const deferredTarget = officeDraftCheapAgentTargetWorldPoint(space, agent, index, total);
        const cachedPoint = cachedMotion
            && Number.isFinite(Number(cachedMotion.x))
            && Number.isFinite(Number(cachedMotion.y))
            ? { x: Math.round(Number(cachedMotion.x) || 0), y: Math.round(Number(cachedMotion.y) || 0) }
            : null;
        const startWorld = cachedPoint || officeDraftInitialMotionWorldPoint(agent, space, deferredTarget, index, total);
        agent.draftMotion = {
            navVersion: OFFICE_DRAFT_AGENT_NAV_VERSION,
            x: startWorld.x,
            y: startWorld.y,
            targetX: deferredTarget.x,
            targetY: deferredTarget.y,
            targetSignature: `deferred:${safeString(space?.id)}:${deferredTarget.x},${deferredTarget.y}`,
            route: [],
            routeIndex: 0,
            lastAt: currentNow,
            lastProgressAt: currentNow,
            routeStartedAt: 0,
            arrivedAt: currentNow,
            dragging: false,
            needsReplan: true,
            lastStepDistance: 0,
        };
        state.agentRoutePlanDeferred = true;
        officeDraftAgentNavStats(agent);
        return {
            x: startWorld.x,
            y: startWorld.y,
            routeActive: Math.hypot(startWorld.x - deferredTarget.x, startWorld.y - deferredTarget.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON,
        };
    }
    const network = officeDraftAutoHallwayNetwork(state.spaces);
    const pinned = officeDraftAgentPinnedTargetWorld(space, agent);
    let targetWorld = officeDraftClampWorldPointToWalkable(pinned || officeDraftAgentTargetWorldPoint(space, agent, index, total, targetAsset), space);
    let targetSignature = officeDraftAgentTargetSignature(space, agent, targetWorld, targetAsset);
    const motion = officeDraftEnsureAgentMotion(agent, space, index, total, targetAsset, currentNow);
    if (!pinned && officeDraftTargetBlocked(motion, targetSignature, currentNow)) {
        targetAsset = null;
        targetWorld = officeDraftFallbackAgentTargetWorldPoint(space, agent, index, total);
        targetSignature = `${officeDraftAgentTargetSignature(space, agent, targetWorld, null)}|fallback`;
    }
    if (motion.dragging) {
        return { x: Math.round(motion.x), y: Math.round(motion.y), routeActive: false };
    }
    if ((Number(motion.routeRetryAfter) || 0) > 0
        && (Number(motion.routeRetryAfter) || 0) <= currentNow
        && (!Array.isArray(motion.route) || motion.route.length === 0)
        && Math.hypot((Number(motion.x) || targetWorld.x) - targetWorld.x, (Number(motion.y) || targetWorld.y) - targetWorld.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        motion.needsReplan = true;
        motion.routeRetryAfter = 0;
    }
    if ((Number(agent.draftPausedUntil) || 0) <= currentNow && (motion.needsReplan || safeString(motion.targetSignature) !== targetSignature)) {
        if (!officeDraftConsumeRoutePlanBudget(state)) {
            motion.needsReplan = true;
            motion.lastAt = currentNow;
            return {
                x: Math.round(Number(motion.x) || targetWorld.x),
                y: Math.round(Number(motion.y) || targetWorld.y),
                routeActive: Array.isArray(motion.route) && motion.route.length > 0,
            };
        }
        const startWorld = { x: Number(motion.x) || targetWorld.x, y: Number(motion.y) || targetWorld.y };
        let route = officeDraftRouteBetweenWorldPoints(startWorld, space, targetWorld, network);
        let routeBlocked = officeDraftRouteHasBlockedSegment(route, state.spaces, network);
        let routeReachedTarget = officeDraftRouteReached(route, targetWorld);
        if ((!routeReachedTarget || routeBlocked) && !pinned) {
            const blockedTargetSignature = targetSignature;
            const fallbackTarget = officeDraftFallbackAgentTargetWorldPoint(space, agent, index, total);
            const fallbackRoute = officeDraftRouteBetweenWorldPoints(startWorld, space, fallbackTarget, network);
            const fallbackBlocked = officeDraftRouteHasBlockedSegment(fallbackRoute, state.spaces, network);
            if (!fallbackBlocked && officeDraftRouteReached(fallbackRoute, fallbackTarget)) {
                officeDraftRememberBlockedTarget(motion, blockedTargetSignature, currentNow);
                targetAsset = null;
                targetWorld = fallbackTarget;
                targetSignature = `${officeDraftAgentTargetSignature(space, agent, targetWorld, null)}|fallback`;
                route = fallbackRoute;
                routeBlocked = false;
                routeReachedTarget = true;
            }
        }
        if (routeBlocked) {
            route = [startWorld];
        }
        motion.route = route;
        motion.routeIndex = route.length > 1 ? 1 : 0;
        motion.targetX = targetWorld.x;
        motion.targetY = targetWorld.y;
        motion.targetSignature = targetSignature;
        motion.routeStartedAt = currentNow;
        motion.lastAt = currentNow;
        motion.lastProgressAt = currentNow;
        motion.needsReplan = false;
        const stats = officeDraftAgentNavStats(agent);
        if (stats) {
            stats.routeResets += 1;
            if (route.length > 2) stats.obstacleDetours += 1;
        }
        if (route.length <= 1 && Math.hypot(startWorld.x - targetWorld.x, startWorld.y - targetWorld.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
            motion.x = targetWorld.x;
            motion.y = targetWorld.y;
        } else if (route.length <= 1) {
            officeDraftHoldAgentRouteAfterBlock(motion, currentNow, 2400);
        }
    }
    officeDraftAdvanceAgentMotion(agent, motion, currentNow);
    return {
        x: Math.round(Number(motion.x) || targetWorld.x),
        y: Math.round(Number(motion.y) || targetWorld.y),
        routeActive: Array.isArray(motion.route) && motion.route.length > 0,
    };
}

function officeDraftAgentWalkPlacement(space, agent, index, total, now = performance.now(), targetAsset = null) {
    const world = officeDraftAgentWorldPlacement(space, agent, index, total, now, targetAsset);
    if (!world) return null;
    return {
        x: Math.round(world.x - (Number(space?.x) || 0)),
        y: Math.round(world.y - (Number(space?.y) || 0)),
        worldX: world.x,
        worldY: world.y,
        routeActive: world.routeActive,
    };
}

function officeDraftAgentPlacement(space, agent, index, total, now = performance.now()) {
    const targetAsset = officeDraftPrimaryInteractionAsset(space, agent, index, total);
    const placement = officeDraftAgentWalkPlacement(space, agent, index, total, now, targetAsset);
    if (placement) return placement;
    const target = officeDraftAgentTargetWorldPoint(space, agent, index, total, targetAsset);
    return {
        x: Math.round(target.x - (Number(space?.x) || 0)),
        y: Math.round(target.y - (Number(space?.y) || 0)),
        worldX: target.x,
        worldY: target.y,
        routeActive: false,
    };
}


