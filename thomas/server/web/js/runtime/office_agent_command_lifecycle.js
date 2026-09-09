/** Command execution, completion, and agent memory. */

function officeDraftSetAgentCommandTarget(agent, space, targetWorld, options = {}) {
    if (!agent || !space || !targetWorld) return null;
    const now = performance.now();
    const roomId = officeDraftNormalizeRoomId(space.roomId, space.id);
    const action = safeString(options.action || 'move') || 'move';
    agent.remoteRoomId = roomId;
    agent.draftPinnedRoomId = roomId;
    agent.draftPinnedTaskId = safeString(agent.taskId);
    agent.draftPinnedLocalX = Math.round(Number(targetWorld.x) - (Number(space.x) || 0));
    agent.draftPinnedLocalY = Math.round(Number(targetWorld.y) - (Number(space.y) || 0));
    agent.draftCommandAssetId = safeString(options.assetId);
    agent.draftCommandAssetType = safeString(options.assetType);
    agent.draftCommandPropLabel = safeString(options.propLabel);
    agent.draftInteractionIntent = action;
    agent.draftCommandUntil = now + 70000;
    agent.draftCommandCompletedAt = 0;
    agent.draftCommandCompletionKey = '';
    agent.draftManualPinUntil = 0;
    agent.draftWanderRoomId = '';
    agent.draftWanderSpaceId = '';
    agent.draftWanderNextAt = 0;
    agent.draftWanderArrivedAt = 0;
    agent.lastOfficeCommandSummary = safeString(options.summary || `Going to ${safeString(space.name) || 'that room'}.`).slice(0, 180);
    agent.draftPausedUntil = 0;
    agent.draftDropUntil = 0;
    agent.state = 'walking';
    agent.intent = ['drink', 'food', 'sit', 'play'].includes(action)
        ? 'break'
        : (['work', 'research', 'print', 'charge', 'monitor', 'record'].includes(action) ? 'task' : 'wander');
    delete agent.draftTargetPointCache;
    delete agent.draftFallbackTargetCache;
    const motion = officeDraftEnsureAgentMotion(agent, space, 0, 1, null, now);
    if (motion) {
        motion.route = [];
        motion.routeIndex = 0;
        motion.targetSignature = '';
        motion.targetX = Math.round(Number(targetWorld.x) || 0);
        motion.targetY = Math.round(Number(targetWorld.y) || 0);
        motion.needsReplan = true;
        motion.dragging = false;
        motion.routeRetryAfter = 0;
        motion.lastProgressAt = now;
        motion.lastAt = now;
    }
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.office_command', {
            agentId: safeString(agent.id),
            roomId,
            spaceId: safeString(space.id),
            assetId: safeString(options.assetId),
            assetType: safeString(options.assetType),
            action,
            summary: agent.lastOfficeCommandSummary,
        }, now);
    }
    return {
        roomId,
        spaceId: safeString(space.id),
        assetId: safeString(options.assetId),
        assetType: safeString(options.assetType),
        action,
        summary: agent.lastOfficeCommandSummary,
    };
}

function officeDraftAgentCommandCompletionKey(agent) {
    if (!agent) return '';
    return [
        safeString(agent.id),
        safeString(agent.draftCommandAssetId),
        safeString(agent.draftCommandAssetType),
        safeString(agent.draftPinnedRoomId),
        Math.round(Number(agent.draftPinnedLocalX) || 0),
        Math.round(Number(agent.draftPinnedLocalY) || 0),
        safeString(agent.draftInteractionIntent),
    ].join('|');
}

function officeDraftAgentCommandRouteActive(agent) {
    const route = Array.isArray(agent?.draftMotion?.route) ? agent.draftMotion.route : [];
    return route.length > 0 && Number(agent?.draftMotion?.routeIndex) < route.length;
}

function officeDraftAgentCommandArrived(agent) {
    if (!officeDraftAgentCommandActive(agent)) return false;
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (!motion) return false;
    const targetX = Number(motion.targetX);
    const targetY = Number(motion.targetY);
    const x = Number(motion.x);
    const y = Number(motion.y);
    if (!Number.isFinite(targetX) || !Number.isFinite(targetY) || !Number.isFinite(x) || !Number.isFinite(y)) return false;
    const arrived = Math.hypot(x - targetX, y - targetY) <= Math.max(OFFICE_DRAFT_AGENT_ROUTE_EPSILON * 2, 18);
    if (arrived) return true;
    if (officeDraftAgentCommandRouteActive(agent)) return false;
    return false;
}

