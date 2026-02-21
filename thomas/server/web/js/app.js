/**
 * Thomas UI - Super Cool & Neat Edition
 * Minimal, clean, vanilla JS to power the thoughtful interface.
 */

// Basic State
let chatHistory = [];
let isGenerating = false;
let pendingDocs = [];
let pendingImages = [];
let sessionId = "";

// DOM Elements
const welcomeScreen = document.getElementById('welcomeScreen');
const chatScrollArea = document.getElementById('chatScrollArea');
const chatMessagesInner = document.getElementById('chatMessagesInner');
const composerTextarea = document.getElementById('composerTextarea');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const attachBtn = document.getElementById('attachBtn');
const attachmentsPreview = document.getElementById('attachmentsPreview');
const docFileInput = document.getElementById('docFileInput');

// New Phase 5 Elements
const sidebar = document.getElementById('sidebar');
const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
const modelSelector = document.getElementById('modelSelector');

const settingsModal = document.getElementById('settingsModal');
const settingsBtn = document.getElementById('settingsBtn');
const closeSettingsBtn = document.getElementById('closeSettingsBtn');
const saveSettingsBtn = document.getElementById('saveSettingsBtn');
const settingSystemPrompt = document.getElementById('settingSystemPrompt');
const settingTheme = document.getElementById('settingTheme');

/**
 * Initialize the ultra-premium UI behaviors
 */
function init() {
    initComposer();
    initActions();
    initFeatures();
    loadInitialState();
}

/**
 * Composer behaviors: Auto-expand, Enter-to-send
 */
function initComposer() {
    composerTextarea.addEventListener('input', () => {
        // Auto-resize
        composerTextarea.style.height = 'auto';
        composerTextarea.style.height = (composerTextarea.scrollHeight) + 'px';

        // Toggle send button state
        if (composerTextarea.value.trim().length > 0 || pendingDocs.length > 0 || pendingImages.length > 0) {
            sendBtn.disabled = false;
            sendBtn.style.color = 'var(--bg-app)';
        } else {
            sendBtn.disabled = true;
        }
    });

    composerTextarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) {
                handleSend();
            }
        }
    });
}

function initActions() {
    sendBtn.addEventListener('click', () => {
        if (isGenerating) {
            // It's a stop button right now
            stopGeneration();
        } else {
            handleSend();
        }
    });

    // Attachments
    attachBtn.addEventListener('click', () => {
        docFileInput.click();
    });

    docFileInput.addEventListener('change', async (e) => {
        for (const file of e.target.files) {
            if (file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = (re) => {
                    pendingImages.push({ data_url: re.target.result, name: file.name });
                    renderAttachmentsPreview();
                };
                reader.readAsDataURL(file);
            } else {
                const text = await file.text();
                pendingDocs.push({ name: file.name, text: text });
                renderAttachmentsPreview();
            }
        }
        docFileInput.value = ''; // reset
    });

    // Microphone
    let recognition = null;
    if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;

        recognition.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            if (transcript) {
                composerTextarea.value += (composerTextarea.value ? ' ' : '') + transcript;
                composerTextarea.dispatchEvent(new Event('input'));
            }
        };
        recognition.onend = () => {
            micBtn.style.color = 'var(--text-secondary)';
        };
        recognition.onerror = () => {
            micBtn.style.color = 'var(--text-secondary)';
        };
    }

    micBtn.addEventListener('click', () => {
        if (recognition) {
            micBtn.style.color = '#ef4444'; // Red indicates recording
            recognition.start();
        } else {
            alert("Speech recognition isn't supported in your browser.");
        }
    });

    // Suggestion chips
    document.querySelectorAll('.suggestion-chip').forEach(btn => {
        btn.addEventListener('click', (e) => {
            composerTextarea.value = e.target.innerText.trim();
            composerTextarea.dispatchEvent(new Event('input')); // trigger resize and enable button
            composerTextarea.focus();
        });
    });
}

/**
 * Execute the send flow
 */
