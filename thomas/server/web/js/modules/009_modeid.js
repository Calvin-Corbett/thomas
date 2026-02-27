// Extracted from part-005.js
// From modeid


    // Handle action commands
    if (selected.cmd === '/clear') {
        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        if (typeof startNewSession === 'function') startNewSession();
        return;
    }
    if (selected.cmd === '/export') {
        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        exportChatConversation();
        return;
    }
    if (selected.cmd === '/help') {
        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        showToast('Shortcuts: Esc=stop, Ctrl+Shift+N=new chat, /=commands');
        return;
    }

    // Mode commands — set the mode and clear the slash text
    const modeId = selected.cmd.replace('/', '');
    composerTextarea.value = '';
    composerTextarea.dispatchEvent(new Event('input'));
    if (typeof composerSetMode === 'function') {
        composerSetMode(modeId);
    }
}

function composerShowGamesColumn(show) {
    if (!composerGamesColumn) return;
    composerGamesColumn.classList.toggle('hidden', !show);
    if (!composerActionList) return;
    const gamesBtn = composerActionList.querySelector('[data-action="games"]');
    if (gamesBtn instanceof HTMLButtonElement) {
        gamesBtn.classList.toggle('active', show);
        gamesBtn.setAttribute('aria-expanded', show ? 'true' : 'false');
    }
}

function composerResolveModePreset(modeIdRaw) {
    const modeId = String(modeIdRaw || '').trim().toLowerCase();
    if (!modeId) return null;
    return COMPOSER_MODE_PRESETS[modeId] || null;
}

function composerRenderModeChip() {
    if (!composerModeChip || !composerModeChipLabel) return;
    if (!composerModeSelection) {
        composerModeChip.classList.add('hidden');
        composerModeChipLabel.textContent = '';
        return;
    }
    composerModeChipLabel.textContent = composerModeSelection.label || 'Mode';
    composerModeChip.classList.remove('hidden');
}

function composerSetMode(modeIdRaw, { label = '', kind = '', promptPrefix = '' } = {}) {
    const preset = composerResolveModePreset(modeIdRaw);
    const modeId = preset?.id || String(modeIdRaw || '').trim().toLowerCase();
    if (!modeId) return null;
    composerModeSelection = {
        id: modeId,
        label: safeString(label) || safeString(preset?.label) || modeId,
        kind: safeString(kind) || safeString(preset?.kind),
        promptPrefix: safeString(promptPrefix) || safeString(preset?.promptPrefix),
    };
    composerRenderModeChip();
    return composerModeSelection;
}

function composerClearMode({ closeGame = true } = {}) {
    const activeModeKind = safeString(composerModeSelection?.kind);
    composerModeSelection = null;
    composerRenderModeChip();
    if (closeGame && activeModeKind === 'game') {
        chatGameClose({ clearMode: false });
    }
}

function composerBuildMessageForModel(textRaw) {
    const text = String(textRaw || '').trim();
    const modePrompt = safeString(composerModeSelection?.promptPrefix);
    if (!modePrompt) return text;
    if (!text) return modePrompt;
    return `${modePrompt}\n\nUser request:\n${text}`;
}

function composerCloseActionsMenu() {
    composerActionsOpen = false;
    if (composerActionPopover) {
        composerActionPopover.classList.add('hidden');
    }
    composerShowGamesColumn(false);
    if (attachBtn) {
        attachBtn.classList.remove('active');
        attachBtn.setAttribute('aria-expanded', 'false');
    }
}

function composerOpenActionsMenu() {
    composerActionsOpen = true;
    if (composerActionPopover) {
        composerActionPopover.classList.remove('hidden');
    }
    composerShowGamesColumn(false);
    if (attachBtn) {
        attachBtn.classList.add('active');
        attachBtn.setAttribute('aria-expanded', 'true');
    }
}

function composerToggleActionsMenu() {
    if (composerActionsOpen) {
        composerCloseActionsMenu();
        return;
    }
    composerOpenActionsMenu();
}

