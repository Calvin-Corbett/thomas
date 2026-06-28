function chatRobotWorldRetarget(state, graph = null) {
    const bounds = chatRobotWorldBounds();
    const motion = chatRobotWorldMotionProfile(animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {}));
    const platformGraph = graph || chatRobotWorldBuildPlatformGraph(bounds, motion.fidelity);
    const platforms = platformGraph.platforms || [];
    const liveTask = chatRobotWorldTaskIsLive(state);
    const isPrimary = safeString(state?.kind) === 'primary';
    const isDelegation = safeString(state?.kind) === 'delegation';
    const physicsMode = chatWorldIsPhysicsMode();
    const groundedPrimaryPhysics = chatRobotWorldPrimaryUsesGroundedPhysics(state);
    if (isDelegation) {
        const helperMode = officePick(['idle', 'inspect', 'workout', 'sleep']) || 'idle';
        const helperSlot = chatRobotWorldHelperSlot(state, platformGraph, platforms);
        const helperPlatform = helperSlot?.platform
            || platformGraph.platformsById?.get(safeString(state.homeFloorId || state.currentPlatformId || state.targetPlatformId || ''))
            || chatRobotWorldCurrentPlatform(state, platforms)
            || platforms.find((platform) => safeString(platform.kind) === 'floor')
            || null;
        state.mode = helperMode;
        state.behaviorClass = chatRobotWorldBehaviorForMode(helperMode);
        state.modeUntil = Date.now() + motion.actionMinMs + Math.random() * (motion.actionMaxMs - motion.actionMinMs);
        if (helperPlatform) {
            const minX = Number(helperPlatform.x1 || 0) + 6;
            const maxX = Number(helperPlatform.x2 || 0) - 6;
            const homeX = chatRobotWorldClamp(
                Number.isFinite(Number(helperSlot?.homeX))
                    ? Number(helperSlot.homeX)
                    : (Number.isFinite(Number(state.homeX)) ? Number(state.homeX) : Number(state.x || ((minX + maxX) * 0.5))),
                minX,
                maxX,
            );
            const patrolRadius = Math.min(62, Math.max(18, (maxX - minX) * 0.14));
            const direction = Number(state.preferredDirection || state.facing || 1) >= 0 ? 1 : -1;
            state.homeFloorId = safeString(helperPlatform.id);
            state.currentPlatformId = safeString(state.currentPlatformId || helperPlatform.id);
            state.targetPlatformId = safeString(helperPlatform.id);
            state.targetY = Number(helperPlatform.y || bounds.groundY) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
            state.targetX = chatRobotWorldClamp(homeX + (direction * patrolRadius), minX, maxX);
            if (Math.abs(state.targetX - homeX) < 10) {
                state.targetX = homeX;
            }
            state.homeX = homeX;
            state.preferredDirection = direction * -1;
        }
        if (physicsMode) {
            state.transition = null;
            state.hiddenTransit = false;
            state.targetPlatformId = safeString(helperPlatform?.id || state.homeFloorId || state.targetPlatformId);
            state.physicsNeedsSnap = false;
        }
        return;
    }
    if (!physicsMode && isPrimary && !liveTask) {
        const leftFloor = platformGraph.platformsById?.get('floor-left')
            || platforms.find((platform) => safeString(platform.kind) === 'floor')
            || null;
        const calmMode = officePick(['idle', 'sleep', 'inspect', 'workout']) || 'idle';
        state.mode = calmMode;
        state.behaviorClass = chatRobotWorldBehaviorForMode(calmMode);
        state.modeUntil = Date.now() + 6800 + Math.random() * 2600;
        if (leftFloor) {
            state.currentPlatformId = safeString(leftFloor.id);
            state.targetPlatformId = safeString(leftFloor.id);
            state.targetY = Number(leftFloor.y || bounds.groundY) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
            state.targetX = chatRobotWorldClamp(Number(state.homeX || 46), Number(leftFloor.x1 || 0) + 6, Number(leftFloor.x2 || 0) - 24);
            state.x = state.targetX;
            state.y = state.targetY;
            state.homeFloorId = safeString(leftFloor.id);
            state.homeX = state.targetX;
        }
        state.transition = null;
        state.hiddenTransit = false;
        state.vx = 0;
        state.vy = 0;
        state.preferredDirection = 1;
        if (calmMode === 'sleep') {
            chatRobotWorldSetSpeech(state, 'Resting on standby.');
        } else if (calmMode === 'workout') {
            chatRobotWorldSetSpeech(state, 'Warmup set.');
        } else if (calmMode === 'inspect') {
            chatRobotWorldSetSpeech(state, 'Watching the chat.');
        } else {
            chatRobotWorldSetSpeech(state, 'Standing by.');
        }
        return;
    }
    if (isPrimary && !liveTask) {
        if (physicsMode) {
            const primaryFloor = platformGraph.platformsById?.get(safeString(state.homeFloorId || state.currentPlatformId || ''))
                || platforms.find((platform) => safeString(platform.kind) === 'floor')
                || null;
            const calmMode = officePick(['idle', 'inspect', 'workout', 'sleep']) || 'idle';
            state.mode = calmMode;
            state.behaviorClass = chatRobotWorldBehaviorForMode(calmMode);
            state.modeUntil = Date.now() + motion.actionMinMs + Math.random() * (motion.actionMaxMs - motion.actionMinMs);
            if (primaryFloor) {
                const minX = Number(primaryFloor.x1 || 0) + 8;
                const maxX = Number(primaryFloor.x2 || 0) - 8;
                const homeX = chatRobotWorldClamp(
                    Number.isFinite(Number(state.homeX)) ? Number(state.homeX) : Number(state.x || ((minX + maxX) * 0.5)),
                    minX,
                    maxX,
                );
                const patrolRadius = Math.min(88, Math.max(20, (maxX - minX) * 0.12));
                const direction = Number(state.preferredDirection || state.facing || 1) >= 0 ? 1 : -1;
                state.currentPlatformId = safeString(state.currentPlatformId || primaryFloor.id);
                state.targetPlatformId = safeString(primaryFloor.id);
                state.homeFloorId = safeString(primaryFloor.id);
                state.homeX = homeX;
                state.targetY = Number(primaryFloor.y || bounds.groundY) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
                state.targetX = chatRobotWorldClamp(homeX + (direction * patrolRadius), minX, maxX);
                state.preferredDirection = direction * -1;
            }
            state.transition = null;
            state.hiddenTransit = false;
            state.physicsNeedsSnap = false;
            if (calmMode === 'sleep') {
                chatRobotWorldSetSpeech(state, 'Resting on standby.');
            } else if (calmMode === 'workout') {
                chatRobotWorldSetSpeech(state, 'Warmup set.');
            } else if (calmMode === 'inspect') {
                chatRobotWorldSetSpeech(state, 'Watching the chat.');
            } else {
                chatRobotWorldSetSpeech(state, 'Standing by.');
            }
            return;
        }
        const nextZone = safeString(state.ambientZone) || chatRobotWorldAmbientZoneForX(state.x, bounds);
        state.ambientZone = nextZone;
        state.ambientClusterRemaining = Number.isFinite(Number(state.ambientClusterRemaining))
            ? Math.max(0, Number(state.ambientClusterRemaining))
            : 0;
        if (state.ambientClusterRemaining <= 0) {
            state.ambientZone = nextZone === 'right' ? 'left' : 'right';
            state.ambientClusterRemaining = 2 + Math.floor(Math.random() * 2);
        } else {
            state.ambientClusterRemaining -= 1;
        }
    }
    const mode = chatRobotWorldChooseMode(state);
    state.mode = mode;
    state.behaviorClass = chatRobotWorldBehaviorForMode(mode);
    state.modeUntil = Date.now() + motion.actionMinMs + Math.random() * (motion.actionMaxMs - motion.actionMinMs);
    state.currentPlatformId = safeString(state.currentPlatformId || chatRobotWorldCurrentPlatform(state, platforms)?.id || '');
    if (!groundedPrimaryPhysics && (mode === 'perch' || mode === 'inspect')) {
        const perch = chatRobotWorldPerchTarget(state, platforms);
        state.targetX = perch.x;
        state.targetY = perch.y;
        const perchPlatform = platforms.find((platform) => (
            perch.x >= (platform.x1 - 6)
            && perch.x <= (platform.x2 + 6)
            && Math.abs((platform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET) - perch.y) <= 14
        )) || {
            id: 'inspect-target',
            kind: 'ui',
            x1: perch.x - 14,
            x2: perch.x + 14,
            y: perch.y + CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
        };
        state.targetPlatformId = perchPlatform.id;
        const transition = chatRobotWorldPlanTransition(state, perchPlatform, bounds, platformGraph, motion.fidelity);
        if (transition) {
            state.transition = transition;
        }
    } else {
        const platform = chatRobotWorldPickTargetPlatform(state, platformGraph, mode, motion);
        if (!platform) return;
        const span = Math.max(24, (platform.x2 - platform.x1) - 12);
        const desiredDirection = Number(state.preferredDirection || state.facing || 1) >= 0 ? 1 : -1;
        const currentX = Number(state.x || ((platform.x1 + platform.x2) * 0.5));
        const minX = platform.x1 + 6;
        const maxX = platform.x2 - 6;
        state.targetPlatformId = platform.id;
        state.targetY = platform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
        if (safeString(platform.id) === safeString(state.currentPlatformId)) {
            if (!liveTask && isPrimary) {
                const hop = groundedPrimaryPhysics
                    ? (10 + (Math.random() * 16))
                    : (18 + (Math.random() * 34));
                state.targetX = chatRobotWorldClamp(currentX + (desiredDirection * hop), minX, maxX);
                if (Math.abs(state.targetX - currentX) < 14) {
                    state.targetX = desiredDirection > 0 ? minX : maxX;
                }
            } else {
                state.targetX = desiredDirection > 0 ? maxX : minX;
                if (Math.abs(state.targetX - currentX) < 24) {
                    state.targetX = desiredDirection > 0 ? minX : maxX;
                }
            }
        } else {
            state.targetX = desiredDirection > 0
                ? chatRobotWorldClamp(maxX - (Math.random() * Math.min(span * 0.28, 84)), minX, maxX)
                : chatRobotWorldClamp(minX + (Math.random() * Math.min(span * 0.28, 84)), minX, maxX);
        }
        state.preferredDirection = desiredDirection * -1;
        const transition = chatRobotWorldPlanTransition(state, platform, bounds, platformGraph, motion.fidelity);
        if (transition && !physicsMode && !(groundedPrimaryPhysics && safeString(transition.routeKind) !== 'door')) {
            state.transition = transition;
            state.targetX = transition.segments[transition.segments.length - 1].x;
            state.targetY = transition.segments[transition.segments.length - 1].y;
        }
    }
    if (!liveTask && isPrimary && safeString(state.targetPlatformId) === safeString(state.currentPlatformId)) {
        state.homeFloorId = safeString(state.currentPlatformId || state.homeFloorId);
        state.homeX = Number(state.targetX || state.x || state.homeX || 48);
    }
    if (mode === 'sleep') {
        chatRobotWorldSetSpeech(state, 'Tiny recharge cycle.');
    } else if (mode === 'workout') {
        chatRobotWorldSetSpeech(state, 'Strength training.');
    } else if (mode === 'inspect') {
        chatRobotWorldSetSpeech(state, 'Checking the controls.');
    } else if (mode === 'perch') {
        chatRobotWorldSetSpeech(state, 'Perched on the UI.');
    } else if (!safeString(state.summary) && state.kind !== 'delegation') {
        chatRobotWorldSetSpeech(state, 'Standing by.');
    }
}

