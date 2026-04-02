async function streamChatResponse(payload, { userContext = '', existingBubbleId = '' } = {}) {
    let bubbleId = existingBubbleId || ('msg-' + Date.now());
    let bubbleRow = null;
    let bubbleMsgContent = null;
    try {
        const landedRobotExit = _portalOutLandedRobot();
        vibeCodePrepareForRequest(payload);

        // Wire AbortController for stop generation
        currentAbortController = new AbortController();
        const chatEndpoint = window.__THOMAS_CHAT_V2__ === false ? '/api/chat' : '/api/v2/chat';
        const res = await fetch(chatEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: currentAbortController.signal,
        });

        if (!res.ok) {
            const errText = await res.text();
            throw new Error(`API Error ${res.status}: ${errText}`);
        }
        void refreshTaskContinuity({
            sessionOverride: safeString(payload?.session_id) || sessionId,
        });

        // Render an empty assistant bubble with typing indicator (or reuse existing)
        if (!existingBubbleId) {
            renderMessage({ role: 'assistant', content: '', id: bubbleId });
        }
        bubbleRow = document.getElementById(bubbleId);
        bubbleMsgContent = bubbleRow ? bubbleRow.querySelector('.message-content') : null;
        if (bubbleMsgContent) {
            bubbleMsgContent.innerHTML = '';
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';
        let hasRenderableText = false;
        let streamDone = false;
        let robotSayingInterval = null;
        let robotTimerInterval = null;
        let robotAnimInterval = null;
        let robotStartTime = Date.now();
        let currentRobotCategory = 'thinking';
        let thinkingText = '';  // accumulates real thinking/reasoning content from stream
        let robotLandedForThisResponse = false;
        let robotStatusQueued = false;
        let robotStatusCanStartAt = Date.now();
        const _officeDelegationTaskByActivity = new Map();
        const _taskContractActivityId = `task-contract:${bubbleId}`;
        const _taskUiSessionId = safeString(payload?.session_id) || safeString(activeChatId) || safeString(sessionId) || bubbleId;
        let _taskUiSeeded = false;
        let _taskUiTerminated = false;
        landedRobotExit.finally(() => {
            robotStatusCanStartAt = Date.now() + 240;
            if (!robotStatusQueued) return;
            const delay = Math.max(0, robotStatusCanStartAt - Date.now());
            setTimeout(() => {
                if (!hasRenderableText) _startRobotStatus();
            }, delay);
        });

        function _startRobotStatus() {
            if (robotSayingInterval || !bubbleMsgContent) return;
            const waitMs = Math.max(0, robotStatusCanStartAt - Date.now());
            if (waitMs > 0) {
                robotStatusQueued = true;
                setTimeout(() => {
                    robotStatusQueued = false;
                    if (!hasRenderableText) _startRobotStatus();
                }, waitMs);
                return;
            }
            robotStatusQueued = false;
            currentRobotCategory = 'thinking';
            robotStartTime = Date.now();
            bubbleRow?.classList.add('message-row-inline-status');
            bubbleMsgContent.classList.add('message-content-inline-status');
            bubbleMsgContent.innerHTML = '';
            bubbleMsgContent.appendChild(_createRobotStatus('thinking'));

            // Rotate sayings every 2.5s
            robotSayingInterval = setInterval(() => {
                const sayingEl = bubbleMsgContent.querySelector('.chat-robot-saying');
                if (sayingEl) {
                    sayingEl.classList.add('saying-fade');
                    setTimeout(() => {
                        sayingEl.textContent = pickChatSaying(currentRobotCategory);
                        sayingEl.classList.remove('saying-fade');
                    }, 200);
                }
            }, 2500);

            // Update elapsed timer every 100ms
            robotTimerInterval = setInterval(() => {
                const timerEl = bubbleMsgContent.querySelector('.chat-robot-timer');
                if (timerEl) {
                    timerEl.textContent = ((Date.now() - robotStartTime) / 1000).toFixed(1) + 's';
                }
            }, 100);

            // Swap animation every 8s  use rAF for clean transition
            robotAnimInterval = setInterval(() => {
                const agentEl = bubbleMsgContent.querySelector('.chat-robot-agent');
                if (agentEl) {
                    const newAnim = _pickRobotAnimation();
                    // Remove old, pause for one frame, then apply new
                    CHAT_ROBOT_ANIMATIONS.forEach(a => agentEl.classList.remove('chat-robot-anim-' + a));
                    agentEl.style.animation = 'none';
                    requestAnimationFrame(() => {
                        agentEl.style.animation = '';
                        agentEl.classList.add('chat-robot-anim-' + newAnim);
                    });
                }
            }, 8000);

            // No more task-ledger polling  thinking text arrives via NDJSON stream events
        }
        _startRobotStatus();

        function _setRobotSaying(text) {
            const sayingEl = bubbleMsgContent?.querySelector('.chat-robot-saying');
            if (sayingEl) {
                sayingEl.classList.add('saying-fade');
                setTimeout(() => {
                    sayingEl.textContent = robotAmbientStatusText(text);
                    sayingEl.classList.remove('saying-fade');
                }, 200);
            }
        }

        function _clearRobotStatus() {
            if (robotSayingInterval) { clearInterval(robotSayingInterval); robotSayingInterval = null; }
            if (robotTimerInterval) { clearInterval(robotTimerInterval); robotTimerInterval = null; }
            if (robotAnimInterval) { clearInterval(robotAnimInterval); robotAnimInterval = null; }
            const robotEl = bubbleMsgContent?.querySelector('.chat-robot-status');
            if (robotEl) robotEl.remove();
            bubbleMsgContent?.classList.remove('message-content-inline-status', 'streaming-active');
            bubbleRow?.classList.remove('message-row-inline-status');
        }

        function _robotExitRun() {
            if (robotSayingInterval) { clearInterval(robotSayingInterval); robotSayingInterval = null; }
            if (robotTimerInterval) { clearInterval(robotTimerInterval); robotTimerInterval = null; }
            if (robotAnimInterval) { clearInterval(robotAnimInterval); robotAnimInterval = null; }
            robotLandedForThisResponse = true;
            const statusEl = bubbleMsgContent?.querySelector('.chat-robot-status');
            if (statusEl) statusEl.remove();
            bubbleRow?.classList.remove('message-row-inline-status');
            bubbleMsgContent?.classList.remove('message-content-inline-status');
            if (bubbleMsgContent) bubbleMsgContent.classList.add('streaming-active');
        }

        //  rAF-batched streaming render 
        let _rafScheduled = false;
        function _scheduleStreamRender() {
            if (_rafScheduled) return;
            _rafScheduled = true;
            requestAnimationFrame(() => {
                _rafScheduled = false;
                updateMessage(bubbleId, fullText);
            });
        }
        function _consumeAssistantChunk(chunk, { renderNow = false } = {}) {
            const textChunk = streamChunkString(chunk);
            if (!textChunk) return false;
            if (!hasRenderableText) {
                _robotExitRun();
                bubbleRow?.classList.remove('message-row-inline-status');
                bubbleMsgContent?.classList.remove('message-content-inline-status');
                if (bubbleMsgContent) bubbleMsgContent.classList.add('streaming-active');
            }
            fullText += textChunk;
            hasRenderableText = true;
            if (renderNow) {
                updateMessage(bubbleId, fullText);
            } else {
                _scheduleStreamRender();
            }
            return true;
        }
        // Collected tool calls for this response
        const collectedToolCalls = [];
        // Live tool card instances for rendering
        const _liveToolCards = [];
        // Container for tool cards  lives inside the thinking dropdown
        function _getToolCardsContainer() {
            let container = bubbleRow?.querySelector('.message-runtime-cards');
            if (container) return container;
            container = document.createElement('div');
            container.className = 'message-runtime-cards hidden';
            if (bubbleRow) {
                bubbleRow.appendChild(container);
            } else if (bubbleMsgContent) {
                bubbleMsgContent.appendChild(container);
            }
            return container;
        }

        function _ensureTaskUi(summaryText = '') {
            if (!_taskUiSeeded) {
                _taskUiSeeded = true;
                chatTaskMessageBySessionId.set(_taskUiSessionId, bubbleId);
                updateMessageTaskStrip(bubbleId, {
                    sessionId: _taskUiSessionId,
                    status: 'spawning',
                    summary: summaryText || 'Task accepted.',
                    checkpoint: 'Task accepted.',
                });
            }
        }
        const _promptTaskSeed = chatShouldSeedTaskUi(safeString(payload?.message || userContext));
        if (_promptTaskSeed) {
            const promptSummary = officeTaskTitle(safeString(payload?.message || userContext));
            _ensureTaskUi(promptSummary);
            updateMessageTaskStrip(bubbleId, {
                sessionId: _taskUiSessionId,
                status: 'defining',
                summary: promptSummary,
                checkpoint: 'Task received. Defining what a good result looks like.',
            });
        }

        function _syncDelegationWorkerVisual(evt, status, taskText) {
            if (!officeEnsureState()) return;
            officeStartLoop();
            const activityId = _delegationActivityId(evt);
            const terminal = _delegationIsTerminalState(status);
            const existingTaskId = safeString(_officeDelegationTaskByActivity.get(activityId));
            if (!terminal && !existingTaskId) {
                const preferredIdentity = officeResolveAgentIdentity(evt.bot_name || evt.bot_id || evt.agent_id || evt.specialist_id, activityId);
                const preferredAgent = officeFindAgentByHandle(preferredIdentity.name);
                const previewSessionId = safeString(evt?.session_id) || _delegationSessionId || safeString(activeChatId) || 'chat';
                const queuedTask = officeQueueTask(taskText, {
                    source: `chat-delegation:${previewSessionId}:${activityId}`,
                    announce: false,
                    preferredAgentId: preferredAgent?.id || '',
                });
                if (queuedTask?.id) {
                    _officeDelegationTaskByActivity.set(activityId, queuedTask.id);
                    chatAgentPresenceSetOfficeContext(activityId, {
                        taskId: queuedTask.id,
                        agentId: safeString(queuedTask.assignedAgentId || preferredAgent?.id),
                        agentName: safeString(preferredAgent?.name || preferredIdentity.name),
                    });
                }
                return;
            }
            if (!terminal || !existingTaskId || !officeState) return;
            const linkedTask = officeState.tasks.find((task) => task.id === existingTaskId);
            if (!linkedTask) return;
            linkedTask.status = 'done';
            linkedTask.completedAt = Date.now();
            if (linkedTask.assignedAgentId) {
                const agent = officeGetAgentById(linkedTask.assignedAgentId);
                if (agent) {
                    officeBeginTeleportSequence(agent, performance.now());
                }
            }
            officeState.tasksDirty = true;
            const completedIdentity = officeResolveAgentIdentity(evt.bot_name || evt.bot_id || evt.agent_id || evt.specialist_id, activityId);
            chatAgentPresenceSetOfficeContext(activityId, {
                taskId: linkedTask.id,
                agentId: linkedTask.assignedAgentId,
                agentName: safeString(linkedTask.assignedAgentId ? officeGetAgentById(linkedTask.assignedAgentId)?.name : '') || completedIdentity.name,
            });
        }

        function _delegationActivityId(evt) {
            return safeString(evt.execution_id || evt.task_id || evt.bot_id || evt.bot_name || evt.agent_id || evt.specialist_id || evt.backend_type || 'worker');
        }
        function _delegationLabel(evt) {
            return safeString(evt.bot_name || evt.bot_id || evt.agent_id || evt.specialist_id || evt.backend_type || 'worker');
        }
        function _delegationTask(evt) {
            const detail = safeString(evt.summary || evt.last_progress || evt.text || evt.task || evt.current_task);
            const backend = safeString(evt.backend_type);
            if (backend && detail) return `[${backend}] ${detail}`;
            return detail || backend || '';
        }
        const _delegationStateCache = new Map();
        const _delegationSessionId = safeString(sessionId || activeChatId || taskContinuityLatestSessionId);
        let _delegationPollTimer = 0;
        let _delegationPolling = false;
        let _delegationShouldPollAfterStream = false;

        function _delegationIsTerminalState(state) {
            const normalized = safeString(state).toLowerCase();
            return normalized === 'completed' || normalized === 'failed' || normalized === 'abandoned';
        }
        function _delegationEventTypeForState(state) {
            return _delegationIsTerminalState(state)
                ? (safeString(state).toLowerCase() === 'completed' ? 'delegation_completed' : 'delegation_failed')
                : 'delegation_progress';
        }
        function _stopDelegationPolling() {
            if (_delegationPollTimer) {
                clearTimeout(_delegationPollTimer);
                _delegationPollTimer = 0;
            }
        }
        function _scheduleDelegationPoll(delayMs = 2500) {
            _stopDelegationPolling();
            if (!_delegationSessionId) return;
            _delegationPollTimer = setTimeout(() => {
                void _pollDelegationStatus();
            }, Math.max(250, Number(delayMs) || 2500));
        }
        async function _pollDelegationStatus() {
            if (_delegationPolling || !_delegationSessionId) return;
            _delegationPolling = true;
            try {
                const resp = await fetchJsonSafe(`/api/v2/chat/session/${encodeURIComponent(_delegationSessionId)}/delegations`);
                if (!resp.ok) {
                    _scheduleDelegationPoll(4000);
                    return;
                }
                const payload = resp.data && typeof resp.data === 'object' ? resp.data : {};
                const delegations = Array.isArray(payload.delegations) ? payload.delegations : [];
                delegations.forEach((row) => {
                    if (!row || typeof row !== 'object') return;
                    _handleDelegationLifecycle({
                        ...row,
                        type: _delegationEventTypeForState(row.state),
                        bot_name: safeString(row.bot_name || row.bot_id),
                    });
                });
                if (delegations.some((row) => !_delegationIsTerminalState(row?.state))) {
                    _scheduleDelegationPoll(2500);
                } else {
                    _stopDelegationPolling();
                }
            } catch (error) {
                console.warn('Delegation status poll failed', error);
                _scheduleDelegationPoll(4000);
            } finally {
                _delegationPolling = false;
            }
        }
        function _handleDelegationLifecycle(evt) {
            const evtType = safeString(evt.type);
            const label = _delegationLabel(evt);
            const badgeKey = safeString(evt.specialist_id || label || 'worker').toLowerCase().replace(/\s+/g, '_');
            const activityId = _delegationActivityId(evt);
            const taskText = _delegationTask(evt) || label;
            const status = evtType === 'delegation_completed'
                ? 'completed'
                : evtType === 'delegation_failed'
                    ? 'failed'
                    : safeString(evt.state) || 'running';
            const cacheKey = `${activityId}::${status}::${taskText}`;
            const alreadySeen = _delegationStateCache.get(activityId) === cacheKey;
            _delegationStateCache.set(activityId, cacheKey);
            const helperIdentity = officeResolveAgentIdentity(label, activityId);
            const container = _getToolCardsContainer();
            if (evtType === 'delegation_started') {
                container.appendChild(createDelegationBadge(badgeKey, taskText));
            }
            upsertAgentActivity(container, activityId, status, taskText, 0);
            _ensureTaskUi(taskText || label);
            chatAgentPresenceUpsert(activityId, {
                kind: 'delegation',
                sessionId: safeString(evt?.session_id) || _taskUiSessionId,
                bubbleId,
                name: helperIdentity.name || 'worker',
                status,
                taskText,
                summary: taskText || label,
                startedAt: missionToEpoch(safeString(evt?.created_at || evt?.updated_at)) || Date.now(),
                color: helperIdentity.color || '#9ad8ff',
                costume: helperIdentity.costume || 'none',
                officeAgentName: helperIdentity.name,
                officeAgentId: helperIdentity.id,
            });
            _syncDelegationWorkerVisual(evt, status, taskText);
            if (!_delegationIsTerminalState(status)) {
                _delegationShouldPollAfterStream = true;
            }
            void refreshTaskContinuity({ sessionOverride: _delegationSessionId, force: true });
            if (!hasRenderableText) {
                if (!robotSayingInterval) _startRobotStatus();
                currentRobotCategory = 'working';
                _setRobotSaying(evtType === 'delegation_started' ? 'delegation-started' : 'delegation-progress');
            }
            if (!alreadySeen) {
                const prefix = evtType === 'delegation_completed'
                    ? 'Background task completed'
                    : evtType === 'delegation_failed'
                        ? 'Background task failed'
                        : 'Background task';
                updateMessageTaskStrip(bubbleId, {
                    sessionId: safeString(evt?.session_id) || _taskUiSessionId,
                    status: _taskUiTerminated ? 'completed' : 'executing',
                    summary: taskText || label,
                    checkpoint: `${prefix}: ${taskText || label}`,
                });
                thinkingText += `\n${prefix}: ${taskText}`;
            }
        }

        function _taskContractStatusForEvent(evt) {
            const evtType = safeString(evt?.type);
            if (evtType === 'task_evaluation') {
                const evaluationStatus = safeString(evt?.evaluation?.status).toLowerCase();
                if (evaluationStatus === 'passed') return 'completed';
                if (evaluationStatus === 'failed') return 'failed';
                return 'completed';
            }
            const phase = safeString(evt?.phase || evt?.status || evt?.task_definition_status).toLowerCase();
            if (phase === 'defining') return 'defining';
            if (phase === 'executing') return 'executing';
            if (phase === 'evaluating') return 'evaluating';
            if (phase === 'complete' || phase === 'completed' || phase === 'passed') return 'completed';
            if (phase === 'failed' || phase === 'blocked') return 'failed';
            return 'running';
        }
        function _taskContractSummaryForEvent(evt) {
            const evtType = safeString(evt?.type);
            if (evtType === 'task_definition') {
                return safeString(evt?.definition?.task_summary)
                    || safeString(evt?.definition?.good_result_definition)
                    || 'Defining what a good result looks like.';
            }
            if (evtType === 'task_evaluation') {
                return safeString(evt?.evaluation?.summary)
                    || (safeString(evt?.evaluation?.status).toLowerCase() === 'failed'
                        ? 'Task failed the visible quality bar.'
                        : 'Task evaluation completed.');
            }
            const phase = safeString(evt?.phase).toLowerCase();
            if (phase === 'defining') return 'Defining what a good result looks like.';
            if (phase === 'executing') return 'Working the task in the background.';
            if (phase === 'evaluating') return 'Evaluating the result against the task contract.';
            return safeString(evt?.label) || 'Working the task in the background.';
        }
        function _handleTaskContractLifecycle(evt) {
            const sessionToken = safeString(evt?.session_id) || _delegationSessionId || safeString(activeChatId) || 'chat';
            const status = _taskContractStatusForEvent(evt);
            const taskText = _taskContractSummaryForEvent(evt);
            if (!taskText) return;
            _ensureTaskUi(taskText);
            const pseudoEvt = {
                execution_id: _taskContractActivityId,
                session_id: sessionToken,
                bot_name: 'Task Bot',
                backend_type: 'task-contract',
                state: status,
                summary: taskText,
                last_progress: taskText,
            };
            const container = _getToolCardsContainer();
            upsertAgentActivity(container, _taskContractActivityId, status, taskText, 0);
            _syncDelegationWorkerVisual(pseudoEvt, status, taskText);
            const checkpoint = evt?.type === 'task_definition'
                ? 'Locked the task definition.'
                : evt?.type === 'task_evaluation'
                    ? `Evaluation ${safeString(evt?.evaluation?.status).toLowerCase() === 'failed' ? 'failed' : 'completed'}.`
                    : chatTaskStatusLabel(status);
            updateMessageTaskStrip(bubbleId, {
                sessionId: sessionToken,
                status,
                summary: taskText,
                checkpoint,
            });
            if (chatTaskIsTerminal(status)) {
                _taskUiTerminated = true;
            }
            if (!hasRenderableText && status !== 'completed' && status !== 'failed') {
                if (!robotSayingInterval) _startRobotStatus();
                currentRobotCategory = 'working';
                _setRobotSaying('delegation-progress');
            }
        }

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const evt = JSON.parse(line);
                        const evtType = safeString(evt.type);
                        const evtText = streamChunkString(evt.text || evt.delta || evt.content);
                        if (evt.type === 'timing') {
                            console.log(`[timing] ${evt.label}: ${evt.elapsed_ms}ms`);
                        } else if (evt.type === 'ui_state_patch') {
                            applyUiStatePatchEvent(evt);
                        } else if (evt.type === 'model_switch') {
                            applyProfileSelection(evt.profile);
                        } else if (evt.type === 'model_runtime') {
                            const runtime = safeString(evt.runtime);
                            if (runtime) pushDebugEvent('chat', `Model runtime: ${runtime}`);
                        } else if (evt.type === 'journal_status') {
                            const status = safeString(evt.status) || 'unknown';
                            pushDebugEvent('chat', `Journal status: ${status}`);
                        } else if (evt.type === 'task_phase') {
                            _handleTaskContractLifecycle(evt);
                            taskContinuityLatestTaskDefinitionStatus = safeString(evt.phase) || taskContinuityLatestTaskDefinitionStatus;
                            renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, safeString(evt.session_id) || taskContinuityLatestSessionId, {
                                activity: taskContinuityLatestActivity,
                                taskDefinition: taskContinuityLatestTaskDefinition,
                                taskEvaluation: taskContinuityLatestTaskEvaluation,
                                taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
                            });
                        } else if (evt.type === 'task_definition') {
                            _handleTaskContractLifecycle(evt);
                            taskContinuityLatestTaskDefinition = evt.definition && typeof evt.definition === 'object' ? evt.definition : null;
                            taskContinuityLatestTaskDefinitionStatus = safeString(evt.status) || 'defining';
                            renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, safeString(evt.session_id) || taskContinuityLatestSessionId, {
                                activity: taskContinuityLatestActivity,
                                taskDefinition: taskContinuityLatestTaskDefinition,
                                taskEvaluation: taskContinuityLatestTaskEvaluation,
                                taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
                            });
                        } else if (evt.type === 'task_evaluation') {
                            _handleTaskContractLifecycle(evt);
                            taskContinuityLatestTaskEvaluation = evt.evaluation && typeof evt.evaluation === 'object' ? evt.evaluation : null;
                            taskContinuityLatestTaskDefinitionStatus = safeString(evt.task_definition_status) || 'complete';
                            renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, safeString(evt.session_id) || taskContinuityLatestSessionId, {
                                activity: taskContinuityLatestActivity,
                                taskDefinition: taskContinuityLatestTaskDefinition,
                                taskEvaluation: taskContinuityLatestTaskEvaluation,
                                taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
                            });
                        } else if (evt.type === 'vibe_graph') {
                            vibeCodeHandleGraphEvent(evt);
                        } else if (evt.type === 'vibe_trace') {
                            vibeCodeHandleTraceEvent(evt);
                        } else if (evt.type === 'text' && evt.text) {
                            _consumeAssistantChunk(evt.text);
                        } else if (evtType === 'agent_text' && evtText) {
                            _consumeAssistantChunk(evtText);
                        } else if (['assistant_delta', 'delta', 'message_delta'].includes(evtType) && evtText) {
                            _consumeAssistantChunk(evtText);
                        } else if (evt.type === 'done') {
                            streamDone = true;
                            if (!fullText.trim()) {
                                const doneText = streamChunkString(evt.text || evt.final || evt.output_text);
                                if (doneText) _consumeAssistantChunk(doneText);
                            }
                        } else if (evt.type === 'error') {
                            if (!hasRenderableText) _clearRobotStatus();
                            if (bubbleMsgContent) bubbleMsgContent.classList.remove('streaming-active');
                            bubbleRow?.classList.remove('message-row-inline-status');
                            const errorText = safeString(evt.error) || 'Unknown stream error.';
                            fullText += `\n\n**Error:** ${errorText}`;
                            hasRenderableText = true;
                            updateMessage(bubbleId, fullText);
                        } else if (evt.type === 'guardrails') {
                            void missionRefresh({ force: true, silent: true });
                        } else if (evt.type === 'tool_start') {
                            collectedToolCalls.push({ name: safeString(evt.name), args: null, result: null });
                            // Render a collapsible tool card
                            const tc = createToolCallCard(safeString(evt.name));
                            _liveToolCards.push(tc);
                            _getToolCardsContainer().appendChild(tc.card);
                            if (!hasRenderableText) {
                                if (!robotSayingInterval) _startRobotStatus();
                                currentRobotCategory = 'working';
                                _setRobotSaying('tool');
                            }
                        } else if (evt.type === 'tool_args' && collectedToolCalls.length > 0) {
                            const last = collectedToolCalls[collectedToolCalls.length - 1];
                            last.args = evt.args || evt.data || null;
                            // Update the latest tool card with args
                            if (_liveToolCards.length > 0) {
                                _liveToolCards[_liveToolCards.length - 1].setArgs(last.args);
                            }
                        } else if (evt.type === 'tool_result') {
                            if (collectedToolCalls.length > 0) {
                                const last = collectedToolCalls[collectedToolCalls.length - 1];
                                last.result = evt.result || evt.data || safeString(evt.text) || null;
                            }
                            // Update the latest tool card with result
                            if (_liveToolCards.length > 0) {
                                const lastCard = _liveToolCards[_liveToolCards.length - 1];
                                const resultData = evt.result || evt.data || safeString(evt.text) || '';
                                lastCard.setResult(resultData);
                            }
                            // Tool finished  back to generic working sayings
                            currentRobotCategory = 'working';
                        } else if (evt.type === 'thinking') {
                            // Accumulate real thinking/reasoning text (from LLM or synthetic)
                            const chunk = safeString(evt.text);
                            if (chunk) {
                                thinkingText += chunk;
                            }
                        } else if (evt.type === 'delegation') {
                            const specId = safeString(evt.specialist_id);
                            const task = safeString(evt.task);
                            if (specId) {
                                const badge = createDelegationBadge(specId, task);
                                _getToolCardsContainer().appendChild(badge);
                                const helperIdentity = officeResolveAgentIdentity(specId, specId);
                                chatAgentPresenceUpsert(specId, {
                                    kind: 'delegation',
                                    sessionId: safeString(evt?.session_id) || _taskUiSessionId || safeString(activeChatId) || 'chat',
                                    bubbleId,
                                    name: helperIdentity.name || specId,
                                    status: 'running',
                                    taskText: task,
                                    summary: task || `Helping with ${specId}`,
                                    startedAt: Date.now(),
                                    color: helperIdentity.color || '#9ad8ff',
                                    costume: helperIdentity.costume || 'none',
                                    officeAgentName: helperIdentity.name,
                                    officeAgentId: helperIdentity.id,
                                });
                                window.setTimeout(() => {
                                    const live = chatAgentPresenceStateByActivityId.get(specId);
                                    if (!live || chatTaskIsTerminal(live.status)) return;
                                    live.status = 'completed';
                                    live.summary = safeString(live.summary || task) || `Helper ${helperIdentity.name || specId} complete.`;
                                    chatRobotWorldRemoveHelper(specId);
                                }, 9000);
                                if (!hasRenderableText) {
                                    if (!robotSayingInterval) _startRobotStatus();
                                    currentRobotCategory = 'working';
                                    _setRobotSaying('delegation');
                                }
                                thinkingText += `\nDelegated to ${specId}: ${task}`;
                            }
                        } else if (evt.type === 'agent_activity') {
                            const agentId = safeString(evt.agent_id);
                            const agentStatus = safeString(evt.status);
                            const agentTask = safeString(evt.current_task);
                            const agentMs = parseInt(evt.elapsed_ms) || 0;
                            if (agentId) {
                                const container = _getToolCardsContainer();
                                upsertAgentActivity(container, agentId, agentStatus, agentTask, agentMs);
                                if (!hasRenderableText && agentStatus === 'running') {
                                    currentRobotCategory = 'working';
                                    _setRobotSaying('working');
                                }
                            }
                        } else if (['delegation_started', 'delegation_progress', 'delegation_completed', 'delegation_failed'].includes(evtType)) {
                            _handleDelegationLifecycle(evt);
                        } else if (evt.type === 'memory_refresh') {
                            const layer = safeString(evt.layer);
                            if (layer && !hasRenderableText) {
                                thinkingText += `\nMemory refresh: ${layer}`;
                                _setRobotSaying('memory');
                            }
                        } else if (evt.type === 'orchestrator_ack') {
                            // Orchestrator acknowledged  show status immediately
                            const ackMsg = safeString(evt.message);
                            if (ackMsg && !hasRenderableText) {
                                if (robotSayingInterval) _clearRobotStatus();
                                _startRobotStatus();
                                _setRobotSaying('working');
                            }
                        } else if (evt.type === 'route' || evt.type === 'task_update') {
                            if (!hasRenderableText) _startRobotStatus();
                        } else if (evt.type === 'iteration') {
                            if (!hasRenderableText && !robotSayingInterval) _startRobotStatus();
                        }
                    } catch (e) {
                        console.warn("Failed to parse stream line:", line, e);
                        if (bubbleMsgContent) bubbleMsgContent.classList.remove('streaming-active');
                    }
                }
            }
        } catch (abortErr) {
            if (abortErr.name === 'AbortError') {
                _clearRobotStatus();
                if (bubbleMsgContent) bubbleMsgContent.classList.remove('streaming-active');
                fullText += '\n\n*\\[Generation stopped\\]*';
                updateMessage(bubbleId, fullText, false);
            } else {
                // On any error, always clean up the streaming cursor
                if (bubbleMsgContent) bubbleMsgContent.classList.remove('streaming-active');
                throw abortErr;
            }
        }

        // Clean up robot status if still running
        _clearRobotStatus();
        currentAbortController = null;

        if (buffer.trim()) {
            try {
                const evt = JSON.parse(buffer);
                const evtType = safeString(evt.type);
                const evtText = streamChunkString(evt.text || evt.delta || evt.content);
                if (evt.type === 'ui_state_patch') {
                    applyUiStatePatchEvent(evt);
                } else if (evt.type === 'model_switch') {
                    applyProfileSelection(evt.profile);
                } else if (evt.type === 'model_runtime') {
                    const runtime = safeString(evt.runtime);
                    if (runtime) pushDebugEvent('chat', `Model runtime: ${runtime}`);
                } else if (evt.type === 'journal_status') {
                    const status = safeString(evt.status) || 'unknown';
                    pushDebugEvent('chat', `Journal status: ${status}`);
                } else if (evt.type === 'task_phase') {
                    _handleTaskContractLifecycle(evt);
                    taskContinuityLatestTaskDefinitionStatus = safeString(evt.phase) || taskContinuityLatestTaskDefinitionStatus;
                    renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, safeString(evt.session_id) || taskContinuityLatestSessionId, {
                        activity: taskContinuityLatestActivity,
                        taskDefinition: taskContinuityLatestTaskDefinition,
                        taskEvaluation: taskContinuityLatestTaskEvaluation,
                        taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
                    });
                } else if (evt.type === 'task_definition') {
                    _handleTaskContractLifecycle(evt);
                    taskContinuityLatestTaskDefinition = evt.definition && typeof evt.definition === 'object' ? evt.definition : null;
                    taskContinuityLatestTaskDefinitionStatus = safeString(evt.status) || 'defining';
                    renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, safeString(evt.session_id) || taskContinuityLatestSessionId, {
                        activity: taskContinuityLatestActivity,
                        taskDefinition: taskContinuityLatestTaskDefinition,
                        taskEvaluation: taskContinuityLatestTaskEvaluation,
                        taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
                    });
                } else if (evt.type === 'task_evaluation') {
                    _handleTaskContractLifecycle(evt);
                    taskContinuityLatestTaskEvaluation = evt.evaluation && typeof evt.evaluation === 'object' ? evt.evaluation : null;
                    taskContinuityLatestTaskDefinitionStatus = safeString(evt.task_definition_status) || 'complete';
                    renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, safeString(evt.session_id) || taskContinuityLatestSessionId, {
                        activity: taskContinuityLatestActivity,
                        taskDefinition: taskContinuityLatestTaskDefinition,
                        taskEvaluation: taskContinuityLatestTaskEvaluation,
                        taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
                    });
                } else if (evt.type === 'vibe_graph') {
                    vibeCodeHandleGraphEvent(evt);
                } else if (evt.type === 'vibe_trace') {
                    vibeCodeHandleTraceEvent(evt);
                } else if (evt.type === 'guardrails') {
                    void missionRefresh({ force: true, silent: true });
                } else if (evt.type === 'text' && evt.text) {
                    _consumeAssistantChunk(evt.text, { renderNow: true });
                } else if (evtType === 'agent_text' && evtText) {
                    _consumeAssistantChunk(evtText, { renderNow: true });
                } else if (['assistant_delta', 'delta', 'message_delta'].includes(evtType) && evtText) {
                    _consumeAssistantChunk(evtText, { renderNow: true });
                } else if (evt.type === 'done') {
                    streamDone = true;
                    if (!fullText.trim()) {
                        const doneText = streamChunkString(evt.text || evt.final || evt.output_text);
                        if (doneText) _consumeAssistantChunk(doneText, { renderNow: true });
                    }
                }
            } catch (ignore) { }
        }

        // Final render  remove streaming cursor
        if (bubbleMsgContent) bubbleMsgContent.classList.remove('streaming-active');

        if (hasRenderableText) {
            updateMessage(bubbleId, fullText, false);
            if (!robotLandedForThisResponse) _landRobotAtComposerDock();
        }
        if (_taskUiSeeded && !_taskUiTerminated && !_delegationShouldPollAfterStream) {
            updateMessageTaskStrip(bubbleId, {
                sessionId: _taskUiSessionId,
                status: 'completed',
                checkpoint: 'Assistant response finished.',
            });
            _taskUiTerminated = true;
        }

        let assistantFinalText = fullText;
        if (!fullText.trim()) {
            assistantFinalText = streamDone
                ? '_Finished, but no assistant text was returned._'
                : '_No text response yet. Still waiting on model output..._';
            updateMessage(bubbleId, assistantFinalText, false);
            showStarterSuggestionRail({ force: true });
            pushDebugEvent('chat', 'Completed chat request with empty response');
        } else {
            maybeShowAssistantFollowups({
                assistantText: fullText,
                userText: userContext,
            });
            pushDebugEvent('chat', `Completed chat request (${fullText.length} chars)`);
        }
        chatHistory.push({
            id: bubbleId,
            role: 'assistant',
            content: assistantFinalText,
            createdAt: Date.now(),
            status: 'complete',
            toolCalls: collectedToolCalls,
        });
        syncActiveChatSidebarEntry();
        void persistActiveChat({ quiet: true });

    } catch (err) {
        if (err.name === 'AbortError') {
            // Already handled in the inner catch
        } else {
            console.error(err);
        }
        if (bubbleMsgContent) bubbleMsgContent.classList.remove('streaming-active');
        currentAbortController = null;
        let errorMsg = err.name === 'AbortError' ? '' : (err.message || '');
        if (!errorMsg) {
            // Abort was handled inline  skip error rendering
        } else if (errorMsg.includes('SyntaxError')) {
            errorMsg = "Invalid JSON returned from server.";
        }
            if (errorMsg) {
            if (_taskUiSeeded) {
                updateMessageTaskStrip(bubbleId, {
                    sessionId: _taskUiSessionId,
                    status: 'failed',
                    checkpoint: errorMsg,
                });
                _taskUiTerminated = true;
            }
            const renderedError = `**Error connecting to ${escapeHtml(getAgentName())} backend.**\n\n\`${escapeHtml(errorMsg)}\``;
            renderMessage({ role: 'assistant', content: renderedError });
            chatHistory.push({
                id: `err-${Date.now()}`,
                role: 'assistant',
                content: renderedError,
                createdAt: Date.now(),
                status: 'complete',
                toolCalls: [],
            });
            syncActiveChatSidebarEntry();
            void persistActiveChat({ quiet: true });
            const trimmedError = safeString(errorMsg).replace(/^API Error \d+:\s*/i, '').slice(0, 220);
            notifyUser(trimmedError ? `Chat failed: ${trimmedError}` : 'Chat request failed.', {
                tone: 'error',
                durationMs: 3600,
            });
            pushDebugEvent('error', `Chat request failed: ${errorMsg}`);
            setAssistantSuggestions({
                title: 'Quick recovery',
                context: 'recovery',
                dismissible: true,
                options: [
                    {
                        label: 'Retry the request',
                        kind: 'action',
                        tone: 'primary',
                        send_prompt: 'Retry my previous request and explain what changed if it still fails.',
                    },
                    {
                        label: 'Diagnose backend issue',
                        kind: 'option',
                        send_prompt: 'Diagnose likely backend connectivity issues and give me concrete checks to run now.',
                    },
                    {
                        label: 'Open Easy Setup',
                        kind: 'option',
                        onChoose: async () => {
                            ensureChatVisible();
                            await openEasySetup({ source: 'error_recovery', force: true, restart: false });
                        },
                    },
                ],
            });
        }
    } finally {
        setGeneratingState(false);
        void refreshTaskContinuity({
            sessionOverride: safeString(payload?.session_id) || sessionId,
            force: true,
        });
        void drainQueuedSends();
    }
}

