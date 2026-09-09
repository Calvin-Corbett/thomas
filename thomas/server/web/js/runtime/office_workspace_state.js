/** Virtual-office state initialization and workspace startup. */

function officeEnsureState() {
    if (officeState) {
        return true;
    }
    if (!officeScene || !officeWorkspace) {
        return false;
    }

    const now = performance.now();
    const storedLayout = loadStoredOfficeLayoutState();
    const storedRuntime = loadStoredOfficeRuntimeState();
    const dynamicRoomBySlug = new Map();
    let dynamicIndex = 0;
    const rooms = OFFICE_STATIC_ROOMS.map((room) => ({ ...room, dynamic: false }));
    if (Array.isArray(storedLayout?.dynamicRooms)) {
        storedLayout.dynamicRooms.forEach((roomRaw, idx) => {
            const room = officeSanitizeDynamicRoomSnapshot(roomRaw, idx);
            if (!room) return;
            rooms.push(room);
            const idMatch = safeString(room.id).match(/^room-dynamic-(\d+)$/i);
            const numericIndex = Number(idMatch?.[1]);
            if (Number.isFinite(numericIndex) && numericIndex > dynamicIndex) {
                dynamicIndex = numericIndex;
            }
        });
    }
    if (storedLayout?.dynamicRoomBySlug && typeof storedLayout.dynamicRoomBySlug === 'object') {
        Object.entries(storedLayout.dynamicRoomBySlug).forEach(([slug, roomId]) => {
            const key = safeString(slug);
            const id = safeString(roomId);
            if (!key || !id) return;
            if (!rooms.some((room) => room.id === id)) return;
            dynamicRoomBySlug.set(key, id);
        });
    }
    const roomById = new Map();
    rooms.forEach((room) => {
        roomById.set(room.id, room);
    });
    const { navMap, roomNav } = officeBuildNavGraph(rooms);
    const lobbyCenterId = roomNav.get('room-lobby')?.centerNodeId || '';
    const lobbyCenter = lobbyCenterId ? navMap.get(lobbyCenterId) : null;
    const spawnRoomSequence = [
        'room-engineering',
        'room-content',
        'room-research',
        'room-ops',
        'room-planning',
        'room-support',
        'room-design',
        'room-pods',
        'room-break',
        'room-coffee',
        'room-lobby',
    ].filter((roomId) => roomById.has(roomId));

    const pickSpawnNodeForAgent = (seed, index) => {
        const preferredRoomId = spawnRoomSequence[index % Math.max(1, spawnRoomSequence.length)] || 'room-lobby';
        const nav = roomNav.get(preferredRoomId);
        const slotNodeIds = Array.isArray(nav?.slotNodeIds) ? nav.slotNodeIds : [];
        if (slotNodeIds.length) {
            const slotIndex = officeStableHash(`${safeString(seed?.name)}|${index}`) % slotNodeIds.length;
            const nodeId = slotNodeIds[slotIndex];
            const node = navMap.get(nodeId);
            if (node) return node;
        }
        const centerNode = navMap.get(nav?.centerNodeId || '');
        if (centerNode) return centerNode;
        return lobbyCenter || null;
    };

    const agents = OFFICE_AGENT_SEEDS.map((seed, index) => {
        const spawnNode = pickSpawnNodeForAgent(seed, index);
        return ({
        id: `agent-${index + 1}`,
        name: seed.name,
        color: seed.color,
        costume: seed.costume,
        tint: seed.tint || 'blue',
        specialty: safeString(seed.specialty) || 'Generalist',
        personality: safeString(seed.personality) || 'Helpful, direct, and persistent.',
        source: 'seed',
        remoteIds: {},
        x: spawnNode ? officeClamp(spawnNode.x + officeRandomRange(-0.18, 0.18), 3, 97) : officeRandomRange(35, 92),
        y: spawnNode ? officeClamp(spawnNode.y + officeRandomRange(-0.18, 0.18), 5, 96) : officeRandomRange(64, 90),
        targetX: 0,
        targetY: 0,
        speed: officeRandomRange(2.35, 3.75),
        facing: officeChance(0.5) ? 1 : -1,
        laneBias: officeRandomRange(-0.65, 0.65),
        state: 'idle',
        intent: 'wander',
        taskId: '',
        workStreak: 0,
        workUntil: 0,
        breakUntil: 0,
        idleUntil: now + (index * 180) + officeRandomRange(450, 1700),
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
        lastMoveX: 0,
        lastMoveY: 0,
        returnAfterRunAt: 0,
        runawayPhase: '',
        runawayExitX: 0,
        runawayExitY: 0,
        currentNodeId: '',
        routeWaypoints: [],
        routeDestinationNodeId: '',
        reservedLaneEdgeKey: '',
    });
    });
    const storedAgentPrefs = loadStoredOfficeAgentPrefs();
    officeApplyDefaultAgentStyleDiversification(agents, storedAgentPrefs);
    officeApplyStoredAgentPrefs(agents, storedAgentPrefs);
    agents.forEach((agent) => {
        agent.targetX = agent.x;
        agent.targetY = agent.y;
        agent.lastMoveX = agent.x;
        agent.lastMoveY = agent.y;
        agent.currentNodeId = officeFindNearestNode(navMap, agent.x, agent.y);
    });
    const initialMap = officeMapDimensionsForRoomCount(rooms.length);
    const storedCamera = loadStoredOfficeCameraState();
    const storedZoom = Number.isFinite(storedCamera?.zoom) ? officeClamp(storedCamera.zoom, OFFICE_ZOOM_MIN, OFFICE_ZOOM_MAX) : 0.9;

    officeState = {
        rooms,
        roomById,
        navMap,
        roomNav,
        corridors: [...OFFICE_CORRIDORS],
        dynamicRoomBySlug,
        dynamicIndex,
        agents,
        tasks: [],
        taskCounter: 0,
        chatLines: [],
        officeEvents: [],
        officeBusListeners: new Set(),
        selectedAgentId: agents[0]?.id || '',
        controlsBound: false,
        roomLayerEl: null,
        agentLayerEl: null,
        agentElements: new Map(),
        tasksDirty: true,
        lastRoomMetaSyncAt: 0,
        lastCameraPersistAt: 0,
        lastCameraPersistSignature: '',
        lastRuntimePersistAt: 0,
        lastWallClockTickAt: Date.now(),
        hiddenAtEpoch: 0,
        lastCollisionCooldownPurgeAt: 0,
        nextGlobalSpeechAt: 0,
        collisionSpeechCooldownUntil: 0,
        collisionPairCooldowns: new Map(),
        laneReservations: new Map(),
        lastSocialTickAt: 0,
        nextSocialWindowAt: now + officeRandomRange(1800, 4000),
        debugOverlayOpen: false,
        lastDebugRenderAt: 0,
        debugFrameRate: 0,
        followAgentId: safeString(storedCamera?.followAgentId),
        rafId: 0,
        lastFrameAt: 0,
        active: false,
        backgroundTickTimerId: 0,
        mapWidth: initialMap.width,
        mapHeight: initialMap.height,
        zoomLevel: storedZoom,
        targetZoomLevel: storedZoom,
        panX: Number(storedCamera?.panX) || 0,
        panY: Number(storedCamera?.panY) || 0,
        targetPanX: Number(storedCamera?.panX) || 0,
        targetPanY: Number(storedCamera?.panY) || 0,
        dragging: {
            active: false,
            pointerId: -1,
            lastX: 0,
            lastY: 0,
        },
        minimapDrag: {
            active: false,
            pointerId: -1,
        },
        touchGesture: {
            pointerById: new Map(),
            active: false,
            baseDistance: 0,
            baseZoom: 1,
            lastCenterX: 0,
            lastCenterY: 0,
        },
        stream: {
            connected: false,
            connecting: false,
            retryMs: OFFICE_STREAM_RETRY_MIN_MS,
            reconnectTimer: 0,
            controller: null,
            lastSeq: 0,
            lastMessageAt: 0,
        },
    };

    officeApplyRuntimeSnapshot(storedRuntime, now);

    officeRenderScene();
    officeRenderTaskList();
    officeRenderAgentSelector();
    officeBindControls();
    officeResetViewport();
    if (storedCamera) {
        officeState.zoomLevel = storedZoom;
        officeState.targetZoomLevel = storedZoom;
        const clampedPan = officeClampPan(
            Number(storedCamera.panX) || 0,
            Number(storedCamera.panY) || 0,
            storedZoom,
        );
        officeState.panX = clampedPan.panX;
        officeState.panY = clampedPan.panY;
        officeState.targetPanX = clampedPan.panX;
        officeState.targetPanY = clampedPan.panY;
        officeApplyZoom();
    }
    if (safeString(storedCamera?.followAgentId)) {
        officeSetFollowMode(true, storedCamera.followAgentId);
    }
    officeUpdateFollowUi();
    officeSetEditorOpen(false);
    officePushChatLine(officePick(OFFICE_DIALOGUE.startup));
    officePersistCameraState();
    officePersistLayoutState();
    officePersistAgentPrefs();
    officePersistRuntimeState(now, { force: true });
    officeBusEmit('office.booted', {
        rooms: officeState.rooms.length,
        dynamicRooms: officeState.rooms.filter((room) => room.dynamic).length,
        agents: officeState.agents.length,
    });
    officeStartLoop();
    return true;
}

