function chatGameAdvanceTime(ms = 16) {
    if (!chatGameRuntime.activeGameId) return;
    const totalMs = Number.isFinite(ms) ? Math.max(1, Number(ms)) : 16;
    const steps = Math.max(1, Math.round(totalMs / (1000 / 60)));
    for (let i = 0; i < steps; i += 1) {
        chatGameStep(1);
    }
    chatGameRender();
}

window.render_game_to_text = chatGameRenderToTextPayload;
window.advanceTime = chatGameAdvanceTime;

function chatGameHandleKeyInput(event, pressed) {
    if (!chatGameRuntime.activeGameId) return;
    const target = event.target;
    const targetIsInput = (
        target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || (target instanceof HTMLElement && target.isContentEditable)
    );
    if (targetIsInput) return;

    const key = String(event.key || '').toLowerCase();
    const activeGame = chatGameRuntime.activeGameId;

    if (activeGame === 'cloud_jump') {
        if (key === 'arrowleft' || key === 'a') {
            chatGameRuntime.input.left = pressed;
            event.preventDefault();
            return;
        }
        if (key === 'arrowright' || key === 'd') {
            chatGameRuntime.input.right = pressed;
            event.preventDefault();
            return;
        }
        if (key === ' ' || key === 'spacebar') {
            if (!pressed) return;
            event.preventDefault();
            const state = chatGameRuntime.cloudJump;
            if (state?.mode === 'ready') {
                chatGameStartRun(state);
                return;
            }
            if (state?.mode === 'game_over') {
                chatGameRestartActive();
            }
            return;
        }
    } else if (activeGame === JETPACK_GAME_ID) {
        if (key === 'arrowup' || key === 'w') {
            chatGameRuntime.input.up = pressed;
            event.preventDefault();
            return;
        }
        if (key === 'arrowdown' || key === 's') {
            chatGameRuntime.input.down = pressed;
            event.preventDefault();
            return;
        }
        if (key === ' ' || key === 'spacebar') {
            if (!pressed) return;
            event.preventDefault();
            const state = chatGameRuntime.jetpackJoyride;
            if (state?.mode === 'ready') {
                chatGameStartJetpackRun(state);
                return;
            }
            if (state?.mode === 'game_over') {
                chatGameRestartActive();
            }
            return;
        }
    } else if (activeGame === DINO_GAME_ID) {
        const dinoState = chatGameRuntime.dinoRun;
        const triggerDinoPrimary = () => {
            if (!dinoState) return;
            if (dinoState.mode === 'ready') {
                chatGameStartDinoRun(dinoState);
                return;
            }
            if (dinoState.mode === 'playing') {
                chatGameDinoJump(dinoState);
                return;
            }
            if (dinoState.mode === 'game_over') {
                chatGameRestartActive();
            }
        };

        if (key === 'arrowdown' || key === 's') {
            chatGameRuntime.input.down = pressed;
            event.preventDefault();
            return;
        }
        if (key === 'arrowup' || key === 'w') {
            chatGameRuntime.input.up = pressed;
            if (!pressed) return;
            event.preventDefault();
            triggerDinoPrimary();
            return;
        }
        if (key === ' ' || key === 'spacebar') {
            if (!pressed) return;
            event.preventDefault();
            triggerDinoPrimary();
            return;
        }
    }

    if (!pressed) return;
    if (key === 'r') {
        chatGameRestartActive();
        return;
    }
    if (key === 'escape') {
        chatGameClose({ clearMode: true });
    }
}

function chatGameBootFromUrl() {
    let gameId = '';
    try {
        const params = new URLSearchParams(window.location.search || '');
        gameId = safeString(params.get('game') || params.get('chat_game')).toLowerCase();
    } catch (_error) {
        gameId = '';
    }
    if (gameId !== 'cloud_jump' && gameId !== JETPACK_GAME_ID && gameId !== DINO_GAME_ID) return;
    window.setTimeout(() => {
        chatGameOpen(gameId);
    }, 150);
}

function initChatGame() {
    const best = chatGameGetHighScore();
    if (chatGameScore) chatGameScore.textContent = '0';
    if (chatGameHighScore) chatGameHighScore.textContent = String(best);
    if (composerDinoScore) composerDinoScore.textContent = '0';
    if (composerDinoHighScore) composerDinoHighScore.textContent = String(chatGameGetHighScore(DINO_GAME_ID));
    chatGameSetStatusText('Press Space to start | Esc to exit');
    chatGameSetPanelOpen(false);
    chatGameSetDinoSurfaceOpen(false);
    chatGameSetCenterMuted(false);
    chatGameSetPhaseClass('');
    if (chatGamePanel) {
        chatGamePanel.classList.remove('door-visible');
        chatGamePanel.classList.remove('jetpack-mode');
    }

    if (chatGameCloseBtn) {
        chatGameCloseBtn.addEventListener('click', () => {
            chatGameClose({ clearMode: true });
        });
    }
    if (chatGameRestartBtn) {
        chatGameRestartBtn.addEventListener('click', () => {
            chatGameRestartActive();
        });
    }

    document.addEventListener('keydown', (event) => {
        chatGameHandleKeyInput(event, true);
    });
    document.addEventListener('keyup', (event) => {
        chatGameHandleKeyInput(event, false);
    });
    chatGameBootFromUrl();
}

