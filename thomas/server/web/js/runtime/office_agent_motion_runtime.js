/** Agent motion advancement and route scheduling. */

function officeDraftAdvanceAgentCheapMotion(agent, motion, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!motion || typeof motion !== 'object' || !officeDraftMotionPaintFresh(currentNow)) {
        if (motion && typeof motion === 'object') motion.lastAt = currentNow;
        return;
    }
    const lastAt = Number(motion.lastAt) || currentNow;
    const deltaSeconds = Math.max(0, Math.min(0.14, (currentNow - lastAt) / 1000));
    motion.lastAt = currentNow;
    if (motion.dragging || (Number(agent?.draftPausedUntil) || 0) > currentNow) return;
    const targetX = Number(motion.targetX);
    const targetY = Number(motion.targetY);
    if (!Number.isFinite(targetX) || !Number.isFinite(targetY)) return;
    const dx = targetX - (Number(motion.x) || targetX);
    const dy = targetY - (Number(motion.y) || targetY);
    const distance = Math.hypot(dx, dy);
    if (distance <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        motion.x = Math.round(targetX);
        motion.y = Math.round(targetY);
        motion.arrivedAt = currentNow;
        motion.needsReplan = false;
        motion.route = [];
        motion.routeIndex = 0;
        return;
    }
    const step = Math.min(distance, officeDraftAgentMotionSpeed(agent) * deltaSeconds);
    if (step <= 0) return;
    const fromPoint = { x: Number(motion.x) || targetX, y: Number(motion.y) || targetY };
    const nextRaw = {
        x: fromPoint.x + ((dx / distance) * step),
        y: fromPoint.y + ((dy / distance) * step),
    };
    const nextPoint = {
        x: Math.round(Number(nextRaw.x) || fromPoint.x),
        y: Math.round(Number(nextRaw.y) || fromPoint.y),
    };
    const stepSpace = officeDraftSpaceAtWorldPoint(nextPoint.x, nextPoint.y)
        || officeDraftSpaceAtWorldPoint(fromPoint.x, fromPoint.y);
    const canStep = officeDraftStepOnHallway(fromPoint, nextPoint)
        || (stepSpace && (
            officeDraftStepInsideDoorCorridor(stepSpace, fromPoint, nextPoint)
            || (
                officeDraftPointWalkableInSpace(nextPoint, stepSpace)
                && officeDraftSegmentClearInSpace(fromPoint, nextPoint, stepSpace)
            )
        ));
    if (!canStep) {
        motion.needsReplan = true;
        return;
    }
    motion.x = nextPoint.x;
    motion.y = nextPoint.y;
    officeDraftRecordAgentStep(agent, motion, fromPoint, nextPoint);
    if (Math.hypot(motion.x - fromPoint.x, motion.y - fromPoint.y) > 1) {
        motion.lastProgressAt = currentNow;
    }
    if (Math.abs(dx) > 1) {
        agent.facing = dx >= 0 ? 1 : -1;
    }
}

function officeDraftAdvanceAgentMotion(agent, motion, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!officeDraftMotionPaintFresh(currentNow)) {
        motion.lastAt = currentNow;
        return;
    }
    const lastAt = Number(motion.lastAt) || currentNow;
    const deltaSeconds = Math.max(0, Math.min(0.18, (currentNow - lastAt) / 1000));
    motion.lastAt = currentNow;
    if (motion.dragging || (Number(agent?.draftPausedUntil) || 0) > currentNow) {
        return;
    }
    const route = Array.isArray(motion.route) ? motion.route : [];
    if (!route.length || Number(motion.routeIndex) >= route.length) {
        return;
    }
    let remaining = officeDraftAgentMotionSpeed(agent) * deltaSeconds;
    while (remaining > 0 && Number(motion.routeIndex) < route.length) {
        const waypoint = route[Number(motion.routeIndex)];
        const dx = (Number(waypoint?.x) || motion.x) - motion.x;
        const dy = (Number(waypoint?.y) || motion.y) - motion.y;
        const distance = Math.hypot(dx, dy);
        if (distance <= OFFICE_DRAFT_AGENT_WAYPOINT_EPSILON) {
            motion.x = Math.round(Number(waypoint?.x) || motion.x);
            motion.y = Math.round(Number(waypoint?.y) || motion.y);
            motion.routeIndex = Number(motion.routeIndex) + 1;
            continue;
        }
        const step = Math.min(distance, remaining);
        const fromPoint = { x: motion.x, y: motion.y };
        const nextPoint = officeDraftConstrainAgentStep(agent, motion, {
            x: motion.x + ((dx / distance) * step),
            y: motion.y + ((dy / distance) * step),
        }, currentNow);
        motion.x = nextPoint.x;
        motion.y = nextPoint.y;
        officeDraftRecordAgentStep(agent, motion, fromPoint, nextPoint);
        if (Math.hypot(motion.x - fromPoint.x, motion.y - fromPoint.y) > 1) {
            motion.lastProgressAt = currentNow;
        } else if ((currentNow - (Number(motion.lastProgressAt) || currentNow)) > OFFICE_DRAFT_AGENT_STUCK_REPLAN_MS) {
            officeDraftHoldAgentRouteAfterBlock(motion, currentNow, OFFICE_DRAFT_AGENT_HARD_CLAMP_RETRY_MS);
            const stats = officeDraftAgentNavStats(agent);
            if (stats) stats.stuckReplans += 1;
            break;
        }
        if (Math.abs(dx) > 1) {
            agent.facing = dx >= 0 ? 1 : -1;
        }
        remaining -= step;
        break;
    }
    if (Number(motion.routeIndex) >= route.length) {
        motion.route = [];
        motion.routeIndex = 0;
        motion.arrivedAt = currentNow;
        agent.draftLastSpaceId = safeString(officeDraftSpaceAtWorldPoint(motion.x, motion.y)?.id);
    }
}

