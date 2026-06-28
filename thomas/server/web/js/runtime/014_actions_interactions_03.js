function _clearSearchHighlights() {
    if (!chatMessagesInner) return;
    chatMessagesInner.querySelectorAll('.search-highlight').forEach(r => r.classList.remove('search-highlight'));
}

function _updateSearchCount() {
    const countEl = document.querySelector('#chatSearchBar .search-count');
    if (!countEl) return;
    if (_chatSearchState.matches.length === 0) {
        countEl.textContent = _chatSearchState.query ? 'No matches' : '';
    } else {
        countEl.textContent = `${_chatSearchState.current + 1} / ${_chatSearchState.matches.length}`;
    }
}

/**
 * Toggle pin on a message.
 */
function togglePinMessage(row) {
    if (!row) return;
    const msgId = row.id;
    const entry = chatHistory.find(m => m.id === msgId);
    const isPinned = row.classList.toggle('pinned');
    if (entry) entry.pinned = isPinned;
    void persistActiveChat({ quiet: true });
    showToast(isPinned ? 'Message pinned' : 'Message unpinned');
}

function initChatSearch() {
    const searchInput = document.getElementById('chatSearchInput');
    const prevBtn = document.getElementById('chatSearchPrev');
    const nextBtn = document.getElementById('chatSearchNext');
    const closeBtn = document.getElementById('chatSearchClose');
    if (!searchInput) return;

    let _debounce = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(_debounce);
        _debounce = setTimeout(() => _performChatSearch(searchInput.value), 200);
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); _navigateSearch(e.shiftKey ? -1 : 1); }
        if (e.key === 'Escape') { e.preventDefault(); toggleChatSearch(); }
    });
    if (prevBtn) prevBtn.addEventListener('click', () => _navigateSearch(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => _navigateSearch(1));
    if (closeBtn) closeBtn.addEventListener('click', () => toggleChatSearch());
}

function stopGeneration() {
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
    setGeneratingState(false);
}

function _getSendIconClass() {
    /* Return theme-appropriate send icon */
    return document.body.classList.contains('te-theme-light') ? 'ph-pen-nib' : 'ph-arrow-up';
}

function setGeneratingState(generating) {
    isGenerating = generating;
    if (generating) {
        sendBtn.classList.add('stop-state');
        sendBtn.innerHTML = '<i class="ph ph-stop"></i>';
        sendBtn.disabled = false;
        _stopSuggestionAutoScroll();
    } else {
        sendBtn.classList.remove('stop-state');
        sendBtn.innerHTML = '<i class="ph ' + _getSendIconClass() + '"></i>';
        sendBtn.disabled = (composerTextarea.value.trim().length === 0 && pendingDocs.length === 0 && pendingImages.length === 0);
    }
    syncSendButtonA11y();
    updateDebugDockSnapshot();
}

// 
//   CHAT & MESSAGE RENDERING                                               
//   Attachments, message bubbles, markdown, code blocks, robot alerts      
// 

function renderAttachmentsPreview() {
    attachmentsPreview.replaceChildren();
    const all = [...pendingDocs.map(d => ({ ...d, type: 'doc' })), ...pendingImages.map(i => ({ ...i, type: 'img' }))];

    all.forEach((item, index) => {
        const chip = document.createElement('div');
        chip.className = 'attachment-chip';

        const imgSrc = String(item.data_url || '');
        if (item.type === 'img' && imgSrc.startsWith('data:image/')) {
            const thumb = document.createElement('img');
            thumb.className = 'attachment-chip-thumb';
            thumb.src = imgSrc;
            thumb.alt = String(item.name || 'image');
            chip.appendChild(thumb);
        } else {
            const icon = document.createElement('i');
            const isPdf = /\.pdf$/i.test(String(item.name || ''));
            icon.className = `ph ${item.type === 'img' ? 'ph-image' : (isPdf ? 'ph-file-pdf' : 'ph-file-text')}`;
            chip.appendChild(icon);
        }

        const label = document.createElement('span');
        label.textContent = String(item.name || '');

        const remove = document.createElement('i');
        remove.className = 'ph ph-x remove-btn';
        remove.dataset.index = String(index);
        remove.dataset.type = item.type;

        chip.appendChild(label);
        chip.appendChild(remove);
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
    syncChatComposerOffset();
}

/*  Toast helper  */
function showToast(msg, durationMs = 2000) {
    if (!toastContainer) return;
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    toastContainer.appendChild(t);
    setTimeout(() => t.remove(), durationMs + 300);
}

/*  Code-block header injection (DOM walk, avoids sanitizer)  */
function addCodeBlockControls(container) {
    container.querySelectorAll('pre > code').forEach(codeEl => {
        const pre = codeEl.parentElement;
        if (pre.parentElement && pre.parentElement.classList.contains('code-block-wrapper')) return;
        // Detect language from class: could be "language-python", "python", or just "hljs"
        const classes = [...codeEl.classList].filter(c => c !== 'hljs');
        let lang = 'text';
        for (const c of classes) {
            if (c.startsWith('language-')) { lang = c.replace('language-', ''); break; }
            if (c && c !== 'undefined' && c !== 'null') { lang = c; break; }
        }
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        const header = document.createElement('div');
        header.className = 'code-block-header';
        header.innerHTML = `<span class="code-block-lang">${escapeHtml(lang)}</span><button class="code-block-copy" title="Copy code"><i class="ph ph-copy"></i> Copy</button>`;
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });
}

/**
 * Build the attachment visuals (image thumbnails + document badges) for a
 * message. Returns null when there are no attachments. Nodes are created
 * directly here (not via the markdown sanitizer); the data URLs come from the
 * user's own picked files, so they are trusted local content.
 */
function buildMessageAttachments(msg) {
    const images = Array.isArray(msg && msg.images) ? msg.images : [];
    const docs = Array.isArray(msg && msg.docs) ? msg.docs : [];
    if (images.length === 0 && docs.length === 0) return null;

    const wrap = document.createElement('div');
    wrap.className = 'message-attachments';

    images.forEach((img) => {
        const src = safeString(img && img.data_url);
        if (!src.startsWith('data:image/')) return;
        const name = safeString(img && img.name) || 'image';
        const tile = document.createElement('button');
        tile.type = 'button';
        tile.className = 'message-attachment-thumb';
        tile.title = name;
        const el = document.createElement('img');
        el.src = src;
        el.alt = name;
        el.loading = 'lazy';
        tile.appendChild(el);
        tile.addEventListener('click', () => openAttachmentLightbox(src, name));
        wrap.appendChild(tile);
    });

    docs.forEach((doc) => {
        const name = safeString(doc && doc.name) || 'document';
        const isPdf = /\.pdf$/i.test(name);
        const badge = document.createElement('div');
        badge.className = 'message-attachment-doc';
        const icon = document.createElement('i');
        icon.className = `ph ${isPdf ? 'ph-file-pdf' : 'ph-file-text'}`;
        const label = document.createElement('span');
        label.textContent = name;
        badge.appendChild(icon);
        badge.appendChild(label);
        wrap.appendChild(badge);
    });

    return wrap;
}

/**
 * Full-screen preview of an attached image. Click anywhere (or press Esc) to close.
 */
function openAttachmentLightbox(src, name) {
    const existing = document.getElementById('attachmentLightbox');
    if (existing) existing.remove();
    const overlay = document.createElement('div');
    overlay.id = 'attachmentLightbox';
    overlay.className = 'attachment-lightbox';
    const img = document.createElement('img');
    img.src = src;
    img.alt = safeString(name) || 'attachment';
    overlay.appendChild(img);
    const close = () => overlay.remove();
    overlay.addEventListener('click', close);
    const onKey = (e) => {
        if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); }
    };
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
}

