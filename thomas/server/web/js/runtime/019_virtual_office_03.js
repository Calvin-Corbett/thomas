function officeSetEditorOpen(open) {
    if (!officeEditorModal) return;
    const isOpen = Boolean(open);
    officeEditorModal.classList.toggle('hidden', !isOpen);
    officeEditorModal.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
    if (officeWorkspace) {
        officeWorkspace.classList.toggle('editor-open', isOpen);
    }
    if (officeEditorToggleBtn) {
        officeEditorToggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    if (officeEditorDockBtn) {
        officeEditorDockBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    if (isOpen) {
        officeSyncCustomizerFields();
        officeBusEmit('editor.opened', { selectedAgentId: officeState?.selectedAgentId || '' });
        if (officeAgentSelect) {
            window.setTimeout(() => {
                officeAgentSelect.focus();
            }, 0);
        }
    } else {
        officeBusEmit('editor.closed', {});
    }
}

function officeSyncCustomizerFields() {
    if (!officeState) return;
    const agent = officeGetAgentById(officeState.selectedAgentId) || officeState.agents[0];
    if (!agent) return;
    officeState.selectedAgentId = agent.id;
    if (officeAgentSelect) officeAgentSelect.value = agent.id;
    if (officeAgentNameInput) officeAgentNameInput.value = agent.name;
    if (officeAgentColorInput) officeAgentColorInput.value = agent.color;
    if (officeAgentCostumeSelect) officeAgentCostumeSelect.value = agent.costume || 'none';
}

function officeRenderAgentSelector(selectedId = '') {
    if (!officeState || !officeAgentSelect) return;
    const fallbackId = selectedId || officeState.selectedAgentId || officeState.agents[0]?.id || '';
    officeAgentSelect.innerHTML = '';
    officeState.agents.forEach((agent) => {
        const option = document.createElement('option');
        option.value = agent.id;
        option.textContent = agent.name;
        officeAgentSelect.appendChild(option);
    });
    if (officeState.agents.some((agent) => agent.id === fallbackId)) {
        officeState.selectedAgentId = fallbackId;
    } else {
        officeState.selectedAgentId = officeState.agents[0]?.id || '';
    }
    officeAgentSelect.value = officeState.selectedAgentId;
    officeSyncCustomizerFields();
}

function officeSetAgentTarget(agent, x, y, { intent = 'wander', speed = 0, preserveRoute = false } = {}) {
    if (!agent) return;
    if (agent.state === 'yield') {
        agent.state = 'walking';
        agent.yieldUntil = 0;
        agent.yieldResumeIntent = '';
    }
    agent.targetX = officeClamp(x, 3, 97);
    agent.targetY = officeClamp(y, 5, 96);
    if (safeString(intent) !== 'runaway' && agent.state !== 'runaway') {
        const walkableTarget = officeNearestWalkablePoint(agent.targetX, agent.targetY, agent.x, agent.y);
        agent.targetX = officeClamp(walkableTarget.x, 3, 97);
        agent.targetY = officeClamp(walkableTarget.y, 5, 96);
    }
    agent.intent = intent;
    agent.state = 'walking';
    if (!preserveRoute) {
        agent.routeWaypoints = [];
        agent.routeDestinationNodeId = '';
    }
    if (speed > 0) {
        agent.speed = speed;
    }
    agent.stuckSince = 0;
}

function officeComputeAgentAvoidance(agent) {
    if (!officeState || !agent) {
        return { x: 0, y: 0 };
    }
    let forceX = 0;
    let forceY = 0;

    officeState.agents.forEach((other) => {
        if (!other || other.id === agent.id || other.state === 'runaway') return;
        const dx = agent.x - other.x;
        const dy = agent.y - other.y;
        const distance = Math.hypot(dx, dy);
        if (!Number.isFinite(distance) || distance <= 0.001 || distance >= OFFICE_AGENT_AVOID_RADIUS) return;

        const ratio = (OFFICE_AGENT_AVOID_RADIUS - distance) / OFFICE_AGENT_AVOID_RADIUS;
        const weight = ratio * ratio;
        forceX += (dx / distance) * weight;
        forceY += (dy / distance) * weight;
    });

    const magnitude = Math.hypot(forceX, forceY);
    if (!Number.isFinite(magnitude) || magnitude <= 0.0001) {
        return { x: 0, y: 0 };
    }
    const capped = Math.min(1.4, magnitude);
    return {
        x: (forceX / magnitude) * capped,
        y: (forceY / magnitude) * capped,
    };
}

function officeMoveAgent(agent, dt) {
    const dx = agent.targetX - agent.x;
    const dy = agent.targetY - agent.y;
    const distance = Math.hypot(dx, dy);
    if (agent.state === 'yield') {
        return distance <= 0.26;
    }

    const avoidance = officeComputeAgentAvoidance(agent);
    const desiredX = distance > 0.001 ? (dx / distance) : 0;
    const desiredY = distance > 0.001 ? (dy / distance) : 0;
    const avoidanceForwardDot = (avoidance.x * desiredX) + (avoidance.y * desiredY);
    const lateralAvoidX = avoidance.x - (desiredX * avoidanceForwardDot);
    const lateralAvoidY = avoidance.y - (desiredY * avoidanceForwardDot);
    const steerX = dx + (lateralAvoidX * 2.42) - (desiredX * Math.max(0, -avoidanceForwardDot) * 0.78);
    const steerY = dy + (lateralAvoidY * 2.42) - (desiredY * Math.max(0, -avoidanceForwardDot) * 0.78);
    const steerDistance = Math.hypot(steerX, steerY);
    const moveX = steerDistance > 0.001 ? steerX : dx;
    const moveY = steerDistance > 0.001 ? steerY : dy;
    const moveDistance = Math.hypot(moveX, moveY);

    if (Math.abs(moveX) > 0.1) {
        agent.facing = moveX >= 0 ? 1 : -1;
    }
    if (distance <= 0.22) {
        agent.x = agent.targetX;
        agent.y = agent.targetY;
        if (Array.isArray(agent.routeWaypoints) && agent.routeWaypoints.length) {
            const nextStop = agent.routeWaypoints.shift();
            if (nextStop) {
                agent.targetX = nextStop.x;
                agent.targetY = nextStop.y;
                if (safeString(nextStop.nodeId)) {
                    agent.currentNodeId = nextStop.nodeId;
                }
                return false;
            }
        }
        if (safeString(agent.routeDestinationNodeId)) {
            agent.currentNodeId = agent.routeDestinationNodeId;
            agent.routeDestinationNodeId = '';
        }
        return true;
    }
    const crowdBrake = 1 - Math.min(0.42, Math.max(0, -avoidanceForwardDot) * 0.26);
    const step = Math.min(distance, Math.max(1.05, agent.speed) * dt * crowdBrake);
    const dirX = moveDistance > 0.001 ? (moveX / moveDistance) : (dx / Math.max(0.001, distance));
    const dirY = moveDistance > 0.001 ? (moveY / moveDistance) : (dy / Math.max(0.001, distance));
    const fromX = agent.x;
    const fromY = agent.y;
    const nextX = officeClamp(agent.x + (dirX * step), 2, 98);
    const nextY = officeClamp(agent.y + (dirY * step), 4, 97);
    const constrained = officeConstrainWalkableMove(agent, fromX, fromY, nextX, nextY);
    agent.x = officeClamp(constrained.x, 2, 98);
    agent.y = officeClamp(constrained.y, 4, 97);
    return false;
}

function officeSafeguardAgentPosition(agent, now = performance.now(), { reroute = true } = {}) {
    if (!officeState || !agent) return false;
    if (agent.state === 'runaway') {
        agent.x = officeClamp(agent.x, 0, 100);
        agent.y = officeClamp(agent.y, 0, 100);
        return false;
    }

    let x = officeClamp(Number(agent.x) || 0, 1, 99);
    let y = officeClamp(Number(agent.y) || 0, 1, 99);
    let targetX = officeClamp(Number(agent.targetX) || x, 1, 99);
    let targetY = officeClamp(Number(agent.targetY) || y, 1, 99);
    let snapped = false;

    if (!officeIsWalkablePoint(x, y)) {
        const fallbackX = Number(agent.lastMoveX) || x;
        const fallbackY = Number(agent.lastMoveY) || y;
        const safe = officeNearestWalkablePoint(x, y, fallbackX, fallbackY);
        x = officeClamp(safe.x, 1, 99);
        y = officeClamp(safe.y, 1, 99);
        snapped = true;
    }
    if (!officeIsWalkablePoint(targetX, targetY)) {
        const safeTarget = officeNearestWalkablePoint(targetX, targetY, x, y);
        targetX = officeClamp(safeTarget.x, 1, 99);
        targetY = officeClamp(safeTarget.y, 1, 99);
        snapped = true;
    }

    agent.x = x;
    agent.y = y;
    agent.targetX = targetX;
    agent.targetY = targetY;

    if (!snapped) return false;

    agent.currentNodeId = officeFindNearestNode(officeState.navMap, agent.x, agent.y);
    if (!reroute || agent.state !== 'walking') {
        return true;
    }

    const destinationNodeId = safeString(agent.routeDestinationNodeId);
    if (destinationNodeId && officeState.navMap.has(destinationNodeId)) {
        officeRouteAgentToNode(agent, destinationNodeId, {
            intent: agent.intent || 'wander',
            speed: Math.max(2.5, Number(agent.speed) || 0),
        });
        agent.collisionCooldownUntil = now + officeRandomRange(260, 620);
    }
    return true;
}

function officeHandleAgentStuck(agent, now) {
    if (!officeState || !agent || agent.state !== 'walking') return;
    const deltaX = Number(agent.x) - Number(agent.lastMoveX || agent.x);
    const deltaY = Number(agent.y) - Number(agent.lastMoveY || agent.y);
    const moved = Math.hypot(deltaX, deltaY);
    const toTarget = Math.hypot((agent.targetX || agent.x) - agent.x, (agent.targetY || agent.y) - agent.y);
    agent.lastMoveX = agent.x;
    agent.lastMoveY = agent.y;

    if (moved > 0.055 || toTarget < 0.48) {
        agent.stuckSince = 0;
        return;
    }
    if (!agent.stuckSince) {
        agent.stuckSince = now;
        return;
    }
    if ((now - agent.stuckSince) < 2100) return;

    agent.stuckSince = now;
    const destinationNodeId = safeString(agent.routeDestinationNodeId);
    if (destinationNodeId && destinationNodeId !== safeString(agent.currentNodeId)) {
        officeRouteAgentToNode(agent, destinationNodeId, {
            intent: agent.intent || 'wander',
            speed: Math.max(3.2, Number(agent.speed) || 0),
        });
        return;
    }

    const fallbackRoomId = agent.intent === 'break' ? 'room-break' : 'room-lobby';
    officeRouteAgentToRoom(agent, fallbackRoomId, {
        intent: agent.intent || 'wander',
        speed: Math.max(3.2, Number(agent.speed) || 0),
    });
}

function officeSnapAgentToNavigation(agent, { reroute = false } = {}) {
    if (!officeState?.navMap || !agent || agent.state === 'runaway') return false;
    const nearestNodeId = officeFindNearestNode(officeState.navMap, agent.x, agent.y);
    const nearestNode = officeState.navMap.get(nearestNodeId);
    if (!nearestNode) return false;

    agent.x = nearestNode.x;
    agent.y = nearestNode.y;
    agent.targetX = nearestNode.x;
    agent.targetY = nearestNode.y;
    agent.currentNodeId = nearestNodeId;

    if (!reroute) return true;

    const destinationNodeId = safeString(agent.routeDestinationNodeId);
    if (destinationNodeId && destinationNodeId !== nearestNodeId) {
        officeRouteAgentToNode(agent, destinationNodeId, {
            intent: agent.intent || 'wander',
            speed: Math.max(2.8, Number(agent.speed) || 0),
        });
        return true;
    }

    if (agent.intent === 'task' && agent.taskId) {
        const task = officeState.tasks.find((entry) => entry.id === agent.taskId);
        if (task) {
            officeRouteAgentToRoom(agent, task.roomId, {
                intent: 'task',
                speed: Math.max(3.2, Number(agent.speed) || 0),
            });
        }
    }
    return true;
}

function officeTaskPriorityScore(task) {
    if (!task) return 0;
    const now = Date.now();
    const ageMs = Math.max(0, now - (Number(task.createdAt) || now));
    const ageScore = Math.min(3.6, ageMs / 22_000);
    const structuredPriority = officeClamp(Number(task.priority) || 0, 0, 4);
    const roomBoost = safeString(task.roomId) === 'room-support' ? 0.5 : 0;
    return ageScore + structuredPriority + roomBoost;
}

function officeAgentTaskFitScore(agent, task) {
    if (!agent || !task) return 0;
    const roomId = safeString(task.roomId);
    const tint = officePersonaBucket(agent);
    const tintRoomAffinity = {
        blue: new Set(['room-engineering', 'room-ops', 'room-lobby']),
        green: new Set(['room-research', 'room-support']),
        orange: new Set(['room-content', 'room-engineering']),
        pink: new Set(['room-design', 'room-content']),
        purple: new Set(['room-planning', 'room-pods', 'room-research']),
        yellow: new Set(['room-support', 'room-lobby']),
    };
    const affinityBoost = tintRoomAffinity[tint]?.has(roomId) ? 1.8 : 0;
    const distancePenalty = Math.min(3.2, Math.hypot((agent.x || 50) - 50, (agent.y || 50) - 50) / 22);
    const routeBoost = Array.isArray(agent.routeWaypoints) && agent.routeWaypoints.length ? -0.6 : 0;
    const idleBoost = agent.state === 'idle' ? 0.8 : 0;
    return affinityBoost + idleBoost + routeBoost - distancePenalty;
}

function officeAssignTaskToAgent(task, agent, now) {
    if (!task || !agent || task.status !== 'queued') return false;
    task.status = 'active';
    task.assignedAgentId = agent.id;
    task.startedAt = Date.now();
    agent.taskId = task.id;
    const routed = officeRouteAgentToRoom(agent, task.roomId, {
        intent: 'task',
        speed: officeRandomRange(3.2, 4.3),
    });
    if (!routed) return false;
    const roomTheme = officeRoomById(task.roomId)?.theme || '';
    const pickupLine = officeBanterForAgent(agent, 'task_pickup', {
        roomTheme,
        taskTitle: task.title,
    }) || officePick(OFFICE_DIALOGUE.pickup).replace('{room}', task.roomLabel);
    officeSpeak(agent, pickupLine, { priority: true, durationMs: 1400 });
    officeBusEmit('task.assigned', {
        taskId: task.id,
        roomId: task.roomId,
        roomLabel: task.roomLabel,
        agentId: agent.id,
        agentName: agent.name,
        score: Number((officeTaskPriorityScore(task) + officeAgentTaskFitScore(agent, task)).toFixed(3)),
    }, now);
    officeState.tasksDirty = true;
    return true;
}

function officeAssignQueuedTasks(now = performance.now()) {
    if (!officeState) return;
    const queued = officeState.tasks
        .filter((task) => task.status === 'queued')
        .sort((a, b) => officeTaskPriorityScore(b) - officeTaskPriorityScore(a));
    if (!queued.length) return;

    const availableAgents = officeState.agents.filter((agent) => (
        !agent.taskId
        && (agent.state === 'idle' || (agent.state === 'walking' && agent.intent === 'wander'))
    ));
    if (!availableAgents.length) return;

    const openTasks = [...queued];
    availableAgents.forEach((agent) => {
        let bestIndex = -1;
        let bestScore = Number.NEGATIVE_INFINITY;
        openTasks.forEach((task, index) => {
            const score = officeTaskPriorityScore(task) + officeAgentTaskFitScore(agent, task);
            if (score > bestScore) {
                bestScore = score;
                bestIndex = index;
            }
        });
        if (bestIndex < 0) return;
        const [nextTask] = openTasks.splice(bestIndex, 1);
        if (!nextTask) return;
        officeAssignTaskToAgent(nextTask, agent, now);
    });
}

// RECOVERED (2026-03-18): Agent animations — were in dead app_parts/part-014.js.
// Called by officeTickAgent() and officeFinishTask() for spawn/teleport effects.
function officeBeginSpawnSequence(agent, now) {
    if (!agent) return;
    const startedAt = Number(now) || performance.now();
    agent.state = 'spawning';
    agent.intent = agent.taskId ? 'task' : (safeString(agent.intent) || 'wander');
    agent.spawnUntil = startedAt + officeRandomRange(520, 920);
    agent.teleportUntil = 0;
    agent.bumpUntil = Math.max(Number(agent.bumpUntil) || 0, startedAt + 280);
    agent.jumpUntil = Math.max(Number(agent.jumpUntil) || 0, startedAt + 320);
    if (!agent.speech) {
        const intent = safeString(agent.intent);
        const line = intent.includes('notif')
            ? 'Heads up. New notification.'
            : (agent.taskId ? 'On it.' : 'Back on deck.');
        officeSpeak(agent, line, { priority: true, durationMs: 1300 });
    }
}

function officeBeginTeleportSequence(agent, now) {
    if (!agent) return;
    const startedAt = Number(now) || performance.now();
    agent.state = 'teleporting';
    agent.intent = 'teleport';
    agent.teleportUntil = startedAt + officeRandomRange(420, 700);
    agent.spawnUntil = 0;
    agent.routeWaypoints = [];
    agent.routeDestinationNodeId = '';
    agent.bumpUntil = Math.max(Number(agent.bumpUntil) || 0, startedAt + 200);
}

function officeFinishTask(agent, now) {
    if (!officeState || !agent?.taskId) return;
    const task = officeState.tasks.find((entry) => entry.id === agent.taskId);
    if (task) {
        task.status = 'done';
        task.completedAt = Date.now();
        officeState.tasksDirty = true;
    }
    agent.taskId = '';
    agent.workUntil = 0;
    if (officeChance(0.38)) {
        const targetRoom = officeChance(0.5) ? 'room-coffee' : 'room-break';
        officeRouteAgentToRoom(agent, targetRoom, {
            intent: 'break',
            speed: officeRandomRange(2.8, 3.8),
        });
        officeSpeak(agent, officeBanterForAgent(agent, 'break', { roomTheme: targetRoom }), { durationMs: 1700 });
        agent.nextBreakAt = now + officeRandomRange(26_000, 62_000);
    } else {
        agent.state = 'idle';
        agent.intent = 'wander';
        agent.idleUntil = now + officeRandomRange(800, 1900);
        officeSpeak(agent, officeBanterForAgent(agent, 'task_done', { taskTitle: task?.title || '' }), { durationMs: 1500 });
    }
    officeBusEmit('task.completed', {
        taskId: task?.id || '',
        roomId: task?.roomId || '',
        roomLabel: task?.roomLabel || '',
        agentId: agent.id,
        agentName: agent.name,
    }, now);
}

function officeTrimTasks() {
    if (!officeState) return;
    let changed = false;
    const completionCutoff = Date.now() - (3 * 60 * 1000);
    const before = officeState.tasks.length;
    officeState.tasks = officeState.tasks.filter((task) => (
        task.status !== 'done' || task.completedAt >= completionCutoff
    ));
    if (officeState.tasks.length !== before) {
        changed = true;
    }
    while (officeState.tasks.length > OFFICE_MAX_TASKS) {
        const doneIndex = officeState.tasks.findIndex((task) => task.status === 'done');
        if (doneIndex >= 0) {
            officeState.tasks.splice(doneIndex, 1);
        } else {
            officeState.tasks.shift();
        }
        changed = true;
    }
    if (changed) {
        officeState.tasksDirty = true;
    }
}

function officeTickBreakSchedules(now) {
    if (!officeState) return;
    officeState.agents.forEach((agent) => {
        if (!agent || agent.state === 'runaway') return;
        if (agent.taskId) return;
        const nextBreakAt = Number(agent.nextBreakAt) || 0;
        if (nextBreakAt <= 0 || now < nextBreakAt) return;
        if (!(agent.state === 'idle' || (agent.state === 'walking' && agent.intent === 'wander'))) return;
        const breakRoomId = officeChance(0.56) ? 'room-coffee' : 'room-break';
        const routed = officeRouteAgentToRoom(agent, breakRoomId, {
            intent: 'break',
            speed: officeRandomRange(2.8, 3.8),
        });
        agent.nextBreakAt = now + officeRandomRange(42_000, 94_000);
        if (!routed) return;
        const line = officeBanterForAgent(agent, 'break', {
            roomTheme: officeRoomById(breakRoomId)?.theme || '',
        });
        officeSpeak(agent, line, { priority: true, durationMs: 1320 });
        officeBusEmit('agent.break_cycle', {
            agentId: agent.id,
            agentName: agent.name,
            roomId: breakRoomId,
        }, now);
    });
}

function officeTickSocialIdle(now) {
    if (!officeState) return;
    if ((now - (officeState.lastSocialTickAt || 0)) < 360) return;
    officeState.lastSocialTickAt = now;
    if (now < (officeState.nextSocialWindowAt || 0)) return;

    const candidates = officeState.agents.filter((agent) => (
        agent
        && !agent.taskId
        && !agent.speech
        && (agent.state === 'idle' || (agent.state === 'walking' && agent.intent === 'wander'))
        && now >= (Number(agent.nextSocialAt) || 0)
    ));
    if (candidates.length < 2) return;

    let bestPair = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let i = 0; i < candidates.length; i += 1) {
        const a = candidates[i];
        const roomA = officeCurrentRoomForAgent(a);
        if (!roomA) continue;
        for (let j = i + 1; j < candidates.length; j += 1) {
            const b = candidates[j];
            const roomB = officeCurrentRoomForAgent(b);
            if (!roomB || roomA.id !== roomB.id) continue;
            const distance = Math.hypot(a.x - b.x, a.y - b.y);
            if (distance > 12.2) continue;
            if (distance < bestDistance) {
                bestDistance = distance;
                bestPair = { a, b, room: roomA };
            }
        }
    }
    if (!bestPair) return;

    const lead = officeChance(0.5) ? bestPair.a : bestPair.b;
    const reply = lead.id === bestPair.a.id ? bestPair.b : bestPair.a;
    const leadLine = officeBanterForAgent(lead, 'social_lead', { roomTheme: bestPair.room.theme });
    const replyLine = officeBanterForAgent(reply, 'social_reply', { roomTheme: bestPair.room.theme });

    let spoke = false;
    if (officeSpeak(lead, leadLine, { priority: true, durationMs: 1320 })) {
        spoke = true;
    }
    if (officeChance(0.86)) {
        window.setTimeout(() => {
            if (!officeState) return;
            officeSpeak(reply, replyLine, { priority: true, durationMs: 1180 });
        }, officeRandomRange(320, 620));
    }

    [lead, reply].forEach((agent) => {
        agent.nextSocialAt = now + officeRandomRange(15_000, 32_000);
    });
    officeState.nextSocialWindowAt = now + officeRandomRange(5_000, 12_000);

    if (spoke) {
        officeBusEmit('agent.social', {
            roomId: bestPair.room.id,
            roomTheme: bestPair.room.theme,
            speakerId: lead.id,
            responderId: reply.id,
        }, now);
    }
}

function officeRenderDebugOverlay(now = performance.now()) {
    if (!officeState || !officeDebugOverlay) return;
    if (!officeState.debugOverlayOpen) {
        officeDebugOverlay.classList.add('hidden');
        return;
    }
    if ((now - (officeState.lastDebugRenderAt || 0)) < OFFICE_DEBUG_REFRESH_MS) return;
    officeState.lastDebugRenderAt = now;
    officeDebugOverlay.classList.remove('hidden');

    const activeTasks = officeState.tasks.filter((task) => task.status === 'active').length;
    const queuedTasks = officeState.tasks.filter((task) => task.status === 'queued').length;
    const walking = officeState.agents.filter((agent) => agent.state === 'walking').length;
    const working = officeState.agents.filter((agent) => agent.state === 'working').length;
    const collisions = officeState.agents.filter((agent) => now < (agent.bumpUntil || 0)).length;
    const fps = Number(officeState.debugFrameRate || 0).toFixed(1);
    const stream = officeState.stream || {};
    const streamStatus = stream.connected ? 'live' : (stream.connecting ? 'connecting' : 'retry');
    const streamSeq = Number(stream.lastSeq) || 0;
    const events = officeState.officeEvents.slice(-3).reverse();
    const eventLines = events.map((event) => {
        const stamp = new Date(event.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        return `<li>[${stamp}] ${escapeHtml(event.type)}</li>`;
    }).join('');

    officeDebugOverlay.innerHTML = `
        <div class="office-debug-head">Office Debug</div>
        <div class="office-debug-grid">
            <span>FPS <strong>${fps}</strong></span>
            <span>Agents <strong>${officeState.agents.length}</strong></span>
            <span>Walking <strong>${walking}</strong></span>
            <span>Working <strong>${working}</strong></span>
            <span>Queued <strong>${queuedTasks}</strong></span>
            <span>Active <strong>${activeTasks}</strong></span>
            <span>Lane Claims <strong>${officeState.laneReservations.size}</strong></span>
            <span>Bumps <strong>${collisions}</strong></span>
            <span>Stream <strong>${streamStatus}</strong></span>
            <span>Seq <strong>${streamSeq}</strong></span>
        </div>
        <ul class="office-debug-events">${eventLines || '<li>No recent events</li>'}</ul>
    `;
}

function officeMissionStatusToOfficeState(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (status === 'active' || status === 'running' || status === 'in_progress' || status === 'executing' || status === 'claimed' || status === 'awaiting_proof') return 'working';
    if (status === 'idle' || status === 'waiting' || status === 'queued' || status === 'requested' || status === 'classified') return 'idle';
    if (status === 'blocked' || status === 'paused' || status === 'awaiting_approval') return 'yield';
    if (status === 'break') return 'break';
    return '';
}

function officeMissionStatusToTaskStatus(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (new Set(['completed', 'complete', 'done', 'succeeded', 'verified', 'success']).has(status)) return 'done';
    if (new Set(['running', 'active', 'executing', 'claimed', 'in_progress', 'awaiting_proof', 'awaiting_approval', 'blocked']).has(status)) return 'active';
    return 'queued';
}

function officeMissionEntryText(entry) {
    return safeString(entry?.task || entry?.summary || entry?.title || entry?.name || entry?.id || 'Mission task');
}

function officeMissionRoomToOfficeRoomId(roomRaw, entry = {}) {
    const missionRoom = safeString(roomRaw || entry?.room || entry?.room_id).toLowerCase();
    return OFFICE_MISSION_ROOM_TO_OFFICE_ROOM[missionRoom] || 'room-lobby';
}

function officeMissionAgentName(entry) {
    const name = safeString(entry?.name || entry?.claimed_owner || entry?.claimedOwner || entry?.bot_name || entry?.botName);
    if (name && !/^worker$/i.test(name)) return name.slice(0, 24);
    const botId = safeString(entry?.bot_id || entry?.botId);
    if (botId) return officeTaskTitle(botId.replace(/[_-]+/g, ' ')).slice(0, 24);
    const kind = safeString(entry?.kind || entry?.source || 'Worker');
    const id = safeString(entry?.execution_id || entry?.job_id || entry?.run_id || entry?.objective_id || entry?.id);
    const suffix = id ? String(officeStableHash(id) % 997).padStart(3, '0') : '';
    return `${officeTaskTitle(kind.replace(/[_-]+/g, ' '))}${suffix ? ` ${suffix}` : ''}`.slice(0, 24);
}

function officeMissionAgentStableId(entry) {
    const botId = safeString(entry?.bot_id || entry?.botId);
    if (botId) return `bot-${officeAgentHandle(botId)}`;
    const name = officeMissionAgentName(entry);
    const handle = officeAgentHandle(name);
    if (handle && !new Set(['worker', 'agent', 'taskmanager']).has(handle)) {
        const existing = officeFindAgentByHandle(handle);
        if (existing) return existing.id;
        return `agent-${handle}`;
    }
    const kind = officeAgentHandle(entry?.kind || entry?.source || 'mission');
    const id = safeString(entry?.execution_id || entry?.job_id || entry?.run_id || entry?.objective_id || entry?.id || name);
    return `${kind || 'mission'}-${officeStableHash(id)}`;
}

function officeMissionSpecialty(entry, roomId) {
    const kind = safeString(entry?.kind || entry?.source).replace(/[_-]+/g, ' ');
    const room = officeRoomById(roomId);
    if (kind) return officeTaskTitle(kind).slice(0, 64);
    return safeString(room?.meta || room?.label || 'Generalist').slice(0, 64);
}

function officeEnsureMissionAgent(entry, roomId, now = performance.now()) {
    if (!officeState) return null;
    const stableId = officeMissionAgentStableId(entry);
    const name = officeMissionAgentName(entry);
    let agent = officeGetAgentById(stableId);
    if (!agent && name && !/^worker(?:\s+\d+)?$/i.test(name)) {
        agent = officeFindAgentByHandle(name);
    }
    if (agent) {
        agent.remoteIds = agent.remoteIds && typeof agent.remoteIds === 'object' ? agent.remoteIds : {};
        const remoteId = safeString(entry?.id);
        if (remoteId) agent.remoteIds[remoteId] = remoteId;
        agent.source = safeString(entry?.source || entry?.kind || agent.source || 'mission');
        agent.specialty = safeString(agent.specialty || officeMissionSpecialty(entry, roomId) || 'Generalist').slice(0, 64);
        agent.personality = safeString(agent.personality || 'Helpful, direct, and persistent.').slice(0, 160);
        return agent;
    }

    const seedIndex = officeStableHash(stableId) % Math.max(1, OFFICE_AGENT_SEEDS.length);
    const seed = OFFICE_AGENT_SEEDS[seedIndex] || OFFICE_AGENT_SEEDS[0] || {};
    const roomNav = officeState.roomNav?.get(roomId);
    const slotIds = Array.isArray(roomNav?.slotNodeIds) ? roomNav.slotNodeIds : [];
    const slotId = slotIds.length ? slotIds[officeStableHash(stableId) % slotIds.length] : roomNav?.centerNodeId;
    const spawn = officeState.navMap?.get(slotId) || officeState.navMap?.get(roomNav?.centerNodeId) || { x: 50, y: 50 };
    agent = {
        id: stableId,
        name,
        color: /^#[0-9a-f]{6}$/i.test(safeString(seed.color)) ? seed.color : '#9ad8ff',
        costume: new Set(OFFICE_AGENT_COSTUME_POOL).has(seed.costume) ? seed.costume : 'none',
        tint: safeString(seed.tint || officeAgentTintFromColor(seed.color || '#9ad8ff')),
        specialty: officeMissionSpecialty(entry, roomId),
        personality: safeString(seed.personality || 'Helpful, direct, and persistent.').slice(0, 160),
        source: safeString(entry?.source || entry?.kind || 'mission'),
        remoteIds: {},
        remoteRoomId: roomId,
        remoteStatus: safeString(entry?.status),
        lastMissionSummary: officeMissionEntryText(entry).slice(0, 180),
        x: officeClamp(Number(spawn.x) || 50, 3, 97),
        y: officeClamp(Number(spawn.y) || 50, 5, 96),
        targetX: officeClamp(Number(spawn.x) || 50, 3, 97),
        targetY: officeClamp(Number(spawn.y) || 50, 5, 96),
        speed: officeRandomRange(2.35, 3.75),
        facing: officeChance(0.5) ? 1 : -1,
        laneBias: officeRandomRange(-0.65, 0.65),
        state: 'idle',
        intent: 'wander',
        taskId: '',
        workStreak: 0,
        workUntil: 0,
        breakUntil: 0,
        idleUntil: now + officeRandomRange(450, 1700),
        nextAmbientAt: now + officeRandomRange(3500, 9000),
        nextWorkLineAt: now + officeRandomRange(2400, 6200),
        nextSocialAt: now + officeRandomRange(5000, 14000),
        nextBreakAt: now + officeRandomRange(34_000, 82_000),
        speech: null,
        bumpUntil: 0,
        jumpUntil: 0,
        collisionCooldownUntil: 0,
        crowdReliefUntil: 0,
        yieldUntil: 0,
        yieldResumeIntent: '',
        stuckSince: 0,
        lastMoveX: officeClamp(Number(spawn.x) || 50, 3, 97),
        lastMoveY: officeClamp(Number(spawn.y) || 50, 5, 96),
        returnAfterRunAt: 0,
        runawayPhase: '',
        runawayExitX: 0,
        runawayExitY: 0,
        currentNodeId: officeFindNearestNode(officeState.navMap, Number(spawn.x) || 50, Number(spawn.y) || 50),
        routeWaypoints: [],
        routeDestinationNodeId: '',
        reservedLaneEdgeKey: '',
    };
    const remoteId = safeString(entry?.id);
    if (remoteId) agent.remoteIds[remoteId] = remoteId;
    officeApplyStoredAgentPrefs([agent], loadStoredOfficeAgentPrefs());
    officeState.agents.push(agent);
    if (!officeState.selectedAgentId) {
        officeState.selectedAgentId = agent.id;
    }
    officeRenderAgentSelector(officeState.selectedAgentId);
    return agent;
}

function officeUpsertMissionTask(entry, agent, roomId, now = performance.now()) {
    if (!officeState || !agent) return null;
    const remoteId = safeString(entry?.id || entry?.execution_id || entry?.job_id || entry?.run_id || entry?.objective_id || `${agent.id}:${officeMissionEntryText(entry)}`);
    const taskId = `mission:${remoteId}`;
    const room = officeRoomById(roomId) || officeRoomById('room-lobby');
    const taskText = officeMissionEntryText(entry);
    const status = officeMissionStatusToTaskStatus(entry?.status);
    let task = officeState.tasks.find((entryTask) => safeString(entryTask?.id) === taskId);
    if (!task) {
        task = {
            id: taskId,
            title: officeTaskTitle(taskText),
            rawText: taskText,
            source: safeString(entry?.source || entry?.kind || 'mission-stream'),
            roomId: room?.id || 'room-lobby',
            roomLabel: room?.label || 'Main Lobby',
            status,
            assignedAgentId: agent.id,
            createdAt: Date.now(),
            startedAt: status === 'active' ? Date.now() : 0,
            completedAt: status === 'done' ? Date.now() : 0,
        };
        officeState.tasks.push(task);
        return task;
    }
    task.title = officeTaskTitle(taskText);
    task.rawText = taskText;
    task.source = safeString(entry?.source || entry?.kind || task.source || 'mission-stream');
    task.roomId = room?.id || 'room-lobby';
    task.roomLabel = room?.label || 'Main Lobby';
    task.assignedAgentId = agent.id;
    if (task.status !== status) {
        task.status = status;
    }
    if (status === 'active' && !task.startedAt) {
        task.startedAt = Date.now();
    }
    if (status === 'done' && !task.completedAt) {
        task.completedAt = Date.now();
    }
    return task;
}

function officeRefreshDraftMapAfterMissionChange(now = performance.now(), options = {}) {
    if (typeof officeRenderDraftMapScene !== 'function') return;
    const requiresSceneRender = options?.requiresSceneRender === true;
    const draftMapActive = typeof officeDraftMapPlane === 'function' && Boolean(officeDraftMapPlane());
    if (!draftMapActive || requiresSceneRender || typeof officeRenderDraftAgentLayerOnly !== 'function') {
        officeRenderDraftMapScene();
        return;
    }
    if (typeof officeEnsureDraftMapState === 'function') {
        const state = officeEnsureDraftMapState();
        state.missionAgentLayerDirty = true;
    }
}

function officeMissionDraftMapActive() {
    return typeof officeDraftMapPlane === 'function' && Boolean(officeDraftMapPlane());
}

function officeMissionAgentAlreadyDraftRouting(agent, roomId, task) {
    if (!officeMissionDraftMapActive() || !agent) return false;
    const taskId = safeString(task?.id || agent.taskId);
    const motion = agent.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    return safeString(agent.remoteRoomId) === safeString(roomId)
        && safeString(agent.taskId) === taskId
        && taskId
        && safeString(motion?.targetSignature).includes(`|${safeString(roomId)}|${taskId}|`)
        && (
            Array.isArray(motion?.route)
            || safeString(agent.intent) === 'task'
            || safeString(agent.state) === 'walking'
        );
}

function officeReconcileFromMissionPayload(payload, now = performance.now()) {
    if (!officeState || !payload || typeof payload !== 'object') return false;
    let changed = false;
    let requiresSceneRender = false;

    const rooms = Array.isArray(payload.rooms) ? payload.rooms : [];
    rooms.forEach((entry) => {
        const id = safeString(entry?.id);
        if (!id) return;
        const room = officeRoomById(officeMissionRoomToOfficeRoomId(id, entry));
        if (!room) return;
        const nextLabel = safeString(entry?.label);
        if (nextLabel && id === room.id && room.label !== nextLabel) {
            room.label = nextLabel;
            changed = true;
            requiresSceneRender = true;
        }
    });

    const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
    tasks.forEach((entry) => {
        const id = safeString(entry?.id);
        if (!id) return;
        const existing = officeState.tasks.find((task) => task.id === id);
        if (existing) {
            const nextStatus = safeString(entry?.status).toLowerCase();
            if (nextStatus && nextStatus !== existing.status) {
                existing.status = nextStatus;
                changed = true;
            }
            const assignedAgentId = safeString(entry?.assigned_agent_id || entry?.assignedAgentId);
            if (assignedAgentId && existing.assignedAgentId !== assignedAgentId) {
                existing.assignedAgentId = assignedAgentId;
                changed = true;
            }
            return;
        }
        const label = safeString(entry?.title || entry?.name || id);
        const roomId = officeMissionRoomToOfficeRoomId(entry?.room || entry?.room_id, entry);
        const room = officeRoomById(roomId) || officeRoomById('room-lobby');
        officeState.tasks.push({
            id,
            title: officeTaskTitle(label),
            rawText: label,
            source: 'mission-stream',
            roomId: room?.id || 'room-lobby',
            roomLabel: room?.label || 'Main Lobby',
            status: safeString(entry?.status).toLowerCase() || 'queued',
            assignedAgentId: safeString(entry?.assigned_agent_id || entry?.assignedAgentId),
            createdAt: Date.now(),
            startedAt: 0,
            completedAt: 0,
        });
        changed = true;
    });

    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    agents.forEach((entry) => {
        const roomId = officeMissionRoomToOfficeRoomId(entry?.room || entry?.room_id, entry);
        const agent = officeEnsureMissionAgent(entry, roomId, now);
        if (!agent) return;
        const task = officeUpsertMissionTask(entry, agent, roomId, now);
        const mappedState = officeMissionStatusToOfficeState(entry?.status);
        const taskStatus = officeMissionStatusToTaskStatus(entry?.status);
        const summary = officeMissionEntryText(entry).slice(0, 180);
        agent.remoteRoomId = roomId;
        agent.remoteStatus = safeString(entry?.status || mappedState || taskStatus);
        agent.lastMissionSummary = summary;
        agent.source = safeString(entry?.source || entry?.kind || agent.source || 'mission');
        agent.specialty = safeString(agent.specialty || officeMissionSpecialty(entry, roomId) || 'Generalist').slice(0, 64);
        if (task) {
            agent.taskId = taskStatus === 'done' ? '' : task.id;
        }
        if (taskStatus === 'done') {
            if (agent.state === 'working' || agent.intent === 'task') {
                agent.state = 'idle';
                agent.intent = 'wander';
                agent.idleUntil = now + officeRandomRange(900, 2200);
            }
            if (task) {
                task.status = 'done';
                task.completedAt = task.completedAt || Date.now();
            }
            changed = true;
            return;
        }
        if (mappedState === 'yield') {
            if (agent.state !== 'yield') {
                officeSetYieldState(agent, now, officeRandomRange(-0.8, 0.8), officeRandomRange(-0.8, 0.8));
            }
            agent.taskId = task?.id || agent.taskId;
            agent.workUntil = now + 24_000;
            changed = true;
            return;
        }
        if (taskStatus === 'active' || mappedState === 'working') {
            const currentRoom = officeCurrentRoomForAgent(agent);
            const alreadyHeadingThere = safeString(agent.routeDestinationNodeId)
                && officeState.roomNav?.get(roomId)?.slotNodeIds?.includes(safeString(agent.routeDestinationNodeId));
            const draftAlreadyHeadingThere = officeMissionAgentAlreadyDraftRouting(agent, roomId, task);
            if (draftAlreadyHeadingThere) {
                agent.intent = 'task';
                if (agent.state !== 'working') agent.state = 'walking';
            } else if (safeString(currentRoom?.id) !== roomId && !alreadyHeadingThere) {
                officeRouteAgentToRoom(agent, roomId, {
                    intent: 'task',
                    speed: officeRandomRange(3.2, 4.3),
                });
            } else if (agent.state !== 'walking') {
                agent.state = 'working';
                agent.intent = 'task';
            }
            agent.taskId = task?.id || agent.taskId;
            agent.workUntil = now + 24_000;
            agent.nextWorkLineAt = now + officeRandomRange(1800, 4200);
            changed = true;
            return;
        }
        if (taskStatus === 'queued') {
            if (!agent.taskId && agent.state === 'idle') {
                officeRouteAgentToRoom(agent, roomId, {
                    intent: 'wander',
                    speed: officeRandomRange(2.5, 3.4),
                });
            }
            changed = true;
        }
    });

    if (changed) {
        officeTrimTasks();
        officeState.tasksDirty = true;
        officeRenderTaskList();
        officeRenderAgentSelector(officeState.selectedAgentId);
        officeRefreshDraftMapAfterMissionChange(now, { requiresSceneRender });
        officePersistAgentPrefs();
        officePersistRuntimeState(now, { force: true });
    }
    return changed;
}

function officeHandleMissionStreamLine(lineRaw) {
    if (!officeState) return;
    const line = safeString(lineRaw);
    if (!line) return;
    let parsed = null;
    try {
        parsed = JSON.parse(line);
    } catch {
        return;
    }
    if (!parsed || typeof parsed !== 'object') return;
    const type = safeString(parsed.type).toLowerCase() || 'snapshot';
    const seq = Number(parsed.seq) || 0;
    if (type === 'snapshot' && parsed.payload && typeof parsed.payload === 'object') {
        const changed = officeReconcileFromMissionPayload(parsed.payload);
        officeState.stream.lastSeq = seq || officeState.stream.lastSeq;
        officeBusEmit('stream.snapshot', {
            seq,
            changed,
        });
        return;
    }
    officeBusEmit('stream.event', {
        type,
        seq,
    });
}

function officeScheduleMissionStreamReconnect(delayMs = 0) {
    if (!officeState?.stream || !officeState.active) return;
    const stream = officeState.stream;
    if (stream.reconnectTimer) return;
    const retryMs = delayMs > 0
        ? delayMs
        : officeClamp(Number(stream.retryMs) || OFFICE_STREAM_RETRY_MIN_MS, OFFICE_STREAM_RETRY_MIN_MS, OFFICE_STREAM_RETRY_MAX_MS);
    stream.retryMs = Math.min(OFFICE_STREAM_RETRY_MAX_MS, Math.round(retryMs * 1.75));
    const timerId = window.setTimeout(() => {
        if (!officeState?.stream) return;
        officeState.stream.reconnectTimer = 0;
        void officeStartMissionStream();
    }, retryMs);
    // Guard against race: if another call beat us, cancel ours
    if (stream.reconnectTimer) {
        window.clearTimeout(timerId);
        return;
    }
    stream.reconnectTimer = timerId;
}

function officeStopMissionStream() {
    if (!officeState?.stream) return;
    const stream = officeState.stream;
    if (stream.reconnectTimer) {
        window.clearTimeout(stream.reconnectTimer);
        stream.reconnectTimer = 0;
    }
    if (stream.controller) {
        try {
            stream.controller.abort();
        } catch {
            // Ignore abort failures.
        }
    }
    stream.connected = false;
    stream.connecting = false;
    stream.controller = null;
}

async function officeStartMissionStream() {
    if (!officeState?.stream || !officeState.active) return;
    const stream = officeState.stream;
    if (stream.connecting || stream.connected) return;
    if (typeof fetch !== 'function' || typeof TextDecoder === 'undefined') return;

    stream.connecting = true;
    const controller = new AbortController();
    stream.controller = controller;
    const url = '/api/mission/stream?interval=1.8';

    try {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                Accept: 'application/x-ndjson',
            },
            signal: controller.signal,
            cache: 'no-store',
        });
        if (!response.ok || !response.body) {
            throw new Error(`mission_stream_http_${response.status}`);
        }

        stream.connected = true;
        stream.connecting = false;
        stream.retryMs = OFFICE_STREAM_RETRY_MIN_MS;
        stream.lastMessageAt = Date.now();
        officeBusEmit('stream.connected', { url });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (officeState && officeState.active && !controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            stream.lastMessageAt = Date.now();
            buffer += decoder.decode(value, { stream: true });
            let newlineIndex = buffer.indexOf('\n');
            while (newlineIndex >= 0) {
                const line = buffer.slice(0, newlineIndex).trim();
                buffer = buffer.slice(newlineIndex + 1);
                if (line) {
                    officeHandleMissionStreamLine(line);
                }
                newlineIndex = buffer.indexOf('\n');
            }
        }
    } catch (error) {
        if (!controller.signal.aborted) {
            officeBusEmit('stream.error', {
                reason: safeString(error?.message || error),
            });
        }
    } finally {
        if (!officeState?.stream) return;
        stream.connected = false;
        stream.connecting = false;
        stream.controller = null;
        if (officeState.active) {
            officeScheduleMissionStreamReconnect();
        }
    }
}

function officeTickAgent(agent, now, dt) {
    if (!agent) return;
    if (agent.state !== 'runaway') {
        officeSafeguardAgentPosition(agent, now, { reroute: false });
    }
    if (agent.state === 'runaway') {
        const arrived = officeMoveAgent(agent, dt);
        if (arrived && safeString(agent.runawayPhase) === 'to-hall') {
            agent.runawayPhase = 'exiting';
            officeSetAgentTarget(agent, agent.runawayExitX, agent.runawayExitY, {
                intent: 'runaway',
                speed: officeRandomRange(5.8, 7.2),
            });
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