function officeSyncReducedMotionPreference() {
    if (!officeWorkspace) return;
    const prefersReduced = Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    const prefersHighContrast = Boolean(window.matchMedia && window.matchMedia('(prefers-contrast: more)').matches);
    officeWorkspace.classList.toggle('reduced-motion', prefersReduced);
    officeWorkspace.classList.toggle('high-contrast', prefersHighContrast);
}

function initOfficeWorkspace() {
    if (!officeScene || !officeWorkspace) return;
    if (typeof officeHydrateServerState === 'function') void officeHydrateServerState();
    if (!officeEnsureState()) return;
    officeState.active = !officeWorkspace.classList.contains('hidden') || officeWorkspace.classList.contains('chat-preview-active');
    if (officeState.active) {
        officeStartLoop();
        void officeStartMissionStream();
    }
    officeEnsureDraftMapState();
    officePrepareDraftMapShell();
    officeRenderDraftMapScene();
    officeBindDraftMapControls();
    officeSyncReducedMotionPreference();
    if (!officeReducedMotionListenerBound && window.matchMedia) {
        officeReducedMotionListenerBound = true;
        const handler = () => officeSyncReducedMotionPreference();
        const queryList = [
            window.matchMedia('(prefers-reduced-motion: reduce)'),
            window.matchMedia('(prefers-contrast: more)'),
        ];
        queryList.forEach((query) => {
            if (!query) return;
            if (typeof query.addEventListener === 'function') {
                query.addEventListener('change', handler);
            } else if (typeof query.addListener === 'function') {
                query.addListener(handler);
            }
        });
    }
}