async function handleSend() {
    const text = composerTextarea.value.trim();
    if (!text && pendingDocs.length === 0 && pendingImages.length === 0) return;

    // 1. UI Updates
    composerTextarea.value = '';
    composerTextarea.dispatchEvent(new Event('input')); // Reset size

    const docsToSend = [...pendingDocs];
    const imagesToSend = [...pendingImages];
    pendingDocs = [];
    pendingImages = [];
    renderAttachmentsPreview();

    if (welcomeScreen && !welcomeScreen.classList.contains('hidden')) {
        welcomeScreen.classList.add('hidden');
        chatScrollArea.classList.remove('hidden');
    }

    // 2. Render User Message
    let uiText = text;
    if (docsToSend.length > 0) uiText += `\n\n*(Attached ${docsToSend.length} document(s))*`;
    if (imagesToSend.length > 0) uiText += `\n\n*(Attached ${imagesToSend.length} image(s))*`;
    renderMessage({ role: 'user', content: uiText || '(Sent Attachments)' });

    // 3. Morph send button to "Thinking/Stop"
    setGeneratingState(true);

    // 4. Hit API
    try {
        const payload = {
            message: text,
            docs: docsToSend,
            images: imagesToSend,
            session_id: sessionId,
            model: modelSelector.value
        };

        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const errText = await res.text();
            throw new Error(`API Error ${res.status}: ${errText}`);
        }

        const bubbleId = 'msg-' + Date.now();
        renderMessage({ role: 'assistant', content: '', id: bubbleId });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const evt = JSON.parse(line);
                    if (evt.type === 'text' && evt.text) {
                        fullText += evt.text;
                        updateMessage(bubbleId, fullText);
                    } else if (evt.type === 'error') {
                        fullText += `\n\n**Error:** ${evt.error}`;
                        updateMessage(bubbleId, fullText);
                    }
                } catch (e) {
                    console.warn("Failed to parse stream line:", line);
                }
            }
        }

        if (buffer.trim()) {
            try {
                const evt = JSON.parse(buffer);
                if (evt.type === 'text' && evt.text) {
                    fullText += evt.text;
                    updateMessage(bubbleId, fullText);
                }
            } catch (ignore) { }
        }

        if (!fullText.trim()) {
            updateMessage(bubbleId, '_Finished with no text response._');
        }

    } catch (err) {
        console.error(err);
        let errorMsg = err.message;
        if (errorMsg.includes('SyntaxError')) {
            errorMsg = "Invalid JSON returned from server.";
        }
        renderMessage({ role: 'assistant', content: '**Error connecting to Thomas backend.**\n\n`' + errorMsg + '`' });
    } finally {
        setGeneratingState(false);
    }
}

function stopGeneration() {
    // Mock stop
    setGeneratingState(false);
}

function setGeneratingState(generating) {
    isGenerating = generating;
    if (generating) {
        sendBtn.classList.add('stop-state');
        sendBtn.innerHTML = '<i class="ph ph-stop"></i>';
        sendBtn.disabled = false;
    } else {
        sendBtn.classList.remove('stop-state');
        sendBtn.innerHTML = '<i class="ph ph-arrow-up"></i>';
        sendBtn.disabled = (composerTextarea.value.trim().length === 0 && pendingDocs.length === 0 && pendingImages.length === 0);
    }
}

function renderAttachmentsPreview() {
    attachmentsPreview.innerHTML = '';
    const all = [...pendingDocs.map(d => ({ ...d, type: 'doc' })), ...pendingImages.map(i => ({ ...i, type: 'img' }))];

    all.forEach((item, index) => {
        const chip = document.createElement('div');
        chip.className = 'attachment-chip';
        chip.innerHTML = `
            <i class="ph ${item.type === 'img' ? 'ph-image' : 'ph-file-text'}"></i>
            <span>${item.name}</span>
            <i class="ph ph-x remove-btn" data-index="${index}" data-type="${item.type}"></i>
        `;
        attachmentsPreview.appendChild(chip);
    });

    attachmentsPreview.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const type = e.target.getAttribute('data-type');
            const idx = parseInt(e.target.getAttribute('data-index'), 10);
            if (type === 'img') {
                pendingImages.splice(idx - pendingDocs.length, 1);
            } else {
                pendingDocs.splice(idx, 1);
            }
            renderAttachmentsPreview();
            composerTextarea.dispatchEvent(new Event('input')); // update button state
        });
    });
}