function composerHandleQuickAction(actionRaw) {
    const action = String(actionRaw || '').trim().toLowerCase();
    if (!action) return;

    if (action === 'games') {
        composerSetMode('games');
        const showing = composerGamesColumn ? !composerGamesColumn.classList.contains('hidden') : false;
        composerShowGamesColumn(!showing);
        return;
    }

    const mode = composerSetMode(action);
    if (!mode) return;
    composerCloseActionsMenu();

    if (mode.kind !== 'game') {
        chatGameClose({ clearMode: false });
    }

    if (action === 'add_files') {
        if (docFileInput) docFileInput.click();
        return;
    }

    if (composerTextarea) {
        composerTextarea.focus();
    }
}

function composerHandleGameChoice(gameRaw) {
    const game = String(gameRaw || '').trim().toLowerCase();
    if (!game) return;
    composerCloseActionsMenu();
    if (game === 'cloud_jump' || game === JETPACK_GAME_ID || game === DINO_GAME_ID) {
        composerSetMode(game);
        chatGameOpen(game);
        return;
    }
    composerSetMode('games');
    chatGameClose({ clearMode: false });
}

function chatGameGetHighScore(gameIdRaw = chatGameRuntime.activeGameId || 'cloud_jump') {
    const gameId = safeString(gameIdRaw).toLowerCase();
    const storageKey = CHAT_GAME_HIGHSCORE_STORAGE_KEYS[gameId] || CHAT_GAME_HIGHSCORE_STORAGE_KEYS.cloud_jump;
    try {
        const raw = window.localStorage.getItem(storageKey);
        const parsed = Number(raw);
        if (!Number.isFinite(parsed)) return 0;
        return Math.max(0, Math.floor(parsed));
    } catch {
        return 0;
    }
}

function chatGameSetHighScore(scoreRaw, gameIdRaw = chatGameRuntime.activeGameId || 'cloud_jump') {
    const gameId = safeString(gameIdRaw).toLowerCase();
    const storageKey = CHAT_GAME_HIGHSCORE_STORAGE_KEYS[gameId] || CHAT_GAME_HIGHSCORE_STORAGE_KEYS.cloud_jump;
    const score = Math.max(0, Math.floor(Number(scoreRaw) || 0));
    try {
        window.localStorage.setItem(storageKey, String(score));
    } catch {
        // no-op in storage restricted contexts
    }
}

function chatGameSetStatusText(text) {
    const next = safeString(text);
    if (chatGameStatusText) {
        chatGameStatusText.textContent = next;
    }
    if (composerDinoStatusText) {
        composerDinoStatusText.textContent = next;
    }
}

function chatGameSetPanelOpen(open) {
    const shouldOpen = Boolean(open);
    if (chatGamePanel) {
        chatGamePanel.classList.toggle('hidden', !shouldOpen);
    }
    if (appRoot) {
        appRoot.classList.remove('chat-game-open');
    }
}