// 
//   ACTIONS & INTERACTIONS                                                 
//   Send/stop, file attach, chat search, keyboard shortcuts, streaming     
// 

function initActions() {
    function prepareManualSendFromComposer() {
        if (typeof window.__thomasStopMicCapture === 'function') {
            window.__thomasStopMicCapture({ send: false });
        }
    }

    sendBtn.addEventListener('click', () => {
        if (isGenerating) {
            const hasQueuedInput = composerTextarea.value.trim().length > 0 || pendingDocs.length > 0 || pendingImages.length > 0;
            if (hasQueuedInput) {
                prepareManualSendFromComposer();
                void handleSend();
            } else {
                // It's a stop button right now
                stopGeneration();
            }
        } else {
            prepareManualSendFromComposer();
            void handleSend();
        }
    });

    // Delegated click handlers for chat area (code copy + message copy)
    chatMessagesInner.addEventListener('click', (e) => {
        // Code block copy button
        const copyCodeBtn = e.target.closest('.code-block-copy');
        if (copyCodeBtn) {
            const wrapper = copyCodeBtn.closest('.code-block-wrapper');
            const code = wrapper ? wrapper.querySelector('code') : null;
            if (code) {
                navigator.clipboard.writeText(code.textContent).then(() => {
                    copyCodeBtn.innerHTML = '<i class="ph ph-check"></i> Copied';
                    showToast('Copied to clipboard');
                    setTimeout(() => { copyCodeBtn.innerHTML = '<i class="ph ph-copy"></i> Copy'; }, 2000);
                });
            }
            return;
        }
        // Message copy button
        const msgCopyBtn = e.target.closest('.msg-action-btn[data-action="copy"]');
        if (msgCopyBtn) {
            const row = msgCopyBtn.closest('.message-row');
            const content = row ? row.querySelector('.message-content') : null;
            if (content) {
                navigator.clipboard.writeText(content.innerText || content.textContent).then(() => {
                    showToast('Copied to clipboard');
                });
            }
            return;
        }
        // Edit user message button
        const msgEditBtn = e.target.closest('.msg-action-btn[data-action="edit"]');
        if (msgEditBtn) {
            const row = msgEditBtn.closest('.message-row');
            if (row) beginEditMessage(row);
            return;
        }
        // Regenerate assistant response button
        const msgRegenBtn = e.target.closest('.msg-action-btn[data-action="regenerate"]');
        if (msgRegenBtn) {
            const row = msgRegenBtn.closest('.message-row');
            if (row) regenerateResponse(row);
            return;
        }
        // Save edited message button
        const msgSaveBtn = e.target.closest('.msg-edit-save');
        if (msgSaveBtn) {
            const row = msgSaveBtn.closest('.message-row');
            if (row) commitEditMessage(row);
            return;
        }
        // Cancel edit button
        const msgCancelBtn = e.target.closest('.msg-edit-cancel');
        if (msgCancelBtn) {
            const row = msgCancelBtn.closest('.message-row');
            if (row) cancelEditMessage(row);
            return;
        }
        // Pin message button
        const msgPinBtn = e.target.closest('.msg-action-btn[data-action="pin"]');
        if (msgPinBtn) {
            const row = msgPinBtn.closest('.message-row');
            if (row) togglePinMessage(row);
            return;
        }
    });

    // Attachments
    attachBtn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        composerToggleActionsMenu();
    });

    if (composerModeChipCloseBtn) {
        composerModeChipCloseBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            composerClearMode();
            if (composerTextarea) {
                composerTextarea.focus();
            }
        });
    }

    if (composerActionList) {
        composerActionList.addEventListener('click', (event) => {
            if (!(event.target instanceof Element)) return;
            const button = event.target.closest('[data-action]');
            if (!(button instanceof HTMLButtonElement)) return;
            composerHandleQuickAction(button.dataset.action);
        });
    }
    if (composerGamesColumn) {
        composerGamesColumn.addEventListener('click', (event) => {
            if (!(event.target instanceof Element)) return;
            const button = event.target.closest('[data-game]');
            if (!(button instanceof HTMLButtonElement)) return;
            composerHandleGameChoice(button.dataset.game);
        });
    }
    document.addEventListener('click', (event) => {
        if (!composerActionsOpen) return;
        if (!(event.target instanceof Element)) return;
        if (event.target.closest('#attachBtn')) return;
        if (event.target.closest('#composerActionPopover')) return;
        composerCloseActionsMenu();
    });
    // Microphone
    let recognition = null;
    let micShouldListen = false;
    let micIsListening = false;
    let micPendingSend = false;
    let micSuppressTranscriptUntil = 0;
    let micBaseText = '';
    let micFinalText = '';
    let micMediaRecorder = null;
    let micMediaStream = null;
    let micRecorderMimeType = '';
    let micRecordedChunks = [];
    let micIsTranscribing = false;
    let micPreferServerCapture = true;
    const micTranscribeEndpoint = '/api/v2/chat/transcribe';

    function setMicButtonState(state = 'idle') {
        if (!(micBtn instanceof HTMLElement)) return;
        if (state === 'listening') {
            micBtn.style.color = 'var(--danger-ink)';
            setElementA11y(micBtn, { title: 'Stop microphone capture', label: 'Stop microphone capture' });
            return;
        }
        if (state === 'transcribing') {
            micBtn.style.color = 'var(--accent, #58a6ff)';
            setElementA11y(micBtn, { title: 'Transcribing microphone input', label: 'Transcribing microphone input' });
            return;
        }
        micBtn.style.color = 'var(--text-secondary)';
        setElementA11y(micBtn, { title: 'Use microphone', label: 'Use microphone' });
    }

    function suppressMicTranscript(ms = 1200) {
        micSuppressTranscriptUntil = Date.now() + Math.max(0, Number(ms) || 0);
    }

    function joinSpeechText(leftRaw, rightRaw) {
        const left = safeString(leftRaw).trim();
        const right = safeString(rightRaw).trim();
        if (!right) return left;
        if (!left) return right;
        const needsSpace = !/\s$/.test(left) && !/^[,.;:!?)]/.test(right);
        return needsSpace ? `${left} ${right}` : `${left}${right}`;
    }

    function renderMicTranscript(interimRaw = '') {
        if (!micShouldListen && !micIsListening && !micIsTranscribing) return;
        if (Date.now() < micSuppressTranscriptUntil || Date.now() < composerInputLockUntil) return;
        const spokenText = joinSpeechText(micFinalText, interimRaw);
        composerTextarea.value = joinSpeechText(micBaseText, spokenText);
        composerTextarea.dispatchEvent(new Event('input'));
    }

    function resetMicDraftState() {
        micBaseText = '';
        micFinalText = '';
        micRecordedChunks = [];
    }

    function stopMicMediaStream() {
        if (micMediaStream?.getTracks) {
            micMediaStream.getTracks().forEach((track) => {
                try {
                    track.stop();
                } catch {
                    // Ignore track shutdown errors.
                }
            });
        }
        micMediaStream = null;
    }

    async function transcribeMicBlob(blob) {
        const form = new FormData();
        const blobType = safeString(blob?.type).toLowerCase();
        const ext = blobType.includes('ogg') ? 'ogg' : blobType.includes('mp4') ? 'm4a' : 'webm';
        form.append('audio', blob, `thomas-mic.${ext}`);
        const response = await fetch(micTranscribeEndpoint, {
            method: 'POST',
            body: form,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(safeString(payload?.error) || `Transcription failed (${response.status})`);
        }
        return safeString(payload?.text);
    }

    function flushPendingMicSend() {
        if (!micPendingSend) return;
        micPendingSend = false;
        suppressMicTranscript();
        resetMicDraftState();
        void handleSend();
    }

    async function finalizeServerMicCapture() {
        const mimeType = safeString(micRecorderMimeType) || 'audio/webm';
        const parts = micRecordedChunks.slice();
        micRecordedChunks = [];
        let transcript = '';
        if (parts.length > 0) {
            micIsTranscribing = true;
            setMicButtonState('transcribing');
            try {
                transcript = await transcribeMicBlob(new Blob(parts, { type: mimeType }));
            } catch (error) {
                console.warn('Microphone transcription failed', error);
                micPendingSend = false;
                const errorText = safeString(error?.message);
                if (recognition && /no stt provider available/i.test(errorText)) {
                    micPreferServerCapture = false;
                    notifyUser('Server transcription is unavailable right now. Falling back to browser speech recognition.', {
                        tone: 'warning',
                        debugKind: 'warning',
                        durationMs: 3600,
                    });
                } else {
                    notifyUser(errorText || 'Microphone transcription failed.', {
                        tone: 'warning',
                        debugKind: 'warning',
                        durationMs: 3200,
                    });
                }
            } finally {
                micIsTranscribing = false;
            }
        }

        micShouldListen = false;
        micIsListening = false;
        setMicButtonState('idle');

        if (transcript) {
            micFinalText = joinSpeechText(micFinalText, transcript);
            renderMicTranscript('');
        }
        flushPendingMicSend();
    }

    function stopMicCapture({ send = false } = {}) {
        micPendingSend = Boolean(send) || micPendingSend;
        micShouldListen = false;

        if (micMediaRecorder) {
            if (micIsTranscribing) return;
            if (micMediaRecorder.state !== 'inactive') {
                try {
                    micMediaRecorder.stop();
                    return;
                } catch {
                    micMediaRecorder = null;
                    stopMicMediaStream();
                }
            }
            setMicButtonState('idle');
            flushPendingMicSend();
            return;
        }

        if (!recognition) {
            setMicButtonState('idle');
            flushPendingMicSend();
            return;
        }
        if (!micIsListening) {
            setMicButtonState('idle');
            flushPendingMicSend();
            return;
        }
        try {
            recognition.stop();
        } catch {
            micIsListening = false;
            setMicButtonState('idle');
            flushPendingMicSend();
        }
    }

    async function startServerMicCapture() {
        let stream = null;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });
        } catch {
            notifyUser('Microphone permission was denied or unavailable.', {
                tone: 'warning',
                debugKind: 'warning',
                durationMs: 2800,
            });
            return false;
        }

        try {
            const preferredMimeTypes = [
                'audio/webm;codecs=opus',
                'audio/webm',
                'audio/ogg;codecs=opus',
                'audio/ogg',
            ];
            const supportedMimeType = preferredMimeTypes.find((candidate) => {
                return typeof MediaRecorder.isTypeSupported === 'function' && MediaRecorder.isTypeSupported(candidate);
            }) || '';
            const recorder = supportedMimeType
                ? new MediaRecorder(stream, { mimeType: supportedMimeType })
                : new MediaRecorder(stream);
            micMediaStream = stream;
            micMediaRecorder = recorder;
            micRecorderMimeType = supportedMimeType || safeString(recorder.mimeType) || 'audio/webm';
            micRecordedChunks = [];
            micShouldListen = true;

            recorder.onstart = () => {
                micIsListening = true;
                setMicButtonState('listening');
            };
            recorder.ondataavailable = (event) => {
                if (event?.data?.size) micRecordedChunks.push(event.data);
            };
            recorder.onerror = () => {
                micIsListening = false;
                micShouldListen = false;
                micMediaRecorder = null;
                stopMicMediaStream();
                setMicButtonState('idle');
                notifyUser('Microphone capture stopped unexpectedly.', {
                    tone: 'warning',
                    debugKind: 'warning',
                    durationMs: 2800,
                });
            };
            recorder.onstop = () => {
                micMediaRecorder = null;
                stopMicMediaStream();
                void finalizeServerMicCapture();
            };
            recorder.start(250);
            return true;
        } catch {
            stopMicMediaStream();
            notifyUser('Unable to start microphone capture right now.', {
                tone: 'warning',
                debugKind: 'warning',
                durationMs: 2800,
            });
            return false;
        }
    }

    function startSpeechRecognitionCapture() {
        if (!recognition || micShouldListen || micIsListening) return;
        micShouldListen = true;
        try {
            recognition.start();
        } catch {
            micShouldListen = false;
            micIsListening = false;
            setMicButtonState('idle');
            notifyUser('Unable to start microphone capture right now.', {
                tone: 'warning',
                debugKind: 'warning',
                durationMs: 2800,
            });
        }
    }

    async function startMicCapture() {
        if (micShouldListen || micIsListening || micIsTranscribing) return;
        resetMicDraftState();
        micBaseText = safeString(composerTextarea.value);
        micPendingSend = false;

        if (recognition) {
            startSpeechRecognitionCapture();
            return;
        }

        if (micPreferServerCapture && navigator.mediaDevices?.getUserMedia && typeof window.MediaRecorder !== 'undefined') {
            const started = await startServerMicCapture();
            if (started) return;
        }

        notifyUser("Speech recognition isn't supported in this browser.", {
            tone: 'warning',
            debugKind: 'warning',
            durationMs: 2800,
        });
    }

    window.__thomasStopMicCapture = ({ send = false } = {}) => {
        stopMicCapture({ send });
        suppressMicTranscript(2200);
    };

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            // Close any open overlays/modals/popovers
            const thinkDrop = document.getElementById('thinkingEffortDropdown');
            if (thinkDrop && !thinkDrop.classList.contains('hidden')) {
                thinkDrop.classList.add('hidden');
                return;
            }
            if (settingsModal && !settingsModal.classList.contains('hidden')) {
                settingsModal.classList.add('hidden');
                return;
            }
            if (easySetupModal && !easySetupModal.classList.contains('hidden')) {
                easySetupModal.classList.add('hidden');
                if (easySetupBackdrop) easySetupBackdrop.classList.add('hidden');
                return;
            }
            // Stop generation if running
            if (isGenerating) {
                stopGeneration();
                return;
            }
            composerCloseActionsMenu();
        }
        // Ctrl+Shift+N  new chat
        if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'N') {
            event.preventDefault();
            if (typeof startNewSession === 'function') startNewSession();
        }
        // Ctrl+F  in-chat search
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key === 'f') {
            // Only override Ctrl+F when chat area is visible
            const chatVisible = chatScrollArea && !chatScrollArea.classList.contains('hidden');
            if (chatVisible) {
                event.preventDefault();
                toggleChatSearch();
            }
        }
        // Ctrl+Shift+E  export conversation
        if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'E') {
            event.preventDefault();
            exportChatConversation();
        }
        if (
            event.key === 'End'
            && !event.ctrlKey
            && !event.metaKey
            && !event.altKey
            && !event.shiftKey
            && (micShouldListen || micIsListening || micIsTranscribing)
        ) {
            event.preventDefault();
            stopMicCapture({ send: true });
        }
    });

    docFileInput.addEventListener('change', async (e) => {
        composerCloseActionsMenu();
        for (const file of e.target.files) {
            if (file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = (re) => {
                    pendingImages.push({ data_url: re.target.result, name: file.name });
                    renderAttachmentsPreview();
                    composerSyncSendButtonState();
                };
                reader.readAsDataURL(file);
            } else {
                const text = await file.text();
                pendingDocs.push({ name: file.name, text: text });
                renderAttachmentsPreview();
                composerSyncSendButtonState();
            }
        }
        docFileInput.value = ''; // reset
        composerSyncSendButtonState();
    });

    if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;

        recognition.onstart = () => {
            micIsListening = true;
            setMicButtonState('listening');
        };

        recognition.onresult = (e) => {
            let interimText = '';
            for (let i = e.resultIndex; i < e.results.length; i += 1) {
                const result = e.results[i];
                const transcript = safeString(result?.[0]?.transcript).trim();
                if (!transcript) continue;
                if (result.isFinal) {
                    micFinalText = joinSpeechText(micFinalText, transcript);
                } else {
                    interimText = joinSpeechText(interimText, transcript);
                }
            }
            renderMicTranscript(interimText);
        };

        recognition.onend = () => {
            micIsListening = false;
            if (micShouldListen) {
                try {
                    recognition.start();
                    return;
                } catch {
                    micShouldListen = false;
                }
            }
            setMicButtonState('idle');
            flushPendingMicSend();
        };

        recognition.onerror = (e) => {
            micIsListening = false;
            if (safeString(e?.error) === 'not-allowed' || safeString(e?.error) === 'service-not-allowed') {
                micShouldListen = false;
                micPendingSend = false;
                notifyUser('Microphone permission was denied.', {
                    tone: 'warning',
                    debugKind: 'warning',
                    durationMs: 2800,
                });
            }
            setMicButtonState('idle');
        };
    }

    micBtn.addEventListener('click', () => {
        if (micShouldListen || micIsListening || micIsTranscribing) {
            stopMicCapture({ send: false });
        } else {
            void startMicCapture();
        }
    });

    // Suggestion chips
    document.querySelectorAll('.suggestion-chip').forEach(btn => {
        btn.addEventListener('click', (e) => {
            composerTextarea.value = e.currentTarget.innerText.trim();
            composerTextarea.dispatchEvent(new Event('input')); // trigger resize and enable button
            composerTextarea.focus();
        });
    });

    if (assistantSuggestionDismissBtn) {
        assistantSuggestionDismissBtn.addEventListener('click', () => {
            hideAssistantSuggestions();
        });
    }
}