/**
 * Render a message bubble into the stream
 */
function renderMessage(msg) {
    const isUser = msg.role === 'user';
    const idAttr = msg.id ? `id="${msg.id}"` : '';
    const html = `
    <div class="message-row" ${idAttr}>
      <div class="avatar ${isUser ? 'user' : 'assistant'}">
        ${isUser ? 'U' : '<i class="ph ph-sparkle"></i>'}
      </div>
      <div class="message-content">
        ${formatMarkdown(msg.content)}
      </div>
    </div>
  `;

    // Insert into DOM
    chatMessagesInner.insertAdjacentHTML('beforeend', html);

    // Scroll to bottom
    chatScrollArea.scrollTo({ top: chatScrollArea.scrollHeight, behavior: 'smooth' });

    // Apply highlighting to new code blocks
    chatMessagesInner.lastElementChild.querySelectorAll('pre code').forEach((el) => {
        hljs.highlightElement(el);
    });
}

function updateMessage(id, newContent) {
    const row = document.getElementById(id);
    if (!row) return;
    const contentDiv = row.querySelector('.message-content');
    if (contentDiv) {
        contentDiv.innerHTML = formatMarkdown(newContent);
        contentDiv.querySelectorAll('pre code').forEach((el) => {
            hljs.highlightElement(el);
        });
        chatScrollArea.scrollTo({ top: chatScrollArea.scrollHeight, behavior: 'smooth' });
    }
}

/**
 * Configure Marked.js to wrap code blocks in our Custom "Mac Style" window
 */
function formatMarkdown(text) {
    const renderer = new marked.Renderer();
    renderer.code = function (code, language) {
        const validLang = !!(language && hljs.getLanguage(language));
        const highlighted = validLang ? hljs.highlight(code, { language }).value : escapeHtml(code);

        return `
      <pre><code class="hljs ${language}">${highlighted}</code></pre>
    `;
    };

    marked.setOptions({ renderer });
    return marked.parse(text);
}

function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

async function loadInitialState() {
    try {
        const res = await fetch('/api/session/new', { method: 'POST' });
        const data = await res.json();
        if (data.session_id) {
            sessionId = data.session_id;
        }
    } catch (e) {
        console.error("Failed to boot session:", e);
    }
    await fetchModels();
}

async function fetchModels() {
    try {
        const res = await fetch('/api/models');
        if (res.ok) {
            const data = await res.json();
            modelSelector.innerHTML = '';
            for (const m of data.profiles || []) {
                const opt = document.createElement('option');
                opt.value = m.name;
                opt.textContent = m.name;
                // Pre-select if it matches default
                if (data.default === m.name) {
                    opt.selected = true;
                }
                modelSelector.appendChild(opt);
            }
        }
    } catch (e) { console.error("Failed to fetch models", e); }
}

function initFeatures() {
    sidebarToggleBtn.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
    });

    settingsBtn.addEventListener('click', () => {
        settingsModal.classList.remove('hidden');
        loadSettings();
    });

    closeSettingsBtn.addEventListener('click', () => {
        settingsModal.classList.add('hidden');
    });

    saveSettingsBtn.addEventListener('click', saveSettings);
}

async function loadSettings() {
    try {
        const res = await fetch('/api/preferences');
        if (res.ok) {
            const data = await res.json();
            settingSystemPrompt.value = data.system_prompt || '';
            settingTheme.value = data.theme || 'system';
        }
    } catch (e) { console.error("Failed to load settings", e); }
}

async function saveSettings() {
    try {
        saveSettingsBtn.textContent = 'Saving...';
        await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                system_prompt: settingSystemPrompt.value,
                theme: settingTheme.value
            })
        });
        saveSettingsBtn.textContent = 'Saved!';
        setTimeout(() => {
            saveSettingsBtn.textContent = 'Save Preferences';
            settingsModal.classList.add('hidden');
        }, 1000);
    } catch (e) { console.error("Failed to save settings", e); saveSettingsBtn.textContent = 'Error'; }
}

// Boot
window.addEventListener('DOMContentLoaded', init);
