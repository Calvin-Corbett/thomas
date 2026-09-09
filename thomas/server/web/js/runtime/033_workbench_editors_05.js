async function moduleGameStudioBridgePushScene(wb) {
    const bridge = moduleGameStudioBridgeState(wb);
    const payload = {
        objectPath: bridge.actorSyncPath,
        functionName: 'ApplySceneSnapshot',
        parameters: {
            sceneActors: Array.isArray(wb.sceneActors) ? wb.sceneActors.slice(0, 320) : [],
            assets: Array.isArray(wb.assets) ? wb.assets.slice(0, 320) : [],
            tiles: wb.tiles,
            gridWidth: wb.gridWidth,
            gridHeight: wb.gridHeight,
        },
    };
    const result = await moduleGameStudioRemoteSend(wb, payload);
    if (result.ok) bridge.pushCount = (Number(bridge.pushCount) || 0) + 1;
    return result;
}

async function moduleGameStudioBridgePullState(wb) {
    const bridge = moduleGameStudioBridgeState(wb);
    const payload = {
        objectPath: bridge.actorSyncPath,
        functionName: 'RequestSceneSnapshot',
        parameters: {},
    };
    const result = await moduleGameStudioRemoteSend(wb, payload);
    if (result.ok) {
        bridge.pullCount = (Number(bridge.pullCount) || 0) + 1;
    }
    const body = result?.body && typeof result.body === 'object' ? result.body : {};
    const params = body?.ReturnValue && typeof body.ReturnValue === 'object'
        ? body.ReturnValue
        : body?.returnValue && typeof body.returnValue === 'object'
            ? body.returnValue
            : body;
    if (params && typeof params === 'object') {
        const remoteWidth = Number(params.gridWidth);
        const remoteHeight = Number(params.gridHeight);
        if (Number.isFinite(remoteWidth) || Number.isFinite(remoteHeight)) {
            moduleGameStudioResizeGrid(
                wb,
                Number.isFinite(remoteWidth) ? remoteWidth : wb.gridWidth,
                Number.isFinite(remoteHeight) ? remoteHeight : wb.gridHeight,
            );
        }
        if (Array.isArray(params.tiles)) {
            const incomingTiles = params.tiles;
            wb.tiles = Array.from({ length: wb.gridHeight }, (_row, y) => (
                Array.from({ length: wb.gridWidth }, (_col, x) => moduleWorkbenchClamp(Number(incomingTiles?.[y]?.[x]) || 0, 0, 4))
            ));
        }
        if (Array.isArray(params.sceneActors)) {
            wb.sceneActors = params.sceneActors.map((actor, index) => moduleGameStudioNormalizeActor(actor, `pull-actor-${index + 1}`));
        }
        if (Array.isArray(params.assets)) {
            wb.assets = params.assets.map((asset, index) => moduleGameStudioNormalizeAsset(asset, `pull-asset-${index + 1}`));
        }
        wb.selectedActorId = safeString(params.selectedActorId) || wb.selectedActorId;
        wb.selectedAssetId = safeString(params.selectedAssetId) || wb.selectedAssetId;
    }
    moduleGameStudioSyncSceneActorsFromTiles(wb);
    moduleGameStudioEnsureAssets(wb);
    return result;
}

function moduleGameStudioRemoteUrl(baseRaw, endpointRaw) {
    const base = safeString(baseRaw).trim();
    const endpoint = safeString(endpointRaw).trim();
    if (!base) return '';
    try {
        return new URL(endpoint || '/', base).toString();
    } catch (_error) {
        const normalizedBase = base.replace(/\/+$/, '');
        if (!endpoint) return normalizedBase;
        const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
        return `${normalizedBase}${normalizedEndpoint}`;
    }
}

async function moduleGameStudioRemoteSend(wb, payloadOverride = null, endpointOverride = '') {
    const url = moduleGameStudioRemoteUrl(wb.unrealRcUrl, endpointOverride || wb.unrealRcEndpoint);
    if (!url) throw new Error('Set Unreal RC URL first.');
    let payload = {};
    if (payloadOverride && typeof payloadOverride === 'object') {
        payload = payloadOverride;
    } else {
        const payloadRaw = safeString(wb.unrealRcPayload).trim();
        if (payloadRaw) {
            try {
                payload = JSON.parse(payloadRaw);
            } catch (_error) {
                throw new Error('Unreal RC payload must be valid JSON.');
            }
        }
    }
    const started = Date.now();
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const text = await response.text();
    let body = text;
    try {
        body = text ? JSON.parse(text) : null;
    } catch (_error) {}
    return {
        ok: response.ok,
        status: response.status,
        statusText: safeString(response.statusText),
        elapsedMs: Date.now() - started,
        url,
        body,
    };
}

function moduleGameStudioCommands(wb) {
    const godotPath = safeString(wb.godotProjectPath) || 'C:/games/MyGodotProject';
    const unrealPath = safeString(wb.unrealProjectPath) || 'C:/games/MyUnrealProject/MyGame.uproject';
    return {
        godotOpen: `godot4 --path "${godotPath}"`,
        godotBuild: `godot4 --headless --path "${godotPath}" --export-release "Windows Desktop"`,
        unrealOpen: `UnrealEditor.exe "${unrealPath}"`,
        unrealBuild: `RunUAT.bat BuildCookRun -project="${unrealPath}" -platform=Win64 -build -cook -stage -pak`,
    };
}

