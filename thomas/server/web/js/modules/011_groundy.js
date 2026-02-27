// Extracted from part-006.js
// From groundy

    if (player.x > state.width) {
        player.x = -player.w;
    } else if ((player.x + player.w) < 0) {
        player.x = state.width;
    }

    const groundY = Number(state.startY) || player.y;
    player.y = groundY;
    player.vy = 0;

    const playerBottom = player.y + player.h;
    const launchSweeps = chatGameCollectPlatformSweeps(state, deltaFrames, CHAT_GAME_LAUNCH_PLATFORM_FALL_SPEED);
    const landedPlatform = chatGameFindLandingPlatform(
        launchSweeps,
        player,
        playerBottom - 4,
        playerBottom + 4,
        { tolerance: 10, footInset: 3 },
    );

    state.platforms = state.platforms.filter((platform) => platform.y < (state.height + 44));
    chatGameSpawnPlatforms(state);

    const scene = state.scene;
    scene.botScale = 1;
    scene.botJetpack = false;
    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botX = player.x;
    scene.botY = player.y;
    scene.botRunning = Math.abs(player.vx) > 0.3;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;

    if (landedPlatform) {
        player.y = landedPlatform.y - player.h;
        player.vy = state.jumpVelocity;
        state.mode = 'playing';
        state.playFrames = 0;
        state.launchSeconds = 0;
        chatGameSetStatusText('Run active. Keep landing to stay up.');
        return;
    }

    if (state.launchSeconds > CHAT_GAME_PLATFORM_LAUNCH_RESPAWN_SECONDS) {
        state.launchSeconds = 0;
        chatGameCreateTopStartPlatforms(state);
        chatGameSetStatusText('Platforms realigned. First landing starts the run.');
    }
}

function chatGameStepPlaying(state, deltaFrames) {
    state.tick += deltaFrames;
    state.playFrames += deltaFrames;

    const player = state.player;
    const horizontal = (chatGameRuntime.input.right ? 1 : 0) - (chatGameRuntime.input.left ? 1 : 0);
    player.vx = horizontal * state.horizontalSpeed;
    player.x += player.vx * deltaFrames;
    if (player.vx > 0.12) {
        player.facing = 1;
    } else if (player.vx < -0.12) {
        player.facing = -1;
    }
    if (player.x > state.width) {
        player.x = -player.w;
    } else if ((player.x + player.w) < 0) {
        player.x = state.width;
    }

    const previousBottom = player.y + player.h;
    player.vy += state.gravity * deltaFrames;
    player.vy = Math.min(player.vy, 14.8);
    player.y += player.vy * deltaFrames;

    const platformFallSpeed = state.baseFallSpeed + Math.min(2.2, state.score * 0.009);
    const platformSweeps = chatGameCollectPlatformSweeps(state, deltaFrames, platformFallSpeed);

    if (player.vy > 0) {
        const currentBottom = player.y + player.h;
        const landedPlatform = chatGameFindLandingPlatform(
            platformSweeps,
            player,
            previousBottom,
            currentBottom,
            { tolerance: 8, footInset: 3 },
        );
        if (landedPlatform) {
            player.y = landedPlatform.y - player.h;
            player.vy = state.jumpVelocity;
        }
    }

    if (player.y < state.scrollLine) {
        const travel = state.scrollLine - player.y;
        player.y = state.scrollLine;
        state.platforms.forEach((platform) => {
            platform.y += travel;
        });
        state.distance += travel;
    }

    const climbScore = Math.max(0, Math.floor(state.distance / 5));
    const timeScore = Math.max(0, Math.floor(state.playFrames * 0.08));
    state.score = Math.max(state.score, climbScore + timeScore);

    state.platforms = state.platforms.filter((platform) => platform.y < (state.height + 44));
    chatGameSpawnPlatforms(state);

    const scene = state.scene;
    scene.botScale = 1;
    scene.botJetpack = false;
    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botX = player.x;
    scene.botY = player.y;
    scene.botRunning = Math.abs(player.vx) > 0.4;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;

    if (player.y > (state.height + 42)) {
        state.mode = 'game_over';
        state.best = Math.max(state.best, state.score);
        chatGameSetHighScore(state.best);
        player.vx = 0;
        player.vy = 0;
        scene.botRunning = false;
        chatGameSetStatusText('Game over. Space to run again | Esc to exit');
    }
}

function chatGameStepGameOver(state, deltaFrames) {
    state.tick += deltaFrames;
    const scene = state.scene;
    scene.botScale = 1;
    scene.botJetpack = false;
    scene.doorVisible = false;
    scene.doorOpen = 0;
    scene.light = 0;
    scene.botVisible = true;
    scene.botRunning = false;
    scene.botInside = false;
    scene.botDoorOffsetX = 0;
    scene.botX = state.player.x;
    scene.botY = Math.min(state.height - state.player.h - 12, state.player.y + (Math.sin(state.tick * 0.08) * 0.6));
}

function chatGameStepCloudJump(deltaFrames) {
    const state = chatGameRuntime.cloudJump;
    if (!state) return;
    const frames = Number.isFinite(deltaFrames) ? Math.max(0, deltaFrames) : 1;

    if (state.mode === 'intro') {
        chatGameStepIntro(state, frames);
    } else if (state.mode === 'ready') {
        chatGameStepReady(state, frames);
    } else if (state.mode === 'launch') {
        chatGameStepLaunch(state, frames);
    } else if (state.mode === 'playing') {
        chatGameStepPlaying(state, frames);
    } else if (state.mode === 'game_over') {
        chatGameStepGameOver(state, frames);
    }
    chatGameUpdateHud(state);
    chatGameSyncScene(state);
}

function chatGameRenderCloudJump() {
    if (!(chatGameCanvas instanceof HTMLCanvasElement)) return;
    const ctx = chatGameCanvas.getContext('2d');
    const state = chatGameRuntime.cloudJump;
    if (!ctx || !state) return;

    const width = state.width;
    const height = state.height;
    ctx.clearRect(0, 0, width, height);

    state.platforms.forEach((platform) => {
        const shimmer = 0.64 + (Math.sin((state.tick * 0.05) + (platform.id * 0.18)) * 0.13);
        ctx.fillStyle = `rgba(70, 175, 248, ${chatGameClamp(shimmer, 0.32, 0.86).toFixed(3)})`;
        ctx.fillRect(platform.x, platform.y, platform.w, platform.h);
        ctx.fillStyle = 'rgba(230, 246, 255, 0.92)';
        ctx.fillRect(platform.x + 2, platform.y + 2, platform.w - 4, 3);
    });

    if (state.mode === 'game_over') {
        ctx.fillStyle = 'rgba(236, 246, 255, 0.88)';
        ctx.font = '700 14px "Segoe UI", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Run Ended', width * 0.5, Math.max(36, height * 0.18));
    }
    chatGameSyncScene(state);
}

function chatGameGetJetpackFlightBounds(state, entityHeight = 0) {
    const minY = JETPACK_PLAYER_TOP_PADDING;
    const maxY = Math.max(
        minY,
        state.height - Number(entityHeight || 0) - JETPACK_PLAYER_BOTTOM_PADDING,
    );
    return { minY, maxY };
}

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