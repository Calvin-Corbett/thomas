/** Agent target signatures and motion constraints. */

function officeDraftEnsureAgentMotion(agent, space, index = 0, total = 1, targetAsset = null, now = performance.now()) {
    const pinned = officeDraftAgentPinnedTargetWorld(space, agent);
    const targetWorld = pinned || officeDraftAgentTargetWorldPoint(space, agent, index, total, targetAsset);
    if (!agent.draftMotion || typeof agent.draftMotion !== 'object' || Number(agent.draftMotion.navVersion) !== OFFICE_DRAFT_AGENT_NAV_VERSION) {
        const startWorld = officeDraftInitialMotionWorldPoint(agent, space, targetWorld, index, total);
        agent.draftMotion = {
            navVersion: OFFICE_DRAFT_AGENT_NAV_VERSION,
            x: startWorld.x,
            y: startWorld.y,
            targetX: targetWorld.x,
            targetY: targetWorld.y,
            targetSignature: `spawn:${safeString(space?.id)}`,
            route: [],
            routeIndex: 0,
            lastAt: Number(now) || performance.now(),
            lastProgressAt: Number(now) || performance.now(),
            routeStartedAt: 0,
            arrivedAt: Number(now) || performance.now(),
            dragging: false,
            needsReplan: false,
            lastStepDistance: 0,
        };
    }
    if (!Number.isFinite(Number(agent.draftMotion.x)) || !Number.isFinite(Number(agent.draftMotion.y))) {
        const startWorld = officeDraftInitialMotionWorldPoint(agent, space, targetWorld, index, total);
        agent.draftMotion.x = startWorld.x;
        agent.draftMotion.y = startWorld.y;
    }
    if (!Number.isFinite(Number(agent.draftMotion.lastAt))) {
        agent.draftMotion.lastAt = Number(now) || performance.now();
    }
    agent.draftMotion.navVersion = OFFICE_DRAFT_AGENT_NAV_VERSION;
    officeDraftAgentNavStats(agent);
    return agent.draftMotion;
}

function officeDraftAgentMotionSpeed(agent) {
    const base = Math.max(OFFICE_DRAFT_AGENT_SPEED_MIN, Math.min(
        OFFICE_DRAFT_AGENT_SPEED_MAX,
        (Number(agent?.speed) || 3.2) * OFFICE_DRAFT_AGENT_SPEED_SCALE,
    ));
    if (officeDraftAgentCommandActive(agent)) return base * 1.16;
    if (safeString(agent?.intent) === 'task') return base * 1.04;
    if (safeString(agent?.state) === 'break') return base * 0.78;
    return base;
}

function officeDraftAgentTargetSignature(space, agent, targetWorld, targetAsset = null) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const pinnedKey = officeDraftAgentPinnedTargetActive(agent) && safeString(agent?.draftPinnedRoomId) === roomId
        ? `${Math.round(Number(agent?.draftPinnedLocalX) || 0)},${Math.round(Number(agent?.draftPinnedLocalY) || 0)}`
        : '';
    const wanderKey = !pinnedKey && officeDraftAgentWanderTargetActive(agent) && officeDraftNormalizeRoomId(agent?.draftWanderRoomId) === roomId
        ? `${Math.round(Number(agent?.draftWanderLocalX) || 0)},${Math.round(Number(agent?.draftWanderLocalY) || 0)}:${Number(agent?.draftWanderSequence) || 0}:${safeString(agent?.draftWanderAssetId)}`
        : '';
    return [
        OFFICE_DRAFT_AGENT_NAV_VERSION,
        safeString(space?.id),
        roomId,
        pinnedKey,
        wanderKey,
        (pinnedKey || wanderKey) ? '' : safeString(targetAsset?.id),
        Math.round(Number(targetWorld?.x) || 0),
        Math.round(Number(targetWorld?.y) || 0),
    ].join('|');
}

function officeDraftStepInsideDoorCorridor(space, fromPoint, toPoint) {
    if (!space) return false;
    const network = officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const door = officeDraftSpaceDoorPoint(space, network);
    const interior = officeDraftSpaceDoorInteriorPoint(space, network);
    const corridor = {
        x1: interior.x,
        y1: interior.y,
        x2: door.outsideX,
        y2: door.outsideY,
    };
    return officeDraftPointOnSegment(fromPoint, corridor, 28)
        && officeDraftPointOnSegment(toPoint, corridor, 28);
}

function officeDraftStepOnHallway(fromPoint, toPoint, networkRaw = null) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const segments = Array.isArray(network?.segments) ? network.segments : [];
    if (!segments.length) return false;
    const tolerance = Math.max(34, (OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH / 2) - 12);
    return officeDraftNearestHallwayPoint(fromPoint, network).distance <= tolerance
        && officeDraftNearestHallwayPoint(toPoint, network).distance <= tolerance;
}

function officeDraftCurrentPointWalkable(current, space) {
    if (!space) return false;
    if (officeDraftStepOnHallway(current, current)) return true;
    return officeDraftPointWalkableInSpace(current, space);
}

