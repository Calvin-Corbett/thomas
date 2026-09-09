async function applyOnboardingCompletion({ skippedInterview = false } = {}) {
    const onboardingAnswers = {
        ...(getOnboardingFromPrefs()?.answers || {}),
        ...(easySetupState.interviewAnswers || {}),
        interview_skipped: Boolean(skippedInterview),
        connection_path: safeString(easySetupState.selectedPath),
        dependency_action: safeString(easySetupState.dependenciesAction) || 'pending',
    };
    const derived = deriveOnboardingDefaults(onboardingAnswers);
    const completedAt = onboardingNowIso();
    const selectedProfile = resolveEasySetupSelectedProfile();
    const selectedModelId = resolveEasySetupSelectedModelId(selectedProfile);

    const patch = {
        autonomy: { default_level: `L${derived.autonomyLevel}` },
        memory: { enabled_global: derived.memoryEnabled },
        notifications: { desktop: derived.desktopNotifications },
        profile: { profile_type: derived.profileType },
        advanced: {
            model: {
                active_profile: selectedProfile,
                model_id: selectedModelId,
            },
            runtime: {
                default_mode: derived.defaultMode,
                default_token_economy: derived.tokenEconomy,
            },
            tools: {
                require_command_approval: derived.requireCommandApproval,
                allow_network: derived.allowNetwork,
            },
            interface: {
                show_timestamps: derived.showTimestamps,
                show_token_meter: derived.showTokenMeter,
                debug_panel_enabled: derived.debugPanelEnabled,
                ui_density: derived.uiDensity,
                animation_fidelity: derived.animationFidelity,
                animations_enabled: isAnimationFidelityEnabled(derived.animationFidelity),
                advanced_chat_physics: derived.chatPhysicsEnabled,
            },
        },
        onboarding: {
            setup_completed: true,
            version: ONBOARDING_VERSION,
            completed_at: completedAt,
            dismissed_at: null,
            current_step: 'completed',
            connection_method: safeString(easySetupState.selectedPath) || null,
            dependency_plan: {
                path: safeString(easySetupState.selectedPath),
                items: Array.isArray(easySetupState.dependencyPlan) ? easySetupState.dependencyPlan : [],
            },
            answers: onboardingAnswers,
        },
    };

    const res = await fetch('/api/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
    });
    if (!res.ok) {
        const reason = await res.text();
        throw new Error(reason || `Failed to finalize onboarding (${res.status})`);
    }
    currentPreferences = await res.json();

    if (derived.sessionOnlyMemory && sessionId) {
        await fetch(`/api/preferences?thread_id=${encodeURIComponent(sessionId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ memory: { thread_enabled: true } }),
        }).catch(() => { });
    }

    activeAutonomyLevel = derived.autonomyLevel;
    activeTokenEconomy = derived.tokenEconomy === 'optimal' ? 'balanced' : derived.tokenEconomy;
    activeChatMode = normalizeChatMode(derived.defaultMode) || 'auto';
    if (selectedProfile) {
        activeModelOverride = selectedModelId;
        if (setupProviderSelector) setupProviderSelector.value = selectedProfile;
        if (modelSelector) modelSelector.value = selectedProfile;
        if (setupModelSelector && selectedModelId) {
            if (!setupModelSelector.querySelector(`option[value="${CSS.escape(selectedModelId)}"]`)) {
                const opt = document.createElement('option');
                opt.value = selectedModelId;
                opt.textContent = selectedModelId;
                setupModelSelector.appendChild(opt);
            }
            setupModelSelector.value = selectedModelId;
        }
        try { window.localStorage.setItem('thomas_active_profile', selectedProfile); } catch (_) {}
        try { window.localStorage.setItem('thomas_active_model_id', selectedModelId); } catch (_) {}
        renderSetupProviderPickerMenu(selectedProfile, { preserveExpanded: false });
        if (modelSetupCurrentLabel) modelSetupCurrentLabel.textContent = _profileHeaderLabel(selectedProfile);
    }
    setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
    setSegmentedControlSelection('setupEconomyGroup', activeTokenEconomy);
    if (settingAdvDefaultMode) settingAdvDefaultMode.value = activeChatMode;
    if (setupMemoryToggle) setupMemoryToggle.checked = Boolean(currentPreferences?.memory?.enabled_global);
    if (settingMemoryEnabled) settingMemoryEnabled.checked = Boolean(currentPreferences?.memory?.enabled_global);
    updateSidebarIdentity();
    easySetupState.interviewStarted = false;
    easySetupState.interviewStage = 'idle';
    easySetupState.interviewIndex = -1;
    hideAssistantSuggestions({ force: true });
    showStarterSuggestionRail({ force: true });

    emitOnboardingTelemetry('completed', {
        skipped_interview: Boolean(skippedInterview),
        connection_method: safeString(easySetupState.selectedPath),
        autonomy_level: derived.autonomyLevel,
        token_economy: derived.tokenEconomy,
    });
}

async function submitOnboardingInterviewAnswer(question, value) {
    const index = Number(easySetupState.interviewIndex);
    easySetupState.interviewAnswers[question.id] = value;
    easySetupState.interviewIndex = index + 1;
    easySetupState.interviewStage = 'question';
    await persistOnboardingPrefs({
        current_step: 'interview',
        answers: { [question.id]: value },
    });
    emitOnboardingTelemetry('interview.answer', {
        question_id: question.id,
        value,
        source: 'explicit_button',
    });
    promptOnboardingQuestion();
}

async function promptInterviewSkipConfirm() {
    easySetupState.interviewStage = 'skip_confirm';
    renderOnboardingChoiceBubble(
        'You can skip the intake and finish with safe defaults. Want me to do that?',
        [
            { value: 'finish_defaults', label: 'Finish setup with defaults', kind: 'action', tone: 'primary' },
            { value: 'resume', label: 'Resume questions', kind: 'action' },
        ],
        async (choice) => {
            renderMessage({ role: 'user', content: safeString(choice?.label) });
            const action = safeString(choice?.value);
            if (action === 'finish_defaults') {
                try {
                    await applyOnboardingCompletion({ skippedInterview: true });
                    renderMessage({
                        role: 'assistant',
                        content: withAgentName('Setup complete. {{agent}} is ready with safe defaults. You can tune anything in Settings later.'),
                    });
                } catch (err) {
                    renderMessage({
                        role: 'assistant',
                        content: `Could not finalize setup: ${safeString(err?.message) || 'unknown error'}`,
                    });
                }
                return;
            }
            easySetupState.interviewSkipChosen = false;
            promptOnboardingQuestion();
        }
    );
}

function promptOnboardingQuestion() {
    const index = Number(easySetupState.interviewIndex);
    if (index >= onboardingInterviewQuestions.length) {
        easySetupState.interviewStage = 'review';
        const answers = easySetupState.interviewAnswers || {};
        const summary = [
            `Experience: ${safeString(answers.experience) || 'builder'}`,
            `Autonomy: ${safeString(answers.autonomy) || 'balanced'}`,
            `Cost/quality: ${safeString(answers.cost_quality) || 'balanced'}`,
            `Memory: ${safeString(answers.memory) || 'remember'}`,
            `Workflow: ${safeString(answers.workflow) || 'build_features'}`,
        ];
        renderMessage({
            role: 'assistant',
            content: `### Review profile\n${summary.map((line) => `- ${line}`).join('\n')}\n\nSay "finish setup", "use defaults", or "open settings".`,
        });
        renderOnboardingChoiceBubble(
            'Final step',
            [
                { value: 'apply', label: 'Finish setup', kind: 'action', tone: 'primary' },
                { value: 'skip', label: 'Finish with defaults', kind: 'action' },
                { value: 'settings', label: 'Open Settings first', kind: 'action' },
            ],
            async (choice) => {
                renderMessage({ role: 'user', content: safeString(choice?.label) });
                const action = safeString(choice?.value);
                if (action === 'settings') {
                    openSettingsModal();
                    renderMessage({
                        role: 'assistant',
                        content: 'Settings opened. Return and tell me to finish setup when you are ready.',
                    });
                    return;
                }
                try {
                    await applyOnboardingCompletion({ skippedInterview: action === 'skip' });
                    renderMessage({
                        role: 'assistant',
                        content: withAgentName('Onboarding complete. {{agent}} is connected and ready.'),
                    });
                } catch (err) {
                    renderMessage({
                        role: 'assistant',
                        content: `Could not finalize setup: ${safeString(err?.message) || 'unknown error'}`,
                    });
                }
            }
        );
        return;
    }

    easySetupState.interviewStage = 'question';
    const question = onboardingInterviewQuestions[index];
    const questionPrompt = withAgentName(question.prompt);
    renderOnboardingChoiceBubble(
        `### ${escapeHtml(questionPrompt)}\nReply naturally or tap an option.`,
        [
            ...question.options.map((option) => ({ ...option, kind: 'option' })),
            { value: '__skip_interview__', label: 'Skip intake', kind: 'action' },
        ],
        async (choice) => {
            renderMessage({ role: 'user', content: safeString(choice?.label) });
            const value = safeString(choice?.value);
            if (value === '__skip_interview__') {
                easySetupState.interviewSkipChosen = true;
                await promptInterviewSkipConfirm();
                return;
            }
            await submitOnboardingInterviewAnswer(question, value);
        }
    );
}

