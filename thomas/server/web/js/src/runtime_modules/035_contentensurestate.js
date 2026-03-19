// Extracted from part-018.js
// From contentensurestate

function contentEnsureState() {
    if (!contentWorkspace) return null;
    if (!contentState) {
        contentState = {
            controlsBound: false,
            loading: false,
            lastFetchedAt: 0,
            error: '',
            payload: null,
        };
    }
    return contentState;
}

function contentToCount(value, fallback = 0) {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.max(0, Math.round(num));
}

function contentEmptyPayload() {
    return {
        generatedAt: '',
        summary: {
            connected_platforms: 0,
            known_platforms: 0,
            total_jobs: 0,
            active_jobs: 0,
            queued_posts: 0,
            workflows: 0,
            scheduled_posts: 0,
            approvals_pending: 0,
            sessions_active: 0,
            sessions_recent_total: 0,
            cron_jobs: 0,
            skills_installed: 0,
            api_keys_configured: 0,
            logs_last_24h: 0,
        },
        platforms: [],
        workflows: [],
        scheduler: [],
        tools: [],
        control_surface: {
            chat_first: { enabled: true, detail: '' },
            cards: [],
            health_status: 'attention',
            health_checks: [],
        },
        navigation: [],
        organization_axes: [],
        checklist: [],
    };
}

function contentNormalizePayload(payloadRaw) {
    const payload = payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : {};
    const summaryRaw = payload.summary && typeof payload.summary === 'object' ? payload.summary : {};
    const controlRaw = payload.control_surface && typeof payload.control_surface === 'object'
        ? payload.control_surface
        : {};
    return {
        generatedAt: safeString(payload.generated_at),
        summary: {
            connected_platforms: contentToCount(summaryRaw.connected_platforms),
            known_platforms: contentToCount(summaryRaw.known_platforms),
            total_jobs: contentToCount(summaryRaw.total_jobs),
            active_jobs: contentToCount(summaryRaw.active_jobs),
            queued_posts: contentToCount(summaryRaw.queued_posts),
            workflows: contentToCount(summaryRaw.workflows),
            scheduled_posts: contentToCount(summaryRaw.scheduled_posts),
            approvals_pending: contentToCount(summaryRaw.approvals_pending),
            sessions_active: contentToCount(summaryRaw.sessions_active),
            sessions_recent_total: contentToCount(summaryRaw.sessions_recent_total),
            cron_jobs: contentToCount(summaryRaw.cron_jobs),
            skills_installed: contentToCount(summaryRaw.skills_installed),
            api_keys_configured: contentToCount(summaryRaw.api_keys_configured),
            logs_last_24h: contentToCount(summaryRaw.logs_last_24h),
        },
        platforms: Array.isArray(payload.platforms) ? payload.platforms : [],
        workflows: Array.isArray(payload.workflows) ? payload.workflows : [],
        scheduler: Array.isArray(payload.scheduler) ? payload.scheduler : [],
        tools: Array.isArray(payload.tools) ? payload.tools : [],
        control_surface: {
            chat_first: controlRaw.chat_first && typeof controlRaw.chat_first === 'object'
                ? controlRaw.chat_first
                : { enabled: true, detail: '' },
            cards: Array.isArray(controlRaw.cards) ? controlRaw.cards : [],
            health_status: safeString(controlRaw.health_status) || 'attention',
            health_checks: Array.isArray(controlRaw.health_checks) ? controlRaw.health_checks : [],
        },
        navigation: Array.isArray(payload.navigation) ? payload.navigation : [],
        organization_axes: Array.isArray(payload.organization_axes) ? payload.organization_axes : [],
        checklist: Array.isArray(payload.checklist) ? payload.checklist : [],
    };
}

function contentFormatNumber(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return '0';
    return num.toLocaleString();
}

function contentParseDate(valueRaw) {
    const raw = safeString(valueRaw);
    if (!raw) return null;
    const dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return null;
    return dt;
}

function contentFormatScheduleDay(valueRaw) {
    const dt = contentParseDate(valueRaw);
    if (!dt) return '--';
    return dt.toLocaleDateString(undefined, { weekday: 'long' });
}

