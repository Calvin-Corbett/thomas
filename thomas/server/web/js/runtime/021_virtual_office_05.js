function officeBindControls() {
    if (!officeState || officeState.controlsBound) return;
    officeState.controlsBound = true;

    if (officeEditorToggleBtn) {
        officeEditorToggleBtn.addEventListener('click', () => {
            officeSetEditorOpen(true);
        });
    }
    if (officeEditorDockBtn) {
        officeEditorDockBtn.addEventListener('click', () => {
            officeSetEditorOpen(true);
        });
    }
    if (officeEditorCloseBtn) {
        officeEditorCloseBtn.addEventListener('click', () => {
            officeSetEditorOpen(false);
        });
    }
    if (officeEditorModal) {
        officeEditorModal.addEventListener('pointerdown', (event) => {
            if (!(event.target instanceof Element)) return;
            if (event.target.closest('.office-editor-card')) return;
            officeSetEditorOpen(false);
        });
        officeEditorModal.addEventListener('keydown', (event) => {
            if (event.key !== 'Tab') return;
            const focusables = [...officeEditorModal.querySelectorAll(
                'button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
            )].filter((node) => !node.hasAttribute('disabled') && !node.classList.contains('hidden'));
            if (!focusables.length) return;
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
                return;
            }
            if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
    }
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            officeSetEditorOpen(false);
        }
    });

    if (officeChatSendBtn) {
        officeChatSendBtn.addEventListener('click', officeHandleChatSend);
    }
    if (officeChatInput) {
        officeChatInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                officeHandleChatSend();
            }
        });
    }

    if (officeAgentSelect) {
        officeAgentSelect.addEventListener('change', () => {
            officeState.selectedAgentId = safeString(officeAgentSelect.value);
            officeSyncCustomizerFields();
            if (safeString(officeState.followAgentId)) {
                officeSetFollowMode(true, officeState.selectedAgentId);
            }
        });
    }

    if (officeFollowToggleBtn) {
        officeFollowToggleBtn.addEventListener('click', () => {
            const enable = !safeString(officeState?.followAgentId);
            officeSetFollowMode(enable, officeState?.selectedAgentId || '');
        });
    }

    if (officeMinimapCanvas) {
        const minimapPan = (event) => {
            if (!officeState) return;
            event.preventDefault();
            officePanToMinimapEvent(event);
        };
        const minimapEnd = (event) => {
            if (!officeState?.minimapDrag?.active) return;
            if (event.pointerId !== officeState.minimapDrag.pointerId) return;
            officeState.minimapDrag.active = false;
            officeState.minimapDrag.pointerId = -1;
            if (officeMinimap && officeMinimap.classList) {
                officeMinimap.classList.remove('dragging');
            }
            if (officeMinimapCanvas.hasPointerCapture(event.pointerId)) {
                officeMinimapCanvas.releasePointerCapture(event.pointerId);
            }
        };
        officeMinimapCanvas.addEventListener('pointerdown', (event) => {
            if (!officeState) return;
            if (safeString(officeState.followAgentId)) {
                officeSetFollowMode(false);
            }
            officeState.minimapDrag.active = true;
            officeState.minimapDrag.pointerId = event.pointerId;
            officeMinimapCanvas.setPointerCapture(event.pointerId);
            if (officeMinimap && officeMinimap.classList) {
                officeMinimap.classList.add('dragging');
            }
            minimapPan(event);
        });
        officeMinimapCanvas.addEventListener('pointermove', (event) => {
            if (!officeState?.minimapDrag?.active) return;
            if (event.pointerId !== officeState.minimapDrag.pointerId) return;
            minimapPan(event);
        });
        officeMinimapCanvas.addEventListener('pointerup', minimapEnd);
        officeMinimapCanvas.addEventListener('pointercancel', minimapEnd);
    }

    if (officeAgentNameInput) {
        officeAgentNameInput.addEventListener('input', () => {
            const agent = officeGetAgentById(officeState.selectedAgentId);
            if (!agent) return;
            const proposed = safeString(officeAgentNameInput.value).slice(0, 24);
            if (!proposed) return;
            const normalized = officeAgentHandle(proposed);
            const duplicate = officeState.agents.find((entry) => (
                entry.id !== agent.id && officeAgentHandle(entry.name) === normalized
            ));
            if (duplicate) {
                const suffix = Math.floor(officeRandomRange(2, 99));
                agent.name = `${proposed.slice(0, 20)} ${suffix}`;
            } else {
                agent.name = proposed;
            }
            officeRenderAgentSelector(agent.id);
            officePersistAgentPrefs();
            officeBusEmit('agent.customized', {
                agentId: agent.id,
                field: 'name',
                value: agent.name,
            });
        });
    }

    if (officeAgentColorInput) {
        officeAgentColorInput.addEventListener('input', () => {
            const agent = officeGetAgentById(officeState.selectedAgentId);
            if (!agent) return;
            const color = safeString(officeAgentColorInput.value);
            if (!/^#[0-9a-f]{6}$/i.test(color)) return;
            agent.color = color;
            agent.tint = officeAgentTintFromColor(color);
            officeRenderAgents();
            officePersistAgentPrefs();
            officeBusEmit('agent.customized', {
                agentId: agent.id,
                field: 'color',
                value: color,
            });
        });
    }

    if (officeAgentCostumeSelect) {
        officeAgentCostumeSelect.addEventListener('change', () => {
            const agent = officeGetAgentById(officeState.selectedAgentId);
            if (!agent) return;
            const costume = safeString(officeAgentCostumeSelect.value).toLowerCase();
            if (!['none', 'cap', 'visor', 'headset', 'bowtie'].includes(costume)) return;
            agent.costume = costume;
            officeRenderAgents();
            officePersistAgentPrefs();
            officeBusEmit('agent.customized', {
                agentId: agent.id,
                field: 'costume',
                value: costume,
            });
        });
    }

    if (officeActionSummonBtn) {
        officeActionSummonBtn.addEventListener('click', () => {
            officeRunQuickAction('summon');
        });
    }
    if (officeActionBreakBtn) {
        officeActionBreakBtn.addEventListener('click', () => {
            officeRunQuickAction('break');
        });
    }
    if (officeActionResumeBtn) {
        officeActionResumeBtn.addEventListener('click', () => {
            officeRunQuickAction('resume');
        });
    }

    if (officeZoomOutBtn) {
        officeZoomOutBtn.addEventListener('click', () => {
            const baseZoom = Number.isFinite(officeState?.targetZoomLevel) ? officeState.targetZoomLevel : (officeState?.zoomLevel || 1);
            officeSetZoom(baseZoom - OFFICE_ZOOM_STEP);
        });
    }
    if (officeZoomInBtn) {
        officeZoomInBtn.addEventListener('click', () => {
            const baseZoom = Number.isFinite(officeState?.targetZoomLevel) ? officeState.targetZoomLevel : (officeState?.zoomLevel || 1);
            officeSetZoom(baseZoom + OFFICE_ZOOM_STEP);
        });
    }
    if (officeZoomResetBtn) {
        officeZoomResetBtn.addEventListener('click', () => {
            officeResetViewport();
        });
    }
    if (officeDebugToggleBtn) {
        officeDebugToggleBtn.addEventListener('click', () => {
            if (!officeState) return;
            officeState.debugOverlayOpen = !officeState.debugOverlayOpen;
            officeDebugToggleBtn.classList.toggle('active', officeState.debugOverlayOpen);
            officeDebugToggleBtn.setAttribute('aria-pressed', officeState.debugOverlayOpen ? 'true' : 'false');
            officeRenderDebugOverlay();
        });
    }
    if (officeSceneWrap) {
        officeSceneWrap.addEventListener('pointerdown', (event) => {
            if (!officeState) return;
            if (!(event.target instanceof Element)) return;
            if (event.target.closest('.office-agent-hitbox')) return;
            if (event.target.closest('.office-map-controls')) return;
            if (event.target.closest('.office-minimap')) return;
            if (event.target.closest('.office-editor-card')) return;
            if (safeString(officeState.followAgentId)) {
                officeSetFollowMode(false);
            }

            if (event.pointerType === 'touch') {
                event.preventDefault();
                officeTouchGestureDown(event);
                officeSceneWrap.setPointerCapture(event.pointerId);
                return;
            }
            if (event.button !== 0) return;

            officeState.dragging = {
                active: true,
                pointerId: event.pointerId,
                lastX: event.clientX,
                lastY: event.clientY,
            };
            officeSceneWrap.classList.add('is-panning');
            officeSceneWrap.setPointerCapture(event.pointerId);
        });
        officeSceneWrap.addEventListener('pointermove', (event) => {
            if (event.pointerType === 'touch') {
                const consumed = officeTouchGestureMove(event);
                if (consumed) {
                    event.preventDefault();
                    return;
                }
            }
            if (!officeState?.dragging?.active) return;
            if (event.pointerId !== officeState.dragging.pointerId) return;
            const deltaX = event.clientX - officeState.dragging.lastX;
            const deltaY = event.clientY - officeState.dragging.lastY;
            officeState.dragging.lastX = event.clientX;
            officeState.dragging.lastY = event.clientY;
            officePanBy(deltaX, deltaY);
        });
        const endDrag = (event) => {
            if (event.pointerType === 'touch') {
                officeTouchGestureEnd(event);
                if (officeSceneWrap.hasPointerCapture(event.pointerId)) {
                    officeSceneWrap.releasePointerCapture(event.pointerId);
                }
            }
            if (!officeState?.dragging?.active) return;
            if (event.pointerId !== officeState.dragging.pointerId) return;
            officeState.dragging.active = false;
            officeSceneWrap.classList.remove('is-panning');
            if (officeSceneWrap.hasPointerCapture(event.pointerId)) {
                officeSceneWrap.releasePointerCapture(event.pointerId);
            }
        };
        officeSceneWrap.addEventListener('pointerup', endDrag);
        officeSceneWrap.addEventListener('pointercancel', endDrag);
        officeSceneWrap.addEventListener('wheel', (event) => {
            if (!officeState) return;
            event.preventDefault();
            const deltaUnit = event.deltaMode === 1 ? 14 : (event.deltaMode === 2 ? 120 : 1);
            const normalizedDelta = officeClamp(event.deltaY * deltaUnit, -220, 220);
            const baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
            const factor = Math.exp(-normalizedDelta * OFFICE_WHEEL_ZOOM_SENSITIVITY);
            officeSetZoom(
                baseZoom * factor,
                { anchorClientX: event.clientX, anchorClientY: event.clientY },
            );
        }, { passive: false });
        officeSceneWrap.addEventListener('keydown', (event) => {
            if (!officeState) return;
            const panStep = event.shiftKey ? 88 : 46;
            if (event.key === 'ArrowLeft') {
                event.preventDefault();
                if (safeString(officeState.followAgentId)) officeSetFollowMode(false);
                officePanBy(panStep, 0);
                return;
            }
            if (event.key === 'ArrowRight') {
                event.preventDefault();
                if (safeString(officeState.followAgentId)) officeSetFollowMode(false);
                officePanBy(-panStep, 0);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                if (safeString(officeState.followAgentId)) officeSetFollowMode(false);
                officePanBy(0, panStep);
                return;
            }
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                if (safeString(officeState.followAgentId)) officeSetFollowMode(false);
                officePanBy(0, -panStep);
                return;
            }
            if (event.key === '+' || event.key === '=' || event.key === 'Add') {
                event.preventDefault();
                const baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
                officeSetZoom(baseZoom + OFFICE_ZOOM_STEP);
                return;
            }
            if (event.key === '-' || event.key === '_' || event.key === 'Subtract') {
                event.preventDefault();
                const baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
                officeSetZoom(baseZoom - OFFICE_ZOOM_STEP);
                return;
            }
            if (event.key === '0' || event.key === 'Home') {
                event.preventDefault();
                officeResetViewport();
                return;
            }
            if (event.key === '`' || event.key === 'd' || event.key === 'D') {
                event.preventDefault();
                if (officeDebugToggleBtn) {
                    officeDebugToggleBtn.click();
                }
            }
        });
    }
    officeEnablePanelResizing();
    window.addEventListener('resize', () => {
        if (!officeState) return;
        officeResetViewport({ preserveZoom: true });
    });
    document.addEventListener('visibilitychange', () => {
        if (!officeState) return;
        if (document.hidden) {
            officeState.hiddenAtEpoch = Date.now();
            officePersistRuntimeState(performance.now(), { force: true });
            return;
        }
        officeState.hiddenAtEpoch = 0;
        officeState.lastWallClockTickAt = Date.now();
        officeRenderAgents();
        if (officeState.tasksDirty) {
            officeState.tasksDirty = false;
            officeRenderTaskList();
        }
        officeUpdateRoomMeta();
        officeRenderMinimap();
        officePersistRuntimeState(performance.now(), { force: true });
    });
    window.addEventListener('beforeunload', () => {
        if (!officeState) return;
        officeStopMissionStream();
        officeStopBackgroundTickTimer();
        officePersistCameraState(Number.POSITIVE_INFINITY);
        officePersistLayoutState();
        officePersistAgentPrefs();
        officePersistRuntimeState(performance.now(), { force: true });
    });
}

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

