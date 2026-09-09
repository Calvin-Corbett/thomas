function showStarterSuggestionRail({ force = false, title = '' } = {}) {
    if (!force && safeString(suggestionContext) === 'onboarding') return;
    if (easySetupState.interviewStarted) return;
    const onboardingDone = isOnboardingComplete();
    const heading = safeString(title) || 'Suggestions';
    setAssistantSuggestions({
        title: heading,
        context: onboardingDone ? 'starter' : 'setup',
        dismissible: onboardingDone,
        options: buildStarterSuggestionOptions(),
    });
}

async function fetchBootDoctorRecoveryNotice() {
    const probe = await fetchJsonSafe('/api/bootdoctor/recovery_notice?consume=1', { timeoutMs: 2000 });
    if (!probe.ok) return null;
    const notice = probe.data && typeof probe.data === 'object' ? probe.data.notice : null;
    if (!notice || typeof notice !== 'object') return null;
    return notice;
}

async function maybeRenderSessionIntro() {
    if (!chatMessagesInner) return;
    const sid = safeString(sessionId);
    if (!sid || introShownSessionIds.has(sid)) return;
    if (chatMessagesInner.children.length > 0) return;
    introShownSessionIds.add(sid);

    const notice = await fetchBootDoctorRecoveryNotice();
    const message = safeString(notice?.message);
    const noticeId = `bootdoctor-recovery-${safeString(notice?.updated_at_utc || sid)}`;
    if (!message) return;
    const appended = appendAssistantChatHistoryMessage(message, noticeId);
    if (!appended) return;
    if (welcomeScreen) welcomeScreen.classList.add('hidden');
    if (chatScrollArea) chatScrollArea.classList.remove('hidden');
    showStarterSuggestionRail({ force: true, title: 'Recovered' });
}

function maybeShowAssistantFollowups() {
    if (!isOnboardingComplete()) return;
    if (easySetupState.interviewStarted) return;
    if (safeString(suggestionContext) === 'onboarding') return;
    setAssistantSuggestions({
        title: 'Suggestions',
        context: 'followup',
        dismissible: true,
        options: buildUniversalFollowupSuggestionOptions(),
    });
}

function refreshEasySetupProfileOptions() {
    const profiles = Array.isArray(availableModelProfiles) ? availableModelProfiles : [];
    const manualProfiles = profiles.filter((p) => {
        const provider = safeString(p?.provider).toLowerCase();
        return provider !== 'codex' && provider !== 'openai_codex' && provider !== 'openai-codex' && provider !== 'ollama' && provider !== 'local';
    });
    const localProfiles = profiles.filter((p) => {
        const provider = safeString(p?.provider).toLowerCase();
        return provider === 'ollama' || provider === 'local';
    });

    if (easySetupManualProfile) {
        easySetupManualProfile.innerHTML = '';
        const source = manualProfiles.length > 0
            ? manualProfiles
            : profiles.filter((p) => {
                const provider = safeString(p?.provider).toLowerCase();
                const name = safeString(p?.name).toLowerCase();
                return name !== 'codex' && name !== 'chatgpt' && provider !== 'codex' && provider !== 'openai_codex' && provider !== 'openai-codex';
            });
        source.forEach((profile) => {
            const option = document.createElement('option');
            option.value = safeString(profile?.name);
            option.textContent = `${safeString(profile?.name)} (${safeString(profile?.provider) || 'provider'})`;
            easySetupManualProfile.appendChild(option);
        });
        if (easySetupManualProfile.options.length === 0) {
            const fallback = document.createElement('option');
            fallback.value = '';
            fallback.textContent = 'No cloud profile configured';
            easySetupManualProfile.appendChild(fallback);
        }
    }

    if (easySetupLocalProfile) {
        easySetupLocalProfile.innerHTML = '';
        const source = localProfiles.length > 0 ? localProfiles : [{ name: 'local', provider: 'ollama' }];
        source.forEach((profile) => {
            const option = document.createElement('option');
            option.value = safeString(profile?.name) || 'local';
            option.textContent = `${safeString(profile?.name) || 'local'} (${safeString(profile?.provider) || 'ollama'})`;
            easySetupLocalProfile.appendChild(option);
        });
    }
}

