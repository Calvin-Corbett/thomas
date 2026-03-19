// Extracted from part-016.js
// From roomid

    }
    if (action.startsWith('focus:')) {
        const roomId = safeString(action.split(':')[1]) || 'room-pods';
        officeState.agents.forEach((agent) => {
            if (!agent || agent.state === 'runaway') return;
            officeRouteAgentToRoom(agent, roomId, {
                intent: 'wander',
                speed: officeRandomRange(3.2, 4.3),
            });
        });
        const roomLabel = officeRoomById(roomId)?.label || roomId;
        officePushChatLine(`System: Focus wave sent to ${roomLabel}.`);
        officeBusEmit('quick_action.run', { ...eventPayload, roomId }, now);
    }
}

function officeTouchActivePointers() {