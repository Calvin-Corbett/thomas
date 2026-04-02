function renderDebugOnboardingGatePanel(payloadRaw) {
    if (debugOnboardingGateStatusPill) debugOnboardingGateStatusPill.textContent = '-';
    if (debugOnboardingCompletionRate) debugOnboardingCompletionRate.textContent = '-';
    if (debugOnboardingMedianReadySeconds) debugOnboardingMedianReadySeconds.textContent = '-';

    const payload = payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : null;
    if (!payload) {
        setDebugOnboardingRepairButtonState({
            visible: debugOnboardingRepairInFlight,
            enabled: false,
            label: debugOnboardingRepairInFlight ? 'Repairing...' : 'Repair Now',
        });
        setDebugStatusNode(debugOnboardingGateStatus, 'Use Refresh to fetch onboarding diagnostics.');
        debugRenderEmpty(debugOnboardingGateList, 'No onboarding diagnostics loaded yet.');
        return;
    }

    const gate = payload?.gate && typeof payload.gate === 'object' ? payload.gate : {};
    const summary = payload?.onboarding_summary && typeof payload.onboarding_summary === 'object'
        ? payload.onboarding_summary
        : (gate?.summary && typeof gate.summary === 'object' ? gate.summary : {});
    const thresholds = gate?.thresholds && typeof gate.thresholds === 'object' ? gate.thresholds : {};
    const errors = Array.isArray(payload?.errors) ? payload.errors : [];
    const warnings = Array.isArray(payload?.warnings) ? payload.warnings : [];

    const ok = payload?.ok === true;
    const strict = Boolean(payload?.strict);
    const windowDays = Number(payload?.window_days || 0);
    const events = Number(summary?.events || 0);
    const completionRate = Number(summary?.completion_rate || 0);
    const recoveryAttempts = Number(summary?.recovery_attempts || 0);
    const recoverySuccessRate = Number(summary?.recovery_success_rate || 0);
    const completedWithTiming = Number(summary?.completed_journeys_with_timing || 0);
    const medianReadySeconds = Number(summary?.median_time_to_ready_seconds || 0);

    const minEvents = Number(thresholds?.min_events_for_quality_thresholds || 0);
    const minCompletionRate = Number(thresholds?.min_completion_rate || 0);
    const minRecoverySuccessRate = Number(thresholds?.min_recovery_success_rate || 0);
    const maxMedianReadySeconds = Number(thresholds?.max_median_time_to_ready_seconds || 0);

    const sampleReady = Number.isFinite(events) && Number.isFinite(minEvents) && events >= minEvents;
    const tone = errors.length > 0 ? 'error' : (warnings.length > 0 ? 'warn' : (ok ? 'ok' : 'warn'));
    const gateLabel = errors.length > 0 ? 'fail' : (warnings.length > 0 ? 'warn' : (ok ? 'pass' : 'check'));
    const needsRepairAction = errors.length > 0 || warnings.length > 0;
    setDebugOnboardingRepairButtonState({
        visible: needsRepairAction || debugOnboardingRepairInFlight,
        enabled: needsRepairAction && !debugOnboardingRepairInFlight,
        label: debugOnboardingRepairInFlight ? 'Repairing...' : 'Repair Now',
    });

    if (debugOnboardingGateStatusPill) debugOnboardingGateStatusPill.textContent = gateLabel;
    if (debugOnboardingCompletionRate) debugOnboardingCompletionRate.textContent = formatDebugPercent(completionRate, 1);
    if (debugOnboardingMedianReadySeconds) {
        debugOnboardingMedianReadySeconds.textContent = Number.isFinite(medianReadySeconds)
            ? medianReadySeconds.toFixed(1)
            : '-';
    }

    let statusText = `Window ${windowDays || '-'}d | events ${Number.isFinite(events) ? events : 0}`;
    if (errors.length > 0) {
        statusText = `Gate failed: ${safeString(errors[0]) || 'threshold violations detected.'}`;
    } else if (warnings.length > 0) {
        statusText = `Gate warning: ${safeString(warnings[0]) || 'sample not yet sufficient.'}`;
    } else if (ok) {
        statusText = 'Onboarding KPI thresholds passing for current telemetry window.';
    }
    setDebugStatusNode(debugOnboardingGateStatus, statusText, tone);

    if (!debugOnboardingGateList) return;
    debugOnboardingGateList.innerHTML = '';
    const frag = document.createDocumentFragment();

    const completionTone = !sampleReady
        ? 'warn'
        : (completionRate >= minCompletionRate ? 'ok' : 'error');
    const recoveryTone = !sampleReady || recoveryAttempts <= 0
        ? 'warn'
        : (recoverySuccessRate >= minRecoverySuccessRate ? 'ok' : 'error');
    const medianTone = !sampleReady || completedWithTiming <= 0
        ? 'warn'
        : (medianReadySeconds <= maxMedianReadySeconds ? 'ok' : 'error');

    frag.appendChild(debugCreateItemCard({
        title: 'Gate Verdict',
        pill: gateLabel,
        pillTone: tone,
        meta: [
            `strict mode: ${strict ? 'on' : 'off'}`,
            `sample readiness: ${sampleReady ? 'threshold checks active' : `insufficient sample (events=${events}, required>=${minEvents})`}`,
            `errors: ${errors.length} | warnings: ${warnings.length}`,
        ],
    }));

    frag.appendChild(debugCreateItemCard({
        title: 'Completion Rate',
        pill: formatDebugPercent(completionRate, 1),
        pillTone: completionTone,
        meta: [
            `target: >= ${formatDebugPercent(minCompletionRate, 1)}`,
            `opened: ${Number(summary?.wizard_opened || 0)} | completed: ${Number(summary?.onboarding_completed || 0)}`,
        ],
    }));

    frag.appendChild(debugCreateItemCard({
        title: 'Recovery Success',
        pill: formatDebugPercent(recoverySuccessRate, 1),
        pillTone: recoveryTone,
        meta: [
            `target: >= ${formatDebugPercent(minRecoverySuccessRate, 1)}`,
            `attempts: ${recoveryAttempts} | succeeded: ${Number(summary?.recovery_succeeded || 0)}`,
        ],
    }));

    frag.appendChild(debugCreateItemCard({
        title: 'Median Time-To-Ready',
        pill: Number.isFinite(medianReadySeconds) ? `${medianReadySeconds.toFixed(1)}s` : '-',
        pillTone: medianTone,
        meta: [
            `target: <= ${Number.isFinite(maxMedianReadySeconds) ? maxMedianReadySeconds.toFixed(1) : '-'}s`,
            `completed journeys with timing: ${completedWithTiming}`,
        ],
    }));

    if (errors.length > 0) {
        frag.appendChild(debugCreateItemCard({
            title: 'Top Gate Error',
            pill: 'action required',
            pillTone: 'error',
            meta: [safeString(errors[0]) || 'Unknown onboarding gate error'],
        }));
    } else if (warnings.length > 0) {
        frag.appendChild(debugCreateItemCard({
            title: 'Top Gate Warning',
            pill: 'warning',
            pillTone: 'warn',
            meta: [safeString(warnings[0]) || 'Unknown onboarding gate warning'],
        }));
    }

    debugOnboardingGateList.appendChild(frag);
}

