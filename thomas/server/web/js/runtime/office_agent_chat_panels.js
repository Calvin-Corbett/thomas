/** Agent chat and roster panels, using the shared Thomas workspace contract. */

function officeDraftChatMessageInstanceKey(agentId, entry) {
    const explicit = safeString(entry?.id || entry?.messageId || entry?.createdAt || entry?.timestamp);
    if (explicit) return explicit;
    const seed = [agentId, safeString(entry?.role), safeString(entry?.timeLabel), safeString(entry?.text)].join('|');
    return `${safeString(agentId) || 'agent'}-${Math.abs(officeStableHash(seed)).toString(36)}`;
}

function officeDraftConfigureLivePanel(panel, { id, label, policy = 'move resize', instanceKey = '' }) {
    if (!(panel instanceof HTMLElement)) return;
    panel.classList.add('office-live-panel');
    panel.dataset.uiId = id;
    panel.dataset.uiLabel = label;
    panel.dataset.uiPolicy = policy;
    panel.dataset.uiConstraints = 'minWidth=300;minHeight=220;maxWidth=760;maxHeight=900';
    if (instanceKey) panel.dataset.uiInstanceKey = instanceKey;
    else delete panel.dataset.uiInstanceKey;
}

function officeRenderDraftAgentChatPanel(options = {}) {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    const state = officeDraftEnsureAgentChatState();
    let panel = officeSceneWrap.querySelector('[data-office-agent-chat-panel="1"]');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('aside');
        panel.dataset.officeAgentChatPanel = '1';
        officeSceneWrap.appendChild(panel);
    }
    officeDraftConfigureLivePanel(panel, {
        id: 'virtual-office.agent-chat',
        label: 'Agent chat',
        instanceKey: safeString(state.agentChatAgentId),
    });
    if (!state.agentChatOpen || !officeState) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    const agent = officeGetAgentById(state.agentChatAgentId) || officeDraftSelectedAgentForChat();
    if (!agent) {
        panel.dataset.officeAgentChatAgentId = '';
        delete panel.dataset.uiInstanceKey;
        panel.style.display = 'grid';
        panel.innerHTML = `
            <header class="office-panel-head">
                <strong>Agent Chat</strong>
                <button class="office-control" type="button" data-office-agent-chat-close="1" data-ui-id="virtual-office.action.close-chat" data-ui-label="Close agent chat" data-ui-policy="protected controls">Close</button>
            </header>
            <div class="office-panel-empty">Click a robot to talk with that agent.</div>
        `;
        officeBindDraftAgentChatPanel(panel);
        return;
    }
    const agentId = safeString(agent.id);
    state.agentChatAgentId = agentId;
    panel.dataset.officeAgentChatAgentId = agentId;
    panel.dataset.uiInstanceKey = agentId;
    panel.dataset.uiLabel = `${safeString(agent.name) || 'Agent'} chat`;
    const palette = officeAgentPalette(agent);
    const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
        ? `costume-${safeString(agent.costume)}`
        : '';
    const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
    const room = officeRoomById(officeDraftRoomIdForAgent(agent));
    const activeTask = officeState.tasks.find((entry) => safeString(entry.assignedAgentId) === agentId && entry.status !== 'done');
    const chatModelLabel = officeDraftAgentChatModelLabel(agent);
    const pending = Boolean(agent.officeChatPending);
    const errorText = safeString(agent.officeChatError);
    const history = officeDraftAgentChatHistory(agent);
    const messageMarkup = history.length ? history.map((entry) => {
        const user = safeString(entry.role) === 'user';
        const instanceKey = officeDraftChatMessageInstanceKey(agentId, entry);
        return `
            <div class="office-chat-message ${user ? 'is-user' : 'is-agent'}" data-office-agent-chat-message="${user ? 'user' : 'agent'}" data-ui-id="virtual-office.chat-message" data-ui-instance-key="${escapeHtml(instanceKey)}" data-ui-label="${user ? 'Your message' : 'Agent message'}" data-ui-policy="protected live-record">
                <span class="office-chat-message-bubble">${escapeHtml(entry.text)}</span>
                <time class="office-chat-message-time">${escapeHtml(entry.timeLabel || '')}</time>
            </div>
        `;
    }).join('') : '<div class="office-panel-empty" data-office-agent-chat-empty="1">Send a message to start this agent\'s local chat memory.</div>';
    const pendingMarkup = pending
        ? '<div class="office-chat-pending" data-office-agent-chat-pending="1" role="status">Thinking...</div>'
        : '';
    const errorMarkup = errorText
        ? `<div class="office-chat-error" data-office-agent-chat-error="1" role="alert">${escapeHtml(errorText)}</div>`
        : '';
    panel.style.display = 'grid';
    panel.innerHTML = `
        <header class="office-panel-head">
            <strong>Agent Chat</strong>
            <button class="office-control" type="button" data-office-agent-chat-close="1" data-ui-id="virtual-office.action.close-chat" data-ui-label="Close agent chat" data-ui-policy="protected controls">Close</button>
        </header>
        <section class="office-agent-summary" data-ui-id="virtual-office.chat-agent-summary" data-ui-instance-key="${escapeHtml(agentId)}" data-ui-label="${escapeHtml(agent.name || 'Agent')} summary" data-ui-policy="move resize">
            <span class="office-agent-portrait"><span style="${paletteStyle}">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span></span>
            <span class="office-agent-summary-copy">
                <strong>${escapeHtml(agent.name || 'Agent')}</strong>
                <span>${escapeHtml(agent.specialty || 'Generalist')} - ${escapeHtml(room?.label || 'Office')}</span>
                <span class="office-accent-copy">Chat model: ${escapeHtml(chatModelLabel)}</span>
                <span>${escapeHtml(activeTask?.title || agent.lastMissionSummary || agent.lastOfficeChatSummary || 'Available.')}</span>
            </span>
        </section>
        <div class="office-chat-log" data-office-agent-chat-log="1" data-ui-id="virtual-office.chat-log" data-ui-instance-key="${escapeHtml(agentId)}" data-ui-label="Chat history" data-ui-policy="move resize">${messageMarkup}${pendingMarkup}</div>
        ${errorMarkup}
        <form class="office-chat-composer" data-office-agent-chat-form="1" data-ui-id="virtual-office.chat-composer" data-ui-instance-key="${escapeHtml(agentId)}" data-ui-label="Agent chat composer" data-ui-policy="protected controls">
            <textarea class="office-field" data-office-agent-chat-input="1" rows="3" placeholder="Message ${escapeHtml(agent.name || 'agent')}"${pending ? ' disabled' : ''}>${escapeHtml(state.agentChatDraftById[agent.id] || '')}</textarea>
            <button class="office-control office-control-primary" type="submit" data-office-agent-chat-send="1" data-ui-id="virtual-office.action.send-agent-message" data-ui-instance-key="${escapeHtml(agentId)}" data-ui-label="Send agent message" data-ui-policy="protected controls"${pending ? ' disabled' : ''}>${pending ? '...' : 'Send'}</button>
        </form>
    `;
    officeBindDraftAgentChatPanel(panel);
    const log = panel.querySelector('[data-office-agent-chat-log="1"]');
    if (log instanceof HTMLElement) log.scrollTop = log.scrollHeight;
    if (options?.focusInput) {
        window.setTimeout(() => {
            const input = panel.querySelector('[data-office-agent-chat-input="1"]');
            if (input instanceof HTMLTextAreaElement) {
                input.focus();
                input.setSelectionRange(input.value.length, input.value.length);
            }
        }, 0);
    }
}

