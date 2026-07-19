/** Agent chat and roster panel rendering. */

function officeRenderDraftAgentChatPanel(options = {}) {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    const state = officeDraftEnsureAgentChatState();
    let panel = officeSceneWrap.querySelector('[data-office-agent-chat-panel="1"]');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('aside');
        panel.dataset.officeAgentChatPanel = '1';
        officeSceneWrap.appendChild(panel);
    }
    if (!state.agentChatOpen || !officeState) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    const agent = officeGetAgentById(state.agentChatAgentId) || officeDraftSelectedAgentForChat();
    if (!agent) {
        panel.dataset.officeAgentChatAgentId = '';
        panel.style.display = 'grid';
        panel.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                <strong style="font-size:0.9rem;letter-spacing:0.06em;text-transform:uppercase;">Agent Chat</strong>
                <button type="button" data-office-agent-chat-close="1" style="padding:7px 10px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.82);color:rgba(235,242,252,0.92);font-weight:800;">Close</button>
            </div>
            <div style="padding:14px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(12,19,31,0.86);color:rgba(204,218,238,0.76);font-size:0.78rem;line-height:1.45;">Click a robot to talk with that agent.</div>
        `;
        officeBindDraftAgentChatPanel(panel);
        return;
    }
    state.agentChatAgentId = safeString(agent.id);
    panel.dataset.officeAgentChatAgentId = safeString(agent.id);
    const palette = officeAgentPalette(agent);
    const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
        ? `costume-${safeString(agent.costume)}`
        : '';
    const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
    const room = officeRoomById(officeDraftRoomIdForAgent(agent));
    const activeTask = officeState.tasks.find((entry) => safeString(entry.assignedAgentId) === safeString(agent.id) && entry.status !== 'done');
    const chatModelLabel = officeDraftAgentChatModelLabel(agent);
    const pending = Boolean(agent.officeChatPending);
    const errorText = safeString(agent.officeChatError);
    const history = officeDraftAgentChatHistory(agent);
    const messageMarkup = history.length ? history.map((entry) => {
        const user = safeString(entry.role) === 'user';
        return `
            <div data-office-agent-chat-message="${user ? 'user' : 'agent'}" style="display:grid;justify-items:${user ? 'end' : 'start'};gap:3px;min-width:0;overflow:hidden;">
                <span style="display:block;box-sizing:border-box;max-width:96%;min-width:0;padding:9px 11px;border-radius:12px;background:${user ? 'rgba(75,121,204,0.36)' : 'rgba(12,19,31,0.92)'};border:1px solid ${user ? 'rgba(146,188,255,0.28)' : 'rgba(116,141,181,0.22)'};color:rgba(238,244,252,0.94);font-size:0.8rem;line-height:1.42;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;overflow:hidden;">${escapeHtml(entry.text)}</span>
                <span style="font-size:0.56rem;color:rgba(185,200,222,0.52);">${escapeHtml(entry.timeLabel || '')}</span>
            </div>
        `;
    }).join('') : `
        <div data-office-agent-chat-empty="1" style="padding:12px;border-radius:12px;border:1px dashed rgba(116,141,181,0.24);background:rgba(5,10,18,0.44);color:rgba(198,210,226,0.62);font-size:0.74rem;line-height:1.4;">Send a message to start this agent's local chat memory.</div>
    `;
    const pendingMarkup = pending ? `
        <div data-office-agent-chat-pending="1" style="justify-self:start;padding:7px 10px;border-radius:999px;background:rgba(72,111,172,0.24);border:1px solid rgba(129,182,255,0.25);color:rgba(218,232,252,0.82);font-size:0.68rem;font-weight:800;">Thinking...</div>
    ` : '';
    const errorMarkup = errorText ? `
        <div data-office-agent-chat-error="1" style="padding:8px 10px;border-radius:12px;border:1px solid rgba(248,112,112,0.28);background:rgba(88,25,31,0.42);color:rgba(255,214,214,0.9);font-size:0.72rem;line-height:1.35;">${escapeHtml(errorText)}</div>
    ` : '';
    panel.style.display = 'grid';
    panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
            <strong style="font-size:0.9rem;letter-spacing:0.06em;text-transform:uppercase;">Agent Chat</strong>
            <button type="button" data-office-agent-chat-close="1" style="padding:7px 10px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.82);color:rgba(235,242,252,0.92);font-weight:800;">Close</button>
        </div>
        <section style="display:grid;grid-template-columns:68px minmax(0,1fr);gap:10px;align-items:center;padding:10px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(12,19,31,0.86);">
            <span style="display:flex;align-items:center;justify-content:center;width:68px;height:66px;border-radius:14px;background:rgba(5,10,18,0.58);overflow:hidden;">
                <span style="transform:scale(0.82);transform-origin:center;">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span>
            </span>
            <span style="display:grid;gap:4px;min-width:0;">
                <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.94rem;color:rgba(242,246,252,0.96);">${escapeHtml(agent.name || 'Agent')}</strong>
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.72rem;color:rgba(196,211,231,0.74);">${escapeHtml(agent.specialty || 'Generalist')} - ${escapeHtml(room?.label || 'Office')}</span>
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.66rem;color:rgba(169,210,255,0.72);">Chat model: ${escapeHtml(chatModelLabel)}</span>
                <span style="font-size:0.66rem;line-height:1.32;color:rgba(196,211,231,0.62);">${escapeHtml(activeTask?.title || agent.lastMissionSummary || agent.lastOfficeChatSummary || 'Available.')}</span>
            </span>
        </section>
        <div data-office-agent-chat-log="1" style="display:grid;align-content:start;gap:10px;min-height:220px;max-height:420px;overflow-y:auto;overflow-x:hidden;padding:2px 4px 6px 2px;overscroll-behavior:contain;min-width:0;">${messageMarkup}${pendingMarkup}</div>
        ${errorMarkup}
        <form data-office-agent-chat-form="1" style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end;">
            <textarea data-office-agent-chat-input="1" rows="3" placeholder="Message ${escapeHtml(agent.name || 'agent')}"${pending ? ' disabled' : ''} style="box-sizing:border-box;width:100%;min-width:0;min-height:72px;max-height:150px;resize:vertical;padding:10px 11px;border-radius:12px;border:1px solid rgba(116,141,181,0.26);background:rgba(5,10,18,0.82);color:rgba(242,246,252,0.94);font-size:0.8rem;line-height:1.4;overflow-x:hidden;overflow-y:auto;white-space:pre-wrap;overflow-wrap:anywhere;">${escapeHtml(state.agentChatDraftById[agent.id] || '')}</textarea>
            <button type="submit" data-office-agent-chat-send="1"${pending ? ' disabled' : ''} style="height:42px;padding:0 13px;border-radius:12px;border:1px solid rgba(129,182,255,0.38);background:${pending ? 'rgba(48,60,82,0.74)' : 'rgba(48,88,154,0.74)'};color:rgba(246,250,255,0.96);font-weight:900;">${pending ? '...' : 'Send'}</button>
        </form>
    `;
    officeBindDraftAgentChatPanel(panel);
    const log = panel.querySelector('[data-office-agent-chat-log="1"]');
    if (log instanceof HTMLElement) {
        log.scrollTop = log.scrollHeight;
    }
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
    if (!state.rosterOpen || !officeState) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    const agents = Array.isArray(officeState.agents) ? officeState.agents : [];
    const expandedId = safeString(state.expandedRosterAgentId);
    const expandedAgent = expandedId ? agents.find((agent) => safeString(agent?.id) === expandedId) : null;
    const agentCard = (agent) => {
        const palette = officeAgentPalette(agent);
        const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
            ? `costume-${safeString(agent.costume)}`
            : '';
        const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
        const room = officeRoomById(officeDraftRoomIdForAgent(agent));
        return `
            <button type="button" data-office-roster-expand="${escapeHtml(agent.id)}" style="display:grid;gap:7px;align-items:center;justify-items:center;min-width:0;padding:9px 7px;border-radius:12px;border:1px solid rgba(116,141,181,0.2);background:rgba(12,19,31,0.86);color:inherit;text-align:center;cursor:pointer;">
                <span style="display:flex;align-items:center;justify-content:center;width:62px;height:58px;border-radius:14px;background:rgba(5,10,18,0.58);overflow:hidden;">
                    <span style="transform:scale(0.78);transform-origin:center;">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span>
                </span>
                <span style="display:block;width:100%;min-width:0;">
                    <strong style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.74rem;color:rgba(242,246,252,0.96);">${escapeHtml(agent.name || 'Agent')}</strong>
                    <span style="display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.58rem;color:rgba(196,211,231,0.72);">${escapeHtml(room?.label || 'Office')}</span>
                </span>
            </button>
        `;
    };
    const rosterGrid = agents.map(agentCard).join('') || '<div style="grid-column:1/-1;padding:12px;border-radius:12px;background:rgba(9,15,26,0.72);color:rgba(198,210,226,0.72);font-size:0.76rem;">No agents yet.</div>';
    const detailMarkup = expandedAgent ? (() => {
        const agent = expandedAgent;
        const palette = officeAgentPalette(agent);
        const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
            ? `costume-${safeString(agent.costume)}`
            : '';
        const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
        const task = officeState.tasks.find((entry) => safeString(entry.assignedAgentId) === safeString(agent.id) && entry.status !== 'done');
        const room = officeRoomById(officeDraftRoomIdForAgent(agent));
        const optionMarkup = (options) => options.map((costume) => `
            <option value="${escapeHtml(costume)}"${safeString(agent.costume || 'none') === costume ? ' selected' : ''}>${escapeHtml(costume === 'none' ? 'none' : officeTaskTitle(costume))}</option>
        `).join('');
        const hatOptions = optionMarkup(['none', 'cap', 'visor', 'headset']);
        const accessoryOptions = optionMarkup(['none', 'bowtie', 'scarf', 'badge', 'satchel']);
        const heldOptions = optionMarkup(['none', 'tablet', 'wrench', 'mug', 'toolbelt']);
        const chatProfile = officeDraftAgentChatProfile(agent);
        const chatModelId = officeDraftAgentChatModelId(agent, chatProfile);
        const chatProfileOptions = officeDraftAgentChatProfileOptionsMarkup(chatProfile);
        return `
            <div style="display:grid;gap:12px;">
                <button type="button" data-office-roster-back="1" style="justify-self:start;padding:6px 10px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.82);color:rgba(235,242,252,0.92);font-weight:800;">Back to Agents</button>
                <section style="display:grid;grid-template-columns:96px 1fr;gap:12px;align-items:center;padding:12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(12,19,31,0.86);">
                    <span style="display:flex;align-items:center;justify-content:center;width:96px;height:94px;border-radius:16px;background:rgba(5,10,18,0.58);overflow:hidden;">
                        <span style="transform:scale(1.08);transform-origin:center;">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span>
                    </span>
                    <span style="display:grid;gap:4px;min-width:0;">
                        <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:1.04rem;color:rgba(242,246,252,0.96);">${escapeHtml(agent.name || 'Agent')}</strong>
                        <span style="font-size:0.76rem;color:rgba(196,211,231,0.74);">${escapeHtml(agent.specialty || 'Generalist')} - ${escapeHtml(room?.label || 'Office')}</span>
                        <span style="font-size:0.7rem;line-height:1.4;color:rgba(196,211,231,0.66);">${escapeHtml(task?.title || agent.lastMissionSummary || 'Available for the next task.')}</span>
                    </span>
                </section>
                <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Name
                    <input data-office-roster-field="name" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(agent.name)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);" />
                </label>
                <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Specialty
                    <input data-office-roster-field="specialty" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(agent.specialty || 'Generalist')}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);" />
                </label>
                <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Personality
                    <textarea data-office-roster-field="personality" data-office-roster-agent-id="${escapeHtml(agent.id)}" rows="4" style="width:100%;resize:vertical;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${escapeHtml(agent.personality || 'Helpful, direct, and persistent.')}</textarea>
                </label>
                <section style="display:grid;gap:8px;padding:10px;border-radius:12px;border:1px solid rgba(116,141,181,0.18);background:rgba(5,10,18,0.38);">
                    <strong style="font-size:0.72rem;color:rgba(218,232,252,0.86);">Chat Model</strong>
                    <label style="display:grid;gap:4px;font-size:0.68rem;color:rgba(198,210,226,0.72);">Profile
                        <select data-office-roster-field="chatProfile" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${chatProfileOptions}</select>
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.68rem;color:rgba(198,210,226,0.72);">Model ID
                        <input data-office-roster-field="chatModelId" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(chatModelId)}" placeholder="${escapeHtml(officeDraftDefaultChatModelId(chatProfile) || 'default')}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);" />
                    </label>
                    <span style="font-size:0.62rem;line-height:1.35;color:rgba(182,199,224,0.58);">Used only for talking to this agent in the office. Task-specialist routing stays separate.</span>
                </section>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Body Color
                        <input type="color" data-office-roster-field="color" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${/^#[0-9a-f]{6}$/i.test(safeString(agent.color)) ? escapeHtml(agent.color) : '#9ad8ff'}" style="width:100%;height:36px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);" />
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Hat / Headset
                        <select data-office-roster-field="costume" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${hatOptions}</select>
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Glasses / Badge
                        <select data-office-roster-field="costume" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${accessoryOptions}</select>
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Held Item / Arms
                        <select data-office-roster-field="costume" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${heldOptions}</select>
                    </label>
                </div>
            </div>
        `;
    })() : '';
    panel.style.display = 'block';
    panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;">
            <strong style="font-size:0.92rem;letter-spacing:0.04em;text-transform:uppercase;">Agent Roster</strong>
            <span style="font-size:0.72rem;color:rgba(202,214,230,0.72);">${agents.length} agents</span>
        </div>
        ${expandedAgent ? detailMarkup : `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;">${rosterGrid}</div>`}
    `;
    officeBindDraftRosterPanel(panel);
}