// ---------------------------------------------------------------------------
// Message editing + regeneration
// ---------------------------------------------------------------------------

/**
 * Enter edit mode on a user message row.
 * Replaces message content with a textarea + save/cancel buttons.
 */
function beginEditMessage(row) {
    if (isGenerating) return;
    if (row.classList.contains('message-editing')) return; // already editing

    const contentDiv = row.querySelector('.message-content');
    const stack = row.querySelector('.message-stack');
    if (!contentDiv) return;
    if (!stack) return;

    // Find this message in chatHistory by row id
    const msgId = row.id;
    const historyEntry = chatHistory.find(m => m.id === msgId);
    const originalText = historyEntry ? historyEntry.content : (contentDiv.innerText || contentDiv.textContent || '');
    // Strip the attachment annotation for editing
    const editText = originalText.replace(/\n\n\*\(Attached \d+ (?:document|image)\(s\)\)\*/g, '').trim();

    row.classList.add('message-editing');
    row.dataset.originalText = originalText;

    const textarea = document.createElement('textarea');
    textarea.className = 'msg-edit-textarea';
    textarea.value = editText;
    textarea.rows = Math.max(2, Math.min(12, editText.split('\n').length + 1));

    const btnBar = document.createElement('div');
    btnBar.className = 'msg-edit-actions';
    btnBar.innerHTML = `
        <button class="msg-edit-save" title="Save & resend">Save & Send</button>
        <button class="msg-edit-cancel" title="Cancel editing">Cancel</button>
    `;

    const panel = document.createElement('div');
    panel.className = 'message-edit-panel';
    panel.appendChild(textarea);
    panel.appendChild(btnBar);
    stack.appendChild(panel);

    btnBar.querySelector('.msg-edit-save')?.addEventListener('click', () => void commitEditMessage(row));
    btnBar.querySelector('.msg-edit-cancel')?.addEventListener('click', () => cancelEditMessage(row));

    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

    // Allow Escape to cancel, Ctrl+Enter to save
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            cancelEditMessage(row);
        } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            commitEditMessage(row);
        }
    });
}