const MODULE_GAME_ENGINE_CATALOG = [
    {
        id: 'unreal',
        label: 'Unreal Engine',
        tag: 'AAA',
        summary: 'High-fidelity runtime and cinematic pipeline.',
        pathHint: 'C:/games/MyUnrealProject/MyGame.uproject',
        launchLabel: 'Launch Unreal',
    },
    {
        id: 'godot',
        label: 'Godot',
        tag: 'MIT',
        summary: 'Fast open-source workflow and lightweight exports.',
        pathHint: 'C:/games/MyGodotProject',
        launchLabel: 'Launch Godot',
    },
    {
        id: 'o3de',
        label: 'O3DE',
        tag: 'Open 3D',
        summary: 'Large-scale simulation and advanced rendering stack.',
        pathHint: 'C:/games/O3DE/Project',
        launchLabel: 'Launch O3DE',
    },
    {
        id: 'bevy',
        label: 'Bevy',
        tag: 'Rust',
        summary: 'Data-driven ECS workflows for rapid prototypes.',
        pathHint: 'C:/games/bevy-project',
        launchLabel: 'Launch Bevy',
    },
    {
        id: 'unity',
        label: 'Unity',
        tag: 'Connector',
        summary: 'Connected through external editor bridge and CLI.',
        pathHint: 'C:/games/UnityProject',
        launchLabel: 'Launch Unity',
    },
    {
        id: 'custom',
        label: 'Custom Engine',
        tag: 'SDK',
        summary: 'Use Thomas plugin hooks for in-house runtimes.',
        pathHint: 'C:/games/custom-engine',
        launchLabel: 'Open Connector',
    },
];

function moduleGameStudioEngineById(engineIdRaw) {
    const engineId = safeString(engineIdRaw).toLowerCase();
    return MODULE_GAME_ENGINE_CATALOG.find((engine) => safeString(engine.id) === engineId) || MODULE_GAME_ENGINE_CATALOG[0];
}

function moduleGameStudioProjectNormalize(projectRaw, fallbackId, engineIdRaw) {
    const project = projectRaw && typeof projectRaw === 'object' ? projectRaw : {};
    const engine = moduleGameStudioEngineById(engineIdRaw);
    const id = safeString(project.id) || safeString(fallbackId) || `project-${Date.now()}`;
    const pathValue = safeString(project.path) || safeString(engine.pathHint);
    const tasks = Array.isArray(project.tasks)
        ? project.tasks.map((item) => safeString(item)).filter(Boolean).slice(0, 8)
        : [];
    return {
        id,
        name: safeString(project.name) || 'Untitled Project',
        path: pathValue,
        status: safeString(project.status).toLowerCase() || 'planning',
        focus: safeString(project.focus) || 'Define loop, player verbs, and build milestone.',
        learning: safeString(project.learning) || 'Capture unknowns and test assumptions each run.',
        tasks,
        updatedAt: Number(project.updatedAt) || Date.now(),
    };
}

function moduleGameStudioEnsureDirectorState(wb) {
    if (!wb || typeof wb !== 'object') return;
    wb.selectedEngine = safeString(wb.selectedEngine).toLowerCase() || 'unreal';
    if (!MODULE_GAME_ENGINE_CATALOG.some((engine) => safeString(engine.id) === wb.selectedEngine)) {
        wb.selectedEngine = 'unreal';
    }
    if (!wb.engineProjects || typeof wb.engineProjects !== 'object') wb.engineProjects = {};
    if (!wb.activeProjectByEngine || typeof wb.activeProjectByEngine !== 'object') wb.activeProjectByEngine = {};
    MODULE_GAME_ENGINE_CATALOG.forEach((engine, index) => {
        const key = safeString(engine.id);
        const seed = index === 0
            ? [{
                id: `${key}-project-1`,
                name: key === 'unreal' ? 'Probe Arena' : `${engine.label} Prototype`,
                path: safeString(engine.pathHint),
                status: 'planning',
                focus: 'Ship first playable slice with one clear objective.',
                learning: 'Validate control feel and production velocity in week one.',
                tasks: ['Define gameplay loop', 'Create graybox level', 'Run first playtest'],
                updatedAt: Date.now(),
            }]
            : [];
        const rowsRaw = Array.isArray(wb.engineProjects[key]) ? wb.engineProjects[key] : seed;
        const seen = new Set();
        wb.engineProjects[key] = rowsRaw
            .map((row, rowIndex) => moduleGameStudioProjectNormalize(row, `${key}-project-${rowIndex + 1}`, key))
            .filter((row) => {
                if (seen.has(row.id)) return false;
                seen.add(row.id);
                return true;
            })
            .slice(0, 120);
        const activeId = safeString(wb.activeProjectByEngine[key]);
        if (!wb.engineProjects[key].some((row) => safeString(row.id) === activeId)) {
            wb.activeProjectByEngine[key] = safeString(wb.engineProjects[key][0]?.id);
        }
    });
    if (!Array.isArray(wb.studioChat)) wb.studioChat = [];
    wb.studioChat = wb.studioChat
        .map((msgRaw, index) => {
            const msg = msgRaw && typeof msgRaw === 'object' ? msgRaw : {};
            return {
                id: safeString(msg.id) || `chat-${index + 1}`,
                role: safeString(msg.role).toLowerCase() === 'assistant' ? 'assistant' : 'user',
                text: safeString(msg.text).slice(0, 2200),
                time: safeString(msg.time) || moduleWorkbenchTimeStamp(),
            };
        })
        .slice(-40);
    if (!wb.studioChat.length) {
        wb.studioChat.push({
            id: `chat-seed-${Date.now()}`,
            role: 'assistant',
            text: 'Game Studio ready. Pick an engine tile, pick a project, then tell Thomas what to build.',
            time: moduleWorkbenchTimeStamp(),
        });
    }
    wb.chatDraft = safeString(wb.chatDraft);
    wb.projectDraftName = safeString(wb.projectDraftName);
    wb.projectDraftPath = safeString(wb.projectDraftPath);
    moduleGameStudioBridgeState(wb);
}