function officeEnsureDraftMapState() {
    if (officeDraftMapState) return officeDraftMapState;
    officeDraftMapState = {
        zoom: OFFICE_DRAFT_MAP_DEFAULT_ZOOM,
        panX: 0,
        panY: 0,
        pointerId: null,
        dragStartX: 0,
        dragStartY: 0,
        dragPanX: 0,
        dragPanY: 0,
        initialized: false,
        hasLiveViewport: false,
        minimapMinimized: false,
        minimapPointerId: null,
        minimapDragStartX: 0,
        minimapDragStartY: 0,
        minimapOffsetX: 0,
        minimapOffsetY: 0,
        minimapDragOffsetX: 0,
        minimapDragOffsetY: 0,
        minimapSize: OFFICE_DRAFT_MINIMAP_SIZE,
        minimapResizePointerId: null,
        minimapResizeStartX: 0,
        minimapResizeStartY: 0,
        minimapResizeStartSize: OFFICE_DRAFT_MINIMAP_SIZE,
        autosaveEnabled: officeDraftLoadAutosavePreference(),
        editorOpen: false,
        selectedSpaceId: 'lounge',
        selectedAssetId: null,
        assetPointerId: null,
        assetDragSpaceId: '',
        assetDragId: '',
        assetDragOffsetX: 0,
        assetDragOffsetY: 0,
        assetDragSnapshot: null,
        catalogPointerId: null,
        catalogPendingType: '',
        catalogPreviewSpaceId: '',
        catalogPreviewX: 0,
        catalogPreviewY: 0,
        rotationStep: 15,
        gridEnabled: true,
        nextAssetId: 3,
        undoStack: [],
        spaces: [
            {
                id: 'lounge',
                name: 'Lounge',
                x: (OFFICE_DRAFT_MAP_SIZE / 2) - 1120,
                y: (OFFICE_DRAFT_MAP_SIZE / 2) - 760,
                width: 2240,
                height: 1520,
                floorPalette: 'tan',
                robotX: 520,
                robotY: 800,
                assets: [
                    { id: 'couch-1', type: 'couch', x: 980, y: 824, rotation: 0, colorVariant: 'caramel', scale: 1 },
                    { id: 'couch-2', type: 'couch', x: 1330, y: 824, rotation: 0, colorVariant: 'caramel', scale: 1 },
                ],
            },
        ],
    };
    officeDraftApplySnapshot(officeDraftLoadStoredLayout(), officeDraftMapState, { persist: false, resetUndo: true });
    return officeDraftMapState;
}