function chatGameSetDinoSurfaceOpen(open) {
    const shouldOpen = Boolean(open);
    if (composerDinoShell) {
        composerDinoShell.classList.toggle('hidden', !shouldOpen);
        composerDinoShell.classList.toggle('is-open', shouldOpen);
    }
    if (composerBox) {
        composerBox.classList.toggle('dino-active', shouldOpen);
    }
    if (composerContainer) {
        composerContainer.classList.toggle('dino-active', shouldOpen);
    }
    if (composerDisclaimer) {
        composerDisclaimer.classList.toggle('hidden', shouldOpen);
    }
    if (chatGamePortal) {
        chatGamePortal.classList.add('hidden');
    }
    if (appRoot) {
        appRoot.classList.toggle('chat-game-dino-open', shouldOpen);
    }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  CHAT GAMES                                                             ║
// ║  Cloud Jump, Jetpack Joyride, Dino Run — physics, rendering, game loop  ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

function chatGameSetCenterMuted(enable) {
    if (!appRoot) return;
    appRoot.classList.toggle('game-center-muted', Boolean(enable));
}

function chatGameSetPhaseClass(modeRaw = '') {
    if (chatGamePanel) {
        chatGamePanel.classList.remove('phase-intro', 'phase-ready', 'phase-launch', 'phase-playing', 'phase-game_over');
    }
    if (composerDinoShell) {
        composerDinoShell.classList.remove('phase-intro', 'phase-ready', 'phase-launch', 'phase-playing', 'phase-game_over');
    }
    const mode = safeString(modeRaw).toLowerCase();
    if (mode === 'intro' || mode === 'ready' || mode === 'launch' || mode === 'playing' || mode === 'game_over') {
        if (chatGamePanel) {
            chatGamePanel.classList.add(`phase-${mode}`);
        }
        if (composerDinoShell) {
            composerDinoShell.classList.add(`phase-${mode}`);
        }
    }
}

function chatGameToggleHiddenCanvasPriority(enable) {
    const demote = Boolean(enable);
    document.querySelectorAll('canvas').forEach((canvas) => {
        if (!(canvas instanceof HTMLCanvasElement)) return;
        if (canvas === chatGameCanvas) return;
        if (demote) {
            const rect = canvas.getBoundingClientRect();
            const hidden = rect.width < 2 || rect.height < 2 || Boolean(canvas.closest('.hidden'));
            if (!hidden) return;
            if (canvas.dataset.thomasCanvasDemoted === '1') return;
            canvas.dataset.thomasCanvasDemoted = '1';
            canvas.dataset.thomasCanvasWidth = String(canvas.width || 0);
            canvas.dataset.thomasCanvasHeight = String(canvas.height || 0);
            canvas.width = 1;
            canvas.height = 1;
            return;
        }
        if (canvas.dataset.thomasCanvasDemoted !== '1') return;
        const savedWidth = Number(canvas.dataset.thomasCanvasWidth);
        const savedHeight = Number(canvas.dataset.thomasCanvasHeight);
        if (Number.isFinite(savedWidth) && Number.isFinite(savedHeight) && savedWidth > 0 && savedHeight > 0) {
            canvas.width = savedWidth;
            canvas.height = savedHeight;
        }
        delete canvas.dataset.thomasCanvasDemoted;
        delete canvas.dataset.thomasCanvasWidth;
        delete canvas.dataset.thomasCanvasHeight;
    });
}

function chatGameClamp(value, min, max) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return Number(min) || 0;
    return Math.min(Number(max) || 0, Math.max(Number(min) || 0, numeric));
}

function chatGameRandom(min, max) {
    const lo = Number(min) || 0;
    const hi = Number(max) || 0;
    return lo + (Math.random() * (hi - lo));
}

function chatGameEaseOutCubic(value) {
    const t = chatGameClamp(value, 0, 1);
    return 1 - ((1 - t) ** 3);
}

function chatGameEaseInOutCubic(value) {
    const t = chatGameClamp(value, 0, 1);
    if (t < 0.5) {
        return 4 * t * t * t;
    }
    return 1 - (((-2 * t) + 2) ** 3) / 2;
}

function chatGameLerp(start, end, t) {
    return Number(start) + ((Number(end) - Number(start)) * chatGameClamp(t, 0, 1));
}

function chatGameNormalizeOfficeAgent(agentRaw, fallbackId = 'agent-game') {
    const fallbackColor = '#9ad8ff';
    const candidate = agentRaw && typeof agentRaw === 'object' ? agentRaw : {};
    const id = safeString(candidate.id) || safeString(fallbackId) || 'agent-game';
    const resolvedName = normalizeAgentName(safeString(candidate.name) || 'Office Bot');
    const colorRaw = safeString(candidate.color);
    const color = /^#[0-9a-f]{6}$/i.test(colorRaw) ? colorRaw : fallbackColor;
    const costumeRaw = safeString(candidate.costume || 'none').toLowerCase();
    const costume = OFFICE_AGENT_COSTUME_POOL.includes(costumeRaw) ? costumeRaw : 'none';
    const tintRaw = safeString(candidate.tint).toLowerCase();
    return {
        id,
        name: resolvedName || 'Office Bot',
        color,
        costume,
        tint: tintRaw || officeAgentTintFromColor(color),
    };
}

function chatGameCollectOfficeAgentRoster() {