async function handleOnboardingChatInput(_textRaw, { docsCount = 0, imagesCount = 0 } = {}) {
    if (docsCount > 0 || imagesCount > 0) {
        renderMessage({
            role: 'assistant',
            content: 'Attachments do not change onboarding choices, so I ignored them for this step.',
        });
    }
    renderMessage({
        role: 'assistant',
        content: 'Onboarding answers only change when you choose one of the visible buttons. Your message did not change any setup setting.',
    });
}

async function beginOnboardingInterview() {
    easySetupState.interviewStarted = true;
    easySetupState.interviewStage = 'question';
    easySetupState.interviewIndex = 0;
    ensureChatVisible();
    await persistOnboardingPrefs({ current_step: 'interview', dismissed_at: null });
    renderMessage({
        role: 'assistant',
        content: 'Brain handshake complete. Choose the visible options below so every setup preference is explicit.',
    });
    promptOnboardingQuestion();
    emitOnboardingTelemetry('interview.started', {
        path: safeString(easySetupState.selectedPath),
    });
}

// 
//   INITIALIZATION & COMPOSER                                              
//   Main init(), composer setup, slash palette, message building           
// 

/**
 * Initialize the ultra-premium UI behaviors
 */
function init() {
    if (appRoot) {
        appRoot.classList.remove('debug-dock-open');
        appRoot.classList.remove('settings-active');
        appRoot.classList.remove('chat-game-open');
    }
    if (settingsModal) {
        settingsModal.classList.add('hidden');
    }
    initComposer();
    initChatComposerSubbar();
    configureComposerSurface();
    initActions();
    initChatSearch();
    initChatGame();
    initFeatures();
    initEasySetup();
    loadInitialState().catch((error) => {
        console.error('Boot initialization failed', error);
        notifyUser('Thomas had trouble loading. Retrying startup tasks.', {
            tone: 'warning',
            durationMs: 2600,
            debugKind: 'error',
        });
    });
    initComposerDeepLink();
    syncChatComposerOffset();
    window.addEventListener('resize', () => syncChatComposerOffset(), { passive: true });
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => syncChatComposerOffset());
    }
    if (composerContainer && 'ResizeObserver' in window) {
        const resizeObs = new ResizeObserver(() => syncChatComposerOffset());
        resizeObs.observe(composerContainer);
    }
}

