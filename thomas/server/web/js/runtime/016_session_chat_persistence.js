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
        safeString(modelSelector?.value)
        || safeString(setupProviderSelector?.value)
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
    const rawModel = safeString(session?.model) || activeProfileNameForPersistence();
    const model = rawModel ? formatProviderDisplay(rawModel, { compact: false }) : '';
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
    ];
    sidebarSessions.sort((a, b) => Number(b?.updatedAt || 0) - Number(a?.updatedAt || 0));
}

function syncActiveChatSidebarEntry({ touchUpdatedAt = true } = {}) {
    const chatId = safeString(activeChatId) || safeString(sessionId);
    if (!chatId) return;
    saveStoredActiveChatId(chatId);
    const normalizedMessages = normalizeConversationHistory(chatHistory);
    const now = Date.now();
    const existing = sidebarSessions.find((s) => safeString(s?.id) === chatId) || null;
    const resolvedUpdatedAt = touchUpdatedAt
        ? now
        : Number(existing?.updatedAt || existing?.createdAt || now);
    const payload = {
        id: chatId,
        title: deriveChatTitleFromMessages(normalizedMessages),
        messages: normalizedMessages,
        createdAt: Number(existing?.createdAt || now),
        updatedAt: resolvedUpdatedAt,
        pinned: Boolean(existing?.pinned),
        sessionId: safeString(sessionId) || null,
        model: activeProfileNameForPersistence(),
    };
    upsertSidebarSession(payload);
    rebuildChatHistorySelector();
    renderSidebarChatList();
}

function buildPersistedChatPayload() {
    const chatId = safeString(activeChatId) || safeString(sessionId);
    if (!chatId) return null;
    const normalizedMessages = normalizeConversationHistory(chatHistory);
    const now = Date.now();
    const existing = sidebarSessions.find((s) => safeString(s?.id) === chatId) || null;
    return {
        id: chatId,
        title: deriveChatTitleFromMessages(normalizedMessages),
        messages: normalizedMessages,
        createdAt: Number(existing?.createdAt || now),
        updatedAt: now,
        pinned: Boolean(existing?.pinned),
        sessionId: safeString(sessionId) || null,
        model: activeProfileNameForPersistence(),
    };
}

