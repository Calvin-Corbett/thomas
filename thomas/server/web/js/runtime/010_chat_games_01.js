function chatGameCreateJetpackObstacle(state, xOverride = null) {
    const hasXOverride = xOverride !== null && xOverride !== undefined && Number.isFinite(Number(xOverride));
    const spawnX = hasXOverride
        ? Number(xOverride)
        : (state.width + chatGameRandom(48, 138));
    const roll = Math.random();
    const bounds = chatGameGetJetpackFlightBounds(state);
    const centerMinY = bounds.minY + 42;
    const centerMaxY = Math.max(centerMinY, bounds.maxY - 42);

    if (roll < 0.58) {
        const angles = [-64, -48, -32, -18, 18, 32, 48, 64];
        const angleDeg = angles[Math.floor(Math.random() * angles.length)];
        return {
            id: state.obstacleSeq++,
            type: 'zapper',
            cx: spawnX,
            cy: chatGameRandom(centerMinY, centerMaxY),
            length: Math.round(chatGameRandom(JETPACK_ZAPPER_LENGTH_MIN, JETPACK_ZAPPER_LENGTH_MAX)),
            thickness: JETPACK_ZAPPER_THICKNESS,
            angle: angleDeg * (Math.PI / 180),
            passed: false,
        };
    }

    if (roll < 0.84) {
        const missileMinY = bounds.minY + 10;
        const missileMaxY = Math.max(missileMinY, bounds.maxY - JETPACK_MISSILE_HEIGHT - 10);
        return {
            id: state.obstacleSeq++,
            type: 'missile',
            x: spawnX,
            y: chatGameRandom(missileMinY, missileMaxY),
            w: JETPACK_MISSILE_WIDTH,
            h: JETPACK_MISSILE_HEIGHT,
            vy: chatGameRandom(-0.44, 0.44),
            passed: false,
        };
    }

    const laserHeight = Math.round(chatGameRandom(JETPACK_LASER_HEIGHT_MIN, JETPACK_LASER_HEIGHT_MAX));
    const side = Math.random() < 0.5 ? 'top' : 'bottom';
    return {
        id: state.obstacleSeq++,
        type: 'laser_wall',
        x: spawnX,
        y: side === 'top' ? 0 : Math.max(0, state.height - laserHeight),
        w: JETPACK_LASER_WIDTH,
        h: laserHeight,
        side,
        passed: false,
    };
}

function chatGameGetJetpackObstacleHorizontalBounds(obstacle) {
    if (!obstacle) return { left: 0, right: 0 };
    if (obstacle.type === 'zapper') {
        const halfLength = (obstacle.length || 0) * 0.5;
        const dx = Math.cos(obstacle.angle || 0) * halfLength;
        const edgePadding = (obstacle.thickness || 0) * 0.5;
        const left = Math.min((obstacle.cx || 0) - dx, (obstacle.cx || 0) + dx) - edgePadding;
        const right = Math.max((obstacle.cx || 0) - dx, (obstacle.cx || 0) + dx) + edgePadding;
        return { left, right };
    }
    return {
        left: obstacle.x || 0,
        right: (obstacle.x || 0) + (obstacle.w || 0),
    };
}

function chatGameGetJetpackObstacleRightEdge(obstacle) {
    return chatGameGetJetpackObstacleHorizontalBounds(obstacle).right;
}

function chatGameStepJetpackObstacle(obstacle, state, deltaFrames) {
    if (!obstacle || !state) return;
    const scroll = state.scrollSpeed * deltaFrames;
    if (obstacle.type === 'zapper') {
        obstacle.cx -= scroll;
        return;
    }

    obstacle.x -= scroll;
    if (obstacle.type === 'missile') {
        obstacle.y += (obstacle.vy || 0) * deltaFrames;
        const bounds = chatGameGetJetpackFlightBounds(state, obstacle.h || 0);
        if (obstacle.y <= bounds.minY || obstacle.y >= bounds.maxY) {
            obstacle.vy = -(obstacle.vy || 0);
            obstacle.y = chatGameClamp(obstacle.y, bounds.minY, bounds.maxY);
        }
    }
}

function chatGameJetpackObstacleCollision(state, obstacle) {
    if (!state || !obstacle) return false;
    const player = state.player;
    const hitX = player.x + (player.w * 0.53);
    const hitY = player.y + (player.h * 0.54);
    const hitRadius = Math.max(7, (Math.min(player.w, player.h) * 0.34) - JETPACK_HITBOX_PADDING);

    if (obstacle.type === 'zapper') {
        const halfLength = (obstacle.length || 0) * 0.5;
        const dx = Math.cos(obstacle.angle || 0) * halfLength;
        const dy = Math.sin(obstacle.angle || 0) * halfLength;
        const x1 = (obstacle.cx || 0) - dx;
        const y1 = (obstacle.cy || 0) - dy;
        const x2 = (obstacle.cx || 0) + dx;
        const y2 = (obstacle.cy || 0) + dy;
        const hitDistance = hitRadius + ((obstacle.thickness || JETPACK_ZAPPER_THICKNESS) * 0.52);
        return chatGameDistanceToSegmentSquared(hitX, hitY, x1, y1, x2, y2) <= (hitDistance * hitDistance);
    }

    return chatGameCircleRectOverlap(
        hitX,
        hitY,
        hitRadius,
        obstacle.x || 0,
        obstacle.y || 0,
        obstacle.w || 0,
        obstacle.h || 0,
    );
}