function renderEasySetupPathCards() {
    if (!easySetupPathGrid) return;
    easySetupPathGrid.querySelectorAll('[data-path]').forEach((btn) => {
        const selected = safeString(btn.getAttribute('data-path')) === safeString(easySetupState.selectedPath);
        btn.classList.toggle('selected', selected);
    });
}

function syncEasySetupAnimationCards() {
    if (!easySetupAnimationGrid) return;
    const fidelity = normalizeAnimationFidelity(easySetupState.animationFidelity, recommendedAnimationFidelity());
    easySetupState.animationFidelity = fidelity;
    easySetupAnimationGrid.querySelectorAll('[data-animation-fidelity]').forEach((btn) => {
        const selected = safeString(btn.getAttribute('data-animation-fidelity')) === fidelity;
        btn.classList.toggle('selected', selected);
        btn.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    if (easySetupAnimationHint) {
        if (fidelity === ANIMATION_FIDELITY_MINIMAL) {
            easySetupAnimationHint.textContent = 'Minimal Motion keeps Thomas mostly grounded and trims expensive effects.';
        } else if (fidelity === ANIMATION_FIDELITY_BALANCED) {
            easySetupAnimationHint.textContent = 'Balanced keeps the chat robot alive but tones down the heavier traversal effects.';
        } else {
            easySetupAnimationHint.textContent = 'High Fidelity keeps the full portal, platform, ladder, stairs, and hidden-tunnel behavior on by default.';
        }
    }
}

function ensureEasySetupPhysicsControls() {
    if (!(easySetupStep4 instanceof HTMLElement)) return null;
    let row = easySetupStep4.querySelector('#easySetupPhysicsRow');
    if (row instanceof HTMLElement) return row;
    row = document.createElement('div');
    row.id = 'easySetupPhysicsRow';
    row.className = 'switch-row easy-setup-switch-row';
    row.innerHTML = `
        <div>
            <strong>Advanced Chat Physics</strong>
            <p>Enable the Phaser-backed chat world with real colliders, grounded bodies, and physics-driven movement. Higher CPU/GPU cost.</p>
        </div>
        <label class="toggle-switch">
            <input type="checkbox" id="easySetupPhysicsToggle">
            <span class="slider round"></span>
        </label>
    `;
    easySetupStep4.appendChild(row);
    const toggle = getEasySetupPhysicsToggle();
    if (toggle instanceof HTMLInputElement) {
        toggle.addEventListener('change', async () => {
            easySetupState.chatPhysicsEnabled = Boolean(toggle.checked);
            syncEasySetupPhysicsControls();
            await persistOnboardingPrefs({
                current_step: easySetupStepName(easySetupState.step),
                answers: {
                    animation_fidelity: easySetupState.animationFidelity,
                    advanced_chat_physics: easySetupState.chatPhysicsEnabled,
                },
            });
        });
    }
    return row;
}

function syncEasySetupPhysicsControls() {
    const row = ensureEasySetupPhysicsControls();
    const toggle = getEasySetupPhysicsToggle();
    if (!(row instanceof HTMLElement) || !(toggle instanceof HTMLInputElement)) return;
    const fidelity = normalizeAnimationFidelity(easySetupState.animationFidelity, recommendedAnimationFidelity());
    const available = fidelity !== ANIMATION_FIDELITY_MINIMAL;
    if (!available) {
        easySetupState.chatPhysicsEnabled = false;
    }
    toggle.checked = available && Boolean(easySetupState.chatPhysicsEnabled);
    toggle.disabled = !available;
    row.classList.toggle('is-disabled', !available);
}

/**
 * Resolve the provider key of the profile currently selected in the manual
 * easy-setup path (the <select id="easySetupManualProfile">). Returns a lower-
 * case provider identity (e.g. 'anthropic', 'openai', 'gemini') or '' if none.
 */
function easySetupManualProviderKey() {
    const profileName = safeString(easySetupManualProfile?.value);
    if (!profileName) return '';
    const profile = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name).toLowerCase() === profileName.toLowerCase())
        : null;
    return safeString(profile?.provider || profileName).toLowerCase();
}

/**
 * Provider-aware guidance for the manual API-key path. Returns the connection
 * meta sentence + the API-key source guidance for the selected provider, so the
 * copy never hardcodes ChatGPT/Codex for an Anthropic or Google profile.
 */