/**
 * Execute the send flow
 */
function buildSendJobFromComposer(textRaw = '') {
    const text = safeString(textRaw).trim();
    const docsToSend = [...pendingDocs];
    const imagesToSend = [...pendingImages];
    const modeId = safeString(composerModeSelection?.id).toLowerCase();
    const modeLabel = safeString(composerModeSelection?.label);
    const modeKind = safeString(composerModeSelection?.kind);
    const modePromptPrefix = safeString(composerModeSelection?.promptPrefix);
    if (!text && docsToSend.length === 0 && imagesToSend.length === 0 && modeId !== 'evolve') return null;
    const clientMessageId = `u-${Date.now()}-${Math.floor(Math.random() * 100000)}`;

    composerTextarea.value = '';
    composerTextarea.dispatchEvent(new Event('input'));
    pendingDocs = [];
    pendingImages = [];
    renderAttachmentsPreview();

    const suggestionUserContext = [
        safeString(text),
        docsToSend.length > 0 ? `Attached ${docsToSend.length} document(s)` : '',
        imagesToSend.length > 0 ? `Attached ${imagesToSend.length} image(s)` : '',
    ].filter(Boolean).join(' | ');
    return {
        text,
        docsToSend,
        imagesToSend,
        suggestionUserContext,
        clientMessageId,
        composerModeId: modeId,
        composerModeLabel: modeLabel,
        composerModeKind: modeKind,
        composerModePromptPrefix: modePromptPrefix,
    };
}

