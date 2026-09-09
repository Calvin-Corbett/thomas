/**
 * Mission Control workspace panel
 * Auto-extracted from index.html to reduce file size.
 * Injected at load time before runtime scripts.
 */
(function () {
    'use strict';
    var el = document.getElementById('missionWorkspace');
    if (!el) { console.warn('[Thomas] Template target #missionWorkspace not found'); return; }
    el.innerHTML = `<div class="mission-shell">
<header class="mission-header">
<div class="mission-header-copy">
<h2>Mission Control</h2>
<p>Always-live operations center for task flow, cron scheduling, approvals, and risk.</p>
</div>
</header>
<div class="mission-meta-row">
<span class="mission-meta-pill neutral" id="missionConnectionPill">Live sync</span>
<span class="mission-meta-text">Updated <strong id="missionUpdatedAt">--</strong>
</span>
</div>
<section class="mission-ops-strip" aria-label="Mission operations pulse">
<article class="mission-ops-card">
<span>Now</span>
<strong id="missionOpsNowTitle">No active execution</strong>
<em id="missionOpsNowMeta">Waiting for active jobs</em>
</article>
<article class="mission-ops-card">
<span>Next</span>
<strong id="missionOpsNextTitle">No scheduled runs</strong>
<em id="missionOpsNextMeta">Create a cron job to automate work</em>
</article>
<article class="mission-ops-card">
<span>Blockers</span>
<strong id="missionOpsBlockersTitle">0 blockers</strong>
<em id="missionOpsBlockersMeta">No blocked or failed work</em>
</article>
</section>
<section class="mission-kpi-grid" aria-label="Mission KPIs">
<article class="mission-kpi-card">
<span>Active Work</span>
<strong id="missionKpiActiveAgents">0</strong>
<em id="missionKpiActiveMeta">No active work</em>
</article>
<article class="mission-kpi-card">
<span>Pending Approvals</span>
<strong id="missionKpiApprovals">0</strong>
<em id="missionKpiApprovalsMeta">No approvals waiting</em>
</article>
<article class="mission-kpi-card">
<span>Risk States</span>
<strong id="missionKpiRisks">0</strong>
<em id="missionKpiRisksMeta">No blocked or failed items</em>
</article>
<article class="mission-kpi-card">
<span>Engine Health</span>
<strong id="missionKpiEngine">--</strong>
<em id="missionKpiEngineMeta">Loading status</em>
</article>
</section>
<div class="mission-grid">
<section class="mission-panel mission-panel-jobs">
<div class="mission-panel-head">
<h3>Task + Cron Jobs</h3>
<span class="mission-panel-meta" id="missionJobsMeta">Loading jobs</span>
</div>
<div class="mission-job-summary-row">
<span class="mission-job-summary-pill">
<strong id="missionJobsTaskCount">0</strong>
<em>tasks</em>
</span>
<span class="mission-job-summary-pill">
<strong id="missionJobsCronCount">0</strong>
<em>cron</em>
</span>
</div>
<div class="mission-list mission-list-jobs" id="missionJobsList">
</div>
</section>
<section class="mission-panel mission-panel-priority">
<div class="mission-panel-head">
<h3>Priority Queue</h3>
<span class="mission-panel-meta" id="missionPriorityMeta">Top mission items</span>
</div>
<div class="mission-list mission-list-priority" id="missionPriorityList">
</div>
</section>
<section class="mission-panel">
<div class="mission-panel-head">
<h3>Add Task / Cron Job</h3>
<span class="mission-panel-meta" id="missionCreateMeta">workflow task</span>
</div>
<form class="mission-job-form" id="missionJobForm">
<label class="mission-field">
<span>Name</span>
<input id="missionJobNameInput" type="text" maxlength="80" placeholder="Publish product launch plan">
</label>
<label class="mission-field">
<span>Task / Goal</span>
<textarea id="missionJobPromptInput" rows="3" placeholder="Write rollout checklist, risk review, and owner handoff plan.">
</textarea>
</label>
<div class="mission-template-row" id="missionJobTemplates">
<button class="mission-template-btn" type="button" data-name="Daily Ops Brief" data-goal="Generate daily priorities, blockers, and owner actions from current mission state." data-mode="daily" data-at="08:00" data-workflow="chain"> Daily Ops Brief </button>
<button class="mission-template-btn" type="button" data-name="Incident Triage Sweep" data-goal="Review failed or blocked mission items, summarize root causes, and propose immediate fixes." data-mode="interval" data-every-seconds="1800" data-workflow="orchestrator_worker"> Incident Triage </button>
<button class="mission-template-btn" type="button" data-name="Release Readiness Check" data-goal="Run release checklist, verify quality gates, and output go/no-go recommendation." data-mode="once" data-workflow="parallel"> Release Check </button>
</div>
<div class="mission-field-row">
<label class="mission-field">
<span>Run mode</span>
<select id="missionJobModeSelect">
<option value="now">Run now</option>
<option value="once">Run once</option>
<option value="interval">Interval</option>
<option value="daily">Daily</option>
<option value="weekly">Weekly</option>
</select>
</label>
<label class="mission-field">
<span>Workflow</span>
<select id="missionJobWorkflowInput">
<option value="chain">chain</option>
<option value="orchestrator_worker">orchestrator_worker</option>
<option value="parallel">parallel</option>
</select>
</label>
</div>
<div class="mission-field-row hidden" id="missionJobOnceAtRow">
<label class="mission-field">
<span>Run at</span>
<input id="missionJobOnceAtInput" type="datetime-local">
</label>
</div>
<div class="mission-field-row hidden" id="missionJobEverySecondsRow">
<label class="mission-field">
<span>Every (seconds)</span>
<input id="missionJobEverySecondsInput" type="number" min="30" step="30" value="3600">
</label>
</div>
<div class="mission-field-row hidden" id="missionJobAtRow">
<label class="mission-field">
<span>At (HH:MM)</span>
<input id="missionJobAtInput" type="time" value="08:00">
</label>
</div>
<div class="mission-field-row hidden" id="missionJobWeekdayRow">
<span class="mission-field-title">Weekdays</span>
<div class="mission-weekdays" id="missionJobWeekdays">
<label class="mission-weekday-option">
<input type="checkbox" value="0" checked>
<span>Mon</span>
</label>
<label class="mission-weekday-option">
<input type="checkbox" value="1" checked>
<span>Tue</span>
</label>
<label class="mission-weekday-option">
<input type="checkbox" value="2" checked>
<span>Wed</span>
</label>
<label class="mission-weekday-option">
<input type="checkbox" value="3" checked>
<span>Thu</span>
</label>
<label class="mission-weekday-option">
<input type="checkbox" value="4" checked>
<span>Fri</span>
</label>
<label class="mission-weekday-option">
<input type="checkbox" value="5">
<span>Sat</span>
</label>
<label class="mission-weekday-option">
<input type="checkbox" value="6">
<span>Sun</span>
</label>
</div>
</div>
<div class="mission-field-row hidden" id="missionJobTimezoneRow">
<label class="mission-field">
<span>Timezone</span>
<input id="missionJobTimezoneInput" type="text" value="America/Chicago" placeholder="America/Chicago">
</label>
</div>
<div class="mission-field-row">
<label class="mission-field">
<span>Profile (optional)</span>
<input id="missionJobProfileInput" type="text" placeholder="balanced">
</label>
<label class="mission-field">
<span>Model (optional)</span>
<input id="missionJobModelInput" type="text" placeholder="gpt-5">
</label>
</div>
<label class="mission-approval-toggle" for="missionJobApprovalToggle">
<input id="missionJobApprovalToggle" type="checkbox">
<span>Require manual approval before execution</span>
</label>
<div class="mission-form-actions">
<button class="btn-primary" id="missionJobSubmitBtn" type="submit">Create Job</button>
</div>
</form>
</section>
<section class="mission-panel">
<div class="mission-panel-head">
<h3>Approvals</h3>
<span class="mission-panel-meta" id="missionApprovalsMeta">Review requests</span>
</div>
<div class="mission-list mission-list-approvals" id="missionApprovalsList">
</div>
</section>
<section class="mission-panel">
<div class="mission-panel-head">
<h3>Room Load</h3>
<span class="mission-panel-meta">Where work is concentrated</span>
</div>
<div class="mission-list mission-rooms mission-list-rooms" id="missionRoomsList">
</div>
</section>
<section class="mission-panel mission-panel-timeline">
<div class="mission-panel-head">
<h3>Recent Signals</h3>
<span class="mission-panel-meta" id="missionTimelineMeta">Latest mission events</span>
</div>
<div class="mission-list mission-list-timeline" id="missionTimelineList">
</div>
</section>
</div>
</div>`;
})();
