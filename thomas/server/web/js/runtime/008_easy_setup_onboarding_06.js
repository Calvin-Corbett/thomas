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

function includesAny(text, terms = []) {
    return (terms || []).some((term) => text.includes(term));
}

function isSecurityTrustConcern(textRaw) {
    const text = safeString(textRaw).toLowerCase();
    if (!text) return false;
    return includesAny(text, [
        'security',
        'secure',
        'unsafe',
        'cyber',
        'risk',
        'risky',
        'trust',
        'dependency',
        'dependencies',
        'dependency tree',
        'dependency trees',
        'install',
        'installer',
        'download',
        'permission',
        'permissions',
        'malware',
        'virus',
        'supply chain',
    ]);
}

function buildSetupSafetyMessage() {
    return [
        'Fair concern. Setup is designed to be explicit and user-controlled:',
        withAgentName('- No silent installs: {{agent}} only runs dependency installs after your approval.'),
        '- Dependency step shows why each tool is needed and where it comes from.',
        '- You can choose the lowest-download path: Manual API Key.',
        '- Safe defaults keep command approval on so actions stay supervised.',
    ].join('\n');
}

function showSetupSafetySuggestions() {
    setAssistantSuggestions({
        title: 'Setup safety',
        context: 'setup_safety',
        dismissible: false,
        options: [
            {
                label: 'Run Easy Setup',
                kind: 'action',
                tone: 'primary',
                onChoose: async () => {
                    ensureChatVisible();
                    await openEasySetup({ source: 'safety_suggestion', force: false, restart: false });
                },
            },
            {
                label: 'Use lowest-download setup',
                kind: 'action',
                onChoose: async () => {
                    ensureChatVisible();
                    await openEasySetup({ source: 'safety_suggestion', force: false, restart: true });
                    handleEasySetupPathSelect('manual');
                },
            },
            {
                label: 'Show exact downloads',
                kind: 'option',
                send_prompt: withAgentName('Show exactly what {{agent}} installs in each setup path and why each dependency is required.'),
            },
        ],
    });
}

function resolveOnboardingOptionLabel(question, value) {
    const options = Array.isArray(question?.options) ? question.options : [];
    const found = options.find((option) => safeString(option?.value) === safeString(value));
    return safeString(found?.label) || safeString(value);
}

function formatOnboardingQuestionOptionList(question) {
    const options = Array.isArray(question?.options) ? question.options : [];
    return options.map((option) => `"${safeString(option?.label)}"`).filter(Boolean).join(', ');
}

function parseOnboardingQuestionAnswer(question, textRaw) {
    const text = safeString(textRaw).toLowerCase();
    if (!text) return '';
    if (text === 'skip' || includesAny(text, ['skip interview', 'skip questions', 'skip setup', 'skip this'])) {
        return '__skip_interview__';
    }

    const options = Array.isArray(question?.options) ? question.options : [];
    for (const option of options) {
        const valueToken = safeString(option?.value).toLowerCase().replace(/_/g, ' ');
        const labelToken = safeString(option?.label).toLowerCase();
        if ((valueToken && text.includes(valueToken)) || (labelToken && text.includes(labelToken))) {
            return safeString(option?.value);
        }
    }

    const questionId = safeString(question?.id);
    if (questionId === 'experience') {
        if (includesAny(text, ['new', 'beginner', 'novice', 'first time', 'first-time', 'non technical', 'non-technical', 'just starting'])) return 'new';
        if (includesAny(text, ['expert', 'advanced', 'senior', 'professional', 'pro'])) return 'expert';
        if (includesAny(text, ['builder', 'intermediate', 'some experience', 'comfortable'])) return 'builder';
    }
    if (questionId === 'personality') {
        if (includesAny(text, ['direct', 'technical', 'blunt', 'straight', 'no fluff', 'concise'])) return 'direct_technical';
        if (includesAny(text, ['calm', 'friendly', 'gentle', 'coach', 'guide', 'supportive'])) return 'calm_guide';
        if (includesAny(text, ['balanced', 'normal', 'neutral', 'mix'])) return 'balanced';
    }
    if (questionId === 'autonomy') {
        if (includesAny(text, ['guided', 'careful', 'safe', 'step by step', 'step-by-step', 'confirm', 'approval', 'ask first'])) return 'guided';
        if (includesAny(text, ['aggressive', 'autonomous', 'fully auto', 'take over', 'run with it', 'do it all', 'max autonomy'])) return 'aggressive';
        if (includesAny(text, ['balanced', 'normal', 'middle'])) return 'balanced';
    }
    if (questionId === 'cost_quality') {
        if (includesAny(text, ['low cost', 'cheap', 'budget', 'save money', 'cost first', 'economy'])) return 'low_cost';
        if (includesAny(text, ['max quality', 'highest quality', 'best quality', 'quality first', 'accuracy', 'premium'])) return 'max_quality';
        if (includesAny(text, ['balanced', 'middle'])) return 'balanced';
    }
    if (questionId === 'memory') {
        if (includesAny(text, ['disable memory', 'no memory', 'dont remember', 'do not remember', 'forget', 'private'])) return 'disabled';
        if (includesAny(text, ['session only', 'this session', 'temporary', 'temp memory'])) return 'session_only';
        if (includesAny(text, ['remember', 'across sessions', 'persistent', 'save context'])) return 'remember';
    }
    if (questionId === 'workflow') {
        if (includesAny(text, ['build', 'ship', 'feature', 'features', 'product', 'app', 'coding', 'code'])) return 'build_features';
        if (includesAny(text, ['research', 'investigate', 'analyze', 'compare', 'study'])) return 'research';
        if (includesAny(text, ['ops', 'reliability', 'incident', 'monitoring', 'infra', 'infrastructure', 'production', 'stability'])) return 'ops_reliability';
    }
    if (questionId === 'default_toggles') {
        if (includesAny(text, ['safe', 'conservative', 'cautious', 'guardrails', 'approval'])) return 'safe_defaults';
        if (includesAny(text, ['power', 'advanced', 'fast', 'max control', 'pro mode'])) return 'power_mode';
        if (includesAny(text, ['quiet', 'minimal', 'silent', 'fewer notifications', 'no notifications'])) return 'quiet_mode';
    }

    return '';
}