function officeDraftMapViewportRect() {
    if (!officeSceneWrap) {
        return { width: 1280, height: 720 };
    }
    const rect = officeSceneWrap.getBoundingClientRect();
    return {
        width: Math.max(320, rect.width || officeSceneWrap.clientWidth || 1280),
        height: Math.max(240, rect.height || officeSceneWrap.clientHeight || 720),
    };
}

function officeClampDraftMapPan(panXRaw, panYRaw, zoomRaw) {
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, Number(zoomRaw) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM));
    const viewport = officeDraftMapViewportRect();
    const viewportWorldWidth = viewport.width / zoom;
    const viewportWorldHeight = viewport.height / zoom;
    const freeWorldX = Math.max(0, viewportWorldWidth - OFFICE_DRAFT_MAP_SIZE);
    const freeWorldY = Math.max(0, viewportWorldHeight - OFFICE_DRAFT_MAP_SIZE);
    const padX = Math.max(2400, viewportWorldWidth * 0.35, (freeWorldX / 2) + 1800);
    const padY = Math.max(2400, viewportWorldHeight * 0.35, (freeWorldY / 2) + 1800);
    const minPanX = -padX;
    const minPanY = -padY;
    const maxPanX = (OFFICE_DRAFT_MAP_SIZE - viewportWorldWidth) + padX;
    const maxPanY = (OFFICE_DRAFT_MAP_SIZE - viewportWorldHeight) + padY;
    return {
        panX: Math.min(Math.max(minPanX, Number(panXRaw) || 0), maxPanX),
        panY: Math.min(Math.max(minPanY, Number(panYRaw) || 0), maxPanY),
    };
}

