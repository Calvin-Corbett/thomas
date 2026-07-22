/** Agent activity, animation, and conversation presentation. */

function officeDraftAgentActivity(agent, space) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const now = performance.now();
    const state = safeString(agent?.state);
    if (agent?.draftMotion?.dragging) return 'dragging';
    if ((Number(agent?.draftDropUntil) || 0) > now) return 'dropped';
    if ((Number(agent?.draftPausedUntil) || 0) > now) {
        return agent?.speech ? 'talking' : 'paused';
    }
    if (Array.isArray(agent?.draftMotion?.route) && agent.draftMotion.route.length) return 'walking';
    officeDraftMaybeCompleteAgentCommand(agent, now);
    if (officeDraftAgentCommandActive(agent, now)) {
        const commandIntent = safeString(agent?.draftInteractionIntent);
        if (commandIntent === 'drink') return 'drink';
        if (commandIntent === 'food') return 'drink';
        if (commandIntent === 'sit') return 'sit';
        if (['work', 'play', 'research', 'print', 'charge', 'monitor', 'record'].includes(commandIntent)) return 'working';
    }
    if (state === 'working') return 'working';
    if (roomId === 'room-coffee') return 'drink';
    if (roomId === 'room-break') return 'sit';
    if (state === 'idle' && safeString(agent?.intent) === 'task') return 'thinking';
    return 'idle';
}

function officeDraftAgentActivityLabel(agent, activity, total = 1) {
    if (activity === 'working') return 'working';
    if (activity === 'walking') return 'en route';
    if (activity === 'drink') return `${safeString(agent?.draftCommandPropLabel || 'Coke')} break`;
    if (activity === 'sit') return 'syncing';
    if (activity === 'paused') return 'paused';
    if (activity === 'talking') return 'talking';
    if (activity === 'dragging') return 'moving';
    if (activity === 'dropped') return 'placed';
    if (activity === 'thinking') return 'thinking';
    if (Number(total) > 1) return 'with team';
    return safeString(agent?.specialty || 'idle');
}

function officeDraftAgentAnimation(agent, activity, now = performance.now()) {
    if (activity === 'walking') return 'walking';
    if (activity === 'working') return safeString(agent?.intent) === 'task' ? 'working' : 'thinking';
    if (activity === 'drink') return 'drinking';
    if (activity === 'sit') return 'sitting';
    if (activity === 'talking') return 'talking';
    if (activity === 'paused') return 'paused';
    if (activity === 'dragging') return 'dragging';
    if (activity === 'dropped') return 'dropped';
    if (activity === 'thinking') return 'thinking';
    if (((Math.floor(((Number(now) || 0) / 2200) + (officeStableHash(agent?.id) % 7)) % 11) === 0)) return 'celebrating';
    return 'idle';
}