function easySetupManualProviderGuidance(providerKeyRaw = '') {
    const key = safeString(providerKeyRaw).toLowerCase();
    const display = formatProviderDisplay(key || 'provider') || 'your provider';
    let keySource = `Paste your ${display} API key, then run live connectivity validation.`;
    if (key.includes('anthropic') || key.includes('claude')) {
        keySource = 'Paste your Anthropic API key from console.anthropic.com, then run live connectivity validation.';
    } else if (key.includes('openai') || key.includes('gpt') || key.includes('chatgpt')) {
        keySource = 'Paste your OpenAI API key from platform.openai.com/api-keys, then run live connectivity validation.';
    } else if (key.includes('google') || key.includes('gemini')) {
        keySource = 'Paste your Google AI Studio (Gemini) API key from aistudio.google.com/app/apikey, then run live connectivity validation.';
    } else if (key.includes('mistral')) {
        keySource = 'Paste your Mistral API key from console.mistral.ai, then run live connectivity validation.';
    } else if (key.includes('groq')) {
        keySource = 'Paste your Groq API key from console.groq.com/keys, then run live connectivity validation.';
    } else if (key.includes('xai') || key.includes('grok')) {
        keySource = 'Paste your xAI (Grok) API key from console.x.ai, then run live connectivity validation.';
    } else if (key.includes('openrouter')) {
        keySource = 'Paste your OpenRouter API key from openrouter.ai/keys, then run live connectivity validation.';
    } else if (key.includes('perplexity')) {
        keySource = 'Paste your Perplexity API key from perplexity.ai/settings/api, then run live connectivity validation.';
    }
    return {
        display,
        meta: `Manual key path. ${keySource}`,
        keySource,
    };
}

function syncEasySetupConnectionBlocks() {
    if (easySetupCodexBlock) easySetupCodexBlock.classList.toggle('hidden', easySetupState.selectedPath !== 'codex');
    if (easySetupManualBlock) easySetupManualBlock.classList.toggle('hidden', easySetupState.selectedPath !== 'manual');
    if (easySetupLocalBlock) easySetupLocalBlock.classList.toggle('hidden', easySetupState.selectedPath !== 'local');

    if (easySetupConnectionMeta) {
        if (easySetupState.selectedPath === 'codex') {
            easySetupConnectionMeta.textContent = 'ChatGPT (OpenAI) sign-in. Sign in with your ChatGPT account and validate your profile — no CLI needed.';
        } else if (easySetupState.selectedPath === 'manual') {
            easySetupConnectionMeta.textContent = easySetupManualProviderGuidance(easySetupManualProviderKey()).meta;
        } else if (easySetupState.selectedPath === 'local') {
            easySetupConnectionMeta.textContent = 'Local path. Validate Ollama endpoint and profile readiness on this machine.';
        } else {
            easySetupConnectionMeta.textContent = 'Select a path first, then run a real verification.';
        }
    }
}

function buildEasySetupDependencyPlan(bootstrap, selectedPath) {
    const tools = bootstrap?.tools || {};
    const plan = [];

    const addDep = (id, title, ready, required, note, installUrl = '') => {
        plan.push({
            id,
            title,
            ready: Boolean(ready),
            required: Boolean(required),
            note: safeString(note),
            install_url: safeString(installUrl),
        });
    };

    if (selectedPath === 'codex') {
        // ChatGPT path uses native OAuth — no CLI download of any kind.
        addDep('chatgpt_oauth', 'Sign in with ChatGPT (OpenAI)', true, false, 'Thomas signs in with your ChatGPT account directly — nothing to install.', '');
    } else if (selectedPath === 'local') {
        addDep('ollama_installed', 'Ollama installed', tools?.ollama?.installed, true, 'Local runtime for on-device model execution.', tools?.ollama?.install_url || 'https://ollama.com/download');
        addDep('ollama_running', 'Ollama service running', tools?.ollama?.running, true, 'Verifies local Ollama service is reachable.', tools?.ollama?.install_url || 'https://ollama.com/download');
    } else if (selectedPath === 'manual') {
        // Provider-aware: only an API key is needed, never a CLI.
        const guidance = easySetupManualProviderGuidance(easySetupManualProviderKey());
        addDep('manual_key', `${guidance.display} key connected`, easySetupState.verified, false, guidance.keySource, '');
    }

    return plan;
}