function chatGameComputeJetpackIntroPose(state, progress) {
    const targetX = state.player.x;
    const targetY = state.player.y;
    const p = chatGameClamp(progress, 0, 1);
    const eased = chatGameEaseOutCubic(p);
    const settle = chatGameEaseInOutCubic(chatGameClamp((p - 0.72) / 0.28, 0, 1));
    const stuntPower = ((1 - p) ** 1.05);

    const travelX = chatGameLerp(JETPACK_FLIGHT_START_X, targetX, eased);
    const travelY = chatGameLerp(JETPACK_FLIGHT_START_Y, targetY, eased);
    const swirlX = Math.sin((p * Math.PI * 8.8) + 0.35) * (132 * stuntPower);
    const swirlY = Math.cos((p * Math.PI * 11.4) + 0.82) * (74 * stuntPower);
    const figureY = Math.sin(p * Math.PI * 4.6) * Math.sin(p * Math.PI * 9.2) * (58 * stuntPower);
    const preSettleX = travelX + swirlX;
    const preSettleY = travelY + swirlY + figureY;

    return {
        x: chatGameLerp(preSettleX, targetX, settle),
        y: chatGameLerp(preSettleY, targetY, settle),
        rotate: (Math.sin(p * Math.PI * 10.6) * 95 * stuntPower) + (Math.cos(p * Math.PI * 5.4) * 24 * stuntPower),
        scale: chatGameClamp(
            0.16 + (eased * 0.92) + (Math.sin(p * Math.PI * 7.2) * 0.08 * stuntPower),
            0.16,
            1.08,
        ),
    };
}

function chatGameResetJetpackJoyride() {
    if (!(chatGameCanvas instanceof HTMLCanvasElement)) return;
    const surface = chatGameResizeCanvas();
    const width = surface.width;
    const height = surface.height;
    const best = chatGameGetHighScore(JETPACK_GAME_ID);
    const selectedAgent = chatGamePickOfficeAgentForRun();
    const playerX = chatGameClamp((width * JETPACK_PLAYER_X_RATIO) - 15, 40, Math.max(40, width - 76));
    const bounds = chatGameGetJetpackFlightBounds({ height }, 34);
    const playerY = chatGameClamp((height * JETPACK_PLAYER_Y_RATIO), bounds.minY, bounds.maxY);
    const state = {
        id: JETPACK_GAME_ID,
        selectedAgent,
        mode: 'intro',
        width,
        height,
        tick: 0,
        introSeconds: 0,
        score: 0,
        best,
        playFrames: 0,
        moveSpeed: JETPACK_MOVE_SPEED,
        scrollSpeed: JETPACK_SCROLL_BASE,
        spawnFrames: 24,
        obstacleSeq: 1,
        obstacles: [],
        player: {
            x: playerX,
            y: playerY,
            w: 30,
            h: 34,
            vx: 0,
            vy: 0,
            facing: 1,
        },
        scene: {
            doorVisible: false,
            doorOpen: 0,
            light: 0,
            botVisible: true,
            botRunning: false,
            botInside: false,
            botDoorOffsetX: 0,
            botX: JETPACK_FLIGHT_START_X,
            botY: JETPACK_FLIGHT_START_Y,
            botScale: 0.16,
            botRotate: 0,
            botJetpack: true,
        },
    };
    chatGameRuntime.jetpackJoyride = state;
    chatGameRuntime.lastFrameMs = 0;
    chatGameUpdateHud(state);
    chatGameSetStatusText('Jetpack inbound...');
    chatGameSyncScene(state);
}

function chatGameStartJetpackRun(state = chatGameRuntime.jetpackJoyride) {
    if (!state || state.mode !== 'ready') return false;
    state.mode = 'playing';
    state.score = 0;
    state.playFrames = 0;
    state.obstacles = [];
    state.spawnFrames = 10;
    state.scrollSpeed = JETPACK_SCROLL_BASE;
    state.player.vx = 0;
    state.player.vy = 0;
    if (state.scene) {
        state.scene.botRotate = 0;
    }
    chatGameSetStatusText('Run active. Use Up/Down to dodge hazards.');
    chatGameSyncScene(state);
    return true;
}

function chatGameStepJetpackIntro(state, deltaFrames) {
    const stepSeconds = deltaFrames / 60;
    state.tick += deltaFrames;
    state.introSeconds += stepSeconds;

    const player = state.player;
    const scene = state.scene;
    const elapsed = state.introSeconds;
    const targetX = player.x;
    const targetY = player.y;

    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botJetpack = true;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botRunning = false;

    if (elapsed < JETPACK_INTRO_DURATION_SECONDS) {
        const progress = chatGameClamp(elapsed / JETPACK_INTRO_DURATION_SECONDS, 0, 1);
        const pose = chatGameComputeJetpackIntroPose(state, progress);
        scene.botScale = pose.scale;
        scene.botRotate = pose.rotate;
        scene.botX = pose.x;
        scene.botY = pose.y;
        player.vy = 0;
    } else {
        state.mode = 'ready';
        scene.botScale = 1;
        scene.botRotate = 0;
        scene.botX = targetX;
        scene.botY = targetY;
        player.vy = 0;
        chatGameSetStatusText('Press Space to start | Esc to exit');
    }
}

function chatGameStepJetpackReady(state, deltaFrames) {
    state.tick += deltaFrames;
    const scene = state.scene;
    const player = state.player;
    const bounds = chatGameGetJetpackFlightBounds(state, player.h);
    player.y = chatGameClamp(player.y, bounds.minY, bounds.maxY);
    player.vx = 0;
    player.vy = 0;

    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botRunning = false;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botScale = 1;
    scene.botRotate = Math.sin(state.tick * 0.08) * 2.2;
    scene.botJetpack = true;
    scene.botX = player.x;
    scene.botY = player.y + (Math.sin(state.tick * 0.11) * 1.2);
}

