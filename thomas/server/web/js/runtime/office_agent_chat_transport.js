/** Agent chat streaming transport and actions. */

async function officeDraftRequestAgentChatReply(agent, userTextRaw) {
    const payload = officeDraftBuildAgentChatRequestPayload(agent, userTextRaw);
    const chatEndpoint = '/api/v2/chat';
    const response = await fetch(chatEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        let errorText = '';
        try {
            errorText = safeString(await response.text()).slice(0, 180);
        } catch (_) {
            errorText = '';
        }
        throw new Error(errorText || `Agent chat failed (${response.status})`);
    }

    const chunks = [];
    let doneText = '';
    const consumeLine = (lineRaw) => {
        let line = safeString(lineRaw).trim();
        if (!line) return;
        if (line.startsWith('data:')) line = line.slice(5).trim();
        if (!line || line === '[DONE]') return;
        try {
            const evt = JSON.parse(line);
            const text = officeDraftExtractAgentChatEventText(evt);
            if (text) chunks.push(text);
            const finalText = officeDraftExtractAgentChatDoneText(evt);
            if (finalText) doneText = finalText;
        } catch (_) {
            chunks.push(line);
        }
    };

    if (response.body && typeof response.body.getReader === 'function') {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split(/\r?\n/);
            buffer = lines.pop() || '';
            lines.forEach(consumeLine);
        }
        buffer += decoder.decode();
        if (buffer.trim()) consumeLine(buffer);
    } else {
        const text = await response.text();
        text.split(/\r?\n/).forEach(consumeLine);
    }

    const reply = safeString(officeDraftJoinAgentChatChunks(chunks) || doneText).trim();
    if (!reply) {
        throw new Error('The chat model returned no text.');
    }
    return { reply, payload };
}

function officeDraftSelectedAgentForChat() {
    if (!officeState) return null;
    const state = officeDraftEnsureAgentChatState();
    const selectedId = safeString(state.agentChatAgentId || officeState.selectedAgentId || state.expandedRosterAgentId);
    return (selectedId ? officeGetAgentById(selectedId) : null)
        || (Array.isArray(officeState.agents) ? officeState.agents[0] : null)
        || null;
}

function officeDraftOpenAgentChat(agentIdRaw, options = {}) {
    const state = officeDraftEnsureAgentChatState();
    const agent = (officeState && officeGetAgentById(agentIdRaw))
        || officeDraftSelectedAgentForChat();
    state.agentChatOpen = true;
    if (!agent) {
        state.agentChatAgentId = '';
        officeRenderDraftAgentChatPanel();
        officePrepareDraftMapShell();
        return null;
    }
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    state.agentChatAgentId = safeString(agent.id);
    state.expandedRosterAgentId = safeString(agent.id);
    if (officeState) officeState.selectedAgentId = safeString(agent.id);
    if (options?.prime !== false) {
        officeDraftPrimeAgentConversation(agent, space, performance.now());
    }
    officeDraftSeedAgentChat(agent, space, performance.now());
    officeRenderDraftAgentChatPanel({ focusInput: Boolean(options?.focusInput) });
    officePrepareDraftMapShell();
    return agent;
}

function officeDraftCloseAgentChat(event) {
    if (event?.preventDefault) event.preventDefault();
    if (event?.stopPropagation) event.stopPropagation();
    const state = officeDraftEnsureAgentChatState();
    state.agentChatOpen = false;
    officeRenderDraftAgentChatPanel();
    officePrepareDraftMapShell();
}

function officeToggleDraftAgentChat(event) {
    if (event?.preventDefault) event.preventDefault();
    if (event?.stopPropagation) event.stopPropagation();
    const state = officeDraftEnsureAgentChatState();
    if (state.agentChatOpen) {
        officeDraftCloseAgentChat(event);
        return;
    }
    officeDraftOpenAgentChat(safeString(officeState?.selectedAgentId || state.expandedRosterAgentId), {
        focusInput: true,
        prime: true,
    });
}