function moduleGameStudioCurrentProject(wb) {
    const engineId = safeString(wb?.selectedEngine).toLowerCase();
    const rows = Array.isArray(wb?.engineProjects?.[engineId]) ? wb.engineProjects[engineId] : [];
    const activeId = safeString(wb?.activeProjectByEngine?.[engineId]);
    return rows.find((row) => safeString(row.id) === activeId) || rows[0] || null;
}

function moduleGameStudioSetCurrentProject(wb, projectIdRaw) {
    if (!wb || typeof wb !== 'object') return;
    const engineId = safeString(wb.selectedEngine).toLowerCase();
    const rows = Array.isArray(wb.engineProjects?.[engineId]) ? wb.engineProjects[engineId] : [];
    const projectId = safeString(projectIdRaw);
    if (!rows.some((row) => safeString(row.id) === projectId)) return;
    wb.activeProjectByEngine[engineId] = projectId;
}

function moduleGameStudioAssistantReply(wb) {
    const engine = moduleGameStudioEngineById(wb?.selectedEngine);
    const project = moduleGameStudioCurrentProject(wb);
    const projectName = safeString(project?.name) || 'current project';
    return `Working in ${engine.label} on ${projectName}. Free-form requests are handled by Thomas in Code mode; project actions here stay explicit: Launch, Build, and Playtest.`;
}

function moduleGameStudioOpenCommand(engineIdRaw, projectPathRaw, wb) {
    const engine = moduleGameStudioEngineById(engineIdRaw);
    const projectPath = safeString(projectPathRaw) || safeString(engine.pathHint);
    if (safeString(engine.id) === 'unreal') {
        wb.unrealProjectPath = projectPath;
        return moduleGameStudioCommands(wb).unrealOpen;
    }
    if (safeString(engine.id) === 'godot') {
        wb.godotProjectPath = projectPath;
        return moduleGameStudioCommands(wb).godotOpen;
    }
    if (safeString(engine.id) === 'o3de') return `o3de.exe --project-path "${projectPath}"`;
    if (safeString(engine.id) === 'bevy') return `cargo run --manifest-path "${projectPath}/Cargo.toml"`;
    if (safeString(engine.id) === 'unity') return `Unity.exe -projectPath "${projectPath}"`;
    return `thomas engine connect --engine custom --project "${projectPath}"`;
}

function moduleGameStudioBuildCommand(engineIdRaw, projectPathRaw, wb) {
    const engine = moduleGameStudioEngineById(engineIdRaw);
    const projectPath = safeString(projectPathRaw) || safeString(engine.pathHint);
    if (safeString(engine.id) === 'unreal') {
        wb.unrealProjectPath = projectPath;
        return moduleGameStudioCommands(wb).unrealBuild;
    }
    if (safeString(engine.id) === 'godot') {
        wb.godotProjectPath = projectPath;
        return moduleGameStudioCommands(wb).godotBuild;
    }
    if (safeString(engine.id) === 'o3de') return `cmake --build "${projectPath}/build" --config profile`;
    if (safeString(engine.id) === 'bevy') return `cargo build --manifest-path "${projectPath}/Cargo.toml" --release`;
    if (safeString(engine.id) === 'unity') return `Unity.exe -batchmode -quit -projectPath "${projectPath}" -buildWindows64Player "${projectPath}/Builds/Game.exe"`;
    return `thomas engine build --engine custom --project "${projectPath}"`;
}

function moduleGameStudioGodotTscn(wb) {
    const lines = [
        '[gd_scene load_steps=2 format=3]',
        '',
        '[node name="ThomasLevel" type="Node2D"]',
        '[node name="Platforms" type="Node2D" parent="."]',
        '[node name="Hazards" type="Node2D" parent="."]',
        '',
    ];
    const tile = 32;
    for (let y = 0; y < wb.gridHeight; y += 1) {
        for (let x = 0; x < wb.gridWidth; x += 1) {
            const type = Number(wb.tiles?.[y]?.[x]) || 0;
            const px = x * tile;
            const py = y * tile;
            if (type === 1) lines.push(`[node name="Platform_${x}_${y}" type="StaticBody2D" parent="Platforms"]`, `position = Vector2(${px}, ${py})`, '');
            if (type === 2) lines.push(`[node name="Hazard_${x}_${y}" type="Area2D" parent="Hazards"]`, `position = Vector2(${px}, ${py})`, '');
            if (type === 3) lines.push('[node name="Spawn" type="Marker2D" parent="."]', `position = Vector2(${px}, ${py})`, '');
            if (type === 4) lines.push('[node name="Goal" type="Marker2D" parent="."]', `position = Vector2(${px}, ${py})`, '');
        }
    }
    return lines.join('\n');
}

function moduleGameStudioUnrealCsv(wb) {
    const rows = ['x,y,type'];
    for (let y = 0; y < wb.gridHeight; y += 1) {
        for (let x = 0; x < wb.gridWidth; x += 1) {
            const type = Number(wb.tiles?.[y]?.[x]) || 0;
            if (!type) continue;
            rows.push(`${x},${y},${type}`);
        }
    }
    return rows.join('\n');
}