function chatGameStepJetpackPlaying(state, deltaFrames) {
    state.tick += deltaFrames;
    state.playFrames += deltaFrames;
    const player = state.player;
    const scene = state.scene;
    const movingUp = Boolean(chatGameRuntime.input.up) && !Boolean(chatGameRuntime.input.down);
    const movingDown = Boolean(chatGameRuntime.input.down) && !Boolean(chatGameRuntime.input.up);
    const moveSpeed = state.moveSpeed || JETPACK_MOVE_SPEED;

    if (movingUp) {
        player.y -= moveSpeed * deltaFrames;
        player.vy = -moveSpeed;
    } else if (movingDown) {
        player.y += moveSpeed * deltaFrames;
        player.vy = moveSpeed;
    } else {
        player.vy = 0;
    }

    const bounds = chatGameGetJetpackFlightBounds(state, player.h);
    player.y = chatGameClamp(player.y, bounds.minY, bounds.maxY);

    state.scrollSpeed = JETPACK_SCROLL_BASE + Math.min(JETPACK_SCROLL_MAX_BONUS, state.score * 0.028);
    state.spawnFrames -= deltaFrames;
    if (state.spawnFrames <= 0) {
        state.obstacles.push(chatGameCreateJetpackObstacle(state));
        state.spawnFrames = chatGameRandom(JETPACK_SPAWN_FRAMES_MIN, JETPACK_SPAWN_FRAMES_MAX);
    }

    let crashed = false;
    state.obstacles.forEach((obstacle) => {
        chatGameStepJetpackObstacle(obstacle, state, deltaFrames);
        const rightEdge = chatGameGetJetpackObstacleRightEdge(obstacle);
        if (!obstacle.passed && rightEdge < player.x) {
            obstacle.passed = true;
            state.score += 1;
        }
        if (!crashed && chatGameJetpackObstacleCollision(state, obstacle)) {
            crashed = true;
        }
    });
    state.obstacles = state.obstacles.filter((obstacle) => chatGameGetJetpackObstacleRightEdge(obstacle) > -56);

    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botRunning = movingUp || movingDown;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botScale = 1;
    scene.botJetpack = true;
    scene.botRotate = movingUp ? -10 : (movingDown ? 10 : Math.sin(state.tick * 0.06) * 2);
    scene.botX = player.x;
    scene.botY = player.y;

    if (crashed) {
        state.mode = 'game_over';
        state.best = Math.max(state.best, state.score);
        chatGameSetHighScore(state.best, JETPACK_GAME_ID);
        player.vy = 0;
        scene.botRotate = 0;
        scene.botJetpack = false;
        chatGameSetStatusText('Run ended. Space to run again | Esc to exit');
    }
}

function chatGameStepJetpackGameOver(state, deltaFrames) {
    state.tick += deltaFrames;
    const scene = state.scene;
    const player = state.player;
    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botRunning = false;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botScale = 1;
    scene.botRotate = 0;
    scene.botJetpack = false;
    scene.botX = player.x;
    scene.botY = player.y + (Math.sin(state.tick * 0.06) * 0.5);
}

function chatGameStepJetpack(deltaFrames) {
    const state = chatGameRuntime.jetpackJoyride;
    if (!state) return;
    const frames = Number.isFinite(deltaFrames) ? Math.max(0, deltaFrames) : 1;

    if (state.mode === 'intro') {
        chatGameStepJetpackIntro(state, frames);
    } else if (state.mode === 'ready') {
        chatGameStepJetpackReady(state, frames);
    } else if (state.mode === 'playing') {
        chatGameStepJetpackPlaying(state, frames);
    } else if (state.mode === 'game_over') {
        chatGameStepJetpackGameOver(state, frames);
    }
    chatGameUpdateHud(state);
    chatGameSyncScene(state);
}

function chatGameRenderJetpack() {
    if (!(chatGameCanvas instanceof HTMLCanvasElement)) return;
    const ctx = chatGameCanvas.getContext('2d');
    const state = chatGameRuntime.jetpackJoyride;
    if (!ctx || !state) return;

    const width = state.width;
    const height = state.height;
    ctx.clearRect(0, 0, width, height);

    state.obstacles.forEach((obstacle) => {
        if (obstacle.type === 'zapper') {
            const halfLength = (obstacle.length || 0) * 0.5;
            const dx = Math.cos(obstacle.angle || 0) * halfLength;
            const dy = Math.sin(obstacle.angle || 0) * halfLength;
            const x1 = (obstacle.cx || 0) - dx;
            const y1 = (obstacle.cy || 0) - dy;
            const x2 = (obstacle.cx || 0) + dx;
            const y2 = (obstacle.cy || 0) + dy;
            const thickness = obstacle.thickness || JETPACK_ZAPPER_THICKNESS;

            ctx.lineCap = 'round';
            ctx.strokeStyle = 'rgba(100, 200, 255, 0.26)';
            ctx.lineWidth = thickness + 8;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();

            ctx.strokeStyle = 'rgba(56, 165, 248, 0.96)';
            ctx.lineWidth = thickness;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();

            ctx.fillStyle = 'rgba(228, 246, 255, 0.95)';
            ctx.beginPath();
            ctx.arc(x1, y1, (thickness * 0.55), 0, Math.PI * 2);
            ctx.arc(x2, y2, (thickness * 0.55), 0, Math.PI * 2);
            ctx.fill();
            return;
        }

        if (obstacle.type === 'missile') {
            const x = obstacle.x || 0;
            const y = obstacle.y || 0;
            const w = obstacle.w || JETPACK_MISSILE_WIDTH;
            const h = obstacle.h || JETPACK_MISSILE_HEIGHT;
            const nose = 10;

            ctx.fillStyle = 'rgba(58, 170, 248, 0.96)';
            ctx.fillRect(x, y, w, h);
            ctx.fillStyle = 'rgba(228, 246, 255, 0.92)';
            ctx.fillRect(x + 2, y + 2, Math.max(6, w - 10), 4);
            ctx.beginPath();
            ctx.moveTo(x + w, y + 2);
            ctx.lineTo(x + w + nose, y + (h * 0.5));
            ctx.lineTo(x + w, y + h - 2);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = 'rgba(255, 168, 86, 0.9)';
            ctx.fillRect(x - 6, y + 5, 6, Math.max(4, h - 10));
            return;
        }

        if (obstacle.type === 'laser_wall') {
            const x = obstacle.x || 0;
            const y = obstacle.y || 0;
            const w = obstacle.w || JETPACK_LASER_WIDTH;
            const h = obstacle.h || 0;
            const beamAlpha = 0.68 + (Math.sin((state.tick * 0.07) + (obstacle.id * 0.2)) * 0.14);

            ctx.fillStyle = `rgba(64, 184, 255, ${chatGameClamp(beamAlpha, 0.42, 0.92).toFixed(3)})`;
            ctx.fillRect(x, y, w, h);
            ctx.fillStyle = 'rgba(227, 246, 255, 0.9)';
            ctx.fillRect(x + 2, y + 2, Math.max(0, w - 4), 4);
            ctx.fillRect(x + 2, Math.max(y + h - 6, y), Math.max(0, w - 4), 4);
            ctx.fillStyle = 'rgba(118, 211, 255, 0.26)';
            ctx.fillRect(x - 4, y, 4, h);
        }
    });

    if (state.mode === 'game_over') {
        ctx.fillStyle = 'rgba(236, 246, 255, 0.88)';
        ctx.font = '700 14px "Segoe UI", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Run Ended', width * 0.5, Math.max(36, height * 0.18));
    }
    chatGameSyncScene(state);
}

