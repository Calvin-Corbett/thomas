/** Virtual-office controls and the two renderers that exceed a single extracted module. */
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
