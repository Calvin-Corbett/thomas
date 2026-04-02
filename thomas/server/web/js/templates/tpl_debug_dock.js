/**
 * Debug Dock / Tools Console panel
 * Auto-extracted from index.html to reduce file size.
 * Injected at load time before runtime scripts.
 */
(function () {
    'use strict';
    var el = document.getElementById('debugDock');
    if (!el) { console.warn('[Thomas] Template target #debugDock not found'); return; }
    el.innerHTML = `<div class="debug-dock-head">
<h3>Tools Console</h3>
<div class="debug-dock-head-actions">
<button type="button" class="settings-mini-btn" id="debugDockRefreshBtn">Refresh</button>
<button type="button" class="btn-icon" id="debugDockCloseBtn" aria-label="Close tools panel">
<i class="ph ph-x">
</i>
</button>
</div>
</div>
<div class="debug-dock-tabs" id="debugDockTabs" role="tablist" aria-label="Tools views">
<button type="button" class="debug-tab-btn active" id="debugTabRuntime" data-debug-tab="runtime" role="tab" aria-selected="true" aria-controls="debugPanelRuntime" tabindex="0">Diagnostics</button>
<button type="button" class="debug-tab-btn" id="debugTabSystem" data-debug-tab="system" role="tab" aria-selected="false" aria-controls="debugPanelSystem" tabindex="-1">System</button>
<button type="button" class="debug-tab-btn" id="debugTabModels" data-debug-tab="models" role="tab" aria-selected="false" aria-controls="debugPanelModels" tabindex="-1">Models</button>
<button type="button" class="debug-tab-btn" id="debugTabTools" data-debug-tab="tools" role="tab" aria-selected="false" aria-controls="debugPanelTools" tabindex="-1">Tools</button>
<button type="button" class="debug-tab-btn" id="debugTabMemory" data-debug-tab="memory" role="tab" aria-selected="false" aria-controls="debugPanelMemory" tabindex="-1">Memory</button>
<button type="button" class="debug-tab-btn" id="debugTabRuns" data-debug-tab="runs" role="tab" aria-selected="false" aria-controls="debugPanelRuns" tabindex="-1">Runs</button>
<button type="button" class="debug-tab-btn" id="debugTabEvents" data-debug-tab="events" role="tab" aria-selected="false" aria-controls="debugPanelEvents" tabindex="-1">Events</button>
<button type="button" class="debug-tab-btn" id="debugTabConsole" data-debug-tab="console" role="tab" aria-selected="false" aria-controls="debugPanelConsole" tabindex="-1">Console</button>
<button type="button" class="debug-tab-btn" id="debugTabNetwork" data-debug-tab="network" role="tab" aria-selected="false" aria-controls="debugPanelNetwork" tabindex="-1">Network</button>
</div>
<div class="debug-dock-body">
<section class="debug-tab-panel active" id="debugPanelRuntime" data-debug-panel="runtime" role="tabpanel" aria-labelledby="debugTabRuntime">
<section class="debug-block">
<h4>Runtime Snapshot</h4>
<div class="debug-kv-list">
<div class="debug-kv">
<span>Session</span>
<code id="debugSessionId">-</code>
</div>
<div class="debug-kv">
<span>Model</span>
<code id="debugModel">-</code>
</div>
<div class="debug-kv">
<span>Messages</span>
<code id="debugMessageCount">0</code>
</div>
<div class="debug-kv">
<span>Generating</span>
<code id="debugGenerating">no</code>
</div>
<div class="debug-kv">
<span>Sidebar</span>
<code id="debugSidebarState">chat/expanded</code>
</div>
<div class="debug-kv">
<span>Search Scope</span>
<code id="debugSearchScope">chat</code>
</div>
<div class="debug-kv">
<span>Theme</span>
<code id="debugThemeName">Nebula Core</code>
</div>
<div class="debug-kv">
<span>Viewport</span>
<code id="debugViewport">-</code>
</div>
<div class="debug-kv">
<span>Events</span>
<code id="debugEventCount">0</code>
</div>
<div class="debug-kv">
<span>Console</span>
<code id="debugConsoleCount">0</code>
</div>
<div class="debug-kv">
<span>Network</span>
<code id="debugNetworkCount">0</code>
</div>
</div>
<div class="debug-actions">
<button type="button" class="settings-mini-btn" id="debugCopySnapshotBtn">Copy Snapshot</button>
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelSystem" data-debug-panel="system" role="tabpanel" aria-labelledby="debugTabSystem">
<section class="debug-block">
<h4>System Health</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Version <code id="debugSystemVersion">-</code>
</div>
<div class="debug-summary-pill">Ready <code id="debugSystemReady">-</code>
</div>
<div class="debug-summary-pill">Engines <code id="debugSystemEngineCount">0</code>
</div>
</div>
<div class="debug-system-status" id="debugSystemStatus">Use Refresh to fetch system status.</div>
<div class="debug-list-grid" id="debugSystemEngineList">
</div>
</section>
<section class="debug-block">
<h4>Onboarding Gate</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Gate <code id="debugOnboardingGateStatusPill">-</code>
</div>
<div class="debug-summary-pill">Completion <code id="debugOnboardingCompletionRate">-</code>
</div>
<div class="debug-summary-pill">Median Ready (s) <code id="debugOnboardingMedianReadySeconds">-</code>
</div>
</div>
<div class="debug-actions">
<button type="button" class="settings-mini-btn" id="debugOnboardingRepairBtn" hidden>Repair Now</button>
</div>
<div class="debug-system-status" id="debugOnboardingGateStatus">Use Refresh to fetch onboarding diagnostics.</div>
<div class="debug-list-grid" id="debugOnboardingGateList">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelModels" data-debug-panel="models" role="tabpanel" aria-labelledby="debugTabModels">
<section class="debug-block">
<h4>Model Control Plane</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Default <code id="debugModelsDefault">-</code>
</div>
<div class="debug-summary-pill">Profiles <code id="debugModelsCount">0</code>
</div>
<div class="debug-summary-pill">Healthy <code id="debugModelsHealthy">0</code>
</div>
</div>
<div class="debug-list-grid" id="debugModelHealthList">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelTools" data-debug-panel="tools" role="tabpanel" aria-labelledby="debugTabTools">
<section class="debug-block">
<h4>Tool Registry</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Total <code id="debugToolsTotal">0</code>
</div>
<div class="debug-summary-pill">Categories <code id="debugToolsCategories">0</code>
</div>
</div>
<div class="debug-chip-list" id="debugToolCategoryList">
</div>
<div class="debug-list-grid" id="debugToolRegistryList">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelMemory" data-debug-panel="memory" role="tabpanel" aria-labelledby="debugTabMemory">
<section class="debug-block">
<h4>Memory Fabric</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Enabled <code id="debugMemoryEnabled">-</code>
</div>
<div class="debug-summary-pill">Pins <code id="debugMemoryPins">0</code>
</div>
<div class="debug-summary-pill">Open Contradictions <code id="debugMemoryContradictions">0</code>
</div>
</div>
<div class="debug-list-grid" id="debugMemoryList">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelRuns" data-debug-panel="runs" role="tabpanel" aria-labelledby="debugTabRuns">
<section class="debug-block">
<h4>Run History</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Listed <code id="debugRunsCount">0</code>
</div>
<div class="debug-summary-pill">Failed <code id="debugRunsFailed">0</code>
</div>
</div>
<div class="debug-list-grid" id="debugRunsList">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelEvents" data-debug-panel="events" role="tabpanel" aria-labelledby="debugTabEvents">
<section class="debug-block">
<h4>Event Log</h4>
<div class="debug-actions">
<button type="button" class="settings-mini-btn" id="debugClearEventsBtn">Clear Events</button>
</div>
<div class="debug-event-log" id="debugEventLog">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelConsole" data-debug-panel="console" role="tabpanel" aria-labelledby="debugTabConsole">
<section class="debug-block">
<h4>Console Stream</h4>
<div class="debug-actions">
<button type="button" class="settings-mini-btn" id="debugClearConsoleBtn">Clear Console</button>
</div>
<div class="debug-console-log" id="debugConsoleLog">
</div>
</section>
</section>
<section class="debug-tab-panel" id="debugPanelNetwork" data-debug-panel="network" role="tabpanel" aria-labelledby="debugTabNetwork">
<section class="debug-block">
<h4>Network Monitor</h4>
<div class="debug-network-summary">
<div class="debug-summary-pill">Calls <code id="debugNetworkTotal">0</code>
</div>
<div class="debug-summary-pill">Errors <code id="debugNetworkErrors">0</code>
</div>
<div class="debug-summary-pill">Avg ms <code id="debugNetworkAvgMs">0</code>
</div>
</div>
<div class="debug-actions">
<button type="button" class="settings-mini-btn" id="debugClearNetworkBtn">Clear Network</button>
</div>
<div class="debug-network-log" id="debugNetworkLog">
</div>
</section>
</section>
</div>`;
})();
