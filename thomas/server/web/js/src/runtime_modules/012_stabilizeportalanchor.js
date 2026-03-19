// Extracted from part-006b.js
// From stabilizeportalanchor

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