async function runDebugOnboardingRepairNow() {
    if (debugOnboardingRepairInFlight) return;
    debugOnboardingRepairInFlight = true;
    setDebugOnboardingRepairButtonState({
        visible: true,
        enabled: false,
        label: 'Repairing...',
    });
    setDebugStatusNode(
        debugOnboardingGateStatus,
        'Running setup repair. You may need to approve system installer prompts.',
        'warn',
    );
    pushDebugEvent('setup', 'Triggered onboarding repair from Tools Console.');
    emitOnboardingTelemetry('repair.triggered', { trigger: 'tools_console_gate' });

    try {
        const res = await fetchJsonSafe('/api/setup/repair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                auto_install_tools: true,
                skip_install: false,
                skip_doctor: false,
            }),
        });

        if (!res.ok || !res.data) {
            const reason = safeString(res.data?.error) || safeString(res.text) || 'Repair call failed.';
            setDebugStatusNode(
                debugOnboardingGateStatus,
                `${reason} Remediation: run repair from command line and retry.`,
                'error',
            );
            emitOnboardingTelemetry('wizard.download_approval_failed', {
                trigger: 'tools_console_gate',
                error: reason,
            });
            notifyUser(`Setup repair failed: ${reason}`, {
                tone: 'error',
                durationMs: 3200,
                debugKind: 'error',
            });
            pushDebugEvent('setup', `Onboarding repair failed: ${reason}`);
            return;
        }

        if (!Boolean(res.data?.ok)) {
            const errorMsg = safeString(res.data?.error) || `Repair exited with code ${res.data?.exit_code}.`;
            const stderrTail = safeString(res.data?.stderr_tail);
            const finalMsg = stderrTail ? `${errorMsg} ${stderrTail}` : errorMsg;
            setDebugStatusNode(
                debugOnboardingGateStatus,
                `${finalMsg} Remediation: approve prompts and retry.`,
                'error',
            );
            emitOnboardingTelemetry('wizard.download_approval_failed', {
                trigger: 'tools_console_gate',
                error: errorMsg,
            });
            notifyUser(`Setup repair failed: ${errorMsg}`, {
                tone: 'error',
                durationMs: 3200,
                debugKind: 'error',
            });
            pushDebugEvent('setup', `Onboarding repair failed: ${errorMsg}`);
            return;
        }

        const reportPath = safeString(res.data?.report_path);
        const successText = reportPath
            ? `Repair completed. Report: ${reportPath}`
            : 'Repair completed successfully.';
        setDebugStatusNode(debugOnboardingGateStatus, successText, 'ok');
        emitOnboardingTelemetry('wizard.download_approved', {
            trigger: 'tools_console_gate',
            report_path: reportPath,
        });
        notifyUser('Setup repair completed. Refreshing onboarding diagnostics.', {
            tone: 'success',
            durationMs: 2500,
            debugKind: 'setup',
        });
        pushDebugEvent('setup', successText);
    } catch (error) {
        const reason = safeString(error?.message) || 'unknown repair error';
        setDebugStatusNode(debugOnboardingGateStatus, `Setup repair failed: ${reason}`, 'error');
        emitOnboardingTelemetry('wizard.download_approval_failed', {
            trigger: 'tools_console_gate',
            error: reason,
        });
        notifyUser(`Setup repair failed: ${reason}`, {
            tone: 'error',
            durationMs: 3200,
            debugKind: 'error',
        });
        pushDebugEvent('setup', `Onboarding repair failed: ${reason}`);
    } finally {
        debugOnboardingRepairInFlight = false;
        await refreshDebugLiveData({ force: true, reason: 'manual' });
    }
}