function chatGameCreateDinoObstacle(state) {
    const roll = Math.random();
    if (roll < 0.22) {
        const w = Math.round(chatGameRandom(30, 48));
        const h = Math.round(chatGameRandom(18, 28));
        return {
            id: state.obstacleSeq++,
            type: 'drone',
            x: state.width + chatGameRandom(18, 96),
            y: Math.round(state.groundY - chatGameRandom(44, 92)),
            w,
            h,
            passed: false,
        };
    }
    const w = Math.round(chatGameRandom(16, 32));
    const h = Math.round(chatGameRandom(24, 46));
    return {
        id: state.obstacleSeq++,
        type: 'cactus',
        x: state.width + chatGameRandom(18, 96),
        y: Math.round(state.groundY + DINO_PLAYER_NORMAL_HEIGHT - h),
        w,
        h,
        passed: false,
    };
}

function chatGameResetDinoRun() {
    if (!(composerDinoCanvas instanceof HTMLCanvasElement)) return;
    const surface = chatGameResizeDinoCanvas();
    const width = surface.width;
    const height = surface.height;
    const selectedAgent = chatGamePickOfficeAgentForRun();
    const best = chatGameGetHighScore(DINO_GAME_ID);
    const playerX = chatGameClamp((width * DINO_PLAYER_X_RATIO), 48, Math.max(48, width - 140));
    const portalAnchor = chatGameGetPortalAnchorInDino({ width, height });
    const groundY = height - DINO_GROUND_PADDING - DINO_PLAYER_NORMAL_HEIGHT;
    const portalY = chatGameClamp(Math.min(portalAnchor.y - 18, groundY + 4), 18, height - 52);
    const state = {
        id: DINO_GAME_ID,
        selectedAgent,
        mode: 'intro',
        width,
        height,
        tick: 0,
        introSeconds: 0,
        playFrames: 0,
        score: 0,
        best,
        speed: DINO_SCROLL_BASE,
        spawnFrames: 36,
        obstacleSeq: 1,
        scrollX: 0,
        groundY,
        portal: {
            x: portalAnchor.x,
            y: portalY,
            visible: true,
            spin: 0,
            scale: 0.26,
            glow: 0.84,
        },
        player: {
            x: playerX,
            y: 0,
            w: DINO_PLAYER_WIDTH,
            h: DINO_PLAYER_NORMAL_HEIGHT,
            vx: 0,
            vy: 0,
            onGround: true,
            ducking: false,
            facing: 1,
        },
        obstacles: [],
        scene: {
            doorVisible: false,
            doorOpen: 0,
            light: 0,
            botVisible: true,
            botRunning: false,
            botInside: false,
            botDoorOffsetX: 0,
            botX: portalAnchor.x,
            botY: portalY,
            botScale: 0.3,
            botRotate: 0,
            botJetpack: false,
        },
    };
    state.player.y = state.groundY;
    chatGameRuntime.dinoRun = state;
    chatGameRuntime.lastFrameMs = 0;
    chatGameUpdateHud(state);
    chatGameSetStatusText('Portal spin-up...');
    chatGameSyncScene(state);

    const stabilizePortalAnchor = () => {
        const live = chatGameRuntime.dinoRun;
        if (!live || live.id !== DINO_GAME_ID || live.mode !== 'intro') return;
        const nextAnchor = chatGameGetPortalAnchorInDino(live);
        live.portal.x = nextAnchor.x;
        live.portal.y = chatGameClamp(Math.min(nextAnchor.y - 18, live.groundY + 4), 18, live.height - 52);
        if (live.introSeconds < 0.16) {
            live.scene.botX = nextAnchor.x;
            live.scene.botY = live.portal.y;
        }
        chatGameSyncScene(live);
    };

    window.requestAnimationFrame(() => {
        stabilizePortalAnchor();
        window.requestAnimationFrame(stabilizePortalAnchor);
    });
}

function chatGameStartDinoRun(state = chatGameRuntime.dinoRun) {
    if (!state || state.mode !== 'ready') return false;
    state.mode = 'playing';
    state.score = 0;
    state.playFrames = 0;
    state.speed = DINO_SCROLL_BASE;
    state.spawnFrames = chatGameRandom(DINO_SPAWN_FRAMES_MIN, DINO_SPAWN_FRAMES_MAX);
    state.obstacles = [];
    state.player.vy = 0;
    state.player.onGround = true;
    state.player.ducking = false;
    state.player.h = DINO_PLAYER_NORMAL_HEIGHT;
    state.player.y = state.height - DINO_GROUND_PADDING - state.player.h;
    state.portal.visible = false;
    chatGameSetStatusText('Run active. Space to jump | Down to duck.');
    chatGameSyncScene(state);
    return true;
}