/**
 * Render a message bubble into the stream
 */
function renderMessage(msg) {
    const isUser = msg.role === 'user';
    const createdAt = Number(msg?.createdAt) || Date.now();
    const row = document.createElement('div');
    row.className = `message-row ${isUser ? 'is-user' : 'is-assistant'}`;
    if (msg.id) {
        row.id = String(msg.id);
    }
    row.dataset.messageTimestamp = String(createdAt);
    row.title = chatMessageTimestampText(createdAt);

    const profileMeta = resolveActiveChatProfileMeta();

    const stack = document.createElement('div');
    stack.className = 'message-stack';

    if (!isUser) {
        const avatar = document.createElement('div');
        avatar.className = 'avatar assistant';
        renderAssistantAvatarVisual(avatar, profileMeta);

        const meta = document.createElement('div');
        meta.className = 'message-meta';

        const author = document.createElement('span');
        author.className = 'message-author';
        author.textContent = resolveAgentName(currentPreferences);
        meta.appendChild(author);

        const provider = document.createElement('span');
        provider.className = 'message-provider';

        if (safeString(profileMeta.modelLabel)) {
            const separator = document.createElement('span');
            separator.className = 'message-provider-separator';
            separator.setAttribute('aria-hidden', 'true');
            provider.appendChild(separator);

            const modelLabel = document.createElement('span');
            modelLabel.className = 'message-model-label';
            modelLabel.textContent = safeString(profileMeta.modelLabel);
            provider.appendChild(modelLabel);
        }

        provider.title = safeString(profileMeta.modelLabel) || resolveAgentName(currentPreferences);
        meta.appendChild(provider);
        row.appendChild(avatar);
        stack.appendChild(meta);
    }

    const content = document.createElement('div');
    content.className = isUser ? 'message-content user-bubble' : 'message-content assistant-bubble';
    content.innerHTML = formatMarkdown(msg.content);
    content.setAttribute('data-message-timestamp', chatMessageTimestampText(createdAt));

    stack.appendChild(content);

    const attachmentsEl = buildMessageAttachments(msg);
    if (attachmentsEl) {
        stack.appendChild(attachmentsEl);
    }

    const footer = document.createElement('div');
    footer.className = 'message-footer';

    const timestamp = document.createElement('span');
    timestamp.className = 'message-timestamp';
    timestamp.textContent = chatMessageTimestampText(createdAt);
    timestamp.setAttribute('aria-label', `Sent ${timestamp.textContent}`);

    const actions = document.createElement('div');
    actions.className = 'message-actions';
    if (isUser) {
        actions.innerHTML = [
            '<button class="msg-action-btn" data-action="edit" title="Edit message"><i class="ph ph-pencil-simple"></i></button>',
            '<button class="msg-action-btn" data-action="copy" title="Copy message"><i class="ph ph-copy"></i></button>',
            '<button class="msg-action-btn" data-action="pin" title="Pin message"><i class="ph ph-push-pin"></i></button>',
        ].join('');
    } else {
        actions.innerHTML = [
            '<button class="msg-action-btn" data-action="copy" title="Copy message"><i class="ph ph-copy"></i></button>',
            '<button class="msg-action-btn" data-action="regenerate" title="Regenerate response"><i class="ph ph-arrows-clockwise"></i></button>',
            '<button class="msg-action-btn" data-action="pin" title="Pin message"><i class="ph ph-push-pin"></i></button>',
        ].join('');
    }
    footer.appendChild(timestamp);
    footer.appendChild(actions);
    stack.appendChild(footer);
    row.appendChild(stack);

    chatMessagesInner.appendChild(row);

    // Scroll to bottom
    chatScrollArea.scrollTo({ top: chatScrollArea.scrollHeight, behavior: 'smooth' });

    // Apply highlighting to new code blocks, then add header controls
    chatMessagesInner.lastElementChild.querySelectorAll('pre code').forEach((el) => {
        try { hljs.highlightElement(el); } catch (_e) { /* ignore unknown lang */ }
    });
    addCodeBlockControls(content);
    updateDebugDockSnapshot();
}