function renderDebugSystemPanel() {
    const payload = debugLiveCache.system;
    if (!payload) {
        if (debugSystemVersion) debugSystemVersion.textContent = '-';
        if (debugSystemReady) debugSystemReady.textContent = '-';
        if (debugSystemEngineCount) debugSystemEngineCount.textContent = '0';
        setDebugSystemStatus('Use Refresh to fetch system status.');
        debugRenderEmpty(debugSystemEngineList, 'No engine data yet.');
        renderDebugOnboardingGatePanel(null);
        return;
    }

    const version = safeString(payload?.version?.version || payload?.version);
    const bootstrap = payload?.bootstrap || {};
    const quickStart = bootstrap?.quick_start || {};
    const recommendedPath = safeString(quickStart?.recommended_path).toLowerCase() || '-';
    const reason = safeString(quickStart?.reason);
    const enginesRaw = payload?.engines || {};
    const engineRows = parseEngineRows(enginesRaw);
    const healthyEngines = engineRows.filter((engine) => engine.running && !engine.error).length;

    if (debugSystemVersion) debugSystemVersion.textContent = version || '-';
    if (debugSystemReady) debugSystemReady.textContent = recommendedPath || '-';
    if (debugSystemEngineCount) debugSystemEngineCount.textContent = String(engineRows.length);

    if (!engineRows.length) {
        setDebugSystemStatus(reason || 'Engine manager unavailable.', 'warn');
        debugRenderEmpty(debugSystemEngineList, 'No engine rows returned.');
        renderDebugOnboardingGatePanel(payload?.onboarding_gate || null);
        return;
    }

    const hasEngineErrors = engineRows.some((engine) => safeString(engine.error));
    const allRunning = healthyEngines === engineRows.length;
    const statusTone = hasEngineErrors ? 'error' : (allRunning ? 'ok' : 'warn');
    const statusText = reason
        ? `${reason} | ${healthyEngines}/${engineRows.length} engines healthy`
        : `${healthyEngines}/${engineRows.length} engines healthy`;
    setDebugSystemStatus(statusText, statusTone);

    if (!debugSystemEngineList) return;
    debugSystemEngineList.innerHTML = '';
    const frag = document.createDocumentFragment();
    engineRows.forEach((engine) => {
        const tone = engine.error ? 'error' : (engine.running ? 'ok' : 'warn');
        frag.appendChild(debugCreateItemCard({
            title: engine.name,
            pill: engine.error ? 'error' : (engine.running ? 'running' : 'stopped'),
            pillTone: tone,
            meta: [
                `cycles: ${Number.isFinite(engine.cycles) ? engine.cycles : 0}`,
                `last activity: ${formatDebugWhen(engine.lastActivity)}`,
                engine.error ? `error: ${engine.error}` : '',
            ],
        }));
    });
    debugSystemEngineList.appendChild(frag);
    renderDebugOnboardingGatePanel(payload?.onboarding_gate || null);
}

function renderDebugModelsPanel() {
    const payload = debugLiveCache.models;
    if (!payload) {
        if (debugModelsDefault) debugModelsDefault.textContent = '-';
        if (debugModelsCount) debugModelsCount.textContent = '0';
        if (debugModelsHealthy) debugModelsHealthy.textContent = '0';
        debugRenderEmpty(debugModelHealthList, 'No model health data yet.');
        return;
    }

    const modelPayload = payload?.models || {};
    const profiles = Array.isArray(modelPayload?.profiles) ? modelPayload.profiles : [];
    const defaultProfile = safeString(modelPayload?.default);
    const capabilitiesByProfile = payload?.capabilities?.profiles || {};
    const handshakes = payload?.handshakes || {};
    const healthy = profiles.filter((profile) => Boolean(handshakes?.[profile.name]?.ok)).length;

    if (debugModelsDefault) debugModelsDefault.textContent = defaultProfile || '-';
    if (debugModelsCount) debugModelsCount.textContent = String(profiles.length);
    if (debugModelsHealthy) debugModelsHealthy.textContent = String(healthy);

    if (!debugModelHealthList) return;
    debugModelHealthList.innerHTML = '';
    if (!profiles.length) {
        debugRenderEmpty(debugModelHealthList, 'No model profiles found.');
        return;
    }

    const frag = document.createDocumentFragment();
    profiles.forEach((profile) => {
        const name = safeString(profile?.name);
        const provider = safeString(profile?.provider);
        const modelId = safeString(profile?.model);
        const handshake = handshakes?.[name] || null;
        const status = safeString(handshake?.status);
        const ok = handshake?.ok === true;
        const tone = ok ? 'ok' : (status === 'error' || status === 'auth' ? 'error' : 'warn');
        const capabilityText = summarizeCapabilities(capabilitiesByProfile?.[name]);
        frag.appendChild(debugCreateItemCard({
            title: name || 'profile',
            pill: status || (ok ? 'ok' : 'unknown'),
            pillTone: tone,
            meta: [
                `provider: ${provider || 'unknown'} | model: ${modelId || '-'}`,
                `capabilities: ${capabilityText}`,
                handshake?.error ? `handshake error: ${safeString(handshake.error)}` : '',
            ],
        }));
    });
    debugModelHealthList.appendChild(frag);
}

function renderDebugToolsPanel() {
    const payload = debugLiveCache.tools;
    if (!payload) {
        if (debugToolsTotal) debugToolsTotal.textContent = '0';
        if (debugToolsCategories) debugToolsCategories.textContent = '0';
        debugRenderEmpty(debugToolCategoryList, 'No tool categories yet.');
        debugRenderEmpty(debugToolRegistryList, 'No tools loaded yet.');
        return;
    }

    const tools = Array.isArray(payload?.tools?.tools) ? payload.tools.tools : [];
    const categories = new Map();
    tools.forEach((tool) => {
        const category = safeString(tool?.category) || 'uncategorized';
        categories.set(category, Number(categories.get(category) || 0) + 1);
    });

    if (debugToolsTotal) debugToolsTotal.textContent = String(tools.length);
    if (debugToolsCategories) debugToolsCategories.textContent = String(categories.size);

    if (debugToolCategoryList) {
        debugToolCategoryList.innerHTML = '';
        if (!categories.size) {
            debugRenderEmpty(debugToolCategoryList, 'No categories found.');
        } else {
            const categoryFrag = document.createDocumentFragment();
            Array.from(categories.entries()).sort((a, b) => a[0].localeCompare(b[0])).forEach(([name, count]) => {
                const chip = document.createElement('span');
                chip.className = 'debug-chip';
                chip.textContent = `${name} (${count})`;
                categoryFrag.appendChild(chip);
            });
            debugToolCategoryList.appendChild(categoryFrag);
        }
    }

    if (!debugToolRegistryList) return;
    debugToolRegistryList.innerHTML = '';
    if (!tools.length) {
        debugRenderEmpty(debugToolRegistryList, 'No tools in registry.');
        return;
    }

    const frag = document.createDocumentFragment();
    tools.slice(0, 80).forEach((tool) => {
        frag.appendChild(debugCreateItemCard({
            title: safeString(tool?.name) || 'tool',
            pill: safeString(tool?.category) || 'misc',
            meta: [safeString(tool?.description) || 'No description'],
        }));
    });
    debugToolRegistryList.appendChild(frag);
}

