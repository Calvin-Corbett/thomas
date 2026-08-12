/**
 * Easy Setup onboarding modal
 * Auto-extracted from index.html to reduce file size.
 * Injected at load time before runtime scripts.
 */
(function () {
    'use strict';
    var el = document.getElementById('easySetupModal');
    if (!el) { console.warn('[Thomas] Template target #easySetupModal not found'); return; }
    el.innerHTML = `<div class="modal-backdrop" id="easySetupBackdrop">
</div>
<div class="modal-content easy-setup-content">
<div class="modal-header">
<h2>Easy Setup</h2>
<button class="btn-icon" id="easySetupCloseBtn">
<i class="ph ph-x">
</i>
</button>
</div>
<div class="easy-setup-progress-wrap">
<div class="easy-setup-progress-bar">
<div id="easySetupProgressFill">
</div>
</div>
<div class="easy-setup-progress-text" id="easySetupProgressText">Step 1 of 5</div>
</div>
<div class="modal-body easy-setup-body">
<section class="easy-setup-step" id="easySetupStep1">
<div class="easy-setup-step-head">
<h3>Choose connection path</h3>
<p id="easySetupConnectionPathCopy" data-agent-template="Pick how {{agent}} should connect to your brain. We will test it before continuing.">Pick how Thomas should connect to your brain. We will test it before continuing.</p>
</div>
<div class="easy-setup-path-grid" id="easySetupPathGrid">
<button type="button" class="easy-setup-path-card" data-path="codex">
<strong>ChatGPT (OpenAI)</strong>
<span>Sign in with your ChatGPT account (OpenAI) — no CLI needed.</span>
</button>
<button type="button" class="easy-setup-path-card" data-path="manual">
<strong>Manual API Key</strong>
<span>Lowest local footprint. Save your provider key and validate connectivity.</span>
</button>
<button type="button" class="easy-setup-path-card" data-path="local">
<strong>Local Ollama</strong>
<span>Run locally with Ollama on this machine.</span>
</button>
</div>
<div class="easy-setup-note" id="easySetupRecommendedHint">
</div>
</section>
<section class="easy-setup-step hidden" id="easySetupStep2">
<div class="easy-setup-step-head">
<h3>Connect and test</h3>
<p>Your selected path must verify before you can continue.</p>
</div>
<div class="easy-setup-connection-meta" id="easySetupConnectionMeta">
</div>
<div class="easy-setup-block hidden" id="easySetupCodexBlock">
<p class="easy-setup-note">We will check sign-in, run ChatGPT login if needed, list your available models, and validate your ChatGPT profile.</p>
<div class="easy-setup-inline-meta" id="easySetupCodexMeta">
</div>
</div>
<div class="easy-setup-block hidden" id="easySetupManualBlock">
<div class="form-group">
<label for="easySetupManualProfile">Provider Profile</label>
<select id="easySetupManualProfile" class="setup-fluid-select">
</select>
</div>
<div class="form-group">
<label for="easySetupManualApiKey">API Key</label>
<input id="easySetupManualApiKey" class="form-control" type="password" form="settingsCredentialForm" placeholder="sk-...">
</div>
<div class="switch-row easy-setup-switch-row">
<div>
<strong>Persist key</strong>
<p>Store encrypted key in local preferences.</p>
</div>
<label class="toggle-switch">
<input type="checkbox" id="easySetupManualPersist" checked>
<span class="slider round">
</span>
</label>
</div>
</div>
<div class="easy-setup-block hidden" id="easySetupLocalBlock">
<div class="form-group">
<label for="easySetupLocalProfile">Local Profile</label>
<select id="easySetupLocalProfile" class="setup-fluid-select">
</select>
</div>
<p class="easy-setup-note">Local checks verify Ollama reachability and run profile validation.</p>
</div>
<div class="easy-setup-inline-actions">
<button type="button" class="btn-primary" id="easySetupTestConnectionBtn">Connect and Test</button>
<button type="button" class="settings-mini-btn" id="easySetupAutoRepairBtn">Auto Repair</button>
</div>
<div class="easy-setup-status" id="easySetupConnectionStatus">
</div>
</section>
<section class="easy-setup-step hidden" id="easySetupStep3">
<div class="easy-setup-step-head">
<h3>Dependency approvals</h3>
<p>Nothing installs silently. Review each required dependency, then approve required downloads to continue.</p>
</div>
<div class="easy-setup-dependency-list" id="easySetupDependencyList">
</div>
<p class="easy-setup-note" id="easySetupDependencyTrustNote">
</p>
<div class="easy-setup-inline-actions">
<button type="button" class="btn-primary" id="easySetupApproveAllBtn">Approve required downloads</button>
<button type="button" class="settings-mini-btn" id="easySetupReviewDownloadsBtn">Review exact downloads</button>
</div>
<div class="easy-setup-review hidden" id="easySetupReviewPanel">
</div>
<div class="easy-setup-status" id="easySetupDependencyStatus">
</div>
</section>
<section class="easy-setup-step hidden" id="easySetupStep4">
<div class="easy-setup-step-head">
<h3>Animation style</h3>
<p>Choose how alive Thomas should feel in chat. You can change this later in Settings.</p>
</div>
<div class="easy-setup-animation-grid" id="easySetupAnimationGrid">
<button type="button" class="easy-setup-path-card easy-setup-animation-card" data-animation-fidelity="high" aria-pressed="false">
<strong>High Fidelity</strong>
<span>Full chat-world behavior with richer platform traversal, tunnel crossings, and ambient motion.</span>
<small>Highest CPU/GPU cost.</small>
</button>
<button type="button" class="easy-setup-path-card easy-setup-animation-card" data-animation-fidelity="balanced" aria-pressed="false">
<strong>Balanced</strong>
<span>Keep Thomas active and expressive, but tone down the heavier transitions.</span>
<small>Recommended for most machines.</small>
</button>
<button type="button" class="easy-setup-path-card easy-setup-animation-card" data-animation-fidelity="minimal" aria-pressed="false">
<strong>Minimal Motion</strong>
<span>Trim advanced movement and effects while keeping the task strip and core robot presence.</span>
<small>Lowest motion and render cost.</small>
</button>
</div>
<p class="easy-setup-animation-hint" id="easySetupAnimationHint">High Fidelity keeps the full chat-world platform behavior on by default.</p>
</section>
<section class="easy-setup-step hidden" id="easySetupStep5">
<div class="easy-setup-step-head">
<h3>Brain ready</h3>
<p>Connection is verified. Continue in chat for a quick personalization interview with option chips.</p>
</div>
<div class="easy-setup-ready-list" id="easySetupReadyList">
</div>
<p class="easy-setup-note">You can skip the interview later, but finishing setup still requires an explicit action.</p>
</section>
</div>
<div class="modal-footer easy-setup-footer">
<button class="settings-mini-btn" id="easySetupBackBtn">Back</button>
<button class="settings-mini-btn hidden" id="easySetupDismissBtn">Close</button>
<button class="btn-primary" id="easySetupNextBtn">Continue</button>
</div>
</div>`;
})();
