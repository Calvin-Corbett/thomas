function officeDraftMapInputActive() {
    return typeof officeDraftMapPlane === 'function' && Boolean(officeDraftMapPlane());
}

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
            if (officeDraftMapInputActive()) return;
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
            if (officeDraftMapInputActive()) return;
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
            if (!OFFICE_AGENT_COSTUME_POOL.includes(costume)) return;
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
            if (officeDraftMapInputActive()) return;
            if (!(event.target instanceof Element)) return;
            if (event.target.closest('.office-agent-hitbox')) return;
            if (event.target.closest('.office-map-controls')) return;
            if (event.target.closest('.office-minimap')) return;
            if (event.target.closest('.office-editor-card')) return;
            if (event.target.closest('[data-office-map-toolbar="1"]')) return;
            if (event.target.closest('[data-office-editor-panel="1"]')) return;
            if (event.target.closest('[data-office-agent-roster-panel="1"]')) return;
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
            if (officeDraftMapInputActive()) return;
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
            if (officeDraftMapInputActive()) return;
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
            if (officeDraftMapInputActive()) return;
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
            if (officeDraftMapInputActive()) return;
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

const OFFICE_DRAFT_DEFAULT_LAYOUT_OFFSET_SCALE = 0.74;
const OFFICE_DRAFT_DEFAULT_ROOM_SCALE_BY_ID = Object.freeze({
    'planning-hub': { scaleX: 0.66, scaleY: 0.64, minWidth: 900, minHeight: 680, offsetScale: 0.68 },
    'software-lab': { scaleX: 0.64, scaleY: 0.62, minWidth: 1180, minHeight: 780, offsetScale: 0.7 },
    'research-bay': { scaleX: 0.61, scaleY: 0.6, minWidth: 860, minHeight: 650, offsetScale: 0.66 },
    'design-loft': { scaleX: 0.6, scaleY: 0.61, minWidth: 800, minHeight: 660, offsetScale: 0.66 },
    'content-studio': { scaleX: 0.62, scaleY: 0.6, minWidth: 860, minHeight: 680, offsetScale: 0.68 },
    'ops-command': { scaleX: 0.62, scaleY: 0.6, minWidth: 900, minHeight: 700, offsetScale: 0.68 },
    'support-desk': { scaleX: 0.6, scaleY: 0.6, minWidth: 900, minHeight: 680, offsetScale: 0.64 },
    cafeteria: { scaleX: 0.62, scaleY: 0.58, minWidth: 1040, minHeight: 760, offsetScale: 0.7 },
    lounge: { scaleX: 0.6, scaleY: 0.58, minWidth: 960, minHeight: 690, offsetScale: 0.68 },
    'focus-pods': { scaleX: 0.58, scaleY: 0.58, minWidth: 820, minHeight: 660, offsetScale: 0.66 },
    lobby: { scaleX: 0.58, scaleY: 0.58, minWidth: 840, minHeight: 560, offsetScale: 0.76 },
});

function officeDraftCompactDefaultAsset(asset, scaleX, scaleY, roomWidth, roomHeight) {
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const margin = 48;
    const maxX = Math.max(margin, Number(roomWidth) - Number(dimensions.width || 0) - margin);
    const maxY = Math.max(margin, Number(roomHeight) - Number(dimensions.height || 0) - margin);
    return {
        ...asset,
        x: Math.round(Math.min(maxX, Math.max(margin, (Number(asset?.x) || 0) * scaleX))),
        y: Math.round(Math.min(maxY, Math.max(margin, (Number(asset?.y) || 0) * scaleY))),
    };
}

function officeDraftCompactDefaultSpace(space, options = {}) {
    const scaleX = Math.max(0.56, Math.min(1, Number(options.scaleX || options.scale) || 1));
    const scaleY = Math.max(0.56, Math.min(1, Number(options.scaleY || options.scale) || scaleX));
    const minWidth = Math.max(720, Math.min(1500, Number(options.minWidth) || 880));
    const minHeight = Math.max(520, Math.min(1100, Number(options.minHeight) || 660));
    const width = Math.max(minWidth, Math.round((Number(space?.width) || 0) * scaleX));
    const height = Math.max(minHeight, Math.round((Number(space?.height) || 0) * scaleY));
    const robotInset = 72;
    const assets = Array.isArray(space?.assets)
        ? space.assets.map((asset) => officeDraftCompactDefaultAsset(asset, scaleX, scaleY, width, height))
        : [];
    return {
        ...space,
        width,
        height,
        robotX: Math.round(Math.min(width - robotInset, Math.max(robotInset, (Number(space?.robotX) || 0) * scaleX))),
        robotY: Math.round(Math.min(height - robotInset, Math.max(robotInset, (Number(space?.robotY) || 0) * scaleY))),
        assets,
    };
}

function officeDraftCompactDefaultLayoutSpaces(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const center = OFFICE_DRAFT_MAP_SIZE / 2;
    return spaces.map((space) => {
        const scale = OFFICE_DRAFT_DEFAULT_ROOM_SCALE_BY_ID[safeString(space?.id)] || {};
        const compact = officeDraftCompactDefaultSpace(space, scale);
        const offsetScale = Math.max(0.62, Math.min(1, Number(scale.offsetScale) || OFFICE_DRAFT_DEFAULT_LAYOUT_OFFSET_SCALE));
        const previousCenterX = (Number(space?.x) || 0) + ((Number(space?.width) || 0) / 2);
        const previousCenterY = (Number(space?.y) || 0) + ((Number(space?.height) || 0) / 2);
        const nextCenterX = center + ((previousCenterX - center) * offsetScale);
        const nextCenterY = center + ((previousCenterY - center) * offsetScale);
        return {
            ...compact,
            x: Math.round(nextCenterX - (compact.width / 2)),
            y: Math.round(nextCenterY - (compact.height / 2)),
        };
    });
}

const OFFICE_DRAFT_DEFAULT_UPRIGHT_ASSET_TYPES = new Set([
    'bean_bag',
    'bench',
    'chair',
    'couch',
    'lounge_chair',
    'loveseat',
    'meeting_chair',
    'ottoman',
    'stool',
]);

const OFFICE_DRAFT_DEFAULT_LAYERED_ASSET_TYPES = new Set([
    'keyboard_tray',
    'laptop',
    'microphone',
    'carpet',
    'rug',
]);

const OFFICE_DRAFT_DEFAULT_INTERACTION_CLEARANCE_TYPES = new Set([
    'arcade_cabinet',
    'charging_dock',
    'coffee_bar',
    'focus_pod',
    'fridge',
    'printer',
    'ticket_kiosk',
    'vending_machine',
    'water_cooler',
]);

const OFFICE_DRAFT_DEFAULT_LAYOUT_ASSET_OVERRIDES = Object.freeze({
    'planning-hub': Object.freeze({
        'whiteboard-1': { x: 70, y: 82 },
        'round_table-2': { x: 365, y: 315 },
        'chair-3': { x: 300, y: 220 },
        'chair-4': { x: 570, y: 455 },
        'kanban_board-45': { x: 660, y: 88 },
        'blueprint_table-46': { x: 105, y: 455 },
        'sticky_note_wall-120': { x: 690, y: 295 },
        'meeting_chair-220': { x: 435, y: 225 },
        'meeting_chair-221': { x: 460, y: 500 },
        'data_wall-270': { x: 330, y: 92 },
        'tablet_stand-271': { x: 765, y: 510 },
        'bench-272': { x: 620, y: 535 },
        'room_sign-273': { x: 55, y: 545 },
    }),
    'software-lab': Object.freeze({
        'workstation-5': { x: 155, y: 135 },
        'workstation-6': { x: 445, y: 135 },
        'desk-7': { x: 780, y: 170 },
        'server_rack-8': { x: 1010, y: 130 },
        'chair-9': { x: 245, y: 370 },
        'chair-10': { x: 535, y: 370 },
        'lab_bench-49': { x: 715, y: 520 },
        'tool_cart-50': { x: 1010, y: 535 },
        'dual_monitor-122': { x: 590, y: 365 },
        'testing_rig-123': { x: 905, y: 640 },
        'code_terminal-224': { x: 610, y: 570 },
        'storage_locker-226': { x: 1080, y: 390 },
        'rug-258': { x: 380, y: 300 },
        'standing_desk-259': { x: 350, y: 560 },
        'data_wall-260': { x: 845, y: 250 },
        'power_panel-261': { x: 1085, y: 210 },
        'task_lamp-262': { x: 825, y: 565 },
        'divider-263': { x: 930, y: 505 },
    }),
    'research-bay': Object.freeze({
        'bookshelf-11': { x: 80, y: 100 },
        'whiteboard-13': { x: 565, y: 90 },
        'desk-12': { x: 350, y: 365 },
        'research_terminal-125': { x: 410, y: 215 },
        'map_table-126': { x: 170, y: 360 },
        'microscope-228': { x: 640, y: 345 },
        'sample_tray-127': { x: 735, y: 490 },
        'data_wall-230': { x: 300, y: 535 },
        'plant-14': { x: 720, y: 500 },
        'rug-264': { x: 255, y: 285 },
        'tablet_stand-265': { x: 520, y: 510 },
        'archive_box-266': { x: 115, y: 520 },
        'bench-267': { x: 565, y: 565 },
        'task_lamp-268': { x: 230, y: 495 },
        'room_sign-269': { x: 55, y: 535 },
    }),
    'design-loft': Object.freeze({
        'whiteboard-15': { x: 80, y: 80 },
        'pinboard-128': { x: 470, y: 85 },
        'drafting_table-58': { x: 145, y: 385 },
        'round_table-16': { x: 450, y: 405 },
        'chair-17': { x: 375, y: 550 },
        'loveseat-231': { x: 575, y: 360 },
        'side_table-130': { x: 690, y: 535 },
        'monitor_stand-232': { x: 315, y: 245 },
        'tall_plant-233': { x: 710, y: 180 },
        'plant-18': { x: 720, y: 520 },
    }),
    'content-studio': Object.freeze({
        'wall_monitor-65': { x: 105, y: 80 },
        'desk-19': { x: 130, y: 205 },
        'workstation-20': { x: 465, y: 205 },
        'podcast_desk-234': { x: 285, y: 385 },
        'microphone-131': { x: 310, y: 480 },
        'sound_mixer-132': { x: 560, y: 420 },
        'green_screen-133': { x: 650, y: 85 },
        'light_panel-63': { x: 735, y: 255 },
        'camera_tripod-62': { x: 145, y: 465 },
        'couch-21': { x: 435, y: 560 },
        'plant-22': { x: 35, y: 520 },
        'prop_shelf-236': { x: 725, y: 520 },
    }),
    'ops-command': Object.freeze({
        'server_rack-23': { x: 75, y: 115 },
        'server_rack-24': { x: 230, y: 115 },
        'wall_monitor-69': { x: 455, y: 75 },
        'workstation-25': { x: 535, y: 225 },
        'security_console-66': { x: 325, y: 430 },
        'network_switch-134': { x: 140, y: 410 },
        'data_wall-136': { x: 520, y: 390 },
        'server_console-237': { x: 650, y: 520 },
        'firewall_box-238': { x: 260, y: 555 },
        'storage_locker-239': { x: 70, y: 500 },
        'package_station-68': { x: 675, y: 610 },
    }),
    'support-desk': Object.freeze({
        'dispatch_board-139': { x: 215, y: 80 },
        'whiteboard-29': { x: 585, y: 90 },
        'ticket_kiosk-137': { x: 765, y: 128 },
        'phone_booth-138': { x: 50, y: 220 },
        'desk-27': { x: 250, y: 260 },
        'laptop-243': { x: 315, y: 296 },
        'chair-28': { x: 335, y: 430 },
        'printer-71': { x: 575, y: 310 },
        'copier-240': { x: 650, y: 450 },
        'bookshelf-30': { x: 715, y: 445 },
        'mail_sorter-70': { x: 80, y: 500 },
        'mail_cart-242': { x: 245, y: 565 },
        'shredder-241': { x: 455, y: 570 },
        'filing_cabinet-72': { x: 520, y: 520 },
        'floor_sign-73': { x: 740, y: 315 },
    }),
    cafeteria: Object.freeze({
        'vending_machine-31': { x: 70, y: 155 },
        'coffee_bar-32': { x: 325, y: 150 },
        'microwave-76': { x: 470, y: 285 },
        'fridge-75': { x: 850, y: 165 },
        'water_cooler-77': { x: 920, y: 405 },
        'kitchen_island-74': { x: 220, y: 385 },
        'recipe_counter-79': { x: 105, y: 560 },
        'round_table-33': { x: 565, y: 420 },
        'chair-34': { x: 500, y: 565 },
        'chair-35': { x: 745, y: 390 },
        'stool-244': { x: 360, y: 530 },
        'stool-245': { x: 445, y: 500 },
        'stool-246': { x: 300, y: 330 },
        'snack_shelf-78': { x: 760, y: 555 },
        'snack_table-142': { x: 695, y: 310 },
        'soda_crate-140': { x: 115, y: 365 },
        'tea_station-141': { x: 610, y: 270 },
        'trash_bin-247': { x: 935, y: 590 },
    }),
    lounge: Object.freeze({
        'coffee_bar-36': { x: 110, y: 125 },
        'trophy_shelf-82': { x: 375, y: 125 },
        'arcade_cabinet-81': { x: 675, y: 190 },
        'game_console-144': { x: 715, y: 330 },
        'loveseat-248': { x: 585, y: 165 },
        'couch-1': { x: 260, y: 385 },
        'couch-2': { x: 630, y: 410 },
        'ottoman-143': { x: 490, y: 355 },
        'side_table-249': { x: 555, y: 310 },
        'lounge_chair-145': { x: 125, y: 420 },
        'bean_bag-80': { x: 760, y: 385 },
        'floor_lamp-83': { x: 840, y: 485 },
        'plant-37': { x: 785, y: 510 },
        'planter_box-251': { x: 140, y: 555 },
        'round_table-274': { x: 455, y: 405 },
        'tablet_stand-275': { x: 715, y: 505 },
        'bench-276': { x: 300, y: 540 },
    }),
    'focus-pods': Object.freeze({
        'focus_pod-38': { x: 115, y: 150 },
        'focus_pod-39': { x: 350, y: 150 },
        'focus_pod-40': { x: 585, y: 150 },
        'phone_booth-146': { x: 670, y: 390 },
        'divider-87': { x: 400, y: 425 },
        'task_lamp-147': { x: 295, y: 470 },
        'charging_dock-88': { x: 560, y: 500 },
        'storage_locker-252': { x: 40, y: 430 },
        'planter_box-253': { x: 250, y: 550 },
    }),
    lobby: Object.freeze({
        'floor_sign-90': { x: 670, y: 210 },
        'coat_rack-149': { x: 780, y: 250 },
        'bench-150': { x: 660, y: 110 },
        'loveseat-255': { x: 300, y: 230 },
        'planter_box-256': { x: 710, y: 390 },
    }),
});

function officeDraftDefaultAssetCanLayer(asset) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    return OFFICE_DRAFT_DEFAULT_LAYERED_ASSET_TYPES.has(type)
        || OFFICE_DRAFT_DEFAULT_LAYERED_ASSET_TYPES.has(safeString(descriptor?.shape));
}

function officeDraftDefaultAssetVisualRect(asset) {
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const padding = officeDraftDefaultAssetCanLayer(asset) ? -24 : 14;
    const left = Math.round(Number(asset?.x) || 0);
    const top = Math.round(Number(asset?.y) || 0);
    return {
        left: left - padding,
        top: top - padding,
        right: left + Number(dimensions.width || 0) + padding,
        bottom: top + Number(dimensions.height || 0) + padding,
    };
}

function officeDraftDefaultAssetInteractionClearanceRects(asset, roomWidthRaw = 0, roomHeightRaw = 0) {
    if (!asset || officeDraftDefaultAssetCanLayer(asset)) return [];
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const interaction = safeString(descriptor?.interaction);
    const needsClearance = OFFICE_DRAFT_DEFAULT_INTERACTION_CLEARANCE_TYPES.has(type)
        || ['drink', 'food', 'play', 'print', 'charge', 'work'].includes(interaction);
    if (!needsClearance) return [];
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const roomWidth = Number(roomWidthRaw) || 0;
    const roomHeight = Number(roomHeightRaw) || 0;
    const left = Math.round(Number(asset?.x) || 0);
    const top = Math.round(Number(asset?.y) || 0);
    const right = left + Number(dimensions.width || 0);
    const bottom = top + Number(dimensions.height || 0);
    const reach = type === 'vending_machine' ? 270 : 190;
    const frontDepth = type === 'vending_machine' ? 250 : 180;
    const pad = type === 'vending_machine' ? 26 : 18;
    const clampRect = (rect) => ({
        left: Math.round(officeClamp(rect.left, -80, Math.max(roomWidth, rect.left))),
        top: Math.round(officeClamp(rect.top, -80, Math.max(roomHeight, rect.top))),
        right: Math.round(officeClamp(rect.right, 0, roomWidth + 80)),
        bottom: Math.round(officeClamp(rect.bottom, 0, roomHeight + 80)),
    });
    return [
        clampRect({
            left: left - pad,
            top: bottom + 8,
            right: right + reach,
            bottom: bottom + frontDepth,
        }),
        clampRect({
            left: right + 8,
            top: top + Math.round(Number(dimensions.height || 0) * 0.08),
            right: right + reach,
            bottom: bottom + Math.round(frontDepth * 0.72),
        }),
    ].filter((rect) => rect.left < rect.right && rect.top < rect.bottom);
}

function officeDraftDefaultRectsOverlap(a, b) {
    if (!a || !b) return false;
    return a.left < b.right
        && a.right > b.left
        && a.top < b.bottom
        && a.bottom > b.top;
}

function officeDraftDefaultDoorClearanceRects(space) {
    const width = Number(space?.width) || 0;
    const height = Number(space?.height) || 0;
    if (width <= 0 || height <= 0) return [];
    const depth = Math.max(150, Math.min(210, Math.round(Math.min(width, height) * 0.2)));
    const horizontalSpan = Math.max(240, Math.min(420, Math.round(width * 0.28)));
    const verticalSpan = Math.max(220, Math.min(380, Math.round(height * 0.3)));
    const centerX = Math.round(width * 0.5);
    const centerY = Math.round(height * 0.52);
    const horizontalLeft = Math.round(centerX - (horizontalSpan / 2));
    const horizontalRight = Math.round(centerX + (horizontalSpan / 2));
    const verticalTop = Math.round(centerY - (verticalSpan / 2));
    const verticalBottom = Math.round(centerY + (verticalSpan / 2));
    return [
        { left: horizontalLeft, top: height - depth, right: horizontalRight, bottom: height + 80 },
        { left: horizontalLeft, top: -80, right: horizontalRight, bottom: depth },
        { left: width - depth, top: verticalTop, right: width + 80, bottom: verticalBottom },
        { left: -80, top: verticalTop, right: depth, bottom: verticalBottom },
    ];
}

function officeDraftDefaultRobotClearanceRect(space) {
    const robotX = Math.round(Number(space?.robotX) || 0);
    const robotY = Math.round(Number(space?.robotY) || 0);
    if (!robotX || !robotY) return null;
    return {
        left: robotX - 104,
        top: robotY - 112,
        right: robotX + 124,
        bottom: robotY + 138,
    };
}