function syncChatComposerOffset() {
    if (_composerOffsetRaf) return;
    _composerOffsetRaf = window.requestAnimationFrame(() => {
        _composerOffsetRaf = 0;
        if (!(chatMessagesInner instanceof HTMLElement) || !(composerContainer instanceof HTMLElement)) return;
        const shouldPinToBottom = (chatScrollArea instanceof HTMLElement)
            && ((chatScrollArea.scrollHeight - chatScrollArea.clientHeight - chatScrollArea.scrollTop) <= CHAT_SCROLL_BOTTOM_EPSILON);
        const rect = composerContainer.getBoundingClientRect();
        const offset = Math.max(CHAT_COMPOSER_OFFSET_MIN, Math.ceil(rect.height) + CHAT_COMPOSER_OFFSET_BUFFER);
        if (Math.abs(offset - _lastComposerOffset) < CHAT_COMPOSER_OFFSET_EPSILON) return;
        _lastComposerOffset = offset;
        const offsetValue = `${offset}px`;
        chatMessagesInner.style.setProperty('--composer-offset', offsetValue);
        document.documentElement.style.setProperty('--composer-offset', offsetValue);
        if (shouldPinToBottom && chatScrollArea instanceof HTMLElement) {
            window.requestAnimationFrame(() => {
                chatScrollArea.scrollTop = chatScrollArea.scrollHeight;
            });
        }
    });
}