function officeDraftRememberBlockedTarget(motion, signatureRaw, nowRaw = performance.now()) {
    if (!motion || typeof motion !== 'object') return;
    const signature = safeString(signatureRaw);
    if (!signature) return;
    const currentNow = Number(nowRaw) || performance.now();
    const until = currentNow + OFFICE_DRAFT_AGENT_BLOCKED_TARGET_MS;
    const records = motion.blockedTargetRecords && typeof motion.blockedTargetRecords === 'object'
        ? motion.blockedTargetRecords
        : {};
    Object.keys(records).forEach((key) => {
        if ((Number(records[key]) || 0) <= currentNow) delete records[key];
    });
    records[signature] = until;
    motion.blockedTargetRecords = records;
    motion.blockedTargetSignature = signature;
    motion.blockedTargetUntil = until;
}

function officeDraftTargetBlocked(motion, signatureRaw, nowRaw = performance.now()) {
    if (!motion || typeof motion !== 'object') return false;
    const signature = safeString(signatureRaw);
    if (!signature) return false;
    const currentNow = Number(nowRaw) || performance.now();
    const records = motion.blockedTargetRecords && typeof motion.blockedTargetRecords === 'object'
        ? motion.blockedTargetRecords
        : {};
    if ((Number(records[signature]) || 0) > currentNow) return true;
    return safeString(motion.blockedTargetSignature) === signature
        && (Number(motion.blockedTargetUntil) || 0) > currentNow;
}

function officeDraftHoldAgentRouteAfterBlock(motion, nowRaw = performance.now(), retryMs = OFFICE_DRAFT_AGENT_HARD_CLAMP_RETRY_MS) {
    if (!motion || typeof motion !== 'object') return;
    const currentNow = Number(nowRaw) || performance.now();
    motion.route = [];
    motion.routeIndex = 0;
    motion.needsReplan = false;
    motion.routeRetryAfter = Math.max(Number(motion.routeRetryAfter) || 0, currentNow + Math.max(480, Number(retryMs) || 0));
    officeDraftRememberBlockedTarget(motion, motion.targetSignature, currentNow);
    motion.lastProgressAt = currentNow;
}

function officeDraftConstrainAgentStep(agent, motion, nextPoint, now = performance.now()) {
    const next = {
        x: Math.round(Number(nextPoint?.x) || Number(motion?.x) || 0),
        y: Math.round(Number(nextPoint?.y) || Number(motion?.y) || 0),
    };
    const current = {
        x: Math.round(Number(motion?.x) || next.x),
        y: Math.round(Number(motion?.y) || next.y),
    };
    const space = officeDraftSpaceAtWorldPoint(next.x, next.y)
        || officeDraftSpaceAtWorldPoint(current.x, current.y);
    if (!space) return next;
    if (officeDraftStepOnHallway(current, next)) return next;
    if (officeDraftPointWalkableInSpace(next, space)) return next;
    if (officeDraftStepInsideDoorCorridor(space, current, next)) return next;
    const eased = [0.75, 0.5, 0.33, 0.2].find((factor) => {
        const candidate = {
            x: Math.round(current.x + ((next.x - current.x) * factor)),
            y: Math.round(current.y + ((next.y - current.y) * factor)),
        };
        return (officeDraftStepOnHallway(current, candidate)
            || officeDraftStepInsideDoorCorridor(space, current, candidate)
            || (
                officeDraftPointWalkableInSpace(candidate, space)
                && officeDraftSegmentClearInSpace(current, candidate, space)
            ));
    });
    if (Number.isFinite(eased)) {
        return {
            x: Math.round(current.x + ((next.x - current.x) * eased)),
            y: Math.round(current.y + ((next.y - current.y) * eased)),
        };
    }
    const stats = officeDraftAgentNavStats(agent);
    if (stats) stats.hardClamps += 1;
    officeDraftHoldAgentRouteAfterBlock(motion, now);
    if (officeDraftCurrentPointWalkable(current, space)) return current;
    return officeDraftClampWorldPointToWalkable(current, space);
}

function officeDraftRecordAgentStep(agent, motion, fromPoint, toPoint) {
    const distance = Math.round(Math.hypot((Number(toPoint?.x) || 0) - (Number(fromPoint?.x) || 0), (Number(toPoint?.y) || 0) - (Number(fromPoint?.y) || 0)));
    motion.lastStepDistance = distance;
    const stats = officeDraftAgentNavStats(agent);
    if (stats) {
        stats.lastJump = distance;
        stats.maxJump = Math.max(Number(stats.maxJump) || 0, distance);
    }
}

function officeDraftMotionPaintFresh(now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    const lastPaintAt = Number(officeState?.lastDraftMotionPaintAt) || currentNow;
    const maxPaintGap = typeof OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS === 'number'
        ? OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS
        : 260;
    return currentNow - lastPaintAt <= maxPaintGap;
}

