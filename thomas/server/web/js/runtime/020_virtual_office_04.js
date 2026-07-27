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
            const a = officeState.agents[i];
            const b = officeState.agents[j];
            if (!a || !b) continue;
            if (a.state === 'runaway' || b.state === 'runaway') continue;
            if (now < a.collisionCooldownUntil || now < b.collisionCooldownUntil) continue;
            const pairKey = officeCollisionPairKey(a.id, b.id);
            if (!pairKey) continue;
            if (now < (pairCooldowns.get(pairKey) || 0)) continue;

            let dx = b.x - a.x;
            let dy = b.y - a.y;
            let distance = Math.hypot(dx, dy);
            if (distance === 0) {
                dx = officeRandomRange(-1, 1);
                dy = officeRandomRange(-1, 1);
                distance = Math.max(0.001, Math.hypot(dx, dy));
            }
            if (distance >= minDistance) continue;

            const overlap = minDistance - distance;
            const nx = dx / distance;
            const ny = dy / distance;
            const separation = (overlap * 0.62) + 0.24;
            const prevAX = a.x;
            const prevAY = a.y;
            const prevBX = b.x;
            const prevBY = b.y;

            const aMovable = a.state === 'walking' || a.state === 'yield' || a.state === 'idle' || a.state === 'break';
            const bMovable = b.state === 'walking' || b.state === 'yield' || b.state === 'idle' || b.state === 'break';
            if (!aMovable && !bMovable) continue;

            if (aMovable && bMovable) {
                a.x = officeClamp(a.x - (nx * separation), 2, 98);
                a.y = officeClamp(a.y - (ny * separation), 4, 97);
                b.x = officeClamp(b.x + (nx * separation), 2, 98);
                b.y = officeClamp(b.y + (ny * separation), 4, 97);
            } else if (aMovable) {
                a.x = officeClamp(a.x - (nx * separation * 1.3), 2, 98);
                a.y = officeClamp(a.y - (ny * separation * 1.3), 4, 97);
            } else if (bMovable) {
                b.x = officeClamp(b.x + (nx * separation * 1.3), 2, 98);
                b.y = officeClamp(b.y + (ny * separation * 1.3), 4, 97);
            }

            if (aMovable) {
                const aConstrained = officeConstrainWalkableMove(a, prevAX, prevAY, a.x, a.y);
                a.x = officeClamp(aConstrained.x, 2, 98);
                a.y = officeClamp(aConstrained.y, 4, 97);
                officeSafeguardAgentPosition(a, now, { reroute: false });
            }
            if (bMovable) {
                const bConstrained = officeConstrainWalkableMove(b, prevBX, prevBY, b.x, b.y);
                b.x = officeClamp(bConstrained.x, 2, 98);
                b.y = officeClamp(bConstrained.y, 4, 97);
                officeSafeguardAgentPosition(b, now, { reroute: false });
            }

            const shouldYield = a.state === 'walking' && b.state === 'walking';
            if (shouldYield) {
                const aPriority = officeAgentTrafficPriority(a);
                const bPriority = officeAgentTrafficPriority(b);
                const yielder = aPriority <= bPriority ? a : b;
                const awayDir = yielder.id === a.id ? -1 : 1;
                officeSetYieldState(
                    yielder,
                    now,
                    nx * awayDir * officeRandomRange(0.6, 1.4),
                    ny * awayDir * officeRandomRange(0.6, 1.4),
                );
            }

            a.bumpUntil = now + 520;
            b.bumpUntil = now + 520;
            a.collisionCooldownUntil = now + officeRandomRange(820, 1380);
            b.collisionCooldownUntil = now + officeRandomRange(820, 1380);
            pairCooldowns.set(pairKey, now + officeRandomRange(
                OFFICE_COLLISION_PAIR_COOLDOWN_MIN,
                OFFICE_COLLISION_PAIR_COOLDOWN_MAX,
            ));
            officePulseHaptic([10, 22, 10]);
            officeBusEmit('agent.collision', {
                pairKey,
                aId: a.id,
                bId: b.id,
                aState: a.state,
                bState: b.state,
                distance: Number(distance.toFixed(3)),
            }, now);

            if (now >= officeState.collisionSpeechCooldownUntil) {
                const speaker = officeChance(0.5) ? a : b;
                const line = officeBanterForAgent(speaker, 'collision');
                if (officeSpeak(speaker, line, { priority: true, durationMs: 1200 })) {
                    officePushChatLine(`${speaker.name}: ${line}`);
                    officeState.collisionSpeechCooldownUntil = now + 1050;
                }
            }
        }
    }
}

function officeDisperseCrowds(now) {
    if (!officeState) return;
    const activeAgents = officeState.agents.filter((agent) => (
        agent
        && agent.state !== 'runaway'
        && !agent.taskId
        && (
            agent.state === 'idle'
            || agent.state === 'break'
            || agent.state === 'yield'
            || (agent.state === 'walking' && safeString(agent.intent) === 'wander')
        )
    ));
    if (activeAgents.length < OFFICE_CROWD_RELIEF_NEIGHBORS) return;

    let redirected = 0;
    activeAgents.forEach((agent) => {
        if (redirected >= 3) return;
        if (now < (agent.crowdReliefUntil || 0)) return;

        const nearby = activeAgents.filter((other) => (
            other.id !== agent.id
            && Math.hypot(other.x - agent.x, other.y - agent.y) <= OFFICE_CROWD_RELIEF_RADIUS
        ));
        if (nearby.length < (OFFICE_CROWD_RELIEF_NEIGHBORS - 1)) return;

        let centerX = agent.x;
        let centerY = agent.y;
        nearby.forEach((other) => {
            centerX += other.x;
            centerY += other.y;
        });
        const total = nearby.length + 1;
        centerX /= total;
        centerY /= total;

        const awayX = agent.x - centerX;
        const awayY = agent.y - centerY;
        const awayLen = Math.max(0.001, Math.hypot(awayX, awayY));
        const randomBias = officeRandomRange(-0.58, 0.58);
        const baseAngle = Math.atan2(awayY / awayLen, awayX / awayLen) + randomBias;
        const scatterDistance = officeRandomRange(4.8, 9.4);
        const proposed = officeNearestWalkablePoint(
            agent.x + (Math.cos(baseAngle) * scatterDistance),
            agent.y + (Math.sin(baseAngle) * scatterDistance),
            agent.x,
            agent.y,
        );
        officeSetAgentTarget(agent, proposed.x, proposed.y, {
            intent: 'wander',
            speed: Math.max(2.35, agent.speed),
        });
        agent.collisionCooldownUntil = now + officeRandomRange(650, 1100);
        agent.crowdReliefUntil = now + officeRandomRange(
            OFFICE_CROWD_RELIEF_COOLDOWN_MS,
            OFFICE_CROWD_RELIEF_COOLDOWN_MS + 900,
        );
        redirected += 1;
    });
}