function updateMessage(id, newContent, isStreaming = true) {
    const row = document.getElementById(id);
    if (!row) return;
    const contentDiv = row.querySelector('.message-content');
    if (contentDiv) {
        // Preserve thinking summary if present (lives above markdown, includes tool cards)
        const thinkingSummary = contentDiv.querySelector('.thinking-summary');
        if (thinkingSummary) thinkingSummary.remove(); // detach temporarily

        contentDiv.innerHTML = formatMarkdown(newContent);
        contentDiv.querySelectorAll('pre code').forEach((el) => {
            try { hljs.highlightElement(el); } catch (_e) { /* ignore unknown lang */ }
        });
        addCodeBlockControls(contentDiv);

        // Re-attach thinking summary at top
        if (thinkingSummary) contentDiv.insertBefore(thinkingSummary, contentDiv.firstChild);

        contentDiv.classList.remove('streaming-cursor');
        chatScrollArea.scrollTo({ top: chatScrollArea.scrollHeight, behavior: 'smooth' });
        updateDebugDockSnapshot();
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
        const langClass = validLang ? language : '';
        return `<pre><code class="hljs${langClass ? ' ' + langClass : ''}">${highlighted}</code></pre>`;
    };
    renderer.html = function (rawHtml) {
        // Raw HTML in user/assistant messages is treated as text to block XSS.
        return escapeHtml(rawHtml || '');
    };

    marked.setOptions({ renderer });
    const rendered = marked.parse(String(text || ''));
    return sanitizeRenderedHtml(rendered);
}

function sanitizeRenderedHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = String(html || '');

    const blockedTags = new Set([
        'SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE',
        'FORM', 'INPUT', 'BUTTON', 'TEXTAREA', 'SELECT', 'OPTION'
    ]);
    const urlAttrs = new Set(['href', 'src', 'xlink:href']);
    const allowDataImage = new Set(['IMG']);
    const elements = template.content.querySelectorAll('*');
    for (const el of elements) {
        const tag = String(el.tagName || '').toUpperCase();
        if (blockedTags.has(tag)) {
            el.remove();
            continue;
        }
        for (const attr of [...el.attributes]) {
            const name = String(attr.name || '').toLowerCase();
            const value = String(attr.value || '');
            if (name.startsWith('on') || name === 'style' || name === 'srcdoc') {
                el.removeAttribute(attr.name);
                continue;
            }
            if (urlAttrs.has(name)) {
                const safe = sanitizeUrl(value, allowDataImage.has(tag));
                if (safe === null) {
                    el.removeAttribute(attr.name);
                } else {
                    el.setAttribute(attr.name, safe);
                }
            }
        }
        if (tag === 'A') {
            el.setAttribute('rel', 'noopener noreferrer nofollow');
            if (!el.getAttribute('target')) {
                el.setAttribute('target', '_blank');
            }
        }
    }
    return template.innerHTML;
}

function sanitizeUrl(raw, allowDataImage = false) {
    const value = String(raw || '').trim();
    if (!value) return null;
    if (value.startsWith('#') || value.startsWith('/')) return value;
    try {
        const parsed = new URL(value, window.location.origin);
        const protocol = String(parsed.protocol || '').toLowerCase();
        if (protocol === 'http:' || protocol === 'https:' || protocol === 'mailto:' || protocol === 'tel:') {
            return parsed.href;
        }
        if (allowDataImage && protocol === 'data:' && /^data:image\//i.test(value)) {
            return value;
        }
    } catch (e) {
        return null;
    }
    return null;
}

function escapeHtml(unsafe) {
    return String(unsafe || '')
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function safeString(value) {
    return String(value || '').trim();
}

function streamChunkString(value) {
    return value === undefined || value === null ? '' : String(value);
}

function normalizeReasoningEffort(valueRaw) {
    const value = safeString(valueRaw).toLowerCase();
    if (!value) return '';
    // Older settings builds mislabeled the xHigh tier as "max".
    if (value === 'max') return 'xhigh';
    return new Set(['low', 'medium', 'high', 'xhigh']).has(value) ? value : '';
}

function defaultModelIdForProfile(profileName = '') {
    const targetProfile = safeString(profileName);
    if (!targetProfile) return '';
    const profile = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name) === targetProfile)
        : null;
    return safeString(profile?.model).split('/').pop();
}

function getPersistedReasoningEffort(profileName = '') {
    const savedProfile = safeString(currentPreferences?.advanced?.model?.active_profile)
        || safeString(window.localStorage.getItem('thomas_active_profile'));
    const targetProfile = safeString(profileName);
    if (targetProfile && savedProfile && targetProfile !== savedProfile) {
        return '';
    }
    return normalizeReasoningEffort(currentPreferences?.advanced?.model?.reasoning_effort);
}

function resolveStoredModelSelection(profileName = '', { allowLocalBackup = false } = {}) {
    const targetProfile = safeString(profileName);
    if (!targetProfile) return '';
    const prefProfile = safeString(currentPreferences?.advanced?.model?.active_profile);
    const prefModelId = safeString(currentPreferences?.advanced?.model?.model_id);
    if (prefProfile === targetProfile && prefModelId) return prefModelId;
    if (!prefProfile && allowLocalBackup) {
        const savedProfile = safeString(window.localStorage.getItem('thomas_active_profile'));
        const savedModelId = safeString(window.localStorage.getItem('thomas_active_model_id'));
        if (savedProfile === targetProfile && savedModelId) return savedModelId;
    }
    return defaultModelIdForProfile(targetProfile);
}

function resolveProfileReasoningEffort(profileName = '') {
    const targetProfile = safeString(profileName);
    if (!targetProfile) return '';
    const profile = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name) === targetProfile)
        : null;
    const reasoningControl = profile?.chat_controls?.model?.reasoning_effort;
    const persistedEffort = getPersistedReasoningEffort(targetProfile);
    const provider = safeString(profile?.provider).toLowerCase();
    const defaultEffort = normalizeReasoningEffort(
        reasoningControl?.default_value
        || profile?.reasoning_effort
        || (provider === 'codex' || provider === 'openai_codex' || provider === 'openai-codex' ? 'medium' : '')
    );
    if (!reasoningControl?.supported && !defaultEffort && !persistedEffort) return '';
    if (persistedEffort) return persistedEffort;
    if (defaultEffort) return defaultEffort;
    return '';
}