async function drainQueuedSends() {
    if (isGenerating || queuedSendDrainActive || pendingSendQueue.length === 0) return;
    queuedSendDrainActive = true;
    try {
        while (!isGenerating && pendingSendQueue.length > 0) {
            const next = pendingSendQueue.shift();
            if (!next) continue;
            await runChatSendJob(next);
        }
    } finally {
        queuedSendDrainActive = false;
        composerSyncSendButtonState();
    }
}

async function runEvolveMissionJob(sendJob, { profile = '', modelId = '' } = {}) {
    const goal = safeString(sendJob?.text).trim();
    const chatSessionId = safeString(sessionId || activeChatId);
    const payload = {
        kind: 'evolve_session',
        name: goal ? `Evolve: ${goal.slice(0, 48)}` : 'Evolve Thomas',
        goal,
        prompt: goal,
        profile: safeString(profile),
        model_id: safeString(modelId),
        session_id: chatSessionId,
        passes: 1,
        promote_on_pass: false,
    };
    const res = await fetch('/api/mission/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const details = await res.text();
        throw new Error(details || `HTTP ${res.status}`);
    }
    const created = await res.json();
    const job = created?.job || {};
    const jobId = safeString(job.id) || `${Date.now()}`;
    const jobName = safeString(job.name) || safeString(payload.name) || 'Evolve Thomas';
    const assistantMessageId = `mission-evolve-queued-${jobId}`;
    const assistantContent = `${jobName} is running in the background.

I'll reply here when it finishes. Mission Control is available from the left sidebar if you want live details.

Green-side evolve mode is syncing blue -> green, running a self-improvement pass, and verifying before any promotion.`;
    if (appendAssistantChatHistoryMessage(assistantContent, assistantMessageId)) {
        syncActiveChatSidebarEntry();
        void persistActiveChat({ quiet: true });
    }
    composerClearMode();
    notifyUser(`${jobName} queued.`, {
        tone: 'success',
        durationMs: 1900,
        debugKind: 'mission-job',
    });
    void refreshTaskContinuity({ sessionOverride: chatSessionId, force: true });
    void missionRefresh({ force: true, silent: true });
}