function contentFormatScheduleTime(valueRaw) {
    const dt = contentParseDate(valueRaw);
    if (!dt) return '--';
    return dt.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function contentPlatformConnected(platform) {
    if (typeof platform?.connected === 'boolean') return platform.connected;
    return Number(platform?.total_jobs || 0) > 0;
}

function contentStatusClass(statusRaw) {
    const slug = safeString(statusRaw)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return slug ? ` status-${slug}` : '';
}

function contentRenderPlatforms(platforms = []) {
    if (!contentPlatformGrid) return;
    contentPlatformGrid.innerHTML = '';
    if (!platforms.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'No platforms connected yet.';
        contentPlatformGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    platforms.forEach((platform) => {
        const connected = contentPlatformConnected(platform);
        const row = document.createElement('article');
        row.className = 'content-platform-card';
        row.innerHTML = `
            <div class="content-platform-head">
                <h4>${escapeHtml(platform?.name || 'Platform')}</h4>
                <span class="content-pill ${connected ? 'connected' : 'offline'}">${connected ? 'Connected' : 'Not Connected'}</span>
            </div>
            <div class="content-platform-metrics">
                <span>Total Jobs <strong>${contentFormatNumber(platform?.total_jobs)}</strong></span>
                <span>Queued <strong>${contentFormatNumber(platform?.queued)}</strong></span>
                <span>Running <strong>${contentFormatNumber(platform?.running)}</strong></span>
                <span>Needs Approval <strong>${contentFormatNumber(platform?.awaiting_approval)}</strong></span>
                <span>Published <strong>${contentFormatNumber(platform?.published)}</strong></span>
                <span>Failed <strong>${contentFormatNumber(platform?.failed)}</strong></span>
            </div>
        `;
        frag.appendChild(row);
    });
    contentPlatformGrid.appendChild(frag);
}

function contentRenderWorkflows(workflows = []) {
    if (!contentWorkflowGrid) return;
    contentWorkflowGrid.innerHTML = '';
    if (!workflows.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'No workflows configured yet.';
        contentWorkflowGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    workflows.forEach((workflow) => {
        const activeJobs = contentToCount(workflow?.active_jobs);
        const totalJobs = contentToCount(workflow?.total_jobs);
        const row = document.createElement('article');
        row.className = 'content-workflow-card';
        row.innerHTML = `
            <h4>${escapeHtml(workflow?.name || 'Workflow')}</h4>
            <p><span>Trigger:</span> ${escapeHtml(safeString(workflow?.trigger))}</p>
            <p><span>Automation:</span> ${escapeHtml(safeString(workflow?.automation))}</p>
            <p><span>Approval:</span> ${escapeHtml(safeString(workflow?.approval))}</p>
            <p><span>Load:</span> ${contentFormatNumber(activeJobs)} active / ${contentFormatNumber(totalJobs)} total</p>
        `;
        frag.appendChild(row);
    });
    contentWorkflowGrid.appendChild(frag);
}

function contentRenderScheduler(schedule = []) {
    if (!contentSchedulerRows) return;
    contentSchedulerRows.innerHTML = '';
    if (!schedule.length) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="5">No scheduled content yet.</td>';
        contentSchedulerRows.appendChild(row);
        return;
    }

    const frag = document.createDocumentFragment();
    schedule.forEach((item) => {
        const runAt = safeString(item?.run_at);
        const day = safeString(item?.day) || contentFormatScheduleDay(runAt);
        const time = safeString(item?.time) || contentFormatScheduleTime(runAt);
        const platform = safeString(item?.platform || item?.channel) || 'All Channels';
        const type = safeString(item?.type || item?.workflow) || 'Scheduled content';
        const status = safeString(item?.status) || 'Queued';
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${escapeHtml(day)}</td>
            <td>${escapeHtml(time)}</td>
            <td>${escapeHtml(platform)}</td>
            <td>${escapeHtml(type)}</td>
            <td><span class="content-status-pill${contentStatusClass(status)}">${escapeHtml(status)}</span></td>
        `;
        frag.appendChild(row);
    });
    contentSchedulerRows.appendChild(frag);
}

function contentRenderTools(tools = []) {
    if (!contentToolsGrid) return;
    contentToolsGrid.innerHTML = '';
    if (!tools.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'No manager tools configured yet.';
        contentToolsGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    tools.forEach((tool) => {
        const status = safeString(tool?.status);
        const row = document.createElement('article');
        row.className = 'content-tool-card';
        row.innerHTML = `
            <h4>${escapeHtml(tool?.title || 'Capability')}</h4>
            ${status ? `<p class="content-tool-status">Status: ${escapeHtml(status)}</p>` : ''}
            <p>${escapeHtml(safeString(tool?.detail))}</p>
        `;
        frag.appendChild(row);
    });
    contentToolsGrid.appendChild(frag);
}

function contentToneClass(statusRaw, prefix = 'tone-') {
    const slug = safeString(statusRaw)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return slug ? `${prefix}${slug}` : `${prefix}neutral`;
}

function contentRenderControl(control = null) {
    if (!contentControlGrid) return;
    contentControlGrid.innerHTML = '';