function missingRequiredDependencies(plan) {
    return (plan || []).filter((item) => Boolean(item.required) && !Boolean(item.ready));
}

function buildEasySetupDependencyTrustNote(selectedPath, plan) {
    const path = safeString(selectedPath);
    const items = Array.isArray(plan) ? plan : [];
    const required = items.filter((item) => Boolean(item?.required));
    const missingRequired = required.filter((item) => !Boolean(item?.ready)).length;
    const requiredCount = required.length;
    const requiredText = requiredCount === 0
        ? 'This path does not require extra local runtime downloads.'
        : `This path uses ${requiredCount} required core tool${requiredCount === 1 ? '' : 's'}.`;
    const missingText = missingRequired > 0
        ? `${missingRequired} required item${missingRequired === 1 ? '' : 's'} still need approval.`
        : 'Required items are already available or not needed.';
    let pathGuidance = '';
    if (path === 'manual') {
        pathGuidance = 'Manual API Key is the lowest-download path.';
    } else if (path === 'codex') {
        pathGuidance = 'ChatGPT (OpenAI) signs in natively in Thomas — nothing to install.';
    } else if (path === 'local') {
        pathGuidance = 'Local path requires Ollama running on this machine.';
    }
    return `Security check: nothing installs until you approve it. ${requiredText} ${missingText} ${pathGuidance}`.trim();
}

function renderEasySetupDependencies() {
    if (!easySetupDependencyList) return;
    easySetupDependencyList.innerHTML = '';
    const plan = Array.isArray(easySetupState.dependencyPlan) ? easySetupState.dependencyPlan : [];
    if (plan.length === 0) {
        easySetupDependencyList.innerHTML = '<div class="easy-setup-note">No dependency checks were generated for this path.</div>';
        if (easySetupDependencyTrustNote) {
            easySetupDependencyTrustNote.textContent = 'Security check: this path currently has no dependency checks.';
        }
        return;
    }
    plan.forEach((dep) => {
        const row = document.createElement('div');
        row.className = 'easy-setup-dep-item';
        const stateClass = dep.ready ? 'ready' : (dep.required ? 'missing' : '');
        const stateText = dep.ready ? 'Ready' : (dep.required ? 'Required' : 'Optional');
        row.innerHTML = `
            <div>
                <strong>${escapeHtml(dep.title)}</strong>
                <span>${escapeHtml(dep.note)}</span>
            </div>
            <span class="easy-setup-dep-pill ${stateClass}">${stateText}</span>
        `;
        easySetupDependencyList.appendChild(row);
    });
    if (easySetupDependencyTrustNote) {
        easySetupDependencyTrustNote.textContent = buildEasySetupDependencyTrustNote(easySetupState.selectedPath, plan);
    }
}

function setEasySetupDependencyDefaultStatus() {
    const missing = missingRequiredDependencies(easySetupState.dependencyPlan).length;
    if (missing > 0) {
        setEasySetupStatus(easySetupDependencyStatus, 'Approve required downloads to continue.');
    } else {
        setEasySetupStatus(easySetupDependencyStatus, 'No required downloads pending for this path. Continue when ready.', 'ok');
    }
}

function renderEasySetupReviewPanel() {
    if (!easySetupReviewPanel) return;
    easySetupReviewPanel.innerHTML = '';
    const plan = Array.isArray(easySetupState.dependencyPlan) ? easySetupState.dependencyPlan : [];
    if (plan.length === 0) {
        easySetupReviewPanel.classList.add('hidden');
        return;
    }
    plan.forEach((dep) => {
        const item = document.createElement('div');
        item.className = 'easy-setup-review-item';
        const state = dep.ready ? 'ready' : (dep.required ? 'missing' : 'optional');
        const installUrl = safeString(dep.install_url);
        item.innerHTML = `<strong>${escapeHtml(dep.title)}</strong> - ${escapeHtml(dep.note)} (status: ${escapeHtml(state)})`;
        if (installUrl) {
            const link = document.createElement('a');
            link.href = installUrl;
            link.target = '_blank';
            link.rel = 'noreferrer';
            link.textContent = 'Install link';
            item.appendChild(document.createTextNode(' '));
            item.appendChild(link);
        }
        easySetupReviewPanel.appendChild(item);
    });
}

