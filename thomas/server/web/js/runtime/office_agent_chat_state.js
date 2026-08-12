/** Per-agent chat state, profile, and request payloads. */

function officeDraftEnsureAgentChatState(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    state.agentChatOpen = Boolean(state.agentChatOpen);
    state.agentChatAgentId = safeString(state.agentChatAgentId);
    if (!state.agentChatDraftById || typeof state.agentChatDraftById !== 'object' || Array.isArray(state.agentChatDraftById)) {
        state.agentChatDraftById = {};
    }
    return state;
}

function officeDraftAgentChatHistory(agent) {
    if (!agent) return [];
    if (!Array.isArray(agent.officeChatHistory)) {
        agent.officeChatHistory = [];
    }
    if (agent.officeChatHistory.length > 28) {
        agent.officeChatHistory.splice(0, agent.officeChatHistory.length - 28);
    }
    return agent.officeChatHistory;
}

function officeDraftAppendAgentChat(agent, roleRaw, textRaw, now = performance.now()) {
    const text = safeString(textRaw).replace(/\s+/g, ' ').trim();
    if (!agent || !text) return null;
    const entry = {
        role: safeString(roleRaw) || 'agent',
        text: text.slice(0, 600),
        at: Date.now(),
        timeLabel: new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
    };
    const history = officeDraftAgentChatHistory(agent);
    history.push(entry);
    if (history.length > 28) {
        history.splice(0, history.length - 28);
    }
    agent.lastOfficeChatAt = Number(now) || performance.now();
    return entry;
}

function officeDraftJoinAgentChatChunks(chunksRaw = []) {
    const chunks = (Array.isArray(chunksRaw) ? chunksRaw : [])
        .map((chunk) => safeString(chunk))
        .filter((chunk) => chunk);
    if (!chunks.length) return '';
    if (chunks.some((chunk) => /\s/.test(chunk))) return chunks.join('');
    if (chunks.every((chunk) => chunk.length <= 1)) return chunks.join('');
    return chunks.join(' ');
}

function officeDraftSeedAgentChat(agent, space, now = performance.now()) {
    if (!agent) return;
    officeDraftAgentChatHistory(agent);
    if (!agent.lastOfficeConversationPrompt) {
        officeDraftPrimeAgentConversation(agent, space, now);
    }
}

function officeDraftAgentChatSessionId(agent) {
    const rawId = safeString(agent?.id || agent?.name || 'agent');
    const slug = rawId.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 64) || 'agent';
    return `office-agent-chat-${slug}`;
}

function officeDraftDefaultChatProfile() {
    return safeString(modelSelector?.value)
        || safeString(setupProviderSelector?.value)
        || safeString(currentPreferences?.advanced?.model?.active_profile)
        || (Array.isArray(availableModelProfiles) ? safeString(availableModelProfiles.find((profile) => safeString(profile?.name))?.name) : '')
        || '';
}

function officeDraftDefaultChatModelId(profileRaw = '') {
    const profile = safeString(profileRaw || officeDraftDefaultChatProfile());
    if (!profile) return safeString(activeModelOverride);
    if (typeof resolveActiveModelIdForProfile === 'function') {
        const activeModelId = safeString(resolveActiveModelIdForProfile(profile));
        if (activeModelId) return activeModelId;
    }
    if (typeof defaultModelIdForProfile === 'function') {
        return safeString(defaultModelIdForProfile(profile));
    }
    const profileMeta = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name) === profile)
        : null;
    return safeString(profileMeta?.model).split('/').pop();
}

function officeDraftAgentChatProfile(agent) {
    return safeString(agent?.chatProfile) || officeDraftDefaultChatProfile();
}

function officeDraftAgentChatModelId(agent, profileRaw = '') {
    const profile = safeString(profileRaw || officeDraftAgentChatProfile(agent));
    return safeString(agent?.chatModelId) || officeDraftDefaultChatModelId(profile);
}