function officeDraftConsumeRoutePlanBudget(stateRaw = null) {
    const state = stateRaw || officeDraftMapState;
    if (!state || !Number.isFinite(Number(state.agentRoutePlansRemaining))) return true;
    if (Number(state.agentRoutePlansRemaining) > 0) {
        state.agentRoutePlansRemaining = Number(state.agentRoutePlansRemaining) - 1;
        return true;
    }
    state.agentRoutePlanDeferred = true;
    return false;
}

function officeDraftAgentHasPendingRoutePlan(agent, nowRaw = performance.now()) {
    if (!agent || typeof agent !== 'object') return false;
    const now = Number(nowRaw) || performance.now();
    if ((Number(agent.draftPausedUntil) || 0) > now) return false;
    const motion = agent.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (!motion || Number(motion.navVersion) !== OFFICE_DRAFT_AGENT_NAV_VERSION) return true;
    if (motion.dragging === true) return false;
    if ((Number(motion.routeRetryAfter) || 0) > now) return false;
    if (motion.needsReplan === true) return true;
    const signature = safeString(motion.targetSignature);
    if (!signature || signature.startsWith('spawn:') || signature.startsWith('deferred:')) return true;
    const routeActive = Array.isArray(motion.route) && motion.route.length > 0;
    if (routeActive) return false;
    const distanceToTarget = Math.hypot(
        (Number(motion.x) || 0) - (Number(motion.targetX) || Number(motion.x) || 0),
        (Number(motion.y) || 0) - (Number(motion.targetY) || Number(motion.y) || 0),
    );
    return distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON && (Number(motion.routeRetryAfter) || 0) <= now;
}

function officeDraftRoutePlanQuietActive(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if ((Number(state.routePlanQuietUntil) || 0) > currentNow) return true;
    return officeDraftAgentRenderQuietActive(state, currentNow);
}

function officeDraftScheduleDeferredRoutePlan(stateRaw = null, now = performance.now()) {
    const state = stateRaw || officeDraftMapState;
    if (!state || state.agentRoutePlanTimer) return;
    const currentNow = Number(now) || performance.now();
    const previousCost = Math.max(0, Number(officeState?.lastDraftAgentRenderDurationMs) || 0);
    const adaptiveDelay = previousCost > OFFICE_DRAFT_AGENT_RENDER_OVERLOAD_MS
        ? Math.min(2200, Math.max(900, Math.round(previousCost * 8)))
        : 900;
    const lastRoutePlanAt = Number(state.lastRoutePlanRenderAt) || 0;
    const sinceLastRoutePlan = currentNow - lastRoutePlanAt;
    const throttleDelay = Math.max(0, OFFICE_DRAFT_AGENT_ROUTE_PLAN_MIN_INTERVAL_MS - sinceLastRoutePlan);
    state.agentRoutePlanTimer = window.setTimeout(() => {
        state.agentRoutePlanTimer = 0;
        const timerNow = performance.now();
        if (officeDraftRoutePlanQuietActive(state, timerNow)) {
            officeDraftScheduleDeferredRoutePlan(state, timerNow);
            return;
        }
        officeRenderDraftAgentLayerOnly(timerNow, { force: true, source: 'route-plan' });
    }, Math.max(adaptiveDelay, throttleDelay, OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS - (currentNow % OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS)));
}