function moduleGameStudioStartPhaserPreview(wb, mount, { onGoal = null, onHazard = null } = {}) {
    if (!window.Phaser || !(mount instanceof HTMLElement)) return null;
    if (wb.phaserGame?.destroy) {
        try {
            wb.phaserGame.destroy(true);
        } catch (_error) {}
    }
    mount.innerHTML = '';

    const tile = 28;
    const width = Math.max(320, wb.gridWidth * tile);
    const height = Math.max(240, wb.gridHeight * tile);
    const tiles = wb.tiles.map((row) => row.map((item) => moduleWorkbenchClamp(Number(item) || 0, 0, 4)));
    const spawn = moduleGameStudioFindFirstTile(wb, 3) || { x: 1, y: wb.gridHeight - 2 };

    const game = new window.Phaser.Game({
        type: window.Phaser.AUTO,
        width,
        height,
        parent: mount,
        backgroundColor: '#0f2336',
        physics: {
            default: 'arcade',
            arcade: {
                gravity: { y: 850 },
                debug: false,
            },
        },
        scene: {
            create() {
                this.cursors = this.input.keyboard.createCursorKeys();
                this.platforms = this.physics.add.staticGroup();
                this.hazards = this.physics.add.staticGroup();
                this.goals = this.physics.add.staticGroup();
                this.score = 0;
                this.scoreText = this.add.text(10, 8, 'SCORE 0', {
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: '12px',
                    color: '#eaf4ff',
                });

                tiles.forEach((row, y) => {
                    row.forEach((tileType, x) => {
                        if (!tileType) return;
                        const px = (x * tile) + (tile / 2);
                        const py = (y * tile) + (tile / 2);
                        if (tileType === 1) {
                            const block = this.add.rectangle(px, py, tile - 4, tile - 4, 0x5ca4f3);
                            this.physics.add.existing(block, true);
                            this.platforms.add(block);
                        } else if (tileType === 2) {
                            const hazard = this.add.rectangle(px, py, tile - 6, tile - 6, 0xf17b8a);
                            this.physics.add.existing(hazard, true);
                            this.hazards.add(hazard);
                        } else if (tileType === 4) {
                            const goal = this.add.rectangle(px, py, tile - 8, tile - 8, 0xf5ce74);
                            this.physics.add.existing(goal, true);
                            this.goals.add(goal);
                        }
                    });
                });

                this.player = this.add.rectangle((spawn.x * tile) + (tile / 2), (spawn.y * tile) + (tile / 2) - 8, tile * 0.56, tile * 0.78, 0x8fd6ff);
                this.physics.add.existing(this.player);
                this.player.body.setCollideWorldBounds(true);
                this.player.body.setBounce(0.02);
                this.player.body.setDragX(500);
                this.player.body.setMaxVelocity(260, 720);

                this.physics.add.collider(this.player, this.platforms);
                this.physics.add.overlap(this.player, this.hazards, () => {
                    if (typeof onHazard === 'function') onHazard();
                    this.scene.restart();
                });
                this.physics.add.overlap(this.player, this.goals, () => {
                    if (typeof onGoal === 'function') onGoal();
                    this.scene.restart();
                });

                this.time.addEvent({
                    delay: 220,
                    loop: true,
                    callback: () => {
                        this.score += 1;
                        wb.previewScore = Math.max(0, Number(this.score) || 0);
                        wb.highScore = Math.max(Number(wb.highScore) || 0, wb.previewScore);
                        this.scoreText.setText(`SCORE ${wb.previewScore}`);
                    },
                });
            },
            update() {
                if (!this.player?.body) return;
                const body = this.player.body;
                if (this.cursors.left.isDown) {
                    body.setVelocityX(-190);
                } else if (this.cursors.right.isDown) {
                    body.setVelocityX(190);
                } else {
                    body.setVelocityX(0);
                }
                const canJump = body.blocked.down || body.touching.down;
                if ((this.cursors.up.isDown || this.cursors.space.isDown) && canJump) {
                    body.setVelocityY(-360);
                }
            },
        },
    });
    wb.phaserGame = game;
    return game;
}

