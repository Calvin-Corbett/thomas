// Extracted from part-015.js
// From outofbounds

            agent.state = 'runaway';
            agent.intent = 'runaway';
            return;
        }
        const outOfBounds = agent.x < 0.5 || agent.x > 99.5 || agent.y < 0.5 || agent.y > 99.5;
        if (arrived || outOfBounds || now >= agent.returnAfterRunAt) {
            agent.x = officeClamp(agent.x, 2, 98);
            agent.y = officeClamp(agent.y, 2, 98);
            agent.targetX = agent.x;
            agent.targetY = agent.y;
            agent.state = 'walking';
            agent.intent = 'wander';
            agent.returnAfterRunAt = 0;
            agent.runawayPhase = '';
            agent.runawayExitX = 0;
            agent.runawayExitY = 0;
            agent.currentNodeId = officeFindNearestNode(officeState.navMap, agent.x, agent.y);
            const routed = officeRouteAgentToRoom(agent, 'room-lobby', {
                intent: 'wander',
                speed: officeRandomRange(3.9, 5.2),
            });
            if (!routed) {
                agent.state = 'idle';
                agent.intent = 'wander';
                agent.idleUntil = now + officeRandomRange(800, 1700);
            }
        }
        return;
    }

    if (agent.state === 'yield') {
        if (now >= agent.yieldUntil) {
            agent.state = 'walking';
            if (safeString(agent.yieldResumeIntent)) {
                agent.intent = agent.yieldResumeIntent;
            }
            agent.yieldUntil = 0;
            agent.yieldResumeIntent = '';
        } else {
            return;
        }
    }

    if (agent.state === 'walking') {
        const arrived = officeMoveAgent(agent, dt);
        if (!arrived) {
            officeSafeguardAgentPosition(agent, now, { reroute: true });
            officeHandleAgentStuck(agent, now);
            return;
        }
        agent.stuckSince = 0;

        if (agent.intent === 'task' && agent.taskId) {
            agent.state = 'working';
            agent.workUntil = now + officeRandomRange(6200, 15000);
            agent.nextWorkLineAt = now + officeRandomRange(2400, 5600);
            officeBusEmit('agent.state', {
                agentId: agent.id,
                state: agent.state,
                intent: agent.intent,
            }, now);
            return;
        }
        if (agent.intent === 'break') {
            agent.state = 'break';
            agent.breakUntil = now + officeRandomRange(3000, 7600);
            agent.nextWorkLineAt = now + officeRandomRange(1200, 3200);
            officeBusEmit('agent.state', {
                agentId: agent.id,
                state: agent.state,
                intent: agent.intent,
            }, now);
            return;
        }
        agent.state = 'idle';
        agent.intent = 'wander';
        agent.idleUntil = now + officeRandomRange(1200, 3200);
        return;
    }

    if (agent.state === 'working') {
        if (now >= agent.workUntil) {
            officeFinishTask(agent, now);
            return;
        }
        if (now >= agent.nextWorkLineAt) {
            const room = officeCurrentRoomForAgent(agent);
            officeSpeak(agent, officeBanterForAgent(agent, 'ambient', {
                roomTheme: room?.theme || room?.kind || '',
            }));
            agent.nextWorkLineAt = now + officeRandomRange(3500, 7200);
        }
        return;
    }

    if (agent.state === 'break') {
        if (now >= agent.breakUntil) {
            agent.state = 'idle';
            agent.intent = 'wander';
            agent.idleUntil = now + officeRandomRange(600, 1800);
            officeRouteAgentToRoom(agent, 'room-lobby', {
                intent: 'wander',
                speed: officeRandomRange(2.6, 3.6),
            });
            return;
        }
        if (now >= agent.nextWorkLineAt) {
            const room = officeCurrentRoomForAgent(agent);
            officeSpeak(agent, officeBanterForAgent(agent, 'break', {
                roomTheme: room?.theme || room?.kind || '',
            }));
            agent.nextWorkLineAt = now + officeRandomRange(2600, 5600);
        }
        return;
    }

    if (agent.state !== 'idle') {
        return;
    }

    if (now >= agent.nextAmbientAt) {
        const room = officeCurrentRoomForAgent(agent);
        if (room && room.kind === 'break') {
            officeSpeak(agent, officeBanterForAgent(agent, 'break', { roomTheme: room.theme || room.kind }));
        } else if (officeChance(0.62)) {
            officeSpeak(agent, officeBanterForAgent(agent, 'ambient', { roomTheme: room?.theme || room?.kind || '' }));
        }
        agent.nextAmbientAt = now + officeRandomRange(8200, 16000);
    }

    if (now >= agent.idleUntil && !agent.taskId) {
        if (officeChance(0.16)) {
            const breakRoomId = officeChance(0.5) ? 'room-coffee' : 'room-break';
            officeRouteAgentToRoom(agent, breakRoomId, {
                intent: 'break',
                speed: officeRandomRange(3, 4.1),
            });
            return;
        }
        const roamRoom = officePick(officeState.rooms);
        officeRouteAgentToRoom(agent, roamRoom?.id || 'room-lobby', {
            intent: 'wander',
            speed: officeRandomRange(2.4, 3.5),
        });
    }
}

function officeAgentTrafficPriority(agent) {
    if (!agent) return 0;
    let score = 0;
    if (agent.intent === 'task') score += 4;
    if (agent.state === 'working') score += 3;
    if (agent.intent === 'break') score += 1;
    if (Array.isArray(agent.routeWaypoints)) {
        score += Math.min(1.4, agent.routeWaypoints.length * 0.08);
    }
    const stableTieBreak = (safeString(agent.id).charCodeAt(safeString(agent.id).length - 1) || 0) / 2550;
    return score + stableTieBreak;
}