function parseOnboardingSkipConfirmAction(textRaw) {
    const text = safeString(textRaw).toLowerCase();
    if (!text) return '';
    if (includesAny(text, ['finish', 'defaults', 'default settings', 'skip it', 'yes'])) return 'finish_defaults';
    if (includesAny(text, ['resume', 'continue', 'questions', 'go back', 'no'])) return 'resume';
    return '';
}

function parseOnboardingReviewAction(textRaw) {
    const text = safeString(textRaw).toLowerCase();
    if (!text) return '';
    if (includesAny(text, ['open settings', 'settings', 'tweak settings'])) return 'settings';
    if (includesAny(text, ['defaults', 'skip interview', 'finish with defaults', 'use defaults'])) return 'skip';
    if (includesAny(text, ['finish', 'apply', 'done', 'complete', 'looks good', 'yes'])) return 'apply';
    return '';
}

async function submitOnboardingInterviewAnswer(question, value, { source = 'bubble' } = {}) {
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
        source: safeString(source) || 'bubble',
    });
    if (safeString(source) === 'text') {
        const answerLabel = resolveOnboardingOptionLabel(question, value);
        renderMessage({
            role: 'assistant',
            content: `Got it. **${answerLabel}** works for that.`,
        });
    }
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
            await submitOnboardingInterviewAnswer(question, value, { source: 'bubble' });
        }
    );
}