/**
 * Composer behaviors: Auto-expand, Enter-to-send
 */
function composerSyncSendButtonState() {
    if (isGenerating) return;
    const canSend = composerTextarea.value.trim().length > 0 || pendingDocs.length > 0 || pendingImages.length > 0;
    sendBtn.disabled = !canSend;
    sendBtn.style.color = canSend ? 'var(--text-primary)' : '';
    syncSendButtonA11y();
}

/*  Chat Composer Controls  */
function resolveProfileChatControls(profileName = '') {
    const targetProfile = safeString(profileName);
    const profile = targetProfile && Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name) === targetProfile)
        : null;
    const controls = profile?.chat_controls;
    return controls && typeof controls === 'object'
        ? controls
        : { model: {}, thomas: {} };
}

function profileSupportsReasoningEffort(profileName = '') {
    return Boolean(resolveProfileChatControls(profileName)?.model?.reasoning_effort?.supported);
}

function resolveChatPayloadReasoningEffort(profileName = '') {
    if (!profileSupportsReasoningEffort(profileName)) return undefined;
    const effort = normalizeReasoningEffort(activeReasoningEffort);
    return effort || undefined;
}

function resolveChatPayloadTokenEconomy() {
    const value = safeString(activeTokenEconomy).toLowerCase();
    if (value === 'cheap' || value === 'max') return value;
    return 'optimal';
}

function syncSetupReasoningVisibility(profileName = '') {
    const reasoningGroup = document.getElementById('setupReasoningGroup');
    const supported = profileSupportsReasoningEffort(profileName);
    const current = supported ? resolveProfileReasoningEffort(profileName) : '';
    if (reasoningGroup) reasoningGroup.style.display = supported ? '' : 'none';
    activeReasoningEffort = current;
    setSegmentedControlSelection('setupReasoningEffortGroup', current);
    if (settingAdvReasoningEffort) {
        settingAdvReasoningEffort.value = current || 'medium';
    }
}

/* ---------------------------------------------------------------------------
 * Composer controls (the 5 dials) render/toggle MOVED to js/composer_controls.js.
 *
 * ensureChatComposerControls / ensureChatComposerSubbar / wireComposerControlsToggle
 * / renderChatComposerSubbar / initChatComposerSubbar now live in composer_controls.js
 * (loaded as a classic script before app_runtime_loader.js, so they join this
 * shared global scope). They still read the same runtime state vars
 * (activeReasoningEffort, activeTokenEconomy, activeAutonomyLevel, activeFileAccess,
 * activeGuardrails, autonomyLevelManuallySet) and helpers defined here / elsewhere
 * in the runtime, and the runtime keeps calling them by bare name. The 5 <select>
 * ids, option sets and change side-effects are byte-identical to the originals.
 * buildChatRequestPayload() (below) is the sole reader of those state vars.
 * ------------------------------------------------------------------------- */

function buildChatRequestPayload(message, { docs = [], images = [], systemPrompt = '', resolvedProfile = '', studioChatContext = null } = {}) {
    const requestedProfile = safeString(resolvedProfile);
    const fallbackProfile = requestedProfile || safeString(modelSelector?.value) || safeString(setupProviderSelector?.value);
    const role = typeof resolveComposerModelRole === 'function' && !safeString(studioChatContext?.preferredProfile)
        ? resolveComposerModelRole()
        : '';
    const specialty = role && typeof resolveSpecialtyModelSelection === 'function'
        ? resolveSpecialtyModelSelection(role, fallbackProfile)
        : null;
    const profile = safeString(specialty?.profile) || fallbackProfile;
    // Module scope: when the user is inside a workspace module (e.g. Evolution),
    // tag the turn so the server starts Thomas in that module's context. It is
    // still the full Thomas -- the module is a starting point, not a cage, and he
    // can break out if the conversation goes elsewhere.
    const activeModuleKey = (typeof sidebarNavMode === 'string' && sidebarNavMode === 'evolution') ? 'evolve' : '';
    const payload = {
        message: message,
        docs: Array.isArray(docs) ? docs : [],
        images: Array.isArray(images) ? images : [],
        session_id: sessionId,
        module: activeModuleKey || undefined,
        profile: profile,
        model: profile,
        model_id: safeString(specialty?.modelId) || resolveActiveModelIdForProfile(profile) || undefined,
        autonomy_level: Math.max(1, parseInt(String(activeAutonomyLevel || 1), 10) || 1),
        file_access: safeString(activeFileAccess) || 'workspace',
        token_economy: resolveChatPayloadTokenEconomy(),
        thomas_guardrails: safeString(activeGuardrails) || 'guarded',
        thomas_guardrail_modes: (() => {
            try { return JSON.parse(localStorage.getItem('thomasGuardrailModes') || 'null') || undefined; } catch (e) { return undefined; }
        })(),
        system_prompt: systemPrompt || undefined,
    };
    const reasoningEffort = resolveChatPayloadReasoningEffort(profile);
    if (reasoningEffort) payload.reasoning_effort = reasoningEffort;
    if (studioChatContext?.enabled) {
        payload.asset_studio_mode = 'comfy_studio';
        payload.asset_studio_context = studioChatContext.context || {};
    }
    return payload;
}