/**
 * Cancel editing and restore original content.
 */
function cancelEditMessage(row) {
    if (!row.classList.contains('message-editing')) return;
    row.querySelector('.message-edit-panel')?.remove();
    row.classList.remove('message-editing');
    delete row.dataset.originalText;
}

/**
 * Commit an edited user message: truncate history after this message,
 * remove all subsequent DOM rows, and re-stream with edited text.
 */
async function commitEditMessage(row) {
    if (!row.classList.contains('message-editing')) return;
    const textarea = row.querySelector('.msg-edit-textarea');
    if (!textarea) return;

    const newText = textarea.value.trim();
    if (!newText) {
        cancelEditMessage(row);
        return;
    }

    const msgId = row.id;

    // 1. Find position in chatHistory
    const histIdx = chatHistory.findIndex(m => m.id === msgId);

    // 2. Truncate chatHistory after this message
    if (histIdx >= 0) {
        chatHistory.length = histIdx; // remove this message and all after
    }

    // 3. Remove all DOM rows from this message onward (including this one)
    let sibling = row;
    while (sibling) {
        const next = sibling.nextElementSibling;
        // Don't remove non-message elements (like the landed robot)
        if (sibling.classList.contains('message-row') || sibling.classList.contains('chat-robot-landed')) {
            sibling.remove();
        }
        sibling = next;
    }

    // 4. Re-render the edited user message
    const userContent = newText;
    renderMessage({ role: 'user', content: userContent, id: msgId });
    chatHistory.push({
        id: msgId,
        role: 'user',
        content: userContent,
        createdAt: Date.now(),
        status: 'complete',
        toolCalls: [],
    });
    syncActiveChatSidebarEntry();
    void persistActiveChat({ quiet: true });

    // 5. Build payload and stream new response
    setGeneratingState(true);
    pushDebugEvent('chat', 'Edited message  re-streaming response');

    let finalPrompt = setupPersonalitySelector.value;
    if (finalPrompt === 'custom') {
        finalPrompt = setupCustomPrompt.value.trim();
    }
    const selectedProfile = modelSelector.value || setupProviderSelector.value;
    const studioChatContext = typeof moduleStudioBuildChatContext === 'function' ? moduleStudioBuildChatContext() : { enabled: false, preferredProfile: '', context: {} };
    const preferredProfile = safeString(studioChatContext.preferredProfile);
    const resolvedProfile = preferredProfile || selectedProfile;
    if (preferredProfile && preferredProfile !== safeString(selectedProfile) && typeof applyProfileSelection === 'function') {
        applyProfileSelection(preferredProfile);
    }
    const payload = buildChatRequestPayload(newText, {
        docs: [],
        images: [],
        systemPrompt: finalPrompt || undefined,
        resolvedProfile,
        studioChatContext,
    });

    await streamChatResponse(payload, { userContext: newText });
}

