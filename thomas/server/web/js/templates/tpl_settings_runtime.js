window.__settingsRuntimeTemplate = `<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Runtime + Quality</h3>
<p>Set default run behavior and strictness for production-grade work.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvDefaultMode">Default Run Mode</label>
<select id="settingAdvDefaultMode" class="setup-fluid-select">
<option value="auto">Auto</option>
<option value="fast">Fast</option>
<option value="thinking">Thinking</option>
</select>
</div>
<div class="form-group">
<label for="settingAdvDefaultTokenEconomy">Default Token Economy</label>
<select id="settingAdvDefaultTokenEconomy" class="setup-fluid-select">
<option value="optimal">Balanced</option>
<option value="cheap">Cheap</option>
<option value="max">Maximum</option>
</select>
</div>
<div class="form-group">
<label for="settingAdvMaxAgentIterations">Max Agent Iterations (0 = auto)</label>
<input id="settingAdvMaxAgentIterations" class="form-control" type="number" min="0" max="200" value="0">
</div>
</div>
<div class="switch-row">
<div>
<strong>Quality Enforce</strong>
<p>Hard-stop runs that fail quality gates.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvQualityEnforce">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Require Verification For Coding</strong>
<p>Force verification evidence for coding responses.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvQualityRequireVerification">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Require Tests For Code Edits</strong>
<p>Demand tests whenever files are changed.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvQualityRequireTests">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Require Monolith Guard</strong>
<p>Block oversized, brittle single-shot code changes.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvQualityRequireMonolithGuard">
<span class="slider round">
</span>
</label>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Tool Execution + Sandbox</h3>
<p>Command safety, tool fan-out, and environment limits.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvAutoToolThreshold">Auto Tool Threshold <span id="settingAdvAutoToolThresholdValue">0.45</span>
</label>
<input id="settingAdvAutoToolThreshold" class="settings-range" type="range" min="0" max="1" step="0.01" value="0.45">
</div>
<div class="form-group">
<label for="settingAdvToolTimeoutS">Tool Timeout (seconds)</label>
<input id="settingAdvToolTimeoutS" class="form-control" type="number" min="5" max="1800" value="120">
</div>
<div class="form-group">
<label for="settingAdvMaxParallelTools">Max Parallel Tools</label>
<input id="settingAdvMaxParallelTools" class="form-control" type="number" min="1" max="32" value="6">
</div>
</div>
<div class="switch-row">
<div>
<strong>Require Command Approval</strong>
<p>Force approval before shell command execution.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvRequireCommandApproval">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Keep Me Approved (Approval Window)</strong>
<p>After you approve a protected action with Windows Hello, don't ask again for the time below. Every other safety check still runs.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvBreakglassWindowEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvBreakglassWindowHours">Approval Window (hours)</label>
<input id="settingAdvBreakglassWindowHours" class="form-control" type="number" min="0.25" max="12" step="0.25" value="3">
</div>
</div>
<div class="switch-row">
<div>
<strong>Allow Shell Execution</strong>
<p>Let agents run shell commands.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAllowShell">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow File Writes</strong>
<p>Permit tools to modify files in the workspace.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAllowFileWrite">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow Network Access</strong>
<p>Permit outbound internet requests from tools.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAllowNetwork">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow Browser Tools</strong>
<p>Enable browser automation, snapshots, and web telemetry actions.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAllowBrowser">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow Channel Tools</strong>
<p>Enable messaging/channel operations (Telegram, Slack, Discord, webhooks).</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAllowChannels">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow Git + Diff Tools</strong>
<p>Enable git and patch-generation tool paths.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAllowGit">
<span class="slider round">
</span>
</label>
</div>
<div class="settings-grid two-col settings-top-gap">
<div class="form-group">
<label for="settingAdvAllowedPaths">Allowed Paths (one per line)</label>
<textarea id="settingAdvAllowedPaths" class="form-control settings-textarea" rows="3">
</textarea>
</div>
<div class="form-group">
<label for="settingAdvBlockedCommands">Blocked Commands (one per line)</label>
<textarea id="settingAdvBlockedCommands" class="form-control settings-textarea" rows="3">
</textarea>
</div>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Memory + Retrieval</h3>
<p>Control context shaping, memory quality, and contradictions.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvRetrievalTopK">Retrieval Top-K</label>
<input id="settingAdvRetrievalTopK" class="form-control" type="number" min="1" max="64" value="8">
</div>
<div class="form-group">
<label for="settingAdvMaxPackTokens">Memory Pack Token Budget</label>
<input id="settingAdvMaxPackTokens" class="form-control" type="number" min="200" max="64000" value="1200">
</div>
<div class="form-group">
<label for="settingAdvAutoSummarizeThreshold">Auto Summarize Threshold</label>
<input id="settingAdvAutoSummarizeThreshold" class="form-control" type="number" min="10" max="2000" value="80">
</div>
<div class="form-group">
<label for="settingAdvMemoryDecayDays">Memory Decay Days</label>
<input id="settingAdvMemoryDecayDays" class="form-control" type="number" min="1" max="3650" value="90">
</div>
<div class="form-group">
<label for="settingAdvDecayHalfLifeHours">Decay Half-Life (hours)</label>
<input id="settingAdvDecayHalfLifeHours" class="form-control" type="number" min="1" max="87600" step="1" value="240">
</div>
<div class="form-group">
<label for="settingAdvAutoCompactEpisodeThreshold">Auto-Compact Episode Threshold</label>
<input id="settingAdvAutoCompactEpisodeThreshold" class="form-control" type="number" min="10" max="1000000" value="2000">
</div>
<div class="form-group">
<label for="settingAdvAutoCompactMinIntervalHours">Auto-Compact Min Interval (hours)</label>
<input id="settingAdvAutoCompactMinIntervalHours" class="form-control" type="number" min="0.1" max="8760" step="0.1" value="24">
</div>
<div class="form-group">
<label for="settingAdvAutoOptimizeWasteThreshold">Auto-Optimize Waste Threshold</label>
<input id="settingAdvAutoOptimizeWasteThreshold" class="form-control" type="number" min="0" max="1" step="0.01" value="0.22">
</div>
<div class="form-group">
<label for="settingAdvAutoOptimizeMinIntervalHours">Auto-Optimize Min Interval (hours)</label>
<input id="settingAdvAutoOptimizeMinIntervalHours" class="form-control" type="number" min="0.1" max="8760" step="0.1" value="12">
</div>
<div class="form-group">
<label for="settingAdvContradictionPolicy">Contradiction Policy</label>
<select id="settingAdvContradictionPolicy" class="setup-fluid-select">
<option value="ask">Ask Before Override</option>
<option value="latest_wins">Latest Wins</option>
<option value="strict">Strict Block</option>
</select>
</div>
<div class="form-group">
<label for="settingAdvContextPruneStrategy">Context Prune Strategy</label>
<select id="settingAdvContextPruneStrategy" class="setup-fluid-select">
<option value="balanced">Balanced</option>
<option value="recency">Recency First</option>
<option value="aggressive">Aggressive Trim</option>
</select>
</div>
</div>
<div class="switch-row">
<div>
<strong>Include Global Memory</strong>
<p>Inject curated global memory alongside thread retrieval.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvIncludeGlobalMemory">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Include Profile Memory</strong>
<p>Inject profile facts into retrieval context.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvIncludeProfileMemory">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Include Thread Memory</strong>
<p>Inject thread-specific memory into retrieval context.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvIncludeThreadMemory">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Pins-Only Retrieval</strong>
<p>Only use explicitly pinned memory entries for context.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvPinsOnly">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Auto-Compact Memory</strong>
<p>Automatically compact memory when threads become large.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAutoCompactEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Auto-Optimize Memory</strong>
<p>Continuously optimize memory packs for lower waste.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAutoOptimizeEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="form-group settings-top-gap">
<label for="settingAdvPinnedContext">Pinned Context</label>
<textarea id="settingAdvPinnedContext" class="form-control settings-textarea" rows="3" placeholder="Always-include context notes">
</textarea>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Cost + Failover</h3>
<p>Budgets, retry strategy, and fallback chains.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvSessionTokenBudget">Session Token Budget</label>
<input id="settingAdvSessionTokenBudget" class="form-control" type="number" min="1000" max="5000000" value="200000">
</div>
<div class="form-group">
<label for="settingAdvDailyTokenBudget">Daily Token Budget</label>
<input id="settingAdvDailyTokenBudget" class="form-control" type="number" min="10000" max="50000000" value="2000000">
</div>
<div class="form-group">
<label for="settingAdvMaxRetries">Max Retries</label>
<input id="settingAdvMaxRetries" class="form-control" type="number" min="0" max="20" value="2">
</div>
<div class="form-group">
<label for="settingAdvRetryBackoffMs">Retry Backoff (ms)</label>
<input id="settingAdvRetryBackoffMs" class="form-control" type="number" min="0" max="120000" value="800">
</div>
</div>
<div class="switch-row">
<div>
<strong>Throttle On Budget</strong>
<p>Slow/limit actions when budget threshold is reached.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvThrottleOnBudget">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Low-Cost Mode</strong>
<p>Prefer cheaper providers and shorter outputs.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvLowCostMode">
<span class="slider round">
</span>
</label>
</div>
<div class="settings-grid two-col settings-top-gap">
<div class="form-group">
<label for="settingAdvProviderFailoverChain">Provider Failover Chain</label>
<input id="settingAdvProviderFailoverChain" class="form-control" type="text" placeholder="openai,anthropic,google">
</div>
<div class="form-group">
<label for="settingAdvModelFailoverChain">Model Failover Chain</label>
<input id="settingAdvModelFailoverChain" class="form-control" type="text" placeholder="gpt-5,gpt-4.1-mini">
</div>
</div>
</section>
`;