function officeCenterDraftMapViewport() {
    const state = officeEnsureDraftMapState();
    const viewport = officeDraftMapViewportRect();
    state.panX = Math.max(0, (OFFICE_DRAFT_MAP_SIZE / 2) - (viewport.width / (2 * state.zoom)));
    state.panY = Math.max(0, (OFFICE_DRAFT_MAP_SIZE / 2) - (viewport.height / (2 * state.zoom)));
}

function officeDraftMapViewportWorldRect() {
    const state = officeEnsureDraftMapState();
    const viewport = officeDraftMapViewportRect();
    return {
        x: state.panX,
        y: state.panY,
        width: viewport.width / state.zoom,
        height: viewport.height / state.zoom,
    };
}

function officeDraftRoomPalette(paletteId) {
    return OFFICE_DRAFT_ROOM_FLOOR_PALETTES[safeString(paletteId)] || OFFICE_DRAFT_ROOM_FLOOR_PALETTES.tan;
}

function officeDraftSelectedSpace() {
    const state = officeEnsureDraftMapState();
    return state.spaces.find((space) => safeString(space?.id) === safeString(state.selectedSpaceId)) || state.spaces[0] || null;
}

function officeDraftFindSpace(spaceId) {
    const state = officeEnsureDraftMapState();
    return state.spaces.find((space) => safeString(space?.id) === safeString(spaceId)) || null;
}