function chatGameDinoJump(state = chatGameRuntime.dinoRun) {
    if (!state || state.mode !== 'playing') return false;
    const player = state.player;
    if (!player.onGround) return false;
    player.vy = DINO_JUMP_VELOCITY;
    player.onGround = false;
    return true;
}

function chatGameSetDinoDuck(state, wantsDuck) {
    const player = state?.player;
    if (!player || !player.onGround) return;
    if (wantsDuck && !player.ducking) {
        const delta = DINO_PLAYER_NORMAL_HEIGHT - DINO_PLAYER_DUCK_HEIGHT;
        player.ducking = true;
        player.h = DINO_PLAYER_DUCK_HEIGHT;
        player.y += delta;
    } else if (!wantsDuck && player.ducking) {
        const delta = DINO_PLAYER_NORMAL_HEIGHT - DINO_PLAYER_DUCK_HEIGHT;
        player.ducking = false;
        player.h = DINO_PLAYER_NORMAL_HEIGHT;
        player.y -= delta;
    }
}

function chatGameDinoCollision(state, obstacle) {
    const player = state?.player;
    if (!player || !obstacle) return false;
    const padding = 4;
    const px = player.x + padding;
    const py = player.y + padding;
    const pw = Math.max(1, player.w - (padding * 2));
    const ph = Math.max(1, player.h - (padding * 2));
    return (
        px < obstacle.x + obstacle.w
        && px + pw > obstacle.x
        && py < obstacle.y + obstacle.h
        && py + ph > obstacle.y
    );
}

function chatGameStepDinoIntro(state, deltaFrames) {
    state.tick += deltaFrames;
    state.introSeconds += (deltaFrames / 60);
    const scene = state.scene;
    const player = state.player;
    const portal = state.portal;
    const progress = chatGameClamp(state.introSeconds / DINO_INTRO_DURATION_SECONDS, 0, 1);
    const warmup = chatGameClamp(progress / 0.34, 0, 1);
    const walkProgress = chatGameEaseOutCubic(chatGameClamp((progress - 0.34) / 0.62, 0, 1));

    portal.visible = progress < 0.95;
    portal.spin += (deltaFrames * chatGameLerp(33, 16, warmup));
    portal.scale = chatGameLerp(0.24, 1.46, warmup) + (Math.sin(state.tick * 0.11) * (0.03 + (0.05 * warmup)));
    portal.glow = 0.82 + (Math.sin(state.tick * 0.11) * 0.14);

    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botVisible = progress > 0.34;
    scene.botRunning = walkProgress > 0.06 && walkProgress < 0.98;
    scene.botJetpack = false;
    scene.botScale = chatGameClamp(0.74 + (walkProgress * 0.26), 0.7, 1);
    scene.botRotate = 0;
    scene.botX = chatGameLerp(portal.x + 1, player.x, walkProgress);
    scene.botY = state.groundY;
    player.y = state.groundY;
    player.vy = 0;
    player.onGround = true;

    if (progress >= 1) {
        state.mode = 'ready';
        scene.botVisible = true;
        scene.botRunning = false;
        scene.botScale = 1;
        scene.botRotate = 0;
        scene.botX = player.x;
        scene.botY = player.y;
        portal.visible = false;
        chatGameSetStatusText('Press Space to start | Esc to exit');
    }
}

function chatGameStepDinoReady(state, deltaFrames) {
    state.tick += deltaFrames;
    state.scrollX += (DINO_SCROLL_BASE * 0.38) * deltaFrames;
    const scene = state.scene;
    const player = state.player;
    player.ducking = false;
    player.h = DINO_PLAYER_NORMAL_HEIGHT;
    player.y = state.height - DINO_GROUND_PADDING - player.h;
    player.vy = 0;
    player.onGround = true;

    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botRunning = false;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botScale = 1;
    scene.botRotate = 0;
    scene.botJetpack = false;
    scene.botX = player.x;
    scene.botY = player.y + (Math.sin(state.tick * 0.12) * 0.9);
}

function chatGameStepDinoPlaying(state, deltaFrames) {
    state.tick += deltaFrames;
    state.playFrames += deltaFrames;
    const player = state.player;
    const scene = state.scene;

    chatGameSetDinoDuck(state, Boolean(chatGameRuntime.input.down));

    player.vy += DINO_GRAVITY * deltaFrames;
    player.vy = Math.min(player.vy, 16);
    player.y += player.vy * deltaFrames;
    const groundY = state.height - DINO_GROUND_PADDING - player.h;
    if (player.y >= groundY) {
        player.y = groundY;
        player.vy = 0;
        player.onGround = true;
    } else {
        player.onGround = false;
    }

    state.speed = DINO_SCROLL_BASE + Math.min(DINO_SCROLL_MAX_BONUS, (Math.floor(state.score) * 0.015));
    state.spawnFrames -= deltaFrames;
    if (state.spawnFrames <= 0) {
        state.obstacles.push(chatGameCreateDinoObstacle(state));
        const speedTighten = Math.min(24, Math.floor(state.score) * 0.02);
        state.spawnFrames = chatGameRandom(
            Math.max(30, DINO_SPAWN_FRAMES_MIN - speedTighten),
            Math.max(46, DINO_SPAWN_FRAMES_MAX - speedTighten),
        );
    }

    state.scrollX += state.speed * deltaFrames;
    let crashed = false;
    state.obstacles.forEach((obstacle) => {
        obstacle.x -= state.speed * deltaFrames;
        if (!obstacle.passed && (obstacle.x + obstacle.w) < player.x) {
            obstacle.passed = true;
            state.score += 1;
        }
        if (!crashed && chatGameDinoCollision(state, obstacle)) {
            crashed = true;
        }
    });
    state.obstacles = state.obstacles.filter((obstacle) => (obstacle.x + obstacle.w) >= -28);
    state.score += state.speed * deltaFrames * 0.11;

    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botRunning = player.onGround && !player.ducking;
    scene.botScale = player.ducking ? 0.9 : 1;
    scene.botRotate = player.onGround ? 0 : -8;
    scene.botJetpack = false;
    scene.botX = player.x;
    scene.botY = player.y;

    if (crashed) {
        state.mode = 'game_over';
        state.best = Math.max(state.best, Math.floor(state.score));
        chatGameSetHighScore(state.best, DINO_GAME_ID);
        player.vy = 0;
        scene.botRunning = false;
        scene.botScale = 1;
        scene.botRotate = 0;
        chatGameSetStatusText('Run ended. Space to run again | Esc to exit');
    }
}