async function runChatSendJob(sendJob) {
    const text = safeString(sendJob?.text).trim();
    const docsToSend = Array.isArray(sendJob?.docsToSend) ? sendJob.docsToSend : [];
    const imagesToSend = Array.isArray(sendJob?.imagesToSend) ? sendJob.imagesToSend : [];
    const suggestionUserContext = safeString(sendJob?.suggestionUserContext);
    const queuedModeId = safeString(sendJob?.composerModeId).toLowerCase();
    const clientMessageId = safeString(sendJob?.clientMessageId) || `u-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
    if (!text && docsToSend.length === 0 && imagesToSend.length === 0 && queuedModeId !== 'evolve') return;

    if (safeString(suggestionContext) !== 'onboarding') {
        hideAssistantSuggestions({ force: true });
    }
    if (welcomeScreen && !welcomeScreen.classList.contains('hidden')) {
        welcomeScreen.classList.add('hidden');
        chatScrollArea.classList.remove('hidden');
    }

    // Build user message content once for both display and history.
    // Attachments now render as real thumbnails / file badges below the text
    // (see buildMessageAttachments in renderMessage), so we no longer inject
    // the old "(Attached N …)" placeholder text into the bubble.
    let userContent = safeString(text);
    if (!userContent && docsToSend.length === 0 && imagesToSend.length === 0) {
        userContent = (queuedModeId === 'evolve' ? '(Evolve Thomas)' : '(Sent Attachments)');
    }
    const attachmentMeta = {};
    if (imagesToSend.length > 0) attachmentMeta.images = imagesToSend;
    if (docsToSend.length > 0) attachmentMeta.docs = docsToSend;

    // Skip rendering if already shown when queued
    if (!sendJob._alreadyRendered) {
        const existingUserRow = document.getElementById(clientMessageId);
        if (!existingUserRow) {
            renderMessage({ role: 'user', content: userContent, id: clientMessageId, ...attachmentMeta });
        }
    }
    if (!safeString(activeChatId)) {
        activeChatId = safeString(sessionId) || `chat-${Date.now()}`;
    }
    chatHistory.push({
        id: clientMessageId,
        role: 'user',
        content: userContent,
        createdAt: Date.now(),
        status: 'complete',
        toolCalls: [],
        ...attachmentMeta,
    });
    syncActiveChatSidebarEntry();
    void persistActiveChat({ quiet: true });

    const sendMode = {
        id: safeString(sendJob?.composerModeId).toLowerCase(),
        label: safeString(sendJob?.composerModeLabel),
        kind: safeString(sendJob?.composerModeKind),
        promptPrefix: safeString(sendJob?.composerModePromptPrefix),
    };
    let finalPrompt = setupPersonalitySelector.value;
    if (finalPrompt === 'custom') {
        finalPrompt = setupCustomPrompt.value.trim();
    }

    const selectedProfile = modelSelector.value || setupProviderSelector.value;
    const studioChatContext = typeof moduleStudioBuildChatContext === 'function' ? moduleStudioBuildChatContext() : { enabled: false, preferredProfile: '', context: {} };
    const preferredProfile = safeString(studioChatContext.preferredProfile);
    const resolvedProfile = preferredProfile || selectedProfile;
    if (preferredProfile && preferredProfile !== safeString(selectedProfile) && typeof applyProfileSelection === 'function') {
        applyProfileSelection(preferredProfile);
    }
    if (sendMode.id === 'evolve') {
        try {
            await runEvolveMissionJob(sendJob, { profile: resolvedProfile, modelId: resolveActiveModelIdForProfile(resolvedProfile) || '' });
        } catch (error) {
            console.error('Evolve mission launch failed', error);
            notifyUser(`Failed to launch evolve mode: ${safeString(error?.message) || 'unknown error'}`, {
                tone: 'warning',
                durationMs: 2600,
                debugKind: 'mission-job',
            });
        }
        return;
    }

    setGeneratingState(true);
    pushDebugEvent('chat', 'Started chat request');

    const modelMessage = composerBuildMessageForModel(text, sendMode);
    const payload = buildChatRequestPayload(modelMessage || text, {
        docs: docsToSend,
        images: imagesToSend,
        systemPrompt: finalPrompt || undefined,
        resolvedProfile,
        studioChatContext,
    });

    await streamChatResponse(payload, { userContext: suggestionUserContext });
}

async function handleSend() {
    composerCloseActionsMenu();
    const text = composerTextarea.value.trim();
    if (!text && pendingDocs.length === 0 && pendingImages.length === 0) return;
    composerInputLockUntil = Date.now() + 1600;

    if (isOnboardingSlashCommand(text) && pendingDocs.length === 0 && pendingImages.length === 0) {
        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        ensureChatVisible();
        renderMessage({ role: 'user', content: text });
        renderMessage({ role: 'assistant', content: 'Opening Easy Setup. We will verify your connection before setup continues.' });
        openEasySetup({ source: 'slash', force: true });
        return;
    }

    if (!isOnboardingComplete()) {
        if (easySetupState.interviewStarted) {
            const docsToSend = [...pendingDocs];
            const imagesToSend = [...pendingImages];
            composerTextarea.value = '';
            composerTextarea.dispatchEvent(new Event('input'));
            pendingDocs = [];
            pendingImages = [];
            renderAttachmentsPreview();
            ensureChatVisible();

            let uiText = text;
            if (docsToSend.length > 0) uiText += `\n\n*(Attached ${docsToSend.length} document(s))*`;
            if (imagesToSend.length > 0) uiText += `\n\n*(Attached ${imagesToSend.length} image(s))*`;
            if (safeString(uiText)) {
                renderMessage({ role: 'user', content: uiText });
            }

            await handleOnboardingChatInput(text, {
                docsCount: docsToSend.length,
                imagesCount: imagesToSend.length,
            });
            return;
        }

        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        pendingDocs = [];
        pendingImages = [];
        renderAttachmentsPreview();
        ensureChatVisible();
        if (safeString(text)) {
            renderMessage({ role: 'user', content: text });
        }
        renderMessage({
            role: 'assistant',
            content: withAgentName('Finish Easy Setup first. {{agent}} requires setup before chat can run.'),
        });
        openEasySetup({ source: 'mandatory', force: false, restart: false });
        return;
    }

    const sendJob = buildSendJobFromComposer(text);
    if (!sendJob) return;
    if (isGenerating) {
        // FIX (2026-03-18): Don't abort the current generation when user
        // sends a new message. Instead, send it as an interrupt to the backend
        // so Thomas can keep working while the user keeps chatting.
        // The backend queues the message and the active run picks it up.
        const interruptPayload = {
            text: text,
            session_id: sessionId,
            profile: safeString(
                (typeof modelSelector !== 'undefined' && modelSelector ? modelSelector.value : '')
                || (typeof setupProviderSelector !== 'undefined' && setupProviderSelector ? setupProviderSelector.value : '')
                || (typeof currentPreferences !== 'undefined' ? currentPreferences?.advanced?.model?.active_profile : '')
            ),
            busy_strategy: 'interrupt',
        };
        // Render user message immediately
        renderMessage({ role: 'user', content: text });
        chatHistory.push({
            role: 'user',
            content: text,
            createdAt: Date.now(),
            status: 'complete',
        });
        // Fire and forget — don't block, don't abort current stream
        const chatEndpoint = '/api/v2/chat';
        fetch(chatEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(interruptPayload),
        }).catch(err => console.warn('[Thomas] Interrupt send failed:', err));
        // Clear composer
        composerTextarea.value = '';
        composerTextarea.dispatchEvent(new Event('input'));
        composerSyncSendButtonState();
        return;
    }

    await runChatSendJob(sendJob);
}

const VIBE_CODE_FALLBACK_NODES = [
    {
        id: 'user.input',
        label: 'User Input',
        kind: 'user',
        summary: 'Waiting for request.',
    },
    {
        id: 'api.chat.request',
        label: 'Chat API Request',
        kind: 'server',
        summary: 'Waiting for request.',
    },
    {
        id: 'session.resolve',
        label: 'Session + Runtime Resolve',
        kind: 'server',
        summary: 'Waiting for request.',
    },
    {
        id: 'route.select',
        label: 'Route Selection',
        kind: 'router',
        summary: 'Waiting for route selection.',
    },
    {
        id: 'llm.generate',
        label: 'LLM Generate',
        kind: 'model',
        summary: 'Waiting for model output.',
    },
    {
        id: 'tool.exec',
        label: 'Tool Execution',
        kind: 'tool',
        summary: 'No tools yet.',
    },
    {
        id: 'response.stream',
        label: 'Response Stream',
        kind: 'stream',
        summary: 'Waiting for streamed response.',
    },
    {
        id: 'response.done',
        label: 'Response Finalized',
        kind: 'result',
        summary: 'Waiting for completion.',
    },
];
const VIBE_CODE_FALLBACK_EDGES = [
    { from: 'user.input', to: 'api.chat.request' },
    { from: 'api.chat.request', to: 'session.resolve' },
    { from: 'session.resolve', to: 'route.select' },
    { from: 'route.select', to: 'llm.generate' },
    { from: 'llm.generate', to: 'tool.exec' },
    { from: 'tool.exec', to: 'response.stream' },
    { from: 'response.stream', to: 'response.done' },
];
const VIBE_CODE_PROJECT_NODES = [
    { id: 'project.frontend', label: 'Frontend UI', summary: 'Sidebar, composer, and user input.' },
    { id: 'project.api', label: 'Chat API', summary: 'HTTP/SSE stream entrypoint.' },
    { id: 'project.session', label: 'Session + Memory', summary: 'Session/profile/runtime context.' },
    { id: 'project.router', label: 'Route + Planner', summary: 'Routing and execution strategy.' },
    { id: 'project.model', label: 'Model Runtime', summary: 'Reasoning + generation.' },
    { id: 'project.tools', label: 'Tool Runtime', summary: 'Tool calls and integration steps.' },
    { id: 'project.mission', label: 'Mission Engine', summary: 'Jobs, approvals, automation graph.' },
    { id: 'project.content', label: 'Content Engine', summary: 'Publishing and workflows.' },
    { id: 'project.modules', label: 'Workspace Modules', summary: 'Office/mission/content/module tabs.' },
    { id: 'project.output', label: 'Streaming Output', summary: 'Token stream and final render.' },
];
const VIBE_CODE_PROJECT_EDGES = [
    { from: 'project.frontend', to: 'project.api' },
    { from: 'project.api', to: 'project.session' },
    { from: 'project.session', to: 'project.router' },
    { from: 'project.router', to: 'project.model' },
    { from: 'project.model', to: 'project.tools' },
    { from: 'project.model', to: 'project.output' },
    { from: 'project.tools', to: 'project.mission' },
    { from: 'project.tools', to: 'project.content' },
    { from: 'project.mission', to: 'project.modules' },
    { from: 'project.content', to: 'project.modules' },
    { from: 'project.modules', to: 'project.output' },
];
const VIBE_CODE_CORE_PROJECT_MODULES = new Set([
    'project.frontend',
    'project.api',
    'project.session',
    'project.router',
    'project.model',
    'project.tools',
    'project.output',
]);
const VIBE_CODE_STATUS_ORDER = {
    pending: 0,
    active: 1,
    success: 2,
    error: 3,
};
const vibeCodeState = {
    traces: new Map(),
    activeTraceId: '',
    panel: null,
    graphEl: null,
    projectFlowEl: null,
    runtimeFlowEl: null,
    logEl: null,
    discoveryEl: null,
    metaEl: null,
    statusPillEl: null,
    bodyEl: null,
    toggleBtn: null,
    controlsEl: null,
    moduleGridEl: null,
    edgeCountEl: null,
    collapsed: false,
    discoveredNodes: new Map(),
    controls: {
        projectEnabled: true,
        runtimeEnabled: true,
        disconnectedEdges: new Set(),
        moduleEnabled: new Set(VIBE_CODE_PROJECT_NODES.map((node) => safeString(node.id)).filter(Boolean)),
    },
};

function vibeCodeNormalizeStatus(status) {
    const normalized = safeString(status).toLowerCase();
    return Object.prototype.hasOwnProperty.call(VIBE_CODE_STATUS_ORDER, normalized) ? normalized : 'pending';
}

function vibeCodeMergeStatus(leftRaw, rightRaw) {
    const left = vibeCodeNormalizeStatus(leftRaw);
    const right = vibeCodeNormalizeStatus(rightRaw);
    return (VIBE_CODE_STATUS_ORDER[right] || 0) > (VIBE_CODE_STATUS_ORDER[left] || 0) ? right : left;
}

function vibeCodeToneFromStatus(statusRaw) {
    const status = vibeCodeNormalizeStatus(statusRaw);
    if (status === 'success') return 'ok';
    if (status === 'error') return 'error';
    if (status === 'active') return 'warn';
    return '';
}

