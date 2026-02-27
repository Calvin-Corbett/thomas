// Extracted from part-007b.js
// From chatvisible

            micBtn.style.color = 'var(--text-secondary)';
            notifyUser('Unable to start microphone capture right now.', {
                tone: 'warning',
                debugKind: 'warning',
                durationMs: 2800,
            });
        }
    }
    window.__thomasStopMicCapture = ({ send = false } = {}) => {
        stopMicCapture({ send });
        suppressMicTranscript(2200);
        resetMicDraftState();
    };

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            // Stop generation first if running
            if (isGenerating) {
                stopGeneration();
                return;
            }
            composerCloseActionsMenu();
        }
        // Ctrl+Shift+N → new chat
        if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'N') {
            event.preventDefault();
            if (typeof startNewSession === 'function') startNewSession();
        }
        // Ctrl+F → in-chat search
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key === 'f') {
            // Only override Ctrl+F when chat area is visible
            const chatVisible = chatScrollArea && !chatScrollArea.classList.contains('hidden');
            if (chatVisible) {
                event.preventDefault();
                toggleChatSearch();
            }
        }
        // Ctrl+Shift+E → export conversation
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
            && (micShouldListen || micIsListening)
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
            micBtn.style.color = 'var(--danger-ink)';
        };

        recognition.onresult = (e) => {
            let interimText = '';
            for (let i = e.resultIndex; i < e.results.length; i += 1) {