function officeDraftDefaultAssetNudgeCandidates(asset, roomWidth, roomHeight) {
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const margin = 40;
    const maxX = Math.max(margin, Number(roomWidth) - Number(dimensions.width || 0) - margin);
    const maxY = Math.max(margin, Number(roomHeight) - Number(dimensions.height || 0) - margin);
    const originX = Math.round(Number(asset?.x) || 0);
    const originY = Math.round(Number(asset?.y) || 0);
    const clampCandidate = (dx, dy) => ({
        x: Math.round(officeClamp(originX + dx, margin, maxX)),
        y: Math.round(officeClamp(originY + dy, margin, maxY)),
    });
    const candidates = [clampCandidate(0, 0)];
    const stepX = Math.max(76, Math.round(Number(dimensions.width || 0) * 0.58));
    const stepY = Math.max(64, Math.round(Number(dimensions.height || 0) * 0.62));
    for (let ring = 1; ring <= 6; ring += 1) {
        [
            [ring, 0],
            [-ring, 0],
            [0, ring],
            [0, -ring],
            [ring, ring],
            [-ring, ring],
            [ring, -ring],
            [-ring, -ring],
            [ring, Math.ceil(ring / 2)],
            [-ring, Math.ceil(ring / 2)],
            [Math.ceil(ring / 2), ring],
            [Math.ceil(ring / 2), -ring],
        ].forEach(([xMul, yMul]) => {
            candidates.push(clampCandidate(xMul * stepX, yMul * stepY));
        });
    }
    const scanStepX = Math.max(86, Math.round(Number(dimensions.width || 0) * 0.68));
    const scanStepY = Math.max(72, Math.round(Number(dimensions.height || 0) * 0.72));
    for (let y = margin; y <= maxY; y += scanStepY) {
        for (let x = margin; x <= maxX; x += scanStepX) {
            candidates.push({
                x: Math.round(officeClamp(x, margin, maxX)),
                y: Math.round(officeClamp(y, margin, maxY)),
            });
        }
    }
    candidates.push({ x: Math.round(maxX), y: Math.round(maxY) });
    const seen = new Set();
    return candidates.filter((candidate) => {
        const key = `${candidate.x},${candidate.y}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function officeDraftPolishDefaultAsset(asset, roomWidth, roomHeight, placedRects, reservedRects = []) {
    const next = {
        ...asset,
        rotation: OFFICE_DRAFT_DEFAULT_UPRIGHT_ASSET_TYPES.has(safeString(asset?.type))
            ? 0
            : officeDraftNormalizeRotation(asset?.rotation),
    };
    if (officeDraftDefaultAssetCanLayer(next)) return next;
    let best = { ...next };
    let bestScore = Number.POSITIVE_INFINITY;
    const reserved = (Array.isArray(reservedRects) ? reservedRects : []).filter(Boolean);
    const candidates = officeDraftDefaultAssetNudgeCandidates(next, roomWidth, roomHeight);
    const scoreCandidates = ({ allowPlacedOverlap = false, allowReservedOverlap = false } = {}) => {
        candidates.forEach((candidate) => {
            const candidateAsset = { ...next, x: candidate.x, y: candidate.y };
            const rect = officeDraftDefaultAssetVisualRect(candidateAsset);
            const placedOverlapCount = placedRects.filter((placed) => officeDraftDefaultRectsOverlap(rect, placed)).length;
            if (!allowPlacedOverlap && placedOverlapCount) return;
            const reservedOverlapCount = reserved.filter((reservedRect) => officeDraftDefaultRectsOverlap(rect, reservedRect)).length;
            if (!allowReservedOverlap && reservedOverlapCount) return;
            const distance = Math.hypot(candidate.x - (Number(next.x) || 0), candidate.y - (Number(next.y) || 0));
            const score = distance + (candidate.y * 0.02) + (reservedOverlapCount * 400) + (placedOverlapCount * 10000);
            if (score < bestScore) {
                best = candidateAsset;
                bestScore = score;
            }
        });
    };
    scoreCandidates({ allowPlacedOverlap: false, allowReservedOverlap: false });
    if (!Number.isFinite(bestScore)) scoreCandidates({ allowPlacedOverlap: false, allowReservedOverlap: true });
    if (!Number.isFinite(bestScore)) scoreCandidates({ allowPlacedOverlap: true, allowReservedOverlap: true });
    return best;
}

function officeDraftPolishDefaultLayoutSpaces(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    return spaces.map((space) => {
        const placedRects = [];
        const reservedRects = [
            ...officeDraftDefaultDoorClearanceRects(space),
            officeDraftDefaultRobotClearanceRect(space),
        ].filter(Boolean);
        const assets = (Array.isArray(space?.assets) ? space.assets : []).map((asset) => {
            const override = OFFICE_DRAFT_DEFAULT_LAYOUT_ASSET_OVERRIDES[safeString(space?.id)]?.[safeString(asset?.id)] || null;
            const authoredAsset = override ? { ...asset, ...override } : asset;
            const polished = officeDraftPolishDefaultAsset(
                authoredAsset,
                Number(space?.width) || 0,
                Number(space?.height) || 0,
                placedRects,
                reservedRects,
            );
            if (!officeDraftDefaultAssetCanLayer(polished)) {
                placedRects.push(officeDraftDefaultAssetVisualRect(polished));
                reservedRects.push(...officeDraftDefaultAssetInteractionClearanceRects(
                    polished,
                    Number(space?.width) || 0,
                    Number(space?.height) || 0,
                ));
            }
            return polished;
        });
        return {
            ...space,
            assets,
        };
    });
}

function officeDraftDefaultLayoutSnapshot() {
    const centerX = OFFICE_DRAFT_MAP_SIZE / 2;
    const centerY = OFFICE_DRAFT_MAP_SIZE / 2;
    const spaces = [
            {
                id: 'planning-hub',
                roomId: 'room-planning',
                name: 'Strategy Room',
                x: centerX - 2480,
                y: centerY - 1880,
                width: 1540,
                height: 1180,
                floorPalette: 'slate',
                robotX: 520,
                robotY: 640,
                assets: [
                    { id: 'whiteboard-1', type: 'whiteboard', x: 160, y: 96, rotation: 0, colorVariant: 'clean', scale: 1 },
                    { id: 'round_table-2', type: 'conference_table', x: 520, y: 500, rotation: 0, colorVariant: 'glass', scale: 0.78 },
                    { id: 'chair-3', type: 'meeting_chair', x: 480, y: 430, rotation: 330, colorVariant: 'ink', scale: 0.86 },
                    { id: 'chair-4', type: 'meeting_chair', x: 870, y: 650, rotation: 140, colorVariant: 'berry', scale: 0.86 },
                    { id: 'kanban_board-45', type: 'kanban_board', x: 1030, y: 120, rotation: 0, colorVariant: 'clean', scale: 0.9 },
                    { id: 'blueprint_table-46', type: 'blueprint_table', x: 220, y: 690, rotation: 0, colorVariant: 'blueprint', scale: 0.85 },
                    { id: 'floor_lamp-47', type: 'floor_lamp', x: 1260, y: 750, rotation: 0, colorVariant: 'amber', scale: 0.75 },
                    { id: 'rug-48', type: 'rug', x: 560, y: 420, rotation: 0, colorVariant: 'slate', scale: 0.85 },
                    { id: 'sticky_note_wall-120', type: 'sticky_note_wall', x: 980, y: 340, rotation: 0, colorVariant: 'warning', scale: 0.8 },
                    { id: 'room_sign-121', type: 'room_sign', x: 90, y: 1010, rotation: 0, colorVariant: 'clean', scale: 0.75 },
                    { id: 'meeting_chair-220', type: 'meeting_chair', x: 660, y: 420, rotation: 0, colorVariant: 'steel', scale: 0.82 },
                    { id: 'meeting_chair-221', type: 'meeting_chair', x: 710, y: 680, rotation: 180, colorVariant: 'steel', scale: 0.82 },
                    { id: 'planter_box-222', type: 'planter_box', x: 1180, y: 560, rotation: 0, colorVariant: 'moss', scale: 0.7 },
                    { id: 'wall_clock-223', type: 'wall_clock', x: 1260, y: 120, rotation: 0, colorVariant: 'clean', scale: 0.7 },
                    { id: 'data_wall-270', type: 'data_wall', x: 510, y: 150, rotation: 0, colorVariant: 'blueprint', scale: 0.66 },
                    { id: 'tablet_stand-271', type: 'tablet_stand', x: 1160, y: 790, rotation: 0, colorVariant: 'neon', scale: 0.68 },
                    { id: 'bench-272', type: 'bench', x: 950, y: 840, rotation: 0, colorVariant: 'oak', scale: 0.7 },
                    { id: 'room_sign-273', type: 'room_sign', x: 90, y: 930, rotation: 0, colorVariant: 'clean', scale: 0.7 },
                ],
            },
            {
                id: 'software-lab',
                roomId: 'room-engineering',
                name: 'Software Lab',
                x: centerX - 740,
                y: centerY - 2040,
                width: 2140,
                height: 1360,
                floorPalette: 'sand',
                robotX: 760,
                robotY: 720,
                assets: [
                    { id: 'workstation-5', type: 'workstation', x: 260, y: 270, rotation: 0, colorVariant: 'neon', scale: 1 },
                    { id: 'workstation-6', type: 'workstation', x: 740, y: 270, rotation: 0, colorVariant: 'amber', scale: 1 },
                    { id: 'desk-7', type: 'desk', x: 1240, y: 320, rotation: 0, colorVariant: 'steel', scale: 1.2 },
                    { id: 'server_rack-8', type: 'server_rack', x: 1760, y: 260, rotation: 0, colorVariant: 'datacenter', scale: 1 },
                    { id: 'chair-9', type: 'chair', x: 350, y: 540, rotation: 180, colorVariant: 'ink', scale: 1 },
                    { id: 'chair-10', type: 'chair', x: 835, y: 540, rotation: 180, colorVariant: 'ink', scale: 1 },
                    { id: 'lab_bench-49', type: 'lab_bench', x: 1220, y: 780, rotation: 0, colorVariant: 'steel', scale: 0.9 },
                    { id: 'tool_cart-50', type: 'tool_cart', x: 1660, y: 830, rotation: 0, colorVariant: 'warning', scale: 0.8 },
                    { id: 'router_node-51', type: 'router_node', x: 1710, y: 610, rotation: 0, colorVariant: 'neon', scale: 0.8 },
                    { id: 'wall_monitor-52', type: 'wall_monitor', x: 1180, y: 92, rotation: 0, colorVariant: 'neon', scale: 0.85 },
                    { id: 'charging_dock-53', type: 'charging_dock', x: 510, y: 890, rotation: 0, colorVariant: 'neon', scale: 0.8 },
                    { id: 'dual_monitor-122', type: 'dual_monitor', x: 1010, y: 500, rotation: 0, colorVariant: 'blueprint', scale: 0.8 },
                    { id: 'testing_rig-123', type: 'testing_rig', x: 1500, y: 1020, rotation: 0, colorVariant: 'warning', scale: 0.72 },
                    { id: 'keyboard_tray-124', type: 'keyboard_tray', x: 420, y: 440, rotation: 0, colorVariant: 'graphite', scale: 0.72 },
                    { id: 'code_terminal-224', type: 'code_terminal', x: 1040, y: 720, rotation: 0, colorVariant: 'neon', scale: 0.74 },
                    { id: 'laptop-225', type: 'laptop', x: 1360, y: 530, rotation: 0, colorVariant: 'steel', scale: 0.72 },
                    { id: 'storage_locker-226', type: 'storage_locker', x: 1880, y: 690, rotation: 0, colorVariant: 'steel', scale: 0.7 },
                    { id: 'meeting_chair-227', type: 'meeting_chair', x: 1140, y: 890, rotation: 180, colorVariant: 'ink', scale: 0.8 },
                    { id: 'rug-258', type: 'rug', x: 620, y: 470, rotation: 0, colorVariant: 'slate', scale: 0.82 },
                    { id: 'standing_desk-259', type: 'standing_desk', x: 610, y: 900, rotation: 0, colorVariant: 'walnut', scale: 0.78 },
                    { id: 'data_wall-260', type: 'data_wall', x: 1390, y: 410, rotation: 0, colorVariant: 'blueprint', scale: 0.76 },
                    { id: 'power_panel-261', type: 'power_panel', x: 1780, y: 380, rotation: 0, colorVariant: 'warning', scale: 0.7 },
                    { id: 'task_lamp-262', type: 'task_lamp', x: 1320, y: 840, rotation: 0, colorVariant: 'clean', scale: 0.7 },
                    { id: 'divider-263', type: 'divider', x: 1510, y: 760, rotation: 0, colorVariant: 'slate', scale: 0.72 },
                ],
            },
            {
                id: 'research-bay',
                roomId: 'room-research',
                name: 'Research Bay',
                x: centerX + 1620,
                y: centerY - 1840,
                width: 1560,
                height: 1180,
                floorPalette: 'clay',
                robotX: 590,
                robotY: 640,
                assets: [
                    { id: 'bookshelf-11', type: 'bookshelf', x: 120, y: 150, rotation: 0, colorVariant: 'archive', scale: 1.2 },
                    { id: 'desk-12', type: 'desk', x: 650, y: 610, rotation: 0, colorVariant: 'walnut', scale: 1 },
                    { id: 'whiteboard-13', type: 'whiteboard', x: 930, y: 140, rotation: 0, colorVariant: 'lime', scale: 1 },
                    { id: 'plant-14', type: 'plant', x: 1300, y: 830, rotation: 0, colorVariant: 'fern', scale: 1 },
                    { id: 'filing_cabinet-54', type: 'filing_cabinet', x: 240, y: 720, rotation: 0, colorVariant: 'steel', scale: 0.8 },
                    { id: 'archive_box-55', type: 'archive_box', x: 430, y: 880, rotation: 0, colorVariant: 'cardboard', scale: 0.8 },
                    { id: 'wall_monitor-56', type: 'wall_monitor', x: 560, y: 130, rotation: 0, colorVariant: 'blueprint', scale: 0.85 },
                    { id: 'floor_lamp-57', type: 'floor_lamp', x: 1200, y: 570, rotation: 0, colorVariant: 'clean', scale: 0.75 },
                    { id: 'research_terminal-125', type: 'research_terminal', x: 680, y: 360, rotation: 0, colorVariant: 'blueprint', scale: 0.75 },
                    { id: 'map_table-126', type: 'map_table', x: 360, y: 520, rotation: 0, colorVariant: 'blueprint', scale: 0.72 },
                    { id: 'sample_tray-127', type: 'sample_tray', x: 980, y: 720, rotation: 0, colorVariant: 'clean', scale: 0.7 },
                    { id: 'microscope-228', type: 'microscope', x: 1040, y: 470, rotation: 0, colorVariant: 'steel', scale: 0.72 },
                    { id: 'pinboard-229', type: 'pinboard', x: 1120, y: 350, rotation: 0, colorVariant: 'cardboard', scale: 0.7 },
                    { id: 'data_wall-230', type: 'data_wall', x: 560, y: 850, rotation: 0, colorVariant: 'blueprint', scale: 0.68 },
                    { id: 'rug-264', type: 'rug', x: 470, y: 470, rotation: 0, colorVariant: 'slate', scale: 0.74 },
                    { id: 'tablet_stand-265', type: 'tablet_stand', x: 850, y: 835, rotation: 0, colorVariant: 'neon', scale: 0.68 },
                    { id: 'archive_box-266', type: 'archive_box', x: 210, y: 845, rotation: 0, colorVariant: 'cardboard', scale: 0.7 },
                    { id: 'bench-267', type: 'bench', x: 930, y: 920, rotation: 0, colorVariant: 'oak', scale: 0.68 },
                    { id: 'task_lamp-268', type: 'task_lamp', x: 390, y: 820, rotation: 0, colorVariant: 'clean', scale: 0.66 },
                    { id: 'room_sign-269', type: 'room_sign', x: 90, y: 930, rotation: 0, colorVariant: 'clean', scale: 0.66 },
                ],
            },
            {
                id: 'design-loft',
                roomId: 'room-design',
                name: 'Design Loft',
                x: centerX - 2540,
                y: centerY - 320,
                width: 1440,
                height: 1220,
                floorPalette: 'terrazzo',
                robotX: 520,
                robotY: 660,
                assets: [
                    { id: 'whiteboard-15', type: 'whiteboard', x: 130, y: 120, rotation: 0, colorVariant: 'clean', scale: 1 },
                    { id: 'round_table-16', type: 'round_table', x: 690, y: 580, rotation: 0, colorVariant: 'oak', scale: 1 },
                    { id: 'chair-17', type: 'chair', x: 590, y: 830, rotation: 0, colorVariant: 'berry', scale: 1 },
                    { id: 'plant-18', type: 'plant', x: 1160, y: 760, rotation: 0, colorVariant: 'blossom', scale: 1 },
                    { id: 'drafting_table-58', type: 'drafting_table', x: 230, y: 590, rotation: 0, colorVariant: 'oak', scale: 0.9 },
                    { id: 'acoustic_panel-59', type: 'acoustic_panel', x: 980, y: 210, rotation: 0, colorVariant: 'berry', scale: 0.85 },
                    { id: 'floor_lamp-60', type: 'floor_lamp', x: 1190, y: 470, rotation: 0, colorVariant: 'amber', scale: 0.75 },
                    { id: 'rug-61', type: 'rug', x: 520, y: 530, rotation: 0, colorVariant: 'berry', scale: 0.8 },
                    { id: 'pinboard-128', type: 'pinboard', x: 720, y: 140, rotation: 0, colorVariant: 'cardboard', scale: 0.8 },
                    { id: 'vr_headset-129', type: 'vr_headset', x: 440, y: 790, rotation: 0, colorVariant: 'graphite', scale: 0.7 },
                    { id: 'side_table-130', type: 'side_table', x: 930, y: 830, rotation: 0, colorVariant: 'oak', scale: 0.72 },
                    { id: 'loveseat-231', type: 'loveseat', x: 900, y: 590, rotation: 0, colorVariant: 'moss', scale: 0.72 },
                    { id: 'monitor_stand-232', type: 'monitor_stand', x: 470, y: 380, rotation: 0, colorVariant: 'neon', scale: 0.7 },
                    { id: 'tall_plant-233', type: 'tall_plant', x: 1260, y: 260, rotation: 0, colorVariant: 'moss', scale: 0.68 },
                ],
            },
            {
                id: 'content-studio',
                roomId: 'room-content',
                name: 'Content Studio',
                x: centerX - 860,
                y: centerY - 360,
                width: 1480,
                height: 1220,
                floorPalette: 'carpet',
                robotX: 560,
                robotY: 620,
                assets: [
                    { id: 'desk-19', type: 'desk', x: 220, y: 250, rotation: 0, colorVariant: 'steel', scale: 1.2 },
                    { id: 'workstation-20', type: 'workstation', x: 690, y: 250, rotation: 0, colorVariant: 'amber', scale: 1 },
                    { id: 'couch-21', type: 'couch', x: 560, y: 810, rotation: 0, colorVariant: 'harbor', scale: 1 },
                    { id: 'plant-22', type: 'plant', x: 1180, y: 760, rotation: 0, colorVariant: 'fern', scale: 1 },
                    { id: 'camera_tripod-62', type: 'camera_tripod', x: 180, y: 680, rotation: 0, colorVariant: 'graphite', scale: 0.8 },
                    { id: 'light_panel-63', type: 'light_panel', x: 1110, y: 270, rotation: 0, colorVariant: 'clean', scale: 0.8 },
                    { id: 'acoustic_panel-64', type: 'acoustic_panel', x: 1010, y: 560, rotation: 0, colorVariant: 'slate', scale: 0.9 },
                    { id: 'wall_monitor-65', type: 'wall_monitor', x: 330, y: 110, rotation: 0, colorVariant: 'neon', scale: 0.85 },
                    { id: 'microphone-131', type: 'microphone', x: 450, y: 680, rotation: 0, colorVariant: 'graphite', scale: 0.72 },
                    { id: 'sound_mixer-132', type: 'sound_mixer', x: 740, y: 570, rotation: 0, colorVariant: 'graphite', scale: 0.72 },
                    { id: 'green_screen-133', type: 'green_screen', x: 1040, y: 120, rotation: 0, colorVariant: 'moss', scale: 0.72 },
                    { id: 'podcast_desk-234', type: 'podcast_desk', x: 390, y: 520, rotation: 0, colorVariant: 'walnut', scale: 0.74 },
                    { id: 'camera_case-235', type: 'camera_case', x: 240, y: 880, rotation: 0, colorVariant: 'graphite', scale: 0.72 },
                    { id: 'prop_shelf-236', type: 'prop_shelf', x: 1120, y: 600, rotation: 0, colorVariant: 'walnut', scale: 0.72 },
                ],
            },
            {
                id: 'ops-command',
                roomId: 'room-ops',
                name: 'Ops Command',
                x: centerX + 840,
                y: centerY - 360,
                width: 1560,
                height: 1220,
                floorPalette: 'slate',
                robotX: 590,
                robotY: 650,
                assets: [
                    { id: 'server_rack-23', type: 'server_rack', x: 170, y: 210, rotation: 0, colorVariant: 'datacenter', scale: 1.2 },
                    { id: 'server_rack-24', type: 'server_rack', x: 390, y: 210, rotation: 0, colorVariant: 'warning', scale: 1 },
                    { id: 'workstation-25', type: 'workstation', x: 820, y: 300, rotation: 0, colorVariant: 'neon', scale: 1.2 },
                    { id: 'whiteboard-26', type: 'whiteboard', x: 850, y: 740, rotation: 0, colorVariant: 'clean', scale: 1 },
                    { id: 'security_console-66', type: 'security_console', x: 470, y: 720, rotation: 0, colorVariant: 'warning', scale: 0.9 },
                    { id: 'router_node-67', type: 'router_node', x: 1210, y: 280, rotation: 0, colorVariant: 'neon', scale: 0.8 },
                    { id: 'package_station-68', type: 'package_station', x: 1120, y: 810, rotation: 0, colorVariant: 'cardboard', scale: 0.85 },
                    { id: 'wall_monitor-69', type: 'wall_monitor', x: 640, y: 90, rotation: 0, colorVariant: 'blueprint', scale: 0.85 },
                    { id: 'network_switch-134', type: 'network_switch', x: 230, y: 620, rotation: 0, colorVariant: 'neon', scale: 0.7 },
                    { id: 'power_panel-135', type: 'power_panel', x: 1320, y: 560, rotation: 0, colorVariant: 'warning', scale: 0.72 },
                    { id: 'data_wall-136', type: 'data_wall', x: 790, y: 510, rotation: 0, colorVariant: 'blueprint', scale: 0.72 },
                    { id: 'server_console-237', type: 'server_console', x: 1030, y: 600, rotation: 0, colorVariant: 'neon', scale: 0.72 },
                    { id: 'firewall_box-238', type: 'firewall_box', x: 280, y: 930, rotation: 0, colorVariant: 'warning', scale: 0.72 },
                    { id: 'storage_locker-239', type: 'storage_locker', x: 80, y: 660, rotation: 0, colorVariant: 'graphite', scale: 0.72 },
                ],
            },
            {
                id: 'support-desk',
                roomId: 'room-support',
                name: 'Support Desk',
                x: centerX + 2620,
                y: centerY - 220,
                width: 1320,
                height: 1060,
                floorPalette: 'sand',
                robotX: 500,
                robotY: 560,
                assets: [
                    { id: 'desk-27', type: 'desk', x: 230, y: 320, rotation: 0, colorVariant: 'walnut', scale: 1.2 },
                    { id: 'chair-28', type: 'chair', x: 330, y: 560, rotation: 180, colorVariant: 'ink', scale: 1 },
                    { id: 'whiteboard-29', type: 'whiteboard', x: 770, y: 180, rotation: 0, colorVariant: 'lime', scale: 0.8 },
                    { id: 'bookshelf-30', type: 'bookshelf', x: 780, y: 620, rotation: 0, colorVariant: 'library', scale: 0.9 },
                    { id: 'mail_sorter-70', type: 'mail_sorter', x: 120, y: 720, rotation: 0, colorVariant: 'steel', scale: 0.8 },
                    { id: 'printer-71', type: 'printer', x: 560, y: 480, rotation: 0, colorVariant: 'steel', scale: 0.75 },
                    { id: 'filing_cabinet-72', type: 'filing_cabinet', x: 980, y: 740, rotation: 0, colorVariant: 'graphite', scale: 0.8 },
                    { id: 'floor_sign-73', type: 'floor_sign', x: 1040, y: 420, rotation: 0, colorVariant: 'warning', scale: 0.75 },
                    { id: 'ticket_kiosk-137', type: 'ticket_kiosk', x: 1040, y: 170, rotation: 0, colorVariant: 'clean', scale: 0.72 },
                    { id: 'phone_booth-138', type: 'phone_booth', x: 110, y: 360, rotation: 0, colorVariant: 'slate', scale: 0.72 },
                    { id: 'dispatch_board-139', type: 'dispatch_board', x: 560, y: 120, rotation: 0, colorVariant: 'clean', scale: 0.74 },
                    { id: 'copier-240', type: 'copier', x: 620, y: 720, rotation: 0, colorVariant: 'steel', scale: 0.7 },
                    { id: 'shredder-241', type: 'shredder', x: 440, y: 760, rotation: 0, colorVariant: 'graphite', scale: 0.68 },
                    { id: 'mail_cart-242', type: 'mail_cart', x: 160, y: 860, rotation: 0, colorVariant: 'steel', scale: 0.7 },
                    { id: 'laptop-243', type: 'laptop', x: 430, y: 390, rotation: 0, colorVariant: 'steel', scale: 0.68 },
                ],
            },
            {
                id: 'cafeteria',
                roomId: 'room-coffee',
                name: 'Cafeteria',
                x: centerX - 1980,
                y: centerY + 1260,
                width: 1880,
                height: 1360,
                floorPalette: 'terrazzo',
                robotX: 620,
                robotY: 680,
                assets: [
                    { id: 'vending_machine-31', type: 'vending_machine', x: 170, y: 260, rotation: 0, colorVariant: 'cola', scale: 1 },
                    { id: 'coffee_bar-32', type: 'coffee_bar', x: 520, y: 250, rotation: 0, colorVariant: 'copper', scale: 1.2 },
                    { id: 'round_table-33', type: 'round_table', x: 880, y: 690, rotation: 0, colorVariant: 'oak', scale: 1 },
                    { id: 'chair-34', type: 'chair', x: 780, y: 920, rotation: 0, colorVariant: 'ink', scale: 1 },
                    { id: 'chair-35', type: 'chair', x: 1120, y: 640, rotation: 90, colorVariant: 'berry', scale: 1 },
                    { id: 'kitchen_island-74', type: 'kitchen_island', x: 330, y: 620, rotation: 0, colorVariant: 'clean', scale: 0.9 },
                    { id: 'fridge-75', type: 'fridge', x: 1480, y: 240, rotation: 0, colorVariant: 'glass', scale: 0.85 },
                    { id: 'microwave-76', type: 'microwave', x: 720, y: 430, rotation: 0, colorVariant: 'steel', scale: 0.75 },
                    { id: 'water_cooler-77', type: 'water_cooler', x: 1620, y: 720, rotation: 0, colorVariant: 'glass', scale: 0.8 },
                    { id: 'snack_shelf-78', type: 'snack_shelf', x: 1240, y: 830, rotation: 0, colorVariant: 'market', scale: 0.85 },
                    { id: 'recipe_counter-79', type: 'recipe_counter', x: 210, y: 980, rotation: 0, colorVariant: 'mint', scale: 0.85 },
                    { id: 'soda_crate-140', type: 'soda_crate', x: 220, y: 560, rotation: 0, colorVariant: 'market', scale: 0.72 },
                    { id: 'tea_station-141', type: 'tea_station', x: 1030, y: 420, rotation: 0, colorVariant: 'mint', scale: 0.72 },
                    { id: 'snack_table-142', type: 'snack_table', x: 1320, y: 520, rotation: 0, colorVariant: 'market', scale: 0.72 },
                    { id: 'stool-244', type: 'stool', x: 520, y: 820, rotation: 0, colorVariant: 'walnut', scale: 0.72 },
                    { id: 'stool-245', type: 'stool', x: 690, y: 800, rotation: 0, colorVariant: 'walnut', scale: 0.72 },
                    { id: 'stool-246', type: 'stool', x: 460, y: 520, rotation: 0, colorVariant: 'walnut', scale: 0.72 },
                    { id: 'trash_bin-247', type: 'trash_bin', x: 1660, y: 1040, rotation: 0, colorVariant: 'graphite', scale: 0.7 },
                ],
            },
            {
                id: 'lounge',
                roomId: 'room-break',
                name: 'Lounge',
                x: centerX + 160,
                y: centerY + 1260,
                width: 1760,
                height: 1260,
                floorPalette: 'carpet',
                robotX: 520,
                robotY: 800,
                assets: [
                    { id: 'couch-1', type: 'couch', x: 520, y: 720, rotation: 0, colorVariant: 'caramel', scale: 1 },
                    { id: 'couch-2', type: 'couch', x: 880, y: 720, rotation: 0, colorVariant: 'moss', scale: 1 },
                    { id: 'coffee_bar-36', type: 'coffee_bar', x: 200, y: 260, rotation: 0, colorVariant: 'mint', scale: 1 },
                    { id: 'plant-37', type: 'plant', x: 1450, y: 790, rotation: 0, colorVariant: 'blossom', scale: 1 },
                    { id: 'bean_bag-80', type: 'bean_bag', x: 1190, y: 450, rotation: 0, colorVariant: 'berry', scale: 0.9 },
                    { id: 'arcade_cabinet-81', type: 'arcade_cabinet', x: 1380, y: 210, rotation: 0, colorVariant: 'neon', scale: 0.8 },
                    { id: 'trophy_shelf-82', type: 'trophy_shelf', x: 560, y: 230, rotation: 0, colorVariant: 'amber', scale: 0.85 },
                    { id: 'floor_lamp-83', type: 'floor_lamp', x: 1280, y: 780, rotation: 0, colorVariant: 'amber', scale: 0.75 },
                    { id: 'rug-84', type: 'rug', x: 590, y: 640, rotation: 0, colorVariant: 'moss', scale: 0.9 },
                    { id: 'ottoman-143', type: 'ottoman', x: 840, y: 560, rotation: 0, colorVariant: 'moss', scale: 0.74 },
                    { id: 'game_console-144', type: 'game_console', x: 1160, y: 650, rotation: 0, colorVariant: 'neon', scale: 0.72 },
                    { id: 'lounge_chair-145', type: 'lounge_chair', x: 330, y: 660, rotation: 0, colorVariant: 'berry', scale: 0.72 },
                    { id: 'loveseat-248', type: 'loveseat', x: 950, y: 470, rotation: 0, colorVariant: 'harbor', scale: 0.74 },
                    { id: 'side_table-249', type: 'side_table', x: 690, y: 500, rotation: 0, colorVariant: 'oak', scale: 0.72 },
                    { id: 'wall_clock-250', type: 'wall_clock', x: 1540, y: 180, rotation: 0, colorVariant: 'clean', scale: 0.68 },
                    { id: 'planter_box-251', type: 'planter_box', x: 240, y: 950, rotation: 0, colorVariant: 'moss', scale: 0.72 },
                    { id: 'round_table-274', type: 'round_table', x: 760, y: 675, rotation: 0, colorVariant: 'glass', scale: 0.66 },
                    { id: 'tablet_stand-275', type: 'tablet_stand', x: 1190, y: 880, rotation: 0, colorVariant: 'neon', scale: 0.66 },
                    { id: 'bench-276', type: 'bench', x: 500, y: 930, rotation: 0, colorVariant: 'oak', scale: 0.66 },
                ],
            },
            {
                id: 'focus-pods',
                roomId: 'room-pods',
                name: 'Focus Pods',
                x: centerX + 2200,
                y: centerY + 1200,
                width: 1540,
                height: 1260,
                floorPalette: 'slate',
                robotX: 620,
                robotY: 660,
                assets: [
                    { id: 'focus_pod-38', type: 'focus_pod', x: 220, y: 260, rotation: 0, colorVariant: 'quiet', scale: 1 },
                    { id: 'focus_pod-39', type: 'focus_pod', x: 560, y: 260, rotation: 0, colorVariant: 'sunrise', scale: 1 },
                    { id: 'focus_pod-40', type: 'focus_pod', x: 900, y: 260, rotation: 0, colorVariant: 'quiet', scale: 1 },
                    { id: 'plant-41', type: 'plant', x: 1260, y: 760, rotation: 0, colorVariant: 'fern', scale: 1 },
                    { id: 'acoustic_panel-85', type: 'acoustic_panel', x: 220, y: 720, rotation: 0, colorVariant: 'slate', scale: 0.85 },
                    { id: 'floor_lamp-86', type: 'floor_lamp', x: 1130, y: 520, rotation: 0, colorVariant: 'clean', scale: 0.75 },
                    { id: 'divider-87', type: 'divider', x: 690, y: 740, rotation: 0, colorVariant: 'slate', scale: 0.8 },
                    { id: 'charging_dock-88', type: 'charging_dock', x: 1040, y: 860, rotation: 0, colorVariant: 'neon', scale: 0.8 },
                    { id: 'phone_booth-146', type: 'phone_booth', x: 1240, y: 210, rotation: 0, colorVariant: 'slate', scale: 0.72 },
                    { id: 'task_lamp-147', type: 'task_lamp', x: 510, y: 760, rotation: 0, colorVariant: 'clean', scale: 0.72 },
                    { id: 'wall_clock-148', type: 'wall_clock', x: 800, y: 210, rotation: 0, colorVariant: 'clean', scale: 0.72 },
                    { id: 'storage_locker-252', type: 'storage_locker', x: 1060, y: 690, rotation: 0, colorVariant: 'steel', scale: 0.7 },
                    { id: 'planter_box-253', type: 'planter_box', x: 240, y: 920, rotation: 0, colorVariant: 'moss', scale: 0.72 },
                    { id: 'monitor_stand-254', type: 'monitor_stand', x: 520, y: 600, rotation: 0, colorVariant: 'blueprint', scale: 0.68 },
                ],
            },
            {
                id: 'lobby',
                roomId: 'room-lobby',
                name: 'Main Lobby',
                x: centerX - 520,
                y: centerY + 2960,
                width: 1280,
                height: 860,
                floorPalette: 'sand',
                robotX: 500,
                robotY: 430,
                assets: [
                    { id: 'round_table-42', type: 'round_table', x: 220, y: 320, rotation: 0, colorVariant: 'glass', scale: 0.9 },
                    { id: 'plant-43', type: 'plant', x: 920, y: 420, rotation: 0, colorVariant: 'fern', scale: 1 },
                    { id: 'bookshelf-44', type: 'bookshelf', x: 820, y: 120, rotation: 0, colorVariant: 'library', scale: 0.8 },
                    { id: 'reception_counter-89', type: 'reception_counter', x: 380, y: 520, rotation: 0, colorVariant: 'walnut', scale: 0.85 },
                    { id: 'floor_sign-90', type: 'floor_sign', x: 980, y: 160, rotation: 0, colorVariant: 'warning', scale: 0.75 },
                    { id: 'package_station-91', type: 'package_station', x: 80, y: 570, rotation: 0, colorVariant: 'cardboard', scale: 0.75 },
                    { id: 'charging_dock-92', type: 'charging_dock', x: 830, y: 620, rotation: 0, colorVariant: 'neon', scale: 0.75 },
                    { id: 'wall_monitor-93', type: 'wall_monitor', x: 250, y: 110, rotation: 0, colorVariant: 'blueprint', scale: 0.75 },
                    { id: 'coat_rack-149', type: 'coat_rack', x: 1090, y: 560, rotation: 0, colorVariant: 'walnut', scale: 0.72 },
                    { id: 'bench-150', type: 'bench', x: 490, y: 250, rotation: 0, colorVariant: 'oak', scale: 0.72 },
                    { id: 'room_sign-151', type: 'room_sign', x: 80, y: 160, rotation: 0, colorVariant: 'clean', scale: 0.72 },
                    { id: 'loveseat-255', type: 'loveseat', x: 640, y: 360, rotation: 0, colorVariant: 'moss', scale: 0.68 },
                    { id: 'planter_box-256', type: 'planter_box', x: 920, y: 640, rotation: 0, colorVariant: 'moss', scale: 0.68 },
                    { id: 'tablet_stand-257', type: 'tablet_stand', x: 280, y: 510, rotation: 0, colorVariant: 'neon', scale: 0.68 },
                ],
            },
        ];
    return {
        schemaVersion: OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION,
        selectedSpaceId: 'planning-hub',
        selectedAssetId: '',
        rotationStep: 15,
        gridEnabled: true,
        nextAssetId: 340,
        spaces: officeDraftFitSpacesToMapBounds(officeDraftPolishDefaultLayoutSpaces(officeDraftCompactDefaultLayoutSpaces(spaces))),
    };
}

function officeDraftStoredLayoutIsLegacy(snapshotRaw) {
    if (!snapshotRaw || typeof snapshotRaw !== 'object') return false;
    if (Number(snapshotRaw.schemaVersion) < OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION) return true;
    if (Number(snapshotRaw.schemaVersion) >= OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION) return false;
    const spaces = Array.isArray(snapshotRaw.spaces) ? snapshotRaw.spaces : [];
    if (!spaces.length) return true;
    return spaces.length <= 1 && spaces.every((space) => !safeString(space?.roomId));
}

function officeDraftFitSpacesToMapBounds(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    if (!spaces.length) return spaces;
    const margin = 360;
    const bounds = spaces.reduce((acc, space) => {
        const x = Number(space?.x) || 0;
        const y = Number(space?.y) || 0;
        const width = Math.max(320, Number(space?.width) || 0);
        const height = Math.max(240, Number(space?.height) || 0);
        acc.minX = Math.min(acc.minX, x);
        acc.minY = Math.min(acc.minY, y);
        acc.maxX = Math.max(acc.maxX, x + width);
        acc.maxY = Math.max(acc.maxY, y + height);
        return acc;
    }, {
        minX: Number.POSITIVE_INFINITY,
        minY: Number.POSITIVE_INFINITY,
        maxX: Number.NEGATIVE_INFINITY,
        maxY: Number.NEGATIVE_INFINITY,
    });
    if (!Number.isFinite(bounds.minX) || !Number.isFinite(bounds.minY)) return spaces;
    const needsFit = bounds.minX < margin
        || bounds.minY < margin
        || bounds.maxX > (OFFICE_DRAFT_MAP_SIZE - margin)
        || bounds.maxY > (OFFICE_DRAFT_MAP_SIZE - margin);
    if (!needsFit) return spaces;
    const centerX = bounds.minX + ((bounds.maxX - bounds.minX) / 2);
    const centerY = bounds.minY + ((bounds.maxY - bounds.minY) / 2);
    const offsetX = (OFFICE_DRAFT_MAP_SIZE / 2) - centerX;
    const offsetY = (OFFICE_DRAFT_MAP_SIZE / 2) - centerY;
    return spaces.map((space) => {
        const width = Math.max(320, Number(space?.width) || 0);
        const height = Math.max(240, Number(space?.height) || 0);
        const maxX = Math.max(margin, OFFICE_DRAFT_MAP_SIZE - margin - width);
        const maxY = Math.max(margin, OFFICE_DRAFT_MAP_SIZE - margin - height);
        return {
            ...space,
            x: Math.round(Math.max(margin, Math.min(maxX, (Number(space?.x) || 0) + offsetX))),
            y: Math.round(Math.max(margin, Math.min(maxY, (Number(space?.y) || 0) + offsetY))),
        };
    });
}

function officeEnsureDraftMapState() {
    if (officeDraftMapState) return officeDraftMapState;
    const defaultLayout = officeDraftDefaultLayoutSnapshot();
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
        agentFocusInitialized: false,
        userSelectedSpace: false,
        minimapMinimized: false,
        minimapPointerId: null,
        minimapDragStartX: 0,
        minimapDragStartY: 0,
        minimapOffsetX: 0,
        minimapOffsetY: 0,
        minimapDragOffsetX: 0,
        minimapDragOffsetY: 0,
        minimapLocked: true,
        minimapPointerMode: 'camera',
        minimapSize: OFFICE_DRAFT_MINIMAP_SIZE,
        minimapResizePointerId: null,
        minimapResizeStartX: 0,
        minimapResizeStartY: 0,
        minimapResizeStartSize: OFFICE_DRAFT_MINIMAP_SIZE,
        autosaveEnabled: officeDraftLoadAutosavePreference(),
        editorOpen: false,
        rosterOpen: false,
        expandedRosterAgentId: '',
        agentChatOpen: false,
        agentChatAgentId: '',
        agentChatDraftById: {},
        catalogSearch: '',
        catalogCategory: 'all',
        selectedSpaceId: defaultLayout.selectedSpaceId,
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
        hallwayNetworkCache: null,
        missionAgentLayerDirty: false,
        agentRoutePlansRemaining: null,
        agentRoutePlanDeferred: false,
        agentRoutePlanTimer: 0,
        nextAssetId: defaultLayout.nextAssetId,
        undoStack: [],
        spaces: officeDraftCloneLayoutPayload(defaultLayout.spaces) || [],
    };
    const storedLayout = officeDraftLoadStoredLayout();
    if (!officeDraftStoredLayoutIsLegacy(storedLayout)) {
        officeDraftApplySnapshot(storedLayout, officeDraftMapState, { persist: false, resetUndo: true });
    } else {
        officeDraftPersistLayout(officeDraftMapState, { force: true });
    }
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

function officeDraftInitialFocusSpace(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    const selectedSpace = spaces.find((space) => safeString(space?.id) === safeString(state.selectedSpaceId))
        || spaces[0]
        || null;
    if (!spaces.length || typeof officeDraftAgentAssignmentMap !== 'function') return selectedSpace;
    const assignments = officeDraftAgentAssignmentMap(state);
    const selectedAgents = assignments.get(safeString(selectedSpace?.id)) || [];
    if (selectedAgents.length) return selectedSpace;
    let bestSpace = selectedSpace;
    let bestScore = 0;
    spaces.forEach((space) => {
        const spaceId = safeString(space?.id);
        const roomId = officeDraftNormalizeRoomId(space?.roomId, spaceId);
        const agents = assignments.get(spaceId) || [];
        if (!agents.length) return;
        const score = agents.reduce((total, agent) => {
            const agentState = safeString(agent?.state);
            let value = 1;
            if (safeString(agent?.taskId)) value += 8;
            if (agentState === 'working' || agentState === 'walking') value += 5;
            if (agentState === 'break') value += 2;
            if (safeString(agent?.id) === safeString(officeState?.selectedAgentId)) value += 20;
            return total + value;
        }, roomId === 'room-lobby' ? 0 : 2);
        if (score > bestScore) {
            bestScore = score;
            bestSpace = space;
        }
    });
    return bestSpace || selectedSpace;
}

function officeDraftContentBounds(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces.filter(Boolean) : [];
    if (!spaces.length) return null;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    spaces.forEach((space) => {
        const x = Number(space.x) || 0;
        const y = Number(space.y) || 0;
        const w = Number(space.width) || 0;
        const h = Number(space.height) || 0;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + w);
        maxY = Math.max(maxY, y + h);
    });
    if (!Number.isFinite(minX) || !Number.isFinite(maxX)) return null;
    return {
        minX, minY, maxX, maxY,
        width: maxX - minX,
        height: maxY - minY,
        cx: (minX + maxX) / 2,
        cy: (minY + maxY) / 2,
    };
}

function officeCenterDraftMapViewport() {
    const state = officeEnsureDraftMapState();
    const viewport = officeDraftMapViewportRect();
    const focusSpace = officeDraftInitialFocusSpace(state);
    if (focusSpace && !state.initialized && safeString(focusSpace.id) !== safeString(state.selectedSpaceId)) {
        state.selectedSpaceId = safeString(focusSpace.id);
    }
    // On the first viewport setup, zoom the WHOLE office to fit the screen so
    // the user sees the full floor plan instead of opening at a fixed zoom that
    // overflows the viewport. (Fix: office rendered ~2x too large.)
    if (!state.initialized) {
        const bounds = officeDraftContentBounds(state);
        if (bounds && bounds.width > 0 && bounds.height > 0) {
            const pad = 420;
            const fitZoom = Math.min(
                viewport.width / (bounds.width + pad),
                viewport.height / (bounds.height + pad),
            );
            // Clamp to a LEGIBLE floor: below ~0.5 the furniture outlines render
            // sub-pixel and the whole office looks broken/blurry. We'd rather show
            // fewer rooms crisply (and let the user pan/zoom) than fit everything
            // illegibly. The legible floor wins over a tiny fit-everything zoom.
            const OFFICE_DRAFT_LEGIBLE_MIN_ZOOM = 0.5;
            state.zoom = Math.max(OFFICE_DRAFT_LEGIBLE_MIN_ZOOM, Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, fitZoom));
            const fitClamped = officeClampDraftMapPan(
                bounds.cx - (viewport.width / (2 * state.zoom)),
                bounds.cy - (viewport.height / (2 * state.zoom)),
                state.zoom,
            );
            state.panX = fitClamped.panX;
            state.panY = fitClamped.panY;
            return;
        }
    }
    const focusX = focusSpace
        ? (Number(focusSpace.x) || 0) + ((Number(focusSpace.width) || 0) / 2)
        : (OFFICE_DRAFT_MAP_SIZE / 2);
    const focusY = focusSpace
        ? (Number(focusSpace.y) || 0) + ((Number(focusSpace.height) || 0) / 2)
        : (OFFICE_DRAFT_MAP_SIZE / 2);
    const clamped = officeClampDraftMapPan(
        focusX - (viewport.width / (2 * state.zoom)),
        focusY - (viewport.height / (2 * state.zoom)),
        state.zoom,
    );
    state.panX = clamped.panX;
    state.panY = clamped.panY;
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
    const renderScale = scale * (Number(OFFICE_DRAFT_ASSET_RENDER_SCALE) || 1);
    return {
        width: Math.round(descriptor.width * renderScale),
        height: Math.round(descriptor.height * renderScale),
        scale: renderScale,
        layoutScale: scale,
    };
}

function officeDraftAssetDefaultColorVariant(assetType) {
    const type = safeString(assetType) || 'couch';
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || OFFICE_DRAFT_ASSET_LIBRARY.couch;
    const colorways = OFFICE_DRAFT_ASSET_COLORWAYS[type]
        || OFFICE_DRAFT_ASSET_COLORWAYS[safeString(descriptor?.colorGroup)]
        || OFFICE_DRAFT_ASSET_COLORWAYS.couch
        || {};
    const preferred = safeString(descriptor?.defaultColorVariant);
    if (preferred && colorways[preferred]) return preferred;
    const first = Object.keys(colorways)[0];
    return first || 'caramel';
}

function officeDraftAssetColorway(assetType, colorId) {
    const type = safeString(assetType) || 'couch';
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || OFFICE_DRAFT_ASSET_LIBRARY.couch;
    const colorways = OFFICE_DRAFT_ASSET_COLORWAYS[type]
        || OFFICE_DRAFT_ASSET_COLORWAYS[safeString(descriptor?.colorGroup)]
        || OFFICE_DRAFT_ASSET_COLORWAYS.couch;
    const fallbackId = officeDraftAssetDefaultColorVariant(type);
    return colorways[safeString(colorId)] || colorways[fallbackId] || colorways.caramel || Object.values(colorways)[0];
}

function officeDraftNormalizeRoomId(roomIdRaw, fallbackRaw = '') {
    const roomId = safeString(roomIdRaw);
    if (roomId && officeRoomById(roomId)) return roomId;
    const fallback = safeString(fallbackRaw);
    if (fallback && officeRoomById(fallback)) return fallback;
    return 'room-lobby';
}

function officeDraftLayoutSnapshot(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    return {
        schemaVersion: OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION,
        selectedSpaceId: safeString(state.selectedSpaceId),
        selectedAssetId: safeString(state.selectedAssetId),
        rotationStep: officeDraftRotationOptions().includes(Number(state.rotationStep)) ? Number(state.rotationStep) : 15,
        gridEnabled: state.gridEnabled !== false,
        nextAssetId: Math.max(1, Number(state.nextAssetId) || 1),
        spaces: (Array.isArray(state.spaces) ? state.spaces : []).map((space) => ({
            id: safeString(space?.id),
            roomId: officeDraftNormalizeRoomId(space?.roomId, space?.id),
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
                colorVariant: safeString(asset?.colorVariant) || officeDraftAssetDefaultColorVariant(asset?.type),
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
    const normalizedSpaces = snapshotRaw.spaces.map((space, spaceIndex) => {
        const spaceId = safeString(space?.id) || `space-${spaceIndex + 1}`;
        return {
            id: spaceId,
            roomId: officeDraftNormalizeRoomId(space?.roomId, spaceId),
            name: safeString(space?.name) || 'Space',
            x: Math.round(Number(space?.x) || 0),
            y: Math.round(Number(space?.y) || 0),
            width: Math.max(320, Math.round(Number(space?.width) || 0)),
            height: Math.max(240, Math.round(Number(space?.height) || 0)),
            floorPalette: OFFICE_DRAFT_ROOM_FLOOR_PALETTES[safeString(space?.floorPalette)] ? safeString(space.floorPalette) : 'tan',
            robotX: Math.round(Number(space?.robotX) || 0),
            robotY: Math.round(Number(space?.robotY) || 0),
            assets: (Array.isArray(space?.assets) ? space.assets : []).map((asset, assetIndex) => {
                const type = OFFICE_DRAFT_ASSET_LIBRARY[safeString(asset?.type)] ? safeString(asset.type) : 'couch';
                return {
                    id: safeString(asset?.id) || `asset-${spaceIndex + 1}-${assetIndex + 1}`,
                    type,
                    x: Math.round(Number(asset?.x) || 0),
                    y: Math.round(Number(asset?.y) || 0),
                    rotation: officeDraftNormalizeRotation(asset?.rotation),
                    colorVariant: safeString(asset?.colorVariant) || officeDraftAssetDefaultColorVariant(type),
                    scale: officeDraftClampAssetScale(asset?.scale),
                };
            }),
        };
    });
    const boundedSpaces = officeDraftFitSpacesToMapBounds(normalizedSpaces);
    state.spaces = boundedSpaces;
    state.nextAssetId = Math.max(1, Number(snapshotRaw.nextAssetId) || 1);
    state.rotationStep = officeDraftRotationOptions().includes(Number(snapshotRaw.rotationStep)) ? Number(snapshotRaw.rotationStep) : 15;
    state.gridEnabled = snapshotRaw.gridEnabled !== false;
    state.selectedSpaceId = boundedSpaces.some((space) => safeString(space.id) === safeString(snapshotRaw.selectedSpaceId))
        ? safeString(snapshotRaw.selectedSpaceId)
        : safeString(boundedSpaces[0]?.id);
    const assetExists = boundedSpaces.some((space) => Array.isArray(space.assets) && space.assets.some((asset) => safeString(asset.id) === safeString(snapshotRaw.selectedAssetId)));
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
    couch.dataset.officeDraftAssetType = 'couch';
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
    couchShadow.style.height = scaled(18);
    couchShadow.style.borderRadius = '999px';
    couchShadow.style.background = 'rgba(3, 8, 16, 0.18)';
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

function officeDraftAppendAssetPart(parent, styles = {}, text = '') {
    const part = document.createElement('div');
    part.style.boxSizing = 'border-box';
    Object.entries(styles).forEach(([key, value]) => {
        part.style[key] = value;
    });
    if (text) {
        part.textContent = text;
    }
    parent.appendChild(part);
    return part;
}

function officeDraftAddAssetSurfaceDetail(root, scaled, baseWidthRaw, baseHeightRaw, color = {}) {
    if (!(root instanceof HTMLElement) || typeof scaled !== 'function') return;
    const baseWidth = Math.max(48, Number(baseWidthRaw) || 0);
    const baseHeight = Math.max(48, Number(baseHeightRaw) || 0);
    const accent = color.accent || color.arm || 'rgba(214, 236, 255, 0.62)';
    const line = color.line || color.seam || 'rgba(9, 18, 31, 0.34)';
    officeDraftAppendAssetPart(root, {
        position: 'absolute',
        left: scaled(baseWidth * 0.12),
        top: scaled(baseHeight * 0.08),
        width: scaled(Math.max(26, baseWidth * 0.26)),
        height: scaled(Math.max(4, baseHeight * 0.045)),
        borderRadius: '999px',
        background: 'rgba(255,255,255,0.18)',
        pointerEvents: 'none',
    });
    officeDraftAppendAssetPart(root, {
        position: 'absolute',
        right: scaled(baseWidth * 0.1),
        bottom: scaled(baseHeight * 0.09),
        width: scaled(Math.max(24, baseWidth * 0.2)),
        height: scaled(Math.max(4, baseHeight * 0.04)),
        borderRadius: '999px',
        background: line,
        opacity: '0.24',
        pointerEvents: 'none',
    });
    [0.24, 0.5, 0.76].forEach((leftRatio, index) => {
        officeDraftAppendAssetPart(root, {
            position: 'absolute',
            left: scaled(baseWidth * leftRatio),
            top: scaled(baseHeight * (0.16 + (index % 2) * 0.58)),
            width: scaled(Math.max(5, baseWidth * 0.025)),
            height: scaled(Math.max(5, baseWidth * 0.025)),
            borderRadius: '999px',
            background: index === 1 ? accent : line,
            opacity: index === 1 ? '0.46' : '0.24',
            pointerEvents: 'none',
        });
    });
}

function officeDraftAddAssetPixelDetail(root, scaled, baseWidthRaw, baseHeightRaw, color = {}, typeRaw = '', shapeRaw = '') {
    if (!(root instanceof HTMLElement) || typeof scaled !== 'function') return;
    const baseWidth = Math.max(48, Number(baseWidthRaw) || 0);
    const baseHeight = Math.max(48, Number(baseHeightRaw) || 0);
    const type = safeString(typeRaw);
    const shape = safeString(shapeRaw);
    const accent = color.accent || color.arm || 'rgba(214, 236, 255, 0.72)';
    const line = color.line || color.seam || 'rgba(7, 13, 24, 0.36)';
    const surface = color.surface || color.seat || color.body || 'rgba(120, 147, 184, 0.92)';
    const body = color.body || color.back || surface;
    const part = (styles = {}) => officeDraftAppendAssetPart(root, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    });
    part({
        left: scaled(baseWidth * 0.06),
        top: scaled(baseHeight * 0.12),
        width: scaled(Math.max(4, baseWidth * 0.018)),
        height: scaled(Math.max(18, baseHeight * 0.56)),
        borderRadius: '999px',
        background: line,
        opacity: '0.18',
    });
    part({
        right: scaled(baseWidth * 0.06),
        top: scaled(baseHeight * 0.16),
        width: scaled(Math.max(4, baseWidth * 0.018)),
        height: scaled(Math.max(18, baseHeight * 0.42)),
        borderRadius: '999px',
        background: 'rgba(255,255,255,0.16)',
        opacity: '0.82',
    });
    part({
        left: scaled(baseWidth * 0.18),
        top: scaled(baseHeight * 0.08),
        width: scaled(Math.max(32, baseWidth * 0.34)),
        height: scaled(Math.max(4, baseHeight * 0.035)),
        borderRadius: '999px',
        background: 'rgba(255,255,255,0.22)',
        opacity: '0.72',
    });

    const isScreenLike = shape === 'screen' || shape === 'board' || ['workstation', 'dual_monitor', 'code_terminal', 'research_terminal', 'data_wall', 'wall_monitor', 'monitor_stand', 'laptop', 'tablet_stand'].includes(type);
    const isSeating = ['chair', 'meeting_chair', 'lounge_chair', 'stool', 'couch', 'loveseat', 'bench', 'ottoman', 'bean_bag'].includes(type) || shape === 'soft_seat';
    const isSurface = ['desk', 'round_table', 'conference_table', 'coffee_table', 'kitchen_island'].includes(type) || shape === 'table' || shape === 'tilt_table' || shape === 'counter';
    const isStorage = ['bookshelf', 'server_rack', 'storage_locker', 'filing_cabinet', 'printer', 'copier', 'mail_sorter', 'mail_cart', 'package_station'].includes(type) || shape === 'cabinet' || shape === 'shelf';
    const isUtility = ['vending_machine', 'coffee_bar', 'ticket_kiosk', 'power_panel', 'charging_dock', 'network_switch', 'router_node', 'firewall_box', 'sound_mixer', 'testing_rig', 'game_console'].includes(type) || shape === 'appliance' || shape === 'machine' || shape === 'console';

    if (isScreenLike) {
        [0.28, 0.42, 0.56].forEach((topRatio, index) => {
            part({
                left: scaled(baseWidth * 0.24),
                top: scaled(baseHeight * topRatio),
                width: scaled(baseWidth * (index === 1 ? 0.36 : 0.26)),
                height: scaled(Math.max(4, baseHeight * 0.025)),
                borderRadius: '999px',
                background: index === 1 ? accent : surface,
                opacity: index === 1 ? '0.9' : '0.58',
                boxShadow: index === 1 ? `0 0 ${scaled(8)} ${accent}` : 'none',
            });
        });
        return;
    }

    if (isSeating) {
        [0.28, 0.5, 0.72].forEach((leftRatio, index) => {
            part({
                left: scaled(baseWidth * leftRatio),
                top: scaled(baseHeight * 0.5),
                width: scaled(Math.max(5, baseWidth * 0.026)),
                height: scaled(Math.max(18, baseHeight * 0.18)),
                borderRadius: '999px',
                background: line,
                opacity: index === 1 ? '0.32' : '0.22',
            });
        });
        part({
            left: scaled(baseWidth * 0.22),
            top: scaled(baseHeight * 0.28),
            width: scaled(baseWidth * 0.18),
            height: scaled(baseHeight * 0.12),
            borderRadius: scaled(10),
            background: accent,
            opacity: '0.48',
        });
        return;
    }

    if (isSurface) {
        [0.22, 0.42, 0.62].forEach((topRatio, index) => {
            part({
                left: scaled(baseWidth * (0.2 + index * 0.08)),
                top: scaled(baseHeight * topRatio),
                width: scaled(baseWidth * 0.32),
                height: scaled(Math.max(4, baseHeight * 0.025)),
                borderRadius: '999px',
                background: index === 1 ? accent : line,
                opacity: index === 1 ? '0.38' : '0.22',
            });
        });
        part({
            right: scaled(baseWidth * 0.18),
            top: scaled(baseHeight * 0.24),
            width: scaled(baseWidth * 0.12),
            height: scaled(baseHeight * 0.12),
            borderRadius: scaled(6),
            background: body,
            opacity: '0.62',
        });
        return;
    }

    if (isStorage || isUtility) {
        [0.24, 0.48, 0.72].forEach((topRatio, index) => {
            part({
                right: scaled(baseWidth * 0.18),
                top: scaled(baseHeight * topRatio),
                width: scaled(Math.max(8, baseWidth * 0.06)),
                height: scaled(Math.max(5, baseHeight * 0.035)),
                borderRadius: '999px',
                background: index === 1 ? accent : line,
                opacity: index === 1 ? '0.88' : '0.34',
                boxShadow: index === 1 ? `0 0 ${scaled(7)} ${accent}` : 'none',
            });
        });
        part({
            left: scaled(baseWidth * 0.18),
            bottom: scaled(baseHeight * 0.16),
            width: scaled(baseWidth * 0.24),
            height: scaled(Math.max(5, baseHeight * 0.035)),
            borderRadius: '999px',
            background: line,
            opacity: '0.38',
        });
    }
}

function officeDraftAddAssetQualityOverlay(root, asset, state) {
    if (!(root instanceof HTMLElement) || !asset) return root;
    if (root.dataset.officeAssetQualityDetail === '16px') return root;
    const type = safeString(asset?.type) || 'desk';
    const descriptor = officeDraftAssetDimensions(type, asset?.scale);
    const assetInfo = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(assetInfo.shape);
    if (type === 'rug' || shape === 'rug') {
        root.dataset.officeAssetQualityDetail = '16px';
        return root;
    }
    const color = officeDraftAssetColorway(type, asset?.colorVariant) || {};
    const lightweight = root.dataset.officeDraftAssetLightweight === '1';
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const richDetail = !lightweight && zoom > 0.34 && !asset?.preview;
    const body = color.body || color.back || color.swatch || 'rgba(77,101,136,0.94)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(169,211,255,0.92)';
    const line = color.line || color.seam || 'rgba(8,15,27,0.44)';
    const highlight = 'rgba(255,255,255,0.24)';
    const layer = document.createElement('div');
    layer.dataset.officeAssetQualityOverlay = '1';
    layer.style.position = 'absolute';
    layer.style.inset = '0';
    layer.style.pointerEvents = 'none';
    layer.style.zIndex = '40';
    layer.style.overflow = 'hidden';
    layer.style.borderRadius = 'inherit';
    layer.style.mixBlendMode = 'normal';
    const part = (styles = {}, text = '') => officeDraftAppendAssetPart(layer, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    }, text);
    const dot = (left, top, size = 4, colorRaw = accent) => part({
        left: `${left}%`,
        top: `${top}%`,
        width: `${size}px`,
        height: `${size}px`,
        borderRadius: '2px',
        background: colorRaw,
        boxShadow: `0 0 ${Math.max(4, size)}px ${colorRaw}`,
    });
    part({ left: '7%', top: '8%', width: '26%', height: '4%', borderRadius: '999px', background: highlight, opacity: richDetail ? '0.86' : '0.45' });
    part({ right: '8%', bottom: '9%', width: '24%', height: '4%', borderRadius: '999px', background: line, opacity: '0.22' });
    if (!richDetail) {
        root.appendChild(layer);
        root.dataset.officeAssetQualityDetail = '16px';
        return root;
    }

    const isSeat = ['chair', 'meeting_chair', 'lounge_chair', 'stool', 'couch', 'loveseat', 'bench', 'ottoman', 'bean_bag'].includes(type)
        || shape === 'soft_seat';
    const isScreen = shape === 'screen' || shape === 'console' || ['workstation', 'dual_monitor', 'code_terminal', 'research_terminal', 'data_wall', 'wall_monitor', 'monitor_stand', 'laptop', 'tablet_stand', 'security_console', 'server_console', 'sound_mixer'].includes(type);
    const isTable = shape === 'table' || shape === 'tilt_table' || shape === 'counter' || shape === 'bench' || ['desk', 'round_table', 'conference_table', 'podcast_desk', 'kitchen_island', 'recipe_counter'].includes(type);
    const isStorage = shape === 'cabinet' || shape === 'shelf' || ['bookshelf', 'server_rack', 'storage_locker', 'filing_cabinet', 'mail_sorter', 'mail_cart', 'package_station', 'printer', 'copier'].includes(type);
    const isBoard = shape === 'board' || shape === 'panel' || ['whiteboard', 'kanban_board', 'pinboard', 'sticky_note_wall', 'dispatch_board', 'green_screen', 'acoustic_panel', 'divider'].includes(type);
    const isPlant = ['plant', 'tall_plant', 'planter_box'].includes(type);
    const isUtility = shape === 'appliance' || shape === 'machine' || shape === 'dock' || shape === 'node' || shape === 'box' || ['vending_machine', 'coffee_bar', 'ticket_kiosk', 'charging_dock', 'network_switch', 'router_node', 'firewall_box', 'testing_rig', 'game_console', 'arcade_cabinet'].includes(type);

    if (type === 'vending_machine') {
        part({ left: '21%', top: '15%', width: '30%', height: '34%', borderRadius: '7px', background: 'linear-gradient(180deg, rgba(244,251,255,0.56), rgba(78,124,170,0.36))', border: '2px solid rgba(255,255,255,0.34)' });
        [21, 30, 39].forEach((top, row) => {
            [28, 39].forEach((left, col) => dot(left + (col * 0.8), top, 5, row === 1 ? accent : 'rgba(255,255,255,0.72)'));
        });
        part({ right: '20%', top: '22%', width: '10%', height: '28%', borderRadius: '6px', background: 'rgba(8,14,24,0.52)' });
        dot(73, 31, 6, accent);
        part({ left: '24%', bottom: '20%', width: '38%', height: '12%', borderRadius: '6px', background: accent, color: 'rgba(105,23,35,0.94)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `${Math.max(8, Math.round(Number(descriptor.width || 0) * 0.06))}px`, fontWeight: '900', letterSpacing: '0' }, 'Coke');
    } else if (type === 'data_wall') {
        [18, 41, 64].forEach((left, index) => {
            part({ left: `${left}%`, top: '22%', width: '18%', height: '46%', borderRadius: '8px', background: 'rgba(4,10,20,0.72)', border: `1px solid ${line}` });
            [33, 45, 57].forEach((top, row) => {
                part({ left: `${left + 3}%`, top: `${top}%`, width: `${row === 1 ? 12 : 8}%`, height: '3%', borderRadius: '999px', background: row === index % 3 ? accent : surface, opacity: row === index % 3 ? '0.9' : '0.5' });
            });
        });
        [24, 47, 70].forEach((left, index) => dot(left, 72, index === 1 ? 6 : 4, index === 1 ? accent : highlight));
    } else if (type === 'map_table') {
        part({ left: '18%', top: '24%', width: '62%', height: '42%', borderRadius: '14px', background: 'rgba(214,236,255,0.16)', border: `1px solid ${highlight}` });
        [34, 45, 56].forEach((top, index) => {
            part({ left: `${24 + (index * 5)}%`, top: `${top}%`, width: `${36 - (index * 4)}%`, height: '3%', borderRadius: '999px', background: index === 1 ? accent : line, opacity: index === 1 ? '0.74' : '0.42' });
        });
        dot(31, 38, 6, accent);
        dot(62, 54, 5, 'rgba(255,226,128,0.92)');
        dot(52, 44, 4, highlight);
    } else if (type === 'microscope') {
        part({ left: '46%', top: '18%', width: '10%', height: '48%', borderRadius: '999px', background: body, transform: 'rotate(18deg)' });
        part({ left: '30%', top: '26%', width: '32%', height: '18%', borderRadius: '999px', background: surface, border: `1px solid ${highlight}` });
        part({ left: '38%', top: '48%', width: '30%', height: '9%', borderRadius: '999px', background: accent });
        part({ left: '23%', bottom: '18%', width: '56%', height: '10%', borderRadius: '999px', background: line, opacity: '0.55' });
        dot(67, 27, 5, accent);
    } else if (type === 'conference_table') {
        [24, 40, 56, 72].forEach((left, index) => {
            part({ left: `${left}%`, top: `${32 + ((index % 2) * 18)}%`, width: '9%', height: '10%', borderRadius: '5px', background: index % 2 ? accent : highlight, opacity: '0.72' });
        });
        part({ left: '26%', top: '48%', width: '48%', height: '5%', borderRadius: '999px', background: line, opacity: '0.26' });
        part({ left: '39%', top: '27%', width: '22%', height: '8%', borderRadius: '999px', background: accent, opacity: '0.42' });
    } else if (type === 'arcade_cabinet') {
        part({ left: '28%', top: '17%', width: '43%', height: '25%', borderRadius: '7px', background: 'rgba(5,10,18,0.88)', border: `1px solid ${line}` });
        part({ left: '35%', top: '27%', width: '28%', height: '5%', borderRadius: '999px', background: accent, boxShadow: `0 0 10px ${accent}` });
        part({ left: '30%', top: '53%', width: '40%', height: '17%', borderRadius: '8px', background: surface });
        [39, 50, 61].forEach((left, index) => dot(left, 60, index === 1 ? 6 : 4, index === 1 ? accent : 'rgba(255,231,122,0.9)'));
    } else if (type === 'focus_pod') {
        part({ left: '19%', top: '12%', width: '62%', height: '64%', borderRadius: '22px 22px 18px 18px', background: 'rgba(215,235,255,0.18)', border: `2px solid ${highlight}` });
        part({ left: '31%', top: '31%', width: '38%', height: '12%', borderRadius: '999px', background: accent, opacity: '0.72' });
        part({ left: '28%', bottom: '19%', width: '44%', height: '11%', borderRadius: '999px', background: line, opacity: '0.32' });
    } else if (isScreen) {
        [27, 37, 47, 57].forEach((top, index) => {
            part({ left: `${24 + (index % 2) * 5}%`, top: `${top}%`, width: `${index === 1 ? 38 : 28}%`, height: '3.5%', borderRadius: '999px', background: index === 1 ? accent : surface, opacity: index === 1 ? '0.88' : '0.52' });
        });
        [68, 75, 82].forEach((left, index) => dot(left, 23 + (index * 9), 5, index === 1 ? accent : 'rgba(255,255,255,0.5)'));
        if (['workstation', 'dual_monitor', 'laptop', 'code_terminal', 'research_terminal'].includes(type)) {
            part({ left: '24%', bottom: '16%', width: '42%', height: '5%', borderRadius: '999px', background: line, opacity: '0.4' });
            [27, 34, 41, 48, 55].forEach((left) => dot(left, 78, 3, highlight));
        }
    } else if (isSeat) {
        [26, 50, 74].forEach((left, index) => {
            part({ left: `${left}%`, top: '50%', width: '2.8%', height: '22%', borderRadius: '999px', background: line, opacity: index === 1 ? '0.4' : '0.26' });
        });
        part({ left: '20%', top: '28%', width: '20%', height: '11%', borderRadius: '10px', background: accent, opacity: '0.42' });
        part({ right: '18%', top: '31%', width: '16%', height: '9%', borderRadius: '9px', background: highlight, opacity: '0.35' });
    } else if (isTable) {
        [20, 36, 52, 68].forEach((left, index) => {
            part({ left: `${left}%`, top: `${32 + (index % 2) * 13}%`, width: '16%', height: '3%', borderRadius: '999px', background: index === 1 ? accent : line, opacity: index === 1 ? '0.34' : '0.2' });
        });
        part({ right: '18%', top: '23%', width: '13%', height: '12%', borderRadius: '7px', background: 'rgba(255,255,255,0.14)', border: `1px solid ${highlight}` });
        dot(74, 52, 4, accent);
    } else if (isStorage) {
        [23, 40, 57, 74].forEach((top, index) => {
            part({ left: '18%', top: `${top}%`, width: '60%', height: '3.4%', borderRadius: '999px', background: index % 2 ? accent : line, opacity: index % 2 ? '0.72' : '0.28' });
        });
        [30, 44, 58, 72].forEach((left, index) => {
            part({ left: `${left}%`, top: `${32 + (index % 2) * 20}%`, width: '4.8%', height: '13%', borderRadius: '2px', background: index % 2 ? surface : accent, opacity: '0.88' });
        });
        dot(82, 20, 5, accent);
    } else if (isBoard) {
        [24, 40, 56].forEach((left, index) => {
            part({ left: `${left}%`, top: '22%', width: '11%', height: '15%', borderRadius: '3px', background: index === 1 ? accent : 'rgba(255,236,151,0.9)', transform: `rotate(${index - 1}deg)` });
        });
        [35, 51, 67].forEach((top, index) => {
            part({ left: '24%', top: `${top}%`, width: `${index === 1 ? 50 : 34}%`, height: '3%', borderRadius: '999px', background: index === 0 ? accent : line, opacity: index === 0 ? '0.82' : '0.46' });
        });
    } else if (isPlant) {
        [22, 36, 50, 64].forEach((left, index) => {
            part({ left: `${left}%`, top: `${20 + (index % 2) * 10}%`, width: '15%', height: '38%', borderRadius: '70% 30% 70% 30%', background: index % 2 ? surface : body, transform: `rotate(${index % 2 ? 20 : -24}deg)`, opacity: '0.92' });
        });
        part({ left: '20%', bottom: '13%', width: '60%', height: '13%', borderRadius: '8px', background: accent, boxShadow: 'inset 0 -4px rgba(0,0,0,0.13)' });
    } else if (isUtility) {
        part({ left: '18%', top: '25%', width: '54%', height: '28%', borderRadius: '9px', background: surface, border: `2px solid ${body}` });
        [28, 44, 60].forEach((left, index) => dot(left, 39, index === 1 ? 6 : 4, index === 1 ? accent : highlight));
        part({ left: '25%', top: '59%', width: '42%', height: '4%', borderRadius: '999px', background: line, opacity: '0.34' });
        part({ right: '17%', top: '34%', width: '9%', height: '9%', borderRadius: '999px', background: accent, boxShadow: `0 0 9px ${accent}` });
    } else {
        [26, 48, 70].forEach((left, index) => dot(left, 28 + (index * 16), 4, index === 1 ? accent : highlight));
        part({ left: '22%', top: '58%', width: '44%', height: '4%', borderRadius: '999px', background: line, opacity: '0.3' });
    }
    root.appendChild(layer);
    root.dataset.officeAssetQualityDetail = '16px';
    return root;
}

function officeDraftDecorateLightweightAssetElement(root, type, shape, color, descriptor) {
    if (!(root instanceof HTMLElement)) return;
    const body = color.body || color.back || color.swatch || 'rgba(92, 119, 158, 0.92)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(154, 194, 255, 0.86)';
    const line = color.line || color.seam || 'rgba(12, 20, 34, 0.42)';
    const part = (styles = {}, text = '') => officeDraftAppendAssetPart(root, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    }, text);
    root.style.overflow = 'hidden';
    root.style.boxShadow = 'inset 0 2px 0 rgba(255,255,255,0.20), inset 0 -7px 12px rgba(0,0,0,0.18), 0 7px 12px rgba(2,8,18,0.18)';
    part({ left: '13%', top: '9%', width: '30%', height: '6%', borderRadius: '999px', background: 'rgba(255,255,255,0.18)' });
    part({ right: '11%', bottom: '10%', width: '24%', height: '6%', borderRadius: '999px', background: line, opacity: '0.24' });
    [25, 50, 75].forEach((left, index) => {
        part({
            left: `${left}%`,
            top: `${index === 1 ? 74 : 18}%`,
            width: '5%',
            height: '6%',
            borderRadius: '999px',
            background: index === 1 ? accent : line,
            opacity: index === 1 ? '0.42' : '0.2',
        });
    });

    if (type === 'vending_machine') {
        part({ left: '15%', top: '10%', width: '46%', height: '45%', borderRadius: '8px', background: 'linear-gradient(180deg, rgba(247,252,255,0.78), rgba(84,139,182,0.68))', border: '2px solid rgba(255,255,255,0.48)' });
        [20, 31, 42].forEach((top, index) => {
            part({ left: `${25 + (index * 2)}%`, top: `${top}%`, width: '22%', height: '5%', borderRadius: '999px', background: index === 1 ? accent : 'rgba(255,255,255,0.58)' });
        });
        part({ right: '13%', top: '16%', width: '17%', height: '40%', borderRadius: '7px', background: 'rgba(9,15,27,0.48)' });
        part({ right: '17%', top: '25%', width: '8%', height: '7%', borderRadius: '999px', background: accent });
        part({ left: '22%', bottom: '19%', width: '52%', height: '16%', borderRadius: '7px', background: accent, color: 'rgba(99,24,30,0.92)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `${Math.max(8, Math.round(Number(descriptor.width || 0) * 0.1))}px`, fontWeight: '900', lineHeight: '1' }, 'Coke');
        part({ left: '34%', bottom: '8%', width: '26%', height: '7%', borderRadius: '999px', background: line });
        return;
    }

    if (type === 'workstation' || type === 'dual_monitor' || type === 'code_terminal' || type === 'laptop' || shape === 'screen') {
        const screens = type === 'dual_monitor' ? [['13%', '18%'], ['53%', '18%']] : [['22%', '16%']];
        screens.forEach(([left, top]) => {
            part({ left, top, width: type === 'dual_monitor' ? '34%' : '58%', height: type === 'laptop' ? '40%' : '48%', borderRadius: '8px', background: 'rgba(5,10,18,0.86)', border: `2px solid ${line}` });
            part({ left: `calc(${left} + 10%)`, top: `calc(${top} + 16%)`, width: type === 'dual_monitor' ? '16%' : '30%', height: '7%', borderRadius: '999px', background: accent, boxShadow: `0 0 10px ${accent}` });
            part({ left: `calc(${left} + 12%)`, top: `calc(${top} + 30%)`, width: type === 'dual_monitor' ? '13%' : '24%', height: '4%', borderRadius: '999px', background: surface, opacity: '0.72' });
        });
        part({ left: '18%', bottom: '13%', width: '64%', height: '14%', borderRadius: '8px', background: surface });
        part({ left: '39%', bottom: '27%', width: '22%', height: '8%', borderRadius: '5px', background: line });
        return;
    }

    if (shape === 'board' || shape === 'panel' || shape === 'divider') {
        part({ left: '9%', top: '11%', width: '82%', height: '70%', borderRadius: '9px', background: surface, border: `2px solid ${body}` });
        part({ left: '19%', top: '31%', width: '44%', height: '6%', borderRadius: '999px', background: accent });
        part({ left: '19%', top: '49%', width: '60%', height: '5%', borderRadius: '999px', background: line, opacity: '0.72' });
        part({ left: '19%', top: '65%', width: '36%', height: '5%', borderRadius: '999px', background: line, opacity: '0.55' });
        [32, 48, 64].forEach((left, index) => {
            part({ left: `${left}%`, top: '18%', width: '9%', height: '11%', borderRadius: '3px', background: index === 1 ? accent : 'rgba(255,238,150,0.86)', transform: `rotate(${index - 1}deg)` });
        });
        return;
    }

    if (type === 'chair' || type === 'meeting_chair' || type === 'lounge_chair' || type === 'stool'
        || type === 'couch' || type === 'loveseat' || type === 'bench' || type === 'ottoman' || type === 'bean_bag'
        || shape === 'soft_seat') {
        if (type === 'bean_bag') {
            part({ left: '12%', top: '18%', width: '76%', height: '66%', borderRadius: '46% 54% 42% 58%', background: surface, transform: 'rotate(-6deg)', boxShadow: 'inset -8px -8px rgba(0,0,0,0.12)' });
            part({ left: '33%', top: '33%', width: '30%', height: '11%', borderRadius: '999px', background: accent, opacity: '0.7' });
            return;
        }
        part({ left: '13%', top: type === 'stool' ? '25%' : '12%', width: '74%', height: type === 'stool' ? '34%' : '38%', borderRadius: '16px 16px 8px 8px', background: body });
        part({ left: '9%', top: type === 'stool' ? '42%' : '46%', width: '82%', height: type === 'stool' ? '30%' : '32%', borderRadius: '13px', background: surface, boxShadow: 'inset 0 -5px rgba(0,0,0,0.14)' });
        part({ left: '18%', top: type === 'stool' ? '49%' : '55%', width: '58%', height: '7%', borderRadius: '999px', background: accent, opacity: '0.5' });
        part({ left: '21%', bottom: '9%', width: '8%', height: '22%', borderRadius: '5px', background: line });
        part({ right: '21%', bottom: '9%', width: '8%', height: '22%', borderRadius: '5px', background: line });
        if (type === 'couch' || type === 'loveseat') {
            part({ left: '36%', top: '51%', width: '3px', height: '22%', borderRadius: '999px', background: line, opacity: '0.48' });
            part({ right: '36%', top: '51%', width: '3px', height: '22%', borderRadius: '999px', background: line, opacity: '0.48' });
            part({ left: '7%', top: '44%', width: '12%', height: '33%', borderRadius: '10px', background: body });
            part({ right: '7%', top: '44%', width: '12%', height: '33%', borderRadius: '10px', background: body });
        }
        return;
    }

    if (type === 'plant' || type === 'tall_plant' || type === 'planter_box') {
        part({ left: type === 'planter_box' ? '12%' : '34%', bottom: '9%', width: type === 'planter_box' ? '76%' : '32%', height: type === 'planter_box' ? '20%' : '25%', borderRadius: '9px', background: accent });
        [18, 36, 54, 70].forEach((left, index) => {
            if (type !== 'planter_box' && index > 2) return;
            part({ left: `${left}%`, top: `${18 + ((index % 2) * 12)}%`, width: type === 'planter_box' ? '16%' : '28%', height: type === 'tall_plant' ? '52%' : '42%', borderRadius: '70% 30% 70% 30%', background: index % 2 ? body : surface, transform: `rotate(${index % 2 ? 18 : -24}deg)` });
        });
        return;
    }

    if (shape === 'counter' || shape === 'bench' || shape === 'table' || type === 'desk' || type === 'round_table' || type === 'conference_table') {
        part({ left: '8%', top: type === 'round_table' ? '9%' : '22%', width: '84%', height: type === 'round_table' ? '78%' : '34%', borderRadius: type === 'round_table' ? '999px' : '14px', background: surface, boxShadow: 'inset 0 -6px rgba(0,0,0,0.13)' });
        part({ left: '19%', bottom: '15%', width: '10%', height: '25%', borderRadius: '5px', background: body });
        part({ right: '19%', bottom: '15%', width: '10%', height: '25%', borderRadius: '5px', background: body });
        part({ left: '32%', top: type === 'round_table' ? '36%' : '32%', width: '36%', height: '7%', borderRadius: '999px', background: accent });
        [20, 38, 56].forEach((left) => {
            part({ left: `${left}%`, top: type === 'round_table' ? '55%' : '43%', width: '14%', height: '4%', borderRadius: '999px', background: line, opacity: '0.22' });
        });
        return;
    }

    if (shape === 'cabinet' || shape === 'shelf' || type === 'bookshelf' || type === 'server_rack') {
        part({ left: '10%', top: '8%', width: '80%', height: '78%', borderRadius: '10px', background: body, border: `2px solid ${line}` });
        [24, 43, 62].forEach((top, index) => {
            part({ left: '19%', top: `${top}%`, width: '60%', height: '5%', borderRadius: '999px', background: index === 1 ? accent : surface, opacity: index === 1 ? '0.95' : '0.74' });
        });
        [28, 42, 56, 70].forEach((left, index) => {
            part({ left: `${left}%`, top: `${31 + ((index % 2) * 20)}%`, width: '5%', height: '14%', borderRadius: '2px', background: index % 2 ? accent : surface });
        });
        part({ right: '18%', top: '17%', width: '8%', height: '8%', borderRadius: '999px', background: accent, boxShadow: `0 0 8px ${accent}` });
        return;
    }

    if (shape === 'tower' || shape === 'lamp' || shape === 'light' || shape === 'tripod' || shape === 'sign') {
        part({ left: '45%', top: '25%', width: '10%', height: '54%', borderRadius: '999px', background: body });
        part({ left: '22%', top: '10%', width: '56%', height: '28%', borderRadius: shape === 'sign' ? '8px' : '999px', background: surface, boxShadow: `0 0 12px ${accent}` });
        part({ left: '18%', bottom: '8%', width: '64%', height: '8%', borderRadius: '999px', background: line });
        return;
    }

    if (shape === 'appliance' || shape === 'machine' || shape === 'console' || shape === 'cart' || shape === 'dock' || shape === 'node' || shape === 'box') {
        part({ left: '11%', top: '20%', width: '78%', height: '52%', borderRadius: '12px', background: surface, border: `2px solid ${body}` });
        part({ left: '25%', top: '36%', width: '33%', height: '8%', borderRadius: '999px', background: accent, boxShadow: `0 0 8px ${accent}` });
        [48, 58, 68].forEach((top, index) => {
            part({ left: `${30 + (index * 13)}%`, top: `${top}%`, width: '8%', height: '5%', borderRadius: '999px', background: line, opacity: '0.42' });
        });
        part({ left: '20%', bottom: '12%', width: '13%', height: '13%', borderRadius: '999px', background: line });
        part({ right: '20%', bottom: '12%', width: '13%', height: '13%', borderRadius: '999px', background: line });
        return;
    }

    part({ left: '10%', top: '12%', width: '80%', height: '64%', borderRadius: '12px', background: surface, border: `2px solid ${body}` });
    part({ left: '24%', top: '34%', width: '42%', height: '7%', borderRadius: '999px', background: accent });
    part({ left: '24%', top: '53%', width: '56%', height: '5%', borderRadius: '999px', background: line, opacity: '0.55' });
}

function officeDraftUseLightweightAssetRender(state, asset) {
    if (!state || state.editorOpen || asset?.preview) return false;
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    return zoom <= 0.3;
}

function officeDraftCreateLightweightAssetElement(space, asset, state) {
    const type = safeString(asset?.type) || 'desk';
    const assetInfo = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(assetInfo.shape);
    const descriptor = officeDraftAssetDimensions(type, asset?.scale);
    const color = officeDraftAssetColorway(type, asset?.colorVariant) || {};
    const rotation = officeDraftNormalizeRotation(asset?.rotation);
    const body = color.body || color.back || color.swatch || 'rgba(92, 119, 158, 0.92)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(154, 194, 255, 0.86)';
    const root = document.createElement('div');
    const isSelected = state.editorOpen && safeString(asset?.id) === safeString(state.selectedAssetId);
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const lightweightVisualScale = zoom <= 0.2 ? 2.7 : (zoom <= 0.26 ? 2.25 : 1.72);
    const visualWidth = Math.round(Number(descriptor.width || 0) * lightweightVisualScale);
    const visualHeight = Math.round(Number(descriptor.height || 0) * lightweightVisualScale);
    const visualLeft = Math.round((Number(asset?.x) || 0) - ((visualWidth - Number(descriptor.width || 0)) / 2));
    const visualTop = Math.round((Number(asset?.y) || 0) - ((visualHeight - Number(descriptor.height || 0)) / 2));
    const radius = (() => {
        if (shape === 'rug' || type === 'round_table') return '999px';
        if (shape === 'screen' || shape === 'board' || shape === 'panel' || shape === 'divider') return '10px';
        if (shape === 'tower' || shape === 'lamp' || shape === 'light' || type === 'plant') return '999px 999px 18px 18px';
        return '18px';
    })();
    root.dataset.officeDraftAssetId = safeString(asset?.id);
    root.dataset.officeDraftSpaceId = safeString(space?.id);
    root.dataset.officeDraftAssetType = type;
    root.dataset.officeDraftAssetLightweight = '1';
    root.dataset.officeDraftAssetLightweightScale = String(lightweightVisualScale);
    root.style.position = 'absolute';
    root.style.left = `${visualLeft}px`;
    root.style.top = `${visualTop}px`;
    root.style.width = `${visualWidth}px`;
    root.style.height = `${visualHeight}px`;
    root.style.pointerEvents = 'none';
    root.style.borderRadius = radius;
    root.style.background = `linear-gradient(180deg, ${surface}, ${body})`;
    root.style.border = `2px solid ${accent}`;
    root.style.opacity = '0.86';
    root.style.outline = isSelected ? '2px solid rgba(132, 187, 255, 0.75)' : 'none';
    root.style.transform = `rotate(${rotation}deg)`;
    root.style.transformOrigin = 'center center';
    root.style.contain = 'layout paint style';
    officeDraftDecorateLightweightAssetElement(root, type, shape, color, descriptor);
    return root;
}

function officeDraftCreateGenericAssetElement(space, asset, state) {
    const type = safeString(asset?.type) || 'desk';
    const assetInfo = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(assetInfo.shape);
    const descriptor = officeDraftAssetDimensions(type, asset?.scale);
    const color = officeDraftAssetColorway(type, asset?.colorVariant) || {};
    const scale = descriptor.scale;
    const scaled = (value) => `${Math.round(Number(value) * scale)}px`;
    const root = document.createElement('div');
    const isSelected = state.editorOpen && safeString(asset?.id) === safeString(state.selectedAssetId);
    const isPreview = Boolean(asset?.preview);
    const rotation = officeDraftNormalizeRotation(asset?.rotation);
    const body = color.body || color.back || 'linear-gradient(180deg, rgba(91, 115, 151, 0.98), rgba(44, 61, 91, 0.98))';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(152, 193, 255, 0.88)';
    const line = color.line || color.seam || 'rgba(12, 20, 34, 0.42)';

    root.dataset.officeDraftAssetId = safeString(asset?.id);
    root.dataset.officeDraftSpaceId = safeString(space?.id);
    root.dataset.officeDraftAssetType = type;
    root.style.position = 'absolute';
    root.style.left = `${Math.round(Number(asset?.x) || 0)}px`;
    root.style.top = `${Math.round(Number(asset?.y) || 0)}px`;
    root.style.width = `${descriptor.width}px`;
    root.style.height = `${descriptor.height}px`;
    root.style.pointerEvents = isPreview ? 'none' : (state.editorOpen ? 'auto' : 'none');
    root.style.cursor = isPreview ? 'copy' : (state.editorOpen ? (isSelected && state.assetPointerId !== null ? 'grabbing' : 'grab') : 'default');
    root.style.filter = isPreview ? 'opacity(0.72) drop-shadow(0 0 0.55rem rgba(111, 169, 255, 0.38))' : (isSelected ? 'drop-shadow(0 0 0.65rem rgba(111, 169, 255, 0.45))' : 'none');
    root.style.outline = isPreview ? '2px dashed rgba(132, 187, 255, 0.6)' : (isSelected ? '2px solid rgba(132, 187, 255, 0.75)' : 'none');
    root.style.outlineOffset = scaled(4);
    root.style.borderRadius = scaled(16);
    root.style.transform = `rotate(${rotation}deg)`;
    root.style.transformOrigin = 'center center';

    officeDraftAppendAssetPart(root, {
        position: 'absolute',
        left: scaled(10),
        right: scaled(10),
        bottom: scaled(8),
        height: scaled(14),
        borderRadius: '999px',
        background: 'rgba(3, 8, 16, 0.16)',
    });
    const baseWidth = Number(descriptor.width || 0) / Math.max(0.01, Number(scale) || 1);
    const baseHeight = Number(descriptor.height || 0) / Math.max(0.01, Number(scale) || 1);
    officeDraftAddAssetSurfaceDetail(root, scaled, baseWidth, baseHeight, { accent, line });
    officeDraftAddAssetPixelDetail(root, scaled, baseWidth, baseHeight, { accent, line, surface, body }, type, shape);

    if (type === 'desk') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(30), width: scaled(224), height: scaled(66), borderRadius: scaled(16), background: surface, boxShadow: `inset 0 -${scaled(10)} rgba(0,0,0,0.16)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), top: scaled(88), width: scaled(34), height: scaled(52), borderRadius: scaled(8), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(30), top: scaled(88), width: scaled(34), height: scaled(52), borderRadius: scaled(8), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(140), top: scaled(48), width: scaled(72), height: scaled(10), borderRadius: '999px', background: accent });
        [64, 108, 152].forEach((left) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(74), width: scaled(34), height: scaled(5), borderRadius: '999px', background: line, opacity: '0.24' });
        });
        return root;
    }

    if (type === 'chair') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(24), top: scaled(10), width: scaled(68), height: scaled(62), borderRadius: `${scaled(22)} ${scaled(22)} ${scaled(10)} ${scaled(10)}`, background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(14), top: scaled(58), width: scaled(88), height: scaled(42), borderRadius: scaled(18), background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(68), width: scaled(48), height: scaled(6), borderRadius: '999px', background: accent, opacity: '0.55' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(24), top: scaled(94), width: scaled(12), height: scaled(30), borderRadius: scaled(5), background: line });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(24), top: scaled(94), width: scaled(12), height: scaled(30), borderRadius: scaled(5), background: line });
        return root;
    }

    if (type === 'workstation') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(100), width: scaled(264), height: scaled(54), borderRadius: scaled(15), background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(70), top: scaled(24), width: scaled(160), height: scaled(86), borderRadius: scaled(12), background: body, border: `${scaled(8)} solid rgba(10,18,30,0.72)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(94), top: scaled(48), width: scaled(112), height: scaled(22), borderRadius: scaled(8), background: accent, boxShadow: `0 0 ${scaled(18)} ${accent}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(98), top: scaled(82), width: scaled(92), height: scaled(7), borderRadius: '999px', background: surface, opacity: '0.7' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(116), top: scaled(124), width: scaled(72), height: scaled(12), borderRadius: '999px', background: line });
        return root;
    }

    if (type === 'whiteboard') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(16), width: scaled(274), height: scaled(124), borderRadius: scaled(18), background: surface, border: `${scaled(8)} solid ${body}`, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.32)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(54), width: scaled(104), height: scaled(6), borderRadius: '999px', background: accent });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(78), width: scaled(166), height: scaled(6), borderRadius: '999px', background: line });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(36), top: scaled(148), width: scaled(238), height: scaled(8), borderRadius: '999px', background: line });
        [178, 206, 234].forEach((left, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(48 + (index * 16)), width: scaled(28), height: scaled(18), borderRadius: scaled(4), background: index === 1 ? 'rgba(255,238,150,0.86)' : accent, transform: `rotate(${index - 1}deg)` });
        });
        return root;
    }

    if (type === 'vending_machine') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(10), width: scaled(114), height: scaled(226), borderRadius: scaled(18), background: body, boxShadow: 'inset 0 12px 18px rgba(255,255,255,0.12), inset 0 -16px 18px rgba(0,0,0,0.22)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(44), width: scaled(56), height: scaled(88), borderRadius: scaled(10), background: 'linear-gradient(180deg, rgba(248,252,255,0.72), rgba(101,151,197,0.68))', border: `${scaled(3)} solid rgba(255,255,255,0.5)` });
        [60, 84, 108].forEach((top, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(44 + (index * 3)), top: scaled(top), width: scaled(34), height: scaled(7), borderRadius: '999px', background: index === 1 ? accent : 'rgba(255,255,255,0.54)' });
        });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(28), top: scaled(52), width: scaled(24), height: scaled(78), borderRadius: scaled(7), background: 'rgba(12,18,30,0.42)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(36), top: scaled(74), width: scaled(10), height: scaled(10), borderRadius: '999px', background: accent });
        const label = officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(36), top: scaled(148), width: scaled(76), height: scaled(30), borderRadius: scaled(9), background: accent, color: 'rgba(99,24,30,0.92)', fontSize: scaled(13), fontWeight: '800', display: 'flex', alignItems: 'center', justifyContent: 'center', letterSpacing: '0.04em' }, 'Coke');
        label.style.textTransform = 'uppercase';
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(56), top: scaled(188), width: scaled(38), height: scaled(18), borderRadius: scaled(9), background: line });
        return root;
    }

    if (type === 'coffee_bar') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(16), top: scaled(74), width: scaled(278), height: scaled(66), borderRadius: scaled(18), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(28), top: scaled(46), width: scaled(254), height: scaled(38), borderRadius: scaled(15), background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(54), top: scaled(24), width: scaled(36), height: scaled(34), borderRadius: `${scaled(8)} ${scaled(8)} ${scaled(14)} ${scaled(14)}`, background: accent });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(116), top: scaled(20), width: scaled(52), height: scaled(48), borderRadius: scaled(12), background: line });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(60), top: scaled(24), width: scaled(36), height: scaled(34), borderRadius: `${scaled(8)} ${scaled(8)} ${scaled(14)} ${scaled(14)}`, background: accent });
        [50, 132, 224].forEach((left) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(92), width: scaled(42), height: scaled(6), borderRadius: '999px', background: 'rgba(255,255,255,0.18)' });
        });
        [128, 142, 156].forEach((left, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(10 + (index * 5)), width: scaled(5), height: scaled(16), borderRadius: '999px', background: accent, opacity: '0.5' });
        });
        return root;
    }

    if (type === 'fridge') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(10), width: scaled(94), height: scaled(214), borderRadius: scaled(18), background: body, border: `${scaled(6)} solid ${line}`, boxShadow: 'inset 0 12px 18px rgba(255,255,255,0.18), inset 0 -18px 22px rgba(0,0,0,0.12)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), top: scaled(26), width: scaled(70), height: scaled(92), borderRadius: scaled(12), background: 'linear-gradient(180deg, rgba(211,245,255,0.78), rgba(105,156,190,0.52))', border: `${scaled(3)} solid rgba(255,255,255,0.5)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), top: scaled(128), width: scaled(70), height: scaled(62), borderRadius: scaled(10), background: surface, opacity: '0.9' });
        [48, 70, 92, 148, 170].forEach((top, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(top), width: scaled(36), height: scaled(6), borderRadius: '999px', background: index % 2 ? accent : 'rgba(255,255,255,0.72)' });
        });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(22), top: scaled(78), width: scaled(8), height: scaled(68), borderRadius: '999px', background: line, opacity: '0.52' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(38), bottom: scaled(18), width: scaled(54), height: scaled(10), borderRadius: '999px', background: line });
        return root;
    }

    if (type === 'water_cooler') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(29), top: scaled(8), width: scaled(48), height: scaled(64), borderRadius: `${scaled(22)} ${scaled(22)} ${scaled(16)} ${scaled(16)}`, background: 'linear-gradient(180deg, rgba(225,249,255,0.86), rgba(93,165,213,0.52))', border: `${scaled(4)} solid rgba(255,255,255,0.48)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(24), top: scaled(66), width: scaled(58), height: scaled(92), borderRadius: scaled(14), background: body, border: `${scaled(5)} solid ${line}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(36), top: scaled(92), width: scaled(34), height: scaled(12), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(10)} ${accent}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(41), top: scaled(112), width: scaled(8), height: scaled(18), borderRadius: '999px', background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(32), top: scaled(112), width: scaled(8), height: scaled(18), borderRadius: '999px', background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), bottom: scaled(14), width: scaled(68), height: scaled(10), borderRadius: '999px', background: line });
        return root;
    }

    if (type === 'microwave') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(14), top: scaled(18), width: scaled(128), height: scaled(68), borderRadius: scaled(14), background: body, border: `${scaled(5)} solid ${line}`, boxShadow: 'inset 0 8px 12px rgba(255,255,255,0.12)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(28), top: scaled(34), width: scaled(58), height: scaled(28), borderRadius: scaled(7), background: 'rgba(8,15,26,0.74)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(40), top: scaled(44), width: scaled(32), height: scaled(6), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(9)} ${accent}` });
        [35, 47, 59].forEach((top) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(24), top: scaled(top), width: scaled(9), height: scaled(7), borderRadius: scaled(3), background: surface });
        });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), bottom: scaled(12), width: scaled(94), height: scaled(8), borderRadius: '999px', background: line, opacity: '0.35' });
        return root;
    }

    if (type === 'snack_shelf') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(16), width: scaled(180), height: scaled(138), borderRadius: scaled(14), background: body, border: `${scaled(6)} solid ${line}` });
        [44, 82, 120].forEach((top) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(top), width: scaled(148), height: scaled(8), borderRadius: '999px', background: line, opacity: '0.38' });
        });
        for (let index = 0; index < 12; index += 1) {
            const left = 44 + ((index % 4) * 32);
            const top = 54 + (Math.floor(index / 4) * 36);
            const packColor = index % 3 === 0 ? accent : (index % 3 === 1 ? 'rgba(255,221,103,0.92)' : surface);
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(top), width: scaled(18), height: scaled(20), borderRadius: scaled(4), background: packColor, boxShadow: 'inset 0 -3px rgba(0,0,0,0.14)' });
        }
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), bottom: scaled(14), width: scaled(132), height: scaled(9), borderRadius: '999px', background: line });
        return root;
    }

    if (type === 'kitchen_island' || type === 'recipe_counter' || type === 'snack_table') {
        const tableW = Math.max(150, descriptor.width / scale - 32);
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(16), top: scaled(42), width: scaled(tableW), height: scaled(64), borderRadius: scaled(18), background: surface, boxShadow: `inset 0 -${scaled(12)} rgba(0,0,0,0.14)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(32), top: scaled(28), width: scaled(tableW - 32), height: scaled(34), borderRadius: scaled(14), background: body, opacity: '0.95' });
        [56, 104, 152].forEach((left, index) => {
            if (left > tableW - 8) return;
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(44 + ((index % 2) * 10)), width: scaled(28), height: scaled(12), borderRadius: scaled(6), background: index === 1 ? accent : 'rgba(255,245,210,0.84)' });
        });
        [52, 120, 188].forEach((left) => {
            if (left < tableW) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(78), width: scaled(42), height: scaled(6), borderRadius: '999px', background: line, opacity: '0.28' });
        });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(104), width: scaled(24), height: scaled(44), borderRadius: scaled(7), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(34), top: scaled(104), width: scaled(24), height: scaled(44), borderRadius: scaled(7), background: body });
        if (type === 'recipe_counter') {
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(48), top: scaled(34), width: scaled(56), height: scaled(38), borderRadius: scaled(8), background: 'rgba(245,252,255,0.82)', border: `${scaled(3)} solid rgba(141,190,255,0.48)` });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(60), top: scaled(46), width: scaled(32), height: scaled(5), borderRadius: '999px', background: accent });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(60), top: scaled(58), width: scaled(40), height: scaled(4), borderRadius: '999px', background: line, opacity: '0.42' });
        }
        return root;
    }

    if (type === 'arcade_cabinet') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(28), top: scaled(10), width: scaled(94), height: scaled(194), borderRadius: `${scaled(18)} ${scaled(18)} ${scaled(10)} ${scaled(10)}`, background: body, border: `${scaled(6)} solid ${line}`, boxShadow: 'inset 0 10px 14px rgba(255,255,255,0.12)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(34), width: scaled(66), height: scaled(50), borderRadius: scaled(8), background: 'rgba(5,10,18,0.86)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(54), top: scaled(54), width: scaled(38), height: scaled(7), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(12)} ${accent}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(108), width: scaled(66), height: scaled(38), borderRadius: scaled(8), background: surface });
        [54, 76, 98].forEach((left, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(120 + ((index % 2) * 10)), width: scaled(10), height: scaled(10), borderRadius: '999px', background: index === 1 ? accent : 'rgba(255,100,140,0.9)' });
        });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), bottom: scaled(14), width: scaled(82), height: scaled(12), borderRadius: '999px', background: line });
        return root;
    }

    if (type === 'round_table') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(18), width: scaled(174), height: scaled(174), borderRadius: '999px', background: surface, boxShadow: `inset 0 -${scaled(18)} rgba(0,0,0,0.14)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(77), top: scaled(77), width: scaled(56), height: scaled(56), borderRadius: '999px', background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(72), top: scaled(38), width: scaled(66), height: scaled(9), borderRadius: '999px', background: accent });
        [54, 106, 144].forEach((left) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(118), width: scaled(34), height: scaled(6), borderRadius: '999px', background: line, opacity: '0.24' });
        });
        return root;
    }

    if (type === 'plant') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), bottom: scaled(20), width: scaled(48), height: scaled(42), borderRadius: `${scaled(10)} ${scaled(10)} ${scaled(18)} ${scaled(18)}`, background: accent });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), top: scaled(38), width: scaled(38), height: scaled(78), borderRadius: '70% 30% 70% 30%', background: surface, transform: 'rotate(-24deg)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(16), width: scaled(44), height: scaled(94), borderRadius: '45% 65% 45% 65%', background: body, transform: 'rotate(14deg)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(16), top: scaled(62), width: scaled(48), height: scaled(68), borderRadius: '70% 30% 70% 30%', background: body, transform: 'rotate(-46deg)' });
        return root;
    }

    if (type === 'bookshelf') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(22), top: scaled(18), width: scaled(206), height: scaled(164), borderRadius: scaled(14), background: body });
        [50, 92, 134].forEach((top) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(38), top: scaled(top), width: scaled(174), height: scaled(8), borderRadius: '999px', background: line });
        });
        [48, 74, 100, 128, 154].forEach((left, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(58 + ((index % 3) * 32)), width: scaled(14), height: scaled(30), borderRadius: scaled(4), background: index % 2 ? accent : surface });
        });
        [174, 190].forEach((left) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(98), width: scaled(10), height: scaled(26), borderRadius: scaled(3), background: 'rgba(255,238,150,0.82)' });
        });
        return root;
    }

    if (type === 'server_rack') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(10), width: scaled(114), height: scaled(214), borderRadius: scaled(16), background: body, border: `${scaled(6)} solid rgba(9,15,25,0.52)` });
        [42, 76, 110, 144, 178].forEach((top, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(top), width: scaled(82), height: scaled(18), borderRadius: scaled(6), background: surface });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(44), top: scaled(top + 5), width: scaled(8), height: scaled(8), borderRadius: '999px', background: index % 2 ? accent : 'rgba(255, 120, 120, 0.9)', boxShadow: `0 0 ${scaled(10)} ${accent}` });
        });
        return root;
    }

    if (type === 'focus_pod') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(22), top: scaled(18), width: scaled(176), height: scaled(206), borderRadius: `${scaled(74)} ${scaled(74)} ${scaled(30)} ${scaled(30)}`, background: body, boxShadow: 'inset 0 12px 18px rgba(255,255,255,0.12)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(54), width: scaled(116), height: scaled(126), borderRadius: `${scaled(48)} ${scaled(48)} ${scaled(20)} ${scaled(20)}`, background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(78), top: scaled(92), width: scaled(64), height: scaled(14), borderRadius: '999px', background: accent });
        return root;
    }

    if (['bench', 'loveseat', 'lounge_chair', 'ottoman', 'bean_bag', 'meeting_chair', 'stool'].includes(type)) {
        if (type === 'bean_bag') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(24), width: scaled(150), height: scaled(118), borderRadius: '48% 52% 44% 56%', background: surface, transform: 'rotate(-7deg)', boxShadow: `inset -${scaled(18)} -${scaled(16)} rgba(0,0,0,0.12)` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(56), top: scaled(48), width: scaled(54), height: scaled(18), borderRadius: '999px', background: accent, opacity: '0.7' });
            return root;
        }
        if (type === 'ottoman') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(22), width: scaled(110), height: scaled(56), borderRadius: scaled(22), background: surface, boxShadow: `inset 0 -${scaled(12)} rgba(0,0,0,0.13)` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(28), bottom: scaled(22), width: scaled(18), height: scaled(26), borderRadius: scaled(6), background: body });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(28), bottom: scaled(22), width: scaled(18), height: scaled(26), borderRadius: scaled(6), background: body });
            return root;
        }
        if (type === 'lounge_chair' || type === 'meeting_chair' || type === 'stool') {
            const seatW = type === 'stool' ? 58 : (type === 'meeting_chair' ? 76 : 104);
            const left = Math.max(12, ((descriptor.width / scale) - seatW) / 2);
            if (type !== 'stool') {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left + 8), top: scaled(12), width: scaled(seatW - 16), height: scaled(type === 'meeting_chair' ? 46 : 66), borderRadius: `${scaled(22)} ${scaled(22)} ${scaled(10)} ${scaled(10)}`, background: body });
            }
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(type === 'stool' ? 24 : 58), width: scaled(seatW), height: scaled(type === 'stool' ? 42 : 48), borderRadius: scaled(type === 'stool' ? 28 : 18), background: surface, boxShadow: `inset 0 -${scaled(9)} rgba(0,0,0,0.14)` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left + 14), bottom: scaled(18), width: scaled(10), height: scaled(34), borderRadius: scaled(5), background: line });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(left + 14), bottom: scaled(18), width: scaled(10), height: scaled(34), borderRadius: scaled(5), background: line });
            if (type === 'lounge_chair') {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left - 4), top: scaled(70), width: scaled(18), height: scaled(44), borderRadius: scaled(10), background: body });
                officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(left - 4), top: scaled(70), width: scaled(18), height: scaled(44), borderRadius: scaled(10), background: body });
            }
            return root;
        }
        const wideSeat = Math.max(150, descriptor.width / scale - 28);
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(16), top: scaled(type === 'loveseat' ? 24 : 18), width: scaled(wideSeat), height: scaled(type === 'loveseat' ? 54 : 42), borderRadius: `${scaled(22)} ${scaled(22)} ${scaled(10)} ${scaled(10)}`, background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(12), top: scaled(type === 'loveseat' ? 70 : 50), width: scaled(wideSeat + 8), height: scaled(46), borderRadius: scaled(16), background: surface, boxShadow: `inset 0 -${scaled(10)} rgba(0,0,0,0.14)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(40), top: scaled(type === 'loveseat' ? 82 : 60), width: scaled(Math.max(58, wideSeat * 0.28)), height: scaled(7), borderRadius: '999px', background: accent, opacity: '0.5' });
        [34, wideSeat - 8].forEach((left) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), bottom: scaled(18), width: scaled(16), height: scaled(32), borderRadius: scaled(6), background: line });
        });
        if (type === 'loveseat') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(106), top: scaled(76), width: scaled(3), height: scaled(32), borderRadius: '999px', background: line, opacity: '0.55' });
        } else {
            [0.34, 0.5, 0.66].forEach((ratio) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(wideSeat * ratio), top: scaled(58), width: scaled(3), height: scaled(26), borderRadius: '999px', background: line, opacity: '0.42' });
            });
        }
        return root;
    }

    if (['wall_monitor', 'monitor_stand', 'laptop', 'tablet_stand', 'dual_monitor', 'code_terminal', 'research_terminal', 'data_wall'].includes(type)) {
        const screenBack = type === 'data_wall' ? surface : 'rgba(5,10,18,0.88)';
        if (type === 'dual_monitor') {
            [22, 124].forEach((left, index) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(18), width: scaled(88), height: scaled(58), borderRadius: scaled(9), background: screenBack, border: `${scaled(5)} solid ${body}` });
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left + 22), top: scaled(42), width: scaled(42), height: scaled(7), borderRadius: '999px', background: index ? accent : surface, boxShadow: `0 0 ${scaled(12)} ${accent}` });
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left + 38), top: scaled(78), width: scaled(14), height: scaled(18), borderRadius: scaled(4), background: line });
            });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(58), bottom: scaled(18), width: scaled(122), height: scaled(10), borderRadius: '999px', background: line });
            return root;
        }
        if (type === 'laptop') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(26), top: scaled(16), width: scaled(98), height: scaled(56), borderRadius: scaled(9), background: screenBack, border: `${scaled(5)} solid ${body}`, transform: 'skewX(-5deg)' });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(74), width: scaled(114), height: scaled(18), borderRadius: scaled(8), background: surface });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(58), top: scaled(40), width: scaled(34), height: scaled(6), borderRadius: '999px', background: accent });
            return root;
        }
        if (type === 'tablet_stand') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(24), top: scaled(12), width: scaled(56), height: scaled(80), borderRadius: scaled(12), background: screenBack, border: `${scaled(5)} solid ${body}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(46), top: scaled(96), width: scaled(12), height: scaled(20), borderRadius: scaled(5), background: line });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(24), bottom: scaled(12), width: scaled(56), height: scaled(8), borderRadius: '999px', background: line });
            return root;
        }
        if (type === 'data_wall') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(16), width: scaled(294), height: scaled(132), borderRadius: scaled(14), background: 'rgba(4,10,18,0.86)', border: `${scaled(7)} solid ${body}` });
            [38, 80, 122].forEach((top, index) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(44 + (index * 34)), top: scaled(top), width: scaled(78), height: scaled(7), borderRadius: '999px', background: index === 1 ? accent : surface });
            });
            [50, 106, 162, 218].forEach((left, index) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(58 + ((index % 2) * 38)), width: scaled(16), height: scaled(16), borderRadius: '999px', background: index % 2 ? accent : surface, boxShadow: `0 0 ${scaled(10)} ${accent}` });
            });
            return root;
        }
        const bodyW = Math.max(128, descriptor.width / scale - 44);
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(22), top: scaled(18), width: scaled(bodyW), height: scaled(Math.max(72, descriptor.height / scale - 64)), borderRadius: scaled(12), background: screenBack, border: `${scaled(7)} solid ${body}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(50), width: scaled(72), height: scaled(8), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(16)} ${accent}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(76), width: scaled(104), height: scaled(7), borderRadius: '999px', background: surface });
        [96, 112, 128].forEach((top, index) => {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52 + (index * 18)), top: scaled(top), width: scaled(54), height: scaled(6), borderRadius: '999px', background: index === 1 ? accent : surface, opacity: '0.58' });
        });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(70), bottom: scaled(20), width: scaled(74), height: scaled(10), borderRadius: '999px', background: line });
        return root;
    }

    if (['kanban_board', 'pinboard', 'sticky_note_wall', 'dispatch_board'].includes(type)) {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(16), width: scaled(Math.max(188, descriptor.width / scale - 36)), height: scaled(Math.max(104, descriptor.height / scale - 32)), borderRadius: scaled(12), background: surface, border: `${scaled(7)} solid ${body}` });
        if (type === 'kanban_board' || type === 'dispatch_board') {
            [58, 112, 166].forEach((left) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(38), width: scaled(2), height: scaled(82), borderRadius: '999px', background: line, opacity: '0.42' });
            });
        }
        const notes = type === 'sticky_note_wall' ? 9 : 6;
        for (let index = 0; index < notes; index += 1) {
            const left = 42 + ((index % 3) * 58) + (type === 'dispatch_board' ? 12 : 0);
            const top = 42 + (Math.floor(index / 3) * 34);
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(top), width: scaled(type === 'dispatch_board' ? 46 : 34), height: scaled(22), borderRadius: scaled(5), background: index % 2 ? accent : (index % 3 ? 'rgba(255,236,151,0.92)' : 'rgba(138,210,255,0.9)'), transform: `rotate(${(index % 3) - 1}deg)` });
        }
        return root;
    }

    if (['sound_mixer', 'testing_rig', 'game_console', 'vr_headset', 'microscope', 'sample_tray', 'soda_crate', 'network_switch', 'router_node', 'firewall_box', 'charging_dock'].includes(type)) {
        if (type === 'microscope') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(48), top: scaled(18), width: scaled(26), height: scaled(82), borderRadius: scaled(14), background: body, transform: 'rotate(18deg)' });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(62), top: scaled(78), width: scaled(28), height: scaled(42), borderRadius: scaled(12), background: surface });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(22), bottom: scaled(18), width: scaled(72), height: scaled(12), borderRadius: '999px', background: line });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(72), top: scaled(24), width: scaled(24), height: scaled(16), borderRadius: scaled(8), background: accent });
            return root;
        }
        if (type === 'vr_headset') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(20), top: scaled(28), width: scaled(80), height: scaled(38), borderRadius: scaled(20), background: body, border: `${scaled(5)} solid ${line}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(40), width: scaled(18), height: scaled(8), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(10)} ${accent}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(34), top: scaled(40), width: scaled(18), height: scaled(8), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(10)} ${accent}` });
            return root;
        }
        if (type === 'charging_dock') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(42), width: scaled(196), height: scaled(54), borderRadius: scaled(18), background: body, border: `${scaled(6)} solid ${line}` });
            [48, 92, 136].forEach((left) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(58), width: scaled(26), height: scaled(16), borderRadius: scaled(8), background: accent, boxShadow: `0 0 ${scaled(12)} ${accent}` });
            });
            return root;
        }
        const panelW = Math.max(92, descriptor.width / scale - 34);
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(type === 'network_switch' ? 24 : 30), width: scaled(panelW), height: scaled(Math.max(44, descriptor.height / scale - 58)), borderRadius: scaled(13), background: body, border: `${scaled(6)} solid ${line}`, boxShadow: 'inset 0 10px 14px rgba(255,255,255,0.1)' });
        if (type === 'sound_mixer') {
            [42, 70, 98, 126, 154].forEach((left, index) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(48), width: scaled(8), height: scaled(46), borderRadius: '999px', background: surface });
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left - 4), top: scaled(56 + ((index % 3) * 10)), width: scaled(16), height: scaled(8), borderRadius: '999px', background: accent });
            });
        } else {
            [42, 70, 98, 126, 154].forEach((left, index) => {
                if (left < panelW) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(54 + ((index % 2) * 22)), width: scaled(18), height: scaled(10), borderRadius: scaled(4), background: index % 2 ? accent : surface, boxShadow: index % 2 ? `0 0 ${scaled(10)} ${accent}` : 'none' });
            });
        }
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), bottom: scaled(18), width: scaled(Math.max(58, panelW - 34)), height: scaled(8), borderRadius: '999px', background: line });
        return root;
    }

    if (['phone_booth', 'ticket_kiosk', 'power_panel', 'storage_locker', 'filing_cabinet', 'copier', 'printer', 'mail_sorter', 'mail_cart'].includes(type)) {
        if (type === 'phone_booth') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(12), width: scaled(132), height: scaled(204), borderRadius: scaled(24), background: body, border: `${scaled(7)} solid ${line}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(40), width: scaled(84), height: scaled(86), borderRadius: scaled(14), background: surface, opacity: '0.9' });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(30), top: scaled(138), width: scaled(10), height: scaled(26), borderRadius: '999px', background: accent });
            return root;
        }
        if (type === 'ticket_kiosk') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(28), top: scaled(14), width: scaled(92), height: scaled(154), borderRadius: `${scaled(26)} ${scaled(26)} ${scaled(14)} ${scaled(14)}`, background: body });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(44), top: scaled(42), width: scaled(60), height: scaled(44), borderRadius: scaled(9), background: surface, border: `${scaled(4)} solid ${line}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(58), top: scaled(102), width: scaled(32), height: scaled(10), borderRadius: '999px', background: accent });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(36), bottom: scaled(16), width: scaled(76), height: scaled(10), borderRadius: '999px', background: line });
            return root;
        }
        const cabinetW = Math.max(82, descriptor.width / scale - 36);
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(14), width: scaled(cabinetW), height: scaled(Math.max(86, descriptor.height / scale - 32)), borderRadius: scaled(12), background: body, border: `${scaled(5)} solid ${line}` });
        [44, 82, 120, 158].forEach((top, index) => {
            if (top < (descriptor.height / scale) - 26) {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(top), width: scaled(Math.max(48, cabinetW - 32)), height: scaled(10), borderRadius: scaled(4), background: index % 2 ? surface : accent, opacity: index % 2 ? '0.75' : '0.9' });
            }
        });
        if (type === 'printer' || type === 'copier') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), top: scaled(26), width: scaled(Math.max(48, cabinetW - 32)), height: scaled(18), borderRadius: scaled(6), background: surface, opacity: '0.82' });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(44), top: scaled(30), width: scaled(Math.max(32, cabinetW - 52)), height: scaled(5), borderRadius: '999px', background: accent });
        }
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(34), top: scaled(46), width: scaled(8), height: scaled(8), borderRadius: '999px', background: accent });
        return root;
    }

    if (['green_screen', 'acoustic_panel', 'divider', 'rug', 'keyboard_tray'].includes(type)) {
        const isRug = type === 'rug';
        if (isRug) {
            root.replaceChildren();
            root.style.zIndex = '0';
            root.style.borderRadius = scaled(38);
            root.style.filter = isPreview ? 'opacity(0.58) drop-shadow(0 0 0.45rem rgba(111, 169, 255, 0.2))' : (isSelected ? 'drop-shadow(0 0 0.45rem rgba(111, 169, 255, 0.35))' : 'none');
            officeDraftAppendAssetPart(root, {
                position: 'absolute',
                left: scaled(16),
                top: scaled(18),
                width: scaled(Math.max(72, descriptor.width / scale - 32)),
                height: scaled(Math.max(48, descriptor.height / scale - 36)),
                borderRadius: scaled(34),
                background: `linear-gradient(180deg, ${surface}, ${body})`,
                border: `${scaled(3)} solid rgba(255,255,255,0.22)`,
                opacity: '0.46',
                boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.08)',
            });
            [34, 50, 66].forEach((top, index) => {
                officeDraftAppendAssetPart(root, {
                    position: 'absolute',
                    left: scaled(42 + (index * 18)),
                    top: scaled(top),
                    width: scaled(Math.max(52, descriptor.width / scale - 108)),
                    height: scaled(3),
                    borderRadius: '999px',
                    background: index === 1 ? accent : line,
                    opacity: index === 1 ? '0.28' : '0.14',
                });
            });
            return root;
        }
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(isRug ? 16 : 18), top: scaled(isRug ? 18 : 14), width: scaled(Math.max(72, descriptor.width / scale - (isRug ? 32 : 36))), height: scaled(Math.max(48, descriptor.height / scale - (isRug ? 36 : 28))), borderRadius: scaled(isRug ? 34 : 12), background: surface, border: `${scaled(isRug ? 4 : 6)} solid ${body}` });
        if (type === 'green_screen') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(28), top: scaled(28), width: scaled(Math.max(190, descriptor.width / scale - 56)), height: scaled(104), borderRadius: scaled(10), background: 'rgba(75, 178, 95, 0.94)' });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), bottom: scaled(16), width: scaled(12), height: scaled(42), borderRadius: scaled(5), background: line });
            officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(30), bottom: scaled(16), width: scaled(12), height: scaled(42), borderRadius: scaled(5), background: line });
        } else if (type === 'acoustic_panel' || type === 'divider') {
            [34, 58, 82, 106, 130].forEach((left) => {
                if (left < (descriptor.width / scale) - 30) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(28), width: scaled(8), height: scaled(Math.max(52, descriptor.height / scale - 56)), borderRadius: '999px', background: line, opacity: '0.35' });
            });
        } else {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(isRug ? 48 : 36), width: scaled(Math.max(52, descriptor.width / scale - 84)), height: scaled(8), borderRadius: '999px', background: accent, opacity: '0.75' });
        }
        return root;
    }

    if (['floor_sign', 'room_sign', 'wall_clock', 'coat_rack', 'task_lamp', 'microphone', 'camera_tripod', 'light_panel', 'tall_plant', 'planter_box'].includes(type)) {
        if (type === 'wall_clock') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(12), top: scaled(12), width: scaled(62), height: scaled(62), borderRadius: '999px', background: surface, border: `${scaled(6)} solid ${body}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(24), width: scaled(4), height: scaled(22), borderRadius: '999px', background: line, transformOrigin: 'bottom center', transform: 'rotate(35deg)' });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(42), width: scaled(18), height: scaled(4), borderRadius: '999px', background: accent });
            return root;
        }
        if (type === 'room_sign' || type === 'floor_sign') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(type === 'floor_sign' ? 18 : 20), width: scaled(type === 'floor_sign' ? 58 : 98), height: scaled(type === 'floor_sign' ? 52 : 42), borderRadius: scaled(8), background: surface, border: `${scaled(5)} solid ${body}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(32), top: scaled(type === 'floor_sign' ? 38 : 36), width: scaled(type === 'floor_sign' ? 30 : 58), height: scaled(6), borderRadius: '999px', background: accent });
            if (type === 'floor_sign') {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(44), top: scaled(70), width: scaled(8), height: scaled(44), borderRadius: '999px', background: line });
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(24), bottom: scaled(12), width: scaled(46), height: scaled(8), borderRadius: '999px', background: line });
            }
            return root;
        }
        if (type === 'tall_plant' || type === 'planter_box') {
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(type === 'planter_box' ? 18 : 34), bottom: scaled(18), width: scaled(type === 'planter_box' ? 184 : 42), height: scaled(type === 'planter_box' ? 34 : 44), borderRadius: scaled(12), background: accent });
            [20, 48, 76, 104, 132].forEach((left, index) => {
                if (type === 'tall_plant' && index > 2) return;
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(type === 'tall_plant' ? 26 + (index * 12) : left), top: scaled(type === 'tall_plant' ? 22 + (index * 18) : 20 + ((index % 2) * 12)), width: scaled(34), height: scaled(type === 'tall_plant' ? 74 : 54), borderRadius: '70% 30% 70% 30%', background: index % 2 ? body : surface, transform: `rotate(${index % 2 ? 18 : -22}deg)` });
            });
            return root;
        }
        if (type === 'microphone' || type === 'camera_tripod' || type === 'light_panel' || type === 'task_lamp') {
            const center = (descriptor.width / scale) / 2;
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(center - 6), top: scaled(type === 'task_lamp' ? 64 : 58), width: scaled(12), height: scaled(Math.max(52, descriptor.height / scale - 92)), borderRadius: '999px', background: line });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(center - (type === 'light_panel' ? 42 : 24)), top: scaled(type === 'light_panel' ? 18 : 18), width: scaled(type === 'light_panel' ? 84 : 48), height: scaled(type === 'microphone' ? 64 : (type === 'task_lamp' ? 44 : 58)), borderRadius: scaled(type === 'microphone' ? 24 : 12), background: surface, boxShadow: `0 0 ${scaled(16)} ${accent}` });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), bottom: scaled(16), width: scaled(Math.max(44, descriptor.width / scale - 36)), height: scaled(8), borderRadius: '999px', background: line });
            if (type === 'camera_tripod') {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(center - 34), bottom: scaled(22), width: scaled(68), height: scaled(8), borderRadius: '999px', background: line, transform: 'rotate(-22deg)' });
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(center - 34), bottom: scaled(22), width: scaled(68), height: scaled(8), borderRadius: '999px', background: line, transform: 'rotate(22deg)' });
            }
            return root;
        }
        if (type === 'coat_rack') {
            const center = (descriptor.width / scale) / 2;
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(center - 6), top: scaled(22), width: scaled(12), height: scaled(128), borderRadius: '999px', background: body });
            [-28, 28].forEach((offset) => {
                officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(center - 4), top: scaled(48), width: scaled(42), height: scaled(8), borderRadius: '999px', background: line, transform: `rotate(${offset > 0 ? 28 : -28}deg)`, transformOrigin: 'left center' });
            });
            officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), bottom: scaled(18), width: scaled(48), height: scaled(9), borderRadius: '999px', background: line });
            return root;
        }
    }

    if (shape === 'counter' || shape === 'bench') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(16), top: scaled(44), width: scaled(Math.max(120, descriptor.width / scale - 32)), height: scaled(60), borderRadius: scaled(16), background: surface, boxShadow: `inset 0 -${scaled(10)} rgba(0,0,0,0.14)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(30), top: scaled(96), width: scaled(26), height: scaled(46), borderRadius: scaled(7), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(30), top: scaled(96), width: scaled(26), height: scaled(46), borderRadius: scaled(7), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(62), top: scaled(64), width: scaled(92), height: scaled(8), borderRadius: '999px', background: accent });
        [52, 112, 172].forEach((left) => {
            if (left < (descriptor.width / scale) - 44) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(82), width: scaled(42), height: scaled(5), borderRadius: '999px', background: line, opacity: '0.22' });
        });
        return root;
    }

    if (shape === 'table' || shape === 'tilt_table') {
        const tabletopWidth = Math.max(112, descriptor.width / scale - 38);
        const tabletopHeight = Math.max(70, descriptor.height / scale - 70);
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(20), top: scaled(22), width: scaled(tabletopWidth), height: scaled(tabletopHeight), borderRadius: shape === 'tilt_table' ? scaled(12) : scaled(28), background: surface, transform: shape === 'tilt_table' ? 'skewX(-10deg)' : 'none', boxShadow: `inset 0 -${scaled(16)} rgba(0,0,0,0.12)` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(56), top: scaled(74), width: scaled(16), height: scaled(62), borderRadius: scaled(7), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(56), top: scaled(74), width: scaled(16), height: scaled(62), borderRadius: scaled(7), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(74), top: scaled(42), width: scaled(86), height: scaled(8), borderRadius: '999px', background: accent });
        [60, 118, 176].forEach((left) => {
            if (left < tabletopWidth) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(70), width: scaled(42), height: scaled(5), borderRadius: '999px', background: line, opacity: '0.22' });
        });
        return root;
    }

    if (shape === 'screen' || shape === 'board') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(22), top: scaled(18), width: scaled(Math.max(118, descriptor.width / scale - 44)), height: scaled(Math.max(76, descriptor.height / scale - 38)), borderRadius: scaled(14), background: shape === 'screen' ? 'rgba(5,10,18,0.86)' : surface, border: `${scaled(8)} solid ${body}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(54), top: scaled(52), width: scaled(94), height: scaled(8), borderRadius: '999px', background: accent, boxShadow: shape === 'screen' ? `0 0 ${scaled(18)} ${accent}` : 'none' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(54), top: scaled(78), width: scaled(58), height: scaled(7), borderRadius: '999px', background: line });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(54), top: scaled(102), width: scaled(124), height: scaled(6), borderRadius: '999px', background: surface, opacity: '0.58' });
        return root;
    }

    if (shape === 'cabinet' || shape === 'shelf') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(14), width: scaled(Math.max(74, descriptor.width / scale - 36)), height: scaled(Math.max(92, descriptor.height / scale - 32)), borderRadius: scaled(14), background: body });
        [48, 84, 120].forEach((top) => {
            if (top < (descriptor.height / scale) - 24) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(32), top: scaled(top), width: scaled(Math.max(52, descriptor.width / scale - 64)), height: scaled(7), borderRadius: '999px', background: line });
        });
        [42, 64, 86, 108].forEach((left, index) => {
            if (left < (descriptor.width / scale) - 30) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(60 + ((index % 2) * 42)), width: scaled(14), height: scaled(28), borderRadius: scaled(4), background: index % 2 ? accent : surface });
        });
        [132, 156, 180].forEach((left, index) => {
            if (left < (descriptor.width / scale) - 30) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(left), top: scaled(98 + ((index % 2) * 38)), width: scaled(12), height: scaled(24), borderRadius: scaled(3), background: index % 2 ? 'rgba(255,238,150,0.84)' : accent });
        });
        return root;
    }

    if (shape === 'appliance' || shape === 'machine' || shape === 'console') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(28), width: scaled(Math.max(88, descriptor.width / scale - 36)), height: scaled(Math.max(68, descriptor.height / scale - 48)), borderRadius: scaled(16), background: body, boxShadow: 'inset 0 10px 14px rgba(255,255,255,0.1)' });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(40), top: scaled(50), width: scaled(64), height: scaled(22), borderRadius: scaled(8), background: surface });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(36), top: scaled(58), width: scaled(14), height: scaled(14), borderRadius: '999px', background: accent, boxShadow: `0 0 ${scaled(14)} ${accent}` });
        [84, 104, 124].forEach((top) => {
            if (top < (descriptor.height / scale) - 24) officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(42), top: scaled(top), width: scaled(56), height: scaled(5), borderRadius: '999px', background: line, opacity: '0.34' });
        });
        return root;
    }

    if (shape === 'tower' || shape === 'lamp' || shape === 'light' || shape === 'tripod' || shape === 'sign') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled((descriptor.width / scale / 2) - 7), top: scaled(44), width: scaled(14), height: scaled(Math.max(76, descriptor.height / scale - 70)), borderRadius: scaled(8), background: body });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled((descriptor.width / scale / 2) - 34), top: scaled(12), width: scaled(68), height: scaled(shape === 'sign' ? 46 : 54), borderRadius: shape === 'sign' ? scaled(9) : scaled(24), background: surface, boxShadow: `0 0 ${scaled(18)} ${accent}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(20), bottom: scaled(16), width: scaled(Math.max(52, descriptor.width / scale - 40)), height: scaled(9), borderRadius: '999px', background: line });
        return root;
    }

    if (shape === 'cart' || shape === 'dock' || shape === 'node' || shape === 'box') {
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(18), top: scaled(34), width: scaled(Math.max(76, descriptor.width / scale - 36)), height: scaled(Math.max(52, descriptor.height / scale - 62)), borderRadius: scaled(14), background: surface, border: `${scaled(7)} solid ${body}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(34), bottom: scaled(22), width: scaled(18), height: scaled(18), borderRadius: '999px', background: line });
        officeDraftAppendAssetPart(root, { position: 'absolute', right: scaled(34), bottom: scaled(22), width: scaled(18), height: scaled(18), borderRadius: '999px', background: line });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(58), top: scaled(58), width: scaled(58), height: scaled(8), borderRadius: '999px', background: accent });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(44), top: scaled(80), width: scaled(92), height: scaled(5), borderRadius: '999px', background: line, opacity: '0.3' });
        return root;
    }

    if (shape === 'panel' || shape === 'divider' || shape === 'rug' || shape === 'soft_seat') {
        const isRug = shape === 'rug';
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(isRug ? 18 : 20), top: scaled(isRug ? 20 : 14), width: scaled(Math.max(72, descriptor.width / scale - (isRug ? 36 : 40))), height: scaled(Math.max(58, descriptor.height / scale - (isRug ? 40 : 28))), borderRadius: shape === 'soft_seat' ? '999px 999px 28px 28px' : scaled(isRug ? 34 : 14), background: surface, border: `${scaled(7)} solid ${body}` });
        officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(52), top: scaled(isRug ? 64 : 48), width: scaled(68), height: scaled(8), borderRadius: '999px', background: accent });
        return root;
    }

    officeDraftAppendAssetPart(root, { position: 'absolute', left: scaled(16), top: scaled(16), width: scaled(Math.max(40, descriptor.width / scale - 32)), height: scaled(Math.max(40, descriptor.height / scale - 32)), borderRadius: scaled(18), background: surface, border: `${scaled(6)} solid ${body}` });
    return root;
}

function officeDraftCreateAssetElement(space, asset, state) {
    let element = null;
    if (officeDraftUseLightweightAssetRender(state, asset)) {
        element = officeDraftCreateLightweightAssetElement(space, asset, state);
    } else if (safeString(asset?.type) === 'couch') {
        element = officeDraftCreateCouchElement(space, asset, state);
    } else {
        element = officeDraftCreateGenericAssetElement(space, asset, state);
    }
    if (safeString(asset?.type) === 'rug' && element instanceof HTMLElement) {
        element.style.zIndex = '0';
    }
    return officeDraftAddAssetQualityOverlay(element, asset, state);
}