function chatRobotWorldEnsurePrimaryState() {
    if (chatPrimaryPresenceState) return chatPrimaryPresenceState;
    const initialBounds = chatRobotWorldBounds();
    chatPrimaryPresenceState = {
        activityId: 'primary',
        kind: 'primary',
        element: null,
        status: 'idle',
        summary: 'Standing by.',
        taskText: '',
        startedAt: 0,
        endedAt: 0,
        visibleSince: Date.now(),
        lingerUntil: 0,
        x: 46,
        y: initialBounds.groundY,
        targetX: 46,
        targetY: initialBounds.groundY,
        vx: 0,
        vy: 0,
        facing: 1,
        paused: false,
        mode: 'idle',
        modeUntil: Date.now() + 2600,
        officeTaskId: '',
        officeAgentId: '',
        officeAgentName: DEFAULT_AGENT_NAME,
        name: DEFAULT_AGENT_NAME,
        color: '#9ad8ff',
        costume: 'none',
        behaviorClass: 'looking',
        transition: null,
        hiddenTransit: false,
        currentPlatformId: '',
        targetPlatformId: '',
        preferredDirection: 1,
        homeFloorId: 'floor-left',
        homeX: 46,
        ambientZone: 'left',
        ambientClusterRemaining: 2,
        taskSpeechAt: 0,
        portalTransfer: null,
        debugPropKind: '',
        debugPropPhase: '',
        physicsNeedsSnap: true,
    };
    chatPrimaryPresenceState.element = null;
    return chatPrimaryPresenceState;
}

