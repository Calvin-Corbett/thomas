// Extracted from part-010b.js
// // ║  SE


function deriveChatTitleFromMessages(messagesRaw) {
    const preview = deriveChatPreviewFromMessages(messagesRaw);
    if (preview) return preview.slice(0, 72);
    return 'New Chat';
}

function formatSidebarTimestamp(epochMs) {
    const ts = Number(epochMs);
    if (!Number.isFinite(ts) || ts <= 0) return '';
    try {
        return new Date(ts).toLocaleString([], {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        });
    } catch (error) {
        return '';
    }
}

// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║  SESSION & CHAT PERSISTENCE                                             ║
// ║  Chat save/load, sidebar sessions, persistence helpers, animation locks ║
// ╚═══════════════════════════════════════════════════════════════════════════╝

function mapPersistedChatToSidebarSession(chatRaw) {
    if (!chatRaw || typeof chatRaw !== 'object') return null;
    const id = safeString(chatRaw.id);
    if (!id) return null;

    const messages = normalizeConversationHistory(chatRaw.messages);
    const createdAt = Number(chatRaw.createdAt);
    const updatedAt = Number(chatRaw.updatedAt);
    const createdAtSafe = Number.isFinite(createdAt) && createdAt > 0 ? Math.floor(createdAt) : Date.now();
    const updatedAtSafe = Number.isFinite(updatedAt) && updatedAt > 0 ? Math.floor(updatedAt) : createdAtSafe;

    const title = safeString(chatRaw.title) || deriveChatTitleFromMessages(messages);
    const preview = deriveChatPreviewFromMessages(messages) || title;
    const model = safeString(chatRaw.model);
    const timestamp = formatSidebarTimestamp(updatedAtSafe);

    return {
        id,
        title,
        preview,
        model,
        timestamp,
        createdAt: createdAtSafe,
        updatedAt: updatedAtSafe,
        pinned: Boolean(chatRaw.pinned),
        sessionId: safeString(chatRaw.sessionId),
        messages,
    };
}

function mapLegacySidebarSession(sessionRaw) {
    if (!sessionRaw || typeof sessionRaw !== 'object') return null;
    const id = safeString(sessionRaw.id);
    if (!id) return null;
    const preview = safeString(sessionRaw.preview);
    const title = preview || `Chat ${id.slice(0, 8)}`;
    return {
        id,
        title,
        preview: preview || title,
        model: safeString(sessionRaw.model),
        timestamp: safeString(sessionRaw.timestamp),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        pinned: false,
        sessionId: id,
        messages: normalizeConversationHistory(sessionRaw.conversation),
    };
}

function activeProfileNameForPersistence() {
    return (
        safeString(setupProviderSelector?.value)
        || safeString(modelSelector?.value)
        || safeString(availableModelProfiles.find((p) => safeString(p?.name) === safeString(modelSelector?.value))?.name)
        || ''
    );
}

function formatSidebarSessionTitle(session) {
    const title = safeString(session?.title);
    if (title) return title;
    const preview = safeString(session?.preview);
    if (preview) return preview;
    const sid = safeString(session?.id);
    return sid ? `Chat ${sid.slice(0, 8)}` : 'Untitled chat';
}

function formatSidebarSessionMeta(session) {
    const model = safeString(session?.model) || activeProfileNameForPersistence();
    const timestamp = safeString(session?.timestamp);
    if (model && timestamp) return `${model} | ${timestamp}`;
    if (model) return model;
    if (timestamp) return timestamp;
    return 'Chat';
}

function rebuildChatHistorySelector() {
    if (!chatHistorySelector) return;
    const activeId = safeString(activeChatId) || safeString(sessionId);
    chatHistorySelector.innerHTML = '<option value="new">New Chat</option>';
    sidebarSessions.forEach((session) => {
        const sid = safeString(session?.id);
        if (!sid) return;
        const opt = document.createElement('option');
        opt.value = sid;
        const title = formatSidebarSessionTitle(session);
        opt.textContent = title.length > 36 ? `${title.slice(0, 33)}...` : title;
        if (sid === activeId) opt.selected = true;
        chatHistorySelector.appendChild(opt);
    });
}

function upsertSidebarSession(sessionRaw) {
    const session = mapPersistedChatToSidebarSession(sessionRaw) || mapLegacySidebarSession(sessionRaw);
    if (!session) return;
    const sid = safeString(session.id);
    sidebarSessions = [
        session,
        ...sidebarSessions.filter((row) => safeString(row?.id) !== sid),