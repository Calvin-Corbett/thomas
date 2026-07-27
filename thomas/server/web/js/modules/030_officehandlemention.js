// Extracted from part-015b.js
// From officehandlemention

    if (command === 'status' || command === 'where' || command === 'load') return { command: 'status', args };
    if (command === 'break' || command === 'coffee' || command === 'lunch') return { command: 'break', args };
    if (command === 'resume' || command === 'work') return { command: 'resume', args };
    if (command === 'summon' || command === 'lobby') return { command: 'summon', args };
    if (command === 'focus') return { command: 'focus', args };
    if (command === 'task') return { command: 'task', args };
    return { command: 'message', args: message };
}

function officeHandleMention(agent, messageRaw) {
    if (!officeState || !agent) return;
    const message = safeString(messageRaw);
    const parsed = officeParseMentionCommand(message);
    let reply = '';

    if (parsed.command === 'status') {
        const activeCount = officeState.tasks.filter((task) => task.status === 'active').length;
        const room = officeCurrentRoomForAgent(agent);
        const status = officePick(OFFICE_DIALOGUE.mentionStatus).replace('{count}', String(activeCount));
        reply = `${status} I am in ${room?.label || 'the hallway'} right now.`;
    } else if (parsed.command === 'break') {
        const breakTarget = officeChance(0.5) ? 'room-coffee' : 'room-break';
        officeRouteAgentToRoom(agent, breakTarget, {
            intent: 'break',
            speed: officeRandomRange(2.8, 3.9),
        });
        agent.nextBreakAt = performance.now() + officeRandomRange(40_000, 88_000);
        reply = 'Copy. Taking a short break loop and returning to queue.';
    } else if (parsed.command === 'resume') {
        agent.state = 'idle';
        agent.intent = 'wander';
        agent.idleUntil = performance.now() + officeRandomRange(320, 1200);
        const routed = officeRouteAgentToRoom(agent, 'room-lobby', {
            intent: 'wander',
            speed: officeRandomRange(2.8, 3.8),
        });
        reply = routed ? 'Resuming active route from lobby.' : 'Resuming in place.';
    } else if (parsed.command === 'summon') {
        officeRouteAgentToRoom(agent, 'room-lobby', {
            intent: 'wander',
            speed: officeRandomRange(3.2, 4.1),
        });
        reply = 'On my way to Main Lobby.';
    } else if (parsed.command === 'focus') {
        const roomId = officeResolveExplicitRoom(parsed.args)?.id || 'room-pods';
        const room = officeRoomById(roomId);
        officeRouteAgentToRoom(agent, roomId, {
            intent: 'wander',
            speed: officeRandomRange(3.1, 4.1),
        });
        reply = `Switching to focus in ${room?.label || 'Focus Pods'}.`;
    } else if (parsed.command === 'task') {
        const taskText = parsed.args || 'new task';
        const task = officeQueueTask(taskText, {
            source: `mention:${agent.id}`,
            announce: false,
            preferredAgentId: agent.id,
        });
        if (task && task.assignedAgentId === agent.id) {
            reply = `Picked it up. I am moving to ${task.roomLabel}.`;
        } else if (task) {
            reply = `Queued it in ${task.roomLabel}. I will grab it after my current task.`;
        } else {
            reply = officePick(OFFICE_DIALOGUE.mention);
        }
    } else {
        reply = officePick(OFFICE_DIALOGUE.mention);
    }

    if (officeSpeak(agent, reply, { priority: true, durationMs: 1700 })) {
        officePushChatLine(`@${agent.name}: ${reply}`);
        officeBusEmit('agent.mention', {
            agentId: agent.id,
            agentName: agent.name,
            command: parsed.command,
            args: safeString(parsed.args).slice(0, 160),
        });
    }
}

function officeHandleAgentTap(agentId) {
    if (!officeState) return;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    officeState.selectedAgentId = agent.id;
    officeSyncCustomizerFields();
    if (safeString(officeState.followAgentId)) {
        officeSetFollowMode(true, agent.id);
    }
    const now = performance.now();
    const exit = officePlanRunawayExit(agent);
    agent.jumpUntil = now + 460;
    agent.bumpUntil = now + 460;
    agent.state = 'runaway';
    agent.intent = 'runaway';
    agent.returnAfterRunAt = now + officeClamp(OFFICE_RUNAWAY_DURATION_MS * 0.46, 2000, 3200);
    agent.taskId = '';
    agent.facing = exit.x >= agent.x ? 1 : -1;
    agent.runawayExitX = exit.x;
    agent.runawayExitY = exit.y;
    agent.runawayPhase = 'to-hall';