/**
 * Regenerate an assistant response: remove it and re-stream from the
 * preceding user message.
 */
async function regenerateResponse(row) {
    if (isGenerating) return;

    const msgId = row.id;
    const histIdx = chatHistory.findIndex(m => m.id === msgId);
    if (histIdx < 0) return;

    // Find the preceding user message
    let userIdx = -1;
    for (let i = histIdx - 1; i >= 0; i--) {
        if (chatHistory[i].role === 'user') {
            userIdx = i;
            break;
        }
    }
    if (userIdx < 0) return; // No user message to regenerate from

    const userMsg = chatHistory[userIdx];

    // Truncate everything after (and including) the assistant message
    chatHistory.length = histIdx;

    // Remove DOM rows from the assistant message onward
    let sibling = row;
    while (sibling) {
        const next = sibling.nextElementSibling;
        if (sibling.classList.contains('message-row') || sibling.classList.contains('chat-robot-landed')) {
            sibling.remove();
        }
        sibling = next;
    }

    syncActiveChatSidebarEntry();
    void persistActiveChat({ quiet: true });

    // Build payload and stream new response
    setGeneratingState(true);
    pushDebugEvent('chat', 'Regenerating assistant response');

    let finalPrompt = setupPersonalitySelector.value;
    if (finalPrompt === 'custom') {
        finalPrompt = setupCustomPrompt.value.trim();
    }
    const selectedProfile = modelSelector.value || setupProviderSelector.value;
    const studioChatContext = typeof moduleStudioBuildChatContext === 'function' ? moduleStudioBuildChatContext() : { enabled: false, preferredProfile: '', context: {} };
    const preferredProfile = safeString(studioChatContext.preferredProfile);
    const resolvedProfile = preferredProfile || selectedProfile;
    if (preferredProfile && preferredProfile !== safeString(selectedProfile) && typeof applyProfileSelection === 'function') {
        applyProfileSelection(preferredProfile);
    }
    const payload = buildChatRequestPayload(userMsg.content, {
        docs: [],
        images: [],
        systemPrompt: finalPrompt || undefined,
        resolvedProfile,
        studioChatContext,
    });

    await streamChatResponse(payload, { userContext: userMsg.content });
}

