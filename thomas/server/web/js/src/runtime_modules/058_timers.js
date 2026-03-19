// Extracted from part-030.js
// From timers

                }))
                .filter((line) => Boolean(line.message))
            : [],
        tasks: Array.isArray(officeState.tasks)
            ? officeState.tasks.map((task) => ({
                id: safeString(task?.id),
                title: safeString(task?.title),
                rawText: safeString(task?.rawText),
                source: safeString(task?.source),
                roomId: safeString(task?.roomId),
                roomLabel: safeString(task?.roomLabel),
                status: safeString(task?.status).toLowerCase(),
                assignedAgentId: safeString(task?.assignedAgentId),
                createdAt: Number(task?.createdAt) || 0,
                startedAt: Number(task?.startedAt) || 0,
                completedAt: Number(task?.completedAt) || 0,
            })).filter((task) => Boolean(task.id))
            : [],
        agents: Array.isArray(officeState.agents)
            ? officeState.agents.map((agent) => {
                const timers = {};
                OFFICE_RUNTIME_TIMER_FIELDS.forEach((field) => {
                    timers[field] = officeRuntimeTimerRemaining(timerNow, agent?.[field]);
                });
                return {
                    id: safeString(agent?.id),
                    name: safeString(agent?.name).slice(0, 24),
                    color: safeString(agent?.color),
                    costume: safeString(agent?.costume || 'none').toLowerCase(),
                    tint: safeString(agent?.tint || officeAgentTintFromColor(agent?.color)).toLowerCase(),
                    x: Number(agent?.x) || 0,
                    y: Number(agent?.y) || 0,
                    targetX: Number(agent?.targetX) || 0,
                    targetY: Number(agent?.targetY) || 0,
                    speed: Number(agent?.speed) || 0,
                    facing: Number(agent?.facing) || 1,
                    laneBias: Number(agent?.laneBias) || 0,
                    state: safeString(agent?.state).toLowerCase(),
                    intent: safeString(agent?.intent).toLowerCase(),
                    taskId: safeString(agent?.taskId),
                    workStreak: Number(agent?.workStreak) || 0,
                    yieldResumeIntent: safeString(agent?.yieldResumeIntent),
                    runawayPhase: safeString(agent?.runawayPhase),
                    runawayExitX: Number(agent?.runawayExitX) || 0,
                    runawayExitY: Number(agent?.runawayExitY) || 0,
                    currentNodeId: safeString(agent?.currentNodeId),
                    routeWaypoints: Array.isArray(agent?.routeWaypoints)
                        ? agent.routeWaypoints.slice(0, 24).map((point) => ({
                            x: Number(point?.x) || 0,
                            y: Number(point?.y) || 0,
                            nodeId: safeString(point?.nodeId),
                        }))
                        : [],
                    routeDestinationNodeId: safeString(agent?.routeDestinationNodeId),
                    reservedLaneEdgeKey: safeString(agent?.reservedLaneEdgeKey),
                    timers,
                };
            }).filter((agent) => Boolean(agent.id))
            : [],
    };
}

function officeApplyRuntimeSnapshot(snapshotRaw, now = performance.now()) {
    if (!officeState || !snapshotRaw || typeof snapshotRaw !== 'object') return false;
    if (Number(snapshotRaw.version) !== OFFICE_RUNTIME_SCHEMA_VERSION) return false;
    const timerNow = Number(now) || performance.now();
    let changed = false;