function chatGameStepDinoGameOver(state, deltaFrames) {
    state.tick += deltaFrames;
    const scene = state.scene;
    const player = state.player;
    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botRunning = false;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botScale = 1;
    scene.botRotate = 0;
    scene.botJetpack = false;
    scene.botX = player.x;
    scene.botY = player.y + (Math.sin(state.tick * 0.08) * 0.5);
}

function chatGameStepDino(deltaFrames) {
    const state = chatGameRuntime.dinoRun;
    if (!state) return;
    const frames = Number.isFinite(deltaFrames) ? Math.max(0, deltaFrames) : 1;

    if (state.mode === 'intro') {
        chatGameStepDinoIntro(state, frames);
    } else if (state.mode === 'ready') {
        chatGameStepDinoReady(state, frames);
    } else if (state.mode === 'playing') {
        chatGameStepDinoPlaying(state, frames);
    } else if (state.mode === 'game_over') {
        chatGameStepDinoGameOver(state, frames);
    }
    chatGameUpdateHud(state);
    chatGameSyncScene(state);
}

function chatGameRenderDino() {
    if (!(composerDinoCanvas instanceof HTMLCanvasElement)) return;
    const ctx = composerDinoCanvas.getContext('2d');
    const state = chatGameRuntime.dinoRun;
    if (!ctx || !state) return;
    const width = state.width;
    const height = state.height;
    const groundY = state.height - DINO_GROUND_PADDING;

    ctx.clearRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(98, 188, 255, 0.9)';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(0, groundY);
    ctx.lineTo(width, groundY);
    ctx.stroke();

    const stripeStep = 24;
    const stripeOffset = (state.scrollX % stripeStep);
    ctx.fillStyle = 'rgba(193, 232, 255, 0.84)';
    for (let x = -stripeStep; x < width + stripeStep; x += stripeStep) {
        const drawX = Math.round(x - stripeOffset);
        ctx.fillRect(drawX, groundY + 4, 10, 2);
    }

    state.obstacles.forEach((obstacle) => {
        if (obstacle.type === 'drone') {
            ctx.fillStyle = 'rgba(83, 179, 248, 0.92)';
            ctx.fillRect(obstacle.x, obstacle.y + 3, obstacle.w, obstacle.h - 6);
            ctx.fillStyle = 'rgba(232, 247, 255, 0.94)';
            ctx.fillRect(obstacle.x + 4, obstacle.y + 5, Math.max(8, obstacle.w - 8), 4);
            ctx.fillStyle = 'rgba(255, 173, 104, 0.88)';
            ctx.fillRect(obstacle.x - 3, obstacle.y + (obstacle.h * 0.5) - 2, 3, 4);
            return;
        }
        ctx.fillStyle = 'rgba(66, 176, 246, 0.96)';
        ctx.fillRect(obstacle.x, obstacle.y, obstacle.w, obstacle.h);
        ctx.fillStyle = 'rgba(228, 246, 255, 0.92)';
        ctx.fillRect(obstacle.x + 2, obstacle.y + 2, Math.max(4, obstacle.w - 4), 3);
    });

    if (state.mode === 'game_over') {
        ctx.fillStyle = 'rgba(236, 246, 255, 0.88)';
        ctx.font = '700 14px "Segoe UI", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Run Ended', width * 0.5, Math.max(28, height * 0.24));
    }
    chatGameSyncScene(state);
}

function chatGameStep(deltaFrames = 1) {
    const frames = Number.isFinite(deltaFrames) ? Math.max(0, deltaFrames) : 1;
    if (chatGameRuntime.activeGameId === 'cloud_jump') {
        chatGameStepCloudJump(frames);
    } else if (chatGameRuntime.activeGameId === JETPACK_GAME_ID) {
        chatGameStepJetpack(frames);
    } else if (chatGameRuntime.activeGameId === DINO_GAME_ID) {
        chatGameStepDino(frames);
    }
}

function chatGameRender() {
    if (chatGameRuntime.activeGameId === 'cloud_jump') {
        chatGameRenderCloudJump();
    } else if (chatGameRuntime.activeGameId === JETPACK_GAME_ID) {
        chatGameRenderJetpack();
    } else if (chatGameRuntime.activeGameId === DINO_GAME_ID) {
        chatGameRenderDino();
    }
}

function chatGameStartLoop() {
    chatGameStopLoop();
    const runFrame = (timestampMs) => {
        if (!chatGameRuntime.activeGameId) return;
        if (!chatGameRuntime.lastFrameMs) {
            chatGameRuntime.lastFrameMs = timestampMs;
        }
        const elapsedMs = Math.max(0, timestampMs - chatGameRuntime.lastFrameMs);
        chatGameRuntime.lastFrameMs = timestampMs;
        const deltaFrames = Math.min(2.8, Math.max(0.6, elapsedMs / (1000 / 60)));
        chatGameStep(deltaFrames);
        chatGameRender();
        chatGameRuntime.rafId = window.requestAnimationFrame(runFrame);
    };
    chatGameRuntime.rafId = window.requestAnimationFrame(runFrame);
}

