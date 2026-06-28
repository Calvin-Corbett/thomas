function chatPhysicsWorldSnapActorsToStableSurfaces(worldState, actors = [], graph = null) {
    if (!worldState?.ready && !worldState?.scene) return;
    (actors || []).forEach((state) => {
        if (!state) return;
        if (state.portalTransfer || state.transition) return;
        if (safeString(state.mode) === 'falling') return;
        if (!state.physicsNeedsSnap) return;
        const actorRecord = chatPhysicsWorldEnsureActor(worldState, state);
        if (!actorRecord?.body) return;
        const stablePlatform = chatPhysicsWorldStablePlatformForState(state, graph);
        if (!stablePlatform) return;
        const x1 = Number(stablePlatform.x1 || 0);
        const x2 = Number(stablePlatform.x2 || x1);
        const fallbackX = Math.round((x1 + x2) * 0.5);
        const nextX = chatRobotWorldClamp(
            Number.isFinite(Number(state.targetX)) ? Number(state.targetX) : Number(state.x || fallbackX),
            x1 + 6,
            x2 - 6,
        );
        state.x = nextX;
        state.y = Number(stablePlatform.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
        state.targetX = nextX;
        state.targetY = state.y;
        state.currentPlatformId = safeString(stablePlatform.id);
        state.targetPlatformId = safeString(stablePlatform.id);
        state.hiddenTransit = false;
        state.vx = 0;
        state.vy = 0;
        chatPhysicsWorldSyncBodyFromState(state, actorRecord);
        try {
            actorRecord.body.setVelocity(0, 0);
        } catch (_) {}
        state.physicsNeedsSnap = false;
        chatPhysicsWorldRenderActorVisual(state, actorRecord);
    });
}

function chatPhysicsWorldSyncActors(worldState, actors) {
    if (!worldState?.scene) return;
    const liveIds = new Set((actors || []).map((state) => safeString(state?.activityId)).filter(Boolean));
    [...(worldState.actorBodies?.keys?.() || [])].forEach((activityId) => {
        if (!liveIds.has(activityId)) {
            chatPhysicsWorldRemoveActor(worldState, activityId);
        }
    });
    (actors || []).forEach((state) => {
        chatPhysicsWorldEnsureActor(worldState, state);
    });
}

function chatPhysicsWorldDestroy() {
    const worldState = chatPhysicsWorldState;
    if (!worldState) return;
    try {
        worldState.game?.destroy?.(true);
    } catch (_) {}
    if (worldState.layer instanceof HTMLElement) {
        worldState.layer.classList.add('hidden');
        worldState.layer.innerHTML = '';
    }
    chatPhysicsWorldState = null;
}

function chatPhysicsWorldPrime(bounds, graph, actors = []) {
    if (chatWorldCurrentMode() !== CHAT_WORLD_MODE_PHYSICS) {
        chatPhysicsWorldDestroy();
        return null;
    }
    const layer = chatRobotWorldPhysicsLayer();
    if (!(layer instanceof HTMLElement)) return null;
    layer.classList.remove('hidden');
    layer.style.width = `${Math.round(Number(bounds?.width || 0))}px`;
    layer.style.height = `${Math.round(Number(bounds?.height || 0))}px`;
    const nextSignature = chatPhysicsWorldStateSignature(bounds, graph);
    if (chatPhysicsWorldState?.ready && chatPhysicsWorldState.signature !== nextSignature) {
        chatPhysicsWorldRebuildStatics(chatPhysicsWorldState, bounds, graph);
        chatPhysicsWorldState.signature = nextSignature;
    }
    if (chatPhysicsWorldState?.ready) {
        chatPhysicsWorldState.bounds = bounds;
        chatPhysicsWorldState.graph = graph;
        const signatureChanged = chatPhysicsWorldState.signature !== nextSignature;
        chatPhysicsWorldState.signature = nextSignature;
        chatPhysicsWorldSyncActors(chatPhysicsWorldState, actors);
        if (signatureChanged) {
            (actors || []).forEach((state) => {
                if (!state || safeString(state.mode) === 'falling') return;
                state.physicsNeedsSnap = true;
            });
        }
        if (chatPhysicsWorldState.signature === nextSignature) {
            chatPhysicsWorldSnapActorsToStableSurfaces(chatPhysicsWorldState, actors, graph);
        }
        return chatPhysicsWorldState;
    }
    if (chatPhysicsWorldState?.loadingPromise) return chatPhysicsWorldState;
    const worldState = {
        layer,
        bounds,
        graph,
        signature: nextSignature,
        actorBodies: new Map(),
        staticBodies: [],
        game: null,
        scene: null,
        ready: false,
        loadingPromise: null,
    };
    chatPhysicsWorldState = worldState;
    worldState.loadingPromise = (async () => {
        const Phaser = await moduleWorkbenchLoadPhaser();
        if (chatWorldCurrentMode() !== CHAT_WORLD_MODE_PHYSICS || chatPhysicsWorldState !== worldState) return null;
        let resolveSceneReady = () => {};
        const readyPromise = new Promise((resolve) => {
            resolveSceneReady = resolve;
        });
        worldState.game = new Phaser.Game({
            type: Phaser.CANVAS,
            parent: layer,
            width: Math.max(220, Math.round(Number(bounds?.width || 0))),
            height: Math.max(140, Math.round(Number(bounds?.height || 0))),
            transparent: true,
            audio: { noAudio: true },
            banner: false,
            fps: { target: 60, forceSetTimeOut: false },
            physics: {
                default: 'arcade',
                arcade: {
                    gravity: { y: 980 },
                    debug: false,
                },
            },
            scene: {
                create() {
                    worldState.scene = this;
                    this.cameras.main.setBackgroundColor('rgba(0,0,0,0)');
                    resolveSceneReady(this);
                },
            },
        });
        await readyPromise;
        if (chatPhysicsWorldState !== worldState) return null;
        chatPhysicsWorldRebuildStatics(worldState, bounds, graph);
        chatPhysicsWorldSyncActors(worldState, actors);
        chatPhysicsWorldSnapActorsToStableSurfaces(worldState, actors, graph);
        chatPhysicsWorldRenderVisualLayer(worldState, bounds, graph, actors);
        worldState.ready = true;
        worldState.loadingPromise = null;
        return worldState;
    })().catch((error) => {
        console.error('Failed to initialize chat physics world', error);
        if (chatPhysicsWorldState === worldState) {
            chatPhysicsWorldDestroy();
        }
        return null;
    });
    return worldState;
}

function chatPhysicsWorldAdvanceActor(worldState, state, dt, bounds, graph, walkSpeed, { scenarioLocked = false } = {}) {
    const actorRecord = chatPhysicsWorldEnsureActor(worldState, state);
    if (!actorRecord?.body) return false;
    const body = actorRecord.body;
    const targetPlatform = graph?.platformsById?.get(safeString(state.targetPlatformId || state.currentPlatformId || '')) || null;
    if (safeString(state.mode) === 'falling') {
        chatPhysicsWorldSetActorGravity(actorRecord, true);
        body.setVelocityX(Number(body.velocity?.x || 0) * 0.92);
        chatPhysicsWorldSyncStateFromBody(state, actorRecord, bounds);
        const landedPlatform = chatRobotWorldCurrentPlatform(state, graph?.platforms || []);
        if (landedPlatform && (body.blocked?.down || body.touching?.down)) {
            state.currentPlatformId = safeString(landedPlatform.id);
            state.targetPlatformId = safeString(landedPlatform.id);
            state.homeFloorId = safeString(state.homeFloorId || landedPlatform.id);
            state.y = Number(landedPlatform.y || bounds.groundY) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
            state.targetY = state.y;
            state.mode = 'idle';
            state.modeUntil = Date.now() + 1800;
            state.physicsNeedsSnap = false;
            chatRobotWorldSetSpeech(state, chatRobotWorldAmbientLine(state) || 'Helper online.', 1600);
            chatPhysicsWorldSyncBodyFromState(state, actorRecord);
        }
        chatPhysicsWorldRenderActorVisual(state, actorRecord);
        return true;
    }
    if (state.portalTransfer) {
        chatPhysicsWorldSetActorGravity(actorRecord, false);
        chatRobotWorldAdvancePortalTransfer(state, bounds);
        chatPhysicsWorldSyncBodyFromState(state, actorRecord);
        chatPhysicsWorldRenderActorVisual(state, actorRecord);
        return true;
    }
    if (state.transition) {
        chatPhysicsWorldSetActorGravity(actorRecord, false);
        chatRobotWorldAdvanceTransition(state, dt, bounds);
        chatPhysicsWorldSyncBodyFromState(state, actorRecord);
        chatPhysicsWorldRenderActorVisual(state, actorRecord);
        return true;
    }
    chatPhysicsWorldSetActorGravity(actorRecord, true);
    if (targetPlatform && Number(state.postTransitionStickUntil || 0) > Date.now()) {
        state.x = chatRobotWorldClamp(
            Number(state.x || 0),
            Number(targetPlatform.x1 || 0) + 4,
            Number(targetPlatform.x2 || 0) - 4,
        );
        state.y = Number(targetPlatform.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
        chatPhysicsWorldSyncBodyFromState(state, actorRecord);
        state.currentPlatformId = safeString(targetPlatform.id);
        chatPhysicsWorldRenderActorVisual(state, actorRecord);
        return true;
    }
    if (scenarioLocked || (safeString(state.kind) === 'delegation' && state.exiting)) {
        body.setVelocityX(0);
        chatPhysicsWorldSyncStateFromBody(state, actorRecord, bounds);
        chatPhysicsWorldRenderActorVisual(state, actorRecord);
        return true;
    }
    const targetX = Number(state.targetX ?? state.x ?? 0);
    const currentCenterX = Number(actorRecord.node.x || 0);
    const desiredCenterX = targetX + actorRecord.metrics.centerOffsetX;
    const dx = desiredCenterX - currentCenterX;
    let desiredVelocityX = 0;
    if (Math.abs(dx) > 3) {
        state.facing = dx >= 0 ? 1 : -1;
        desiredVelocityX = (dx >= 0 ? 1 : -1) * Math.max(26, walkSpeed * 360);
        if ((state.mode === 'sleep' || state.mode === 'workout') && safeString(state.status) === 'idle') {
            desiredVelocityX *= 0.35;
        }
    }
    if (targetPlatform) {
        const minCenterX = Number(targetPlatform.x1 || 0) + actorRecord.metrics.centerOffsetX - 2;
        const maxCenterX = Number(targetPlatform.x2 || 0) - (46 - actorRecord.metrics.centerOffsetX) + 2;
        if (currentCenterX <= minCenterX && desiredVelocityX < 0) desiredVelocityX = 0;
        if (currentCenterX >= maxCenterX && desiredVelocityX > 0) desiredVelocityX = 0;
    }
    body.setVelocityX(desiredVelocityX);
    chatPhysicsWorldSyncStateFromBody(state, actorRecord, bounds);
    const landedPlatform = chatRobotWorldCurrentPlatform(state, graph?.platforms || []);
    if (landedPlatform) {
        state.currentPlatformId = safeString(landedPlatform.id);
    }
    if (
        targetPlatform
        && landedPlatform
        && safeString(landedPlatform.id) === safeString(targetPlatform.id)
        && (body.blocked?.down || body.touching?.down)
    ) {
        state.x = chatRobotWorldClamp(
            Number(state.x || 0),
            Number(targetPlatform.x1 || 0) + 4,
            Number(targetPlatform.x2 || 0) - 4,
        );
        state.y = Number(targetPlatform.y || 0) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
        chatPhysicsWorldSyncBodyFromState(state, actorRecord);
    }
    chatPhysicsWorldRenderActorVisual(state, actorRecord);
    return true;
}

function chatPhysicsWorldActorDebugRow(activityId) {
    const record = chatPhysicsWorldState?.actorBodies?.get?.(safeString(activityId));
    const body = record?.body;
    const node = record?.node;
    if (!record || !body || !node) return null;
    return {
        bodyCenterX: Math.round(Number(node.x || 0)),
        bodyCenterY: Math.round(Number(node.y || 0)),
        bodyVelocityX: Math.round(Number(body.velocity?.x || 0)),
        bodyVelocityY: Math.round(Number(body.velocity?.y || 0)),
        bodyBlockedDown: Boolean(body.blocked?.down || body.touching?.down),
        bodyBlockedLeft: Boolean(body.blocked?.left),
        bodyBlockedRight: Boolean(body.blocked?.right),
    };
}

function chatWorldSyncRootVisibility() {
    const root = chatWorldEnsureUi();
    if (!(root instanceof HTMLElement)) {
        return;
    }
    const hasHelpers = chatAgentPresenceStateByActivityId.size > 0;
    const show = chatRobotWorldShouldBeVisible() && (Boolean(chatPrimaryPresenceState?.element) || hasHelpers);
    root.classList.toggle('is-hidden', !show);
    root.classList.toggle('is-active', show);
    root.dataset.worldMode = chatWorldCurrentMode();
    const bounds = chatRobotWorldBounds();
    root.style.left = `${bounds.left}px`;
    root.style.top = `${bounds.top}px`;
    root.style.width = `${bounds.width}px`;
    root.style.height = `${bounds.height}px`;
    root.style.setProperty('--chat-robot-ground-y', `${bounds.groundY}px`);
    const physicsLayer = root.querySelector('[data-role="physics"]');
    if (physicsLayer instanceof HTMLElement) {
        physicsLayer.classList.toggle('hidden', !(show && chatWorldCurrentMode() === CHAT_WORLD_MODE_PHYSICS));
        physicsLayer.style.width = `${bounds.width}px`;
        physicsLayer.style.height = `${bounds.height}px`;
    }
    const legacyDock = document.getElementById(CHAT_ROBOT_DOCK_ID);
    if (legacyDock instanceof HTMLElement && show) {
        legacyDock.classList.add('is-hidden');
        legacyDock.innerHTML = '';
    }
}

function chatRobotWorldOfficeButtonHandler(activityId, state) {
    return (event) => {
        event.preventDefault();
        event.stopPropagation();
        openOfficeForTaskContext({
            activityId,
            agentId: safeString(state?.officeAgentId),
            agentName: safeString(state?.officeAgentName || state?.name || DEFAULT_AGENT_NAME),
        });
    };
}

function chatRobotWorldActorMarkup(name = 'Thomas', helper = false) {
    return `
        <span class="chat-robot-world-portal chat-robot-portal hidden" data-role="portal">
            <span class="chat-game-portal-ring"></span>
            <span class="chat-game-portal-ring ring-inner"></span>
            <span class="chat-game-portal-core"></span>
        </span>
        <span class="chat-robot-world-shadow" aria-hidden="true"></span>
        <span class="chat-robot-world-bot ${helper ? 'is-helper' : 'is-primary'}" data-role="bot">
            ${chatTaskRobotAgentMarkup()}
        </span>
        <span class="chat-robot-world-label" data-role="label">${escapeHtml(name)}</span>
        <span class="chat-robot-world-speech hidden" data-role="speech"></span>
        <span class="chat-robot-world-bubble" data-role="bubble">
            <strong data-role="name">${escapeHtml(name)}</strong>
            <p data-role="summary"></p>
            <div class="chat-robot-world-bubble-meta">
                <span data-role="status">Standing by</span>
                <button type="button" data-role="open">Open Office</button>
            </div>
        </span>
    `;
}

function chatRobotWorldCreateActorElement(activityId, state) {
    const stage = chatRobotWorldStage();
    if (!(stage instanceof HTMLElement)) return null;
    const el = document.createElement('button');
    el.type = 'button';
    el.className = `chat-robot-world-actor${state?.kind === 'delegation' ? ' is-helper' : ' is-primary'}`;
    el.dataset.activityId = safeString(activityId);
    el.innerHTML = chatRobotWorldActorMarkup(safeString(state?.name) || DEFAULT_AGENT_NAME, state?.kind === 'delegation');
    const openBtn = el.querySelector('[data-role="open"]');
    if (openBtn instanceof HTMLButtonElement) {
        openBtn.addEventListener('click', chatRobotWorldOfficeButtonHandler(activityId, state));
    }
    el.addEventListener('click', (event) => {
        if (event.target instanceof Element && event.target.closest('[data-role="open"]')) return;
        state.paused = !state.paused;
        el.classList.toggle('is-expanded', Boolean(state.paused));
    });
    const routeEl = document.createElement('span');
    routeEl.className = 'chat-robot-world-route hidden';
    routeEl.dataset.role = 'route';
    routeEl.dataset.activityId = safeString(activityId);
    stage.appendChild(routeEl);
    state.routeElement = routeEl;
    stage.appendChild(el);
    return el;
}

function chatRobotWorldSetSpeech(state, textRaw, holdMs = 2600) {
    if (!state?.element) return;
    const speechEl = state.element.querySelector('[data-role="speech"]');
    if (!(speechEl instanceof HTMLElement)) return;
    const text = chatTaskCheckpointText(textRaw);
    if (!text) {
        speechEl.classList.add('hidden');
        speechEl.textContent = '';
        state.speechUntil = 0;
        return;
    }
    state.speechUntil = Date.now() + Math.max(1200, Number(holdMs) || 2600);
    speechEl.textContent = text;
    speechEl.classList.remove('hidden');
    state.element.classList.add('is-speaking');
}

function chatRobotWorldPlayPortal(state, mode = 'open') {
    if (!state?.element) return;
    const portal = state.element.querySelector('[data-role="portal"]');
    if (!(portal instanceof HTMLElement)) return;
    portal.classList.remove('hidden', 'portal-opening', 'portal-closing', 'portal-idle');
    if (mode === 'close') {
        portal.classList.add('portal-opening');
        window.setTimeout(() => {
            portal.classList.remove('portal-opening');
            portal.classList.add('portal-closing');
        }, 120);
        window.setTimeout(() => {
            portal.classList.add('hidden');
            portal.classList.remove('portal-closing');
        }, 720);
        return;
    }
    portal.classList.add('portal-opening');
    window.setTimeout(() => {
        portal.classList.remove('portal-opening');
        portal.classList.add('portal-closing');
    }, 420);
    window.setTimeout(() => {
        portal.classList.add('hidden');
        portal.classList.remove('portal-closing');
    }, 980);
}

function chatRobotWorldApplyPalette(state) {
    if (!state?.element) return;
    const palette = officeAgentPalette({ color: state.color || '#9ad8ff' });
    state.element.style.setProperty('--agent-primary', palette.primary);
    state.element.style.setProperty('--agent-secondary', palette.secondary);
    state.element.style.setProperty('--agent-glow', palette.glow);
    const agentEl = state.element.querySelector('.office-pixel-agent, .chat-robot-agent');
    if (!(agentEl instanceof HTMLElement)) return;
    agentEl.style.setProperty('--agent-primary', palette.primary);
    agentEl.style.setProperty('--agent-secondary', palette.secondary);
    agentEl.style.setProperty('--agent-glow', palette.glow);
    agentEl.classList.toggle('facing-left', Number(state.facing || 1) < 0);
    CHAT_ROBOT_ANIMATIONS.forEach((anim) => agentEl.classList.remove(`chat-robot-anim-${anim}`));
    const behavior = safeString(state.behaviorClass).replace(/^chat-robot-anim-/, '');
    if (behavior) {
        agentEl.classList.add(`chat-robot-anim-${behavior}`);
    }
    agentEl.classList.remove('costume-cap', 'costume-visor', 'costume-headset', 'costume-bowtie', 'costume-toolbelt', 'costume-satchel', 'costume-scarf', 'costume-badge', 'costume-tablet', 'costume-wrench', 'costume-mug');
    const costume = safeString(state.costume || 'none').toLowerCase();
    if (costume && costume !== 'none') {
        agentEl.classList.add(`costume-${costume}`);
    }
}

function chatRobotWorldBehaviorForMode(modeRaw = '') {
    const mode = safeString(modeRaw).toLowerCase();
    if (mode === 'sleep') return 'napping';
    if (mode === 'workout') return 'lifting';
    if (mode === 'inspect') return 'scanning';
    if (mode === 'perch') return 'looking';
    return officePick(['bouncing', 'waving', 'shimmy', 'looking']) || 'looking';
}

function chatRobotWorldCurrentPlatform(state, platforms = []) {
    const actorY = Number(state?.y ?? 0) + CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
    const actorX = Number(state?.x ?? 0) + 23;
    return platforms.find((platform) => (
        actorX >= (platform.x1 - 12)
        && actorX <= (platform.x2 + 12)
        && Math.abs(actorY - platform.y) <= 12
    )) || null;
}

function chatRobotWorldFindRoute(graph, fromId, toId) {
    const startId = safeString(fromId);
    const targetId = safeString(toId);
    if (!startId || !targetId) return [];
    if (startId === targetId) return [startId];
    const queue = [[startId]];
    const seen = new Set([startId]);
    while (queue.length) {
        const route = queue.shift();
        const nodeId = route?.[route.length - 1];
        if (!nodeId) continue;
        const neighbors = graph?.edges?.get(nodeId) || [];
        for (const neighbor of neighbors) {
            const nextId = safeString(neighbor?.to);
            if (!nextId || seen.has(nextId)) continue;
            const nextRoute = [...route, nextId];
            if (nextId === targetId) return nextRoute;
            seen.add(nextId);
            queue.push(nextRoute);
        }
    }
    return [];
}

function chatRobotWorldTransitionKindForFidelity(fidelityRaw) {
    const fidelity = normalizeAnimationFidelity(fidelityRaw, ANIMATION_FIDELITY_HIGH);
    if (fidelity === ANIMATION_FIDELITY_MINIMAL) return '';
    if (fidelity === ANIMATION_FIDELITY_BALANCED) return 'ladder';
    return officePick(['ladder', 'stairs', 'lift']) || 'ladder';
}

function chatRobotWorldCreateTransition(state, segments = [], meta = {}) {
    if (!Array.isArray(segments) || segments.length === 0) return null;
    const first = segments[0];
    return {
        kind: safeString(meta.kind || first.kind || ''),
        routeKind: safeString(meta.routeKind || first.routeKind || ''),
        segments,
        index: 0,
        startedAt: performance.now(),
        fromX: Number(state?.x || 0),
        fromY: Number(state?.y || 0),
        hiddenTransit: Boolean(first.hidden),
        targetPlatformId: safeString(meta.targetPlatformId || first.platformId || ''),
    };
}

function chatRobotWorldPlatformCenter(platform) {
    if (!platform) return 0;
    return (Number(platform.x1 || 0) + Number(platform.x2 || 0)) * 0.5;
}

function chatRobotWorldAmbientZoneForX(x, bounds = chatRobotWorldBounds()) {
    return Number(x || 0) <= (Number(bounds.width || 0) * 0.5) ? 'left' : 'right';
}

function chatRobotWorldRoutePlacement(state, transition, segment) {
    if (!state || !transition || !segment) return null;
    const routeKind = safeString(segment.routeKind || transition.routeKind || '');
    if (!routeKind) return null;
    const currentX = Number(state.x || transition.fromX || 0);
    const currentY = Number(state.y || transition.fromY || 0);
    const targetX = Number(segment.x || currentX);
    const targetY = Number(segment.y || currentY);
    if (routeKind === 'door') {
        const hidden = Boolean(segment.hidden);
        const doorX = Math.round(hidden ? targetX : currentX);
        const doorY = Math.round(Math.max(currentY, targetY) + 10);
        return {
            kind: routeKind,
            phase: hidden ? 'transit' : (transition.index > 0 ? 'opening' : 'staging'),
            left: doorX - 16,
            top: doorY - 4,
            width: 32,
            height: 36,
        };
    }
    const propAnchorX = Number(segment.propX || targetX);
    const propTopY = Number.isFinite(segment.propTopY) ? Number(segment.propTopY) : Math.min(currentY, targetY);
    const propBottomY = Number.isFinite(segment.propBottomY) ? Number(segment.propBottomY) : Math.max(currentY, targetY);
    const phase = segment.kind === 'walk' ? 'staging' : 'active';
    if (routeKind === 'ladder') {
        const height = Math.max(48, Math.round(propBottomY - propTopY) + 20);
        return {
            kind: routeKind,
            phase,
            left: Math.round(propAnchorX - 10),
            top: Math.round(propTopY - 8),
            width: 20,
            height,
        };
    }
    if (routeKind === 'lift' || routeKind === 'magic') {
        const height = Math.max(58, Math.round(propBottomY - propTopY) + 26);
        return {
            kind: routeKind,
            phase,
            left: Math.round(propAnchorX - 14),
            top: Math.round(propTopY - 10),
            width: 28,
            height,
        };
    }
    const baseLeft = Math.min(propAnchorX, targetX) - 12;
    const width = Math.max(60, Math.abs(targetX - propAnchorX) + 44);
    const height = Math.max(32, Math.round(propBottomY - propTopY) + 18);
    return {
        kind: routeKind || 'stairs',
        phase,
        left: Math.round(baseLeft),
        top: Math.round(propTopY - 6),
        width: Math.round(width),
        height,
    };
}

function chatRobotWorldPlanTransition(state, targetPlatform, bounds, graph, fidelityRaw, options = {}) {
    const fidelity = normalizeAnimationFidelity(fidelityRaw, ANIMATION_FIDELITY_HIGH);
    if (fidelity === ANIMATION_FIDELITY_MINIMAL || !targetPlatform) return null;
    const geometry = graph?.geometry || chatRobotWorldGeometry(bounds);
    const platforms = graph?.platforms || [];
    const platformsById = graph?.platformsById || new Map(platforms.map((platform) => [platform.id, platform]));
    const currentPlatform = platformsById.get(safeString(state?.currentPlatformId))
        || chatRobotWorldCurrentPlatform(state, platforms)
        || platforms.find((platform) => platform.kind === 'floor')
        || null;
    const currentX = Number(state?.x || 0);
    const currentY = Number(state?.y || bounds.groundY);
    const targetX = Number(state?.targetX || Math.round((targetPlatform.x1 + targetPlatform.x2) * 0.5));
    const targetY = Number(targetPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET);
    if (!currentPlatform) return null;
    const routeIds = chatRobotWorldFindRoute(graph, currentPlatform.id, targetPlatform.id);
    if (!routeIds.length || routeIds.length === 1) return null;
    const segments = [];
    let cursorX = currentX;
    let cursorY = currentY;
    for (let i = 1; i < routeIds.length; i += 1) {
        const fromPlatform = platformsById.get(routeIds[i - 1]);
        const toPlatform = platformsById.get(routeIds[i]);
        if (!fromPlatform || !toPlatform) continue;
        const edge = (graph?.edges?.get(fromPlatform.id) || []).find((item) => safeString(item?.to) === toPlatform.id) || {};
        const routeKind = safeString(options.routeKindOverride || edge.routeKind || '');
        if (safeString(edge.kind) === 'tunnel' && geometry.backgroundTunnel) {
            const movingRight = toPlatform.x2 > fromPlatform.x1;
            const entryX = movingRight ? geometry.backgroundTunnel.leftDoorX : geometry.backgroundTunnel.rightDoorX;
            const exitX = movingRight ? geometry.backgroundTunnel.rightDoorX : geometry.backgroundTunnel.leftDoorX;
            segments.push(
                {
                    x: entryX,
                    y: fromPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    durationMs: 680,
                    kind: 'tunnel',
                    routeKind: 'door',
                    hidden: false,
                    platformId: fromPlatform.id,
                    propX: entryX,
                    propTopY: fromPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    propBottomY: fromPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                },
                {
                    x: exitX,
                    y: toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    durationMs: 1080,
                    kind: 'tunnel',
                    routeKind: 'door',
                    hidden: true,
                    platformId: toPlatform.id,
                    propX: exitX,
                    propTopY: toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    propBottomY: toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                },
            );
            cursorX = exitX;
            cursorY = toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
            continue;
        }
        if (safeString(edge.kind) === 'climb') {
            const movingRight = ((toPlatform.x1 + toPlatform.x2) * 0.5) >= ((fromPlatform.x1 + fromPlatform.x2) * 0.5);
            const startEdgeX = movingRight
                ? Math.max(fromPlatform.x1 + 14, fromPlatform.x2 - 20)
                : Math.min(fromPlatform.x2 - 14, fromPlatform.x1 + 20);
            if (Math.abs(startEdgeX - cursorX) > 10) {
                segments.push({
                    x: startEdgeX,
                    y: fromPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    durationMs: 560,
                    kind: 'walk',
                    routeKind,
                    hidden: false,
                    platformId: fromPlatform.id,
                    propX: startEdgeX,
                    propTopY: Math.min(fromPlatform.y, toPlatform.y) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    propBottomY: Math.max(fromPlatform.y, toPlatform.y) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                });
            }
            if (routeKind === 'stairs') {
                const stairEndX = movingRight
                    ? chatRobotWorldClamp(startEdgeX + 78, toPlatform.x1 + 16, toPlatform.x2 - 18)
                    : chatRobotWorldClamp(startEdgeX - 78, toPlatform.x1 + 18, toPlatform.x2 - 16);
                segments.push({
                    x: stairEndX,
                    y: toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    durationMs: fidelity === ANIMATION_FIDELITY_HIGH ? 1360 : 1040,
                    kind: 'climb',
                    routeKind,
                    hidden: false,
                    platformId: toPlatform.id,
                    propX: startEdgeX,
                    propTopY: Math.min(fromPlatform.y, toPlatform.y) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    propBottomY: Math.max(fromPlatform.y, toPlatform.y) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                });
                cursorX = stairEndX;
                cursorY = toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
                continue;
            }
            const anchorX = movingRight
                ? chatRobotWorldClamp(toPlatform.x1 + 18, toPlatform.x1 + 12, toPlatform.x2 - 14)
                : chatRobotWorldClamp(toPlatform.x2 - 18, toPlatform.x1 + 14, toPlatform.x2 - 12);
            segments.push({
                x: anchorX,
                y: toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                durationMs: routeKind === 'lift'
                    ? (fidelity === ANIMATION_FIDELITY_HIGH ? 1180 : 980)
                    : (fidelity === ANIMATION_FIDELITY_HIGH ? 980 : 820),
                kind: 'climb',
                routeKind,
                hidden: false,
                platformId: toPlatform.id,
                propX: anchorX,
                propTopY: Math.min(fromPlatform.y, toPlatform.y) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                propBottomY: Math.max(fromPlatform.y, toPlatform.y) - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
            });
            cursorX = anchorX;
            cursorY = toPlatform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET;
        }
    }
    segments.push({
        x: targetX,
        y: targetY,
        durationMs: 620,
        kind: 'walk',
        routeKind: safeString(segments[segments.length - 1]?.routeKind || ''),
        hidden: false,
        platformId: targetPlatform.id,
    });
    if (!segments.length) return null;
    return chatRobotWorldCreateTransition(state, segments, {
        kind: safeString(segments[0]?.kind || 'walk'),
        routeKind: safeString(segments[0]?.routeKind || ''),
        targetPlatformId: targetPlatform.id,
    });
}

function chatRobotWorldAdvanceTransition(state, dt, bounds) {
    const transition = state?.transition;
    if (!transition || !Array.isArray(transition.segments) || transition.segments.length === 0) return false;
    const segment = transition.segments[transition.index];
    if (!segment) {
        state.transition = null;
        return false;
    }
    const durationMs = Math.max(120, Number(segment.durationMs || 420));
    const elapsed = Math.max(0, performance.now() - Number(transition.startedAt || 0));
    const t = Math.min(1, elapsed / durationMs);
    const nextX = transition.fromX + ((Number(segment.x) - transition.fromX) * t);
    const nextY = transition.fromY + ((Number(segment.y) - transition.fromY) * t);
    const deltaX = nextX - Number(state?.x ?? transition.fromX ?? 0);
    state.x = nextX;
    state.y = nextY;
    if (Math.abs(deltaX) >= 0.5) {
        state.facing = deltaX >= 0 ? 1 : -1;
    }
    state.hiddenTransit = Boolean(segment.hidden);
    if (t < 1) return true;
    transition.index += 1;
    if (transition.index >= transition.segments.length) {
        state.x = Number(segment.x);
        state.y = Math.max(0, Math.min(bounds.height - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT, Number(segment.y)));
        state.currentPlatformId = safeString(segment.platformId || transition.targetPlatformId || state.currentPlatformId);
        state.postTransitionStickUntil = Date.now() + 320;
        state.transition = null;
        state.hiddenTransit = false;
        return false;
    }
    transition.fromX = Number(segment.x);
    transition.fromY = Number(segment.y);
    transition.startedAt = performance.now();
    state.hiddenTransit = Boolean(transition.segments[transition.index]?.hidden);
    return true;
}

function chatRobotWorldRenderRoute(state) {
    if (!state?.element) return;
    const routeEl = state.routeElement || state.element.querySelector('[data-role="route"]');
    if (!(routeEl instanceof HTMLElement)) return;
    if (chatWorldIsPhysicsMode()) {
        routeEl.className = 'chat-robot-world-route hidden';
        routeEl.removeAttribute('style');
        routeEl.dataset.phase = '';
        routeEl.dataset.kind = '';
        state.debugPropKind = safeString(state?.transition?.routeKind || '');
        state.debugPropPhase = safeString(state?.transition ? 'physics' : '');
        return;
    }
    const transition = state.transition;
    if (!transition || !transition.routeKind) {
        routeEl.className = 'chat-robot-world-route hidden';
        routeEl.removeAttribute('style');
        routeEl.dataset.phase = '';
        routeEl.dataset.kind = '';
        state.debugPropKind = '';
        state.debugPropPhase = '';
        return;
    }
    const currentSegment = transition.segments[Math.min(transition.index, transition.segments.length - 1)] || null;
    const placement = chatRobotWorldRoutePlacement(state, transition, currentSegment);
    if (!placement) {
        routeEl.className = 'chat-robot-world-route hidden';
        routeEl.removeAttribute('style');
        routeEl.dataset.phase = '';
        routeEl.dataset.kind = '';
        state.debugPropKind = '';
        state.debugPropPhase = '';
        return;
    }
    const routeKind = safeString(placement.kind).replace(/[^a-z0-9_-]/gi, '') || 'ladder';
    routeEl.className = `chat-robot-world-route route-${routeKind}`;
    routeEl.dataset.phase = safeString(placement.phase || '');
    routeEl.dataset.kind = routeKind;
    routeEl.style.left = `${Math.round(placement.left)}px`;
    routeEl.style.top = `${Math.round(placement.top)}px`;
    routeEl.style.width = `${Math.round(placement.width)}px`;
    routeEl.style.height = `${Math.round(placement.height)}px`;
    routeEl.style.setProperty('--route-span-width', `${Math.round(placement.width)}px`);
    routeEl.style.setProperty('--route-span-height', `${Math.round(placement.height)}px`);
    state.debugPropKind = routeKind;
    state.debugPropPhase = safeString(placement.phase || '');
}

function chatRobotWorldPerchTarget(state, platforms = []) {
    const bounds = chatRobotWorldBounds();
    const anchor = sendBtn instanceof HTMLElement
        ? sendBtn.getBoundingClientRect()
        : attachBtn instanceof HTMLElement
            ? attachBtn.getBoundingClientRect()
            : null;
    if (!anchor) {
        const best = platforms.find((platform) => platform.kind !== 'floor');
        if (best) {
            return {
                x: Math.round((best.x1 + best.x2) * 0.5),
                y: best.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
            };
        }
        return { x: Math.round(bounds.width * 0.72), y: bounds.groundY };
    }
    return {
        x: Math.max(22, Math.min(bounds.width - 22, Math.round(anchor.left - bounds.left + (anchor.width * 0.5)))),
        y: Math.round(anchor.top - bounds.top - CHAT_PRIMARY_ROBOT_FOOT_OFFSET - (state?.kind === 'delegation' ? 6 : 0)),
    };
}

function chatRobotWorldTaskFocusTarget(state, graph = null) {
    const bounds = chatRobotWorldBounds();
    const platforms = graph?.platforms || chatRobotWorldPlatforms(bounds);
    const strip = document.querySelector('.message-task-strip:not(.hidden)');
    if (strip instanceof HTMLElement) {
        const rect = strip.getBoundingClientRect();
        const x = chatRobotWorldClamp(Math.round(rect.left - bounds.left + (rect.width * 0.5)), 28, bounds.width - 28);
        const roof = platforms.find((platform) => platform.id === 'composer-roof')
            || platforms.find((platform) => platform.kind === 'ui' || platform.kind === 'suggestion')
            || platforms.find((platform) => platform.kind === 'floor')
            || null;
        if (roof) {
            return {
                x: chatRobotWorldClamp(x, roof.x1 + 10, roof.x2 - 10),
                y: roof.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                platformId: roof.id,
            };
        }
    }
    const perch = chatRobotWorldPerchTarget(state, platforms);
    const platform = platforms.find((item) => (
        perch.x >= (item.x1 - 6)
        && perch.x <= (item.x2 + 6)
        && Math.abs((item.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET) - perch.y) <= 14
    )) || platforms.find((item) => item.kind === 'roof' || item.kind === 'ui') || platforms[0] || null;
    return {
        x: platform ? chatRobotWorldClamp(perch.x, platform.x1 + 8, platform.x2 - 8) : perch.x,
        y: platform ? (platform.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET) : perch.y,
        platformId: safeString(platform?.id),
    };
}

function chatRobotWorldHomeTarget(state, graph = null) {
    const bounds = chatRobotWorldBounds();
    const platforms = graph?.platforms || chatRobotWorldPlatforms(bounds);
    const preferredFloorId = safeString(state?.homeFloorId);
    const floor = platforms.find((platform) => platform.id === preferredFloorId)
        || platforms.find((platform) => platform.kind === 'floor' && Number(state?.homeX || 0) <= ((platform.x1 + platform.x2) * 0.5))
        || platforms.find((platform) => platform.kind === 'floor')
        || null;
    if (!floor) {
        return {
            x: chatRobotWorldClamp(Number(state?.homeX || 48), 24, bounds.width - 24),
            y: bounds.groundY,
            platformId: '',
        };
    }
    const homeX = chatRobotWorldClamp(Number(state?.homeX || floor.x1 + 18), floor.x1 + 8, floor.x2 - 8);
    return {
        x: homeX,
        y: floor.y - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
        platformId: floor.id,
    };
}

function chatRobotWorldStartPortalTransfer(state, target = {}, reason = 'portal') {
    if (!state?.element || !target) return false;
    if (state.portalTransfer) return false;
    state.portalTransfer = {
        reason: safeString(reason || 'portal'),
        startedAt: performance.now(),
        sourceX: Number(state.x || 0),
        sourceY: Number(state.y || 0),
        targetX: Number(target.x || state.x || 0),
        targetY: Number(target.y || state.y || 0),
        targetPlatformId: safeString(target.platformId || state.targetPlatformId || state.currentPlatformId || ''),
        arrivalPortalPlayed: false,
    };
    state.mode = 'inspect';
    state.modeUntil = Date.now() + 2200;
    state.vx = 0;
    state.vy = 0;
    chatRobotWorldPlayPortal(state, 'open');
    return true;
}

function chatRobotWorldAdvancePortalTransfer(state, bounds) {
    const transfer = state?.portalTransfer;
    if (!transfer) return false;
    const elapsed = Math.max(0, performance.now() - Number(transfer.startedAt || 0));
    if (elapsed < 360) {
        state.x = transfer.sourceX;
        state.y = transfer.sourceY;
        state.hiddenTransit = false;
        return true;
    }
    if (elapsed < 740) {
        state.hiddenTransit = true;
        if (!transfer.arrivalPortalPlayed) {
            transfer.arrivalPortalPlayed = true;
            state.x = transfer.targetX;
            state.y = chatRobotWorldClamp(transfer.targetY, 0, Math.max(0, bounds.height - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT));
            if (transfer.targetPlatformId) {
                state.currentPlatformId = transfer.targetPlatformId;
                state.targetPlatformId = transfer.targetPlatformId;
            }
            chatRobotWorldPlayPortal(state, 'open');
        }
        return true;
    }
    state.hiddenTransit = false;
    state.x = transfer.targetX;
    state.y = chatRobotWorldClamp(transfer.targetY, 0, Math.max(0, bounds.height - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT));
    if (transfer.targetPlatformId) {
        state.currentPlatformId = transfer.targetPlatformId;
        state.targetPlatformId = transfer.targetPlatformId;
    }
    state.portalTransfer = null;
    return false;
}

function chatRobotWorldChooseMode(state) {
    const terminal = chatTaskIsTerminal(state?.status);
    if (terminal) return 'idle';
    const fidelity = animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {});
    const roll = Math.random();
    if (chatRobotWorldPrimaryUsesGroundedPhysics(state)) {
        if (fidelity === ANIMATION_FIDELITY_MINIMAL) {
            if (roll < 0.72) return 'idle';
            if (roll < 0.9) return 'sleep';
            if (roll < 0.98) return 'workout';
            return 'roam';
        }
        if (fidelity === ANIMATION_FIDELITY_BALANCED) {
            if (roll < 0.56) return 'idle';
            if (roll < 0.76) return 'sleep';
            if (roll < 0.9) return 'workout';
            return 'roam';
        }
        if (roll < 0.48) return 'idle';
        if (roll < 0.68) return 'sleep';
        if (roll < 0.82) return 'workout';
        return 'roam';
    }
    if (!chatRobotWorldTaskIsLive(state) && safeString(state?.kind) === 'primary') {
        if (fidelity === ANIMATION_FIDELITY_MINIMAL) {
            if (roll < 0.58) return 'idle';
            if (roll < 0.82) return 'sleep';
            if (roll < 0.94) return 'workout';
            return 'inspect';
        }
        if (fidelity === ANIMATION_FIDELITY_BALANCED) {
            if (roll < 0.34) return 'idle';
            if (roll < 0.58) return 'sleep';
            if (roll < 0.76) return 'inspect';
            if (roll < 0.9) return 'workout';
            return 'roam';
        }
        if (roll < 0.26) return 'idle';
        if (roll < 0.48) return 'inspect';
        if (roll < 0.7) return 'sleep';
        if (roll < 0.86) return 'workout';
        return 'roam';
    }
    if (fidelity === ANIMATION_FIDELITY_MINIMAL) {
        if (roll < 0.58) return 'idle';
        if (roll < 0.78) return 'inspect';
        if (roll < 0.9) return 'sleep';
        return 'roam';
    }
    if (fidelity === ANIMATION_FIDELITY_BALANCED) {
        if (roll < 0.26) return 'sleep';
        if (roll < 0.34) return 'workout';
        if (roll < 0.74) return 'idle';
        if (roll < 0.88) return 'roam';
        if (roll < 0.96) return 'inspect';
        return 'idle';
    }
    if (roll < 0.2) return 'sleep';
    if (roll < 0.28) return 'workout';
    if (roll < 0.7) return 'idle';
    if (roll < 0.88) return 'roam';
    if (roll < 0.97) return 'inspect';
    if (roll < 0.99) return 'perch';
    return 'idle';
}

function chatRobotWorldPickTargetPlatform(state, graph, mode, motion) {
    const platforms = graph?.platforms || [];
    const currentPlatform = graph?.platformsById?.get(safeString(state?.currentPlatformId))
        || chatRobotWorldCurrentPlatform(state, platforms);
    const currentCenter = currentPlatform
        ? ((currentPlatform.x1 + currentPlatform.x2) * 0.5)
        : Number(state?.x || 0);
    const desiredDirection = Number(state?.preferredDirection || state?.facing || 1) >= 0 ? 1 : -1;
    const liveTask = chatRobotWorldTaskIsLive(state);
    const groundedPrimaryPhysics = chatRobotWorldPrimaryUsesGroundedPhysics(state);
    let candidates = [];
    if (groundedPrimaryPhysics) {
        candidates = platforms.filter((platform) => platform.kind === 'floor');
    } else if (mode === 'inspect') {
        candidates = platforms.filter((platform) => new Set(['ui', 'roof', 'suggestion']).has(platform.kind));
    } else if (mode === 'perch') {
        candidates = platforms.filter((platform) => new Set(['roof', 'suggestion', 'ui']).has(platform.kind));
    } else if (motion.fidelity === ANIMATION_FIDELITY_MINIMAL) {
        candidates = platforms.filter((platform) => platform.kind === 'floor');
    } else if (motion.fidelity === ANIMATION_FIDELITY_BALANCED) {
        candidates = platforms.filter((platform) => platform.kind === 'floor' || platform.kind === 'roof');
    } else {
        candidates = platforms.filter((platform) => platform.kind === 'floor');
    }
    if (!liveTask && safeString(state?.kind) === 'primary') {
        const bounds = graph?.bounds || chatRobotWorldBounds();
        const zone = safeString(state?.ambientZone) || chatRobotWorldAmbientZoneForX(state?.x, bounds);
        const zoneCandidates = candidates.filter((platform) => {
            const center = chatRobotWorldPlatformCenter(platform);
            return zone === 'right'
                ? center >= (bounds.width * 0.46)
                : center <= (bounds.width * 0.54);
        });
        if (zoneCandidates.length) {
            candidates = zoneCandidates;
        }
        if (currentPlatform?.kind === 'floor' && safeString(mode) !== 'roam') {
            const samePlatform = candidates.filter((platform) => platform.id === currentPlatform.id);
            if (samePlatform.length) {
                candidates = samePlatform;
            }
        }
        if (groundedPrimaryPhysics && currentPlatform?.kind === 'floor' && safeString(mode) !== 'roam') {
            const sameFloor = candidates.filter((platform) => platform.id === currentPlatform.id);
            if (sameFloor.length) {
                candidates = sameFloor;
            }
        }
    }
    if (!candidates.length) candidates = platforms;
    if (!candidates.length) return null;
    const directional = currentPlatform
        ? candidates.filter((platform) => {
            const center = ((platform.x1 + platform.x2) * 0.5);
            const delta = center - currentCenter;
            return desiredDirection > 0 ? delta > 40 : delta < -40;
        })
        : [];
    const sideBiased = currentPlatform
        ? candidates.filter((platform) => (
            Math.sign(((platform.x1 + platform.x2) * 0.5) - ((currentPlatform.x1 + currentPlatform.x2) * 0.5)) === 0
            || Math.abs(((platform.x1 + platform.x2) * 0.5) - ((currentPlatform.x1 + currentPlatform.x2) * 0.5)) > 40
        ))
        : candidates;
    return officePick(directional) || officePick(sideBiased) || officePick(candidates) || candidates[0];
}