function officeDraftFindAsset(assetId) {
    const state = officeEnsureDraftMapState();
    for (const space of state.spaces) {
        const asset = Array.isArray(space?.assets) ? space.assets.find((item) => safeString(item?.id) === safeString(assetId)) : null;
        if (asset) {
            return { space, asset };
        }
    }
    return null;
}

function officeDraftSpaceAtWorldPoint(worldX, worldY) {
    const state = officeEnsureDraftMapState();
    return state.spaces.find((space) => (
        Number(worldX) >= Number(space?.x)
        && Number(worldX) <= Number(space?.x) + Number(space?.width)
        && Number(worldY) >= Number(space?.y)
        && Number(worldY) <= Number(space?.y) + Number(space?.height)
    )) || null;
}

function officeDraftRotationOptions() {
    return [15, 30, 45];
}

function officeDraftNormalizeRotation(value) {
    const normalized = Number(value) || 0;
    const wrapped = ((normalized % 360) + 360) % 360;
    return Math.round(wrapped);
}

function officeDraftSnap(value, gridSize, enabled = true) {
    if (!enabled) return Math.round(Number(value) || 0);
    const size = Math.max(1, Number(gridSize) || 1);
    return Math.round((Number(value) || 0) / size) * size;
}

function officeDraftCloneLayoutPayload(payload) {
    try {
        return JSON.parse(JSON.stringify(payload));
    } catch {
        return null;
    }
}

function officeDraftClampAssetScale(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 1;
    return Math.min(OFFICE_DRAFT_ASSET_SCALE_MAX, Math.max(OFFICE_DRAFT_ASSET_SCALE_MIN, Math.round(numeric * 20) / 20));
}

function officeDraftAssetDimensions(assetType, scaleRaw = 1) {
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[safeString(assetType)] || OFFICE_DRAFT_ASSET_LIBRARY.couch;
    const scale = officeDraftClampAssetScale(scaleRaw);
    return {
        width: Math.round(descriptor.width * scale),
        height: Math.round(descriptor.height * scale),
        scale,
    };
}

function officeDraftAssetColorway(assetType, colorId) {
    const colorways = OFFICE_DRAFT_ASSET_COLORWAYS[safeString(assetType)] || OFFICE_DRAFT_ASSET_COLORWAYS.couch;
    return colorways[safeString(colorId)] || colorways.caramel;
}

function officeDraftLayoutSnapshot(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    return {
        selectedSpaceId: safeString(state.selectedSpaceId),
        selectedAssetId: safeString(state.selectedAssetId),
        rotationStep: officeDraftRotationOptions().includes(Number(state.rotationStep)) ? Number(state.rotationStep) : 15,
        gridEnabled: state.gridEnabled !== false,
        nextAssetId: Math.max(1, Number(state.nextAssetId) || 1),
        spaces: (Array.isArray(state.spaces) ? state.spaces : []).map((space) => ({
            id: safeString(space?.id),
            name: safeString(space?.name) || 'Space',
            x: Math.round(Number(space?.x) || 0),
            y: Math.round(Number(space?.y) || 0),
            width: Math.max(320, Math.round(Number(space?.width) || 0)),
            height: Math.max(240, Math.round(Number(space?.height) || 0)),
            floorPalette: safeString(space?.floorPalette) || 'tan',
            robotX: Math.round(Number(space?.robotX) || 0),
            robotY: Math.round(Number(space?.robotY) || 0),
            assets: (Array.isArray(space?.assets) ? space.assets : []).map((asset) => ({
                id: safeString(asset?.id),
                type: safeString(asset?.type) || 'couch',
                x: Math.round(Number(asset?.x) || 0),
                y: Math.round(Number(asset?.y) || 0),
                rotation: officeDraftNormalizeRotation(asset?.rotation),
                colorVariant: safeString(asset?.colorVariant) || 'caramel',
                scale: officeDraftClampAssetScale(asset?.scale),
            })),
        })),
    };
}