function officeDraftAgentRouteActive(agent) {
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    return Boolean(
        motion
        && Array.isArray(motion.route)
        && Number(motion.routeIndex) < motion.route.length,
    );
}

function officeTickDraftAgentTaskState(agent, now) {
    if (!agent || agent.state === 'runaway') return;
    const routeActive = officeDraftAgentRouteActive(agent);
    const intent = safeString(agent.intent);
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    const taskId = safeString(agent.taskId);
    const taskSignatureArrived = taskId
        && motion
        && !routeActive
        && safeString(motion.targetSignature).includes(`|${taskId}|`)
        && (Number(now) - (Number(motion.arrivedAt) || Number(now))) >= 120;

    if (agent.state === 'yield') {
        if (now >= agent.yieldUntil) {
            agent.state = 'idle';
            agent.intent = 'wander';
            agent.yieldUntil = 0;
            agent.yieldResumeIntent = '';
        }
        return;
    }

    if (agent.state === 'walking' && intent === 'task' && taskSignatureArrived) {
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

    if (agent.state === 'walking' && intent === 'break' && motion && !routeActive && (Number(motion.arrivedAt) || 0) > 0) {
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

    if (agent.state === 'working') {
        if (now >= agent.workUntil) {
            officeFinishTask(agent, now);
            return;
        }
        if (now >= agent.nextWorkLineAt) {
            const room = typeof officeDraftSpaceForAgent === 'function'
                ? officeRoomById(officeDraftRoomIdForAgent(agent))
                : officeCurrentRoomForAgent(agent);
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
            agent.idleUntil = now + officeRandomRange(900, 2200);
            return;
        }
        if (now >= agent.nextWorkLineAt) {
            const room = typeof officeDraftSpaceForAgent === 'function'
                ? officeRoomById(officeDraftRoomIdForAgent(agent))
                : officeCurrentRoomForAgent(agent);
            officeSpeak(agent, officeBanterForAgent(agent, 'break', {
                roomTheme: room?.theme || room?.kind || '',
            }));
            agent.nextWorkLineAt = now + officeRandomRange(2600, 5600);
        }
    }
}

function officeTickDraftAgentTaskStates(now) {
    if (!officeState || !Array.isArray(officeState.agents)) return;
    officeState.agents.forEach((agent) => officeTickDraftAgentTaskState(agent, now));
}

function officeTick(now, dt, options = {}) {
    if (!officeState) return;
    const background = Boolean(options.background);
    const draftTimer = Boolean(options.draftTimer);
    officeState.debugFrameRate = dt > 0 ? (1 / dt) : 0;
    if (draftTimer) {
        officeAssignQueuedTasks(now);
        officeTickDraftAgentTaskStates(now);
        officeTrimTasks();
        if (!background) {
            const draftMapActive = typeof officeDraftMapPlane === 'function' && officeDraftMapPlane();
            if (draftMapActive && typeof officeRenderDraftAgentLayerOnly === 'function') {
                officeRenderDraftAgentLayerOnly(now);
            }
            if (officeState.tasksDirty) {
                officeState.tasksDirty = false;
                officeRenderTaskList();
            }
            officeRenderDebugOverlay(now);
        }
        officePersistRuntimeState(now);
        return;
    }
    officeTickBreakSchedules(now);
    officeAssignQueuedTasks(now);
    officeTickLaneReservations(now);
    officeTickSocialIdle(now);
    officeState.agents.forEach((agent) => officeTickAgent(agent, now, dt));
    officeHandleCollisions(now);
    officeState.agents.forEach((agent) => {
        if (!agent || agent.state === 'runaway') return;
        officeSafeguardAgentPosition(agent, now, { reroute: false });
    });
    officeDisperseCrowds(now);
    officeTrimTasks();
    if (!background) {
        const draftMapActive = typeof officeDraftMapPlane === 'function' && officeDraftMapPlane();
        if (draftMapActive) {
            if (typeof officeRenderDraftAgentLayerOnly === 'function') {
                officeRenderDraftAgentLayerOnly(now);
            }
        } else {
            officeTickFollowCamera();
            officeTickCamera(dt);
            officePersistCameraState(now);
            officeRenderAgents(now);
            const shouldSyncRoomMeta = (now - (officeState.lastRoomMetaSyncAt || 0)) >= 220;
            if (shouldSyncRoomMeta) {
                officeState.lastRoomMetaSyncAt = now;
                officeUpdateRoomMeta();
            }
        }
        if (officeState.tasksDirty) {
            officeState.tasksDirty = false;
            officeRenderTaskList();
            if (!draftMapActive) {
                officeState.lastRoomMetaSyncAt = now;
                officeUpdateRoomMeta();
            }
        }
        officeRenderDebugOverlay(now);
    }
    officePersistRuntimeState(now);
}

function officeEnsureBackgroundTickTimer() {
    if (!officeState || officeState.backgroundTickTimerId) return;
    officeState.backgroundTickTimerId = window.setInterval(() => {
        if (!officeState) return;
        if (!document.hidden) return;
        const wallNow = Date.now();
        const lastWall = Number(officeState.lastWallClockTickAt) || wallNow;
        const dt = officeClamp((wallNow - lastWall) / 1000, 0.18, 1.45);
        officeState.lastWallClockTickAt = wallNow;
        const nowPerf = performance.now();
        officeState.lastFrameAt = nowPerf;
        officeTick(nowPerf, dt, { background: true });
    }, OFFICE_BACKGROUND_TICK_MS);
}

function officeStopBackgroundTickTimer() {
    if (!officeState) return;
    if (officeState.backgroundTickTimerId) {
        window.clearInterval(officeState.backgroundTickTimerId);
        officeState.backgroundTickTimerId = 0;
    }
}

const OFFICE_DRAFT_MOTION_TIMER_MS = 48;
const OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS = 260;

function officeDraftMapLoopActive() {
    return typeof officeDraftMapPlane === 'function'
        && officeDraftMapPlane()
        && !document.hidden;
}

function officeEnsureDraftMotionTimer() {
    if (!officeState) return;
    if (!officeState.lastDraftMotionWallAt) {
        officeState.lastDraftMotionWallAt = Date.now();
    }
    if (!officeState.lastDraftOfficeTickAt) {
        officeState.lastDraftOfficeTickAt = performance.now();
    }
}

function officeStopDraftMotionTimer() {
    if (!officeState) return;
    if (officeState.draftMotionTimerId) {
        window.clearInterval(officeState.draftMotionTimerId);
        officeState.draftMotionTimerId = 0;
    }
    officeState.lastDraftMotionWallAt = 0;
    officeState.lastDraftMotionPaintWallAt = 0;
}

function officeTickDraftMotionFrame(frameNow, wallNow) {
    if (!officeState || !officeDraftMapLoopActive()) return;
    const currentFrameNow = Number(frameNow) || performance.now();
    const currentWallNow = Number(wallNow) || Date.now();
    const lastTickAt = Number(officeState.lastDraftOfficeTickAt) || 0;
    if (lastTickAt && currentFrameNow - lastTickAt < OFFICE_DRAFT_MOTION_TIMER_MS) return;
    const lastPaintWall = Number(officeState.lastDraftMotionPaintWallAt) || currentWallNow;
    if (currentWallNow - lastPaintWall > OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS) {
        officeState.lastDraftMotionWallAt = currentWallNow;
        officeState.lastDraftOfficeTickAt = currentFrameNow;
        return;
    }
    const lastWall = Number(officeState.lastDraftMotionWallAt) || currentWallNow;
    const dt = officeClamp((currentWallNow - lastWall) / 1000, 0.01, 0.12);
    officeState.lastDraftMotionWallAt = currentWallNow;
    officeState.lastWallClockTickAt = currentWallNow;
    officeState.lastDraftOfficeTickAt = currentFrameNow;
    officeTick(currentFrameNow, dt, { background: false, draftTimer: true });
}

function officeAnimationLoop(now) {
    if (!officeState) return;
    if (!officeState.lastFrameAt) {
        officeState.lastFrameAt = now;
    }
    const wallNow = Date.now();
    if (!officeState.lastWallClockTickAt) {
        officeState.lastWallClockTickAt = wallNow;
    }
    const frameNow = Number(now) || performance.now();
    const draftMapActive = officeDraftMapLoopActive();
    officeState.lastFrameAt = frameNow;
    if (draftMapActive) {
        officeState.lastDraftMotionPaintWallAt = wallNow;
        officeState.lastDraftMotionPaintAt = frameNow;
        officeEnsureDraftMotionTimer();
        officeTickDraftMotionFrame(frameNow, wallNow);
        officeState.rafId = window.requestAnimationFrame(officeAnimationLoop);
        return;
    }
    officeStopDraftMotionTimer();
    const dt = officeClamp((wallNow - officeState.lastWallClockTickAt) / 1000, 0.01, 0.16);
    officeState.lastWallClockTickAt = wallNow;
    officeTick(frameNow, dt, { background: false });
    officeState.rafId = window.requestAnimationFrame(officeAnimationLoop);
}

function officeStartLoop() {
    if (!officeState || officeState.rafId) return;
    officeEnsureBackgroundTickTimer();
    officeState.lastFrameAt = performance.now();
    officeState.lastWallClockTickAt = Date.now();
    officeState.rafId = window.requestAnimationFrame(officeAnimationLoop);
}

function officeChatPreviewSessionKey() {
    const sessionKey = safeString(officeChatPreviewSessionId || activeChatId || taskContinuityLatestSessionId || 'chat');
    return sessionKey || 'chat';
}

function officeHasChatPreviewTasks() {
    if (!officeState || !Array.isArray(officeState.tasks)) return false;
    if (!chatMessagesInner || !chatMessagesInner.querySelector('.message-row')) return false;
    const previewSessionId = officeChatPreviewSessionKey();
    const prefix = `chat-delegation:${previewSessionId}:`;
    return officeState.tasks.some((task) => safeString(task?.source).startsWith(prefix));
}

function officeTaskMatchesChatPreview(task) {
    const previewSessionId = officeChatPreviewSessionKey();
    return safeString(task?.source).startsWith(`chat-delegation:${previewSessionId}:`);
}

function officeShouldShowChatPreview() {
    return false;
}

function officeShowChatPreviewNow() {
    return;
}

function officeScheduleChatPreviewRefresh() {
    if (officeChatPreviewTimer) {
        window.clearTimeout(officeChatPreviewTimer);
        officeChatPreviewTimer = 0;
    }
    if (!officeShouldShowChatPreview()) return;
    const delay = Math.max(160, officeChatPreviewUntil - Date.now() + 120);
    officeChatPreviewTimer = window.setTimeout(() => {
        officeChatPreviewTimer = 0;
        officeRefreshSurfaceVisibility();
    }, delay);
}

function officeRefreshSurfaceVisibility() {
    const isOffice = sidebarNavMode === 'office';
    const showPreview = false;
    if (officeWorkspace) {
        officeWorkspace.classList.toggle('hidden', !(isOffice || showPreview));
        officeWorkspace.classList.toggle('chat-preview-active', showPreview && !isOffice);
    }
    if (appRoot) {
        appRoot.classList.toggle('office-active', isOffice);
        appRoot.classList.toggle('office-preview-active', showPreview && !isOffice);
    }
    document.body.classList.toggle('office-active', isOffice);
    if (sidebar) {
        sidebar.classList.toggle('mode-office', isOffice);
    }
    if (officeState) {
        officeState.active = isOffice || showPreview;
    }
    officeScheduleChatPreviewRefresh();
}

function officeNearestHallId(doorX, doorY) {
    let bestId = 'hall-south-mid';
    let bestDistance = Number.POSITIVE_INFINITY;
    OFFICE_HALL_NODES.forEach((node) => {
        const nodeId = safeString(node?.id);
        if (!nodeId.startsWith('hall-south') && nodeId !== 'hall-center' && nodeId !== 'hall-east' && nodeId !== 'hall-west') {
            return;
        }
        const distance = Math.hypot((Number(doorX) || 0) - node.x, (Number(doorY) || 0) - node.y);
        if (distance < bestDistance) {
            bestDistance = distance;
            bestId = node.id;
        }
    });
    return bestId;
}

function officeDynamicRoomSlotByIndex(index) {
    const baseSlot = OFFICE_DYNAMIC_ROOM_SLOTS[index];
    if (baseSlot) return { ...baseSlot };

    const generatedIndex = Math.max(0, index - OFFICE_DYNAMIC_ROOM_SLOTS.length);
    const roomW = 6.6;
    const roomH = 6.6;
    const gapX = 0.8;
    const gapY = 0.8;
    const cols = 4;
    const row = Math.floor(generatedIndex / cols);
    const col = generatedIndex % cols;
    const x = 46 + (col * (roomW + gapX));
    const y = 84 + (row * (roomH + gapY));
    if ((x + roomW) >= 96 || (y + roomH) >= 99.6) {
        return null;
    }
    return { x, y, w: roomW, h: roomH };
}

function officePlanRunawayExit(agent) {
    const exits = [
        { hallId: 'hall-west', x: OFFICE_RUNAWAY_EXIT_MARGIN, y: 48 },
        { hallId: 'hall-north-west', x: 20, y: OFFICE_RUNAWAY_EXIT_MARGIN },
        { hallId: 'hall-south-west', x: 24, y: 100 - OFFICE_RUNAWAY_EXIT_MARGIN },
        { hallId: 'hall-north-east', x: 82, y: OFFICE_RUNAWAY_EXIT_MARGIN },
        { hallId: 'hall-east', x: 100 - OFFICE_RUNAWAY_EXIT_MARGIN, y: 48 },
        { hallId: 'hall-south-east', x: 84, y: 100 - OFFICE_RUNAWAY_EXIT_MARGIN },
    ];
    const sourceX = Number(agent?.x) || 50;
    const sourceY = Number(agent?.y) || 50;
    const ranked = exits
        .map((candidate) => {
            const node = officeState?.navMap?.get(candidate.hallId);
            const nodeX = Number(node?.x) || 50;
            const nodeY = Number(node?.y) || 50;
            return {
                ...candidate,
                x: officeClamp(Number(candidate.x) || nodeX, OFFICE_RUNAWAY_EXIT_MARGIN, 100 - OFFICE_RUNAWAY_EXIT_MARGIN),
                y: officeClamp(Number(candidate.y) || nodeY, OFFICE_RUNAWAY_EXIT_MARGIN, 100 - OFFICE_RUNAWAY_EXIT_MARGIN),
                score: Math.hypot(nodeX - sourceX, nodeY - sourceY) + officeRandomRange(0, 6),
            };
        })
        .sort((a, b) => a.score - b.score);
    return ranked[0] || exits[0];
}

function officeCreateDynamicRoom(taskText) {
    if (!officeState) return officeRoomById('room-planning');
    if (officeState.dynamicRoomBySlug.size >= OFFICE_MAX_DYNAMIC_ROOMS) {
        return officeRoomById('room-planning') || officeState.rooms[0];
    }

    const baseTitle = officeTaskTitle(taskText);
    const labelRoot = baseTitle
        .replace(/[^a-zA-Z0-9\s-]/g, '')
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .join(' ');
    const label = labelRoot ? `${labelRoot} Pod` : `Task Pod ${officeState.dynamicIndex + 1}`;
    const slot = officeDynamicRoomSlotByIndex(officeState.dynamicIndex);
    if (!slot) {
        return officeRoomById('room-planning') || officeState.rooms[0];
    }
    const roomId = `room-dynamic-${officeState.dynamicIndex + 1}`;
    officeState.dynamicIndex += 1;
    const doorY = slot.y >= 70 ? slot.y : slot.y + slot.h;
    const doorX = slot.x + (slot.w / 2);
    const hallId = officeNearestHallId(doorX, doorY);

    const room = {
        id: roomId,
        label,
        meta: 'Auto-generated feature room',
        x: slot.x,
        y: slot.y,
        w: slot.w,
        h: slot.h,
        kind: 'work',
        theme: 'dynamic',
        doorX,
        doorY,
        hallId,
        dynamic: true,
    };
    officeState.rooms.push(room);
    officeState.roomById.set(room.id, room);
    officeState.dynamicRoomBySlug.set(
        officeTaskTitle(taskText)
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 42),
        room.id,
    );
    officeRefreshNavGraph();
    officeRecalculateMapSize({ preserveZoom: true, rerender: true });
    officePersistLayoutState();
    officeBusEmit('room.dynamic_created', {
        roomId: room.id,
        label: room.label,
        theme: room.theme,
    });
    return room;
}

function officeResolveExplicitRoom(roomRefRaw) {
    const roomRef = safeString(roomRefRaw).trim().toLowerCase();
    if (!roomRef) return null;
    const explicitId = OFFICE_EXPLICIT_ROOM_IDS[roomRef] || roomRef;
    return officeRoomById(explicitId)
        || officeState?.rooms?.find((room) => safeString(room?.label).trim().toLowerCase() === roomRef)
        || null;
}

function officeQueueTask(taskText, {
    source = 'office-chat',
    announce = false,
    preferredAgentId = '',
    roomId = 'room-planning',
    priority = 0,
} = {}) {
    if (!officeState) return null;
    const clean = safeString(taskText).replace(/\s+/g, ' ');
    if (!clean) return null;
    const room = officeResolveExplicitRoom(roomId) || officeRoomById('room-planning') || officeState?.rooms?.[0];
    if (!room) return null;

    const task = {
        id: `task-${officeState.taskCounter + 1}`,
        title: officeTaskTitle(clean),
        rawText: clean,
        source: safeString(source) || 'office-chat',
        priority: officeClamp(Number(priority) || 0, 0, 4),
        roomId: room.id,
        roomLabel: room.label,
        status: 'queued',
        assignedAgentId: '',
        createdAt: Date.now(),
        startedAt: 0,
        completedAt: 0,
    };
    officeState.taskCounter += 1;
    officeState.tasks.push(task);
    officeState.tasksDirty = true;
    officeTrimTasks();
    officeBusEmit('task.queued', {
        taskId: task.id,
        source: task.source,
        roomId: task.roomId,
        roomLabel: task.roomLabel,
        title: task.title,
    });

    if (preferredAgentId) {
        const preferredAgent = officeGetAgentById(preferredAgentId);
        if (preferredAgent && !preferredAgent.taskId && preferredAgent.state === 'idle') {
            officeAssignTaskToAgent(task, preferredAgent, performance.now());
        }
    }
    officeAssignQueuedTasks(performance.now());

    if (announce) {
        const queueLine = officePick(OFFICE_DIALOGUE.queued)
            .replace('{room}', room.label)
            .replace('{task}', task.title);
        officePushChatLine(queueLine);
    }

    return task;
}

function officeSyncStructuredDelegationTask(evt, statusRaw, taskTextRaw) {
    if (!officeState || !evt || typeof evt !== 'object') return null;
    const executionId = safeString(evt.execution_id || evt.task_id).trim();
    const sessionId = safeString(evt.session_id || officeChatPreviewSessionKey()).trim() || 'chat';
    if (!executionId) return null;
    const source = `chat-delegation:${sessionId}:${executionId}`;
    const normalizedStatus = safeString(statusRaw || evt.state).trim().toLowerCase();
    let task = officeState.tasks.find((candidate) => safeString(candidate?.source) === source) || null;
    if (!task) {
        const specialistId = safeString(evt.specialist_id).trim().toLowerCase();
        const structuredRoomId = safeString(evt.room_id || evt.roomId).trim()
            || OFFICE_SPECIALIST_ROOM_IDS[specialistId]
            || 'room-planning';
        const identity = officeResolveAgentIdentity(evt.bot_name || evt.bot_id, executionId);
        task = officeQueueTask(taskTextRaw || evt.summary || 'Background task', {
            source,
            announce: false,
            preferredAgentId: identity.id,
            roomId: structuredRoomId,
            priority: evt.priority,
        });
    }
    if (!task) return null;
    if (['completed', 'failed', 'abandoned', 'cancelled'].includes(normalizedStatus)) {
        task.status = 'done';
        task.completedAt = Date.now();
        const assignedAgent = officeGetAgentById(task.assignedAgentId);
        if (assignedAgent && assignedAgent.taskId === task.id) {
            assignedAgent.taskId = '';
            assignedAgent.state = 'idle';
            assignedAgent.intent = 'wander';
        }
        officeState.tasksDirty = true;
    }
    return task;
}


function officeFindAgentByHandle(handleRaw) {
    if (!officeState) return null;
    const handle = officeAgentHandle(handleRaw);
    if (!handle) return null;
    return officeState.agents.find((agent) => officeAgentHandle(agent.name) === handle)
        || officeState.agents.find((agent) => officeAgentHandle(agent.name).startsWith(handle))
        || null;
}

function officeResolveAgentIdentity(handleRaw, activityIdRaw = '') {
    const officeAgent = officeFindAgentByHandle(handleRaw);
    if (officeAgent) {
        return {
            id: safeString(officeAgent.id),
            name: safeString(officeAgent.name) || DEFAULT_AGENT_NAME,
            color: safeString(officeAgent.color) || '#9ad8ff',
            costume: safeString(officeAgent.costume) || 'none',
            tint: safeString(officeAgent.tint) || 'blue',
            source: 'office',
        };
    }
    const key = officeAgentHandle(handleRaw) || officeAgentHandle(activityIdRaw) || 'helper';
    const seedIndex = Math.abs(officeStableHash(key)) % Math.max(1, OFFICE_AGENT_SEEDS.length);
    const seed = OFFICE_AGENT_SEEDS[seedIndex] || OFFICE_AGENT_SEEDS[0] || {};
    return {
        id: '',
        name: safeString(seed.name) || DEFAULT_AGENT_NAME,
        color: safeString(seed.color) || '#9ad8ff',
        costume: safeString(seed.costume) || 'none',
        tint: safeString(seed.tint) || 'blue',
        source: 'seed',
    };
}

function officeParseMentionCommand(messageRaw) {
    const message = safeString(messageRaw).trim();
    if (!message) return { command: 'status', args: '' };
    const parts = message.split(/\s+/);
    const command = safeString(parts.shift()).toLowerCase();
    const args = parts.join(' ').trim();
    if (command === 'status' || command === 'where' || command === 'load') return { command: 'status', args };
    if (command === 'break' || command === 'coffee' || command === 'lunch') return { command: 'break', args };
    if (command === 'resume' || command === 'work') return { command: 'resume', args };
    if (command === 'summon' || command === 'lobby') return { command: 'summon', args };
    if (command === 'focus') return { command: 'focus', args };
    if (command === 'task') return { command: 'task', args };
    return { command: 'message', args: message };
}

function officeHandleMention(agent, messageRaw) {
    if (!officeState || !agent) return '';
    const message = safeString(messageRaw);
    const parsed = officeParseMentionCommand(message);
    let reply = '';

    if (parsed.command === 'status') {
        const activeCount = officeState.tasks.filter((task) => task.status === 'active').length;
        const room = officeCurrentRoomForAgent(agent);
        const status = officePick(OFFICE_DIALOGUE.mentionStatus).replace('{count}', String(activeCount));
        reply = `${status} I am in ${room?.label || 'the hallway'} right now.`;
    } else if (parsed.command === 'break') {
        const breakTarget = officeChance(0.5) ? 'room-coffee' : 'room-break';
        officeRouteAgentToRoom(agent, breakTarget, {
            intent: 'break',
            speed: officeRandomRange(2.8, 3.9),
        });
        agent.nextBreakAt = performance.now() + officeRandomRange(40_000, 88_000);
        reply = 'Copy. Taking a short break loop and returning to queue.';
    } else if (parsed.command === 'resume') {
        agent.state = 'idle';
        agent.intent = 'wander';
        agent.idleUntil = performance.now() + officeRandomRange(320, 1200);
        const routed = officeRouteAgentToRoom(agent, 'room-lobby', {
            intent: 'wander',
            speed: officeRandomRange(2.8, 3.8),
        });
        reply = routed ? 'Resuming active route from lobby.' : 'Resuming in place.';
    } else if (parsed.command === 'summon') {
        officeRouteAgentToRoom(agent, 'room-lobby', {
            intent: 'wander',
            speed: officeRandomRange(3.2, 4.1),
        });
        reply = 'On my way to Main Lobby.';
    } else if (parsed.command === 'focus') {
        const roomId = officeResolveExplicitRoom(parsed.args)?.id || 'room-pods';
        const room = officeRoomById(roomId);
        officeRouteAgentToRoom(agent, roomId, {
            intent: 'wander',
            speed: officeRandomRange(3.1, 4.1),
        });
        reply = `Switching to focus in ${room?.label || 'Focus Pods'}.`;
    } else if (parsed.command === 'task') {
        const taskText = parsed.args || 'new task';
        const task = officeQueueTask(taskText, {
            source: `mention:${agent.id}`,
            announce: false,
            preferredAgentId: agent.id,
        });
        if (task && task.assignedAgentId === agent.id) {
            reply = `Picked it up. I am moving to ${task.roomLabel}.`;
        } else if (task) {
            reply = `Queued it in ${task.roomLabel}. I will grab it after my current task.`;
        } else {
            reply = officePick(OFFICE_DIALOGUE.mention);
        }
    } else {
        reply = officePick(OFFICE_DIALOGUE.mention);
    }

    if (officeSpeak(agent, reply, { priority: true, durationMs: 1700 })) {
        officePushChatLine(`@${agent.name}: ${reply}`);
        officeBusEmit('agent.mention', {
            agentId: agent.id,
            agentName: agent.name,
            command: parsed.command,
            args: safeString(parsed.args).slice(0, 160),
        });
    }
    return reply;
}

function officeHandleAgentTap(agentId) {
    if (!officeState) return;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    officeState.selectedAgentId = agent.id;
    officeSyncCustomizerFields();
    if (safeString(officeState.followAgentId)) {
        officeSetFollowMode(true, agent.id);
    }
    const now = performance.now();
    const exit = officePlanRunawayExit(agent);
    agent.jumpUntil = now + 460;
    agent.bumpUntil = now + 460;
    agent.state = 'runaway';
    agent.intent = 'runaway';
    agent.returnAfterRunAt = now + officeClamp(OFFICE_RUNAWAY_DURATION_MS * 0.46, 2000, 3200);
    agent.taskId = '';
    agent.facing = exit.x >= agent.x ? 1 : -1;
    agent.runawayExitX = exit.x;
    agent.runawayExitY = exit.y;
    agent.runawayPhase = 'to-hall';
    agent.routeWaypoints = [];
    agent.routeDestinationNodeId = '';
    const routed = officeRouteAgentToNode(agent, exit.hallId, {
        intent: 'runaway',
        speed: officeRandomRange(5.2, 6.8),
    });
    if (!routed) {
        agent.runawayPhase = 'exiting';
        officeSetAgentTarget(agent, exit.x, exit.y, {
            intent: 'runaway',
            speed: officeRandomRange(6.1, 7.8),
        });
    }
    agent.state = 'runaway';
    agent.intent = 'runaway';
    const line = officePick(OFFICE_DIALOGUE.clicked);
    officeSpeak(agent, line, { priority: true, durationMs: 1200 });
    officePushChatLine(`${agent.name}: ${line}`);
    officePulseHaptic([14, 24, 10]);
    officeBusEmit('agent.tapped', {
        agentId: agent.id,
        agentName: agent.name,
        runawayPhase: agent.runawayPhase,
    });
    officeState.tasks.forEach((task) => {
        if (task.assignedAgentId === agent.id && task.status === 'active') {
            task.status = 'queued';
            task.assignedAgentId = '';
            task.startedAt = 0;
            officeState.tasksDirty = true;
        }
    });
}

function officeHandleChatSend() {
    if (!officeState || !officeChatInput) return;
    const input = safeString(officeChatInput.value);
    if (!input) return;
    officeChatInput.value = '';

    const slashMatch = input.match(/^\/([a-z_-]+)\s*(.*)$/i);
    if (slashMatch) {
        const command = safeString(slashMatch[1]).toLowerCase();
        const args = safeString(slashMatch[2]).trim();
        if (command === 'summon' || command === 'break' || command === 'resume') {
            officeRunQuickAction(command);
            return;
        }
        if (command === 'focus') {
            const roomId = officeResolveExplicitRoom(args)?.id || 'room-pods';
            officeRunQuickAction(`focus:${roomId}`);
            return;
        }
        if (command === 'task') {
            officeQueueTask(args || 'new task', { source: 'office-chat', announce: true });
            return;
        }
    }

    const mentionMatch = input.match(/^@([a-z0-9._-]+)\s*(.*)$/i);
    if (mentionMatch) {
        const handle = mentionMatch[1];
        const message = safeString(mentionMatch[2]);
        const agent = officeFindAgentByHandle(handle);
        if (!agent) {
            const handles = officeState.agents.map((entry) => `@${officeAgentHandle(entry.name)}`).join(', ');
            officePushChatLine(`No agent found for @${handle}. Available: ${handles}`);
            return;
        }
        officePushChatLine(`You -> @${agent.name}: ${message || 'status?'}`, 'user');
        officeHandleMention(agent, message || 'status');
        return;
    }

    officeQueueTask(input, { source: 'office-chat', announce: true });
}

function officeRunQuickAction(actionRaw) {
    if (!officeState) return;
    const action = safeString(actionRaw).toLowerCase();
    const now = performance.now();
    const eventPayload = {
        action,
        at: Date.now(),
    };
    if (action === 'summon') {
        officeState.agents.forEach((agent) => {
            if (!agent || agent.state === 'runaway') return;
            officeRouteAgentToRoom(agent, 'room-lobby', {
                intent: 'wander',
                speed: officeRandomRange(3.1, 4.2),
            });
        });
        officePushChatLine('System: All agents summoned to the Main Lobby.');
        officePulseHaptic([12, 18, 12]);
        officeBusEmit('quick_action.run', eventPayload, now);
        return;
    }
    if (action === 'break') {
        officeState.agents.forEach((agent) => {
            if (!agent || agent.state === 'runaway') return;
            const breakRoomId = officeChance(0.5) ? 'room-coffee' : 'room-break';
            officeRouteAgentToRoom(agent, breakRoomId, {
                intent: 'break',
                speed: officeRandomRange(2.9, 3.8),
            });
            agent.nextBreakAt = now + officeRandomRange(42_000, 94_000);
            if (officeChance(0.42)) {
                officeSpeak(agent, officeBanterForAgent(agent, 'break', {
                    roomTheme: officeRoomById(breakRoomId)?.theme || '',
                }), { priority: true, durationMs: 1200 });
            }
        });
        officePushChatLine('System: Break wave sent. Agents are rotating to coffee/lunch rooms.');
        officePulseHaptic([10, 20, 10]);
        officeBusEmit('quick_action.run', eventPayload, now);
        return;
    }
    if (action === 'resume') {
        officeState.agents.forEach((agent) => {
            if (!agent || agent.state === 'runaway') return;
            const assignedTask = agent.taskId
                ? officeState.tasks.find((task) => task.id === agent.taskId && task.status !== 'done')
                : null;
            if (assignedTask) {
                officeRouteAgentToRoom(agent, assignedTask.roomId, {
                    intent: 'task',
                    speed: officeRandomRange(3.2, 4.2),
                });
                return;
            }
            agent.state = 'idle';
            agent.intent = 'wander';
            agent.idleUntil = now + officeRandomRange(400, 1200);
        });
        officePushChatLine('System: Resume signal sent. Agents are returning to active work routing.');
        officePulseHaptic(14);
        officeBusEmit('quick_action.run', eventPayload, now);
        return;
    }
    if (action.startsWith('focus:')) {
        const roomId = safeString(action.split(':')[1]) || 'room-pods';
        officeState.agents.forEach((agent) => {
            if (!agent || agent.state === 'runaway') return;
            officeRouteAgentToRoom(agent, roomId, {
                intent: 'wander',
                speed: officeRandomRange(3.2, 4.3),
            });
        });
        const roomLabel = officeRoomById(roomId)?.label || roomId;
        officePushChatLine(`System: Focus wave sent to ${roomLabel}.`);
        officeBusEmit('quick_action.run', { ...eventPayload, roomId }, now);
    }
}

function officeTouchActivePointers() {
    if (!officeState?.touchGesture?.pointerById) return [];
    return [...officeState.touchGesture.pointerById.values()];
}

function officeTouchGestureDown(event) {
    if (!officeState?.touchGesture) return;
    const gesture = officeState.touchGesture;
    gesture.pointerById.set(event.pointerId, {
        x: event.clientX,
        y: event.clientY,
    });
    const pointers = officeTouchActivePointers();
    if (pointers.length < 2) {
        gesture.active = true;
        gesture.baseDistance = 0;
        gesture.baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
        gesture.lastCenterX = event.clientX;
        gesture.lastCenterY = event.clientY;
        return;
    }
    const a = pointers[0];
    const b = pointers[1];
    gesture.active = true;
    gesture.baseDistance = Math.max(0.001, Math.hypot(b.x - a.x, b.y - a.y));
    gesture.baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
    gesture.lastCenterX = (a.x + b.x) / 2;
    gesture.lastCenterY = (a.y + b.y) / 2;
}

function officeTouchGestureMove(event) {
    if (!officeState?.touchGesture) return false;
    const gesture = officeState.touchGesture;
    if (!gesture.pointerById.has(event.pointerId)) return false;
    gesture.pointerById.set(event.pointerId, {
        x: event.clientX,
        y: event.clientY,
    });
    const pointers = officeTouchActivePointers();
    if (pointers.length >= 2) {
        const a = pointers[0];
        const b = pointers[1];
        const centerX = (a.x + b.x) / 2;
        const centerY = (a.y + b.y) / 2;
        const distance = Math.max(0.001, Math.hypot(b.x - a.x, b.y - a.y));
        if (!gesture.active) {
            gesture.active = true;
            gesture.baseDistance = distance;
            gesture.baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
            gesture.lastCenterX = centerX;
            gesture.lastCenterY = centerY;
            return true;
        }
        const ratio = distance / Math.max(0.001, gesture.baseDistance || distance);
        const nextZoom = (gesture.baseZoom || officeState.zoomLevel) * ratio;
        officeSetZoom(nextZoom, {
            anchorClientX: centerX,
            anchorClientY: centerY,
        });
        const deltaX = centerX - (gesture.lastCenterX || centerX);
        const deltaY = centerY - (gesture.lastCenterY || centerY);
        if (Math.abs(deltaX) > 0.2 || Math.abs(deltaY) > 0.2) {
            officePanBy(deltaX, deltaY);
        }
        gesture.lastCenterX = centerX;
        gesture.lastCenterY = centerY;
        return true;
    }
    if (pointers.length === 1 && gesture.active) {
        const pointer = pointers[0];
        const deltaX = pointer.x - (gesture.lastCenterX || pointer.x);
        const deltaY = pointer.y - (gesture.lastCenterY || pointer.y);
        if (Math.abs(deltaX) > 0.1 || Math.abs(deltaY) > 0.1) {
            officePanBy(deltaX, deltaY);
        }
        gesture.lastCenterX = pointer.x;
        gesture.lastCenterY = pointer.y;
        return true;
    }
    return false;
}

function officeTouchGestureEnd(event) {
    if (!officeState?.touchGesture) return;
    const gesture = officeState.touchGesture;
    gesture.pointerById.delete(event.pointerId);
    const pointers = officeTouchActivePointers();
    if (pointers.length >= 2) {
        const a = pointers[0];
        const b = pointers[1];
        gesture.baseDistance = Math.max(0.001, Math.hypot(b.x - a.x, b.y - a.y));
        gesture.baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
        gesture.lastCenterX = (a.x + b.x) / 2;
        gesture.lastCenterY = (a.y + b.y) / 2;
        gesture.active = true;
        return;
    }
    if (pointers.length === 1) {
        const pointer = pointers[0];
        gesture.lastCenterX = pointer.x;
        gesture.lastCenterY = pointer.y;
        gesture.baseDistance = 0;
        gesture.active = true;
        return;
    }
    gesture.active = false;
    gesture.baseDistance = 0;
}

function officeClampResizeValue(value, min, max) {
    const minBound = Number.isFinite(min) ? min : 80;
    const maxBound = Number.isFinite(max) ? Math.max(minBound, max) : Number.POSITIVE_INFINITY;
    if (!Number.isFinite(value)) return minBound;
    return Math.max(minBound, Math.min(maxBound, value));
}

function officePanelResizeMetrics(panel) {
    if (!(panel instanceof HTMLElement)) {
        return { minWidth: 120, minHeight: 80, maxWidth: window.innerWidth, maxHeight: window.innerHeight };
    }
    const computed = window.getComputedStyle(panel);
    const minWidth = Math.max(120, Number.parseFloat(computed.minWidth) || 0);
    const minHeight = Math.max(80, Number.parseFloat(computed.minHeight) || 0);
    const parentRect = panel.parentElement instanceof Element
        ? panel.parentElement.getBoundingClientRect()
        : null;
    const maxWidth = Math.max(minWidth, Number(parentRect?.width) || window.innerWidth);
    const maxHeight = Math.max(minHeight, Number(parentRect?.height) || window.innerHeight);
    return { minWidth, minHeight, maxWidth, maxHeight };
}

function officePanelResizeBegin(event) {
    if (!officeState || !(event.currentTarget instanceof Element)) return;
    if (window.matchMedia && window.matchMedia('(max-width: 760px)').matches) return;
    const handle = event.currentTarget;
    const panel = handle.closest('.office-resizable');
    if (!(panel instanceof HTMLElement)) return;
    event.preventDefault();
    event.stopPropagation();

    const rect = panel.getBoundingClientRect();
    const { minWidth, minHeight, maxWidth, maxHeight } = officePanelResizeMetrics(panel);
    officeState.panelResize = {
        active: true,
        pointerId: event.pointerId,
        dir: safeString(handle.getAttribute('data-dir')).toLowerCase(),
        panel,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: rect.width,
        startHeight: rect.height,
        minWidth,
        minHeight,
        maxWidth,
        maxHeight,
    };
    panel.classList.add('is-resizing');
    if (typeof handle.setPointerCapture === 'function') {
        handle.setPointerCapture(event.pointerId);
    }
}

function officePanelResizeMove(event) {
    const resize = officeState?.panelResize;
    if (!resize?.active || !(resize.panel instanceof HTMLElement)) return;
    if (event.pointerId !== resize.pointerId) return;
    event.preventDefault();

    const deltaX = event.clientX - resize.startX;
    const deltaY = event.clientY - resize.startY;
    const dir = safeString(resize.dir);
    const horizontal = dir.includes('e') || dir.includes('w');
    const vertical = dir.includes('n') || dir.includes('s');

    if (horizontal) {
        let nextWidth = resize.startWidth;
        if (dir.includes('e')) nextWidth += deltaX;
        if (dir.includes('w')) nextWidth -= deltaX;
        const clampedWidth = officeClampResizeValue(nextWidth, resize.minWidth, resize.maxWidth);
        resize.panel.style.width = String(Math.round(clampedWidth)) + 'px';
    }

    if (vertical) {
        let nextHeight = resize.startHeight;
        if (dir.includes('s')) nextHeight += deltaY;
        if (dir.includes('n')) nextHeight -= deltaY;
        const clampedHeight = officeClampResizeValue(nextHeight, resize.minHeight, resize.maxHeight);
        resize.panel.style.height = String(Math.round(clampedHeight)) + 'px';
    }
}

function officePanelResizeEnd(event) {
    const resize = officeState?.panelResize;
    if (!resize?.active) return;
    if (event && Number.isFinite(event.pointerId) && event.pointerId !== resize.pointerId) return;

    const resizedPanel = resize.panel;
    if (resizedPanel instanceof HTMLElement) {
        resizedPanel.classList.remove('is-resizing');
    }
    officeState.panelResize = {
        active: false,
        pointerId: -1,
        dir: '',
        panel: null,
        startX: 0,
        startY: 0,
        startWidth: 0,
        startHeight: 0,
        minWidth: 0,
        minHeight: 0,
        maxWidth: 0,
        maxHeight: 0,
    };
    if (resizedPanel === officeSceneWrap && officeState) {
        officeResetViewport({ preserveZoom: true });
    }
    officeRenderMinimap();
}

function officeEnablePanelResizing() {
    if (!officeState || !officeWorkspace) return;
    const existingHandles = officeWorkspace.querySelectorAll('.office-resize-handle');
    existingHandles.forEach((handle) => handle.remove());
    officeWorkspace.querySelectorAll('.office-resizable').forEach((panel) => {
        panel.classList.remove('office-resizable', 'is-resizing');
    });
    return;
    if (!officeState.panelResize || typeof officeState.panelResize !== 'object') {
        officeState.panelResize = {
            active: false,
            pointerId: -1,
            dir: '',
            panel: null,
            startX: 0,
            startY: 0,
            startWidth: 0,
            startHeight: 0,
            minWidth: 0,
            minHeight: 0,
            maxWidth: 0,
            maxHeight: 0,
        };
    }
    if (!officeState.panelResizeWindowBound) {
        officeState.panelResizeWindowBound = true;
        window.addEventListener('pointermove', officePanelResizeMove, { passive: false });
        window.addEventListener('pointerup', officePanelResizeEnd);
        window.addEventListener('pointercancel', officePanelResizeEnd);
    }

    if (officeMinimap instanceof HTMLElement) {
        officeMinimap.classList.remove('office-resizable', 'is-resizing');
        officeMinimap.querySelectorAll('.office-resize-handle').forEach((handle) => handle.remove());
        officeMinimap.style.removeProperty('width');
        officeMinimap.style.removeProperty('height');
    }

    const panels = [
        officeWorkspace.querySelector('.office-toolbar'),
        officeSceneWrap,
        officeWorkspace.querySelector('.office-live-panel'),
        officeWorkspace.querySelector('.office-chatbar'),
        officeWorkspace.querySelector('.office-task-list'),
        officeWorkspace.querySelector('.office-chat-log'),
    ];
    const handleDirs = ['n', 'e', 's', 'w', 'ne', 'nw', 'se', 'sw'];

    panels.forEach((panelRaw) => {
        if (!(panelRaw instanceof HTMLElement)) return;
        panelRaw.classList.add('office-resizable');
        panelRaw.querySelectorAll('.office-resize-handle').forEach((handle) => handle.remove());
        handleDirs.forEach((dir) => {
            const handle = document.createElement('button');
            handle.type = 'button';
            handle.className = `office-resize-handle office-resize-handle-${dir}`;
            handle.setAttribute('data-dir', dir);
            handle.setAttribute('aria-label', `Resize panel ${dir}`);
            handle.addEventListener('pointerdown', officePanelResizeBegin);
            panelRaw.appendChild(handle);
        });
    });
}