function chatGameStopLoop() {
    if (chatGameRuntime.rafId) {
        window.cancelAnimationFrame(chatGameRuntime.rafId);
    }
    chatGameRuntime.rafId = 0;
    chatGameRuntime.lastFrameMs = 0;
}

function chatGameOpen(gameId = 'cloud_jump') {
    const gameKey = String(gameId || '').trim().toLowerCase();
    if (gameKey !== 'cloud_jump' && gameKey !== JETPACK_GAME_ID && gameKey !== DINO_GAME_ID) return;
    if (gameKey === DINO_GAME_ID && !(composerDinoCanvas instanceof HTMLCanvasElement)) return;
    if (gameKey !== DINO_GAME_ID && !(chatGameCanvas instanceof HTMLCanvasElement)) return;
    chatGameToggleHiddenCanvasPriority(true);
    chatGameRuntime.activeGameId = gameKey;
    chatGameRuntime.input.left = false;
    chatGameRuntime.input.right = false;
    chatGameRuntime.input.up = false;
    chatGameRuntime.input.down = false;
    chatGameRuntime.input.thrust = false;
    chatGameRuntime.cloudJump = null;
    chatGameRuntime.jetpackJoyride = null;
    chatGameRuntime.dinoRun = null;
    const isDino = gameKey === DINO_GAME_ID;
    chatGameSetPanelOpen(!isDino);
    chatGameSetDinoSurfaceOpen(isDino);
    if (chatGamePanel) {
        chatGamePanel.classList.toggle('jetpack-mode', gameKey === JETPACK_GAME_ID);
    }
    chatGameSetCenterMuted(gameKey === JETPACK_GAME_ID);
    if (gameKey === 'cloud_jump') {
        chatGameResetCloudJump();
    } else if (gameKey === JETPACK_GAME_ID) {
        chatGameResetJetpackJoyride();
    } else {
        chatGameResetDinoRun();
    }
    chatGameRender();
    chatGameStartLoop();
}

function chatGameClose({ clearMode = false } = {}) {
    chatGameStopLoop();
    chatGameToggleHiddenCanvasPriority(false);
    const closingGameId = chatGameRuntime.activeGameId || 'cloud_jump';
    chatGameRuntime.activeGameId = '';
    chatGameRuntime.cloudJump = null;
    chatGameRuntime.jetpackJoyride = null;
    chatGameRuntime.dinoRun = null;
    chatGameRuntime.input.left = false;
    chatGameRuntime.input.right = false;
    chatGameRuntime.input.up = false;
    chatGameRuntime.input.down = false;
    chatGameRuntime.input.thrust = false;
    chatGameSetPanelOpen(false);
    chatGameSetDinoSurfaceOpen(false);
    chatGameSetCenterMuted(false);
    chatGameSetPhaseClass('');
    if (chatGamePanel) {
        chatGamePanel.classList.remove('door-visible');
        chatGamePanel.classList.remove('jetpack-mode');
    }
    if (chatGameDoor) {
        chatGameDoor.style.removeProperty('--door-open');
        chatGameDoor.style.removeProperty('--door-light');
    }
    if (chatGameBotWrap) {
        chatGameBotWrap.classList.remove('visible', 'inside-door', 'is-running', 'dir-left', 'jetpack-on', 'dino-ride');
        delete chatGameBotWrap.dataset.agentId;
        delete chatGameBotWrap.dataset.agentName;
        if (chatGameLane instanceof HTMLElement && chatGameBotWrap.parentElement !== chatGameLane) {
            chatGameLane.appendChild(chatGameBotWrap);
        }
        chatGameBotWrap.style.left = '0px';
        chatGameBotWrap.style.top = '0px';
        chatGameBotWrap.style.bottom = 'auto';
        chatGameBotWrap.style.transform = 'translate3d(0px, 0px, 0px) rotate(0deg) scale(1)';
        chatGameBotWrap.style.removeProperty('--bot-rotate');
    }
    if (chatGameBot) {
        chatGameBot.classList.remove('looking-user');
        chatGameBot.classList.remove('costume-cap', 'costume-visor', 'costume-headset', 'costume-bowtie');
        chatGameBot.style.removeProperty('--agent-primary');
        chatGameBot.style.removeProperty('--agent-secondary');
        chatGameBot.style.removeProperty('--agent-glow');
        chatGameBot.style.removeProperty('--agent-trim');
    }
    if (chatGameBotName) {
        chatGameBotName.textContent = 'Office Bot';
        chatGameBotName.title = 'Office Bot';
    }
    const best = chatGameGetHighScore(closingGameId);
    if (chatGameScore) chatGameScore.textContent = '0';
    if (chatGameHighScore) chatGameHighScore.textContent = String(best);
    if (composerDinoScore) composerDinoScore.textContent = '0';
    if (composerDinoHighScore) composerDinoHighScore.textContent = String(chatGameGetHighScore(DINO_GAME_ID));
    chatGameSetStatusText('Press Space to start | Esc to exit');
    if (clearMode && safeString(composerModeSelection?.kind) === 'game') {
        composerClearMode({ closeGame: false });
    }
}

function chatGameRestartActive() {
    if (chatGameRuntime.activeGameId === 'cloud_jump') {
        chatGameResetCloudJump();
    } else if (chatGameRuntime.activeGameId === JETPACK_GAME_ID) {
        chatGameResetJetpackJoyride();
    } else if (chatGameRuntime.activeGameId === DINO_GAME_ID) {
        chatGameResetDinoRun();
    } else {
        return;
    }
    chatGameRender();
    chatGameStartLoop();
}