function initComposer() {
    composerTextarea.addEventListener('input', () => {
        // Auto-resize
        composerTextarea.style.height = 'auto';
        composerTextarea.style.height = (composerTextarea.scrollHeight) + 'px';

        // Toggle send button state
        composerSyncSendButtonState();

        // Slash command palette
        _updateSlashPalette();
        syncChatComposerOffset();
    });

    composerTextarea.addEventListener('keydown', (e) => {
        if (_modelPaletteVisible) {
            if (e.key === 'ArrowDown') { e.preventDefault(); _modelPaletteNav(1); return; }
            if (e.key === 'ArrowUp') { e.preventDefault(); _modelPaletteNav(-1); return; }
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _modelPaletteSelect(); return; }
            if (e.key === 'Escape') { e.preventDefault(); _hideModelPalette(); return; }
            if (e.key === 'Tab') { e.preventDefault(); _modelPaletteSelect(); return; }
        }

        // Slash palette navigation
        if (_slashPaletteVisible) {
            if (e.key === 'ArrowDown') { e.preventDefault(); _slashPaletteNav(1); return; }
            if (e.key === 'ArrowUp') { e.preventDefault(); _slashPaletteNav(-1); return; }
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _slashPaletteSelect(); return; }
            if (e.key === 'Escape') { e.preventDefault(); _hideSlashPalette(); return; }
            if (e.key === 'Tab') { e.preventDefault(); _slashPaletteSelect(); return; }
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) {
                sendBtn.click();
            }
        }
    });

    //  Paste images from clipboard 
    composerTextarea.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (!file) continue;
                const reader = new FileReader();
                reader.onload = (re) => {
                    pendingImages.push({ data_url: re.target.result, name: file.name || 'pasted-image.png' });
                    renderAttachmentsPreview();
                    composerSyncSendButtonState();
                    showToast('Image pasted');
                };
                reader.readAsDataURL(file);
                break; // only handle first image
            }
        }
    });

    //  Drag-and-drop files onto composer 
    const composerArea = composerTextarea.closest('.composer') || composerTextarea.parentElement;
    if (composerArea) {
        let _dragCounter = 0;

        // Create drop overlay
        const dropOverlay = document.createElement('div');
        dropOverlay.className = 'composer-drop-overlay';
        dropOverlay.innerHTML = '<span><i class="ph ph-upload-simple"></i> Drop files here</span>';
        composerArea.style.position = composerArea.style.position || 'relative';
        composerArea.appendChild(dropOverlay);

        composerArea.addEventListener('dragenter', (e) => {
            e.preventDefault();
            _dragCounter++;
            dropOverlay.classList.add('visible');
        });
        composerArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            _dragCounter--;
            if (_dragCounter <= 0) {
                _dragCounter = 0;
                dropOverlay.classList.remove('visible');
            }
        });
        composerArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });
        composerArea.addEventListener('drop', async (e) => {
            e.preventDefault();
            _dragCounter = 0;
            dropOverlay.classList.remove('visible');

            const files = e.dataTransfer?.files;
            if (!files || files.length === 0) return;

            for (const file of files) {
                if (file.type.startsWith('image/')) {
                    const reader = new FileReader();
                    reader.onload = (re) => {
                        pendingImages.push({ data_url: re.target.result, name: file.name });
                        renderAttachmentsPreview();
                        composerSyncSendButtonState();
                    };
                    reader.readAsDataURL(file);
                } else {
                    try {
                        const text = await file.text();
                        pendingDocs.push({ name: file.name, text: text });
                        renderAttachmentsPreview();
                        composerSyncSendButtonState();
                    } catch (err) {
                        console.warn('Failed to read dropped file:', err);
                    }
                }
            }
            showToast(`${files.length} file(s) attached`);
        });
    }
}

