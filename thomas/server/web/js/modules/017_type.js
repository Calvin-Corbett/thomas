// Extracted from part-009.js
// From type

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

/* ── Toast helper ── */
function showToast(msg, durationMs = 2000) {
    if (!toastContainer) return;
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    toastContainer.appendChild(t);
    setTimeout(() => t.remove(), durationMs + 300);
}

/* ── Code-block header injection (DOM walk, avoids sanitizer) ── */
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
 * Render a message bubble into the stream
 */
function renderMessage(msg) {
    const isUser = msg.role === 'user';
    const row = document.createElement('div');
    row.className = 'message-row';
    if (msg.id) {
        row.id = String(msg.id);
    }

    const avatar = document.createElement('div');
    avatar.className = `avatar ${isUser ? 'user' : 'assistant'}`;
    if (isUser) {
        avatar.textContent = 'U';
    } else {
        const icon = document.createElement('i');
        icon.className = 'ph ph-sparkle';
        avatar.appendChild(icon);
    }

    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerHTML = formatMarkdown(msg.content);

    row.appendChild(avatar);
    row.appendChild(content);

    // Message action buttons (hover-visible)
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    if (isUser) {
        actions.innerHTML = [
            '<button class="msg-action-btn" data-action="edit" title="Edit message"><i class="ph ph-pencil-simple"></i></button>',
            '<button class="msg-action-btn" data-action="copy" title="Copy message"><i class="ph ph-copy"></i></button>',
            '<button class="msg-action-btn" data-action="pin" title="Pin message"><i class="ph ph-push-pin"></i></button>',