function officeRenderDraftAgentRosterPanel() {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    const state = officeEnsureDraftMapState();
    let panel = officeSceneWrap.querySelector('[data-office-agent-roster-panel="1"]');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('aside');
        panel.dataset.officeAgentRosterPanel = '1';
        officeSceneWrap.appendChild(panel);
    }
    officeDraftConfigureLivePanel(panel, { id: 'virtual-office.agent-roster', label: 'Agent roster' });
    if (!state.rosterOpen || !officeState) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    const agents = Array.isArray(officeState.agents) ? officeState.agents : [];
    const expandedId = safeString(state.expandedRosterAgentId);
    const expandedAgent = expandedId ? agents.find((agent) => safeString(agent?.id) === expandedId) : null;
    const agentCard = (agent) => {
        const agentId = safeString(agent.id);
        const palette = officeAgentPalette(agent);
        const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none' ? `costume-${safeString(agent.costume)}` : '';
        const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
        const room = officeRoomById(officeDraftRoomIdForAgent(agent));
        return `
            <button class="office-roster-card" type="button" data-office-roster-expand="${escapeHtml(agentId)}" data-ui-id="virtual-office.roster-agent" data-ui-instance-key="${escapeHtml(agentId)}" data-ui-label="${escapeHtml(agent.name || 'Agent')} roster card" data-ui-policy="protected live-record">
                <span class="office-agent-portrait is-compact"><span style="${paletteStyle}">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span></span>
                <span class="office-roster-card-copy"><strong>${escapeHtml(agent.name || 'Agent')}</strong><span>${escapeHtml(room?.label || 'Office')}</span></span>
            </button>
        `;
    };
    const rosterGrid = agents.map(agentCard).join('') || '<div class="office-panel-empty">No agents yet.</div>';
    const detailMarkup = expandedAgent ? (() => {
        const agent = expandedAgent;
        const agentId = safeString(agent.id);
        const palette = officeAgentPalette(agent);
        const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none' ? `costume-${safeString(agent.costume)}` : '';
        const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
        const task = officeState.tasks.find((entry) => safeString(entry.assignedAgentId) === agentId && entry.status !== 'done');
        const room = officeRoomById(officeDraftRoomIdForAgent(agent));
        const optionMarkup = (options) => options.map((costume) => `<option value="${escapeHtml(costume)}"${safeString(agent.costume || 'none') === costume ? ' selected' : ''}>${escapeHtml(costume === 'none' ? 'none' : officeTaskTitle(costume))}</option>`).join('');
        const chatProfile = officeDraftAgentChatProfile(agent);
        const chatModelId = officeDraftAgentChatModelId(agent, chatProfile);
        const fieldAttrs = (field) => `data-office-roster-agent-id="${escapeHtml(agentId)}" data-ui-id="virtual-office.roster-field" data-ui-instance-key="${escapeHtml(`${agentId}:${field}`)}" data-ui-label="${escapeHtml(officeTaskTitle(field))}" data-ui-policy="protected controls"`;
        return `
            <div class="office-roster-detail" data-ui-id="virtual-office.roster-detail" data-ui-instance-key="${escapeHtml(agentId)}" data-ui-label="${escapeHtml(agent.name || 'Agent')} details" data-ui-policy="move resize">
                <button class="office-control office-roster-back" type="button" data-office-roster-back="1" data-ui-id="virtual-office.action.roster-back" data-ui-label="Back to agents" data-ui-policy="protected controls">Back to Agents</button>
                <section class="office-agent-summary is-large">
                    <span class="office-agent-portrait is-large"><span style="${paletteStyle}">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span></span>
                    <span class="office-agent-summary-copy"><strong>${escapeHtml(agent.name || 'Agent')}</strong><span>${escapeHtml(agent.specialty || 'Generalist')} - ${escapeHtml(room?.label || 'Office')}</span><span>${escapeHtml(task?.title || agent.lastMissionSummary || 'Available for the next task.')}</span></span>
                </section>
                <label class="office-label">Name<input class="office-field" data-office-roster-field="name" ${fieldAttrs('name')} value="${escapeHtml(agent.name)}" /></label>
                <label class="office-label">Specialty<input class="office-field" data-office-roster-field="specialty" ${fieldAttrs('specialty')} value="${escapeHtml(agent.specialty || 'Generalist')}" /></label>
                <label class="office-label">Personality<textarea class="office-field" data-office-roster-field="personality" ${fieldAttrs('personality')} rows="4">${escapeHtml(agent.personality || 'Helpful, direct, and persistent.')}</textarea></label>
                <section class="office-settings-group">
                    <strong>Chat Model</strong>
                    <label class="office-label">Profile<select class="office-field" data-office-roster-field="chatProfile" ${fieldAttrs('chat-profile')}>${officeDraftAgentChatProfileOptionsMarkup(chatProfile)}</select></label>
                    <label class="office-label">Model ID<input class="office-field" data-office-roster-field="chatModelId" ${fieldAttrs('chat-model')} value="${escapeHtml(chatModelId)}" placeholder="${escapeHtml(officeDraftDefaultChatModelId(chatProfile) || 'default')}" /></label>
                    <span class="office-panel-note">Used only for talking to this agent in the office. Task-specialist routing stays separate.</span>
                </section>
                <div class="office-roster-field-grid">
                    <label class="office-label">Body Color<input class="office-field office-color-field" type="color" data-office-roster-field="color" ${fieldAttrs('color')} value="${/^#[0-9a-f]{6}$/i.test(safeString(agent.color)) ? escapeHtml(agent.color) : '#9ad8ff'}" /></label>
                    <label class="office-label">Hat / Headset<select class="office-field" data-office-roster-field="costume" ${fieldAttrs('hat')}>${optionMarkup(['none', 'cap', 'visor', 'headset'])}</select></label>
                    <label class="office-label">Glasses / Badge<select class="office-field" data-office-roster-field="costume" ${fieldAttrs('accessory')}>${optionMarkup(['none', 'bowtie', 'scarf', 'badge', 'satchel'])}</select></label>
                    <label class="office-label">Held Item / Arms<select class="office-field" data-office-roster-field="costume" ${fieldAttrs('held-item')}>${optionMarkup(['none', 'tablet', 'wrench', 'mug', 'toolbelt'])}</select></label>
                </div>
            </div>
        `;
    })() : '';
    panel.style.display = 'block';
    panel.innerHTML = `
        <header class="office-panel-head"><strong>Agent Roster</strong><span>${agents.length} agents</span></header>
        ${expandedAgent ? detailMarkup : `<div class="office-roster-grid" data-ui-id="virtual-office.roster-grid" data-ui-label="Roster cards" data-ui-policy="move resize">${rosterGrid}</div>`}
    `;
    officeBindDraftRosterPanel(panel);
}