//  Slash Command Palette 
const SLASH_COMMANDS = [
    { cmd: '/research',  desc: 'Deep research mode  thorough web search + synthesis' },
    { cmd: '/image',     desc: 'Generate an image from a description' },
    { cmd: '/code',      desc: 'Code-focused mode  programming assistance' },
    { cmd: '/write',     desc: 'Writing mode  essays, emails, creative text' },
    { cmd: '/analyze',   desc: 'Analyze documents, data, or complex topics' },
    { cmd: '/model',     desc: 'Switch active model/profile inline' },
    { cmd: '/status',    desc: 'Show live engine status and runtime details' },
    { cmd: '/issues',    desc: 'Run code issue detection and automated fixes' },
    { cmd: '/upgrade',   desc: 'Run self-upgrade engine cycle' },
    { cmd: '/sync',      desc: 'Run workspace sync cycle (commit / housekeeping)' },
    { cmd: '/ui-audit',  desc: 'Run UI workflow review and polish checks' },
    { cmd: '/clear',     desc: 'Clear the conversation and start fresh' },
    { cmd: '/export',    desc: 'Export this conversation as markdown or JSON' },
    { cmd: '/help',      desc: 'Show available commands and keyboard shortcuts' },
];

let _slashPaletteVisible = false;
let _slashPaletteIndex = 0;
let _slashPaletteFiltered = [];
let _slashPaletteEl = null;
let _modelPaletteVisible = false;
let _modelPaletteIndex = 0;
let _modelPaletteOptions = [];
let _modelPaletteEl = null;

function _getSlashPaletteEl() {
    if (_slashPaletteEl) return _slashPaletteEl;
    _slashPaletteEl = document.createElement('div');
    _slashPaletteEl.className = 'slash-palette';
    const composerArea = composerTextarea.closest('.composer') || composerTextarea.parentElement;
    if (composerArea) {
        composerArea.style.position = composerArea.style.position || 'relative';
        composerArea.appendChild(_slashPaletteEl);
    }
    return _slashPaletteEl;
}

function _updateSlashPalette() {
    if (_modelPaletteVisible) return;
    const text = composerTextarea.value;
    if (!text.startsWith('/') || text.includes(' ') || text.includes('\n')) {
        _hideSlashPalette();
        return;
    }
    const query = text.toLowerCase();
    _slashPaletteFiltered = SLASH_COMMANDS.filter(c => c.cmd.startsWith(query));
    if (_slashPaletteFiltered.length === 0) {
        _hideSlashPalette();
        return;
    }
    _slashPaletteIndex = Math.min(_slashPaletteIndex, _slashPaletteFiltered.length - 1);
    _renderSlashPalette();
    _slashPaletteVisible = true;
}

function _renderSlashPalette() {
    const el = _getSlashPaletteEl();
    el.innerHTML = _slashPaletteFiltered.map((c, i) =>
        `<div class="slash-palette-item${i === _slashPaletteIndex ? ' active' : ''}" data-idx="${i}">
            <span class="slash-cmd">${escapeHtml(c.cmd)}</span>
            <span class="slash-desc">${escapeHtml(c.desc)}</span>
        </div>`
    ).join('');
    el.classList.add('visible');

    // Click to select
    el.querySelectorAll('.slash-palette-item').forEach(item => {
        item.addEventListener('click', (e) => {
            _slashPaletteIndex = parseInt(item.dataset.idx, 10);
            _slashPaletteSelect();
        });
    });
}

function _hideSlashPalette() {
    _slashPaletteVisible = false;
    _slashPaletteIndex = 0;
    if (_slashPaletteEl) _slashPaletteEl.classList.remove('visible');
}

function _slashPaletteNav(dir) {
    _slashPaletteIndex = Math.max(0, Math.min(_slashPaletteFiltered.length - 1, _slashPaletteIndex + dir));
    _renderSlashPalette();
}

