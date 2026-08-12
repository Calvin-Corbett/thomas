/**
 * Settings Suite — full settings modal inner HTML
 * Auto-extracted from index.html to reduce file size.
 * Injected at load time before runtime scripts.
 */
(function () {
    'use strict';
    var el = document.getElementById('settingsModal');
    if (!el) { console.warn('[Thomas] Template target #settingsModal not found'); return; }
    el.innerHTML = `<div class="settings-suite-content settings-screen-shell" id="settingsSuite">
<div class="settings-screen-top">
<div class="settings-suite-left">
<button class="settings-back-btn" id="closeSettingsBtn">
<i class="ph ph-arrow-left">
</i>
<span>Back</span>
</button>
<h2>Settings Suite</h2>
</div>
<div class="settings-suite-actions">
<div class="advanced-toggle-wrap">
<span>Show More</span>
<label class="toggle-switch">
<input type="checkbox" id="settingsAdvancedToggle">
<span class="slider round">
</span>
</label>
</div>
</div>
</div>
<div class="settings-suite-body">
<aside class="settings-nav-panel" aria-label="Settings navigation">
<label class="settings-nav-search" for="settingsSectionSearch">
<i class="ph ph-magnifying-glass">
</i>
<input id="settingsSectionSearch" type="search" placeholder="Find setting section..." autocomplete="off">
</label>
<nav class="settings-nav-list" id="settingsSectionNav">
</nav>
<p class="settings-nav-empty hidden" id="settingsNavEmpty">No matching sections.</p>
</aside>
<div class="settings-sections" id="settingsSections">
<section class="settings-section">
<div class="settings-section-head">
<h3>Profile</h3>
<p>Set your assistant identity and avatar. This name appears across the workspace.</p>
</div>
<div class="profile-grid">
<div class="profile-avatar" id="settingsProfileAvatar">U</div>
<div class="profile-fields">
<div class="form-group">
<label for="settingsDisplayName">Agent Name</label>
<input id="settingsDisplayName" class="form-control" type="text" placeholder="How the assistant should be named">
</div>
<div class="settings-inline-note" id="settingsAccountMeta">Not connected</div>
<div class="profile-actions">
<button type="button" class="settings-mini-btn" id="changeAvatarBtn">Change Photo</button>
<button type="button" class="settings-mini-btn danger" id="removeAvatarBtn">Remove</button>
</div>
</div>
</div>
<input type="file" id="settingsAvatarInput" accept="image/*" class="hidden">
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Basic</h3>
<p>Essentials only. Keep this clean and fast.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAutonomy">Default Autonomy Level</label>
<select id="settingAutonomy" class="setup-fluid-select">
<option value="L1">L1 - Chat</option>
<option value="L2">L2 - Assist</option>
<option value="L3">L3 - Auto</option>
<option value="L4">L4 - Agent</option>
</select>
</div>
</div>
<div class="switch-row">
<div>
<strong>Memory</strong>
<p>Keep context between chats.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingMemoryEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Desktop Notifications</strong>
<p>Show local desktop notifications for updates.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingDesktopNotifications">
<span class="slider round">
</span>
</label>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Graphics</h3>
<p>Appearance, theme, and visual settings for Thomas.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingTheme">Theme</label>
<select id="settingTheme" class="setup-fluid-select">
<option value="auto">Nebula Core (Standard)</option>
<option value="dark">Dark</option>
<option value="light">Light</option>
<option value="aurora">Aurora</option>
<option value="sandstone">Sandstone</option>
</select>
</div>
<div class="form-group">
<label for="settingFontSize">Font Size <span id="settingFontSizeValue">16px</span>
</label>
<input id="settingFontSize" class="settings-range" type="range" min="12" max="28" step="1" value="16">
</div>
</div>
<div class="switch-row">
<div>
<strong>Space Theme Background</strong>
<p>Show the animated nebula background on the chat page.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingSpaceTheme" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Thomas Mascot</strong>
<p>Show the idle Thomas robot on the chat page.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingShowMascot" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Robot Notifications</strong>
<p>Animate the fly-in robot for chat notifications.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingRobotNotifications" checked>
<span class="slider round"></span>
</label>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Onboarding</h3>
<p>Re-run Easy Setup any time to reconnect providers or retune defaults.</p>
</div>
<div class="settings-inline-actions">
<button type="button" class="settings-mini-btn" id="rerunEasySetupBtn">Run Easy Setup</button>
<span class="settings-inline-note">Tip: type <code>/onboarding</code> in chat to launch this wizard.</span>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Workspaces</h3>
<p>Choose which workspace tabs are visible in the sidebar.</p>
</div>
<div class="switch-row">
<div>
<strong>Mission Control</strong>
<p>Task board, goals, and operational overview.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsMission" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>UI Editor</strong>
<p>Visual app builder for custom interfaces.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsAppBuilder" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Library</strong>
<p>Personal vault, saved items, and bookmarks.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsMyStuff" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Channels</strong>
<p>Messaging channels — Telegram, Discord, Slack, webhooks.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsChannels" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Token Economy</strong>
<p>Spending dashboard, budget tracking, and cost analytics.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsTokenEconomy" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Marketplace</strong>
<p>Browse and install domain modules, plugins, and integrations.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsMarketplace" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Virtual Office</strong>
<p>2D workspace with autonomous agents and live presence.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWsOffice">
<span class="slider round"></span>
</label>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Token Economy</h3>
<p>Control spending, budgets, and economy behavior.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingTeMonthlyBudget">Monthly Budget (tokens)</label>
<input id="settingTeMonthlyBudget" class="form-control" type="number" min="0" max="100000000" value="5000000" placeholder="0 = unlimited">
</div>
<div class="form-group">
<label for="settingTeBudgetAlertPct">Budget Alert Threshold</label>
<select id="settingTeBudgetAlertPct" class="setup-fluid-select">
<option value="50">50%</option>
<option value="75" selected>75%</option>
<option value="90">90%</option>
<option value="100">100% (hard cap)</option>
</select>
</div>
</div>
<div class="switch-row">
<div>
<strong>Show Spend in Sidebar</strong>
<p>Display running token count below the Token Economy nav button.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingTeShowSidebarSpend" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Auto-Summarize Spend</strong>
<p>Generate a daily summary of token usage and costs.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingTeAutoSummarize">
<span class="slider round"></span>
</label>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Channels</h3>
<p>Configure messaging integrations and channel defaults.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingChDefaultChannel">Default Channel</label>
<select id="settingChDefaultChannel" class="setup-fluid-select">
<option value="none">None</option>
<option value="telegram">Telegram</option>
<option value="discord">Discord</option>
<option value="slack">Slack</option>
<option value="webhook">Webhook</option>
</select>
</div>
<div class="form-group">
<label for="settingChMaxMessageLength">Max Message Length</label>
<input id="settingChMaxMessageLength" class="form-control" type="number" min="100" max="10000" value="4000">
</div>
</div>
<div class="switch-row">
<div>
<strong>Auto-Route Replies</strong>
<p>Send agent replies back to the originating channel automatically.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingChAutoRoute" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Channel Notifications</strong>
<p>Receive in-app notifications for incoming channel messages.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingChNotifications" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow Channel File Uploads</strong>
<p>Let channels send images and documents into Thomas.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingChAllowUploads" checked>
<span class="slider round"></span>
</label>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Marketplace &amp; Plugins</h3>
<p>Manage installed modules and plugin behavior.</p>
</div>
<div class="switch-row">
<div>
<strong>Auto-Update Plugins</strong>
<p>Keep marketplace plugins up to date automatically.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingMpAutoUpdate" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Show Domain Modules in Sidebar</strong>
<p>Add installed domain modules (Agriculture, Blockchain, etc.) to the sidebar nav.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingMpShowDomainModules">
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Allow Plugin Network Access</strong>
<p>Permit marketplace plugins to make outbound network requests.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingMpPluginNetworkAccess" checked>
<span class="slider round"></span>
</label>
</div>
<div class="form-group settings-top-gap">
<label for="settingMpInstalledPlugins">Installed Plugins</label>
<div id="settingMpInstalledPluginsList" class="settings-inline-note">No plugins installed. Visit the Marketplace to browse.</div>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Data &amp; Storage</h3>
<p>Chat history, exports, and local data management.</p>
</div>
<div class="switch-row">
<div>
<strong>Persist Chat History</strong>
<p>Keep chat sessions between app restarts.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingDataPersistHistory" checked>
<span class="slider round"></span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Auto-Archive Old Chats</strong>
<p>Move chats older than 30 days to archive automatically.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingDataAutoArchive">
<span class="slider round"></span>
</label>
</div>
<div class="settings-inline-actions">
<button type="button" class="settings-mini-btn" id="exportAllSettingsBtn">Export All Settings</button>
<button type="button" class="settings-mini-btn" id="importSettingsBtn">Import Settings</button>
<button type="button" class="settings-mini-btn danger" id="clearAllDataBtn">Clear All Data</button>
</div>
<div id="settingDataStorageUsage" class="settings-inline-note">Calculating storage usage...</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>About Thomas</h3>
<p>Platform information and links.</p>
</div>
<div class="settings-about-grid">
<div class="settings-inline-note"><strong>Version:</strong> <span id="settingAboutVersion">—</span></div>
<div class="settings-inline-note"><strong>Runtime:</strong> <span id="settingAboutRuntime">—</span></div>
<div class="settings-inline-note"><strong>Active Model:</strong> <span id="settingAboutModel">—</span></div>
<div class="settings-inline-note"><strong>Memory Entries:</strong> <span id="settingAboutMemoryCount">—</span></div>
</div>
<div class="settings-inline-actions" style="margin-top:12px">
<button type="button" class="settings-mini-btn" id="aboutCheckUpdatesBtn">Check for Updates</button>
<button type="button" class="settings-mini-btn" id="aboutViewLogsBtn">View Logs</button>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Voice + Input</h3>
<p>Fine-tune speech and microphone behavior.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingVoice">TTS Voice</label>
<input id="settingVoice" class="form-control" type="text" placeholder="default">
</div>
<div class="form-group">
<label for="settingMicDeviceId">Mic Device ID</label>
<input id="settingMicDeviceId" class="form-control" type="text" placeholder="Leave empty for system default">
</div>
<div class="form-group">
<label for="settingVoiceSpeed">Voice Speed <span id="settingVoiceSpeedValue">1.00x</span>
</label>
<input id="settingVoiceSpeed" class="settings-range" type="range" min="0.5" max="2" step="0.05" value="1">
</div>
</div>
<div class="switch-row">
<div>
<strong>Wake Word</strong>
<p>Enable always-listening wake word support.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWakeWordEnabled">
<span class="slider round">
</span>
</label>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Agent + Notifications</h3>
<p>Detailed controls for behavior and background automation.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingConcurrencyLimit">Autonomy Concurrency Limit</label>
<input id="settingConcurrencyLimit" class="form-control" type="number" min="1" max="64" value="2">
</div>
</div>
<div class="switch-row">
<div>
<strong>Web Push Notifications</strong>
<p>Allow browser push notifications.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingWebPush">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Telegram Notifications</strong>
<p>Send updates over Telegram when configured.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingTelegram">
<span class="slider round">
</span>
</label>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced API Integrations</h3>
<p>Set provider keys. Leave blank to keep current value.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingApiKeyOpenai">OpenAI API Key</label>
<input id="settingApiKeyOpenai" class="form-control" type="password" form="settingsCredentialForm" placeholder="sk-...">
</div>
<div class="form-group">
<label for="settingApiKeyAnthropic">Anthropic API Key</label>
<input id="settingApiKeyAnthropic" class="form-control" type="password" form="settingsCredentialForm" placeholder="sk-ant-...">
</div>
<div class="form-group">
<label for="settingApiKeyGoogle">Google API Key</label>
<input id="settingApiKeyGoogle" class="form-control" type="password" form="settingsCredentialForm">
</div>
<div class="form-group">
<label for="settingApiKeyElevenlabs">ElevenLabs API Key</label>
<input id="settingApiKeyElevenlabs" class="form-control" type="password" form="settingsCredentialForm">
</div>
<div class="form-group">
<label for="settingApiKeyAzureOpenai">Azure OpenAI Key</label>
<input id="settingApiKeyAzureOpenai" class="form-control" type="password" form="settingsCredentialForm">
</div>
<div class="form-group">
<label for="settingApiKeyCustom">Custom Provider Key</label>
<input id="settingApiKeyCustom" class="form-control" type="password" form="settingsCredentialForm">
</div>
</div>
<p class="settings-inline-note">Type <code>clear</code> in a key field to remove that stored key.</p>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Model Behavior</h3>
<p>Sampling, reasoning, and output controls.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvTemperature">Temperature <span id="settingAdvTemperatureValue">0.70</span>
</label>
<input id="settingAdvTemperature" class="settings-range" type="range" min="0" max="2" step="0.05" value="0.7">
</div>
<div class="form-group">
<label for="settingAdvTopP">Top P <span id="settingAdvTopPValue">1.00</span>
</label>
<input id="settingAdvTopP" class="settings-range" type="range" min="0" max="1" step="0.01" value="1">
</div>
<div class="form-group">
<label for="settingAdvFrequencyPenalty">Frequency Penalty <span id="settingAdvFrequencyPenaltyValue">0.0</span>
</label>
<input id="settingAdvFrequencyPenalty" class="settings-range" type="range" min="-2" max="2" step="0.1" value="0">
</div>
<div class="form-group">
<label for="settingAdvPresencePenalty">Presence Penalty <span id="settingAdvPresencePenaltyValue">0.0</span>
</label>
<input id="settingAdvPresencePenalty" class="settings-range" type="range" min="-2" max="2" step="0.1" value="0">
</div>
<div class="form-group">
<label for="settingAdvMaxOutputTokens">Max Output Tokens</label>
<input id="settingAdvMaxOutputTokens" class="form-control" type="number" min="128" max="32768" value="4096">
</div>
<div class="form-group">
<label for="settingAdvReasoningEffort">Reasoning Effort</label>
<select id="settingAdvReasoningEffort" class="setup-fluid-select">
<option value="low">Low</option>
<option value="medium">Medium</option>
<option value="high">High</option>
<option value="xhigh">xHigh</option>
</select>
</div>
<div class="form-group">
<label for="settingAdvReasoningBudget">Reasoning Token Budget</label>
<input id="settingAdvReasoningBudget" class="form-control" type="number" min="128" max="65536" value="4096">
</div>
<div class="form-group">
<label for="settingAdvDeterministicSeed">Deterministic Seed (optional)</label>
<input id="settingAdvDeterministicSeed" class="form-control" type="number" min="0" max="2147483647" placeholder="blank = random">
</div>
</div>
<div class="switch-row">
<div>
<strong>Strict JSON Mode</strong>
<p>Favor machine-readable responses.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvJsonMode">
<span class="slider round">
</span>
</label>
</div>
<div class="form-group settings-top-gap">
<label for="settingAdvStopSequences">Stop Sequences (comma separated)</label>
<textarea id="settingAdvStopSequences" class="form-control settings-textarea" rows="2" placeholder="e.g. ###, END">
</textarea>
</div>
</section>
<section class="settings-section settings-advanced-only">
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
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Failover + Recovery</h3>
<p>Resilience controls for provider and model switching.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvFailoverCooldownSeconds">Failover Cooldown (seconds)</label>
<input id="settingAdvFailoverCooldownSeconds" class="form-control" type="number" min="0" max="86400" value="300">
</div>
</div>
<div class="switch-row">
<div>
<strong>Enable Failover</strong>
<p>Permit model/profile fallback when primary routing fails.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvFailoverEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Chat Auto-Failover</strong>
<p>Allow regular chat turns to auto-fallback without explicit mode changes.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvChatAutoFailover">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Fallback On Auth Error</strong>
<p>Retry on alternate routes when provider auth expires or fails.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvFallbackOnAuthError">
<span class="slider round">
</span>
</label>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Privacy + Compliance</h3>
<p>Data handling, telemetry, and logging controls.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvRetentionDays">Retention Days</label>
<input id="settingAdvRetentionDays" class="form-control" type="number" min="1" max="3650" value="90">
</div>
</div>
<div class="switch-row">
<div>
<strong>Enable Telemetry</strong>
<p>Send usage telemetry for diagnostics.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvTelemetryEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Redact Secrets In Logs</strong>
<p>Hide API keys and token-like strings in logs.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvRedactSecretsInLogs">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Strict PII Guard</strong>
<p>Increase protection for sensitive user data.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvPiiGuardStrict">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Local-Only Mode</strong>
<p>Limit cloud-bound actions where possible.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvLocalOnlyMode">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Audit Log Enabled</strong>
<p>Record detailed operational audit events.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAuditLogEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Export Settings On Exit</strong>
<p>Persist an exportable settings snapshot on shutdown.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvExportOnExit">
<span class="slider round">
</span>
</label>
</div>
</section>
<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Advanced Interface + Developer</h3>
<p>Power-user UI density, observability, and labs switches.</p>
</div>
<div class="settings-grid two-col">
<div class="form-group">
<label for="settingAdvUiDensity">UI Density</label>
<select id="settingAdvUiDensity" class="setup-fluid-select">
<option value="comfortable">Comfortable</option>
<option value="compact">Compact</option>
<option value="dense">Dense</option>
</select>
</div>
<div class="form-group">
<label for="settingBubbleStyle">Message Bubble Style</label>
<select id="settingBubbleStyle" class="setup-fluid-select">
<option value="rounded">Rounded</option>
<option value="square">Square</option>
<option value="compact">Compact</option>
</select>
</div>
<div class="form-group">
<label for="settingAdvCodeTheme">Code Theme</label>
<select id="settingAdvCodeTheme" class="setup-fluid-select">
<option value="atom-one-dark">Atom One Dark</option>
<option value="github-dark">GitHub Dark</option>
<option value="monokai">Monokai</option>
<option value="nord">Nord</option>
</select>
</div>
<div class="form-group">
<label for="settingAdvEventLogVerbosity">Event Log Verbosity</label>
<select id="settingAdvEventLogVerbosity" class="setup-fluid-select">
<option value="minimal">Minimal</option>
<option value="standard">Standard</option>
<option value="verbose">Verbose</option>
</select>
</div>
</div>
<div class="switch-row">
<div>
<strong>Show Timestamps</strong>
<p>Always show message timestamps in chat.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvShowTimestamps">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Show Token Meter</strong>
<p>Display token usage metrics in UI.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvShowTokenMeter">
<span class="slider round">
</span>
</label>
</div>
<div class="form-group settings-top-gap">
<label for="settingAdvAnimationFidelity">Animation Fidelity</label>
<select id="settingAdvAnimationFidelity" class="setup-fluid-select">
<option value="high">High Fidelity</option>
<option value="balanced">Balanced</option>
<option value="minimal">Minimal Motion</option>
</select>
<p class="settings-inline-note">High Fidelity enables the full chat-world platform behavior. Minimal Motion trims the heavier effects for lower CPU/GPU load.</p>
</div>
<div class="switch-row hidden" aria-hidden="true">
<div>
<strong>Enable Animations</strong>
<p>Compatibility toggle derived from Animation Fidelity.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvAnimationsEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="switch-row">
<div>
<strong>Enable Debug Panel</strong>
<p>Expose UI-level debug and diagnostics panels.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="settingAdvDebugPanelEnabled">
<span class="slider round">
</span>
</label>
</div>
<div class="form-group settings-top-gap">
<label for="settingAdvLabsFlags">Labs Flags (comma separated)</label>
<textarea id="settingAdvLabsFlags" class="form-control settings-textarea" rows="2" placeholder="feature_x,experimental_renderer">
</textarea>
</div>
</section>
<section class="settings-section">
<div class="settings-section-head">
<h3>Thomas Overrides</h3>
<p>Advanced Thomas metadata and runtime overrides used by backend preferences.</p>
</div>
<div class="form-group">
<label for="settingThomadsConfig">Thomads Settings (JSON)</label>
<textarea id="settingThomadsConfig" class="form-control settings-textarea" rows="4" placeholder="{\\"thomads\\":true}">
</textarea>
</div>
</section>
</div>
</div>
<div class="settings-screen-footer">
<button class="btn-primary" id="saveSettingsBtn">Save Settings</button>
</div>
</div>`;
})();
