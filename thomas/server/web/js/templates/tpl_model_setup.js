document.getElementById('app').insertAdjacentHTML('afterend', `<div class="thomas-modal" id="modelSetupModal">
<div class="modal-backdrop" id="modelSetupBackdrop">
</div>
<div class="modal-content model-setup-content">
<div class="modal-header">
<h2>Model Setup</h2>
<button class="btn-icon" id="closeModelSetupBtn">
<i class="ph ph-x">
</i>
</button>
</div>
<div class="modal-body">
<div class="form-group">
<label for="setupProviderPickerBtn">Provider</label>
<div class="setup-provider-picker" id="setupProviderPicker">
<button type="button" class="setup-provider-trigger" id="setupProviderPickerBtn" aria-haspopup="listbox" aria-expanded="false" aria-controls="setupProviderMenu">
<span class="setup-provider-trigger-copy">
<span class="setup-provider-trigger-label" id="setupProviderPickerLabel">Select provider</span>
<span class="setup-provider-trigger-state" id="setupProviderPickerState">Choose where Thomas should run.</span>
</span>
<i class="ph ph-caret-down">
</i>
</button>
<div class="setup-provider-menu hidden" id="setupProviderMenu" role="listbox" aria-label="Provider list">
</div>
</div>
<select id="setupProviderSelector" class="hidden">
</select>
</div>
<div class="form-group" id="setupModelOverrideGroup">
<label>Model</label>
<select id="setupModelSelector" class="setup-fluid-select">
</select>
</div>
<div class="form-group model-specialty-group" id="setupSpecialtyModelGroup">
<label for="setupSpecialtyRoleSelector">Specialties</label>
<div class="model-specialty-controls">
<select id="setupSpecialtyRoleSelector" class="setup-fluid-select">
<option value="research">Research</option>
<option value="coding">Coding</option>
<option value="planning">Planning</option>
<option value="memory">Memory</option>
<option value="tools">Tool use</option>
<option value="creative">Creative</option>
</select>
<select id="setupSpecialtyProviderSelector" class="setup-fluid-select" aria-label="Specialty provider">
</select>
<select id="setupSpecialtyModelSelector" class="setup-fluid-select" aria-label="Specialty model">
</select>
<button type="button" class="settings-mini-btn" id="setupSpecialtyClearBtn">Inherit</button>
</div>
<p class="model-specialty-status" id="setupSpecialtyStatus">Roles inherit the base model until a specialty override is selected.</p>
</div>
<div class="form-group" id="setupReasoningGroup" style="display:none">
<label>Reasoning</label>
<div class="segmented-control" id="setupReasoningEffortGroup">
<button class="segment" data-level="low">Low</button>
<button class="segment active" data-level="medium">Medium</button>
<button class="segment" data-level="high">High</button>
<button class="segment" data-level="xhigh">xHigh</button>
</div>
<p class="setup-hint">The model's own thinking depth (its native setting). Higher spends more time reasoning before it answers — better on hard problems, slower and pricier on easy ones.</p>
</div>
<div class="form-group split-group">
<div class="form-subgroup">
<label>Personality Preset</label>
<select id="setupPersonalitySelector" class="setup-fluid-select">
<option value="">Default Assistant</option>
<option value="You are a helpful and friendly companion. Use emojis.">Friendly Companion </option>
<option value="You are a terse senior software engineer. Answer directly in code with zero fluff."> Senior Coder</option>
<option value="custom">Custom (Override)</option>
</select>
</div>
</div>
<div class="form-group hidden" id="customPersonalityGroup">
<label>Custom System Prompt</label>
<textarea id="setupCustomPrompt" rows="3" placeholder="You are Thomas..." data-agent-placeholder-template="You are {{agent}}...">
</textarea>
</div>
<div class="form-group">
<label>Autonomy</label>
<div class="segmented-control" id="setupAutonomyGroup">
<button class="segment active" data-level="1">L1 <span>Chat</span>
</button>
<button class="segment" data-level="2">L2 <span>Assist</span>
</button>
<button class="segment" data-level="3">L3 <span>Agent</span>
</button>
<button class="segment" data-level="4">L4 <span>Full</span>
</button>
</div>
<p class="setup-hint">How far Thomas goes on its own. <b>L1 Chat</b> — answers only. <b>L2 Assist</b> — drafts and suggests, you approve. <b>L3 Agent</b> — runs multi-step tasks, checks in on big calls. <b>L4 Full</b> — plans and executes end-to-end without stopping to ask.</p>
</div>
<div class="form-group">
<label>Effort</label>
<div class="segmented-control" id="setupEconomyGroup">
<button class="segment" data-level="cheap">Brisk</button>
<button class="segment active" data-level="balanced">Diligent</button>
<button class="segment" data-level="max">Exhaustive</button>
</div>
<p class="setup-hint">How hard Thomas works on a task. No setting limits how many steps a run may take — Thomas stops when it is done. <b>Brisk</b> — lowest cost: no auto-repair attempt after a failed check, and the leanest build brief. <b>Diligent</b> — the default: auto-repair follows your configured retry count. <b>Exhaustive</b> — staffs a crew, runs adversarial review passes and a quality rubric, and self-corrects until it's right (slowest, most expensive).</p>
</div>
<div class="form-group" id="setupGuardrailsGroupWrap">
<label>Guardrails</label>
<div class="segmented-control" id="setupGuardrailsGroup">
<button class="segment" data-level="open">Open</button>
<button class="segment active" data-level="guarded">Guarded</button>
<button class="segment" data-level="fortress">Fortress</button>
</div>
<p class="setup-hint"><b>Open</b> — minimal friction, fewest checks. <b>Guarded</b> — sensible defaults. <b>Fortress</b> — maximum strictness. Safety-critical Vault checks (secrets, destructive actions) always stay on and can't be turned off.</p>
<button type="button" class="settings-mini-btn" id="setupGuardrailsDetailBtn" aria-expanded="false">Detailed guardrails &#9662;</button>
<div class="guardrail-detail hidden" id="setupGuardrailDetail" role="group" aria-label="Per-group guardrails"></div>
</div>
<div class="form-group switch-group">
<div class="switch-label">
<strong>Memory Engine</strong>
<span>Persist context across sessions natively</span>
</div>
<label class="toggle-switch">
<input type="checkbox" id="setupMemoryToggle" checked>
<span class="slider round">
</span>
</label>
</div>
</div>
<div class="modal-footer" style="justify-content:space-between">
<button class="btn-secondary" id="restartServerBtn" title="Restart Thomas server" style="font-size:0.85rem">&#8635; Restart Server</button>
<button class="btn-primary" id="applyModelSetupBtn">Apply Configuration</button>
</div>
</div>
</div>
`);