function resolveActiveModelIdForProfile(profileName = '') {
    const targetProfile = safeString(profileName);
    if (!targetProfile) return safeString(activeModelOverride);
    const activeProfile = activeProfileNameForPersistence();
    if (activeProfile && activeProfile === targetProfile && safeString(activeModelOverride)) {
        return safeString(activeModelOverride);
    }
    return resolveStoredModelSelection(targetProfile, {
        allowLocalBackup: !safeString(currentPreferences?.advanced?.model?.active_profile),
    });
}

function findSetupProviderProfile(profileName = '') {
    const targetProfile = safeString(profileName);
    if (!targetProfile || !Array.isArray(availableModelProfiles)) return null;
    return availableModelProfiles.find((entry) => safeString(entry?.name) === targetProfile) || null;
}

function isKeylessLocalProfile(profile) {
    // Local/Ollama providers need no API key — they are "connected" when the
    // local runtime is reachable, not when a key is present. Without this they
    // are classified inactive, so picking a local model in Model Setup always
    // bounces through the full onboarding wizard instead of just switching.
    const provider = safeString(profile?.provider).toLowerCase();
    const name = safeString(profile?.name).toLowerCase();
    const baseUrl = safeString(profile?.base_url).toLowerCase();
    if (provider === 'local' || provider === 'ollama' || name === 'local' || name.includes('ollama')) return true;
    return baseUrl.includes('11434') || baseUrl.includes('//localhost') || baseUrl.includes('//127.0.0.1');
}

function isSetupProviderProfileActive(profile) {
    return Boolean(profile?.has_api_key) || isKeylessLocalProfile(profile);
}

function classifySetupProviderProfiles() {
    const profiles = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.filter((profile) => {
            const name = safeString(profile?.name);
            // Drop the legacy "codex" profile from the picker entirely — the
            // ChatGPT OAuth path lives on the "openai_codex" profile.
            return Boolean(name) && name.toLowerCase() !== 'codex';
        })
        : [];
    return {
        active: profiles.filter((profile) => isSetupProviderProfileActive(profile)),
        inactive: profiles.filter((profile) => !isSetupProviderProfileActive(profile)),
    };
}

function updateSetupProviderPickerButton(profileName = '') {
    if (!setupProviderPickerBtn || !setupProviderPickerLabel) return;
    const selectedProfile = safeString(profileName) || safeString(setupProviderSelector?.value);
    const profile = findSetupProviderProfile(selectedProfile);
    const isConnected = isSetupProviderProfileActive(profile);
    setupProviderPickerLabel.textContent = selectedProfile
        ? formatProviderDisplay(selectedProfile)
        : 'Select provider';
    setupProviderPickerBtn.dataset.state = isConnected ? 'connected' : (profile ? 'inactive' : 'idle');
    if (setupProviderPickerState) setupProviderPickerState.textContent = '';
}

function createSetupProviderMenuLabel(text, className = 'setup-provider-section-label') {
    const label = document.createElement('div');
    label.className = className;
    label.textContent = text;
    return label;
}

function createSetupProviderOptionButton(profile, selectedProfile = '') {
    const profileName = safeString(profile?.name);
    const isConnected = isSetupProviderProfileActive(profile);
    const isSelected = profileName === safeString(selectedProfile);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'setup-provider-option';
    if (isSelected) button.classList.add('is-selected');
    button.dataset.profile = profileName;
    button.dataset.state = isConnected ? 'connected' : 'inactive';
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', isSelected ? 'true' : 'false');

    const name = document.createElement('span');
    name.className = 'setup-provider-option-name';
    name.textContent = formatProviderDisplay(profileName) || profileName;

    button.append(name);
    return button;
}

function resolveEasySetupPathForProfile(profileName = '') {
    const profile = findSetupProviderProfile(profileName);
    const provider = safeString(profile?.provider).toLowerCase();
    const profileKey = safeString(profile?.name).toLowerCase();
    if (provider === 'codex' || provider === 'openai_codex' || provider === 'openai-codex' || profileKey === 'codex' || profileKey === 'chatgpt') return 'codex';
    if (provider === 'local' || provider === 'ollama' || profileKey === 'local' || profileKey.includes('ollama')) return 'local';
    return 'manual';
}

function primeEasySetupProfileSelection(profileName = '', path = '') {
    const selectedProfile = safeString(profileName);
    if (!selectedProfile) return;
    const targetSelect = path === 'manual'
        ? easySetupManualProfile
        : (path === 'local' ? easySetupLocalProfile : null);
    if (!targetSelect) return;
    const hasMatch = Array.from(targetSelect.options || []).some((option) => safeString(option.value) === selectedProfile);
    if (hasMatch) {
        targetSelect.value = selectedProfile;
    }
}

async function handoffInactiveProviderToEasySetup(profileName = '') {
    const selectedProfile = safeString(profileName);
    if (!selectedProfile) return;
    const path = resolveEasySetupPathForProfile(selectedProfile);
    closeSetupProviderMenu();
    if (modelSetupModal) {
        modelSetupModal.classList.remove('active');
        modelSetupModal.style.display = 'none';
    }
    await openEasySetup({ source: 'model_setup_provider', force: true, restart: true });
    handleEasySetupPathSelect(path);
    primeEasySetupProfileSelection(selectedProfile, path);
    if (easySetupConnectionStatus) {
        const statusMessage = path === 'codex'
            ? 'ChatGPT (OpenAI) selected. Run connection test.'
            : `Selected ${formatProviderDisplay(selectedProfile) || selectedProfile}. Run connection test.`;
        setEasySetupStatus(easySetupConnectionStatus, statusMessage);
    }
}