function chatRobotWorldSyncRootVisibility() {
    chatAgentPresenceSyncRootVisibility();
}

function chatRobotWorldLatestTaskState() {
    const states = [...chatTaskStripStateByMessageId.values()]
        .filter(Boolean)
        .sort((a, b) => Number(b?.startedAt || b?.endedAt || 0) - Number(a?.startedAt || a?.endedAt || 0));
    return states.find((item) => !chatTaskIsTerminal(item?.status))
        || states.find((item) => Date.now() - Number(item?.endedAt || 0) < CHAT_PRIMARY_ROBOT_LINGER_MS)
        || null;
}

function chatRobotWorldSyncPrimaryFromTasks() {
    const primary = chatRobotWorldEnsurePrimaryState();
    primary.name = resolveAgentName(currentPreferences) || DEFAULT_AGENT_NAME;
    primary.officeAgentName = primary.name;
    primary.status = 'idle';
    primary.summary = 'Standing by.';
    primary.taskText = '';
    primary.taskSpeechAt = 0;
    chatRobotWorldRenderActor(primary);
}

function chatRobotWorldRenderActor(state, graph = null) {
    if (!state?.element) return;
    const bounds = chatRobotWorldBounds();
    const physicsMode = chatWorldIsPhysicsMode();
    const platforms = graph?.platforms || chatRobotWorldPlatforms(bounds);
    const currentPlatform = physicsMode
        ? (chatRobotWorldCurrentPlatform(state, platforms)
            || graph?.platformsById?.get(safeString(state?.currentPlatformId)))
        : (graph?.platformsById?.get(safeString(state?.currentPlatformId))
            || chatRobotWorldCurrentPlatform(state, platforms));
    if (currentPlatform) {
        state.currentPlatformId = currentPlatform.id;
    }
    state.element.style.transform = `translate(${Math.round(Number(state.x) || 0)}px, ${Math.round(Number(state.y) || 0)}px)`;
    state.element.classList.toggle('is-paused', Boolean(state.paused));
    state.element.classList.toggle('is-sleeping', state.mode === 'sleep');
    state.element.classList.toggle('is-working-out', state.mode === 'workout');
    state.element.classList.toggle('is-perched', state.mode === 'perch' || state.mode === 'inspect');
    state.element.classList.toggle('is-terminal', chatTaskIsTerminal(state.status));
    state.element.classList.toggle('is-active-task', !chatTaskIsTerminal(state.status) && safeString(state.status) !== 'idle');
    state.element.classList.toggle('is-in-tunnel', Boolean(state.hiddenTransit));
    state.element.classList.toggle('is-traversing', Boolean(state.transition));
    state.element.classList.toggle('is-physics-rendered', physicsMode);
    state.element.dataset.transitionKind = safeString(state.transition?.routeKind || '');
    state.element.dataset.platformId = safeString(state.currentPlatformId || '');
    state.element.dataset.targetPlatformId = safeString(state.targetPlatformId || '');
    state.element.dataset.mode = safeString(state.mode || '');
    state.element.dataset.identitySource = safeString(state.identitySource || '');
    const label = state.element.querySelector('[data-role="label"]');
    if (label instanceof HTMLElement) {
        label.textContent = safeString(state.name) || DEFAULT_AGENT_NAME;
    }
    const bubbleName = state.element.querySelector('[data-role="name"]');
    if (bubbleName instanceof HTMLElement) {
        bubbleName.textContent = safeString(state.name) || DEFAULT_AGENT_NAME;
    }
      const bubbleSummary = state.element.querySelector('[data-role="summary"]');
      if (bubbleSummary instanceof HTMLElement) {
          bubbleSummary.textContent = chatRobotWorldDetailLine(state);
      }
    const bubbleStatus = state.element.querySelector('[data-role="status"]');
    if (bubbleStatus instanceof HTMLElement) {
        bubbleStatus.textContent = chatTaskStatusLabel(state.status || 'idle');
    }
    const botEl = state.element.querySelector('[data-role="bot"]');
    if (botEl instanceof HTMLElement) {
        botEl.classList.toggle('is-facing-left', Number(state.facing || 1) < 0);
    }
    if (Date.now() > Number(state.speechUntil || 0)) {
        const speechEl = state.element.querySelector('[data-role="speech"]');
        if (speechEl instanceof HTMLElement) {
            speechEl.classList.add('hidden');
            speechEl.textContent = '';
        }
        state.element.classList.remove('is-speaking');
    }
    chatRobotWorldApplyPalette(state);
    chatRobotWorldRenderRoute(state);
    const botVisual = state.element.querySelector('.office-pixel-agent, .chat-robot-agent');
    const labelEl = state.element.querySelector('[data-role="label"]');
    const actorRect = state.element.getBoundingClientRect();
    const actorCenterX = actorRect.left + (actorRect.width * 0.5);
    const botRect = botVisual instanceof HTMLElement ? botVisual.getBoundingClientRect() : null;
    const visualCenterOffset = botRect
        ? ((botRect.left + (botRect.width * 0.5)) - actorCenterX)
        : 0;
    state.element.style.setProperty('--chat-robot-label-offset-x', `${Math.round(visualCenterOffset * 10) / 10}px`);
    if (labelEl instanceof HTMLElement) {
        const labelRect = labelEl.getBoundingClientRect();
        state.element.dataset.labelOffsetPx = `${Math.round((((labelRect.left + (labelRect.width * 0.5)) - actorCenterX) * 10)) / 10}`;
    }
    state.element.dataset.visualCenterOffsetPx = `${Math.round(visualCenterOffset * 10) / 10}`;
    state.element.classList.toggle('is-teleporting', Boolean(state.portalTransfer));
    const maxX = Math.max(22, bounds.width - 24);
    state.x = Math.max(16, Math.min(maxX, Number(state.x) || 0));
}