function moduleRenderWorkbenchGameStudioDirector(container, wb) {
    if (!container || !wb) return false;
    moduleGameStudioEnsureDirectorState(wb);
    if (!Array.isArray(wb.logs)) wb.logs = [];
    wb.unrealRcUrl = safeString(wb.unrealRcUrl) || 'http://127.0.0.1:30010';
    wb.unrealRcEndpoint = safeString(wb.unrealRcEndpoint) || '/remote/object/call';
    wb.unrealRcPayload = safeString(wb.unrealRcPayload)
        || '{\n  "objectPath": "/Game/Blueprints/BP_GameMode.BP_GameMode_C",\n  "functionName": "RunEditorTick",\n  "parameters": {}\n}';

    moduleWorkbenchHeader(
        container,
        'Game Studio',
        'Launch engine projects and direct Thomas to build games. Simple control surface, full backend tooling.',
    );

    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-game-director';
    shell.innerHTML = `
        <section class="module-wb-stage-card module-wb-gs-launcher">
            <div class="module-wb-stage-head">
                <span class="module-wb-stage-title">Engine Launcher</span>
                <span class="module-wb-stage-meta">Pick an engine workspace</span>
            </div>
            <div class="module-wb-engine-grid" data-game-engines></div>
        </section>
        <section class="module-wb-main-grid module-wb-gs-director-grid">
            <aside class="module-wb-side-card module-wb-gs-pane">
                <h4 data-game-projects-title>Projects</h4>
                <form class="module-wb-inline-form" data-game-project-form>
                    <input type="text" data-game-project-name placeholder="New project name" />
                    <input type="text" data-game-project-path placeholder="Project path" />
                    <button type="submit" class="module-item-btn">Add Project</button>
                </form>
                <div class="module-wb-app-list module-wb-gs-project-list" data-game-projects></div>
            </aside>
            <section class="module-wb-stage-card module-wb-gs-pane module-wb-gs-focus-pane">
                <div class="module-wb-stage-head">
                    <span class="module-wb-stage-title" data-game-focus-title>Project Focus</span>
                    <span class="module-wb-stage-meta" data-game-focus-meta></span>
                </div>
                <div class="module-wb-inspector-actions">
                    <button type="button" class="module-item-btn" data-game-action="project_launch">Launch</button>
                    <button type="button" class="module-item-btn" data-game-action="project_test">Test</button>
                    <button type="button" class="module-item-btn" data-game-action="project_build">Build</button>
                    <button type="button" class="module-item-btn" data-game-action="project_plan">Plan Sprint</button>
                    <button type="button" class="module-item-btn" data-game-action="project_remove">Remove</button>
                </div>
                <div class="module-wb-gs-focus" data-game-focus></div>
                <div class="module-wb-gs-tools" data-game-tools></div>
            </section>
            <aside class="module-wb-inspector-card module-wb-gs-pane">
                <h4>Engine Status</h4>
                <div class="module-wb-metrics" data-game-metrics></div>
                <h4>Unreal Bridge</h4>
                <div class="module-wb-inspector-actions">
                    <button type="button" class="module-item-btn" data-game-action="bridge_ping">Ping</button>
                    <button type="button" class="module-item-btn" data-game-action="bridge_pull">Pull</button>
                    <button type="button" class="module-item-btn" data-game-action="bridge_push_scene">Push Scene</button>
                </div>
                <p class="module-wb-hint" data-game-bridge-status>Bridge idle.</p>
                <h4>Output</h4>
                <div class="module-wb-log-list" data-game-logs></div>
            </aside>
        </section>
        <section class="module-wb-stage-card module-wb-gs-chatdock">
            <div class="module-wb-stage-head">
                <span class="module-wb-stage-title">Thomas Game Chat</span>
                <span class="module-wb-stage-meta" data-game-chat-context></span>
            </div>
            <div class="module-wb-gs-chat-thread" data-game-chat-thread></div>
            <form class="module-wb-inline-form module-wb-gs-chat-form" data-game-chat-form>
                <input type="text" data-game-chat-input placeholder="Tell Thomas what game feature to build..." />
                <button type="submit" class="module-item-btn">Send</button>
            </form>
            <div class="module-wb-inline-actions">
                <button type="button" class="module-item-btn" data-game-chat-chip="Plan the next sprint">Plan Sprint</button>
                <button type="button" class="module-item-btn" data-game-chat-chip="Generate a vertical slice checklist">Vertical Slice</button>
                <button type="button" class="module-item-btn" data-game-chat-chip="What should we test first?">Test Priorities</button>
                <button type="button" class="module-item-btn" data-game-action="chat_clear">Clear Chat</button>
            </div>
        </section>
        ${moduleWorkbenchRenderOssStack('game_studio')}
    `;
    container.appendChild(shell);

    const engineGrid = shell.querySelector('[data-game-engines]');
    const projectsTitle = shell.querySelector('[data-game-projects-title]');
    const projectForm = shell.querySelector('[data-game-project-form]');
    const projectNameInput = shell.querySelector('input[data-game-project-name]');
    const projectPathInput = shell.querySelector('input[data-game-project-path]');
    const projectsList = shell.querySelector('[data-game-projects]');
    const focusTitle = shell.querySelector('[data-game-focus-title]');
    const focusMeta = shell.querySelector('[data-game-focus-meta]');
    const focus = shell.querySelector('[data-game-focus]');
    const tools = shell.querySelector('[data-game-tools]');
    const metrics = shell.querySelector('[data-game-metrics]');
    const bridgeStatus = shell.querySelector('[data-game-bridge-status]');
    const logs = shell.querySelector('[data-game-logs]');
    const chatContext = shell.querySelector('[data-game-chat-context]');
    const chatThread = shell.querySelector('[data-game-chat-thread]');
    const chatForm = shell.querySelector('[data-game-chat-form]');
    const chatInput = shell.querySelector('input[data-game-chat-input]');
    if (!(engineGrid instanceof HTMLElement)
        || !(projectsTitle instanceof HTMLElement)
        || !(projectForm instanceof HTMLFormElement)
        || !(projectNameInput instanceof HTMLInputElement)
        || !(projectPathInput instanceof HTMLInputElement)
        || !(projectsList instanceof HTMLElement)
        || !(focusTitle instanceof HTMLElement)
        || !(focusMeta instanceof HTMLElement)
        || !(focus instanceof HTMLElement)
        || !(tools instanceof HTMLElement)
        || !(metrics instanceof HTMLElement)
        || !(bridgeStatus instanceof HTMLElement)
        || !(logs instanceof HTMLElement)
        || !(chatContext instanceof HTMLElement)
        || !(chatThread instanceof HTMLElement)
        || !(chatForm instanceof HTMLFormElement)
        || !(chatInput instanceof HTMLInputElement)) {
        return false;
    }

    const engineTools = {
        unreal: [
            { label: 'Remote Control', value: 'object + function calls', tone: 'ok' },
            { label: 'Pixel Stream', value: 'live viewport handoff', tone: 'ok' },
            { label: 'Build Pipeline', value: 'UAT automation', tone: 'ok' },
        ],
        godot: [
            { label: 'CLI Export', value: 'headless export commands', tone: 'ok' },
            { label: 'Scene Ops', value: 'TSCN generation hooks', tone: 'ok' },
            { label: 'Playtest Loop', value: 'rapid run + tune', tone: 'ok' },
        ],
        o3de: [
            { label: 'Project CLI', value: 'project launch/build wrapper', tone: 'warn' },
            { label: 'Asset Pipeline', value: 'converter integration path', tone: 'warn' },
            { label: 'Simulation Ops', value: 'plugin bridge required', tone: 'warn' },
        ],
        bevy: [
            { label: 'Cargo Runtime', value: 'Rust dev loop', tone: 'ok' },
            { label: 'ECS Assist', value: 'system spec generation', tone: 'ok' },
            { label: 'Build Export', value: 'release packaging', tone: 'warn' },
        ],
        unity: [
            { label: 'Editor Bridge', value: 'external control path', tone: 'warn' },
            { label: 'Batchmode Build', value: 'CLI build jobs', tone: 'ok' },
            { label: 'Asset Sync', value: 'connector plugin needed', tone: 'warn' },
        ],
        custom: [
            { label: 'SDK Hooks', value: 'tool adapters', tone: 'warn' },
            { label: 'Command Bus', value: 'custom runtime calls', tone: 'warn' },
            { label: 'Build Runner', value: 'user-defined scripts', tone: 'warn' },
        ],
    };

    const pushChat = (roleRaw, textRaw) => {
        const role = safeString(roleRaw).toLowerCase() === 'assistant' ? 'assistant' : 'user';
        const text = safeString(textRaw).trim();
        if (!text) return;
        wb.studioChat.push({
            id: `chat-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
            role,
            text: text.slice(0, 2200),
            time: moduleWorkbenchTimeStamp(),
        });
        wb.studioChat = wb.studioChat.slice(-40);
    };

    const runBridgeAction = (taskFactory, { successMessage = 'Bridge request completed.', failureMessage = 'Bridge request failed.' } = {}) => {
        void taskFactory().then((result) => {
            const bridge = moduleGameStudioBridgeState(wb);
            bridge.lastSeenAt = Date.now();
            bridge.lastPingMs = Number(result?.elapsedMs) || 0;
            bridge.status = result?.ok ? 'online' : (Number(result?.status) > 0 ? 'degraded' : 'offline');
            bridge.lastError = result?.ok ? '' : (safeString(result?.statusText) || `HTTP ${Number(result?.status) || 0}`);
            moduleWorkbenchPushLog(
                wb.logs,
                result?.ok ? successMessage : `${failureMessage} (${Number(result?.status) || 0}).`,
                result?.ok ? 'ok' : 'warn',
                80,
                'game-log',
            );
            render();
        }).catch((error) => {
            const bridge = moduleGameStudioBridgeState(wb);
            bridge.status = 'offline';
            bridge.lastSeenAt = Date.now();
            bridge.lastPingMs = 0;
            bridge.lastError = safeString(error?.message) || failureMessage;
            moduleWorkbenchPushLog(wb.logs, bridge.lastError, 'error', 80, 'game-log');
            render();
        });
    };

    const render = () => {
        moduleGameStudioEnsureDirectorState(wb);
        const engine = moduleGameStudioEngineById(wb.selectedEngine);
        const projects = Array.isArray(wb.engineProjects?.[engine.id]) ? wb.engineProjects[engine.id] : [];
        const project = moduleGameStudioCurrentProject(wb);
        const bridge = moduleGameStudioBridgeState(wb);
        const bridgeStatusLabel = bridge.status === 'online'
            ? 'online'
            : bridge.status === 'degraded'
                ? 'degraded'
                : bridge.status === 'offline'
                    ? 'offline'
                    : 'idle';

        engineGrid.innerHTML = MODULE_GAME_ENGINE_CATALOG.map((row) => {
            const active = safeString(row.id) === safeString(engine.id) ? ' active' : '';
            const badge = safeString(row.tag);
            return `
                <button type="button" class="module-wb-engine-tile${active}" data-game-engine-id="${escapeHtml(safeString(row.id))}">
                    <span class="module-wb-engine-mark">${escapeHtml(safeString(row.label).slice(0, 2).toUpperCase())}</span>
                    <strong>${escapeHtml(safeString(row.label))}</strong>
                    <small>${escapeHtml(safeString(row.summary))}</small>
                    <span class="module-wb-engine-tag">${escapeHtml(badge)}</span>
                </button>
            `;
        }).join('');

        projectsTitle.textContent = `${engine.label} Projects`;
        projectNameInput.value = safeString(wb.projectDraftName);
        projectPathInput.value = safeString(wb.projectDraftPath) || safeString(engine.pathHint);
        projectsList.innerHTML = projects.length
            ? projects.map((row) => {
                const active = safeString(project?.id) === safeString(row.id) ? ' active' : '';
                return `
                    <button type="button" class="module-wb-outliner-row module-wb-gs-project-row${active}" data-game-project-id="${escapeHtml(safeString(row.id))}">
                        <strong>${escapeHtml(safeString(row.name))}</strong>
                        <span>${escapeHtml(`${safeString(row.status)} | ${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()}`)}</span>
                    </button>
                `;
            }).join('')
            : '<div class="module-wb-ghost">No projects yet. Add one above.</div>';

        focusTitle.textContent = project ? safeString(project.name) : `${engine.label} Workspace`;
        focusMeta.textContent = project ? `${safeString(project.status)} | ${safeString(project.path)}` : 'No active project';
        focus.innerHTML = project
            ? `
                <article class="module-wb-list-item">
                    <strong>Working On</strong>
                    <span>${escapeHtml(safeString(project.focus))}</span>
                </article>
                <article class="module-wb-list-item">
                    <strong>Learning Track</strong>
                    <span>${escapeHtml(safeString(project.learning))}</span>
                </article>
                <article class="module-wb-list-item">
                    <strong>Tasks</strong>
                    <span>${escapeHtml((Array.isArray(project.tasks) && project.tasks.length ? project.tasks.join(' | ') : 'No tasks yet'))}</span>
                </article>
            `
            : `
                <div class="module-wb-ghost">Select an engine, create a project, and direct Thomas from chat.</div>
            `;

        const toolRows = Array.isArray(engineTools?.[engine.id]) ? engineTools[engine.id] : [];
        tools.innerHTML = toolRows.map((row) => `
            <article class="module-wb-list-item ${moduleToneClass(row.tone) || ''}">
                <strong>${escapeHtml(safeString(row.label))}</strong>
                <span>${escapeHtml(safeString(row.value))}</span>
            </article>
        `).join('');

        metrics.innerHTML = `
            <div><span>Engine</span><strong>${escapeHtml(safeString(engine.label))}</strong></div>
            <div><span>Projects</span><strong>${projects.length}</strong></div>
            <div><span>Active</span><strong>${escapeHtml(project ? safeString(project.name) : '--')}</strong></div>
            <div><span>Bridge</span><strong>${escapeHtml(bridgeStatusLabel)}</strong></div>
            <div><span>Ping</span><strong>${Number(bridge.lastPingMs) > 0 ? `${Number(bridge.lastPingMs)} ms` : '--'}</strong></div>
            <div><span>Actions</span><strong>${Math.min(999, wb.logs.length)}</strong></div>
        `;

        bridgeStatus.textContent = bridge.lastError
            ? `Last error: ${safeString(bridge.lastError)}`
            : `Bridge ${bridgeStatusLabel}${Number(bridge.lastPingMs) > 0 ? ` (${Number(bridge.lastPingMs)} ms)` : ''}`;

        logs.innerHTML = wb.logs.length
            ? wb.logs.slice(0, 12).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('')
            : '<div class="module-wb-ghost">No engine actions yet.</div>';

        chatContext.textContent = `${engine.label}${project ? ` | ${safeString(project.name)}` : ''}`;
        chatThread.innerHTML = wb.studioChat.length
            ? wb.studioChat.map((msg) => `
                <article class="module-wb-gs-chat-msg ${safeString(msg.role) === 'assistant' ? 'assistant' : 'user'}">
                    <strong>${safeString(msg.role) === 'assistant' ? 'Thomas' : 'You'}</strong>
                    <p>${escapeHtml(safeString(msg.text))}</p>
                    <span>${escapeHtml(safeString(msg.time))}</span>
                </article>
            `).join('')
            : '<div class="module-wb-ghost">Start by describing the game outcome you want.</div>';
        chatInput.value = safeString(wb.chatDraft);
        chatInput.placeholder = project
            ? `Ask Thomas about ${safeString(project.name)}...`
            : `Ask Thomas what to build in ${safeString(engine.label)}...`;
    };

    const openProject = (project) => {
        if (!project) return;
        const command = moduleGameStudioOpenCommand(wb.selectedEngine, project.path, wb);
        moduleWorkbenchCopyText(command, `${moduleGameStudioEngineById(wb.selectedEngine).label} Open Command`);
        moduleWorkbenchPushLog(wb.logs, `Launch command prepared for ${safeString(project.name)}.`, 'ok', 80, 'game-log');
    };

    const buildProject = (project) => {
        if (!project) return;
        const command = moduleGameStudioBuildCommand(wb.selectedEngine, project.path, wb);
        moduleWorkbenchCopyText(command, `${moduleGameStudioEngineById(wb.selectedEngine).label} Build Command`);
        moduleWorkbenchPushLog(wb.logs, `Build command prepared for ${safeString(project.name)}.`, 'ok', 80, 'game-log');
    };

    const planProject = (project) => {
        if (!project) return;
        const engine = moduleGameStudioEngineById(wb.selectedEngine);
        const payload = [
            `# ${safeString(project.name)} Sprint Plan`,
            `Engine: ${safeString(engine.label)}`,
            `Focus: ${safeString(project.focus)}`,
            '',
            '1. Build one playable loop end-to-end.',
            '2. Add telemetry and failure logs for each run.',
            '3. Run two focused playtests and record action items.',
            '4. Package build + notes for next review.',
        ].join('\n');
        moduleWorkbenchCopyText(payload, 'Game Studio Sprint Plan');
        moduleWorkbenchPushLog(wb.logs, `Sprint plan generated for ${safeString(project.name)}.`, 'ok', 80, 'game-log');
        pushChat('assistant', `Sprint plan generated for ${safeString(project.name)}. I copied it so you can drop it into task tracking.`);
    };

    render();
    void moduleGameStudioBridgePing(wb, { silent: true }).then(() => {
        if (!document.body.contains(shell)) return;
        render();
    });

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element
            ? event.target.closest('[data-game-engine-id], [data-game-project-id], [data-game-action], [data-game-chat-chip]')
            : null;
        if (!target) return;
        const engineId = safeString(target.dataset.gameEngineId);
        const projectId = safeString(target.dataset.gameProjectId);
        const action = safeString(target.dataset.gameAction).toLowerCase();
        const chatChip = safeString(target.dataset.gameChatChip);

        if (engineId) {
            wb.selectedEngine = engineId;
            moduleGameStudioEnsureDirectorState(wb);
            wb.projectDraftPath = safeString(moduleGameStudioEngineById(engineId).pathHint);
            moduleWorkbenchPushLog(wb.logs, `Engine switched to ${moduleGameStudioEngineById(engineId).label}.`, 'ok', 80, 'game-log');
            render();
            return;
        }
        if (projectId) {
            moduleGameStudioSetCurrentProject(wb, projectId);
            render();
            return;
        }
        if (chatChip) {
            wb.chatDraft = chatChip;
            chatInput.focus();
            render();
            return;
        }

        const project = moduleGameStudioCurrentProject(wb);
        if (action === 'project_launch') {
            openProject(project);
            render();
            return;
        }
        if (action === 'project_test') {
            if (safeString(wb.selectedEngine) !== 'unreal') {
                moduleWorkbenchPushLog(wb.logs, 'Automated test trigger is currently wired for Unreal bridge.', 'warn', 80, 'game-log');
                render();
                return;
            }
            const bridge = moduleGameStudioBridgeState(wb);
            runBridgeAction(
                () => moduleGameStudioRemoteSend(wb, {
                    objectPath: bridge.actorSyncPath,
                    functionName: 'RunSmokeTest',
                    parameters: {
                        project: safeString(project?.name),
                    },
                }),
                {
                    successMessage: `Smoke test trigger sent${project ? ` for ${safeString(project.name)}` : ''}.`,
                    failureMessage: 'Smoke test trigger failed',
                },
            );
            return;
        }
        if (action === 'project_build') {
            buildProject(project);
            render();
            return;
        }
        if (action === 'project_plan') {
            planProject(project);
            render();
            return;
        }
        if (action === 'project_remove') {
            if (!project) return;
            const engine = safeString(wb.selectedEngine);
            wb.engineProjects[engine] = (Array.isArray(wb.engineProjects[engine]) ? wb.engineProjects[engine] : [])
                .filter((row) => safeString(row.id) !== safeString(project.id));
            wb.activeProjectByEngine[engine] = safeString(wb.engineProjects[engine][0]?.id);
            moduleWorkbenchPushLog(wb.logs, `Removed project ${safeString(project.name)}.`, 'warn', 80, 'game-log');
            render();
            return;
        }
        if (action === 'bridge_ping') {
            runBridgeAction(
                () => moduleGameStudioBridgePing(wb, { silent: true }),
                { successMessage: 'Bridge ping successful.', failureMessage: 'Bridge ping failed' },
            );
            return;
        }
        if (action === 'bridge_pull') {
            runBridgeAction(
                () => moduleGameStudioBridgePullState(wb),
                { successMessage: 'Bridge state pulled.', failureMessage: 'Bridge pull failed' },
            );
            return;
        }
        if (action === 'bridge_push_scene') {
            runBridgeAction(
                () => moduleGameStudioBridgePushScene(wb),
                { successMessage: 'Scene pushed to bridge.', failureMessage: 'Bridge push failed' },
            );
            return;
        }
        if (action === 'chat_clear') {
            wb.studioChat = [{
                id: `chat-reset-${Date.now()}`,
                role: 'assistant',
                text: 'Chat reset. Tell me what game outcome you want next.',
                time: moduleWorkbenchTimeStamp(),
            }];
            render();
        }
    });

    projectForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const engine = moduleGameStudioEngineById(wb.selectedEngine);
        const name = safeString(wb.projectDraftName).trim() || `New ${safeString(engine.label)} Project`;
        const pathValue = safeString(wb.projectDraftPath).trim() || safeString(engine.pathHint);
        const project = moduleGameStudioProjectNormalize({
            id: `${safeString(engine.id)}-project-${Date.now()}`,
            name,
            path: pathValue,
            status: 'planning',
            focus: 'Define first playable objective and milestone.',
            learning: 'Identify highest-risk mechanic and test it early.',
            tasks: ['Define core loop', 'Set first milestone', 'Run smoke test'],
            updatedAt: Date.now(),
        }, '', engine.id);
        wb.engineProjects[engine.id] = [project, ...(Array.isArray(wb.engineProjects[engine.id]) ? wb.engineProjects[engine.id] : [])]
            .slice(0, 120);
        wb.activeProjectByEngine[engine.id] = safeString(project.id);
        wb.projectDraftName = '';
        wb.projectDraftPath = safeString(engine.pathHint);
        moduleWorkbenchPushLog(wb.logs, `Created ${safeString(engine.label)} project ${safeString(project.name)}.`, 'ok', 80, 'game-log');
        pushChat('assistant', `Project ${safeString(project.name)} created in ${safeString(engine.label)} workspace.`);
        render();
    });

    projectNameInput.addEventListener('input', () => {
        wb.projectDraftName = safeString(projectNameInput.value).slice(0, 140);
    });
    projectPathInput.addEventListener('input', () => {
        wb.projectDraftPath = safeString(projectPathInput.value).slice(0, 260);
    });

    chatForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const prompt = safeString(wb.chatDraft).trim();
        if (!prompt) return;
        pushChat('user', prompt);
        const reply = moduleGameStudioAssistantReply(wb);
        pushChat('assistant', reply);
        wb.chatDraft = '';
        render();
    });
    chatInput.addEventListener('input', () => {
        wb.chatDraft = safeString(chatInput.value).slice(0, 1200);
    });

    return true;
}

