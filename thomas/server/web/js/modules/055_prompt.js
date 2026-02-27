// Extracted from part-028b.js
// From prompt

                {
                    successMessage: 'Pulled scene snapshot from bridge.',
                    failureMessage: 'Scene pull failed',
                },
            );
            return;
        }
        if (action === 'bridge_push_actor') {
            runBridgeAction(
                () => moduleGameStudioBridgePushSelectedActor(wb),
                {
                    successMessage: 'Pushed selected actor to bridge.',
                    failureMessage: 'Actor push failed',
                },
            );
            return;
        }
        if (action === 'bridge_push_scene') {
            runBridgeAction(
                () => moduleGameStudioBridgePushScene(wb),
                {
                    successMessage: 'Pushed scene snapshot to bridge.',
                    failureMessage: 'Scene push failed',
                },
            );
            return;
        }
        if (action === 'rc_send') {
            runBridgeAction(
                () => moduleGameStudioRemoteSend(wb),
                {
                    successMessage: 'Unreal RC succeeded.',
                    failureMessage: 'Unreal RC failed',
                },
            );
            return;
        }
        if (action === 'ai_blueprint') {
            const prompt = safeString(wb.aiPrompt) || 'Gameplay feature';
            moduleWorkbenchCopyText(
                `// Thomas AI Blueprint Spec\nFeature: ${prompt}\n\nSystems:\n- Core loop nodes\n- Input handling\n- Reward state\n- Failure state\n\nUnreal Blueprint Tasks:\n1. Create BP_GameMode_Thomas.\n2. Create BP_PlayerController_Thomas.\n3. Add event dispatchers for mission_start / mission_complete.\n4. Bind HUD widget update events.\n`,
                'AI Blueprint Spec',
            );
            moduleWorkbenchPushLog(wb.logs, 'Generated AI blueprint spec.', 'ok', 80, 'game-log');
            render();
            return;
        }
        if (action === 'ai_quest') {
            const prompt = safeString(wb.aiPrompt) || 'mission loop';
            moduleWorkbenchCopyJson({
                quest_pack: 'thomas-ai-pack',
                theme: prompt,
                quests: [
                    { id: 'q_intro', name: 'Boot Sequence', objective: 'Activate first terminal and sync diagnostics.' },
                    { id: 'q_ops', name: 'Ops Drift', objective: 'Resolve three incident anomalies before timer expires.' },
                    { id: 'q_boss', name: 'Command Breaker', objective: 'Stabilize central node under threat pressure.' },
                ],
                rewards: ['upgrade_token', 'gear_module', 'lore_fragment'],
            }, 'AI Quest Pack JSON');
            moduleWorkbenchPushLog(wb.logs, 'Generated AI quest pack.', 'ok', 80, 'game-log');
            render();
            return;
        }
        if (action === 'ai_npc') {
            const prompt = safeString(wb.aiPrompt) || 'npc behaviors';
            moduleWorkbenchCopyJson({
                prompt,
                behavior_tree: {
                    root: 'selector',
                    nodes: [
                        { id: 'sense_player', type: 'service', tick_ms: 200 },
                        { id: 'engage', type: 'sequence', condition: 'player_visible' },
                        { id: 'flank', type: 'task', score: 0.72 },
                        { id: 'fallback', type: 'task', condition: 'low_health' },
                        { id: 'patrol', type: 'task', default: true },
                    ],
                },
            }, 'AI NPC Behavior JSON');
            moduleWorkbenchPushLog(wb.logs, 'Generated NPC behavior template.', 'ok', 80, 'game-log');
            render();
            return;
        }
        if (action === 'ai_test_plan') {
            const prompt = safeString(wb.aiPrompt) || 'game feature';
            moduleWorkbenchCopyText(
                `# AI Playtest Plan\nFeature Focus: ${prompt}\n\n1. Core loop test: verify start -> objective -> reward completes without deadlock.\n2. Failure test: force hazard/death and verify clean restart + preserved high score.\n3. Balance test: run 10 sessions and record completion time distribution.\n4. UX test: confirm control discoverability within first 30 seconds.\n5. Perf test: monitor FPS in split viewport while Unreal stream is active.\n`,
                'AI Playtest Plan',
            );
            moduleWorkbenchPushLog(wb.logs, 'Generated AI playtest plan.', 'ok', 80, 'game-log');
            render();
            return;
        }
        const commands = moduleGameStudioCommands(wb);
        if (action === 'godot_export') {
            moduleWorkbenchCopyJson({
                format: 'godot.tilemap.v1',
                tile_size: 32,
                ...exportLevel(),
            }, 'Godot TileMap JSON');
            return;
        }
        if (action === 'unreal_export') {
            moduleWorkbenchCopyJson({
                format: 'unreal.world.v1',
                tile_size: 100,
                ...exportLevel(),
            }, 'Unreal World JSON');
            return;
        }
        if (action === 'godot_tscn') {
            moduleWorkbenchCopyText(moduleGameStudioGodotTscn(wb), 'Godot TSCN');
            return;
        }
        if (action === 'unreal_csv') {
            moduleWorkbenchCopyText(moduleGameStudioUnrealCsv(wb), 'Unreal CSV');
            return;
        }
        if (action === 'godot_open') moduleWorkbenchCopyText(commands.godotOpen, 'Godot Open Command');
        if (action === 'godot_build') moduleWorkbenchCopyText(commands.godotBuild, 'Godot Build Command');
        if (action === 'unreal_open') moduleWorkbenchCopyText(commands.unrealOpen, 'Unreal Open Command');
        if (action === 'unreal_build') moduleWorkbenchCopyText(commands.unrealBuild, 'Unreal Build Command');
    });

    shell.querySelectorAll('input[data-game-path]').forEach((input) => {
        input.addEventListener('input', () => {
            const key = safeString(input.dataset.gamePath);
            if (key === 'godot') wb.godotProjectPath = safeString(input.value);
            if (key === 'unreal') wb.unrealProjectPath = safeString(input.value);
        });
    });
    assetSearchInput.addEventListener('input', () => {
        wb.assetSearch = safeString(assetSearchInput.value).slice(0, 120);
        render();
    });
    assetTypeSelect.addEventListener('change', () => {
        wb.assetFilterType = safeString(assetTypeSelect.value).toLowerCase() || 'all';
        render();
    });
    unrealUrlInput.addEventListener('input', () => {
        wb.unrealViewportUrl = safeString(unrealUrlInput.value);
        wb.viewportConnected = false;
        wb.viewportLoadState = 'idle';
        wb.viewportBlockedHint = false;
        if (Number(wb.viewportProbeTimer) > 0) {
            window.clearTimeout(Number(wb.viewportProbeTimer));
            wb.viewportProbeTimer = 0;
        }
        renderViewportStatus();
    });
    rcUrlInput.addEventListener('input', () => {
        wb.unrealRcUrl = safeString(rcUrlInput.value);
        const bridge = moduleGameStudioBridgeState(wb);
        bridge.status = 'idle';
        bridge.lastError = '';
        bridge.lastPingMs = 0;
    });
    rcEndpointInput.addEventListener('input', () => {
        wb.unrealRcEndpoint = safeString(rcEndpointInput.value);
    });
    rcPayloadInput.addEventListener('input', () => {
        wb.unrealRcPayload = safeString(rcPayloadInput.value);
    });
    aiPromptInput.addEventListener('input', () => {
        wb.aiPrompt = safeString(aiPromptInput.value);
    });
    viewportFrame.addEventListener('load', () => {
        if (Number(wb.viewportProbeTimer) > 0) {
            window.clearTimeout(Number(wb.viewportProbeTimer));
            wb.viewportProbeTimer = 0;
        }
        wb.viewportConnected = true;
        wb.viewportLoadState = 'live';
        wb.viewportBlockedHint = false;
        moduleWorkbenchPushLog(wb.logs, 'Unreal stream connected in viewport.', 'ok', 80, 'game-log');
        renderViewportStatus();
    });
    viewportFrame.addEventListener('error', () => {
        if (Number(wb.viewportProbeTimer) > 0) {
            window.clearTimeout(Number(wb.viewportProbeTimer));
            wb.viewportProbeTimer = 0;
        }
        wb.viewportConnected = false;
        wb.viewportLoadState = 'blocked';
        wb.viewportBlockedHint = true;
        moduleWorkbenchPushLog(wb.logs, 'Unreal viewport failed to load.', 'warn', 80, 'game-log');
        render();
    });

    const paintFromTarget = (eventTarget) => {
        const cell = eventTarget instanceof Element ? eventTarget.closest('[data-game-x][data-game-y]') : null;
        if (!cell) return false;
        const x = Number(cell.dataset.gameX);
        const y = Number(cell.dataset.gameY);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
        paint(x, y);
        return true;
    };
    grid.addEventListener('pointerdown', (event) => {
        if (paintFromTarget(event.target)) {
            wb.dragging = true;
            render();
        }
    });
    grid.addEventListener('pointermove', (event) => {
        if (!wb.dragging) return;
        if (paintFromTarget(event.target)) {
            render();
        }
    });
    const endPaint = () => {
        wb.dragging = false;
        if (paintDirty) {
            paintDirty = false;
            render();
        }
    };
    grid.addEventListener('pointerup', endPaint);
    grid.addEventListener('pointerleave', endPaint);
    const projectSelect = shell.querySelector('select[data-wb-project-select="game_studio"]');
    if (projectSelect instanceof HTMLSelectElement) {
        projectSelect.addEventListener('change', () => {
            wb.selectedProjectId = safeString(projectSelect.value);
        });
    }

    return true;
}

function moduleRenderWorkbenchGameStudio(container, wb) {
    if (moduleRenderWorkbenchGameStudioOss(container, wb)) return;
    if (!container || !wb) return;
    wb.gridWidth = moduleWorkbenchClamp(Number(wb.gridWidth) || 20, 8, 64);
    wb.gridHeight = moduleWorkbenchClamp(Number(wb.gridHeight) || 12, 6, 40);
    wb.brush = moduleWorkbenchClamp(Number(wb.brush) || 1, 0, 4);
    if (!Array.isArray(wb.tiles) || wb.tiles.length !== wb.gridHeight || (Array.isArray(wb.tiles[0]) && wb.tiles[0].length !== wb.gridWidth)) wb.tiles = Array.from({ length: wb.gridHeight }, () => Array.from({ length: wb.gridWidth }, () => 0));