function renderSetupProviderPickerMenu(profileName = '', { preserveExpanded = true } = {}) {
    if (!setupProviderMenu) return;
    const selectedProfile = safeString(profileName) || safeString(setupProviderSelector?.value);
    updateSetupProviderPickerButton(selectedProfile);
    const { active, inactive } = classifySetupProviderProfiles();
    const selectedIsInactive = inactive.some((profile) => safeString(profile?.name) === selectedProfile);
    const showInactive = !active.length || selectedIsInactive || (preserveExpanded && setupProviderMenuShowMore);
    setupProviderMenuShowMore = showInactive;
    setupProviderMenu.replaceChildren();

    if (!active.length && !inactive.length) {
        setupProviderMenu.appendChild(createSetupProviderMenuLabel('No providers available.', 'setup-provider-empty'));
        return;
    }

    for (const profile of active) {
        setupProviderMenu.appendChild(createSetupProviderOptionButton(profile, selectedProfile));
    }

    if (!inactive.length) return;

    if (!showInactive) {
        const moreButton = document.createElement('button');
        moreButton.type = 'button';
        moreButton.className = 'setup-provider-more';
        moreButton.dataset.action = 'show-more';
        moreButton.textContent = `Show ${inactive.length} more provider${inactive.length === 1 ? '' : 's'}`;
        setupProviderMenu.appendChild(moreButton);
        return;
    }

    setupProviderMenu.appendChild(createSetupProviderMenuLabel('Uninstalled', 'setup-provider-divider'));
    for (const profile of inactive) {
        setupProviderMenu.appendChild(createSetupProviderOptionButton(profile, selectedProfile));
    }
}

function openSetupProviderMenu() {
    if (!setupProviderMenu || !setupProviderPickerBtn) return;
    renderSetupProviderPickerMenu(safeString(setupProviderSelector?.value), { preserveExpanded: true });
    setupProviderMenu.classList.remove('hidden');
    setupProviderPickerBtn.setAttribute('aria-expanded', 'true');
}

function closeSetupProviderMenu({ preserveExpanded = false } = {}) {
    if (!preserveExpanded) setupProviderMenuShowMore = false;
    if (setupProviderMenu) setupProviderMenu.classList.add('hidden');
    if (setupProviderPickerBtn) setupProviderPickerBtn.setAttribute('aria-expanded', 'false');
}

function sleepMs(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, Math.max(0, Number(ms) || 0));
    });
}

function normalizeNotificationMessage(message) {
    return safeString(message).replace(/\s+/g, ' ');
}

function robotAlertVariantFromTone(tone = 'info') {
    const normalized = safeString(tone).toLowerCase();
    if (normalized === 'success' || normalized === 'ok') return 'variant-mint';
    if (normalized === 'error' || normalized === 'danger') return 'variant-pink';
    if (normalized === 'warning' || normalized === 'warn') return 'variant-orange';
    return 'variant-blue';
}

function queueRobotAlert(message, { tone = 'info', durationMs = 0, dedupeMs = 3500 } = {}) {
    if (!robotAlertStage || !robotAlertBot || !robotAlertBubble) return false;
    const normalized = normalizeNotificationMessage(message);
    if (!normalized) return false;

    const now = Date.now();
    if (normalized === robotAlertLastMessage && now - robotAlertLastAt < dedupeMs) {
        return false;
    }

    robotAlertLastMessage = normalized;
    robotAlertLastAt = now;
    robotAlertQueue.push({
        message: normalized,
        tone: safeString(tone).toLowerCase() || 'info',
        durationMs: Number(durationMs) || 0,
    });
    if (robotAlertQueue.length > 8) {
        robotAlertQueue = robotAlertQueue.slice(robotAlertQueue.length - 8);
    }

    if (!robotAlertShowing) {
        void processRobotAlertQueue();
    }
    return true;
}

function _randomSpawnPoint() {
    /* Pick a random origin point in the viewport — biased toward edges
       and upper areas so the robot feels like it's flying in from deep space. */
    const zones = [
        /* top-right quadrant */  { xMin: 60, xMax: 95, yMin: 2, yMax: 20 },
        /* top-center */          { xMin: 30, xMax: 70, yMin: 1, yMax: 10 },
        /* right edge mid */      { xMin: 85, xMax: 98, yMin: 20, yMax: 50 },
        /* bottom-right corner */ { xMin: 70, xMax: 95, yMin: 60, yMax: 85 },
        /* top-left far */        { xMin: 5, xMax: 30, yMin: 1, yMax: 15 },
    ];
    const z = zones[Math.floor(Math.random() * zones.length)];
    const x = z.xMin + Math.random() * (z.xMax - z.xMin);
    const y = z.yMin + Math.random() * (z.yMax - z.yMin);
    return { x: x + 'vw', y: y + 'vh' };
}

async function processRobotAlertQueue() {
    if (robotAlertShowing) return;
    if (!robotAlertStage || !robotAlertBot || !robotAlertBubble) return;
    robotAlertShowing = true;

    const variantClasses = ['variant-blue', 'variant-mint', 'variant-pink', 'variant-orange'];
    const phaseClasses = ['flying-in', 'landed', 'flying-out'];

    try {
        while (robotAlertQueue.length) {
            const next = robotAlertQueue.shift();
            if (!next) continue;

            const tone = safeString(next.tone).toLowerCase() || 'info';
            const variant = robotAlertVariantFromTone(tone);
            robotAlertBot.classList.remove(...variantClasses, ...phaseClasses);
            robotAlertBot.classList.add(variant);
            robotAlertBubble.classList.remove('visible');
            robotAlertBubble.textContent = next.message;

            /* Randomise where the robot spawns from */
            const spawn = _randomSpawnPoint();
            robotAlertBot.style.setProperty('--spawn-x', spawn.x);
            robotAlertBot.style.setProperty('--spawn-y', spawn.y);
            /* Vary the trail angle based on spawn position */
            const trailDeg = (parseFloat(spawn.x) > 50 ? -25 : 20) + (Math.random() * 10 - 5);
            robotAlertBot.style.setProperty('--trail-angle', trailDeg + 'deg');

            /* Show the stage (space theme hides it when not .active) */
            robotAlertStage.classList.add('active');

            /* Phase 1 — fly in from space */
            robotAlertBot.classList.add('flying-in');
            await sleepMs(1100);

            /* Phase 2 — land, show bubble */
            robotAlertBot.classList.remove('flying-in');
            robotAlertBot.classList.add('landed');
            await sleepMs(200);
            robotAlertBubble.classList.add('visible');

            const readingMs = Math.max(1900, Math.min(5600, 900 + (next.message.length * 28)));
            const holdMs = next.durationMs > 0 ? Math.max(900, next.durationMs) : readingMs;
            await sleepMs(holdMs);

            /* Phase 3 — dismiss bubble, fly out */
            robotAlertBubble.classList.remove('visible');
            await sleepMs(220);
            robotAlertBot.classList.remove('landed');
            robotAlertBot.classList.add('flying-out');
            await sleepMs(800);

            /* Clean up */
            robotAlertBot.classList.remove(...phaseClasses);
            robotAlertStage.classList.remove('active');
            await sleepMs(100);
        }
    } finally {
        robotAlertShowing = false;
    }
}