function officeDraftAgentSocialLine(agent, space, index, total, activity, now = performance.now()) {
    if (Number(total) < 2) return '';
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|social`);
    const cadence = activity === 'working' ? 2400 : 3000;
    const slot = Math.floor(((Number(now) || performance.now()) / cadence) + (seed % 5)) % 6;
    if (slot > 1) return '';
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const linesByRoom = {
        'room-engineering': ['Pushing a fix.', 'Running checks.', 'Need a review?'],
        'room-research': ['Found a source.', 'Cross-checking that.', 'I have notes.'],
        'room-content': ['Draft is moving.', 'Tightening copy.', 'Queueing assets.'],
        'room-ops': ['Watching deploys.', 'Logs look steady.', 'Checking alerts.'],
        'room-support': ['I can take that.', 'Reply drafted.', 'Ticket triaged.'],
        'room-coffee': ['Coke break.', 'Back in a sec.', 'Refueled.'],
        'room-break': ['Quick sync?', 'Resetting focus.', 'Ready after this.'],
        'room-pods': ['Deep work.', 'Holding context.', 'On the thread.'],
        'room-planning': ['Plan is clearer.', 'Next step?', 'I mapped it.'],
        'room-lobby': ['Available.', 'Who needs help?', 'Dispatch ready.'],
    };
    const lines = linesByRoom[roomId] || ['On it.', 'Syncing up.', 'I can help.'];
    return lines[(index + seed) % lines.length];
}

function officeDraftAgentPropLabel(agent) {
    const commandIntent = officeDraftAgentCommandActive(agent) ? safeString(agent?.draftInteractionIntent) : '';
    const commandProp = safeString(agent?.draftCommandPropLabel);
    if (commandIntent && commandProp) return commandProp;
    if (commandIntent === 'drink') return safeString(agent?.draftCommandPropLabel || 'Coke') || 'Coke';
    if (commandIntent === 'play') return 'game';
    const text = `${safeString(agent?.specialty)} ${safeString(agent?.personality)} ${safeString(agent?.name)}`.toLowerCase();
    if (/\b(code|software|debug|build|game|engineer)\b/.test(text)) return '</>';
    if (/\b(research|docs|document|source)\b/.test(text)) return 'doc';
    if (/\b(design|ui|visual|polish)\b/.test(text)) return 'ui';
    if (/\b(ops|deploy|reliability|monitor)\b/.test(text)) return 'ops';
    if (/\b(support|ticket|customer|review)\b/.test(text)) return 'msg';
    if (/\b(data|analysis|transform)\b/.test(text)) return 'db';
    if (/\b(plan|strategy|roadmap)\b/.test(text)) return 'map';
    if (/\b(content|video|social)\b/.test(text)) return 'cam';
    return 'ai';
}

function officeDraftAgentUiVisibility(state, agent, activity, selected, now = performance.now(), total = 1) {
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const hovered = safeString(state?.hoveredAgentId) === safeString(agent?.id);
    const clickedAt = Number(agent?.draftClickedAt) || 0;
    const dropUntil = Number(agent?.draftDropUntil) || 0;
    const clicked = clickedAt > 0 && clickedAt + 6600 > (Number(now) || performance.now());
    const dropped = dropUntil > 0 && dropUntil > (Number(now) || performance.now());
    const focused = Boolean(selected || hovered || clicked || dropped || agent?.draftMotion?.dragging);
    // A focused room should read as a staffed office, not as anonymous furniture.
    // At a legible room zoom there is enough space for the compact name labels;
    // keep the stricter density rule for overview and mobile zoom levels.
    const densityAllowsNames = Math.max(1, Number(total) || 1) <= 3 || zoom >= 0.72;
    const speechText = typeof officeVisibleSpeech === 'function' ? officeVisibleSpeech(agent, now) : safeString(agent?.speech);
    const speechContext = activity === 'talking' || activity === 'paused' || activity === 'dropped';
    return {
        focused,
        showName: focused || (densityAllowsNames && zoom >= OFFICE_DRAFT_AGENT_NAME_ZOOM),
        showStatus: false,
        showProp: false,
        showBubble: Boolean(safeString(speechText) && speechContext),
    };
}

function officeEnsureDraftPerformanceStyles() {
    if (document.getElementById('office-draft-performance-styles')) return;
    const style = document.createElement('style');
    style.id = 'office-draft-performance-styles';
    style.textContent = `
        body.office-active #te-space-root {
            display: none !important;
        }
        body.office-active .app-layout,
        body.office-active .main-content {
            background: #050a12 !important;
        }
        #officeWorkspace [data-office-map-plane="1"],
        #officeWorkspace [data-office-map-plane="1"] * {
            animation: none !important;
            backdrop-filter: none !important;
            box-shadow: none !important;
            filter: none !important;
            text-shadow: none !important;
            transition: none !important;
        }
        #officeWorkspace [data-office-map-plane="1"] [data-office-draft-agent-id] {
            contain: layout style;
            overflow: visible !important;
            transition: transform 64ms linear, border-color 120ms ease !important;
        }
        #officeWorkspace [data-office-map-plane="1"] [data-office-agent-overview="1"] {
            width: 62px !important;
            min-height: 62px !important;
            border-radius: 999px !important;
            background: var(--agent-primary) !important;
            outline: none;
            pointer-events: auto !important;
            transition: transform 140ms linear, outline-color 120ms ease !important;
        }
        #officeWorkspace [data-office-map-plane="1"] [data-office-agent-overview="1"] > span {
            display: none !important;
        }
    `;
    document.head.appendChild(style);
}

function officeEnsureDraftAgentMotionStyles() {
    if (document.getElementById('office-draft-agent-motion-styles')) return;
    const style = document.createElement('style');
    style.id = 'office-draft-agent-motion-styles';
    style.textContent = `
        @keyframes officeDraftAgentIdleBreath { 0%,100% { transform: translateY(0) scale(1.28); } 50% { transform: translateY(-3px) scale(1.29); } }
        @keyframes officeDraftAgentWalkBob { 0%,100% { transform: translateY(0) scale(1.28); } 50% { transform: translateY(-4px) scale(1.28); } }
        @keyframes officeDraftAgentLegWalkLeft { 0%,100% { transform: translateY(0) rotate(-8deg); } 50% { transform: translateY(1px) rotate(9deg); } }
        @keyframes officeDraftAgentLegWalkRight { 0%,100% { transform: translateY(1px) rotate(9deg); } 50% { transform: translateY(0) rotate(-8deg); } }
        @keyframes officeDraftAgentWorkTap { 0%,100% { transform: translateY(0) scale(1.28); filter: saturate(1); } 35% { transform: translateY(1px) scale(1.27); filter: saturate(1.25); } 70% { transform: translateY(-2px) scale(1.29); } }
        @keyframes officeDraftAgentDrinkSip { 0%,100% { transform: rotate(0deg) scale(1.28); } 42% { transform: rotate(-5deg) translateY(-4px) scale(1.28); } 60% { transform: rotate(3deg) scale(1.28); } }
        @keyframes officeDraftAgentSitSettle { 0%,100% { transform: translateY(9px) scale(1.14,0.92); } 50% { transform: translateY(6px) scale(1.16,0.9); } }
        @keyframes officeDraftAgentPauseLook { 0%,100% { transform: scale(1.28) rotate(0deg); } 45% { transform: scale(1.28) rotate(-3deg); } 70% { transform: scale(1.28) rotate(3deg); } }
        @keyframes officeDraftAgentTalkBounce { 0%,100% { transform: translateY(0) scale(1.28); } 30% { transform: translateY(-5px) scale(1.31); } 62% { transform: translateY(-2px) scale(1.29); } }
        @keyframes officeDraftAgentDragHover { 0%,100% { transform: translateY(-12px) scale(1.32) rotate(-2deg); } 50% { transform: translateY(-18px) scale(1.34) rotate(2deg); } }
        @keyframes officeDraftAgentDropPop { 0% { transform: translateY(-16px) scale(1.36); } 55% { transform: translateY(2px) scale(1.24); } 100% { transform: translateY(0) scale(1.28); } }
        @keyframes officeDraftAgentThinkGlow { 0%,100% { filter: drop-shadow(0 0 0 rgba(140,190,255,0)); transform: scale(1.28); } 50% { filter: drop-shadow(0 0 12px var(--agent-glow)); transform: scale(1.3); } }
        @keyframes officeDraftAgentCelebrate { 0%,100% { transform: translateY(0) scale(1.28) rotate(0deg); } 25% { transform: translateY(-9px) scale(1.31) rotate(-5deg); } 55% { transform: translateY(-4px) scale(1.3) rotate(5deg); } }
        @keyframes officeDraftAgentBubblePop { 0% { opacity:0; transform:translateX(0) translateY(6px) scale(.92); } 100% { opacity:1; transform:translateX(0) translateY(0) scale(1); } }
        [data-office-draft-agent-id] [data-office-draft-agent-robot] { animation: officeDraftAgentIdleBreath 2.8s ease-in-out infinite; }
        [data-office-agent-animation="walking"] [data-office-draft-agent-robot] { animation: officeDraftAgentWalkBob 0.92s ease-in-out infinite; }
        [data-office-agent-animation="walking"] .office-agent-leg-left { animation: officeDraftAgentLegWalkLeft 0.72s ease-in-out infinite; transform-origin:center top; }
        [data-office-agent-animation="walking"] .office-agent-leg-right { animation: officeDraftAgentLegWalkRight 0.72s ease-in-out infinite; transform-origin:center top; }
        [data-office-agent-animation="working"] [data-office-draft-agent-robot] { animation: officeDraftAgentWorkTap 0.82s ease-in-out infinite; }
        [data-office-agent-animation="drinking"] [data-office-draft-agent-robot] { animation: officeDraftAgentDrinkSip 1.35s ease-in-out infinite; }
        [data-office-agent-animation="sitting"] [data-office-draft-agent-robot] { animation: officeDraftAgentSitSettle 2.4s ease-in-out infinite; }
        [data-office-agent-animation="paused"] [data-office-draft-agent-robot] { animation: officeDraftAgentPauseLook 2.1s ease-in-out infinite; }
        [data-office-agent-animation="talking"] [data-office-draft-agent-robot] { animation: officeDraftAgentTalkBounce 0.72s ease-in-out infinite; }
        [data-office-agent-animation="dragging"] [data-office-draft-agent-robot] { animation: officeDraftAgentDragHover 0.75s ease-in-out infinite; }
        [data-office-agent-animation="dropped"] [data-office-draft-agent-robot] { animation: officeDraftAgentDropPop 0.52s cubic-bezier(.2,.9,.2,1.1) both; }
        [data-office-agent-animation="thinking"] [data-office-draft-agent-robot] { animation: officeDraftAgentThinkGlow 1.65s ease-in-out infinite; }
        [data-office-agent-animation="celebrating"] [data-office-draft-agent-robot] { animation: officeDraftAgentCelebrate 1s ease-in-out infinite; }
        [data-office-agent-animation="talking"] [data-office-draft-agent-bubble],
        [data-office-agent-animation="dropped"] [data-office-draft-agent-bubble] { animation: officeDraftAgentBubblePop 180ms ease-out both; }
    `;
    document.head.appendChild(style);
}

function officeDraftAgentClickLine(agent, space) {
    const room = safeString(space?.name || officeRoomById(officeDraftNormalizeRoomId(space?.roomId, space?.id))?.label || 'the office');
    const lines = [
        `Paused in ${room}. What do you need?`,
        `I stopped here. I can take a task or move rooms.`,
        `I am listening from ${room}.`,
        `Ready. Send me a task or drag me somewhere else.`,
    ];
    return lines[officeStableHash(`${safeString(agent?.id)}|click`) % lines.length];
}

function officeDraftBuildAgentConversationPrompt(agent, space) {
    const agentName = safeString(agent?.name) || 'Agent';
    const roomName = safeString(space?.name || officeRoomById(officeDraftNormalizeRoomId(space?.roomId, space?.id))?.label || 'the office');
    const specialty = safeString(agent?.specialty) || 'Generalist';
    const personality = safeString(agent?.personality) || 'Helpful, direct, and persistent.';
    const activeTask = officeState?.tasks?.find((entry) => (
        safeString(entry?.assignedAgentId) === safeString(agent?.id)
        && safeString(entry?.status) !== 'done'
    ));
    const memoryLine = safeString(activeTask?.title || agent?.lastOfficeActionMemory || agent?.lastMissionSummary || agent?.lastTaskSummary || 'No recent task yet.');
    const commandLine = officeDraftAgentCommandActive(agent)
        ? safeString(agent?.lastOfficeCommandSummary || 'Following the user office command.')
        : 'No direct office command active.';
    return [
        `You are speaking as the persistent Thomas office agent named ${agentName}.`,
        `Stay in character as this robot, not as generic Thomas.`,
        `Specialty: ${specialty}.`,
        `Personality: ${personality}.`,
        `Current office room: ${roomName}.`,
        `Recent task memory: ${memoryLine}.`,
        `Current office action: ${commandLine}.`,
        'This is the office conversation layer, separate from task routing. Reply as this agent in first person and keep the answer concise.',
    ].join('\n');
}

function officeDraftPrimeAgentConversation(agent, space, now = performance.now()) {
    if (!agent) return;
    const promptPrefix = officeDraftBuildAgentConversationPrompt(agent, space);
    agent.lastOfficeConversationPrompt = promptPrefix;
    agent.lastOfficeConversationAt = now;
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.chat_prompt', {
            agentId: safeString(agent.id),
            roomId: officeDraftNormalizeRoomId(space?.roomId, space?.id),
            prompt: promptPrefix,
        }, now);
    }
}


