// Extracted from part-004b.js
// From init


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
    if (!(chatMessagesInner instanceof HTMLElement) || !(composerContainer instanceof HTMLElement)) return;
    const rect = composerContainer.getBoundingClientRect();
    const offset = Math.max(200, Math.ceil(rect.height) + 34);
    chatMessagesInner.style.setProperty('--composer-offset', `${offset}px`);
}

/**
 * Composer behaviors: Auto-expand, Enter-to-send
 */
function composerSyncSendButtonState() {
    if (isGenerating) return;
    const canSend = composerTextarea.value.trim().length > 0 || pendingDocs.length > 0 || pendingImages.length > 0;
    sendBtn.disabled = !canSend;
    sendBtn.style.color = canSend ? 'var(--text-primary)' : '';
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

    // â”€â”€ Paste images from clipboard â”€â”€
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

    // â”€â”€ Drag-and-drop files onto composer â”€â”€
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

// â”€â”€ Slash Command Palette â”€â”€
const SLASH_COMMANDS = [
    { cmd: '/research',  desc: 'Deep research mode â€” thorough web search + synthesis' },
    { cmd: '/image',     desc: 'Generate an image from a description' },
    { cmd: '/code',      desc: 'Code-focused mode â€” programming assistance' },
    { cmd: '/write',     desc: 'Writing mode â€” essays, emails, creative text' },
    { cmd: '/analyze',   desc: 'Analyze documents, data, or complex topics' },
    { cmd: '/status',    desc: 'Show live engine status and runtime details' },
    { cmd: '/issues',    desc: 'Run code issue detection and automated fixes' },
    { cmd: '/upgrade',   desc: 'Run self-upgrade engine cycle' },
    { cmd: '/sync',      desc: 'Run workspace sync cycle (commit / housekeeping)' },
    { cmd: '/ui-audit',  desc: 'Run UI workflow review and polish checks' },
    { cmd: '/clear',     desc: 'Clear the conversation and start fresh' },
    { cmd: '/export',    desc: 'Export this conversation as markdown or JSON' },
    { cmd: '/help',      desc: 'Show available commands and keyboard shortcuts' },