function updateEasySetupReadyList() {
    if (!easySetupReadyList) return;
    const verifiedProfile = safeString(easySetupState.verifiedProfile) || 'n/a';
    const codexModelCount = Array.isArray(easySetupState.codexModels) ? easySetupState.codexModels.length : 0;
    const depPlan = Array.isArray(easySetupState.dependencyPlan) ? easySetupState.dependencyPlan : [];
    const depMissing = missingRequiredDependencies(depPlan).length;

    const rows = [
        `Connection path: ${safeString(easySetupState.selectedPath) || 'not selected'}`,
        `Verification: ${easySetupState.verified ? 'passed' : 'not verified'}`,
        `Validated profile: ${formatProviderDisplay(verifiedProfile) || verifiedProfile}`,
    ];
    if (easySetupState.selectedPath === 'codex' && codexModelCount > 0) {
        rows.push(`ChatGPT models detected: ${codexModelCount}`);
    }
    rows.push(
        `Animation fidelity: ${normalizeAnimationFidelity(easySetupState.animationFidelity, recommendedAnimationFidelity())}`,
        `Advanced chat physics: ${easySetupState.chatPhysicsEnabled ? 'enabled' : 'disabled'}`,
        depMissing > 0
            ? `Required downloads still missing: ${depMissing}`
            : 'Required downloads: complete or not needed for selected path.',
    );

    easySetupReadyList.innerHTML = '';
    rows.forEach((rowText) => {
        const row = document.createElement('div');
        row.className = 'easy-setup-ready-item';
        row.innerHTML = `<i class="ph ph-check-circle"></i><span>${escapeHtml(rowText)}</span>`;
        easySetupReadyList.appendChild(row);
    });
}

function updateEasySetupNavigation() {
    if (!easySetupBackBtn || !easySetupNextBtn) return;
    easySetupBackBtn.style.visibility = easySetupState.step <= 1 ? 'hidden' : 'visible';
    easySetupNextBtn.textContent = easySetupState.step >= EASY_SETUP_TOTAL_STEPS ? 'Continue in chat' : 'Continue';

    let disableNext = false;
    if (easySetupState.step === 1) {
        disableNext = !safeString(easySetupState.selectedPath);
    } else if (easySetupState.step === 2) {
        disableNext = !easySetupState.verified;
    } else if (easySetupState.step === 3) {
        const missing = missingRequiredDependencies(easySetupState.dependencyPlan).length;
        disableNext = missing > 0 && safeString(easySetupState.dependenciesAction) === 'pending';
    } else if (easySetupState.step === 4) {
        disableNext = !normalizeAnimationFidelity(easySetupState.animationFidelity, '');
    }
    easySetupNextBtn.disabled = disableNext;

    const dismissAllowed = !easySetupState.required;
    if (easySetupDismissBtn) {
        easySetupDismissBtn.textContent = easySetupState.required ? 'Skip for now' : 'Close';
        easySetupDismissBtn.classList.toggle('hidden', false);
    }
    if (easySetupCloseBtn) {
        easySetupCloseBtn.classList.toggle('hidden', !dismissAllowed);
    }
    if (easySetupBackdrop) {
        easySetupBackdrop.classList.toggle('easy-setup-backdrop-locked', !dismissAllowed);
    }
}

function setEasySetupStep(step) {
    easySetupState.step = Math.max(1, Math.min(EASY_SETUP_TOTAL_STEPS, Number(step) || 1));
    if (easySetupStep1) easySetupStep1.classList.toggle('hidden', easySetupState.step !== 1);
    if (easySetupStep2) easySetupStep2.classList.toggle('hidden', easySetupState.step !== 2);
    if (easySetupStep3) easySetupStep3.classList.toggle('hidden', easySetupState.step !== 3);
    if (easySetupStep4) easySetupStep4.classList.toggle('hidden', easySetupState.step !== 4);
    if (easySetupStep5) easySetupStep5.classList.toggle('hidden', easySetupState.step !== 5);

    if (easySetupProgressFill) {
        easySetupProgressFill.style.width = `${(easySetupState.step / EASY_SETUP_TOTAL_STEPS) * 100}%`;
    }
    if (easySetupProgressText) {
        easySetupProgressText.textContent = `Step ${easySetupState.step} of ${EASY_SETUP_TOTAL_STEPS}`;
    }

    renderEasySetupPathCards();
    syncEasySetupAnimationCards();
    syncEasySetupConnectionBlocks();
    if (easySetupState.step === 3) {
        renderEasySetupDependencies();
    }
    if (easySetupState.step === 5) {
        updateEasySetupReadyList();
    }
    updateEasySetupNavigation();
}