function chatGameRenderToTextPayload() {
    const panelOpen = Boolean(
        (chatGamePanel && !chatGamePanel.classList.contains('hidden'))
        || (composerDinoShell && !composerDinoShell.classList.contains('hidden')),
    );
    const activeGame = chatGameRuntime.activeGameId || 'none';
    const base = {
        coordinate_system: 'origin top-left; +x right; +y down',
        panel_open: panelOpen,
        active_game: activeGame,
    };
    if (activeGame === 'cloud_jump' && chatGameRuntime.cloudJump) {
        const state = chatGameRuntime.cloudJump;
        return JSON.stringify({
            ...base,
            mode: state.mode,
            score: Math.floor(state.score),
            high_score: Math.floor(state.best),
            door: {
                visible: Boolean(state.scene?.doorVisible),
                open: Number((state.scene?.doorOpen || 0).toFixed(3)),
                light: Number((state.scene?.light || 0).toFixed(3)),
            },
            selected_agent: {
                id: safeString(state.selectedAgent?.id),
                name: safeString(state.selectedAgent?.name),
                costume: safeString(state.selectedAgent?.costume),
                color: safeString(state.selectedAgent?.color),
            },
            bot: {
                visible: Boolean(state.scene?.botVisible),
                x: Number((state.scene?.botX || 0).toFixed(2)),
                y: Number((state.scene?.botY || 0).toFixed(2)),
                running: Boolean(state.scene?.botRunning),
            },
            player: {
                x: Number(state.player.x.toFixed(2)),
                y: Number(state.player.y.toFixed(2)),
                vx: Number(state.player.vx.toFixed(2)),
                vy: Number(state.player.vy.toFixed(2)),
                w: state.player.w,
                h: state.player.h,
            },
            platforms: state.platforms.slice(0, 14).map((platform) => ({
                x: Number(platform.x.toFixed(2)),
                y: Number(platform.y.toFixed(2)),
                w: platform.w,
                h: platform.h,
            })),
        });
    }
    if (activeGame === JETPACK_GAME_ID && chatGameRuntime.jetpackJoyride) {
        const state = chatGameRuntime.jetpackJoyride;
        return JSON.stringify({
            ...base,
            mode: state.mode,
            score: Math.floor(state.score),
            high_score: Math.floor(state.best),
            door: {
                visible: Boolean(state.scene?.doorVisible),
                open: Number((state.scene?.doorOpen || 0).toFixed(3)),
                light: Number((state.scene?.light || 0).toFixed(3)),
            },
            selected_agent: {
                id: safeString(state.selectedAgent?.id),
                name: safeString(state.selectedAgent?.name),
                costume: safeString(state.selectedAgent?.costume),
                color: safeString(state.selectedAgent?.color),
            },
            bot: {
                visible: Boolean(state.scene?.botVisible),
                x: Number((state.scene?.botX || 0).toFixed(2)),
                y: Number((state.scene?.botY || 0).toFixed(2)),
                running: Boolean(state.scene?.botRunning),
            },
            player: {
                x: Number(state.player.x.toFixed(2)),
                y: Number(state.player.y.toFixed(2)),
                vx: Number(state.player.vx.toFixed(2)),
                vy: Number(state.player.vy.toFixed(2)),
                w: state.player.w,
                h: state.player.h,
            },
            obstacles: state.obstacles.slice(0, 12).map((obstacle) => {
                if (obstacle.type === 'zapper') {
                    return {
                        type: 'zapper',
                        cx: Number((obstacle.cx || 0).toFixed(2)),
                        cy: Number((obstacle.cy || 0).toFixed(2)),
                        length: obstacle.length,
                        angle: Number((obstacle.angle || 0).toFixed(3)),
                    };
                }
                return {
                    type: obstacle.type,
                    x: Number((obstacle.x || 0).toFixed(2)),
                    y: Number((obstacle.y || 0).toFixed(2)),
                    w: obstacle.w,
                    h: obstacle.h,
                };
            }),
        });
    }
    if (activeGame === DINO_GAME_ID && chatGameRuntime.dinoRun) {
        const state = chatGameRuntime.dinoRun;
        return JSON.stringify({
            ...base,
            mode: state.mode,
            score: Math.floor(state.score),
            high_score: Math.floor(state.best),
            portal: {
                visible: Boolean(state.portal?.visible),
                x: Number((state.portal?.x || 0).toFixed(2)),
                y: Number((state.portal?.y || 0).toFixed(2)),
            },
            selected_agent: {
                id: safeString(state.selectedAgent?.id),
                name: safeString(state.selectedAgent?.name),
                costume: safeString(state.selectedAgent?.costume),
                color: safeString(state.selectedAgent?.color),
            },
            bot: {
                visible: Boolean(state.scene?.botVisible),
                x: Number((state.scene?.botX || 0).toFixed(2)),
                y: Number((state.scene?.botY || 0).toFixed(2)),
                running: Boolean(state.scene?.botRunning),
            },
            player: {
                x: Number(state.player.x.toFixed(2)),
                y: Number(state.player.y.toFixed(2)),
                vx: Number((state.player.vx || 0).toFixed(2)),
                vy: Number((state.player.vy || 0).toFixed(2)),
                w: state.player.w,
                h: state.player.h,
                ducking: Boolean(state.player.ducking),
            },
            obstacles: state.obstacles.slice(0, 12).map((obstacle) => ({
                type: obstacle.type,
                x: Number((obstacle.x || 0).toFixed(2)),
                y: Number((obstacle.y || 0).toFixed(2)),
                w: obstacle.w,
                h: obstacle.h,
            })),
        });
    }
    if (!chatGameRuntime.cloudJump && !chatGameRuntime.jetpackJoyride && !chatGameRuntime.dinoRun) {
        return JSON.stringify(base);
    }
    return JSON.stringify(base);
}

