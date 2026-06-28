/* ============================================================================
 * composer_controls.js — composer controls/menu chrome.
 *
 * Owns ONLY the controls-popover render + toggle for the 5 conversation dials,
 * plus the back-compat shims the runtime calls by name. Everything else in the
 * send/dispatch path (initComposer, keydown, paste, drop, mic, handleSend,
 * buildSendJobFromComposer, buildChatRequestPayload, streamChatResponse, the
 * send→stop morph, the actions menu / mode chip / games handlers) is OWNED BY
 * THE EXISTING RUNTIME FILES and is untouched.
 *
 * Loaded as a CLASSIC script (not a module) BEFORE app_runtime_loader.js. The
 * five functions below are top-level `function` declarations, so they join the
 * shared global lexical scope alongside the runtime's split scripts. The
 * runtime calls them by bare name (e.g. `renderChatComposerSubbar()`), which
 * resolves to these. The functions only reference runtime-scoped state vars
 * (activeReasoningEffort, activeTokenEconomy, …) and helpers (safeString,
 * escapeHtml, resolveProfileChatControls, setSegmentedControlSelection, …) at
 * CALL time — by which point 001_preamble.js et al. have run and those bindings
 * are initialized. The body of these functions is carried over verbatim from
 * 008_easy_setup_onboarding_06.js so behavior is byte-identical.
 *
 * THE 5 DIALS ARE AN IMMUTABLE CONTRACT — see COMPOSER_REBUILD_SPEC.md §5.1.
 * Each <select> id, option set, change side-effect and module-var write below
 * must stay exactly as the runtime + buildChatRequestPayload() expect, or the
 * outgoing chat payload breaks.
 * ==========================================================================*/

'use strict';

function ensureChatComposerControls() {
    /* Resting state = ONE calm input. The five dials live behind a single quiet
       "controls" button in the composer's bottom row and only appear in a
       compact popover. The button + popover shell are authored in index.html
       for default-safety; this builder reuses them and falls back to creating
       them so the dials stay reachable even if the markup drifts. Returns the
       inner list element that renderChatComposerSubbar() fills. */
    const inputRow = composerTextarea?.closest('.composer-input-row');
    const cluster = composerTextarea
        ? document.querySelector('.composer-right-cluster')
        : null;
    const shell = composerBox instanceof HTMLElement
        ? composerBox
        : (inputRow instanceof HTMLElement ? inputRow.parentElement : null);
    if (!(shell instanceof HTMLElement)) return null;

    // Retire any leftovers from the old always-visible subbar build.
    const legacyRow = document.getElementById('chatComposerSubbar');
    if (legacyRow) legacyRow.remove();
    const legacyStyle = document.getElementById('chatComposerSubbarStyle');
    if (legacyStyle) legacyStyle.remove();

    // The quiet trigger lives in the bottom row's right cluster, left of mic/send.
    let btn = document.getElementById('composerControlsBtn');
    if (!(btn instanceof HTMLElement)) {
        const anchor = (cluster instanceof HTMLElement) ? cluster : inputRow;
        if (anchor instanceof HTMLElement) {
            btn = document.createElement('button');
            btn.type = 'button';
            btn.id = 'composerControlsBtn';
            btn.className = 'btn-icon';
            btn.title = 'Controls';
            btn.setAttribute('aria-label', 'Conversation controls');
            btn.setAttribute('aria-haspopup', 'dialog');
            btn.setAttribute('aria-controls', 'composerControlsPopover');
            btn.setAttribute('aria-expanded', 'false');
            btn.innerHTML = '<i class="ph ph-sliders-horizontal"></i>';
            const micBtn = document.getElementById('micBtn');
            if (micBtn instanceof HTMLElement && micBtn.parentElement === anchor) {
                anchor.insertBefore(btn, micBtn);
            } else {
                anchor.appendChild(btn);
            }
        }
    }

    let popover = document.getElementById('composerControlsPopover');
    if (!(popover instanceof HTMLElement)) {
        popover = document.createElement('div');
        popover.id = 'composerControlsPopover';
        popover.className = 'composer-controls-popover hidden';
        popover.setAttribute('role', 'dialog');
        popover.setAttribute('aria-label', 'Conversation controls');
        popover.setAttribute('aria-hidden', 'true');
        shell.appendChild(popover);
    }
    let list = document.getElementById('composerControlsList');
    if (!(list instanceof HTMLElement)) {
        list = document.createElement('div');
        list.id = 'composerControlsList';
        list.className = 'composer-controls-list';
        popover.appendChild(list);
    }
    return list;
}