/* ── Toast notification for non-chat pages ── */
function _ensureToastContainer() {
    let el = document.getElementById('thomasToastBar');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'thomasToastBar';
    el.className = 'thomas-toast-bar';
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
    return el;
}

function _showToast(message, tone) {
    const bar = _ensureToastContainer();
    const toast = document.createElement('div');
    toast.className = 'thomas-toast thomas-toast--' + (tone || 'info');
    toast.textContent = message;
    bar.appendChild(toast);
    /* trigger entry */
    requestAnimationFrame(() => { toast.classList.add('visible'); });
    const readMs = Math.max(2200, Math.min(5000, 900 + (message.length * 26)));
    setTimeout(() => {
        toast.classList.remove('visible');
        toast.classList.add('exiting');
        setTimeout(() => { toast.remove(); }, 340);
    }, readMs);
}

function _isOnMainChatPage() {
    return typeof sidebarNavMode === 'string' && (sidebarNavMode === 'chat' || sidebarNavMode === 'search');
}

function notifyUser(message, { tone = 'info', durationMs = 0, dedupeMs = 3500, debugKind = '' } = {}) {
    const normalized = normalizeNotificationMessage(message);
    if (!normalized) return;
    if (_isOnMainChatPage()) {
        queueRobotAlert(normalized, { tone, durationMs, dedupeMs });
    } else {
        _showToast(normalized, tone);
    }
    if (safeString(debugKind)) {
        pushDebugEvent(debugKind, normalized);
    }
}

function initialsFromName(nameOrEmail) {
    const text = safeString(nameOrEmail);
    if (!text) return 'U';
    const words = text.replace(/@.*/, '').split(/[.\s_-]+/).filter(Boolean);
    if (words.length === 0) return 'U';
    const first = words[0][0] || '';
    const second = words.length > 1 ? words[1][0] : '';
    return (first + second).toUpperCase() || 'U';
}

function setAvatarVisual(el, { text = 'U', imageUrl = '' } = {}) {
    if (!el) return;
    if (safeString(imageUrl)) {
        el.style.backgroundImage = `url("${imageUrl}")`;
        el.textContent = '';
    } else {
        el.style.backgroundImage = '';
        el.textContent = text;
    }
}

function resolveDisplayName(preferences, codexStatus) {
    const prefName = safeString(preferences?.profile?.display_name);
    if (prefName) return prefName;
    const codexName = safeString(codexStatus?.display_name);
    if (codexName) return codexName;
    const email = safeString(codexStatus?.email);
    return email || 'User';
}

function sanitizeAgentNameInput(value) {
    return safeString(value).replace(/\s+/g, ' ').slice(0, 64);
}

function normalizeAgentName(value) {
    const normalized = sanitizeAgentNameInput(value);
    return normalized || DEFAULT_AGENT_NAME;
}

function resolveAgentName(preferences) {
    const prefName = safeString(preferences?.profile?.display_name);
    return normalizeAgentName(prefName || activeAgentName);
}

function getAgentName() {
    return normalizeAgentName(activeAgentName || resolveAgentName(currentPreferences));
}

function withAgentName(templateRaw) {
    const template = safeString(templateRaw);
    if (!template) return '';
    return template.replace(/\{\{\s*agent\s*\}\}/gi, getAgentName());
}

function applyAgentIdentityToDom(nameRaw = '') {
    const agentName = normalizeAgentName(nameRaw || resolveAgentName(currentPreferences));
    activeAgentName = agentName;

    document.querySelectorAll('[data-agent-template]').forEach((el) => {
        const template = safeString(el.getAttribute('data-agent-template'));
        if (!template) return;
        el.textContent = template.replace(/\{\{\s*agent\s*\}\}/gi, agentName);
    });

    document.querySelectorAll('[data-agent-placeholder-template]').forEach((el) => {
        if (!('placeholder' in el)) return;
        const template = safeString(el.getAttribute('data-agent-placeholder-template'));
        if (!template) return;
        el.placeholder = template.replace(/\{\{\s*agent\s*\}\}/gi, agentName);
    });

    document.querySelectorAll('[data-agent-aria-label-template]').forEach((el) => {
        const template = safeString(el.getAttribute('data-agent-aria-label-template'));
        if (!template) return;
        el.setAttribute('aria-label', template.replace(/\{\{\s*agent\s*\}\}/gi, agentName));
    });
}

function resolveAvatarUrl(preferences, codexStatus) {
    const prefAvatar = safeString(preferences?.profile?.avatar_url);
    if (prefAvatar) return prefAvatar;
    return safeString(codexStatus?.avatar_url);
}

function updateSidebarIdentity() {
    const name = resolveAgentName(currentPreferences);
    const avatarUrl = resolveAvatarUrl(currentPreferences, currentCodexStatus);
    setAvatarVisual(sidebarUserAvatar, {
        text: initialsFromName(name),
        imageUrl: avatarUrl,
    });
    applyAgentIdentityToDom(name);
}

