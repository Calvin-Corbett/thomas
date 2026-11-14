window.__settingsInterfaceTemplate = `<section class="settings-section settings-advanced-only">
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
</section>`;