async function officeDraftSendAgentChatMessage(agentIdRaw = '') {
    const state = officeDraftEnsureAgentChatState();
    const agent = officeGetAgentById(agentIdRaw || state.agentChatAgentId);
    if (!agent) return false;
    if (agent.officeChatPending) return false;
    const panel = officeSceneWrap?.querySelector('[data-office-agent-chat-panel="1"]');
    const input = panel?.querySelector('[data-office-agent-chat-input="1"]');
    const text = safeString(input instanceof HTMLTextAreaElement ? input.value : state.agentChatDraftById?.[agent.id]).trim();
    if (!text) return false;
    const now = performance.now();
    state.agentChatDraftById[agent.id] = '';
    officeDraftAppendAgentChat(agent, 'user', text, now);
    agent.lastOfficeChatSummary = text.slice(0, 160);
    const commandResult = officeDraftApplyAgentChatCommand(agent, text);
    agent.lastOfficeChatCommandHandled = Boolean(commandResult);
    agent.officeChatError = '';
    agent.officeChatPending = true;
    if (typeof officePushChatLine === 'function') {
        officePushChatLine(`You -> @${safeString(agent.name) || 'Agent'}: ${text}`, 'user');
    }
    officeRenderDraftAgentChatPanel({ focusInput: false });
    officeRenderDraftAgentLayerOnly(now, { force: true, source: 'agent-chat-pending' });
    try {
        const { reply, payload } = await officeDraftRequestAgentChatReply(agent, text);
        agent.lastOfficeChatPayload = payload;
        officeDraftAppendAgentChat(agent, 'agent', reply, performance.now());
        if (typeof officeSpeak === 'function') {
            officeSpeak(agent, reply, { priority: true, durationMs: Math.max(2600, Math.min(7200, reply.length * 42)) });
        }
        if (typeof officePushChatLine === 'function') {
            officePushChatLine(`@${safeString(agent.name) || 'Agent'}: ${reply}`);
        }
        if (typeof officeBusEmit === 'function') {
            officeBusEmit('agent.chat_message', {
                agentId: safeString(agent.id),
                agentName: safeString(agent.name),
                message: text.slice(0, 260),
                reply: reply.slice(0, 260),
                sessionId: safeString(payload?.session_id),
                profile: safeString(payload?.profile),
                modelId: safeString(payload?.model_id),
            }, performance.now());
        }
    } catch (error) {
        console.warn('office agent chat request failed', error);
        agent.officeChatError = safeString(error?.message || error || 'Agent chat failed.').slice(0, 220);
    } finally {
        agent.officeChatPending = false;
        officePersistAgentPrefs();
        officeRenderDraftAgentChatPanel({ focusInput: true });
        officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-chat' });
    }
    return true;
}

function officeBindDraftAgentChatPanel(panel) {
    if (!(panel instanceof HTMLElement)) return;
    if (panel.dataset.officeAgentChatPointerBound !== '1') {
        panel.dataset.officeAgentChatPointerBound = '1';
        panel.addEventListener('pointerdown', (event) => {
            event.stopPropagation();
        });
    }
    const state = officeDraftEnsureAgentChatState();
    const agentId = safeString(panel.dataset.officeAgentChatAgentId || state.agentChatAgentId);
    const closeBtn = panel.querySelector('[data-office-agent-chat-close="1"]');
    if (closeBtn instanceof HTMLButtonElement) {
        closeBtn.addEventListener('click', officeDraftCloseAgentChat);
    }
    const form = panel.querySelector('[data-office-agent-chat-form="1"]');
    if (form instanceof HTMLFormElement) {
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            event.stopPropagation();
            void officeDraftSendAgentChatMessage(agentId);
        });
    }
    const input = panel.querySelector('[data-office-agent-chat-input="1"]');
    if (input instanceof HTMLTextAreaElement) {
        input.addEventListener('input', () => {
            state.agentChatDraftById[agentId] = input.value;
        });
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void officeDraftSendAgentChatMessage(agentId);
            }
        });
    }
}

