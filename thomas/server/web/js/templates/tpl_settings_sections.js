(function () {
    'use strict';

    window.renderSettingsAboutSection = function renderSettingsAboutSection() {
        return `<section class="settings-section">
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
</section>`;
    };

    window.renderInstallGuardSettingsSection = function renderInstallGuardSettingsSection() {
        return `<section class="settings-section settings-advanced-only">
<div class="settings-section-head">
<h3>Install Guard</h3>
<p>Controls how Thomas handles tool installs and update apply for this checkout. This writes to <code>thomas.toml</code>, not just browser preferences.</p>
</div>
<div class="form-group">
<label for="settingSecurityProfile">Install Guard Mode</label>
<select id="settingSecurityProfile" class="setup-fluid-select">
<option value="balanced">Balanced</option>
<option value="hands_on">Hands-On</option>
<option value="review_only">Review Only</option>
</select>
</div>
<div class="settings-inline-note" id="settingSecurityProfileSummary">Balanced keeps installs explicit and blocked from happening silently.</div>
<div class="settings-inline-note" id="settingSecurityProfileCapabilities">Loading current capabilities...</div>
<div class="settings-inline-note" id="settingSecurityProfileWhy">Use this when you want Thomas to explain changes, help prepare them, or stay fully review-only on sensitive machines.</div>
</section>`;
    };
})();