/* Back-compat shim: several call sites still reference the old name. */
function ensureChatComposerSubbar() {
    return ensureChatComposerControls();
}

function wireComposerControlsToggle() {
    const btn = document.getElementById('composerControlsBtn');
    const popover = document.getElementById('composerControlsPopover');
    if (!(btn instanceof HTMLElement) || !(popover instanceof HTMLElement)) return;
    if (btn.dataset.controlsWired === '1') return; // idempotent across re-renders
    btn.dataset.controlsWired = '1';

    const isOpen = () => !popover.classList.contains('hidden');
    function onKeydown(event) {
        if (event.key === 'Escape') { event.preventDefault(); close(); try { btn.focus(); } catch (_) {} }
    }
    function onOutside(event) {
        if (popover.contains(event.target) || btn.contains(event.target)) return;
        close();
    }
    function open() {
        if (isOpen()) return;
        popover.classList.remove('hidden');
        popover.setAttribute('aria-hidden', 'false');
        btn.setAttribute('aria-expanded', 'true');
        btn.classList.add('active');
        document.addEventListener('keydown', onKeydown, true);
        document.addEventListener('mousedown', onOutside, true);
        const firstSelect = popover.querySelector('select');
        if (firstSelect instanceof HTMLElement) { try { firstSelect.focus(); } catch (_) {} }
    }
    function close() {
        if (!isOpen()) return;
        popover.classList.add('hidden');
        popover.setAttribute('aria-hidden', 'true');
        btn.setAttribute('aria-expanded', 'false');
        btn.classList.remove('active');
        document.removeEventListener('keydown', onKeydown, true);
        document.removeEventListener('mousedown', onOutside, true);
    }
    btn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (isOpen()) close(); else open();
    });
}