function officeCollisionPairKey(aId, bId) {
    const first = safeString(aId);
    const second = safeString(bId);
    if (!first || !second) return '';
    return first < second ? `${first}|${second}` : `${second}|${first}`;
}

function officeLaneEdgeKey(fromId, toId) {
    const first = safeString(fromId);
    const second = safeString(toId);
    if (!first || !second) return '';
    return first < second ? `${first}<->${second}` : `${second}<->${first}`;
}

function officeAgentActiveRouteEdge(agent) {
    if (!officeState || !agent || agent.state === 'runaway') return null;
    const fromNodeId = safeString(agent.currentNodeId) || officeFindNearestNode(officeState.navMap, agent.x, agent.y);
    let toNodeId = safeString(agent.routeWaypoints?.[0]?.nodeId);
    if (!toNodeId) {
        toNodeId = safeString(agent.routeDestinationNodeId);
    }
    if (!fromNodeId || !toNodeId || fromNodeId === toNodeId) return null;
    const edgeKey = officeLaneEdgeKey(fromNodeId, toNodeId);
    if (!edgeKey) return null;
    return {
        fromNodeId,
        toNodeId,
        edgeKey,
        directedKey: `${fromNodeId}>${toNodeId}`,
    };
}

function officeTickLaneReservations(now) {
    if (!officeState) return;
    const reservations = officeState.laneReservations || new Map();
    officeState.laneReservations = reservations;

    reservations.forEach((claim, edgeKey) => {
        if (!claim || !Number.isFinite(claim.expiresAt) || claim.expiresAt <= now) {
            reservations.delete(edgeKey);
        }
    });

    const walkers = officeState.agents.filter((agent) => (
        agent
        && agent.state === 'walking'
        && agent.intent !== 'runaway'
    ));

    walkers.forEach((agent) => {
        const edge = officeAgentActiveRouteEdge(agent);
        agent.reservedLaneEdgeKey = edge?.edgeKey || '';
        if (!edge) return;

        const priority = officeAgentTrafficPriority(agent);
        const existing = reservations.get(edge.edgeKey);
        if (!existing || safeString(existing.agentId) === agent.id) {
            reservations.set(edge.edgeKey, {
                edgeKey: edge.edgeKey,
                directedKey: edge.directedKey,
                priority,
                agentId: agent.id,
                expiresAt: now + 600,
            });
            return;
        }

        const otherAgent = officeGetAgentById(existing.agentId);
        const otherPriority = Number(existing.priority) || 0;
        const oppositeDirection = safeString(existing.directedKey) !== edge.directedKey;
        const nearEnough = otherAgent
            ? Math.hypot(otherAgent.x - agent.x, otherAgent.y - agent.y) <= 8.8
            : true;

        if (oppositeDirection && nearEnough && priority < otherPriority) {
            const anchorX = otherAgent ? otherAgent.x : agent.targetX;
            const anchorY = otherAgent ? otherAgent.y : agent.targetY;
            const awayX = agent.x - anchorX;
            const awayY = agent.y - anchorY;
            const awayLen = Math.max(0.001, Math.hypot(awayX, awayY));
            officeSetYieldState(
                agent,
                now,
                (awayX / awayLen) * officeRandomRange(0.52, 1.08),
                (awayY / awayLen) * officeRandomRange(0.52, 1.08),
            );
            return;
        }

        if (priority > otherPriority) {
            reservations.set(edge.edgeKey, {
                edgeKey: edge.edgeKey,
                directedKey: edge.directedKey,
                priority,
                agentId: agent.id,
                expiresAt: now + 600,
            });
        }
    });
}

function officeSetYieldState(agent, now, awayX = 0, awayY = 0) {
    if (!agent || agent.state === 'runaway') return;
    if (agent.state !== 'walking' && agent.state !== 'idle' && agent.state !== 'break') return;
    agent.yieldResumeIntent = agent.intent || 'wander';
    agent.state = 'yield';
    agent.yieldUntil = now + officeRandomRange(320, 620);
    const fallbackX = officeClamp(agent.x + awayX, 3, 97);
    const fallbackY = officeClamp(agent.y + awayY, 5, 96);
    const walkableTarget = officeNearestWalkablePoint(fallbackX, fallbackY, agent.x, agent.y);
    agent.targetX = officeClamp(walkableTarget.x, 3, 97);
    agent.targetY = officeClamp(walkableTarget.y, 5, 96);
}

function officeHandleCollisions(now) {
    if (!officeState) return;
    const minDistance = OFFICE_AGENT_COLLISION_DISTANCE;
    const pairCooldowns = officeState.collisionPairCooldowns || new Map();
    if (!officeState.collisionPairCooldowns) {
        officeState.collisionPairCooldowns = pairCooldowns;
    }
    if ((now - (officeState.lastCollisionCooldownPurgeAt || 0)) >= OFFICE_COLLISION_PAIR_PURGE_MS) {
        officeState.lastCollisionCooldownPurgeAt = now;
        pairCooldowns.forEach((until, pairKey) => {
            if (!Number.isFinite(until) || until < now - OFFICE_COLLISION_PAIR_PURGE_MS) {
                pairCooldowns.delete(pairKey);
            }
        });
    }

    for (let i = 0; i < officeState.agents.length; i += 1) {
        for (let j = i + 1; j < officeState.agents.length; j += 1) {