function renderDebugMemoryPanel() {
    const payload = debugLiveCache.memory;
    if (!payload) {
        if (debugMemoryEnabled) debugMemoryEnabled.textContent = '-';
        if (debugMemoryPins) debugMemoryPins.textContent = '0';
        if (debugMemoryContradictions) debugMemoryContradictions.textContent = '0';
        debugRenderEmpty(debugMemoryList, 'No memory diagnostics loaded yet.');
        return;
    }

    const memoryData = payload?.memory || {};
    const enabled = Boolean(memoryData?.enabled);
    const diagnostics = memoryData && typeof memoryData === 'object' ? memoryData : {};
    const pins = Array.isArray(diagnostics?.pins)
        ? diagnostics.pins
        : (Array.isArray(diagnostics?.data?.pins) ? diagnostics.data.pins : []);
    const traces = Array.isArray(diagnostics?.traces)
        ? diagnostics.traces
        : (Array.isArray(diagnostics?.data?.traces) ? diagnostics.data.traces : []);
    const stats = diagnostics?.stats || diagnostics?.data?.stats || {};
    const contradictionsList = Array.isArray(payload?.contradictions?.contradictions)
        ? payload.contradictions.contradictions
        : [];

    if (debugMemoryEnabled) debugMemoryEnabled.textContent = enabled ? 'yes' : 'no';
    if (debugMemoryPins) debugMemoryPins.textContent = String(pins.length);
    if (debugMemoryContradictions) debugMemoryContradictions.textContent = String(contradictionsList.length);

    if (!debugMemoryList) return;
    debugMemoryList.innerHTML = '';
    const frag = document.createDocumentFragment();
    frag.appendChild(debugCreateItemCard({
        title: 'Memory Engine',
        pill: enabled ? 'enabled' : 'disabled',
        pillTone: debugStatusToneFromBool(enabled),
        meta: [
            `events: ${Number(stats?.event_count || 0)}`,
            `dense vectors: ${Boolean(stats?.has_dense) ? 'yes' : 'no'} (dim ${Number(stats?.dense_dim || 0)})`,
            `recent traces: ${traces.length}`,
            `root: ${safeString(stats?.root) || '-'}`,
        ],
    }));

    contradictionsList.slice(0, 6).forEach((row) => {
        const severity = safeString(row?.severity || row?.priority || 'open').toLowerCase();
        const tone = severity.includes('high') ? 'error' : (severity.includes('med') ? 'warn' : 'ok');
        frag.appendChild(debugCreateItemCard({
            title: safeString(row?.summary || row?.claim || `Contradiction ${row?.id || ''}`) || 'Contradiction',
            pill: severity || 'open',
            pillTone: tone,
            meta: [
                `id: ${safeString(row?.id) || '-'}`,
                `status: ${safeString(row?.status) || 'open'} | route: ${safeString(row?.route) || '-'}`,
            ],
        }));
    });

    if (!contradictionsList.length) {
        frag.appendChild(debugCreateItemCard({
            title: 'Contradictions',
            pill: 'none',
            pillTone: 'ok',
            meta: ['No open contradictions.'],
        }));
    }
    debugMemoryList.appendChild(frag);
}

function renderDebugRunsPanel() {
    const payload = debugLiveCache.runs;
    if (!payload) {
        if (debugRunsCount) debugRunsCount.textContent = '0';
        if (debugRunsFailed) debugRunsFailed.textContent = '0';
        debugRenderEmpty(debugRunsList, 'No run data loaded yet.');
        return;
    }

    const runs = Array.isArray(payload?.runs?.runs) ? payload.runs.runs : [];
    const failed = runs.filter((run) => run?.ok === false || safeString(run?.error)).length;
    if (debugRunsCount) debugRunsCount.textContent = String(runs.length);
    if (debugRunsFailed) debugRunsFailed.textContent = String(failed);

    if (!debugRunsList) return;
    debugRunsList.innerHTML = '';
    if (!runs.length) {
        const unavailable = safeString(payload?.error).toLowerCase().includes('404')
            || safeString(payload?.error).toLowerCase().includes('not found');
        debugRenderEmpty(
            debugRunsList,
            unavailable ? 'Run store endpoint is not available in this environment.' : 'No runs found yet.',
        );
        return;
    }

    const frag = document.createDocumentFragment();
    runs.slice(0, 12).forEach((run) => {
        const ok = run?.ok === true ? true : (run?.ok === false ? false : null);
        frag.appendChild(debugCreateItemCard({
            title: safeString(run?.run_id || '').slice(0, 16) || 'run',
            pill: ok === true ? 'ok' : (ok === false ? 'failed' : 'unknown'),
            pillTone: debugStatusToneFromBool(ok),
            meta: [
                `mode: ${safeString(run?.mode) || '-'} | profile: ${safeString(run?.profile) || '-'}`,
                `started: ${formatDebugWhen(run?.started_at)} | ended: ${formatDebugWhen(run?.ended_at)}`,
                safeString(run?.error) ? `error: ${safeString(run.error)}` : '',
            ],
        }));
    });
    debugRunsList.appendChild(frag);
}

function renderDebugLivePanels() {
    renderDebugSystemPanel();
    renderDebugModelsPanel();
    renderDebugToolsPanel();
    renderDebugMemoryPanel();
    renderDebugRunsPanel();
}