function officeDraftLoadStoredLayout() {
    try {
        if (!window?.localStorage) return null;
        const raw = window.localStorage.getItem(OFFICE_DRAFT_LAYOUT_STORAGE_KEY);
        if (!raw) return null;
        return officeDraftCloneLayoutPayload(JSON.parse(raw));
    } catch {
        return null;
    }
}

function officeDraftLoadAutosavePreference() {
    try {
        if (!window?.localStorage) return true;
        return window.localStorage.getItem(OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY) !== '0';
    } catch {
        return true;
    }
}

function officeDraftSetAutosavePreference(enabledRaw, stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    const enabled = enabledRaw !== false;
    state.autosaveEnabled = enabled;
    try {
        if (window?.localStorage) {
            window.localStorage.setItem(OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY, enabled ? '1' : '0');
        }
    } catch {
        // Ignore preference storage failures.
    }
    if (enabled) {
        officeDraftPersistLayout(state, { force: true });
    }
}

function officeDraftPersistLayout(stateRaw = officeEnsureDraftMapState(), options = {}) {
    const state = stateRaw || officeEnsureDraftMapState();
    if (options.force !== true && state.autosaveEnabled === false) return;
    try {
        if (!window?.localStorage) return;
        const snapshot = officeDraftLayoutSnapshot(state);
        window.localStorage.setItem(OFFICE_DRAFT_LAYOUT_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
        // Ignore storage failures so the editor stays usable.
    }
}

function officeDraftManualSaveLayout(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    officeDraftPersistLayout(state, { force: true });
    officeRenderDraftMapScene();
}

function officeDraftApplySnapshot(snapshotRaw, stateRaw = officeEnsureDraftMapState(), options = {}) {
    const state = stateRaw || officeEnsureDraftMapState();
    if (!snapshotRaw || !Array.isArray(snapshotRaw.spaces) || !snapshotRaw.spaces.length) return false;
    const normalizedSpaces = snapshotRaw.spaces.map((space, spaceIndex) => ({
        id: safeString(space?.id) || `space-${spaceIndex + 1}`,
        name: safeString(space?.name) || 'Space',
        x: Math.round(Number(space?.x) || 0),
        y: Math.round(Number(space?.y) || 0),
        width: Math.max(320, Math.round(Number(space?.width) || 0)),
        height: Math.max(240, Math.round(Number(space?.height) || 0)),
        floorPalette: OFFICE_DRAFT_ROOM_FLOOR_PALETTES[safeString(space?.floorPalette)] ? safeString(space.floorPalette) : 'tan',
        robotX: Math.round(Number(space?.robotX) || 0),
        robotY: Math.round(Number(space?.robotY) || 0),
        assets: (Array.isArray(space?.assets) ? space.assets : []).map((asset, assetIndex) => ({
            id: safeString(asset?.id) || `asset-${spaceIndex + 1}-${assetIndex + 1}`,
            type: OFFICE_DRAFT_ASSET_LIBRARY[safeString(asset?.type)] ? safeString(asset.type) : 'couch',
            x: Math.round(Number(asset?.x) || 0),
            y: Math.round(Number(asset?.y) || 0),
            rotation: officeDraftNormalizeRotation(asset?.rotation),
            colorVariant: safeString(asset?.colorVariant) || 'caramel',
            scale: officeDraftClampAssetScale(asset?.scale),
        })),
    }));
    state.spaces = normalizedSpaces;
    state.nextAssetId = Math.max(1, Number(snapshotRaw.nextAssetId) || 1);
    state.rotationStep = officeDraftRotationOptions().includes(Number(snapshotRaw.rotationStep)) ? Number(snapshotRaw.rotationStep) : 15;
    state.gridEnabled = snapshotRaw.gridEnabled !== false;
    state.selectedSpaceId = normalizedSpaces.some((space) => safeString(space.id) === safeString(snapshotRaw.selectedSpaceId))
        ? safeString(snapshotRaw.selectedSpaceId)
        : safeString(normalizedSpaces[0]?.id);
    const assetExists = normalizedSpaces.some((space) => Array.isArray(space.assets) && space.assets.some((asset) => safeString(asset.id) === safeString(snapshotRaw.selectedAssetId)));
    state.selectedAssetId = assetExists ? safeString(snapshotRaw.selectedAssetId) : null;
    state.catalogPointerId = null;
    state.catalogPendingType = '';
    state.catalogPreviewSpaceId = '';
    state.catalogPreviewX = 0;
    state.catalogPreviewY = 0;
    state.assetPointerId = null;
    state.assetDragSpaceId = '';
    state.assetDragId = '';
    state.assetDragOffsetX = 0;
    state.assetDragOffsetY = 0;
    state.assetDragSnapshot = null;
    if (options.resetUndo) {
        state.undoStack = [];
    }
    if (options.persist !== false) {
        officeDraftPersistLayout(state);
    }
    return true;
}

function officeDraftCommitLayoutChange(previousSnapshot, stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    if (!previousSnapshot) {
        officeDraftPersistLayout(state);
        return false;
    }
    const before = JSON.stringify(previousSnapshot);
    const afterSnapshot = officeDraftLayoutSnapshot(state);
    const after = JSON.stringify(afterSnapshot);
    if (before === after) {
        officeDraftPersistLayout(state);
        return false;
    }
    if (!Array.isArray(state.undoStack)) {
        state.undoStack = [];
    }
    const lastSnapshot = state.undoStack[state.undoStack.length - 1] || null;
    if (!lastSnapshot || JSON.stringify(lastSnapshot) !== before) {
        state.undoStack.push(officeDraftCloneLayoutPayload(previousSnapshot));
        if (state.undoStack.length > OFFICE_DRAFT_UNDO_LIMIT) {
            state.undoStack.splice(0, state.undoStack.length - OFFICE_DRAFT_UNDO_LIMIT);
        }
    }
    officeDraftPersistLayout(state);
    return true;
}

function officeDraftUndoLastChange(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    if (!Array.isArray(state.undoStack) || !state.undoStack.length) return;
    const snapshot = state.undoStack.pop();
    if (!snapshot) return;
    officeDraftApplySnapshot(snapshot, state, { persist: true, resetUndo: false });
    officeRenderDraftMapScene();
}

function officeDraftPlaceAssetInSpace(space, assetType, worldX, worldY, options = {}) {
    if (!space || !OFFICE_DRAFT_ASSET_LIBRARY[safeString(assetType)]) return null;
    const dimensions = officeDraftAssetDimensions(assetType, options.scale || 1);
    const snapEnabled = options.gridEnabled !== false;
    const rotation = officeDraftNormalizeRotation(options.rotation || 0);
    const x = Math.max(24, Math.min(
        Number(space.width) - dimensions.width - 24,
        officeDraftSnap(Number(worldX) - Number(space.x) - (dimensions.width / 2), OFFICE_DRAFT_MAP_MINOR_GRID, snapEnabled),
    ));
    const y = Math.max(24, Math.min(
        Number(space.height) - dimensions.height - 24,
        officeDraftSnap(Number(worldY) - Number(space.y) - (dimensions.height / 2), OFFICE_DRAFT_MAP_MINOR_GRID, snapEnabled),
    ));
    return { x, y, rotation, scale: dimensions.scale };
}

function officeDraftMapClientToWorld(clientX, clientY) {
    const state = officeEnsureDraftMapState();
    const rect = officeSceneWrap?.getBoundingClientRect();
    const viewport = officeDraftMapViewportRect();
    const localX = rect ? clientX - rect.left : viewport.width / 2;
    const localY = rect ? clientY - rect.top : viewport.height / 2;
    return {
        x: state.panX + (localX / state.zoom),
        y: state.panY + (localY / state.zoom),
    };
}

function officeDraftCreateCouchElement(space, asset, state) {
    const descriptor = officeDraftAssetDimensions('couch', asset?.scale);
    const couchColor = officeDraftAssetColorway('couch', asset?.colorVariant);
    const scale = descriptor.scale;
    const scaled = (value) => `${Math.round(Number(value) * scale)}px`;
    const couch = document.createElement('div');
    const isSelected = state.editorOpen && safeString(asset?.id) === safeString(state.selectedAssetId);
    const rotation = officeDraftNormalizeRotation(asset?.rotation);
    const isPreview = Boolean(asset?.preview);
    couch.dataset.officeDraftAssetId = safeString(asset?.id);
    couch.dataset.officeDraftSpaceId = safeString(space?.id);
    couch.style.position = 'absolute';
    couch.style.left = `${Math.round(Number(asset?.x) || 0)}px`;
    couch.style.top = `${Math.round(Number(asset?.y) || 0)}px`;
    couch.style.width = `${descriptor.width}px`;
    couch.style.height = `${descriptor.height}px`;
    couch.style.pointerEvents = isPreview ? 'none' : (state.editorOpen ? 'auto' : 'none');
    couch.style.cursor = isPreview ? 'copy' : (state.editorOpen ? (isSelected && state.assetPointerId !== null ? 'grabbing' : 'grab') : 'default');
    couch.style.filter = isPreview ? 'opacity(0.72) drop-shadow(0 0 0.55rem rgba(111, 169, 255, 0.38))' : (isSelected ? 'drop-shadow(0 0 0.65rem rgba(111, 169, 255, 0.45))' : 'none');
    couch.style.outline = isPreview ? '2px dashed rgba(132, 187, 255, 0.6)' : (isSelected ? '2px solid rgba(132, 187, 255, 0.75)' : 'none');
    couch.style.outlineOffset = scaled(4);
    couch.style.borderRadius = scaled(22);
    couch.style.transform = `rotate(${rotation}deg)`;
    couch.style.transformOrigin = 'center center';

    const couchShadow = document.createElement('div');
    couchShadow.style.position = 'absolute';
    couchShadow.style.left = scaled(18);
    couchShadow.style.top = scaled(142);
    couchShadow.style.width = scaled(300);
    couchShadow.style.height = scaled(36);
    couchShadow.style.borderRadius = '999px';
    couchShadow.style.background = 'rgba(3, 8, 16, 0.34)';
    couchShadow.style.filter = `blur(${Math.max(6, Math.round(12 * scale))}px)`;
    couch.appendChild(couchShadow);

    const couchBack = document.createElement('div');
    couchBack.style.position = 'absolute';
    couchBack.style.left = scaled(30);
    couchBack.style.top = scaled(12);
    couchBack.style.width = scaled(276);
    couchBack.style.height = scaled(88);
    couchBack.style.borderRadius = `${scaled(24)} ${scaled(24)} ${scaled(18)} ${scaled(18)}`;
    couchBack.style.background = couchColor.back;
    couchBack.style.boxShadow = 'inset 0 8px 12px rgba(255, 240, 224, 0.18), inset 0 -8px 12px rgba(79, 40, 17, 0.18)';
    couch.appendChild(couchBack);

    const couchSeat = document.createElement('div');
    couchSeat.style.position = 'absolute';
    couchSeat.style.left = scaled(18);
    couchSeat.style.top = scaled(72);
    couchSeat.style.width = scaled(300);
    couchSeat.style.height = scaled(74);
    couchSeat.style.borderRadius = scaled(22);
    couchSeat.style.background = couchColor.seat;
    couchSeat.style.boxShadow = 'inset 0 8px 10px rgba(255, 239, 219, 0.18), inset 0 -10px 14px rgba(105, 58, 28, 0.2)';
    couch.appendChild(couchSeat);

    const couchArmLeft = document.createElement('div');
    couchArmLeft.style.position = 'absolute';
    couchArmLeft.style.left = '0';
    couchArmLeft.style.top = scaled(54);
    couchArmLeft.style.width = scaled(58);
    couchArmLeft.style.height = scaled(84);
    couchArmLeft.style.borderRadius = scaled(20);
    couchArmLeft.style.background = couchColor.arm;
    couchArmLeft.style.boxShadow = 'inset 0 6px 9px rgba(255, 229, 209, 0.12)';
    couch.appendChild(couchArmLeft);

    const couchArmRight = document.createElement('div');
    couchArmRight.style.position = 'absolute';
    couchArmRight.style.right = '0';
    couchArmRight.style.top = scaled(54);
    couchArmRight.style.width = scaled(58);
    couchArmRight.style.height = scaled(84);
    couchArmRight.style.borderRadius = scaled(20);
    couchArmRight.style.background = couchColor.arm;
    couchArmRight.style.boxShadow = 'inset 0 6px 9px rgba(255, 229, 209, 0.12)';
    couch.appendChild(couchArmRight);

    const couchSeamLeft = document.createElement('div');
    couchSeamLeft.style.position = 'absolute';
    couchSeamLeft.style.left = scaled(122);
    couchSeamLeft.style.top = scaled(82);
    couchSeamLeft.style.width = scaled(2);
    couchSeamLeft.style.height = scaled(48);
    couchSeamLeft.style.background = couchColor.seam;
    couch.appendChild(couchSeamLeft);

    const couchSeamRight = document.createElement('div');
    couchSeamRight.style.position = 'absolute';
    couchSeamRight.style.left = scaled(214);
    couchSeamRight.style.top = scaled(82);
    couchSeamRight.style.width = scaled(2);
    couchSeamRight.style.height = scaled(48);
    couchSeamRight.style.background = couchColor.seam;
    couch.appendChild(couchSeamRight);

    return couch;
}