function officeDraftPushAgentOfficeMemory(agent, entryRaw = {}) {
    if (!agent) return;
    const now = Number(entryRaw.at) || Date.now();
    const entry = {
        at: now,
        action: safeString(entryRaw.action || agent.draftInteractionIntent || 'move'),
        roomId: safeString(entryRaw.roomId || agent.draftPinnedRoomId),
        assetId: safeString(entryRaw.assetId || agent.draftCommandAssetId),
        assetType: safeString(entryRaw.assetType || agent.draftCommandAssetType),
        summary: safeString(entryRaw.summary || agent.lastOfficeCommandSummary || 'Completed an office action.').slice(0, 180),
    };
    const history = Array.isArray(agent.officeActionHistory) ? agent.officeActionHistory : [];
    const last = history[history.length - 1] || null;
    if (last && safeString(last.summary) === entry.summary && safeString(last.assetId) === entry.assetId) {
        last.at = now;
        agent.officeActionHistory = history.slice(-8);
    } else {
        agent.officeActionHistory = [...history.slice(-7), entry];
    }
    agent.lastOfficeActionMemory = entry.summary;
}

function officeDraftAgentCommandVerb(agent, actionRaw) {
    const action = safeString(actionRaw || agent?.draftInteractionIntent || 'move');
    const prop = safeString(agent?.draftCommandPropLabel);
    const grabbed = (labelRaw, fallbackRaw) => {
        const label = safeString(labelRaw || fallbackRaw);
        if (!label) return 'grabbed something';
        if (/^(coffee|tea|water)$/i.test(label)) return `grabbed ${label}`;
        if (/^(a|an|the)\s+/i.test(label)) return `grabbed ${label}`;
        return `grabbed a ${label}`;
    };
    if (action === 'drink') return `${grabbed(prop, 'drink')} at`;
    if (action === 'food') return `${grabbed(prop, 'snack')} at`;
    if (action === 'sit') return 'sat down near';
    if (action === 'play') return 'started playing at';
    if (action === 'research') return 'started researching at';
    if (action === 'print') return 'used';
    if (action === 'charge') return 'plugged into';
    if (action === 'monitor') return 'checked';
    if (action === 'record') return 'started recording at';
    if (action === 'work') return 'started working at';
    return 'arrived at';
}

function officeDraftMaybeCompleteAgentCommand(agent, now = performance.now()) {
    if (!agent || !officeDraftAgentCommandArrived(agent)) return false;
    const completionKey = officeDraftAgentCommandCompletionKey(agent);
    if (!completionKey || safeString(agent.draftCommandCompletionKey) === completionKey) return true;
    const action = safeString(agent.draftInteractionIntent || 'move') || 'move';
    const space = officeDraftSpaceForAgent(agent);
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id || agent.draftPinnedRoomId);
    const assetLabel = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(agent.draftCommandAssetType)]?.label || agent.draftCommandAssetType).replace(/_/g, ' ');
    const roomLabel = safeString(space?.name || officeRoomById(roomId)?.label || 'the office');
    const verb = officeDraftAgentCommandVerb(agent, action);
    const summary = assetLabel
        ? `${safeString(agent.name) || 'Agent'} ${verb} the ${assetLabel} in ${roomLabel}.`
        : `${safeString(agent.name) || 'Agent'} arrived in ${roomLabel}.`;
    agent.draftCommandCompletedAt = Number(now) || performance.now();
    agent.draftCommandCompletionKey = completionKey;
    agent.lastOfficeCommandSummary = summary;
    agent.draftCommandUntil = Math.max(Number(agent.draftCommandUntil) || 0, (Number(now) || performance.now()) + 28000);
    if (action === 'drink' || action === 'food' || action === 'sit' || action === 'play') {
        agent.state = 'break';
        agent.intent = 'break';
        agent.breakUntil = (Number(now) || performance.now()) + 24000;
    } else if (['work', 'research', 'print', 'charge', 'monitor', 'record'].includes(action)) {
        agent.state = 'working';
        agent.intent = 'task';
        agent.workUntil = (Number(now) || performance.now()) + 26000;
    } else {
        agent.state = 'idle';
        agent.intent = 'wander';
    }
    officeDraftPushAgentOfficeMemory(agent, {
        at: Date.now(),
        action,
        roomId,
        assetId: safeString(agent.draftCommandAssetId),
        assetType: safeString(agent.draftCommandAssetType),
        summary,
    });
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.office_command_complete', {
            agentId: safeString(agent.id),
            roomId,
            assetId: safeString(agent.draftCommandAssetId),
            assetType: safeString(agent.draftCommandAssetType),
            action,
            summary,
        }, Number(now) || performance.now());
    }
    if (typeof officePersistRuntimeState === 'function') {
        officePersistRuntimeState(Number(now) || performance.now(), { force: true });
    }
    return true;
}