async function refreshDebugLiveData({ force = false, reason = '' } = {}) {
    const activeNeedsLiveData = ['system', 'models', 'tools', 'memory', 'runs'].includes(activeDebugTab);
    if (!force && !activeNeedsLiveData) return;
    const stale = (Date.now() - Number(debugLiveCache.loadedAt || 0)) > DEBUG_LIVE_CACHE_TTL_MS;
    if (!force && !stale && debugLiveCache.loadedAt) {
        renderDebugLivePanels();
        return;
    }
    if (debugLiveLoading) return;

    debugLiveLoading = true;
    if (reason === 'manual') {
        setDebugSystemStatus('Refreshing live console data...');
    }

    const memoryUrl = sessionId
        ? `/api/memory?session_id=${encodeURIComponent(sessionId)}&trace_limit=8`
        : '/api/memory?trace_limit=8';

    try {
        const [versionRes, bootstrapRes, enginesRes, modelsRes, capabilitiesRes, toolsRes, memoryRes, contradictionsRes, runsRes, onboardingGateRes] = await Promise.all([
            fetchJsonSafe('/api/version'),
            fetchJsonSafe('/api/setup/bootstrap'),
            fetchJsonSafe('/api/engines'),
            fetchJsonSafe('/api/models'),
            fetchJsonSafe('/api/models/capabilities'),
            fetchJsonSafe('/api/tools'),
            fetchJsonSafe(memoryUrl),
            fetchJsonSafe('/api/memory/contradictions?only_open=1&limit=12'),
            fetchJsonSafe('/api/runs?limit=12'),
            fetchJsonSafe('/api/onboarding/outcomes/gate?days=7'),
        ]);

        const modelsPayload = modelsRes.ok && modelsRes.data && typeof modelsRes.data === 'object'
            ? modelsRes.data
            : {};
        const profiles = Array.isArray(modelsPayload?.profiles) ? modelsPayload.profiles : [];
        const handshakePairs = await Promise.all(
            profiles.slice(0, 8).map(async (profile) => {
                const name = safeString(profile?.name);
                if (!name) return [name, null];
                const handshakeRes = await fetchJsonSafe(`/api/models/${encodeURIComponent(name)}/handshake`);
                if (handshakeRes.ok && handshakeRes.data && typeof handshakeRes.data === 'object') {
                    return [name, handshakeRes.data];
                }
                return [name, { ok: false, status: 'error', error: safeString(handshakeRes.text) || `HTTP ${handshakeRes.status}` }];
            }),
        );

        debugLiveCache.system = {
            version: versionRes.ok ? versionRes.data : null,
            bootstrap: bootstrapRes.ok ? bootstrapRes.data : null,
            engines: enginesRes.ok ? enginesRes.data : null,
            onboarding_gate: onboardingGateRes.ok ? onboardingGateRes.data : null,
            errors: [
                versionRes.ok ? '' : `version: ${versionRes.status}`,
                bootstrapRes.ok ? '' : `setup/bootstrap: ${bootstrapRes.status}`,
                enginesRes.ok ? '' : `engines: ${enginesRes.status}`,
                onboardingGateRes.ok ? '' : `onboarding/outcomes/gate: ${onboardingGateRes.status}`,
            ].filter(Boolean),
        };
        debugLiveCache.models = {
            models: modelsPayload,
            capabilities: capabilitiesRes.ok ? capabilitiesRes.data : null,
            handshakes: Object.fromEntries(handshakePairs.filter(([name]) => Boolean(safeString(name)))),
        };
        debugLiveCache.tools = {
            tools: toolsRes.ok ? toolsRes.data : null,
        };
        debugLiveCache.memory = {
            memory: memoryRes.ok ? memoryRes.data : null,
            contradictions: contradictionsRes.ok ? contradictionsRes.data : null,
        };
        debugLiveCache.runs = {
            runs: runsRes.ok ? runsRes.data : null,
            error: runsRes.ok ? '' : (safeString(runsRes.text) || `HTTP ${runsRes.status}`),
        };
        debugLiveCache.errors = [
            toolsRes.ok ? '' : `tools: ${toolsRes.status}`,
            memoryRes.ok ? '' : `memory: ${memoryRes.status}`,
            contradictionsRes.ok ? '' : `memory/contradictions: ${contradictionsRes.status}`,
            runsRes.ok ? '' : `runs: ${runsRes.status}`,
            onboardingGateRes.ok ? '' : `onboarding/outcomes/gate: ${onboardingGateRes.status}`,
        ].filter(Boolean);
        debugLiveCache.loadedAt = Date.now();
    } catch (error) {
        console.warn('Failed refreshing tools console live data', error);
        debugLiveCache.errors = [safeString(error?.message) || 'unknown tools console error'];
    } finally {
        debugLiveLoading = false;
        renderDebugLivePanels();
        const warningCount = debugLiveCache.errors.length;
        if (warningCount > 0) {
            setDebugSystemStatus(`Loaded with ${warningCount} warning(s): ${debugLiveCache.errors[0]}`, 'warn');
        }
    }
}