async function handleOnboardingChatInput(textRaw, { docsCount = 0, imagesCount = 0 } = {}) {
    const text = safeString(textRaw);
    if (docsCount > 0 || imagesCount > 0) {
        renderMessage({
            role: 'assistant',
            content: 'For onboarding, plain text replies work best. I ignored attachments for this step.',
        });
    }
    if (!text) {
        renderMessage({
            role: 'assistant',
            content: 'Reply with your preference in plain language, or use a suggestion bubble.',
        });
        return;
    }

    const stage = safeString(easySetupState.interviewStage) || 'question';
    if (stage === 'skip_confirm') {
        const action = parseOnboardingSkipConfirmAction(text);
        if (!action) {
            if (isSecurityTrustConcern(text)) {
                renderMessage({
                    role: 'assistant',
                    content: `${buildSetupSafetyMessage()}\n\nWhen ready, say "finish with defaults" or "resume questions".`,
                });
                return;
            }
            renderMessage({
                role: 'assistant',
                content: 'Say "finish with defaults" or "resume questions".',
            });
            return;
        }
        if (action === 'finish_defaults') {
            try {
                await applyOnboardingCompletion({ skippedInterview: true });
                renderMessage({
                    role: 'assistant',
                    content: withAgentName('Setup complete. {{agent}} is ready with safe defaults.'),
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
        return;
    }

    if (stage === 'review') {
        const action = parseOnboardingReviewAction(text);
        if (!action) {
            if (isSecurityTrustConcern(text)) {
                renderMessage({
                    role: 'assistant',
                    content: `${buildSetupSafetyMessage()}\n\nWhen ready, say "finish setup", "use defaults", or "open settings".`,
                });
                return;
            }
            renderMessage({
                role: 'assistant',
                content: 'Say "finish setup", "use defaults", or "open settings".',
            });
            return;
        }
        if (action === 'settings') {
            openSettingsModal();
            renderMessage({
                role: 'assistant',
                content: 'Settings opened. Return when you want me to finish onboarding.',
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
        return;
    }

    const question = onboardingInterviewQuestions[Number(easySetupState.interviewIndex)];
    if (!question) {
        promptOnboardingQuestion();
        return;
    }

    const parsedValue = parseOnboardingQuestionAnswer(question, text);
    if (parsedValue === '__skip_interview__') {
        easySetupState.interviewSkipChosen = true;
        await promptInterviewSkipConfirm();
        return;
    }
    if (!parsedValue) {
        if (isSecurityTrustConcern(text)) {
            const optionHints = formatOnboardingQuestionOptionList(question);
            renderMessage({
                role: 'assistant',
                content: `${buildSetupSafetyMessage()}\n\nWhen you are ready, answer this step: ${withAgentName(question.prompt)}\nI can map replies like: ${optionHints}.`,
            });
            return;
        }
        const optionHints = formatOnboardingQuestionOptionList(question);
        renderMessage({
            role: 'assistant',
            content: `I can map that, but I am not fully sure yet. Try phrasing it closer to one of: ${optionHints}.`,
        });
        return;
    }

    await submitOnboardingInterviewAnswer(question, parsedValue, { source: 'text' });
}

async function beginOnboardingInterview() {
    easySetupState.interviewStarted = true;
    easySetupState.interviewStage = 'question';
    easySetupState.interviewIndex = 0;
    ensureChatVisible();
    await persistOnboardingPrefs({ current_step: 'interview', dismissed_at: null });
    renderMessage({
        role: 'assistant',
        content: 'Brain handshake complete. I am caffeinated and morally obligated to make this easy. Tell me your preferences in plain English and I will translate them into setup defaults.',
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

function ensureChatComposerSubbar() {
    const inputRow = composerTextarea?.closest('.composer-input-row');
    if (!(inputRow instanceof HTMLElement)) return null;
    const shell = composerBox instanceof HTMLElement ? composerBox : inputRow.parentElement;
    if (!(shell instanceof HTMLElement)) return null;

    let style = document.getElementById('chatComposerSubbarStyle');
    if (!(style instanceof HTMLStyleElement)) {
        style = document.createElement('style');
        style.id = 'chatComposerSubbarStyle';
        style.textContent = `
            .chat-composer-subbar {
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                gap: 6px 10px;
                padding: 6px 8px 0;
                border-top: 1px solid var(--border-light, rgba(255,255,255,0.08));
                margin-top: 4px;
            }
            .chat-composer-control {
                display: flex;
                align-items: center;
                gap: 6px;
                min-width: 0;
            }
            .chat-composer-control[hidden] { display: none !important; }
            .chat-composer-control-label {
                font-size: 10px;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: var(--text-muted, #929bb0);
                white-space: nowrap;
            }
            .chat-composer-control-select {
                min-width: 108px;
                padding: 5px 8px;
                border-radius: 8px;
                border: 1px solid var(--border-light, rgba(255,255,255,0.12));
                background: rgba(19, 22, 30, 0.82);
                color: var(--text-primary, #ececf1);
                font-size: 11px;
                font-weight: 600;
                outline: none;
            }
            .chat-composer-control-select:focus {
                border-color: var(--accent, #58a6ff);
                box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.18);
            }
            @media (max-width: 760px) {
                .chat-composer-subbar {
                    align-items: stretch;
                    gap: 8px;
                }
                .chat-composer-control {
                    width: 100%;
                    justify-content: space-between;
                }
                .chat-composer-control-select {
                    flex: 1 1 auto;
                    min-width: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }

    let root = document.getElementById('chatComposerSubbar');
    if (!(root instanceof HTMLElement)) {
        root = document.createElement('div');
        root.id = 'chatComposerSubbar';
        root.className = 'chat-composer-subbar';
        inputRow.insertAdjacentElement('afterend', root);
    }
    return root;
}

function renderChatComposerSubbar() {
    const root = ensureChatComposerSubbar();
    if (!(root instanceof HTMLElement)) return;

    const profileName = safeString(modelSelector?.value) || safeString(setupProviderSelector?.value);
    const controls = resolveProfileChatControls(profileName);
    const reasoningControl = controls?.model?.reasoning_effort;
    const autonomyControl = controls?.thomas?.autonomy_level;
    const tokenControl = controls?.thomas?.token_economy;
    const reasoningOptions = Array.isArray(reasoningControl?.options) ? reasoningControl.options : [];
    const autonomyOptions = Array.isArray(autonomyControl?.options) ? autonomyControl.options : [];
    const tokenOptions = Array.isArray(tokenControl?.options) ? tokenControl.options : [];

    const renderOptions = (options, selectedValue = '') => options.map((option) => {
        const value = safeString(option?.value);
        const label = safeString(option?.label) || value;
        const selected = value === safeString(selectedValue) ? ' selected' : '';
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
    }).join('');

    root.innerHTML = `
        <div class="chat-composer-control" data-control="reasoning"${reasoningControl?.supported ? '' : ' hidden'}>
            <span class="chat-composer-control-label">${escapeHtml(safeString(reasoningControl?.label) || 'Reasoning')}</span>
            <select id="chatComposerReasoningSelect" class="chat-composer-control-select">
                ${renderOptions(reasoningOptions, normalizeReasoningEffort(activeReasoningEffort))}
            </select>
        </div>
        <div class="chat-composer-control" data-control="autonomy">
            <span class="chat-composer-control-label">${escapeHtml(safeString(autonomyControl?.label) || 'Autonomy')}</span>
            <select id="chatComposerAutonomySelect" class="chat-composer-control-select">
                ${renderOptions(autonomyOptions.length ? autonomyOptions : [
                    { value: '1', label: 'L1 Chat' },
                    { value: '2', label: 'L2 Assist' },
                    { value: '3', label: 'L3 Agent' },
                    { value: '4', label: 'L4 Full Autonomy' },
                ], String(activeAutonomyLevel || 1))}
            </select>
        </div>
        <div class="chat-composer-control" data-control="token_economy">
            <span class="chat-composer-control-label">${escapeHtml(safeString(tokenControl?.label) || 'Token Economy')}</span>
            <select id="chatComposerTokenEconomySelect" class="chat-composer-control-select">
                ${renderOptions(tokenOptions.length ? tokenOptions : [
                    { value: 'cheap', label: 'Cheap' },
                    { value: 'balanced', label: 'Balanced' },
                    { value: 'max', label: 'Maximum' },
                ], safeString(activeTokenEconomy) || 'balanced')}
            </select>
        </div>
    `;

    const reasoningSelect = document.getElementById('chatComposerReasoningSelect');
    if (reasoningSelect instanceof HTMLSelectElement) {
        reasoningSelect.value = normalizeReasoningEffort(activeReasoningEffort);
        reasoningSelect.addEventListener('change', (event) => {
            activeReasoningEffort = normalizeReasoningEffort(event.target.value);
            setSegmentedControlSelection('setupReasoningEffortGroup', activeReasoningEffort);
            if (settingAdvReasoningEffort) settingAdvReasoningEffort.value = activeReasoningEffort || 'medium';
        });
    }

    const autonomySelect = document.getElementById('chatComposerAutonomySelect');
    if (autonomySelect instanceof HTMLSelectElement) {
        autonomySelect.value = String(activeAutonomyLevel || 1);
        autonomySelect.addEventListener('change', (event) => {
            autonomyLevelManuallySet = true;
            activeAutonomyLevel = parseInt(event.target.value, 10) || 1;
            setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
            if (settingAutonomy) settingAutonomy.value = `L${activeAutonomyLevel}`;
        });
    }

    const tokenSelect = document.getElementById('chatComposerTokenEconomySelect');
    if (tokenSelect instanceof HTMLSelectElement) {
        tokenSelect.value = safeString(activeTokenEconomy) || 'balanced';
        tokenSelect.addEventListener('change', (event) => {
            activeTokenEconomy = safeString(event.target.value) || 'balanced';
            setSegmentedControlSelection('setupEconomyGroup', activeTokenEconomy);
            const runtimeValue = activeTokenEconomy === 'balanced' ? 'optimal' : activeTokenEconomy;
            if (settingAdvDefaultTokenEconomy) settingAdvDefaultTokenEconomy.value = runtimeValue;
        });
    }
}

function initChatComposerSubbar() {
    ensureChatComposerSubbar();
    renderChatComposerSubbar();
}

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
    const payload = {
        message: message,
        docs: Array.isArray(docs) ? docs : [],
        images: Array.isArray(images) ? images : [],
        session_id: sessionId,
        profile: profile,
        model: profile,
        model_id: safeString(specialty?.modelId) || resolveActiveModelIdForProfile(profile) || undefined,
        autonomy_level: Math.max(1, parseInt(String(activeAutonomyLevel || 1), 10) || 1),
        token_economy: resolveChatPayloadTokenEconomy(),
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