async function loadEasySetupBootstrap() {
    const res = await fetchJsonSafe('/api/setup/bootstrap');
    if (!res.ok || !res.data) {
        throw new Error(res.text || `Setup bootstrap failed (${res.status})`);
    }
    easySetupState.bootstrap = res.data;
    return res.data;
}

function recommendedLocalModelIdsFromPlan(localPlan) {
    const rows = Array.isArray(localPlan?.recommended_models) ? localPlan.recommended_models : [];
    const ids = [];
    rows.forEach((row) => {
        const id = safeString(row?.id);
        if (!id) return;
        if (!ids.includes(id)) ids.push(id);
    });
    return ids;
}

async function runEasySetupLocalModelSync(profile = 'local') {
    let modelIds = recommendedLocalModelIdsFromPlan(easySetupState.bootstrap?.local_plan);
    if (modelIds.length === 0) {
        const recRes = await fetchJsonSafe(`/api/local/recommendations?profile=${encodeURIComponent(profile)}`);
        if (recRes.ok && recRes.data) {
            const nextPlan = recRes.data?.local_plan;
            modelIds = recommendedLocalModelIdsFromPlan(nextPlan);
            if (nextPlan && easySetupState.bootstrap && typeof easySetupState.bootstrap === 'object') {
                easySetupState.bootstrap.local_plan = nextPlan;
            }
        }
    }

    if (modelIds.length === 0) {
        return {
            skipped: true,
            summary: 'No hardware-recommended local models for this device tier. Continuing with local profile only.',
        };
    }

    const syncRes = await fetchJsonSafe('/api/local/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            profile,
            model_ids: modelIds,
            use_recommended: false,
            pull_missing_only: true,
            verify_only: false,
        }),
        timeoutMs: 1800000,
    });
    if (!syncRes.ok || !syncRes.data) {
        const reason = safeString(syncRes.text) || `Local model sync failed (${syncRes.status})`;
        throw new Error(`${reason} Remediation: ensure Ollama is running and retry.`);
    }

    const rows = Array.isArray(syncRes.data?.results) ? syncRes.data.results : [];
    const failedRows = rows.filter((row) => !Boolean(row?.ok));
    if (failedRows.length > 0) {
        const failed = failedRows.map((row) => safeString(row?.model_id)).filter(Boolean).join(', ');
        const detail = failed ? ` Failed: ${failed}.` : '';
        throw new Error(`Local model sync completed with failures.${detail} Remediation: run Auto Repair and retry.`);
    }

    const pulledCount = rows.filter((row) => Boolean(row?.pulled)).length;
    const reusedCount = rows.filter((row) => Boolean(row?.already_installed)).length;
    const verifiedCount = rows.filter((row) => Boolean(row?.verified)).length;
    let summary = `Verified ${verifiedCount}/${rows.length} local model${rows.length === 1 ? '' : 's'}.`;
    if (pulledCount > 0) summary += ` Pulled ${pulledCount} missing.`;
    if (reusedCount > 0) summary += ` Reused ${reusedCount} already installed.`;
    return {
        skipped: false,
        summary,
    };
}

function resolveEasySetupSelectedProfile() {
    if (safeString(easySetupState.verifiedProfile)) return safeString(easySetupState.verifiedProfile);
    if (easySetupState.selectedPath === 'manual') return safeString(easySetupManualProfile?.value);
    if (easySetupState.selectedPath === 'local') return safeString(easySetupLocalProfile?.value) || 'local';
    if (easySetupState.selectedPath === 'codex') {
        const codexProfile = findEasySetupNativeCodexProfile()
            || (availableModelProfiles || []).find((profile) => (
                safeString(profile?.provider).toLowerCase() === 'codex'
                || safeString(profile?.name).toLowerCase() === 'codex'
            ));
        return safeString(codexProfile?.name) || 'codex';
    }
    return safeString(currentPreferences?.advanced?.model?.active_profile);
}