function renderDebugConsoleLog() {
    if (!debugConsoleLog) return;
    debugConsoleLog.innerHTML = '';
    if (!debugConsoleEntries.length) {
        const empty = document.createElement('div');
        empty.className = 'debug-empty';
        empty.textContent = 'No console output yet.';
        debugConsoleLog.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    debugConsoleEntries.forEach((entry) => {
        const row = document.createElement('div');
        row.className = 'debug-console-item';

        const head = document.createElement('div');
        head.className = 'debug-console-head';

        const level = document.createElement('span');
        level.className = `debug-console-level level-${safeString(entry.level) || 'log'}`;
        level.textContent = safeString(entry.level) || 'log';

        const at = document.createElement('span');
        at.className = 'debug-event-time';
        at.textContent = formatDebugTime(entry.ts);

        const body = document.createElement('div');
        body.className = 'debug-console-body';
        body.textContent = safeString(entry.message);

        head.appendChild(level);
        head.appendChild(at);
        row.appendChild(head);
        row.appendChild(body);
        frag.appendChild(row);
    });

    debugConsoleLog.appendChild(frag);
}

function renderDebugNetworkLog() {
    if (!debugNetworkLog) return;
    debugNetworkLog.innerHTML = '';
    if (!debugNetworkEntries.length) {
        const empty = document.createElement('div');
        empty.className = 'debug-empty';
        empty.textContent = 'No network calls captured yet.';
        debugNetworkLog.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    debugNetworkEntries.forEach((entry) => {
        const row = document.createElement('div');
        row.className = 'debug-network-item';

        const head = document.createElement('div');
        head.className = 'debug-network-head';

        const method = document.createElement('span');
        method.className = 'debug-network-method';
        method.textContent = safeString(entry.method) || 'GET';

        const status = document.createElement('span');
        const ok = Boolean(entry.ok);
        status.className = `debug-network-status ${ok ? 'ok' : 'error'}`;
        const statusText = entry.status ? String(entry.status) : 'ERR';
        status.textContent = `${statusText} | ${safeString(entry.duration_ms)}ms`;

        const url = document.createElement('div');
        url.className = 'debug-network-url';
        url.textContent = shortDebugUrl(entry.url);

        const meta = document.createElement('div');
        meta.className = 'debug-network-meta';
        const errorText = safeString(entry.error);
        meta.textContent = errorText
            ? `${formatDebugTime(entry.ts)} | ${errorText}`
            : formatDebugTime(entry.ts);

        head.appendChild(method);
        head.appendChild(status);
        row.appendChild(head);
        row.appendChild(url);
        row.appendChild(meta);
        frag.appendChild(row);
    });

    debugNetworkLog.appendChild(frag);
}

function updateDebugNetworkSummary() {
    const total = debugNetworkEntries.length;
    const errors = debugNetworkEntries.filter((entry) => !entry.ok).length;
    const averageMs = total
        ? Math.round(debugNetworkEntries.reduce((sum, entry) => sum + Number(entry.duration_ms || 0), 0) / total)
        : 0;

    if (debugNetworkTotal) debugNetworkTotal.textContent = String(total);
    if (debugNetworkErrors) debugNetworkErrors.textContent = String(errors);
    if (debugNetworkAvgMs) debugNetworkAvgMs.textContent = String(averageMs);
}

function pushDebugConsoleEntry(level, args) {
    const message = (Array.isArray(args) ? args : [args])
        .map((value) => safeString(formatDebugValue(value)))
        .filter(Boolean)
        .join(' ')
        .slice(0, 2000);

    debugConsoleEntries.unshift({
        level: safeString(level) || 'log',
        message: message || '(empty)',
        ts: Date.now(),
    });
    if (debugConsoleEntries.length > DEBUG_CONSOLE_LIMIT) {
        debugConsoleEntries = debugConsoleEntries.slice(0, DEBUG_CONSOLE_LIMIT);
    }
    renderDebugConsoleLog();
    updateDebugDockSnapshot();
}

function pushDebugNetworkEntry(entry = {}) {
    debugNetworkEntries.unshift({
        method: safeString(entry.method || 'GET').toUpperCase(),
        url: safeString(entry.url) || '/',
        status: Number(entry.status) || 0,
        ok: Boolean(entry.ok),
        duration_ms: Math.max(0, Number(entry.duration_ms) || 0),
        error: safeString(entry.error),
        ts: Number(entry.ts) || Date.now(),
    });
    if (debugNetworkEntries.length > DEBUG_NETWORK_LIMIT) {
        debugNetworkEntries = debugNetworkEntries.slice(0, DEBUG_NETWORK_LIMIT);
    }
    renderDebugNetworkLog();
    updateDebugNetworkSummary();
    updateDebugDockSnapshot();
}

function startDebugConsoleCapture() {
    if (debugConsoleCaptureEnabled) return;
    debugConsoleCaptureEnabled = true;
    const methods = ['log', 'info', 'warn', 'error', 'debug'];

    methods.forEach((method) => {
        const original = console[method];
        if (typeof original !== 'function') return;
        const bound = original.bind(console);
        console[method] = (...args) => {
            try {
                pushDebugConsoleEntry(method, args);
            } catch {
                // Do not block console output.
            }
            bound(...args);
        };
    });

    window.addEventListener('error', (event) => {
        const where = safeString(event.filename)
            ? `${safeString(event.filename)}:${Number(event.lineno || 0)}`
            : '';
        pushDebugConsoleEntry('error', [safeString(event.message) || 'Unhandled window error', where]);
    });

    window.addEventListener('unhandledrejection', (event) => {
        pushDebugConsoleEntry('error', [`Unhandled rejection: ${formatDebugValue(event.reason)}`]);
    });
}

function startDebugNetworkCapture() {
    if (debugNetworkCaptureEnabled || typeof window.fetch !== 'function') return;
    debugNetworkCaptureEnabled = true;
    const originalFetch = window.fetch.bind(window);

    window.fetch = async (input, init) => {
        const started = performance.now();
        const method = safeString(init?.method || input?.method || 'GET').toUpperCase() || 'GET';
        const url = normalizeDebugUrl(input);
        let status = 0;
        let ok = false;
        let errorText = '';
        try {
            const response = await originalFetch(input, init);
            status = Number(response?.status) || 0;
            ok = Boolean(response?.ok);
            return response;
        } catch (error) {
            errorText = safeString(error?.message) || 'request failed';
            throw error;
        } finally {
            pushDebugNetworkEntry({
                method,
                url,
                status,
                ok,
                error: errorText,
                duration_ms: Math.round(performance.now() - started),
                ts: Date.now(),
            });
        }
    };
}

function renderDebugEventLog() {
    if (!debugEventLog) return;
    debugEventLog.innerHTML = '';
    if (!debugEvents.length) {
        const empty = document.createElement('div');
        empty.className = 'debug-empty';
        empty.textContent = 'No events yet.';
        debugEventLog.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    debugEvents.forEach((entry) => {
        const row = document.createElement('div');
        row.className = 'debug-event-item';

        const head = document.createElement('div');
        head.className = 'debug-event-head';

        const kind = document.createElement('span');
        kind.className = 'debug-event-kind';
        kind.textContent = entry.kind;

        const at = document.createElement('span');
        at.className = 'debug-event-time';
        at.textContent = formatDebugTime(entry.ts);

        head.appendChild(kind);
        head.appendChild(at);

        const body = document.createElement('div');
        body.className = 'debug-event-body';
        body.textContent = entry.message;

        row.appendChild(head);
        row.appendChild(body);
        frag.appendChild(row);
    });

    debugEventLog.appendChild(frag);
}

function pushDebugEvent(kind, message) {
    debugEvents.unshift({
        kind: safeString(kind) || 'event',
        message: safeString(message) || 'event',
        ts: Date.now(),
    });
    if (debugEvents.length > DEBUG_EVENT_LIMIT) {
        debugEvents = debugEvents.slice(0, DEBUG_EVENT_LIMIT);
    }
    renderDebugEventLog();
    updateDebugDockSnapshot();
}

async function verifyRuntimeGuardVersion({ reason = 'poll', notifyOnError = false } = {}) {
    try {
        const versionRes = await fetchJsonSafe('/api/version', { timeoutMs: 7000 });
        if (!versionRes.ok || !versionRes.data || typeof versionRes.data !== 'object') {
            if (notifyOnError) {
                const msg = safeString(versionRes.text) || `HTTP ${versionRes.status}`;
                pushDebugEvent('runtime', `Runtime guard check failed: ${msg}`);
            }
            return;
        }

        const runtimeGuard = versionRes.data.runtime_guard;
        if (!runtimeGuard || typeof runtimeGuard !== 'object') return;

        const isLatestCode = runtimeGuard.is_latest_code !== false;
        const guardState = safeString(runtimeGuard.state) || (isLatestCode ? 'ok' : 'stale');
        const guardReasons = Array.isArray(runtimeGuard.reasons)
            ? runtimeGuard.reasons.map((item) => safeString(item)).filter(Boolean)
            : [];
        const reasonSummary = guardReasons.join(', ');

        if (!isLatestCode) {
            const alertMessage = safeString(runtimeGuard.alert_message)
                || 'Not running the newest Thomas server version. Restart Thomas to load latest code.';
            const signature = `${alertMessage}|${reasonSummary}`;
            const now = Date.now();
            if (
                signature !== runtimeGuardLastAlertSignature
                || (now - runtimeGuardLastAlertAt) > RUNTIME_GUARD_ALERT_DEDUPE_MS
            ) {
                runtimeGuardLastAlertSignature = signature;
                runtimeGuardLastAlertAt = now;
                notifyUser(alertMessage, {
                    tone: 'warning',
                    durationMs: 5200,
                    dedupeMs: RUNTIME_GUARD_ALERT_DEDUPE_MS,
                    debugKind: 'runtime',
                });
            }
            if (runtimeGuardLastState !== guardState || reason === 'boot') {
                pushDebugEvent('runtime', `Runtime guard stale: ${reasonSummary || 'unknown reason'}`);
            }
        } else if (runtimeGuardLastState && runtimeGuardLastState !== 'ok') {
            runtimeGuardLastAlertSignature = '';
            pushDebugEvent('runtime', 'Runtime guard recovered: latest code is active');
        }

        runtimeGuardLastState = guardState;
    } catch (error) {
        if (notifyOnError) {
            pushDebugEvent('runtime', `Runtime guard check failed: ${safeString(error?.message) || 'unknown error'}`);
        }
    }
}

function startRuntimeGuardMonitor() {
    if (runtimeGuardMonitorTimer) {
        window.clearInterval(runtimeGuardMonitorTimer);
        runtimeGuardMonitorTimer = 0;
    }
    void verifyRuntimeGuardVersion({ reason: 'boot', notifyOnError: true });
    runtimeGuardMonitorTimer = window.setInterval(() => {
        void verifyRuntimeGuardVersion({ reason: 'poll', notifyOnError: false });
    }, RUNTIME_GUARD_POLL_INTERVAL_MS);
}

function buildDebugSnapshot() {
    const messageCount = chatMessagesInner ? chatMessagesInner.children.length : 0;
    const activeModel = safeString(modelSetupCurrentLabel?.textContent)
        || safeString(setupProviderSelector?.value)
        || safeString(modelSelector?.value)
        || 'n/a';
    return {
        timestamp: new Date().toISOString(),
        theme: readThemeName(),
        session_id: safeString(sessionId) || null,
        model: activeModel,
        message_count: messageCount,
        generating: Boolean(isGenerating),
        sidebar: {
            collapsed: Boolean(sidebar?.classList.contains('collapsed')),
            mode: sidebarNavMode,
            search_scope: sidebarSearchScope,
        },
        viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
        },
        diagnostics: {
            active_tab: activeDebugTab,
            events_count: debugEvents.length,
            console_count: debugConsoleEntries.length,
            network_count: debugNetworkEntries.length,
        },
        recent_events: debugEvents.slice(0, 30),
        recent_console: debugConsoleEntries.slice(0, 30),
        recent_network: debugNetworkEntries.slice(0, 30),
    };
}

function updateDebugDockSnapshot() {
    const snapshot = buildDebugSnapshot();
    if (debugSessionId) debugSessionId.textContent = snapshot.session_id || '-';
    if (debugModel) debugModel.textContent = snapshot.model;
    if (debugMessageCount) debugMessageCount.textContent = String(snapshot.message_count);
    if (debugGenerating) debugGenerating.textContent = snapshot.generating ? 'yes' : 'no';
    if (debugSidebarState) {
        const collapsed = snapshot.sidebar.collapsed ? 'collapsed' : 'expanded';
        debugSidebarState.textContent = `${snapshot.sidebar.mode}/${collapsed}`;
    }
    if (debugSearchScope) debugSearchScope.textContent = snapshot.sidebar.search_scope;
    if (debugThemeName) debugThemeName.textContent = snapshot.theme;
    if (debugViewport) debugViewport.textContent = `${snapshot.viewport.width}x${snapshot.viewport.height}`;
    if (debugEventCount) debugEventCount.textContent = String(snapshot.diagnostics.events_count);
    if (debugConsoleCount) debugConsoleCount.textContent = String(snapshot.diagnostics.console_count);
    if (debugNetworkCount) debugNetworkCount.textContent = String(snapshot.diagnostics.network_count);
    updateDebugNetworkSummary();
}

function syncLayoutOffsets() {
    if (!appRoot) return;
    const sidebarWidth = sidebar && !sidebar.classList.contains('collapsed')
        ? Math.max(0, Math.round(sidebar.getBoundingClientRect().width))
        : 0;
    appRoot.style.setProperty('--sidebar-visible-width', `${sidebarWidth}px`);
    normalizeMainContentScroll();
    updateDebugDockSnapshot();
}

function normalizeMainContentScroll() {
    if (!mainContent) return;
    if (mainContent.scrollLeft !== 0) {
        mainContent.scrollLeft = 0;
    }
}

function startSidebarAnimationLock() {
    if (!appRoot) return;
    appRoot.classList.add('sidebar-animating');
    if (sidebarAnimationTimer) {
        window.clearTimeout(sidebarAnimationTimer);
    }
    sidebarAnimationTimer = window.setTimeout(() => {
        appRoot.classList.remove('sidebar-animating');
        sidebarAnimationTimer = 0;
    }, SIDEBAR_ANIMATION_LOCK_MS);
}

function startDebugDockAnimationLock() {
    if (!appRoot) return;
    appRoot.classList.add('debug-dock-animating');
    if (debugDockAnimationTimer) {
        window.clearTimeout(debugDockAnimationTimer);
    }
    debugDockAnimationTimer = window.setTimeout(() => {
        appRoot.classList.remove('debug-dock-animating');
        debugDockAnimationTimer = 0;
    }, DEBUG_DOCK_ANIMATION_LOCK_MS);
}

function isSidebarAnimating() {
    return Boolean(appRoot?.classList.contains('sidebar-animating'));
}

function isDebugDockAnimating() {
    return Boolean(appRoot?.classList.contains('debug-dock-animating'));
}

function setDebugDockOpen(open, { recordEvent = true } = {}) {
    if (!appRoot || !debugDock) return;
    const isOpen = Boolean(open);
    const wasOpen = appRoot.classList.contains('debug-dock-open');
    if (wasOpen !== isOpen) {
        startDebugDockAnimationLock();
    }
    appRoot.classList.toggle('debug-dock-open', isOpen);
    if (debugDockToggleBtn) {
        debugDockToggleBtn.classList.toggle('active', isOpen);
        debugDockToggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    syncLayoutOffsets();
    if (isOpen) {
        void refreshDebugLiveData({ reason: 'open' });
    }
    if (recordEvent) {
        pushDebugEvent('tools', isOpen ? 'Opened tools panel' : 'Closed tools panel');
    }
}

async function copyDebugSnapshotToClipboard() {
    const snapshot = buildDebugSnapshot();
    const payload = JSON.stringify(snapshot, null, 2);
    try {
        if (navigator?.clipboard?.writeText) {
            await navigator.clipboard.writeText(payload);
            pushDebugEvent('tools', 'Copied debug snapshot to clipboard');
            return;
        }
    } catch (err) {
        console.warn('Clipboard write failed', err);
    }
    pushDebugEvent('tools', 'Clipboard unavailable for snapshot copy');
}

function normalizeHistoryMessageForPersistence(message, index = 0) {
    if (!message || typeof message !== 'object') return null;
    const role = safeString(message.role);
    if (role !== 'user' && role !== 'assistant') return null;
    const content = safeString(message.content);
    const nowMs = Date.now();
    let createdAt = Number(message.createdAt);
    if (!Number.isFinite(createdAt) || createdAt <= 0) createdAt = nowMs + index;
    const out = {
        id: safeString(message.id) || `m-${createdAt}-${index}`,
        role,
        content,
        createdAt: Math.floor(createdAt),
        status: safeString(message.status) || 'complete',
        toolCalls: Array.isArray(message.toolCalls) ? message.toolCalls : [],
    };
    if (message.pinned) out.pinned = true;
    return out;
}

function normalizeConversationHistory(historyRaw) {
    if (!Array.isArray(historyRaw)) return [];
    const out = [];
    historyRaw.forEach((item, index) => {
        const normalized = normalizeHistoryMessageForPersistence(item, index);
        if (normalized) out.push(normalized);
    });
    return out;
}

function deriveChatPreviewFromMessages(messagesRaw) {
    const messages = normalizeConversationHistory(messagesRaw);
    const firstUser = messages.find((m) => safeString(m.role) === 'user' && safeString(m.content));
    if (firstUser) return safeString(firstUser.content).replace(/\s+/g, ' ').slice(0, 160);
    const firstAny = messages.find((m) => safeString(m.content));
    if (firstAny) return safeString(firstAny.content).replace(/\s+/g, ' ').slice(0, 160);
    return '';
}

function deriveChatTitleFromMessages(messagesRaw) {
    const preview = deriveChatPreviewFromMessages(messagesRaw);
    if (preview) return preview.slice(0, 72);
    return 'New Chat';
}

function formatSidebarTimestamp(epochMs) {
    const ts = Number(epochMs);
    if (!Number.isFinite(ts) || ts <= 0) return '';
    try {
        return new Date(ts).toLocaleString([], {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        });
    } catch (error) {
        return '';
    }
}

// 
//   SESSION & CHAT PERSISTENCE                                             
//   Chat save/load, sidebar sessions, persistence helpers, animation locks 
// 

function mapPersistedChatToSidebarSession(chatRaw) {
    if (!chatRaw || typeof chatRaw !== 'object') return null;
    const id = safeString(chatRaw.id);
    if (!id) return null;

    const messages = normalizeConversationHistory(chatRaw.messages);
    const createdAt = Number(chatRaw.createdAt);
    const updatedAt = Number(chatRaw.updatedAt);
    const createdAtSafe = Number.isFinite(createdAt) && createdAt > 0 ? Math.floor(createdAt) : Date.now();
    const updatedAtSafe = Number.isFinite(updatedAt) && updatedAt > 0 ? Math.floor(updatedAt) : createdAtSafe;

    const title = safeString(chatRaw.title) || deriveChatTitleFromMessages(messages);
    const preview = deriveChatPreviewFromMessages(messages) || title;
    const model = safeString(chatRaw.model);
    const timestamp = formatSidebarTimestamp(updatedAtSafe);

    return {
        id,
        title,
        preview,
        model,
        timestamp,
        createdAt: createdAtSafe,
        updatedAt: updatedAtSafe,
        pinned: Boolean(chatRaw.pinned),
        sessionId: safeString(chatRaw.sessionId),
        messages,
    };
}