function chatRobotWorldPlaceActorOnPlatform(state, platform, x = null) {
    if (!state || !platform) return false;
    const anchorX = Number.isFinite(Number(x))
        ? Number(x)
        : chatRobotWorldClamp(
            Math.round((Number(platform.x1 || 0) + Number(platform.x2 || 0)) * 0.5),
            Number(platform.x1 || 0) + 10,
            Number(platform.x2 || 0) - 10,
        );
    state.currentPlatformId = safeString(platform.id);
    state.targetPlatformId = safeString(platform.id);
    state.x = anchorX;
    state.y = Number(platform.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
    state.targetX = anchorX;
    state.targetY = state.y;
    state.transition = null;
    state.hiddenTransit = false;
    state.portalTransfer = null;
    state.vx = 0;
    state.vy = 0;
    return true;
}

function chatRobotWorldSpawnDebugHelper() {
    const helper = chatWorldUpsertPresence(CHAT_AGENT_DEBUG_HELPER_ID, {
        sessionId: safeString(activeChatId || taskContinuityLatestSessionId || 'debug-session'),
        bubbleId: '',
        name: 'Scout',
        status: 'running',
        summary: 'Debug helper active.',
        taskText: 'Reviewing the staged chat-world task flow.',
        startedAt: Date.now(),
        color: '#7cd6ff',
        costume: 'visor',
    });
    if (!helper) return null;
    helper.mode = 'inspect';
    helper.modeUntil = 0;
    helper.lingerUntil = 0;
    helper.exiting = false;
    helper.portalClosing = false;
    helper.portalCloseAt = 0;
    window.setTimeout(() => {
        const live = chatAgentPresenceStateByActivityId.get(CHAT_AGENT_DEBUG_HELPER_ID);
        if (!live) return;
        live.status = 'done';
        live.summary = 'Debug helper complete.';
        chatRobotWorldRemoveHelper(CHAT_AGENT_DEBUG_HELPER_ID);
    }, 2400);
    return helper;
}

function chatRobotWorldRunDebugScenario(nameRaw = '') {
    const name = safeString(nameRaw).toLowerCase();
    const primary = chatRobotWorldEnsurePrimaryState();
    const bounds = chatRobotWorldBounds();
    const fidelity = animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {});
    const graph = chatRobotWorldBuildPlatformGraph(bounds, fidelity);
    const platformsById = graph.platformsById || new Map();
    const leftFloor = platformsById.get('floor-left') || graph.platforms.find((platform) => platform.kind === 'floor') || null;
    const rightFloor = platformsById.get('floor-right') || leftFloor;
    const roof = platformsById.get('composer-roof') || graph.platforms.find((platform) => platform.kind === 'roof') || null;
    const suggestion = platformsById.get('suggestion-top') || graph.platforms.find((platform) => platform.kind === 'suggestion') || roof;
    if (!name) {
        chatRobotWorldDebugScenario = null;
        return true;
    }
    chatRobotWorldDebugScenario = { name, startedAt: Date.now(), lockUntil: Date.now() + 14_000 };
    if (name === 'helper') {
        chatRobotWorldSpawnDebugHelper();
        return true;
    }
    if (name === 'door' && leftFloor && rightFloor) {
        const tunnel = graph?.geometry?.backgroundTunnel || null;
        chatRobotWorldPlaceActorOnPlatform(primary, leftFloor, Math.min(leftFloor.x2 - 20, leftFloor.x1 + 34));
        primary.preferredDirection = 1;
        primary.mode = 'roam';
        primary.modeUntil = Date.now() + 2600;
        if (tunnel) {
            primary.transition = chatRobotWorldCreateTransition(primary, [
                {
                    x: Number(tunnel.leftDoorX || primary.x),
                    y: Number(leftFloor.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    durationMs: 720,
                    kind: 'tunnel',
                    routeKind: 'door',
                    hidden: false,
                    platformId: leftFloor.id,
                    propX: Number(tunnel.leftDoorX || primary.x),
                    propTopY: Number(leftFloor.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    propBottomY: Number(leftFloor.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                },
                {
                    x: Number(tunnel.rightDoorX || primary.x),
                    y: Number(rightFloor.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    durationMs: 1120,
                    kind: 'tunnel',
                    routeKind: 'door',
                    hidden: true,
                    platformId: rightFloor.id,
                    propX: Number(tunnel.rightDoorX || primary.x),
                    propTopY: Number(rightFloor.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    propBottomY: Number(rightFloor.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                },
            ], {
                kind: 'tunnel',
                routeKind: 'door',
                targetPlatformId: rightFloor.id,
            });
        } else {
            primary.transition = chatRobotWorldPlanTransition(primary, rightFloor, bounds, graph, fidelity);
        }
        if (primary.transition) {
            primary.targetPlatformId = safeString(rightFloor.id);
            primary.targetX = Number(primary.transition.segments[primary.transition.segments.length - 1]?.x || primary.targetX);
            primary.targetY = Number(primary.transition.segments[primary.transition.segments.length - 1]?.y || primary.targetY);
        }
        return true;
    }
    if ((name === 'ladder' || name === 'stairs' || name === 'lift') && leftFloor && (roof || suggestion)) {
        const targetPlatform = suggestion || roof;
        chatRobotWorldPlaceActorOnPlatform(primary, leftFloor, Math.min(leftFloor.x2 - 22, leftFloor.x1 + 30));
        primary.preferredDirection = 1;
        primary.mode = 'inspect';
        primary.modeUntil = Date.now() + 2600;
        primary.transition = chatRobotWorldPlanTransition(primary, targetPlatform, bounds, graph, fidelity, { routeKindOverride: name });
        if (primary.transition) {
            primary.targetPlatformId = safeString(targetPlatform.id);
            primary.targetX = Number(primary.transition.segments[primary.transition.segments.length - 1]?.x || primary.targetX);
            primary.targetY = Number(primary.transition.segments[primary.transition.segments.length - 1]?.y || primary.targetY);
        }
        return true;
    }
    return false;
}

function chatRobotWorldCloneDebugPayload(payload) {
    try {
        return JSON.parse(JSON.stringify(payload));
    } catch (_) {
        return payload;
    }
}

function chatRobotWorldBuildDebugSnapshot(graph, actors, frameNow = Date.now()) {
    const platforms = (graph?.platforms || []).map((platform) => ({
        id: safeString(platform.id),
        kind: safeString(platform.kind),
        x1: Math.round(Number(platform.x1 || 0)),
        x2: Math.round(Number(platform.x2 || 0)),
        y: Math.round(Number(platform.y || 0)),
    }));
    const actorRows = actors.map((state) => {
        const currentPlatform = chatWorldCurrentMode() === CHAT_WORLD_MODE_PHYSICS
            ? (chatRobotWorldCurrentPlatform(state, graph?.platforms || [])
                || graph?.platformsById?.get(safeString(state?.currentPlatformId))
                || null)
            : (graph?.platformsById?.get(safeString(state?.currentPlatformId))
                || chatRobotWorldCurrentPlatform(state, graph?.platforms || [])
                || null);
        const feetY = Math.round(Number(state?.y || 0) + CHAT_PRIMARY_ROBOT_FOOT_OFFSET);
        const actorEl = state?.element;
        const actorRect = actorEl instanceof HTMLElement ? actorEl.getBoundingClientRect() : null;
        const actorCenterX = actorRect ? (actorRect.left + (actorRect.width * 0.5)) : null;
          const botRect = actorEl?.querySelector?.('.office-pixel-agent, .chat-robot-agent')?.getBoundingClientRect?.() || null;
        const labelRect = actorEl?.querySelector?.('[data-role="label"]')?.getBoundingClientRect?.() || null;
        const physicsRow = chatPhysicsWorldActorDebugRow(state?.activityId);
        return {
            activityId: safeString(state?.activityId),
            kind: safeString(state?.kind),
            name: safeString(state?.name),
            mode: safeString(state?.mode),
            status: safeString(state?.status),
            x: Math.round(Number(state?.x || 0)),
            y: Math.round(Number(state?.y || 0)),
            feetY,
            facing: Number(state?.facing || 1) < 0 ? 'left' : 'right',
            currentPlatformId: safeString(state?.currentPlatformId),
            targetPlatformId: safeString(state?.targetPlatformId),
            transitionKind: safeString(state?.transition?.routeKind || ''),
            locomotionKind: safeString(state?.transition?.kind || (state?.vx ? 'walk' : 'idle')),
            propKind: safeString(state?.debugPropKind || ''),
            propPhase: safeString(state?.debugPropPhase || ''),
            speechVisible: Boolean(state?.element?.querySelector?.('[data-role="speech"]:not(.hidden)')),
            hiddenTransit: Boolean(state?.hiddenTransit),
            legalSurfaceLock: currentPlatform ? Math.abs(feetY - Number(currentPlatform.y || feetY)) <= 12 : false,
            surfaceDeltaPx: currentPlatform ? Math.round(feetY - Number(currentPlatform.y || feetY)) : null,
            visualCenterOffsetPx: (actorCenterX !== null && botRect)
                ? Math.round((((botRect.left + (botRect.width * 0.5)) - actorCenterX) * 10)) / 10
                : null,
            labelCenterOffsetPx: (actorCenterX !== null && labelRect)
                ? Math.round((((labelRect.left + (labelRect.width * 0.5)) - actorCenterX) * 10)) / 10
                : null,
            ...physicsRow,
        };
    });
    return {
        capturedAt: Number(frameNow || Date.now()),
        worldMode: chatWorldCurrentMode(),
        fidelity: safeString(graph?.fidelity || ''),
        bounds: graph?.bounds || null,
        geometry: graph?.geometry || null,
        physics: chatPhysicsWorldState
            ? {
                ready: Boolean(chatPhysicsWorldState.ready),
                actorCount: Number(chatPhysicsWorldState.actorBodies?.size || 0),
                signature: safeString(chatPhysicsWorldState.signature || ''),
            }
            : null,
        platforms,
        actors: actorRows,
        primary: actorRows.find((row) => row.kind === 'primary') || null,
        scenario: safeString(chatRobotWorldDebugScenario?.name || ''),
    };
}

function chatRobotWorldSyncDebugState(graph, actors, frameNow = Date.now()) {
    chatRobotWorldLatestSnapshot = chatRobotWorldBuildDebugSnapshot(graph, actors, frameNow);
    chatRobotWorldDebugSamples.push(chatRobotWorldLatestSnapshot);
    if (chatRobotWorldDebugSamples.length > CHAT_PRIMARY_ROBOT_DEBUG_SAMPLE_LIMIT) {
        chatRobotWorldDebugSamples = chatRobotWorldDebugSamples.slice(-CHAT_PRIMARY_ROBOT_DEBUG_SAMPLE_LIMIT);
    }
    if (appRoot instanceof HTMLElement) {
        appRoot.dataset.chatRobotPlatform = safeString(chatRobotWorldLatestSnapshot?.primary?.currentPlatformId || '');
        appRoot.dataset.chatRobotMode = safeString(chatRobotWorldLatestSnapshot?.primary?.mode || '');
        appRoot.dataset.chatRobotFacing = safeString(chatRobotWorldLatestSnapshot?.primary?.facing || '');
    }
    if (typeof window !== 'undefined') {
        window[CHAT_PRIMARY_ROBOT_DEBUG_KEY] = {
            getSnapshot: () => chatRobotWorldCloneDebugPayload(chatRobotWorldLatestSnapshot),
            getSamples: () => chatRobotWorldCloneDebugPayload(chatRobotWorldDebugSamples),
            resetSamples: () => {
                chatRobotWorldDebugSamples = [];
            },
            runScenario: (name) => chatRobotWorldRunDebugScenario(name),
            clearScenario: () => {
                chatRobotWorldDebugScenario = null;
            },
        };
    }
}

function chatRobotWorldRemoveHelper(activityId, { immediate = false } = {}) {
    const key = safeString(activityId);
    if (!key || !chatAgentPresenceStateByActivityId.has(key)) return;
    const state = chatAgentPresenceStateByActivityId.get(key);
    if (!state?.element || immediate) {
        state?.routeElement?.remove?.();
        state?.element?.remove();
        chatAgentPresenceStateByActivityId.delete(key);
        chatRobotWorldSyncRootVisibility();
        return;
    }
    if (state.exiting) return;
    state.exiting = true;
    state.exitAt = Date.now() + CHAT_AGENT_PRESENCE_EXIT_MS + CHAT_AGENT_PRESENCE_PORTAL_OUT_MS;
    state.portalCloseAt = state.exitAt - CHAT_AGENT_PRESENCE_PORTAL_OUT_MS;
    state.portalClosing = false;
    chatRobotWorldSetSpeech(state, safeString(state.status) === 'failed' ? 'Task failed.' : 'Helper complete.', 1800);
}

function chatWorldRemoveHelperPublic(activityId, { immediate = false } = {}) {
    chatRobotWorldRemoveHelper(activityId, { immediate });
}

function chatWorldRemoveAllHelpers() {
    chatAgentPresenceStateByActivityId.forEach((_, activityId) => {
        chatRobotWorldRemoveHelper(activityId, { immediate: true });
    });
    chatWorldSyncRootVisibility();
}

function chatWorldRenderPresence(state) {
    chatRobotWorldRenderActor(state);
}

function chatRobotWorldEnsureLoop() {
    if (chatRobotWorldRaf) return;
    const step = (now) => {
        chatRobotWorldRaf = window.requestAnimationFrame(step);
        const frameNow = Number(now || performance.now());
        const last = Number(chatRobotWorldLastFrameAt || frameNow);
        const dt = Math.min(32, Math.max(10, frameNow - last));
        chatRobotWorldLastFrameAt = frameNow;
        if (!chatRobotWorldShouldBeVisible()) {
            chatWorldSyncRootVisibility();
            return;
        }
        const bounds = chatRobotWorldBounds();
        const fidelity = animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {});
        const graph = chatRobotWorldBuildPlatformGraph(bounds, fidelity);
        const worldMode = chatWorldCurrentMode(currentPreferences?.advanced?.interface || {});
        chatWorldSyncRootVisibility();
        const actors = [chatPrimaryPresenceState, ...chatAgentPresenceStateByActivityId.values()].filter(Boolean);
        const physicsWorld = worldMode === CHAT_WORLD_MODE_PHYSICS
            ? chatPhysicsWorldPrime(bounds, graph, actors)
            : (chatPhysicsWorldDestroy(), null);
        if (physicsWorld?.ready) {
            chatPhysicsWorldRenderVisualLayer(physicsWorld, bounds, graph, actors);
        }
        if (chatRobotWorldDebugScenario && Date.now() >= Number(chatRobotWorldDebugScenario.lockUntil || 0)) {
            chatRobotWorldDebugScenario = null;
        }
        actors.forEach((state) => {
            if (!state?.element || state.paused) {
                chatRobotWorldRenderActor(state, graph);
                return;
            }
            const scenarioLocked = safeString(state.kind) === 'primary'
                && chatRobotWorldDebugScenario
                && Date.now() < Number(chatRobotWorldDebugScenario.lockUntil || 0);
            if (state.portalTransfer) {
                chatRobotWorldAdvancePortalTransfer(state, bounds);
                chatRobotWorldRenderActor(state, graph);
                return;
            }
            if (safeString(state.kind) === 'delegation' && state.exiting) {
                if (!state.portalClosing && Date.now() >= Number(state.portalCloseAt || 0)) {
                    state.portalClosing = true;
                    chatRobotWorldPlayPortal(state, 'close');
                }
                state.vx = 0;
                state.vy = 0;
            } else if (!scenarioLocked && (Number(state.modeUntil || 0) <= Date.now()) && !chatTaskIsTerminal(state.status)) {
                chatRobotWorldRetarget(state, graph);
            }
            const motion = chatRobotWorldMotionProfile(fidelity);
            const walkSpeed = motion.walkSpeed * (state.kind === 'delegation' ? motion.helperSpeedScale : 1);
            const physicsHandled = Boolean(physicsWorld?.ready) && chatPhysicsWorldAdvanceActor(
                physicsWorld,
                state,
                dt,
                bounds,
                graph,
                walkSpeed,
                { scenarioLocked },
            );
            if (!physicsHandled) {
                if (state.transition) {
                    chatRobotWorldAdvanceTransition(state, dt, bounds);
                } else if (scenarioLocked) {
                    state.vx = 0;
                    state.vy = 0;
                    state.mode = 'inspect';
                    state.modeUntil = Date.now() + 320;
                } else if (!(safeString(state.kind) === 'delegation' && state.exiting)) {
                    const targetX = Number(state.targetX ?? state.x ?? 0);
                    const targetPlatform = graph.platformsById.get(safeString(state.targetPlatformId || state.currentPlatformId || ''));
                    const targetY = Number(targetPlatform ? (targetPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET) : (state.targetY ?? bounds.groundY));
                    const dx = targetX - Number(state.x || 0);
                    if (Math.abs(dx) > 3) {
                        state.facing = dx >= 0 ? 1 : -1;
                        state.vx = state.facing * walkSpeed;
                        if ((state.mode === 'sleep' || state.mode === 'workout') && safeString(state.status) === 'idle') {
                            state.vx *= 0.4;
                        }
                        state.x += state.vx * (dt / 16);
                    } else {
                        state.vx = 0;
                        state.x = targetX;
                    }
                    if (targetPlatform) {
                        state.x = Math.max(targetPlatform.x1 + 4, Math.min(targetPlatform.x2 - 4, Number(state.x || targetX)));
                        state.currentPlatformId = targetPlatform.id;
                    }
                    const desiredGround = Math.max(0, Math.min(bounds.height - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT, targetY));
                    if (Number(state.y || 0) < desiredGround - 1) {
                        state.vy = Math.min(CHAT_PRIMARY_ROBOT_FALL_SPEED_MAX, Number(state.vy || 0) + CHAT_PRIMARY_ROBOT_GRAVITY * (dt / 16));
                        state.y += state.vy * (dt / 16);
                        if (state.y >= desiredGround) {
                            state.y = desiredGround;
                            state.vy = 0;
                        }
                    } else {
                        state.y = desiredGround;
                        state.vy = 0;
                    }
                } else {
                    state.vx = 0;
                    state.vy = 0;
                }
            }
            if (chatTaskIsTerminal(state.status) && safeString(state.kind) === 'primary' && Date.now() >= Number(state.lingerUntil || 0)) {
                state.status = 'idle';
                state.summary = 'Standing by.';
                state.taskText = '';
                state.endedAt = Date.now();
                state.lingerUntil = 0;
                state.transition = null;
                chatRobotWorldSetSpeech(state, 'All done here. Back on standby.', 2800);
            }
            if (safeString(state.kind) === 'delegation' && state.exiting && Date.now() >= Number(state.exitAt || 0)) {
                state.routeElement?.remove?.();
                state.element?.remove();
                chatAgentPresenceStateByActivityId.delete(state.activityId);
            }
            chatRobotWorldRenderActor(state, graph);
        });
        chatRobotWorldSyncDebugState(graph, actors, frameNow);
    };
    chatRobotWorldRaf = window.requestAnimationFrame(step);
}

function chatWorldUpsertPresence(activityId, patch = {}) {
    const key = safeString(activityId);
    if (!key) return null;
    if (safeString(patch.kind) === 'primary') {
        const state = chatRobotWorldEnsurePrimaryState();
        Object.assign(state, patch);
        state.activityId = key;
        state.kind = 'primary';
        state.status = safeString(state.status || 'running').toLowerCase() || 'running';
        state.startedAt = Number(state.startedAt || Date.now());
        state.summary = safeString(state.summary || state.taskText) || 'Working the task.';
        if (!state.visibleSince) state.visibleSince = Date.now();
        if (chatTaskIsTerminal(state.status)) {
            state.endedAt = Number(state.endedAt || Date.now());
            state.lingerUntil = Math.max(Number(state.lingerUntil || 0), Date.now() + CHAT_PRIMARY_ROBOT_LINGER_MS);
            chatRobotWorldSetSpeech(state, safeString(state.status) === 'failed' ? 'Task failed.' : 'All done here.', 3200);
        } else {
            state.endedAt = 0;
            state.lingerUntil = 0;
            if (!state.modeUntil) {
                chatRobotWorldRetarget(state);
            }
        }
        chatRobotWorldRenderActor(state);
        chatWorldSyncRootVisibility();
        chatRobotWorldEnsureLoop();
        return state;
    }
    if (!chatRobotWorldShouldBeVisible()) return null;
    const existing = chatAgentPresenceStateByActivityId.get(key);
    const bounds = chatRobotWorldBounds();
    const spawnOrdinal = existing ? Number(existing.spawnOrdinal || 0) : chatHelperSpawnOrdinal++;
    const spawnRatios = [0.18, 0.78, 0.9, 0.28];
    const slotCenter = (bounds.width * spawnRatios[spawnOrdinal % spawnRatios.length]) + (Math.random() * 16) - 8;
    const spawnX = chatRobotWorldClamp(slotCenter, 28, Math.max(28, bounds.width - 28));
    const spawnFloorId = spawnX < (bounds.width * 0.5) ? 'floor-left' : 'floor-right';
    const state = existing || {
        activityId: key,
        kind: 'delegation',
        spawnOrdinal,
        element: null,
        x: spawnX,
        y: -56 - (Math.random() * 44),
        targetX: spawnX,
        targetY: bounds.groundY,
        vx: 0,
        vy: 0,
        facing: 1,
        paused: false,
        startedAt: Date.now(),
        endedAt: 0,
        mode: 'falling',
        modeUntil: 0,
        officeTaskId: '',
        officeAgentId: '',
        officeAgentName: '',
        identitySource: '',
        summary: '',
        taskText: '',
        status: 'running',
        color: '#9ad8ff',
        costume: 'none',
        tint: 'blue',
        homeX: spawnX,
        homeFloorId: spawnFloorId,
        visibleSince: Date.now(),
        lingerUntil: 0,
        exiting: false,
        exitAt: 0,
        transition: null,
        hiddenTransit: false,
        currentPlatformId: '',
        targetPlatformId: '',
        preferredDirection: 1,
        portalTransfer: null,
        portalCloseAt: 0,
        portalClosing: false,
        debugPropKind: '',
        debugPropPhase: '',
        physicsNeedsSnap: false,
    };
    Object.assign(state, patch);
    state.activityId = key;
    state.kind = 'delegation';
    state.spawnOrdinal = spawnOrdinal;
    state.status = safeString(state.status || 'running').toLowerCase();
    state.summary = safeString(state.summary || state.taskText) || 'Helper active.';
    if (!state.element) {
        state.element = chatRobotWorldCreateActorElement(key, state);
        chatRobotWorldPlayPortal(state, 'open');
        state.x = spawnX;
        state.y = -56 - (Math.random() * 44);
        state.targetX = spawnX;
        state.targetY = bounds.groundY;
        state.homeX = spawnX;
        state.homeFloorId = spawnFloorId;
        state.vy = 0;
        state.modeUntil = 0;
        chatRobotWorldSetSpeech(state, chatRobotWorldAmbientLine(state) || 'Helper online.', 1800);
    }
    if (chatTaskIsTerminal(state.status)) {
        state.endedAt = Number(state.endedAt || Date.now());
        state.lingerUntil = Date.now() + CHAT_AGENT_PRESENCE_EXIT_MS;
        chatRobotWorldRemoveHelper(key);
    } else {
        state.endedAt = 0;
        state.exiting = false;
        state.portalClosing = false;
        state.portalCloseAt = 0;
        if (!state.modeUntil && safeString(state.mode) !== 'falling') {
            chatRobotWorldRetarget(state);
        }
    }
    chatAgentPresenceStateByActivityId.set(key, state);
    chatRobotWorldRenderActor(state);
    chatWorldSyncRootVisibility();
    chatRobotWorldEnsureLoop();
    return state;
}

function chatWorldSetOfficeContext(activityId, context = {}) {
    const key = safeString(activityId);
    const state = key === safeString(chatPrimaryPresenceState?.activityId)
        ? chatPrimaryPresenceState
        : chatAgentPresenceStateByActivityId.get(key);
    if (!state) return;
    state.officeTaskId = safeString(context.taskId || state.officeTaskId);
    state.officeAgentId = safeString(context.agentId || state.officeAgentId);
    state.officeAgentName = safeString(context.agentName || state.officeAgentName || state.name || DEFAULT_AGENT_NAME);
}

function chatWorldTaskRuntimeTick() {
    chatTaskStripStateByMessageId.forEach((state, messageId) => {
        if (!state) return;
        renderMessageTaskStrip(messageId);
    });
    chatRobotWorldSyncPrimaryFromTasks();
    chatAgentPresenceStateByActivityId.forEach((state) => {
        chatRobotWorldRenderActor(state);
    });
    chatTaskRuntimeStopIfIdle();
}

function chatWorldTaskRuntimeStopIfIdle() {
    const hasLiveStrip = [...chatTaskStripStateByMessageId.values()].some((state) => state && !chatTaskIsTerminal(state.status));
    if (hasLiveStrip || chatAgentPresenceStateByActivityId.size > 0) return;
    if (chatTaskRuntimeTimer) {
        window.clearInterval(chatTaskRuntimeTimer);
        chatTaskRuntimeTimer = 0;
    }
}

function chatWorldSetPresence(activity) {
    chatRobotWorldEnsurePrimaryState();
    if (!chatRobotWorldShouldBeVisible()) {
        chatWorldSyncRootVisibility();
        return;
    }
    const sessionId = safeString(activity?.sessionId || taskContinuityLatestSessionId || activeChatId);
      const liveRows = Array.isArray(activity?.agents)
          ? activity.agents.filter((item) => delegationRowIsRenderableLive(item))
          : [];
    const nextIds = new Set();
    liveRows.forEach((row) => {
        const activityId = safeString(row?.execution_id || row?.task_id || row?.bot_id || row?.bot_name || row?.agent_id || row?.specialist_id);
        if (!activityId) return;
        nextIds.add(activityId);
        const identity = officeResolveAgentIdentity(
            row?.bot_name || row?.bot_id || row?.agent_id || row?.specialist_id,
            activityId,
        );
        chatAgentPresenceUpsert(activityId, {
            sessionId,
            bubbleId: chatTaskMessageBySessionId.get(sessionId) || '',
            name: identity.name,
            status: safeString(row?.state || row?.status || 'running'),
            taskText: safeString(row?.summary || row?.last_progress || row?.task || row?.current_task),
            summary: safeString(row?.summary || row?.last_progress || row?.task || row?.current_task),
            startedAt: missionToEpoch(safeString(row?.created_at || row?.updated_at)) || Date.now(),
            color: identity.color || '#7cd6ff',
            costume: identity.costume || 'visor',
            tint: identity.tint || 'blue',
            identitySource: identity.source || 'seed',
            officeAgentName: identity.name,
            officeAgentId: identity.id,
        });
    });
    [...chatAgentPresenceStateByActivityId.entries()].forEach(([activityId, state]) => {
        const stateSessionId = safeString(state?.sessionId);
        if (sessionId && stateSessionId && stateSessionId !== sessionId) {
            chatRobotWorldRemoveHelper(activityId);
            return;
        }
        if (!nextIds.has(activityId)) {
            chatRobotWorldRemoveHelper(activityId);
        }
    });
    chatRobotWorldSyncPrimaryFromTasks();
    chatWorldSyncRootVisibility();
    chatRobotWorldEnsureLoop();
}

function chatWorldEnsureDock() {
    return chatWorldEnsureUi();
}

function chatWorldPositionDock() {
    chatWorldSyncRootVisibility();
    return chatWorldEnsureUi();
}

function chatWorldLandAtDock(sourceNode = null) {
    void sourceNode;
    const primary = chatRobotWorldEnsurePrimaryState();
    primary.status = chatTaskIsTerminal(primary.status) ? 'idle' : primary.status;
    primary.summary = safeString(primary.summary) || 'Standing by.';
    if (!primary.modeUntil) {
        chatRobotWorldRetarget(primary);
    }
    chatRobotWorldRenderActor(primary);
    chatWorldSyncRootVisibility();
    chatRobotWorldEnsureLoop();
}

function chatWorldPortalOutLanded() {
    const primary = chatRobotWorldEnsurePrimaryState();
    primary.status = safeString(primary.status) || 'idle';
    primary.summary = safeString(primary.summary) || 'Standing by.';
    primary.mode = 'inspect';
    primary.modeUntil = Date.now() + 1800;
    chatRobotWorldSetSpeech(primary, 'Standing by on the floor.', 1800);
    chatRobotWorldRenderActor(primary);
    return Promise.resolve();
}

function ensureMissionRuntimeHero() {
    if (!missionWorkspace) return null;
    const shell = missionWorkspace.querySelector('.mission-shell');
    if (!(shell instanceof HTMLElement)) return null;
    let panel = shell.querySelector('.mission-runtime-panel');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('section');
        panel.className = 'mission-runtime-panel';
        panel.innerHTML = `
            <div class="mission-runtime-head">
                <div class="mission-runtime-copy">
                    <span class="mission-runtime-eyebrow">Current Task</span>
                    <strong data-role="title">No current task</strong>
                    <p data-role="summary">When Thomas delegates work, it lands here instead of inside chat.</p>
                </div>
                <div class="mission-runtime-status">
                    <span class="mission-meta-pill neutral" data-role="pill">Idle</span>
                    <span class="mission-runtime-status-text" data-role="status">Waiting for delegated work</span>
                </div>
            </div>
            <div class="mission-runtime-progress">
                <div class="mission-runtime-progress-rail" data-role="bar"><span data-role="fill"></span></div>
                <div class="mission-runtime-progress-meta">
                    <span data-role="elapsed">Elapsed --</span>
                    <span data-role="heartbeat">Heartbeat --</span>
                    <span data-role="agents">0 delegated agents</span>
                </div>
            </div>
            <div class="mission-runtime-list-wrap">
                <div class="mission-runtime-list-title">Delegated agents</div>
                <div class="mission-runtime-list" data-role="list"></div>
            </div>
        `;
        const header = shell.querySelector('.mission-header');
        const afterHeader = header && header.nextElementSibling ? header.nextElementSibling : null;
        if (afterHeader) {
            shell.insertBefore(panel, afterHeader);
        } else {
            shell.appendChild(panel);
        }
    }
    return {
        panel,
        title: panel.querySelector('[data-role="title"]'),
        summary: panel.querySelector('[data-role="summary"]'),
        pill: panel.querySelector('[data-role="pill"]'),
        status: panel.querySelector('[data-role="status"]'),
        bar: panel.querySelector('[data-role="bar"]'),
        fill: panel.querySelector('[data-role="fill"]'),
        elapsed: panel.querySelector('[data-role="elapsed"]'),
        heartbeat: panel.querySelector('[data-role="heartbeat"]'),
        agents: panel.querySelector('[data-role="agents"]'),
        list: panel.querySelector('[data-role="list"]'),
    };
}

function missionRuntimePillClass(runtime) {
    const heartbeat = safeString(runtime?.heartbeat);
    const status = missionStatusValue(runtime?.primary?.status);
    if (!runtime || runtime.activeCount <= 0) return 'neutral';
    if (status === 'blocked' || status === 'awaiting_approval') return 'warn';
    if (heartbeat === 'stalled') return 'danger';
    if (status === 'queued' || status === 'pending' || heartbeat === 'starting') return 'neutral';
    return 'ok';
}

function missionRuntimeStatusText(runtime) {
    if (!runtime || runtime.activeCount <= 0) return 'Waiting for active work';
    const room = safeString(runtime?.primary?.room).replace(/_/g, ' ');
    const bits = [
        missionStatusLabel(runtime?.primary?.status),
        room ? `room ${room}` : '',
        `updated ${missionRelativeTime(runtime?.updatedAt)}`,
    ].filter(Boolean);
    return bits.join(' | ');
}