function findEasySetupNativeCodexProfile() {
    return (availableModelProfiles || []).find((profile) => {
        const provider = safeString(profile?.provider).toLowerCase();
        const name = safeString(profile?.name).toLowerCase();
        return provider === 'openai_codex' || provider === 'openai-codex' || provider === 'codex' || name === 'chatgpt';
    }) || null;
}

function resolveEasySetupSelectedModelId(profileName = '') {
    const profile = safeString(profileName);
    if (!profile) return '';
    const codexModel = easySetupState.selectedPath === 'codex' && Array.isArray(easySetupState.codexModels)
        ? safeString(easySetupState.codexModels[0])
        : '';
    return codexModel
        || resolveStoredModelSelection(profile, { allowLocalBackup: true })
        || defaultModelIdForProfile(profile);
}

/**
 * BUG 2 FIX: when a connection test verifies a provider/profile in easy setup,
 * make that profile the ACTIVE model so the choice actually sticks (and survives
 * a reload). Mirrors the verified-working model-setup Apply path: PATCH
 * advanced.model.active_profile + model_id, refresh in-memory model state, and
 * update the header + composer labels immediately. Without this the wizard
 * configured a profile but never activated it, so the old/default model stayed.
 */
function initEasySetup() {
    if (!easySetupModal) return;
    if (easySetupDismissBtn) {
        easySetupDismissBtn.textContent = 'Skip for now';
        easySetupDismissBtn.classList.remove('hidden');
    }
    if (easySetupCloseBtn) {
        easySetupCloseBtn.classList.add('hidden');
    }

    if (easySetupPathGrid) {
        easySetupPathGrid.querySelectorAll('[data-path]').forEach((btn) => {
            btn.addEventListener('click', () => {
                handleEasySetupPathSelect(btn.getAttribute('data-path'));
            });
        });
    }
    if (easySetupAnimationGrid) {
        easySetupAnimationGrid.querySelectorAll('[data-animation-fidelity]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                easySetupState.animationFidelity = normalizeAnimationFidelity(
                    btn.getAttribute('data-animation-fidelity'),
                    recommendedAnimationFidelity(),
                );
                syncEasySetupAnimationCards();
                syncEasySetupPhysicsControls();
                updateEasySetupNavigation();
                await persistOnboardingPrefs({
                    current_step: easySetupStepName(easySetupState.step),
                    answers: {
                        animation_fidelity: easySetupState.animationFidelity,
                        advanced_chat_physics: easySetupState.chatPhysicsEnabled,
                    },
                });
            });
        });
    }
    ensureEasySetupPhysicsControls();

    if (easySetupCloseBtn) easySetupCloseBtn.addEventListener('click', () => requestEasySetupClose('close_button'));
    if (easySetupBackdrop) easySetupBackdrop.addEventListener('click', () => requestEasySetupClose('backdrop'));
    if (easySetupDismissBtn) easySetupDismissBtn.addEventListener('click', () => requestEasySetupClose('footer_skip'));
    if (easySetupBackBtn) {
        easySetupBackBtn.addEventListener('click', () => {
            handleEasySetupBack();
        });
    }
    if (easySetupNextBtn) {
        easySetupNextBtn.addEventListener('click', () => {
            handleEasySetupNext();
        });
    }
    if (easySetupTestConnectionBtn) {
        easySetupTestConnectionBtn.addEventListener('click', () => {
            handleEasySetupConnectionTest();
        });
    }
    if (easySetupAutoRepairBtn) {
        easySetupAutoRepairBtn.addEventListener('click', async () => {
            const ok = await runEasySetupRepair('connect_step');
            if (ok) {
                try {
                    await loadEasySetupBootstrap();
                } catch {
                    // Best effort only.
                }
                easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
                renderEasySetupDependencies();
                updateEasySetupNavigation();
            }
        });
    }
    if (easySetupApproveAllBtn) {
        easySetupApproveAllBtn.addEventListener('click', () => {
            handleEasySetupApproveAll();
        });
    }
    if (easySetupManualProfile) {
        // Re-render the connection copy + dependency plan so the guidance always
        // matches the picked provider (Anthropic/OpenAI/Google/...), never a
        // hardcoded ChatGPT/Codex blurb.
        easySetupManualProfile.addEventListener('change', () => {
            if (easySetupState.selectedPath === 'manual') {
                easySetupState.dependencyPlan = buildEasySetupDependencyPlan(easySetupState.bootstrap, easySetupState.selectedPath);
                syncEasySetupConnectionBlocks();
                renderEasySetupDependencies();
            }
        });
    }
    if (easySetupReviewDownloadsBtn) easySetupReviewDownloadsBtn.addEventListener('click', handleEasySetupReviewDownloads);
    if (rerunEasySetupBtn) {
        rerunEasySetupBtn.addEventListener('click', async () => {
            if (isSettingsScreenOpen()) closeSettingsModal({ restoreNav: false });
            await openEasySetup({ source: 'settings', force: true, restart: true });
        });
    }

    syncEasySetupConnectionBlocks();
    setEasySetupStatus(easySetupConnectionStatus, 'Choose a path and run connection test.');
    setEasySetupDependencyDefaultStatus();
    setEasySetupStep(1);
}