function _slashPaletteSelect() {
    const selected = _slashPaletteFiltered[_slashPaletteIndex];
    if (!selected) { _hideSlashPalette(); return; }

    _hideSlashPalette();

    if (selected.cmd === '/model') {
        _openModelPalette();
        return;
    }

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

    // Mode commands  set the mode and clear the slash text
    const modeId = selected.cmd.replace('/', '');
    composerTextarea.value = '';
    composerTextarea.dispatchEvent(new Event('input'));
    if (typeof composerSetMode === 'function') {
        composerSetMode(modeId);
    }
}

function _getModelPaletteEl() {
    if (_modelPaletteEl) return _modelPaletteEl;
    _modelPaletteEl = document.createElement('div');
    _modelPaletteEl.className = 'slash-palette model-palette';
    const composerArea = composerTextarea.closest('.composer') || composerTextarea.parentElement;
    if (composerArea) {
        composerArea.style.position = composerArea.style.position || 'relative';
        composerArea.appendChild(_modelPaletteEl);
    }
    return _modelPaletteEl;
}

function _buildModelPaletteOptions() {
    const profiles = Array.isArray(availableModelProfiles) ? availableModelProfiles : [];
    return profiles
        .filter((profile) => safeString(profile?.name))
        .map((profile) => {
            const name = safeString(profile.name);
            const provider = safeString(profile.provider);
            const modelId = safeString(profile.model).split('/').pop();
            const status = profile?.has_api_key === false ? 'not configured' : 'ready';
            return {
                profile: name,
                title: name,
                detail: [provider, modelId, status].filter(Boolean).join(' | '),
            };
        });
}

function _openModelPalette() {
    _modelPaletteOptions = _buildModelPaletteOptions();
    if (_modelPaletteOptions.length === 0) {
        notifyUser('No model profiles available yet.', { tone: 'warn', durationMs: 2200, debugKind: 'engine-action' });
        return;
    }
    _modelPaletteIndex = 0;
    _modelPaletteVisible = true;
    composerTextarea.value = '';
    composerTextarea.dispatchEvent(new Event('input'));
    _renderModelPalette();
}

function _renderModelPalette() {
    if (!_modelPaletteVisible) return;
    const el = _getModelPaletteEl();
    const activeProfile = safeString(modelSelector?.value);
    el.innerHTML = _modelPaletteOptions.map((option, index) => {
        const isActive = option.profile === activeProfile;
        return `<div class="slash-palette-item${index === _modelPaletteIndex ? ' active' : ''}" data-idx="${index}">
            <span class="slash-cmd">${escapeHtml(option.title)}${isActive ? ' ' : ''}</span>
            <span class="slash-desc">${escapeHtml(option.detail)}</span>
        </div>`;
    }).join('');
    el.classList.add('visible');
    el.querySelectorAll('.slash-palette-item').forEach((item) => {
        item.addEventListener('click', () => {
            _modelPaletteIndex = parseInt(item.dataset.idx, 10);
            _modelPaletteSelect();
        });
    });
}

function _hideModelPalette() {
    _modelPaletteVisible = false;
    _modelPaletteIndex = 0;
    _modelPaletteOptions = [];
    if (_modelPaletteEl) _modelPaletteEl.classList.remove('visible');
}

function _modelPaletteNav(dir) {
    _modelPaletteIndex = Math.max(0, Math.min(_modelPaletteOptions.length - 1, _modelPaletteIndex + dir));
    _renderModelPalette();
}

async function _persistModelProfileSelection(profile, modelId = '') {
    const patch = {
        advanced: {
            model: {
                active_profile: profile,
                model_id: modelId,
                reasoning_effort: normalizeReasoningEffort(activeReasoningEffort) || 'medium',
            },
        },
    };
    try {
        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patch),
        });
        if (res.ok) {
            currentPreferences = await res.json();
            updateSidebarIdentity();
        }
    } catch (error) {
        console.error('Failed to persist /model selection:', error);
    }
}

function _modelPaletteSelect() {
    const selected = _modelPaletteOptions[_modelPaletteIndex];
    if (!selected) { _hideModelPalette(); return; }
    _hideModelPalette();
    const nextProfile = safeString(selected.profile);
    if (!nextProfile) return;
    applyProfileSelection(nextProfile, { allowLocalBackup: true });
    const nextModelId = resolveActiveModelIdForProfile(nextProfile);
    void _persistModelProfileSelection(nextProfile, nextModelId || '');
    notifyUser(`Model profile set to ${nextProfile}.`, {
        tone: 'success',
        durationMs: 2200,
        debugKind: 'engine-action',
    });
}