async function persistActiveChat({ quiet = true } = {}) {
    const payload = buildPersistedChatPayload();
    if (!payload) return false;
    activeChatId = safeString(payload.id);
    chatPersistQueued = true;
    if (chatPersistInFlight) return true;
    chatPersistInFlight = true;

    let ok = true;
    try {
        while (chatPersistQueued) {
            chatPersistQueued = false;
            const nextPayload = buildPersistedChatPayload();
            if (!nextPayload) continue;
            try {
                const res = await fetch(`/api/chats/${encodeURIComponent(nextPayload.id)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(nextPayload),
                });
                if (!res.ok) {
                    const details = safeString(await res.text()) || `HTTP ${res.status}`;
                    throw new Error(details);
                }
                const body = await res.json();
                const persisted = mapPersistedChatToSidebarSession(body?.chat) || mapPersistedChatToSidebarSession(nextPayload);
                if (persisted) {
                    upsertSidebarSession(persisted);
                    rebuildChatHistorySelector();
                    renderSidebarChatList();
                    updateDebugDockSnapshot();
                }
            } catch (error) {
                ok = false;
                console.error('Failed to persist chat', error);
                if (!quiet) {
                    notifyUser(`Could not save chat: ${safeString(error?.message) || 'unknown error'}`, {
                        tone: 'warning',
                        durationMs: 2600,
                        debugKind: 'error',
                    });
                }
            }
        }
    } finally {
        chatPersistInFlight = false;
    }
    return ok;
}

// 
//   VIRTUAL OFFICE                                                         
//   Office sim, agent movement, room rendering, minimap, sprite painting   
// 

function officeClamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function officeRandomRange(min, max) {
    return min + (Math.random() * (max - min));
}

function officeStableHash(valueRaw) {
    const input = safeString(valueRaw);
    let hash = 2166136261;
    for (let i = 0; i < input.length; i += 1) {
        hash ^= input.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
}

function officeChance(probability) {
    return Math.random() < probability;
}

function officeAgentTintFromColor(colorRaw) {
    if (!/^#[0-9a-f]{6}$/i.test(safeString(colorRaw))) return 'blue';
    const rgb = officeHexToRgb(colorRaw);
    const { r, g, b } = rgb;
    if (r > 210 && b > 190 && g < 185) return 'pink';
    if (r > 188 && g > 150 && b < 130) return 'orange';
    if (r > 180 && g > 180 && b > 210) return 'purple';
    if (r > 210 && g > 205 && b < 150) return 'yellow';
    if (g >= r && g >= b) return 'green';
    return 'blue';
}

function officeApplyDefaultAgentStyleDiversification(agents, prefsRaw) {
    if (!Array.isArray(agents) || !agents.length) return;
    if (prefsRaw && typeof prefsRaw === 'object' && Object.keys(prefsRaw).length > 0) {
        return;
    }
    const colorPool = [...OFFICE_AGENT_STYLE_COLOR_POOL];
    for (let i = colorPool.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [colorPool[i], colorPool[j]] = [colorPool[j], colorPool[i]];
    }

    agents.forEach((agent, index) => {
        if (!agent) return;
        const color = colorPool[index % colorPool.length] || agent.color;
        agent.color = /^#[0-9a-f]{6}$/i.test(safeString(color)) ? color : agent.color;
        // Default agents to no costume — the random cap/visor/bowtie overlays
        // read as visual noise at office scale. Colour variety stays; users can
        // still opt into a costume per-agent from the roster panel.
        agent.costume = 'none';
        agent.tint = officeAgentTintFromColor(agent.color);
    });
}

function officePick(items) {
    if (!Array.isArray(items) || items.length === 0) return '';
    const index = Math.floor(Math.random() * items.length);
    return items[index];
}

function officeAgentHandle(name) {
    return safeString(name).toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function officeTaskTitle(text) {
    const normalized = safeString(text).replace(/\s+/g, ' ').trim();
    if (!normalized) return 'Untitled task';
    const firstSentence = normalized.split(/[.!?]/)[0];
    return firstSentence.length > 68 ? `${firstSentence.slice(0, 65)}...` : firstSentence;
}

function officePersonaBucket(agent) {
    const tint = safeString(agent?.tint).toLowerCase();
    if (Object.prototype.hasOwnProperty.call(OFFICE_PERSONA_LIBRARY, tint)) {
        return tint;
    }
    return 'default';
}

function officePersonaLines(agent, channelRaw) {
    const channel = safeString(channelRaw);
    const bucket = officePersonaBucket(agent);
    const persona = OFFICE_PERSONA_LIBRARY[bucket] || OFFICE_PERSONA_LIBRARY.default;
    const fallback = OFFICE_PERSONA_LIBRARY.default || {};
    const scoped = Array.isArray(persona[channel]) ? persona[channel] : [];
    if (scoped.length) return scoped;
    const defaultScoped = Array.isArray(fallback[channel]) ? fallback[channel] : [];
    if (defaultScoped.length) return defaultScoped;
    if (channel === 'working') return OFFICE_DIALOGUE.working;
    if (channel === 'break') return OFFICE_DIALOGUE.break;
    if (channel === 'collision') return OFFICE_DIALOGUE.collision;
    return OFFICE_DIALOGUE.working;
}

function officePickPersonaLine(agent, channelRaw, fallbackLine = '') {
    const options = officePersonaLines(agent, channelRaw);
    const picked = officePick(options);
    if (picked) return picked;
    return safeString(fallbackLine) || officePick(OFFICE_DIALOGUE.working);
}

function officeSpeechRevealMsForText(textRaw) {
    const text = safeString(textRaw);
    if (!text) return 240;
    const punctuationCount = (text.match(/[,:;.!?]/g) || []).length;
    const longWordCount = text
        .split(/\s+/)
        .filter((token) => token.length >= 8)
        .length;
    const base = (text.length * 22) + (punctuationCount * 46) + (longWordCount * 14);
    return officeClamp(base, 220, 2200);
}

function officeBanterForAgent(agent, contextRaw = 'ambient', detail = {}) {
    const context = safeString(contextRaw).toLowerCase();
    const roomTheme = safeString(detail?.roomTheme).toLowerCase();
    const taskTitle = safeString(detail?.taskTitle).toLowerCase();

    if (context === 'collision') {
        return officePickPersonaLine(agent, 'collision', officePick(OFFICE_DIALOGUE.collision));
    }
    if (context === 'break') {
        return officePickPersonaLine(agent, 'break', officePick(OFFICE_DIALOGUE.break));
    }
    if (context === 'task_pickup' || context === 'task_active') {
        if (roomTheme === 'engineering') {
            return officePick([
                'Routing to Software Lab now.',
                'Engineering lane locked in.',
                'Heading to code zone.',
            ]);
        }
        if (roomTheme === 'content') {
            return officePick([
                'Content Studio route confirmed.',
                'Video/edit pipeline in motion.',
                'Moving to content lane.',
            ]);
        }
        if (roomTheme === 'research') {
            return officePick([
                'Research Bay route confirmed.',
                'Gathering source-backed signal.',
                'Investigation mode active.',
            ]);
        }
        return officePickPersonaLine(agent, 'working', officePick(OFFICE_DIALOGUE.pickup));
    }
    if (context === 'task_done') {
        if (taskTitle.includes('benchmark')) {
            return officePick([
                'Benchmarks wrapped and readable.',
                'Performance pass complete.',
            ]);
        }
        if (taskTitle.includes('deploy')) {
            return officePick([
                'Deploy lane complete.',
                'Release task wrapped.',
            ]);
        }
        return officePick(OFFICE_DIALOGUE.complete);
    }
    if (context === 'social_lead') {
        return officePickPersonaLine(agent, 'socialLead', 'Quick sync?');
    }
    if (context === 'social_reply') {
        return officePickPersonaLine(agent, 'socialReply', 'Copy that.');
    }
    if (roomTheme === 'coffee' || roomTheme === 'break') {
        return officePickPersonaLine(agent, 'break', officePick(OFFICE_DIALOGUE.break));
    }
    return officePickPersonaLine(agent, 'working', officePick(OFFICE_DIALOGUE.working));
}

function officePulseHaptic(pattern = 12) {
    const now = performance.now();
    if ((now - officeLastHapticAt) < OFFICE_HAPTIC_COOLDOWN_MS) return;
    officeLastHapticAt = now;
    try {
        if (typeof navigator !== 'undefined' && navigator && typeof navigator.vibrate === 'function') {
            navigator.vibrate(pattern);
        }
    } catch {
        // Haptics are best-effort only.
    }
}

function officeHexToRgb(hex) {
    const normalized = safeString(hex).replace('#', '');
    if (!/^[0-9a-f]{6}$/i.test(normalized)) {
        return { r: 154, g: 216, b: 255 };
    }
    return {
        r: Number.parseInt(normalized.slice(0, 2), 16),
        g: Number.parseInt(normalized.slice(2, 4), 16),
        b: Number.parseInt(normalized.slice(4, 6), 16),
    };
}

function officeRgbToHex(rgb) {
    const toHex = (value) => officeClamp(Math.round(value), 0, 255).toString(16).padStart(2, '0');
    return `#${toHex(rgb.r)}${toHex(rgb.g)}${toHex(rgb.b)}`;
}

function officeMixHex(baseHex, targetHex, targetWeight = 0.2) {
    const base = officeHexToRgb(baseHex);
    const target = officeHexToRgb(targetHex);
    const w = officeClamp(Number(targetWeight) || 0, 0, 1);
    return officeRgbToHex({
        r: (base.r * (1 - w)) + (target.r * w),
        g: (base.g * (1 - w)) + (target.g * w),
        b: (base.b * (1 - w)) + (target.b * w),
    });
}

function officeAgentPalette(agent) {
    const primary = /^#[0-9a-f]{6}$/i.test(safeString(agent?.color))
        ? safeString(agent.color)
        : '#9ad8ff';
    return {
        primary,
        secondary: officeMixHex(primary, '#0d1117', 0.22),
        glow: officeMixHex(primary, '#58a6ff', 0.34),
    };
}

function officeRoomById(roomId) {
    if (!officeState || !officeState.roomById) return null;
    return officeState.roomById.get(roomId) || null;
}

function officeGetAgentById(agentId) {
    if (!officeState) return null;
    return officeState.agents.find((agent) => agent.id === agentId) || null;
}

function officeCurrentRoomForAgent(agent) {
    if (!officeState || !agent) return null;
    return officeState.rooms.find((room) => (
        officeRoomContainsPoint(room, agent.x, agent.y)
    )) || null;
}

function officeRoomContainsPoint(room, x, y) {
    if (!room) return false;
    return x >= room.x
        && x <= room.x + room.w
        && y >= room.y
        && y <= room.y + room.h;
}

function officeRoomDoorEdge(room) {
    if (!room) return 'bottom';
    const doorX = Number(room.doorX) || (room.x + (room.w / 2));
    const doorY = Number(room.doorY) || (room.y + room.h);
    const distances = {
        top: Math.abs(doorY - room.y),
        bottom: Math.abs(doorY - (room.y + room.h)),
        left: Math.abs(doorX - room.x),
        right: Math.abs(doorX - (room.x + room.w)),
    };
    return Object.entries(distances).sort((a, b) => a[1] - b[1])[0]?.[0] || 'bottom';
}

function officeRoomInteriorInset(room) {
    if (!room) return 1.2;
    return officeClamp(Math.min(room.w, room.h) * 0.15, 1.0, 2.6);
}

function officePointInCorridor(x, y, padding = 0.12) {
    if (!officeState || !Array.isArray(officeState.corridors)) return false;
    return officeState.corridors.some((corridor) => (
        x >= corridor.x - padding
        && x <= corridor.x + corridor.w + padding
        && y >= corridor.y - padding
        && y <= corridor.y + corridor.h + padding
    ));
}

function officePointInRoomInterior(room, x, y) {
    if (!room) return false;
    const inset = officeRoomInteriorInset(room);
    return x >= room.x + inset
        && x <= room.x + room.w - inset
        && y >= room.y + inset
        && y <= room.y + room.h - inset;
}

function officePointInRoomDoorThreshold(room, x, y) {
    if (!room) return false;
    const doorX = Number(room.doorX) || (room.x + (room.w / 2));
    const doorY = Number(room.doorY) || (room.y + room.h);
    const edge = officeRoomDoorEdge(room);
    const doorWidth = officeClamp(Math.min(room.w, room.h) * 0.22, 1.55, 4.4);
    const thresholdDepth = officeClamp(Math.min(room.w, room.h) * 0.13, 0.72, 1.8);

    if (edge === 'top') {
        return x >= doorX - (doorWidth / 2)
            && x <= doorX + (doorWidth / 2)
            && y >= room.y - thresholdDepth
            && y <= room.y + thresholdDepth;
    }
    if (edge === 'bottom') {
        return x >= doorX - (doorWidth / 2)
            && x <= doorX + (doorWidth / 2)
            && y >= room.y + room.h - thresholdDepth
            && y <= room.y + room.h + thresholdDepth;
    }
    if (edge === 'left') {
        return y >= doorY - (doorWidth / 2)
            && y <= doorY + (doorWidth / 2)
            && x >= room.x - thresholdDepth
            && x <= room.x + thresholdDepth;
    }
    return y >= doorY - (doorWidth / 2)
        && y <= doorY + (doorWidth / 2)
        && x >= room.x + room.w - thresholdDepth
        && x <= room.x + room.w + thresholdDepth;
}

function officeIsWalkablePoint(x, y) {
    if (!officeState) return true;
    if (x < 0 || x > 100 || y < 0 || y > 100) return false;
    if (officePointInCorridor(x, y, 0.14)) return true;
    return officeState.rooms.some((room) => (
        officePointInRoomInterior(room, x, y)
        || officePointInRoomDoorThreshold(room, x, y)
    ));
}

function officeNearestWalkablePoint(seedX, seedY, fallbackX = seedX, fallbackY = seedY) {
    if (!officeState) return { x: seedX, y: seedY };
    const startX = officeClamp(Number(seedX) || 50, 0, 100);
    const startY = officeClamp(Number(seedY) || 50, 0, 100);
    if (officeIsWalkablePoint(startX, startY)) {
        return { x: startX, y: startY };
    }

    let bestPoint = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    const scanDistances = [0.2, 0.4, 0.7, 1.1, 1.6, 2.1, 2.8, 3.5, 4.8, 6.2, 8.4, 10.8];
    for (let i = 0; i < scanDistances.length; i += 1) {
        const radius = scanDistances[i];
        for (let angle = 0; angle < 360; angle += 18) {
            const rad = (angle * Math.PI) / 180;
            const x = officeClamp(startX + (Math.cos(rad) * radius), 0, 100);
            const y = officeClamp(startY + (Math.sin(rad) * radius), 0, 100);
            if (!officeIsWalkablePoint(x, y)) continue;
            const dist = Math.hypot(x - startX, y - startY);
            if (dist < bestDistance) {
                bestDistance = dist;
                bestPoint = { x, y };
            }
        }
        if (bestPoint) break;
    }

    if (bestPoint) return bestPoint;
    const safeFallbackX = officeClamp(Number(fallbackX) || startX, 0, 100);
    const safeFallbackY = officeClamp(Number(fallbackY) || startY, 0, 100);
    if (officeIsWalkablePoint(safeFallbackX, safeFallbackY)) {
        return { x: safeFallbackX, y: safeFallbackY };
    }
    const nearestNodeId = officeFindNearestNode(officeState.navMap, safeFallbackX, safeFallbackY);
    const nearestNode = officeState.navMap.get(nearestNodeId);
    if (nearestNode) {
        return { x: nearestNode.x, y: nearestNode.y };
    }
    return { x: safeFallbackX, y: safeFallbackY };
}

function officeConstrainWalkableMove(agent, fromX, fromY, toX, toY) {
    if (!officeState || !agent || agent.state === 'runaway') {
        return { x: toX, y: toY };
    }
    if (officeIsWalkablePoint(toX, toY)) {
        return { x: toX, y: toY };
    }

    const segmentLength = Math.hypot((toX - fromX), (toY - fromY));
    if (segmentLength > 0.001) {
        const steps = Math.max(2, Math.ceil(segmentLength / 0.38));
        let lastWalkable = null;
        for (let i = 1; i <= steps; i += 1) {
            const ratio = i / steps;
            const sampleX = fromX + ((toX - fromX) * ratio);
            const sampleY = fromY + ((toY - fromY) * ratio);
            if (officeIsWalkablePoint(sampleX, sampleY)) {
                lastWalkable = { x: sampleX, y: sampleY };
            } else {
                break;
            }
        }
        if (lastWalkable) {
            return lastWalkable;
        }
    }

    if (officeIsWalkablePoint(toX, fromY)) {
        return { x: toX, y: fromY };
    }
    if (officeIsWalkablePoint(fromX, toY)) {
        return { x: fromX, y: toY };
    }

    const midX = fromX + ((toX - fromX) * 0.6);
    const midY = fromY + ((toY - fromY) * 0.6);
    if (officeIsWalkablePoint(midX, midY)) {
        return { x: midX, y: midY };
    }

    return officeNearestWalkablePoint(midX, midY, fromX, fromY);
}

function officeConnectNavNodes(navMap, fromId, toId) {
    const from = navMap.get(fromId);
    const to = navMap.get(toId);
    if (!from || !to || fromId === toId) return;
    from.links.add(toId);
    to.links.add(fromId);
}

function officeRoomSlotLayout(room) {
    if (!room) return [];
    const basePattern = [
        [0.30, 0.32],
        [0.50, 0.32],
        [0.70, 0.32],
        [0.30, 0.50],
        [0.50, 0.50],
        [0.70, 0.50],
        [0.30, 0.68],
        [0.50, 0.68],
        [0.70, 0.68],
        [0.18, 0.50],
        [0.82, 0.50],
        [0.50, 0.20],
        [0.50, 0.80],
    ];
    const area = (Number(room.w) || 0) * (Number(room.h) || 0);
    let slotCount = 3;
    if (area >= 220) slotCount = 5;
    if (area >= 420) slotCount = 7;
    if (area >= 760) slotCount = 9;
    if (safeString(room.id) === 'room-lobby') slotCount = 10;

    const marginX = officeClamp((Number(room.w) || 0) * 0.16, 1.2, 3.2);
    const marginY = officeClamp((Number(room.h) || 0) * 0.16, 1.2, 3.2);
    const minX = room.x + marginX;
    const maxX = room.x + room.w - marginX;
    const minY = room.y + marginY;
    const maxY = room.y + room.h - marginY;

    return basePattern.slice(0, slotCount).map(([rx, ry], index) => ({
        id: `${room.id}:slot:${index + 1}`,
        x: officeClamp(room.x + (room.w * rx), minX, maxX),
        y: officeClamp(room.y + (room.h * ry), minY, maxY),
    }));
}

function officeBuildNavGraph(rooms) {
    const navMap = new Map();
    const roomNav = new Map();

    OFFICE_HALL_NODES.forEach((node) => {
        navMap.set(node.id, { ...node, links: new Set() });
    });
    OFFICE_HALL_EDGES.forEach(([fromId, toId]) => {
        officeConnectNavNodes(navMap, fromId, toId);
    });

    rooms.forEach((room) => {
        const centerNodeId = `${room.id}:center`;
        const doorNodeId = `${room.id}:door`;
        const hallStubId = `${room.id}:hall`;
        const centerX = room.x + (room.w / 2);
        const centerY = room.y + (room.h / 2);
        const doorX = Number(room.doorX) || centerX;
        const doorY = Number(room.doorY) || (room.y + room.h);
        const hallNode = navMap.get(room.hallId) || OFFICE_HALL_NODES[0];
        const stubX = doorX;
        const stubY = hallNode ? hallNode.y : doorY;

        navMap.set(centerNodeId, { id: centerNodeId, x: centerX, y: centerY, links: new Set() });
        navMap.set(doorNodeId, { id: doorNodeId, x: doorX, y: doorY, links: new Set() });
        navMap.set(hallStubId, { id: hallStubId, x: stubX, y: stubY, links: new Set() });
        officeConnectNavNodes(navMap, centerNodeId, doorNodeId);
        officeConnectNavNodes(navMap, doorNodeId, hallStubId);
        if (hallNode) {
            officeConnectNavNodes(navMap, hallStubId, hallNode.id);
        }
        const roomSlots = officeRoomSlotLayout(room);
        roomSlots.forEach((slot) => {
            navMap.set(slot.id, { id: slot.id, x: slot.x, y: slot.y, links: new Set() });
            officeConnectNavNodes(navMap, centerNodeId, slot.id);
        });

        roomNav.set(room.id, {
            centerNodeId,
            doorNodeId,
            hallStubId,
            hallId: hallNode?.id || '',
            slotNodeIds: roomSlots.map((slot) => slot.id),
        });
    });

    return { navMap, roomNav };
}

function officeRefreshNavGraph() {
    if (!officeState) return;
    const { navMap, roomNav } = officeBuildNavGraph(officeState.rooms);
    officeState.navMap = navMap;
    officeState.roomNav = roomNav;
    officeState.agents.forEach((agent) => {
        if (!agent || agent.state === 'runaway') return;
        agent.currentNodeId = officeFindNearestNode(navMap, agent.x, agent.y);
    });
}

function officeFindNearestNode(navMap, x, y) {
    let best = '';
    let bestDistance = Number.POSITIVE_INFINITY;
    navMap.forEach((node, nodeId) => {
        if (!node) return;
        const distance = Math.hypot(node.x - x, node.y - y);
        if (distance < bestDistance) {
            bestDistance = distance;
            best = nodeId;
        }
    });
    return best;
}

function officeFindPath(navMap, startId, endId) {
    const start = safeString(startId);
    const end = safeString(endId);
    if (!start || !end || !navMap.has(start) || !navMap.has(end)) return [];
    if (start === end) return [start];

    const queue = [start];
    const visited = new Set([start]);
    const parent = new Map();

    while (queue.length) {
        const current = queue.shift();
        if (!current) continue;
        const node = navMap.get(current);
        if (!node) continue;
        if (current === end) break;
        node.links.forEach((nextId) => {
            if (visited.has(nextId)) return;
            visited.add(nextId);
            parent.set(nextId, current);
            queue.push(nextId);
        });
    }

    if (!visited.has(end)) return [];
    const path = [end];
    let cursor = end;
    while (parent.has(cursor)) {
        cursor = parent.get(cursor);
        path.push(cursor);
    }
    path.reverse();
    return path;
}

function officeBuildRoutePoints(navMap, nodeIds) {
    return nodeIds
        .map((nodeId) => {
            const node = navMap.get(nodeId);
            if (!node) return null;
            return { nodeId, x: node.x, y: node.y };
        })
        .filter(Boolean);
}

function officeApplyLaneBiasToRoute(agent, routePoints) {
    if (!agent || !Array.isArray(routePoints) || routePoints.length < 2) {
        return Array.isArray(routePoints) ? routePoints : [];
    }
    const laneBias = officeClamp(Number(agent.laneBias) || 0, -0.8, 0.8);
    if (Math.abs(laneBias) < 0.01) {
        return routePoints;
    }

    return routePoints.map((point, index) => {
        const prev = routePoints[index - 1] || null;
        const next = routePoints[index + 1] || null;
        const refA = prev || point;
        const refB = next || point;
        const dirX = refB.x - refA.x;
        const dirY = refB.y - refA.y;
        const dirLen = Math.hypot(dirX, dirY);
        if (dirLen <= 0.001) return { ...point };

        const perpX = -dirY / dirLen;
        const perpY = dirX / dirLen;
        const rawOffset = laneBias * (index === 0 || index === routePoints.length - 1 ? 0.34 : 0.62);
        const candidate = {
            ...point,
            x: officeClamp(point.x + (perpX * rawOffset), 3, 97),
            y: officeClamp(point.y + (perpY * rawOffset), 7, 92),
        };
        if (index === 0 || index === routePoints.length - 1) {
            return candidate;
        }
        const safePoint = officeNearestWalkablePoint(candidate.x, candidate.y, point.x, point.y);
        return {
            ...candidate,
            x: officeClamp(safePoint.x, 3, 97),
            y: officeClamp(safePoint.y, 7, 92),
        };
    });
}

function officeSetAgentRoute(agent, routePoints, destinationNodeId, { intent = 'wander', speed = 0 } = {}) {
    if (!agent || !Array.isArray(routePoints) || routePoints.length === 0) return false;
    const laneRoute = officeApplyLaneBiasToRoute(agent, routePoints);
    const waypoints = laneRoute.slice(1);
    const first = laneRoute[0];
    if (!first) return false;
    agent.routeWaypoints = waypoints;
    agent.routeDestinationNodeId = safeString(destinationNodeId);
    officeSetAgentTarget(agent, first.x, first.y, { intent, speed, preserveRoute: true });
    return true;
}

function officeRouteAgentToNode(agent, destinationNodeId, { intent = 'wander', speed = 0 } = {}) {
    if (!officeState || !agent) return false;
    const navMap = officeState.navMap;
    if (!navMap || !safeString(destinationNodeId) || !navMap.has(destinationNodeId)) return false;

    const startNodeId = safeString(agent.currentNodeId) && navMap.has(agent.currentNodeId)
        ? agent.currentNodeId
        : officeFindNearestNode(navMap, agent.x, agent.y);
    const pathNodeIds = officeFindPath(navMap, startNodeId, destinationNodeId);
    if (!pathNodeIds.length) return false;

    const routePoints = officeBuildRoutePoints(navMap, pathNodeIds);
    if (!routePoints.length) return false;
    if (routePoints.length === 1) {
        agent.currentNodeId = destinationNodeId;
        return true;
    }

    return officeSetAgentRoute(agent, routePoints.slice(1), destinationNodeId, { intent, speed });
}

function officeSelectRoomDestinationNode(roomId, agent, { intent = 'wander' } = {}) {
    if (!officeState) return '';
    const nav = officeState.roomNav?.get(roomId);
    if (!nav) return '';
    const slotNodeIds = Array.isArray(nav.slotNodeIds) ? nav.slotNodeIds.filter((nodeId) => officeState.navMap.has(nodeId)) : [];
    if (!slotNodeIds.length) {
        return nav.centerNodeId;
    }

    const keySeed = `${safeString(agent?.id)}|${safeString(intent)}|${safeString(agent?.taskId)}`;
    const startIndex = officeStableHash(keySeed) % slotNodeIds.length;
    const scored = slotNodeIds.map((nodeId, index) => {
        const node = officeState.navMap.get(nodeId);
        if (!node) {
            return { nodeId, score: Number.POSITIVE_INFINITY };
        }
        let occupancy = 0;
        officeState.agents.forEach((other) => {
            if (!other || other.state === 'runaway') return;
            if (safeString(other.id) === safeString(agent?.id)) return;
            const claimed = safeString(other.routeDestinationNodeId);
            const current = safeString(other.currentNodeId);
            if (claimed === nodeId || current === nodeId) {
                occupancy += 1;
            }
        });

        const distancePenalty = agent
            ? Math.hypot(node.x - (Number(agent.x) || node.x), node.y - (Number(agent.y) || node.y)) * 0.025
            : 0;
        const stableSpread = ((index - startIndex + slotNodeIds.length) % slotNodeIds.length) * 0.003;
        return {
            nodeId,
            score: (occupancy * 3.8) + distancePenalty + stableSpread,
        };
    }).sort((a, b) => a.score - b.score);

    return safeString(scored[0]?.nodeId) || nav.centerNodeId;
}

function officeRouteAgentToRoom(agent, roomId, { intent = 'wander', speed = 0 } = {}) {
    if (!officeState || !agent) return false;
    const nav = officeState.roomNav?.get(roomId);
    if (!nav) return false;
    const destinationNodeId = officeSelectRoomDestinationNode(roomId, agent, { intent }) || nav.centerNodeId;
    const routed = officeRouteAgentToNode(agent, destinationNodeId, { intent, speed });
    if (routed) {
        officeBusEmit('agent.route', {
            agentId: agent.id,
            roomId,
            destinationNodeId,
            intent: safeString(intent) || 'wander',
            speed: Number(speed) || 0,
        });
    }
    return routed;
}

function officePointInRoom(roomId) {
    const room = officeRoomById(roomId) || officeState?.rooms?.[0];
    if (!room) return { x: 50, y: 50 };
    const marginX = Math.min(3.2, room.w * 0.22);
    const marginY = Math.min(3.2, room.h * 0.22);
    const minX = room.x + marginX;
    const maxX = room.x + room.w - marginX;
    const minY = room.y + marginY;
    const maxY = room.y + room.h - marginY;
    return {
        x: officeClamp(officeRandomRange(minX, maxX), 3, 97),
        y: officeClamp(officeRandomRange(minY, maxY), 7, 92),
    };
}

function officeBubbleClassForX(xPercent) {
    // Keep bubbles on-screen by flipping edge-side anchors.
    if (xPercent <= 20) return 'right';
    if (xPercent >= 82) return 'left';
    return 'center';
}

function officeBubbleVerticalForY(yPercent) {
    return yPercent < 24 ? 'below' : 'above';
}

function officeAgentScreenPosition(agent) {
    if (!officeState || !agent) return null;
    const metrics = officeViewportMetrics();
    if (!metrics) return null;
    const renderZoom = officeEffectiveZoom(officeState.zoomLevel);
    const worldX = (agent.x / 100) * officeState.mapWidth;
    const worldY = (agent.y / 100) * officeState.mapHeight;
    return {
        x: (worldX * renderZoom) + officeState.panX,
        y: (worldY * renderZoom) + officeState.panY,
        width: metrics.wrapWidth,
        height: metrics.wrapHeight,
    };
}

function officeBubbleAnchorForAgent(agent, speechText = '') {
    const fallback = {
        horizontal: officeBubbleClassForX(agent?.x || 50),
        vertical: officeBubbleVerticalForY(agent?.y || 50),
    };
    const screen = officeAgentScreenPosition(agent);
    if (!screen) return fallback;

    const safeSpeech = safeString(speechText);
    const estimatedBubbleWidth = officeClamp(120 + (safeSpeech.length * 4.2), 132, Math.min(252, screen.width * 0.5));
    const margin = 12;
    let horizontal = 'center';
    if ((screen.x - (estimatedBubbleWidth / 2)) <= margin) {
        horizontal = 'right';
    } else if ((screen.x + (estimatedBubbleWidth / 2)) >= (screen.width - margin)) {
        horizontal = 'left';
    }

    let vertical = 'above';
    if ((screen.y - 96) <= margin) {
        vertical = 'below';
    } else if ((screen.y + 96) >= (screen.height - margin)) {
        vertical = 'above';
    } else {
        vertical = officeBubbleVerticalForY(agent?.y || 50);
    }

    return { horizontal, vertical };
}

function officeVisibleSpeech(agent, now) {
    if (!agent?.speech) return '';
    if (now >= agent.speech.endAt) {
        agent.speech = null;
        return '';
    }
    const text = safeString(agent.speech.text);
    if (!text) return '';
    const elapsed = now - agent.speech.startAt;
    const revealMs = Math.max(1, Number(agent.speech.revealMs) || 1);
    const ratio = officeClamp(elapsed / revealMs, 0, 1);
    const chars = Math.max(1, Math.round(text.length * ratio));
    return text.slice(0, chars);
}

function officeSpeak(agent, text, { priority = false, durationMs = 0 } = {}) {
    if (!officeState || !agent) return false;
    const clean = safeString(text);
    if (!clean) return false;
    const now = performance.now();
    if (!priority && now < officeState.nextGlobalSpeechAt) {
        return false;
    }

    const revealMs = officeSpeechRevealMsForText(clean);
    const holdMs = durationMs > 0
        ? officeClamp(durationMs, 700, 4800)
        : officeClamp(clean.length * 46, 1100, 3600);

    agent.speech = {
        text: clean,
        startAt: now,
        revealMs,
        endAt: now + revealMs + holdMs,
    };
    agent.nextAmbientAt = now + officeRandomRange(6800, 13000);
    officeState.nextGlobalSpeechAt = now + officeRandomRange(850, 1800);
    officeBusEmit('agent.speak', {
        agentId: agent.id,
        state: agent.state,
        intent: agent.intent,
        text: clean.slice(0, 120),
    }, now);
    return true;
}

function officePushChatLine(text, tone = 'system') {
    if (!officeState || !officeChatLog) return;
    const message = safeString(text);
    if (!message) return;
    officeState.chatLines.push({
        message,
        tone: safeString(tone) || 'system',
        at: Date.now(),
    });
    if (officeState.chatLines.length > OFFICE_MAX_CHAT_LINES) {
        officeState.chatLines = officeState.chatLines.slice(officeState.chatLines.length - OFFICE_MAX_CHAT_LINES);
    }

    officeChatLog.innerHTML = '';
    const frag = document.createDocumentFragment();
    officeState.chatLines.forEach((line) => {
        const row = document.createElement('div');
        const epoch = Number(line?.at);
        const stamp = Number.isFinite(epoch) && epoch > 0
            ? new Date(epoch).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : '--:--';
        row.textContent = `[${stamp}] ${safeString(line?.message)}`;
        row.dataset.tone = line.tone;
        frag.appendChild(row);
    });
    officeChatLog.appendChild(frag);
    officeChatLog.scrollTop = officeChatLog.scrollHeight;
}

function officeBusEmit(typeRaw, payload = {}, now = performance.now()) {
    if (!officeState) return null;
    const type = safeString(typeRaw).toLowerCase();
    if (!type) return null;
    const event = {
        id: `oe-${Math.round(now)}-${Math.floor(officeRandomRange(100, 999))}`,
        schema: OFFICE_EVENT_SCHEMA_VERSION,
        type,
        ts: Date.now(),
        now,
        payload: payload && typeof payload === 'object' ? payload : {},
    };
    officeState.officeEvents.push(event);
    if (officeState.officeEvents.length > OFFICE_EVENT_LOG_LIMIT) {
        officeState.officeEvents = officeState.officeEvents.slice(
            officeState.officeEvents.length - OFFICE_EVENT_LOG_LIMIT,
        );
    }
    officeState.officeBusListeners.forEach((listener) => {
        try {
            listener(event);
        } catch {
            // Listener failures should not break simulation loop.
        }
    });
    return event;
}

function officeBusSubscribe(listener) {
    if (!officeState || typeof listener !== 'function') {
        return () => {};
    }
    officeState.officeBusListeners.add(listener);
    return () => {
        if (!officeState) return;
        officeState.officeBusListeners.delete(listener);
    };
}

function officeViewportMetrics() {
    if (!officeSceneWrap || !officeScenePanzoom) return null;
    const wrapRect = officeSceneWrap.getBoundingClientRect();
    return {
        wrapRect,
        wrapWidth: Math.max(1, wrapRect.width),
        wrapHeight: Math.max(1, wrapRect.height),
        mapWidth: Math.max(1, officeState?.mapWidth || officeScenePanzoom.offsetWidth || OFFICE_MAP_WIDTH),
        mapHeight: Math.max(1, officeState?.mapHeight || officeScenePanzoom.offsetHeight || OFFICE_MAP_HEIGHT),
    };
}

function officeClampPan(panX, panY, zoom, metrics = null) {
    const view = metrics || officeViewportMetrics();
    if (!view) return { panX, panY };

    const renderZoom = officeEffectiveZoom(zoom);
    const scaledW = view.mapWidth * renderZoom;
    const scaledH = view.mapHeight * renderZoom;

    let minX;
    let maxX;
    if (scaledW <= view.wrapWidth) {
        minX = (view.wrapWidth - scaledW) / 2;
        maxX = minX;
    } else {
        minX = view.wrapWidth - scaledW - OFFICE_VIEWPORT_MARGIN;
        maxX = OFFICE_VIEWPORT_MARGIN;
    }

    let minY;
    let maxY;
    if (scaledH <= view.wrapHeight) {
        minY = (view.wrapHeight - scaledH) / 2;
        maxY = minY;
    } else {
        minY = view.wrapHeight - scaledH - OFFICE_VIEWPORT_MARGIN;
        maxY = OFFICE_VIEWPORT_MARGIN;
    }

    return {
        panX: officeClamp(panX, minX, maxX),
        panY: officeClamp(panY, minY, maxY),
    };
}

function officeDynamicMinZoom(metrics = null) {
    return OFFICE_ZOOM_MIN;
}

function officeEffectiveZoom(rawZoom) {
    const numeric = officeClamp(
        Number.isFinite(rawZoom) ? rawZoom : 1,
        OFFICE_ZOOM_MIN,
        OFFICE_ZOOM_MAX,
    );
    if (numeric <= OFFICE_ZOOM_RENDER_FLOOR) {
        return OFFICE_ZOOM_RENDER_FLOOR;
    }
    if (numeric < 0.3) {
        const t = officeClamp(
            (numeric - OFFICE_ZOOM_RENDER_FLOOR) / (0.3 - OFFICE_ZOOM_RENDER_FLOOR),
            0,
            1,
        );
        return OFFICE_ZOOM_RENDER_FLOOR + (t * t * (0.3 - OFFICE_ZOOM_RENDER_FLOOR));
    }
    return numeric;
}

function officeApplyZoom() {
    if (!officeState || !officeScenePanzoom) return;
    officeScenePanzoom.style.width = `${officeState.mapWidth}px`;
    officeScenePanzoom.style.height = `${officeState.mapHeight}px`;
    const metrics = officeViewportMetrics();
    const minZoom = officeDynamicMinZoom(metrics);
    officeState.zoomLevel = officeClamp(officeState.zoomLevel, minZoom, OFFICE_ZOOM_MAX);
    const clampedPan = officeClampPan(officeState.panX, officeState.panY, officeState.zoomLevel);
    officeState.panX = clampedPan.panX;
    officeState.panY = clampedPan.panY;
    const renderZoom = officeEffectiveZoom(officeState.zoomLevel);
    officeScenePanzoom.style.setProperty('--office-zoom', String(renderZoom));
    officeScenePanzoom.style.setProperty('--office-pan-x', `${officeState.panX.toFixed(2)}px`);
    officeScenePanzoom.style.setProperty('--office-pan-y', `${officeState.panY.toFixed(2)}px`);
    if (officeSceneWrap) {
        officeSceneWrap.style.setProperty('--office-pan-x', `${officeState.panX.toFixed(2)}px`);
        officeSceneWrap.style.setProperty('--office-pan-y', `${officeState.panY.toFixed(2)}px`);
    }
    if (officeZoomResetBtn) {
        officeZoomResetBtn.textContent = `${Math.round(Math.max(0, officeState.zoomLevel) * 100)}%`;
    }
    officeRenderMinimap();
}

function officePersistCameraState(now = performance.now()) {
    if (!officeState) return;
    if ((now - (officeState.lastCameraPersistAt || 0)) < 260) return;
    const snapshot = {
        zoom: Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel,
        panX: Number.isFinite(officeState.targetPanX) ? officeState.targetPanX : officeState.panX,
        panY: Number.isFinite(officeState.targetPanY) ? officeState.targetPanY : officeState.panY,
        followAgentId: safeString(officeState.followAgentId),
    };
    const signature = [
        Number(snapshot.zoom || 0).toFixed(4),
        Number(snapshot.panX || 0).toFixed(2),
        Number(snapshot.panY || 0).toFixed(2),
        safeString(snapshot.followAgentId),
    ].join('|');
    if (signature === safeString(officeState.lastCameraPersistSignature)) {
        return;
    }
    officeState.lastCameraPersistAt = now;
    officeState.lastCameraPersistSignature = signature;
    saveStoredOfficeCameraState(snapshot);
}