function renderOnboardingChoiceBubble(prompt, options, onChoose) {
    if (safeString(prompt)) {
        renderMessage({ role: 'assistant', content: prompt });
    }
    setAssistantSuggestions({
        title: 'Onboarding choices',
        context: 'onboarding',
        dismissible: false,
        options: (options || []).map((option) => ({
            ...option,
            keep_after_choose: false,
            onChoose: async () => {
                if (typeof onChoose === 'function') {
                    await onChoose(option);
                }
            },
        })),
    });
}

function deriveOnboardingDefaults(answers) {
    const experience = safeString(answers?.experience) || 'builder';
    const autonomyPref = safeString(answers?.autonomy) || 'balanced';
    const costPref = safeString(answers?.cost_quality) || 'balanced';
    const memoryPref = safeString(answers?.memory) || 'remember';
    const personalityPref = safeString(answers?.personality) || 'balanced';
    const workflowPref = safeString(answers?.workflow) || 'build_features';
    const togglesPref = safeString(answers?.default_toggles) || 'safe_defaults';
    const animationFidelity = normalizeAnimationFidelity(
        answers?.animation_fidelity,
        recommendedAnimationFidelity(),
    );
    const chatPhysicsEnabled = Boolean(answers?.advanced_chat_physics) && animationFidelity !== ANIMATION_FIDELITY_MINIMAL;

    let autonomyLevel = 2;
    if (experience === 'new') autonomyLevel = 1;
    if (experience === 'expert') autonomyLevel = 4;
    if (autonomyPref === 'guided') autonomyLevel -= 1;
    if (autonomyPref === 'aggressive') autonomyLevel += 1;
    autonomyLevel = Math.max(1, Math.min(4, autonomyLevel));

    let tokenEconomy = 'optimal';
    if (costPref === 'low_cost') tokenEconomy = 'cheap';
    if (costPref === 'max_quality') tokenEconomy = 'max';

    const memoryEnabled = memoryPref === 'remember';
    const sessionOnlyMemory = memoryPref === 'session_only';
    const requireCommandApproval = togglesPref === 'safe_defaults' || workflowPref === 'ops_reliability';
    const allowNetwork = togglesPref !== 'safe_defaults';
    const showTokenMeter = togglesPref === 'power_mode';
    const debugPanelEnabled = togglesPref === 'power_mode';
    const desktopNotifications = togglesPref !== 'quiet_mode';
    const showTimestamps = personalityPref === 'direct_technical' || workflowPref === 'ops_reliability';
    const uiDensity = togglesPref === 'power_mode' ? 'compact' : 'comfortable';
    const defaultMode = workflowPref === 'research' ? 'thinking' : 'auto';
    let profileType = 'adaptive';
    if (experience === 'new' || personalityPref === 'calm_guide') profileType = 'non_coder';
    if (experience === 'expert' || personalityPref === 'direct_technical') profileType = 'coder';

    return {
        autonomyLevel,
        tokenEconomy,
        memoryEnabled,
        sessionOnlyMemory,
        requireCommandApproval,
        allowNetwork,
        showTokenMeter,
        debugPanelEnabled,
        desktopNotifications,
        showTimestamps,
        uiDensity,
        defaultMode,
        profileType,
        animationFidelity,
        chatPhysicsEnabled,
    };
}