function officeDraftApplyAgentChatCommand(agent, textRaw) {
    if (!agent) return null;
    const commandText = officeDraftNormalizeAgentCommandText(textRaw);
    if (!commandText || !officeDraftAgentCommandVerbPresent(commandText)) return null;
    const roomMatch = officeDraftFindCommandTargetRoom(commandText, agent);
    const assetMatch = officeDraftFindCommandTargetAsset(commandText, agent, roomMatch);
    let targetSpace = assetMatch?.space || roomMatch?.space || null;
    let targetAsset = assetMatch?.asset || null;
    let action = safeString(assetMatch?.action || 'move') || 'move';
    let propLabel = safeString(assetMatch?.propLabel);
    if (!targetSpace) return null;
    if (!targetAsset && roomMatch?.space) {
        targetAsset = officeDraftPrimaryInteractionAsset(targetSpace, agent);
        if (targetAsset) {
            const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(targetAsset.type)]?.interaction);
            const inferredAction = officeDraftInferCommandActionFromInteraction(interaction);
            if (inferredAction) action = inferredAction;
        }
    }
    const seed = officeStableHash(`${safeString(agent.id)}|${commandText}|${safeString(targetAsset?.id)}`);
    const targetWorld = targetAsset
        ? officeDraftChooseAssetApproachPoint(targetSpace, agent, targetAsset, seed, { routeAware: true })
        : officeDraftFallbackAgentTargetWorldPoint(targetSpace, agent, 0, 1);
    if (!targetWorld) return null;
    const assetLabel = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(targetAsset?.type)]?.label);
    const roomLabel = safeString(targetSpace.name || officeRoomById(officeDraftNormalizeRoomId(targetSpace.roomId, targetSpace.id))?.label || 'that room');
    const summary = targetAsset
        ? `${safeString(agent.name) || 'Agent'} is going to the ${assetLabel || 'target'} in ${roomLabel}.`
        : `${safeString(agent.name) || 'Agent'} is going to ${roomLabel}.`;
    const result = officeDraftSetAgentCommandTarget(agent, targetSpace, targetWorld, {
        action,
        propLabel: propLabel || (action === 'drink' ? 'Coke' : ''),
        assetId: safeString(targetAsset?.id),
        assetType: safeString(targetAsset?.type),
        summary,
    });
    agent.lastOfficeChatCommand = result;
    if (typeof officePersistRuntimeState === 'function') {
        officePersistRuntimeState(performance.now(), { force: true });
    }
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-chat-command' });
    return result;
}

function officeDraftPauseAgentForUser(agent, space, now = performance.now()) {
    if (!agent) return;
    const motion = officeDraftEnsureAgentMotion(agent, space, 0, 1, null, now);
    motion.route = [];
    motion.routeIndex = 0;
    motion.dragging = false;
    motion.needsReplan = false;
    agent.draftPausedUntil = now + 6500;
    agent.draftClickedAt = now;
    agent.draftInteractionIntent = 'talk';
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.draft_click', {
            agentId: safeString(agent.id),
            roomId: officeDraftNormalizeRoomId(space?.roomId, space?.id),
        }, now);
    }
    officeDraftPrimeAgentConversation(agent, space, now);
}