function renderChatComposerSubbar() {
    const list = ensureChatComposerControls();
    if (!(list instanceof HTMLElement)) return;

    const profileName = safeString(modelSelector?.value) || safeString(setupProviderSelector?.value);
    const controls = resolveProfileChatControls(profileName);
    const reasoningControl = controls?.model?.reasoning_effort;
    const autonomyControl = controls?.thomas?.autonomy_level;
    const tokenControl = controls?.thomas?.token_economy;
    const reasoningOptions = Array.isArray(reasoningControl?.options) ? reasoningControl.options : [];
    const autonomyOptions = Array.isArray(autonomyControl?.options) ? autonomyControl.options : [];
    const tokenOptions = Array.isArray(tokenControl?.options) ? tokenControl.options : [];

    const renderOptions = (options, selectedValue = '') => options.map((option) => {
        const value = safeString(option?.value);
        const label = safeString(option?.label) || value;
        const selected = value === safeString(selectedValue) ? ' selected' : '';
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
    }).join('');

    const tokenDisplayOptions = (tokenOptions.length ? tokenOptions : [
        { value: 'cheap', label: 'Quick' },
        { value: 'balanced', label: 'Standard' },
        { value: 'max', label: 'Thorough' },
    ]).map((option) => {
        const value = safeString(option?.value);
        const effortLabel = { cheap: 'Quick', balanced: 'Standard', optimal: 'Standard', max: 'Thorough' }[value];
        return effortLabel ? { value, label: effortLabel } : option;
    });

    list.innerHTML = `
        <div class="composer-controls-head">
            <span class="composer-controls-title">Controls</span>
            <span class="composer-controls-model" id="tcsModelReadout" title="Active model"></span>
        </div>
        <div class="composer-control-row" data-control="reasoning"${reasoningControl?.supported ? '' : ' hidden'}>
            <label class="composer-control-label" for="chatComposerReasoningSelect" title="Reasoning — how deeply the model thinks">Reasoning</label>
            <select id="chatComposerReasoningSelect" class="composer-control-select" aria-label="Reasoning depth">
                ${renderOptions(reasoningOptions, normalizeReasoningEffort(activeReasoningEffort))}
            </select>
        </div>
        <div class="composer-control-row" data-control="token_economy">
            <label class="composer-control-label" for="chatComposerTokenEconomySelect" title="Build quality — Quick (just the deliverable, fast) · Standard (solid, balanced) · Thorough (polished, may add tests)">Build</label>
            <select id="chatComposerTokenEconomySelect" class="composer-control-select" aria-label="Build quality">
                ${renderOptions(tokenDisplayOptions, safeString(activeTokenEconomy) || 'balanced')}
            </select>
        </div>
        <div class="composer-control-row" data-control="autonomy">
            <label class="composer-control-label" for="chatComposerAutonomySelect" title="Autonomy — how far Thomas runs on its own">Autonomy</label>
            <select id="chatComposerAutonomySelect" class="composer-control-select" aria-label="Autonomy level">
                ${renderOptions(autonomyOptions.length ? autonomyOptions : [
                    { value: '1', label: 'L1 Chat' },
                    { value: '2', label: 'L2 Assist' },
                    { value: '3', label: 'L3 Agent' },
                    { value: '4', label: 'L4 Full Autonomy' },
                ], String(activeAutonomyLevel || 1))}
            </select>
        </div>
        <div class="composer-control-row" data-control="file_access">
            <label class="composer-control-label" for="chatComposerFileAccessSelect" title="File access — what Thomas can write to (read-only → your PC)">File access</label>
            <select id="chatComposerFileAccessSelect" class="composer-control-select" aria-label="File access">
                ${renderOptions([
                    { value: 'read_only', label: 'Read only' },
                    { value: 'workspace', label: 'Workspace (sandbox)' },
                    { value: 'project', label: 'Project' },
                    { value: 'pc', label: 'Your PC (Desktop, Documents…)' },
                    { value: 'full', label: 'Full' },
                ], safeString(activeFileAccess) || 'workspace')}
            </select>
        </div>
        <div class="composer-control-row" data-control="guardrails">
            <label class="composer-control-label" for="chatComposerGuardrailsSelect" title="Guardrails — how strict the safety rules are">Guardrails</label>
            <select id="chatComposerGuardrailsSelect" class="composer-control-select" aria-label="Guardrails">
                ${renderOptions([
                    { value: 'open', label: 'Open' },
                    { value: 'guarded', label: 'Guarded' },
                    { value: 'fortress', label: 'Fortress' },
                ], safeString(activeGuardrails) || 'guarded')}
            </select>
        </div>
    `;

    const reasoningSelect = document.getElementById('chatComposerReasoningSelect');
    const autonomySelect = document.getElementById('chatComposerAutonomySelect');
    const tokenSelect = document.getElementById('chatComposerTokenEconomySelect');
    const guardrailsSelect = document.getElementById('chatComposerGuardrailsSelect');
    const fileAccessSelect = document.getElementById('chatComposerFileAccessSelect');
    const syncGuardrailPresetModes = (presetRaw) => {
        const preset = safeString(presetRaw) || 'guarded';
        const mode = { open: 'permissive', guarded: 'standard', fortress: 'strict' }[preset] || 'standard';
        const modes = {};
        ['sprawl_guard', 'clean_hands', 'inspector', 'load_bearing', 'safety_net', 'reach', 'gatekeeper'].forEach((id) => {
            modes[id] = mode;
        });
        try { localStorage.setItem('thomasGuardrailModes', JSON.stringify(modes)); } catch (e) {}
        try {
            fetch('/api/guardrails/policy', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modes }),
            }).catch(() => {});
        } catch (e) {}
        return modes;
    };

    // Model readout on the right of the HUD header.
    const modelReadout = document.getElementById('tcsModelReadout');
    if (modelReadout) {
        // Prefer the concrete active model id (e.g. "gpt-5.5"); fall back to a
        // user-facing provider name — NEVER the raw profile key ("openai_codex").
        const activeModelId = safeString(resolveActiveModelIdForProfile(profileName)).split('/').pop();
        let label = activeModelId;
        if (!label && modelSelector instanceof HTMLSelectElement && modelSelector.selectedOptions[0]) {
            const optText = safeString(modelSelector.selectedOptions[0].textContent);
            // The option text is the profile name; map it to a display label.
            label = optText && optText.toLowerCase() === safeString(profileName).toLowerCase()
                ? formatProviderDisplay(optText)
                : optText;
        }
        modelReadout.textContent = safeString(label) || formatProviderDisplay(profileName) || 'model';
    }

    /* ---- original change handlers: the SINGLE source of side-effects (module
       vars + setup-group mirrors + /api/preferences PATCH + localStorage). ---- */
    if (reasoningSelect instanceof HTMLSelectElement) {
        reasoningSelect.addEventListener('change', (event) => {
            activeReasoningEffort = normalizeReasoningEffort(event.target.value);
            setSegmentedControlSelection('setupReasoningEffortGroup', activeReasoningEffort);
            if (settingAdvReasoningEffort) settingAdvReasoningEffort.value = activeReasoningEffort || 'medium';
        });
    }
    if (autonomySelect instanceof HTMLSelectElement) {
        autonomySelect.addEventListener('change', (event) => {
            autonomyLevelManuallySet = true;
            activeAutonomyLevel = parseInt(event.target.value, 10) || 1;
            setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
            if (settingAutonomy) settingAutonomy.value = `L${activeAutonomyLevel}`;
            /* Persist the pick so it sticks across launches (mirror the Settings
               page save exactly — same endpoint/method, server deep-merges). */
            fetch('/api/preferences', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ autonomy: { default_level: `L${activeAutonomyLevel}` } }),
            }).catch(() => {});
        });
    }
    if (tokenSelect instanceof HTMLSelectElement) {
        tokenSelect.addEventListener('change', (event) => {
            activeTokenEconomy = safeString(event.target.value) || 'balanced';
            setSegmentedControlSelection('setupEconomyGroup', activeTokenEconomy);
            const runtimeValue = activeTokenEconomy === 'balanced' ? 'optimal' : activeTokenEconomy;
            if (settingAdvDefaultTokenEconomy) settingAdvDefaultTokenEconomy.value = runtimeValue;
        });
    }
    if (guardrailsSelect instanceof HTMLSelectElement) {
        guardrailsSelect.addEventListener('change', (event) => {
            activeGuardrails = safeString(event.target.value) || 'guarded';
            try { localStorage.setItem('thomasGuardrails', activeGuardrails); } catch (e) {}
            syncGuardrailPresetModes(activeGuardrails);
        });
    }
    if (fileAccessSelect instanceof HTMLSelectElement) {
        fileAccessSelect.addEventListener('change', (event) => {
            activeFileAccess = safeString(event.target.value) || 'workspace';
            try { localStorage.setItem('thomasFileAccess', activeFileAccess); } catch (e) {}
        });
    }

    /* ---- Presentational state only ----
       Seed each select's current value silently (programmatic .value never fires
       'change', so a render causes no side-effects) and flag rows whose dial is
       off its default so the active ones read a touch brighter. */
    const DEFAULT_VALUE = { reasoning: 'medium', autonomy: '1', token_economy: 'balanced', guardrails: 'guarded', file_access: 'workspace' };
    const markActive = (select, controlKey) => {
        if (!(select instanceof HTMLSelectElement)) return;
        const rowEl = select.closest('.composer-control-row');
        if (!rowEl) return;
        const sync = () => rowEl.classList.toggle('is-active', safeString(select.value) !== safeString(DEFAULT_VALUE[controlKey]));
        select.addEventListener('change', sync);
        sync();
    };

    // Seed values silently (programmatic .value never fires 'change' → no side-effects on render).
    if (reasoningSelect instanceof HTMLSelectElement) reasoningSelect.value = normalizeReasoningEffort(activeReasoningEffort);
    if (autonomySelect instanceof HTMLSelectElement) autonomySelect.value = String(activeAutonomyLevel || 1);
    if (tokenSelect instanceof HTMLSelectElement) tokenSelect.value = safeString(activeTokenEconomy) || 'balanced';
    if (guardrailsSelect instanceof HTMLSelectElement) guardrailsSelect.value = safeString(activeGuardrails) || 'guarded';
    if (fileAccessSelect instanceof HTMLSelectElement) fileAccessSelect.value = safeString(activeFileAccess) || 'workspace';

    markActive(reasoningSelect, 'reasoning');
    markActive(autonomySelect, 'autonomy');
    markActive(tokenSelect, 'token_economy');
    markActive(guardrailsSelect, 'guardrails');
    markActive(fileAccessSelect, 'file_access');
}

function initChatComposerSubbar() {
    ensureChatComposerControls();
    renderChatComposerSubbar();
    wireComposerControlsToggle();
}