function officeDraftAgentChatModelLabel(agent) {
    const profile = officeDraftAgentChatProfile(agent);
    const modelId = safeString(officeDraftAgentChatModelId(agent, profile)).split('/').pop();
    const providerLabel = profile && typeof formatProviderDisplay === 'function'
        ? (formatProviderDisplay(profile) || profile)
        : profile;
    if (providerLabel && modelId) return `${providerLabel} - ${modelId}`;
    return providerLabel || modelId || 'default model';
}

function officeDraftAgentChatProfileOptionsMarkup(selectedProfileRaw = '') {
    const selectedProfile = safeString(selectedProfileRaw || officeDraftDefaultChatProfile());
    const profiles = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.filter((profile) => safeString(profile?.name))
        : [];
    if (!profiles.length) {
        const fallback = selectedProfile || 'default';
        return `<option value="${escapeHtml(fallback)}" selected>${escapeHtml(fallback)}</option>`;
    }
    let hasSelected = false;
    const options = profiles.map((profile) => {
        const name = safeString(profile?.name);
        const modelId = safeString(officeDraftDefaultChatModelId(name) || profile?.model).split('/').pop();
        const providerLabel = typeof formatProviderDisplay === 'function'
            ? (formatProviderDisplay(name) || name)
            : name;
        const isSelected = name === selectedProfile;
        hasSelected = hasSelected || isSelected;
        return `<option value="${escapeHtml(name)}"${isSelected ? ' selected' : ''}>${escapeHtml(providerLabel)}${modelId ? ` - ${escapeHtml(modelId)}` : ''}</option>`;
    });
    if (selectedProfile && !hasSelected) {
        options.unshift(`<option value="${escapeHtml(selectedProfile)}" selected>${escapeHtml(selectedProfile)}</option>`);
    }
    return options.join('');
}

function officeDraftBuildAgentChatRequestPayload(agent, userTextRaw) {
    const text = safeString(userTextRaw).trim();
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    const promptPrefix = officeDraftBuildAgentConversationPrompt(agent, space);
    const profile = officeDraftAgentChatProfile(agent);
    const modelId = officeDraftAgentChatModelId(agent, profile);
    const message = `${promptPrefix}\n\nUser message:\n${text}`;
    const payload = typeof buildChatRequestPayload === 'function'
        ? buildChatRequestPayload(message, {
            docs: [],
            images: [],
            systemPrompt: promptPrefix,
            resolvedProfile: profile,
            studioChatContext: { enabled: false },
        })
        : {
            message,
            docs: [],
            images: [],
            system_prompt: promptPrefix,
        };
    payload.message = message;
    payload.session_id = officeDraftAgentChatSessionId(agent);
    payload.profile = profile || payload.profile || undefined;
    payload.model = payload.profile || profile || undefined;
    payload.model_id = modelId || undefined;
    payload.mode = 'auto';
    payload.autonomy_level = 1;
    payload.file_access = 'read_only';
    payload.module = undefined;
    payload.asset_studio_mode = undefined;
    payload.asset_studio_context = undefined;
    payload.office_agent_chat = {
        agent_id: safeString(agent?.id),
        agent_name: safeString(agent?.name),
        specialty: safeString(agent?.specialty),
        chat_profile: profile,
        chat_model_id: modelId,
        session_id: payload.session_id,
    };
    return payload;
}

function officeDraftExtractAgentChatEventText(evt) {
    if (!evt || typeof evt !== 'object') return '';
    const evtType = safeString(evt.type);
    if (evtType === 'text') return safeString(evt.text);
    if (evtType === 'agent_text') return safeString(evt.text || evt.delta || evt.content);
    if (['assistant_delta', 'delta', 'message_delta'].includes(evtType)) {
        return safeString(evt.text || evt.delta || evt.content);
    }
    if (evtType === 'assistant' || evtType === 'message') {
        return safeString(evt.text || evt.content || evt.message);
    }
    const choiceDelta = evt?.choices?.[0]?.delta?.content || evt?.choices?.[0]?.message?.content;
    return safeString(choiceDelta);
}

function officeDraftExtractAgentChatDoneText(evt) {
    if (!evt || typeof evt !== 'object') return '';
    if (safeString(evt.type) !== 'done') return '';
    return safeString(evt.text || evt.final || evt.output_text || evt.message);
}