// ---------------------------------------------------------------------------
// Conversation management: export, search, pin
// ---------------------------------------------------------------------------

/**
 * Export the current chat conversation as a downloadable file.
 * @param {'markdown'|'json'} [format='markdown']
 */
function exportChatConversation(format = 'markdown') {
    if (chatHistory.length === 0) {
        showToast('Nothing to export  conversation is empty.');
        return;
    }

    let content, filename, mimeType;
    const ts = new Date().toISOString().slice(0, 10);

    if (format === 'json') {
        content = JSON.stringify(chatHistory, null, 2);
        filename = `thomas-chat-${ts}.json`;
        mimeType = 'application/json';
    } else {
        // Markdown format
        const lines = [`# Thomas Chat Export  ${ts}\n`];
        for (const msg of chatHistory) {
            const role = msg.role === 'user' ? '**You**' : '**Thomas**';
            lines.push(`### ${role}`);
            lines.push(msg.content || '_(empty)_');
            lines.push('');
        }
        content = lines.join('\n');
        filename = `thomas-chat-${ts}.md`;
        mimeType = 'text/markdown';
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
    showToast(`Exported as ${filename}`);
}

/**
 * In-conversation search: find messages matching a query.
 */
let _chatSearchState = { visible: false, query: '', matches: [], current: -1 };

function toggleChatSearch() {
    const bar = document.getElementById('chatSearchBar');
    if (!bar) return;
    _chatSearchState.visible = !_chatSearchState.visible;
    bar.classList.toggle('visible', _chatSearchState.visible);
    if (_chatSearchState.visible) {
        const input = bar.querySelector('input');
        if (input) input.focus();
    } else {
        _clearSearchHighlights();
    }
}

function _performChatSearch(query) {
    _clearSearchHighlights();
    _chatSearchState.query = query;
    _chatSearchState.matches = [];
    _chatSearchState.current = -1;

    if (!query.trim()) {
        _updateSearchCount();
        return;
    }

    const lowerQ = query.toLowerCase();
    const rows = chatMessagesInner ? chatMessagesInner.querySelectorAll('.message-row') : [];
    rows.forEach(row => {
        const content = row.querySelector('.message-content');
        if (content && (content.textContent || '').toLowerCase().includes(lowerQ)) {
            _chatSearchState.matches.push(row);
        }
    });

    if (_chatSearchState.matches.length > 0) {
        _chatSearchState.current = 0;
        _highlightSearchMatch();
    }
    _updateSearchCount();
}

function _navigateSearch(dir) {
    if (_chatSearchState.matches.length === 0) return;
    _chatSearchState.matches[_chatSearchState.current]?.classList.remove('search-highlight');
    _chatSearchState.current = (_chatSearchState.current + dir + _chatSearchState.matches.length) % _chatSearchState.matches.length;
    _highlightSearchMatch();
    _updateSearchCount();
}

function _highlightSearchMatch() {
    const row = _chatSearchState.matches[_chatSearchState.current];
    if (!row) return;
    row.classList.add('search-highlight');
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