function normalizeProviderIdentity(providerRaw = '', profileName = '') {
    const normalized = safeString(providerRaw || profileName).toLowerCase();
    if (normalized.includes('openai_compat') || normalized.includes('openai-compat')) return 'openai_compat';
    if (normalized.includes('codex') || normalized.includes('openai') || normalized.includes('chatgpt') || normalized.includes('gpt') || normalized.includes('o1') || normalized.includes('o3') || normalized.includes('o4')) return 'openai';
    if (normalized.includes('google') || normalized.includes('gemini')) return 'gemini';
    if (normalized.includes('anthropic') || normalized.includes('claude')) return 'anthropic';
    if (normalized.includes('xai') || normalized.includes('x_ai') || normalized.includes('grok')) return 'grok';
    if (normalized.includes('qwen') || normalized.includes('tongyi')) return 'qwen';
    if (normalized.includes('deepseek')) return 'deepseek';
    if (normalized.includes('llama') || normalized.includes('meta')) return 'meta';
    if (normalized.includes('ollama') || normalized.includes('local')) return 'local';
    return normalized || 'assistant';
}

function resolveProviderIdentity(providerRaw = '', profileName = '', modelRaw = '') {
    const direct = normalizeProviderIdentity(providerRaw, profileName);
    if (direct !== 'assistant' && direct !== 'openai_compat') return direct;
    const inferred = normalizeProviderIdentity(modelRaw, profileName);
    if (inferred && inferred !== 'assistant' && inferred !== 'openai_compat') return inferred;
    return direct;
}

function providerIdentityLabel(providerId = 'assistant') {
    switch (normalizeProviderIdentity(providerId)) {
        case 'openai':
            return 'OpenAI';
        case 'openai_compat':
            return 'Compatible API';
        case 'gemini':
            return 'Gemini';
        case 'anthropic':
            return 'Anthropic';
        case 'grok':
            return 'Grok';
        case 'qwen':
            return 'Qwen';
        case 'deepseek':
            return 'DeepSeek';
        case 'meta':
            return 'Meta';
        case 'local':
            return 'Local';
        default:
            return safeString(providerId || 'Assistant')
                .replace(/[_-]+/g, ' ')
                .replace(/\b[a-z]/g, (match) => match.toUpperCase());
    }
}

function createProviderIdentityIcon(providerId = 'assistant', className = 'provider-identity-icon') {
    const icon = document.createElement('span');
    icon.className = className;
    icon.dataset.provider = normalizeProviderIdentity(providerId);
    icon.setAttribute('aria-hidden', 'true');
    return icon;
}

function resolveActiveChatProfileMeta() {
    const activeProfileName = activeProfileNameForPersistence()
        || safeString(currentPreferences?.advanced?.model?.active_profile)
        || safeString(window.localStorage.getItem('thomas_active_profile'));
    const profile = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name) === activeProfileName)
        : null;
    const modelLabel = safeString(resolveActiveModelIdForProfile(activeProfileName) || profile?.model).split('/').pop()
        || safeString(profile?.name)
        || _profileHeaderLabel(activeProfileName)
        || 'Default model';
    const providerId = resolveProviderIdentity(profile?.provider, profile?.name || activeProfileName, modelLabel);
    const providerLabel = providerIdentityLabel(providerId);
    return {
        providerId,
        providerLabel,
        modelLabel,
    };
}

function renderAssistantAvatarVisual(el, profileMeta = {}) {
    if (!el) return;
    el.replaceChildren();
    el.style.backgroundImage = '';
    el.dataset.provider = safeString(profileMeta.providerId || 'assistant');
    el.appendChild(createProviderIdentityIcon(profileMeta.providerId, 'provider-identity-icon avatar-provider-icon'));
}

function applyInterfaceMotionPreference() {
    const interfacePrefs = currentPreferences?.advanced?.interface || {};
    const fidelity = animationFidelityFromInterfacePrefs(interfacePrefs);
    const allowMotion = isAnimationFidelityEnabled(fidelity);
    const worldMode = chatWorldCurrentMode(interfacePrefs);
    if (!appRoot) return;
    appRoot.classList.toggle('no-motion', !allowMotion);
    appRoot.classList.toggle('motion-balanced', fidelity === ANIMATION_FIDELITY_BALANCED);
    appRoot.classList.toggle('motion-high-fidelity', fidelity === ANIMATION_FIDELITY_HIGH);
    appRoot.dataset.animationFidelity = fidelity;
    appRoot.dataset.chatWorldMode = worldMode;
    if (worldMode !== CHAT_WORLD_MODE_PHYSICS) {
        chatPhysicsWorldDestroy();
    }
    chatWorldSyncRootVisibility();
}

function readThemeName() {
    const value = safeString(getComputedStyle(document.documentElement).getPropertyValue('--theme-name'));
    return value.replace(/^["']|["']$/g, '') || 'Default';
}

function formatDebugTime(stamp = Date.now()) {
    try {
        return new Date(stamp).toLocaleTimeString([], { hour12: false });
    } catch {
        return '';
    }
}

function formatDebugValue(value) {
    if (value instanceof Error) {
        return `${value.name}: ${value.message}`;
    }
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean' || value === null || value === undefined) {
        return String(value);
    }
    try {
        return JSON.stringify(value);
    } catch {
        try {
            return String(value);
        } catch {
            return '[unserializable]';
        }
    }
}

function normalizeDebugUrl(input) {
    if (typeof input === 'string') return input;
    if (typeof URL !== 'undefined' && input instanceof URL) return input.toString();
    if (typeof Request !== 'undefined' && input instanceof Request) return safeString(input.url);
    if (input && typeof input === 'object' && 'url' in input) return safeString(input.url);
    return '';
}

function shortDebugUrl(url) {
    const raw = safeString(url);
    if (!raw) return '-';
    try {
        const parsed = new URL(raw, window.location.origin);
        return `${parsed.pathname}${parsed.search}` || parsed.toString();
    } catch {
        return raw;
    }
}

function setActiveDebugTab(tabRaw = 'runtime') {
    const normalized = DEBUG_TAB_SEQUENCE.includes(safeString(tabRaw))
        ? safeString(tabRaw)
        : 'runtime';
    activeDebugTab = normalized;

    const tabButtons = [
        debugTabRuntime,
        debugTabSystem,
        debugTabModels,
        debugTabTools,
        debugTabMemory,
        debugTabRuns,
        debugTabEvents,
        debugTabConsole,
        debugTabNetwork,
    ];
    tabButtons.forEach((button) => {
        if (!button) return;
        const isActive = safeString(button.dataset.debugTab) === normalized;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
        button.setAttribute('tabindex', isActive ? '0' : '-1');
    });
    const activeButton = tabButtons.find((button) => button && safeString(button.dataset.debugTab) === normalized);
    if (activeButton && typeof activeButton.scrollIntoView === 'function') {
        activeButton.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    const panels = [
        debugPanelRuntime,
        debugPanelSystem,
        debugPanelModels,
        debugPanelTools,
        debugPanelMemory,
        debugPanelRuns,
        debugPanelEvents,
        debugPanelConsole,
        debugPanelNetwork,
    ];
    panels.forEach((panel) => {
        if (!panel) return;
        const isActive = safeString(panel.dataset.debugPanel) === normalized;
        panel.classList.toggle('active', isActive);
        panel.setAttribute('aria-hidden', isActive ? 'false' : 'true');
    });

    updateDebugDockSnapshot();
    void refreshDebugLiveData({ reason: `tab:${normalized}` });
}

// 
//   DEBUG DOCK                                                             
//   Runtime, system, models, tools, memory, runs, console, network panels  
// 

function initDebugDockTabs() {
    if (!debugDockTabs) return;
    const tabButtons = [
        debugTabRuntime,
        debugTabSystem,
        debugTabModels,
        debugTabTools,
        debugTabMemory,
        debugTabRuns,
        debugTabEvents,
        debugTabConsole,
        debugTabNetwork,
    ];
    tabButtons.forEach((button) => {
        if (!button) return;
        button.addEventListener('click', () => {
            setActiveDebugTab(button.dataset.debugTab || 'runtime');
        });
        button.addEventListener('keydown', (event) => {
            const current = tabButtons.filter(Boolean).indexOf(button);
            if (current < 0) return;
            if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                event.preventDefault();
                const delta = event.key === 'ArrowRight' ? 1 : -1;
                const next = (current + delta + tabButtons.length) % tabButtons.length;
                const target = tabButtons[next];
                if (target) {
                    target.focus();
                    setActiveDebugTab(target.dataset.debugTab || 'runtime');
                }
            } else if (event.key === 'Home') {
                event.preventDefault();
                const target = tabButtons[0];
                if (target) {
                    target.focus();
                    setActiveDebugTab(target.dataset.debugTab || 'runtime');
                }
            } else if (event.key === 'End') {
                event.preventDefault();
                const target = tabButtons[tabButtons.length - 1];
                if (target) {
                    target.focus();
                    setActiveDebugTab(target.dataset.debugTab || 'runtime');
                }
            }
        });
    });
    setActiveDebugTab(activeDebugTab);
}

function debugRenderEmpty(target, message) {
    if (!target) return;
    target.innerHTML = '';
    const empty = document.createElement('div');
    empty.className = 'debug-empty';
    empty.textContent = safeString(message) || 'No data available.';
    target.appendChild(empty);
}

function debugCreateItemCard({ title = '', pill = '', pillTone = '', meta = [] } = {}) {
    const row = document.createElement('article');
    row.className = 'debug-item-card';

    const head = document.createElement('div');
    head.className = 'debug-item-head';

    const heading = document.createElement('div');
    heading.className = 'debug-item-title';
    heading.textContent = safeString(title) || 'Item';
    head.appendChild(heading);

    if (safeString(pill)) {
        const badge = document.createElement('span');
        badge.className = 'debug-item-pill';
        if (pillTone === 'ok' || pillTone === 'warn' || pillTone === 'error') {
            badge.classList.add(pillTone);
        }
        badge.textContent = safeString(pill);
        head.appendChild(badge);
    }

    row.appendChild(head);
    (Array.isArray(meta) ? meta : []).forEach((line) => {
        const text = safeString(line);
        if (!text) return;
        const body = document.createElement('div');
        body.className = 'debug-item-meta';
        body.textContent = text;
        row.appendChild(body);
    });
    return row;
}

function debugStatusToneFromBool(value) {
    if (value === true) return 'ok';
    if (value === false) return 'error';
    return 'warn';
}

function setDebugStatusNode(node, text, tone = '') {
    if (!node) return;
    node.textContent = safeString(text) || 'No status available.';
    node.classList.remove('ok', 'warn', 'error');
    if (tone === 'ok' || tone === 'warn' || tone === 'error') {
        node.classList.add(tone);
    }
}

function setDebugSystemStatus(text, tone = '') {
    setDebugStatusNode(debugSystemStatus, text, tone);
}

function setDebugOnboardingRepairButtonState({
    visible = true,
    enabled = true,
    label = 'Repair Now',
} = {}) {
    if (!debugOnboardingRepairBtn) return;
    debugOnboardingRepairBtn.hidden = !visible;
    debugOnboardingRepairBtn.disabled = !enabled;
    debugOnboardingRepairBtn.textContent = safeString(label) || 'Repair Now';
}

function formatDebugWhen(valueRaw) {
    const value = safeString(valueRaw);
    if (!value) return '-';
    try {
        const dt = new Date(value);
        if (!Number.isFinite(dt.getTime())) return value;
        return `${dt.toLocaleTimeString([], { hour12: false })}`;
    } catch {
        return value;
    }
}

function summarizeCapabilities(capabilityMap) {
    if (!capabilityMap || typeof capabilityMap !== 'object') return 'Capabilities unavailable';
    const entries = Object.entries(capabilityMap).filter(([, value]) => value === true);
    if (!entries.length) return 'No explicit capabilities';
    const labels = entries.map(([key]) => key.replace(/_/g, ' '));
    return labels.slice(0, 5).join(', ');
}

function parseEngineRows(enginePayload) {
    const rows = [];
    if (!enginePayload || typeof enginePayload !== 'object') return rows;
    const engines = enginePayload.engines;
    if (!engines || typeof engines !== 'object') return rows;
    Object.entries(engines).forEach(([name, info]) => {
        if (!info || typeof info !== 'object') return;
        const running = Boolean(info.running);
        rows.push({
            name,
            running,
            cycles: Number(info.cycles_completed || 0),
            lastActivity: safeString(info.last_activity || info.started_at),
            error: safeString(info.error),
        });
    });
    return rows;
}
