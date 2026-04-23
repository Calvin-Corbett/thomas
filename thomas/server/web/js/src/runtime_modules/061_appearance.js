// Extracted from part-031b.js
// From appearance

        currentPreferences = prefsRes.data || {};
        currentCodexStatus = codexRes.ok ? (codexRes.data || null) : null;
        applyInterfaceMotionPreference();

        const appearance = currentPreferences.appearance || {};
        const profile = currentPreferences.profile || {};
        const memory = currentPreferences.memory || {};
        const notifications = currentPreferences.notifications || {};
        const autonomy = currentPreferences.autonomy || {};
        const voice = currentPreferences.voice || {};
        const advanced = currentPreferences.advanced || {};
        const advModel = advanced.model || {};
        const advTools = advanced.tools || {};
        const advMemory = advanced.memory || {};
        const advCost = advanced.cost || {};
        const advRuntime = advanced.runtime || {};
        const advFailover = advanced.failover || {};
        const advPrivacy = advanced.privacy || {};
        const advInterface = advanced.interface || {};
        const thomads = currentPreferences.thomads || {};

        const builderModeEnabled = typeof loadStoredBuilderMode === 'function' && loadStoredBuilderMode();
        if (settingsAdvancedToggle && settingsSuite) {
            settingsAdvancedToggle.checked = builderModeEnabled;
            settingsSuite.classList.toggle('advanced-mode', builderModeEnabled);
        }
        ensureThomadsSettingsSection();
        refreshThomadsSettingsSectionNav();
        if (settingsSectionSearch) settingsSectionSearch.value = '';
        if (settingsSections) settingsSections.scrollTop = 0;
        updateSettingsSectionNavVisibility();

        if (settingTheme) settingTheme.value = safeString(appearance.theme) || 'auto';
        const autonomyDefaultLevel = safeString(autonomy.default_level) || 'L2';
        if (settingAutonomy) settingAutonomy.value = autonomyDefaultLevel;
        const autonomyNumeric = Number.parseInt(autonomyDefaultLevel.replace(/^l/i, ''), 10);
        if (Number.isFinite(autonomyNumeric)) {
            activeAutonomyLevel = Math.max(1, Math.min(4, autonomyNumeric));
            setSegmentedControlSelection('setupAutonomyGroup', String(activeAutonomyLevel));
        }

        if (settingFontSize) {
            const fontSize = toInt(appearance.font_size, 16, 12, 28);
            settingFontSize.value = String(fontSize);
            if (settingFontSizeValue) settingFontSizeValue.textContent = `${fontSize}px`;
        }

        if (settingBubbleStyle) settingBubbleStyle.value = safeString(appearance.bubble_style) || 'rounded';
        if (settingMemoryEnabled) settingMemoryEnabled.checked = Boolean(memory.enabled_global);
        if (setupMemoryToggle) setupMemoryToggle.checked = Boolean(memory.enabled_global);
        if (settingDesktopNotifications) settingDesktopNotifications.checked = Boolean(notifications.desktop);

        if (settingVoice) settingVoice.value = safeString(voice.tts_voice) || 'default';
        if (settingMicDeviceId) settingMicDeviceId.value = safeString(voice.mic_device_id);
        if (settingWakeWordEnabled) settingWakeWordEnabled.checked = Boolean(voice.wake_word_enabled);

        if (settingVoiceSpeed) {
            const voiceSpeed = toFloat(voice.speed, 1.0, 0.5, 2.0);
            settingVoiceSpeed.value = String(voiceSpeed);
            settingVoiceSpeed.dispatchEvent(new Event('input'));
        }

        if (settingConcurrencyLimit) {
            settingConcurrencyLimit.value = String(toInt(autonomy.concurrency_limit, 2, 1, 64));
        }

        if (settingWebPush) settingWebPush.checked = Boolean(notifications.web_push);
        if (settingTelegram) settingTelegram.checked = Boolean(notifications.telegram);

        if (settingAdvTemperature) {
            settingAdvTemperature.value = String(toFloat(advModel.temperature, 0.7, 0, 2));
            settingAdvTemperature.dispatchEvent(new Event('input'));
        }
        if (settingAdvTopP) {
            settingAdvTopP.value = String(toFloat(advModel.top_p, 1, 0, 1));
            settingAdvTopP.dispatchEvent(new Event('input'));
        }
        if (settingAdvFrequencyPenalty) {
            settingAdvFrequencyPenalty.value = String(toFloat(advModel.frequency_penalty, 0, -2, 2));
            settingAdvFrequencyPenalty.dispatchEvent(new Event('input'));
        }
        if (settingAdvPresencePenalty) {
            settingAdvPresencePenalty.value = String(toFloat(advModel.presence_penalty, 0, -2, 2));
            settingAdvPresencePenalty.dispatchEvent(new Event('input'));
        }
        if (settingAdvMaxOutputTokens) settingAdvMaxOutputTokens.value = String(toInt(advModel.max_output_tokens, 4096, 128, 32768));
        if (settingAdvReasoningEffort) settingAdvReasoningEffort.value = safeString(advModel.reasoning_effort) || 'medium';
        if (settingAdvReasoningBudget) settingAdvReasoningBudget.value = String(toInt(advModel.reasoning_token_budget, 4096, 128, 65536));
        if (settingAdvDeterministicSeed) settingAdvDeterministicSeed.value = advModel.deterministic_seed === null || advModel.deterministic_seed === undefined ? '' : String(advModel.deterministic_seed);
        if (settingAdvJsonMode) settingAdvJsonMode.checked = Boolean(advModel.json_mode);
        if (settingAdvStopSequences) settingAdvStopSequences.value = safeString(advModel.stop_sequences);
        const runtimeDefaultMode = normalizeChatMode(safeString(advRuntime.default_mode) || 'auto') || 'auto';
        if (settingAdvDefaultMode) settingAdvDefaultMode.value = runtimeDefaultMode;
        activeChatMode = runtimeDefaultMode;

        const runtimeDefaultEconomy = safeString(advRuntime.default_token_economy) || 'optimal';
        if (settingAdvDefaultTokenEconomy) settingAdvDefaultTokenEconomy.value = runtimeDefaultEconomy;
        const economyForComposer = runtimeDefaultEconomy === 'optimal' ? 'balanced' : runtimeDefaultEconomy;
        if (new Set(['cheap', 'balanced', 'max']).has(economyForComposer)) {
            activeTokenEconomy = economyForComposer;
            setSegmentedControlSelection('setupEconomyGroup', economyForComposer);
        }
        if (settingAdvMaxAgentIterations) settingAdvMaxAgentIterations.value = String(toInt(advRuntime.max_agent_iterations, 0, 0, 200));
        if (settingAdvLocalBackgroundAgents) settingAdvLocalBackgroundAgents.checked = Boolean(advRuntime.local_background_agents_enabled);
        if (settingAdvLocalGpuHeadroom) settingAdvLocalGpuHeadroom.value = String(toInt(advRuntime.local_background_min_gpu_headroom_pct, 35, 5, 95));
        void refreshPowerPcRecommendationBadge();
        if (settingAdvQualityEnforce) settingAdvQualityEnforce.checked = Boolean(advRuntime.quality_enforce);
        if (settingAdvQualityRequireVerification) settingAdvQualityRequireVerification.checked = Boolean(advRuntime.quality_require_verification_for_coding);
        if (settingAdvQualityRequireTests) settingAdvQualityRequireTests.checked = Boolean(advRuntime.quality_require_tests_for_code_edits);
        if (settingAdvQualityRequireMonolithGuard) settingAdvQualityRequireMonolithGuard.checked = Boolean(advRuntime.quality_require_monolith_guard_for_coding);

        if (settingAdvAutoToolThreshold) {
            settingAdvAutoToolThreshold.value = String(toFloat(advTools.auto_tool_threshold, 0.45, 0, 1));
            settingAdvAutoToolThreshold.dispatchEvent(new Event('input'));
        }
        if (settingAdvToolTimeoutS) settingAdvToolTimeoutS.value = String(toInt(advTools.tool_timeout_s, 120, 5, 1800));
        if (settingAdvMaxParallelTools) settingAdvMaxParallelTools.value = String(toInt(advTools.max_parallel_tools, 6, 1, 32));
        if (settingAdvRequireCommandApproval) settingAdvRequireCommandApproval.checked = Boolean(advTools.require_command_approval);
        if (settingAdvAllowShell) settingAdvAllowShell.checked = Boolean(advTools.allow_shell);
        if (settingAdvAllowFileWrite) settingAdvAllowFileWrite.checked = Boolean(advTools.allow_file_write);
        if (settingAdvAllowNetwork) settingAdvAllowNetwork.checked = Boolean(advTools.allow_network);
        if (settingAdvAllowBrowser) settingAdvAllowBrowser.checked = Boolean(advTools.allow_browser);
        if (settingAdvAllowChannels) settingAdvAllowChannels.checked = Boolean(advTools.allow_channels);
        if (settingAdvAllowGit) settingAdvAllowGit.checked = Boolean(advTools.allow_git);
        if (settingAdvAllowedPaths) settingAdvAllowedPaths.value = safeString(advTools.allowed_paths);
        if (settingAdvBlockedCommands) settingAdvBlockedCommands.value = safeString(advTools.blocked_commands);

        if (settingAdvIncludeGlobalMemory) settingAdvIncludeGlobalMemory.checked = Boolean(advMemory.include_global_memory);
        if (settingAdvRetrievalTopK) settingAdvRetrievalTopK.value = String(toInt(advMemory.retrieval_top_k, 8, 1, 64));
        if (settingAdvMaxPackTokens) settingAdvMaxPackTokens.value = String(toInt(advMemory.max_pack_tokens, 1200, 200, 64000));
        if (settingAdvDecayHalfLifeHours) settingAdvDecayHalfLifeHours.value = String(toFloat(advMemory.decay_half_life_hours, 240, 1, 87600));
        if (settingAdvAutoSummarizeThreshold) settingAdvAutoSummarizeThreshold.value = String(toInt(advMemory.auto_summarize_threshold, 80, 10, 2000));
        if (settingAdvMemoryDecayDays) settingAdvMemoryDecayDays.value = String(toInt(advMemory.memory_decay_days, 90, 1, 3650));
        if (settingAdvAutoCompactEnabled) settingAdvAutoCompactEnabled.checked = Boolean(advMemory.auto_compact_enabled);
        if (settingAdvAutoCompactEpisodeThreshold) settingAdvAutoCompactEpisodeThreshold.value = String(toInt(advMemory.auto_compact_episode_threshold, 2000, 10, 1000000));
        if (settingAdvAutoCompactMinIntervalHours) settingAdvAutoCompactMinIntervalHours.value = String(toFloat(advMemory.auto_compact_min_interval_hours, 24, 0.1, 8760));
        if (settingAdvAutoOptimizeEnabled) settingAdvAutoOptimizeEnabled.checked = Boolean(advMemory.auto_optimize_enabled);
        if (settingAdvAutoOptimizeWasteThreshold) settingAdvAutoOptimizeWasteThreshold.value = String(toFloat(advMemory.auto_optimize_waste_threshold, 0.22, 0, 1));
        if (settingAdvAutoOptimizeMinIntervalHours) settingAdvAutoOptimizeMinIntervalHours.value = String(toFloat(advMemory.auto_optimize_min_interval_hours, 12, 0.1, 8760));
        if (settingAdvContradictionPolicy) settingAdvContradictionPolicy.value = safeString(advMemory.contradiction_policy) || 'ask';
        if (settingAdvContextPruneStrategy) settingAdvContextPruneStrategy.value = safeString(advMemory.context_prune_strategy) || 'balanced';
        if (settingAdvIncludeProfileMemory) settingAdvIncludeProfileMemory.checked = Boolean(advMemory.include_profile_memory);
        if (settingAdvIncludeThreadMemory) settingAdvIncludeThreadMemory.checked = Boolean(advMemory.include_thread_memory);
        if (settingAdvPinsOnly) settingAdvPinsOnly.checked = Boolean(advMemory.pins_only);
        if (settingAdvPinnedContext) settingAdvPinnedContext.value = safeString(advMemory.pinned_context);

        if (settingAdvSessionTokenBudget) settingAdvSessionTokenBudget.value = String(toInt(advCost.session_token_budget, 200000, 1000, 5000000));
        if (settingAdvDailyTokenBudget) settingAdvDailyTokenBudget.value = String(toInt(advCost.daily_token_budget, 2000000, 10000, 50000000));
        if (settingAdvMaxRetries) settingAdvMaxRetries.value = String(toInt(advCost.max_retries, 2, 0, 20));
        if (settingAdvRetryBackoffMs) settingAdvRetryBackoffMs.value = String(toInt(advCost.retry_backoff_ms, 800, 0, 120000));
        if (settingAdvThrottleOnBudget) settingAdvThrottleOnBudget.checked = Boolean(advCost.throttle_on_budget);
        if (settingAdvLowCostMode) settingAdvLowCostMode.checked = Boolean(advCost.low_cost_mode);
        if (settingAdvProviderFailoverChain) settingAdvProviderFailoverChain.value = safeString(advCost.provider_failover_chain);
        if (settingAdvModelFailoverChain) settingAdvModelFailoverChain.value = safeString(advCost.model_failover_chain);
        if (settingAdvFailoverEnabled) settingAdvFailoverEnabled.checked = Boolean(advFailover.enabled);
        if (settingAdvChatAutoFailover) settingAdvChatAutoFailover.checked = Boolean(advFailover.chat_auto_failover);
        if (settingAdvFallbackOnAuthError) settingAdvFallbackOnAuthError.checked = Boolean(advFailover.fallback_on_auth_error);
        if (settingAdvFailoverCooldownSeconds) settingAdvFailoverCooldownSeconds.value = String(toInt(advFailover.cooldown_seconds, 300, 0, 86400));

        if (settingAdvRetentionDays) settingAdvRetentionDays.value = String(toInt(advPrivacy.retention_days, 90, 1, 3650));
        if (settingAdvTelemetryEnabled) settingAdvTelemetryEnabled.checked = Boolean(advPrivacy.telemetry_enabled);
        if (settingAdvRedactSecretsInLogs) settingAdvRedactSecretsInLogs.checked = Boolean(advPrivacy.redact_secrets_in_logs);
        if (settingAdvPiiGuardStrict) settingAdvPiiGuardStrict.checked = Boolean(advPrivacy.pii_guard_strict);
        if (settingAdvLocalOnlyMode) settingAdvLocalOnlyMode.checked = Boolean(advPrivacy.local_only_mode);
        if (settingAdvAuditLogEnabled) settingAdvAuditLogEnabled.checked = Boolean(advPrivacy.audit_log_enabled);
        if (settingAdvExportOnExit) settingAdvExportOnExit.checked = Boolean(advPrivacy.export_on_exit);

        if (settingAdvUiDensity) settingAdvUiDensity.value = safeString(advInterface.ui_density) || 'comfortable';
        if (settingAdvCodeTheme) settingAdvCodeTheme.value = safeString(advInterface.code_theme) || 'atom-one-dark';
        if (settingAdvEventLogVerbosity) settingAdvEventLogVerbosity.value = safeString(advInterface.event_log_verbosity) || 'standard';
        if (settingAdvShowTimestamps) settingAdvShowTimestamps.checked = Boolean(advInterface.show_timestamps);
        if (settingAdvShowTokenMeter) settingAdvShowTokenMeter.checked = Boolean(advInterface.show_token_meter);
        if (settingAdvAnimationsEnabled) settingAdvAnimationsEnabled.checked = Boolean(advInterface.animations_enabled);
        if (settingAdvDebugPanelEnabled) settingAdvDebugPanelEnabled.checked = Boolean(advInterface.debug_panel_enabled);
        if (settingAdvLabsFlags) settingAdvLabsFlags.value = safeString(advInterface.labs_flags);

        applyApiKeyPlaceholders(currentPreferences.api_keys || {});

        const displayName = resolveAgentName(currentPreferences);
        if (settingsDisplayName) settingsDisplayName.value = displayName;
        if (settingProfileType) {
            const profileType = safeString(profile.profile_type).toLowerCase();
            settingProfileType.value = new Set(['adaptive', 'coder', 'non_coder']).has(profileType) ? profileType : 'adaptive';
        }
        pendingAvatarOverride = null;
        refreshSettingsAvatarPreview();

        if (settingsAccountMeta) {
            if (currentCodexStatus?.logged_in) {
                const plan = safeString(currentCodexStatus.plan_type) || 'plan';
                const email = safeString(currentCodexStatus.email) || 'account';
                settingsAccountMeta.textContent = `Connected as ${email} (${plan})`;
            } else {
                settingsAccountMeta.textContent = 'Not connected. Profile will use local settings only.';
            }
        }
        const settingThomadsConfig = getSettingThomadsConfigInput();
        if (settingThomadsConfig) {
            if (typeof thomads === 'object' && thomads !== null && !Array.isArray(thomads)) {
                settingThomadsConfig.value = JSON.stringify(thomads, null, 2);
            } else {
                settingThomadsConfig.value = '{}';
            }
        }
        if (typeof updateWelcomeSupportRail === 'function') {
            updateWelcomeSupportRail(loadStoredBuilderMode());
        }
    } catch (e) {
        console.error("Failed to load settings", e);
        notifyUser('Could not load settings right now. Check backend and retry.', {
            tone: 'error',
            debugKind: 'error',
            durationMs: 3200,
        });
    }
}

function ensureThomadsSettingsSection() {
    if (!settingsSections) return false;
    if (document.getElementById('settingThomadsConfig')) return false;

    const sections = Array.from(settingsSections.querySelectorAll('.settings-section'));
    const headingText = (section) => safeString(section?.querySelector('.settings-section-head h3')?.textContent).trim().toLowerCase();
    const modelBehaviorSection = sections.find((row) => headingText(row) === 'advanced model behavior');
    const apiIntegrationsSection = sections.find((row) => headingText(row) === 'advanced api integrations');
    if (!modelBehaviorSection && !apiIntegrationsSection) return false;

    const thomadsSection = document.createElement('section');
    thomadsSection.className = 'settings-section settings-advanced-only';
    thomadsSection.innerHTML = "<div class='settings-section-head'><h3>Thomads</h3><p>Custom Thomas settings stored as JSON.</p></div><div class='form-group settings-top-gap'><label for='settingThomadsConfig'>Thomads Settings (JSON)</label><textarea id='settingThomadsConfig' class='form-control settings-textarea' rows='8' placeholder='{\"enable_x\": true}'></textarea></div><p class='settings-inline-note'>Enter valid JSON only. Leave empty to clear all Thomads settings.</p>";
    const insertBefore = modelBehaviorSection ? modelBehaviorSection : (apiIntegrationsSection ? apiIntegrationsSection.nextElementSibling : null);
    if (insertBefore) {
        settingsSections.insertBefore(thomadsSection, insertBefore);
    } else {
        settingsSections.appendChild(thomadsSection);
    }
    return true;
}

function refreshThomadsSettingsSectionNav() {
    if (typeof buildSettingsSectionNav === 'function') {
        buildSettingsSectionNav();
        return;
    }
    if (typeof initSettingsSectionNavigation === 'function' && !settingsNavBound) {
        initSettingsSectionNavigation();
    }
}

function getSettingThomadsConfigInput() {
    return document.getElementById('settingThomadsConfig');
}

function collectApiKeysPatch() {
    const mapping = {
        openai: settingApiKeyOpenai,
        anthropic: settingApiKeyAnthropic,
        google: settingApiKeyGoogle,
        elevenlabs: settingApiKeyElevenlabs,
        azure_openai: settingApiKeyAzureOpenai,
        custom: settingApiKeyCustom,
    };
    const patch = {};
    Object.entries(mapping).forEach(([provider, input]) => {
        if (!input) return;
        const raw = safeString(input.value);
        if (!raw) return;
        patch[provider] = raw.toLowerCase() === 'clear' ? '' : raw;
    });
    return Object.keys(patch).length > 0 ? patch : null;
}

function collectThomadsPatch() {
    const settingThomadsConfig = getSettingThomadsConfigInput();
    if (!settingThomadsConfig) return null;
    const raw = safeString(settingThomadsConfig.value).trim();
    if (!raw) return null;

    let parsed;
    try {
        parsed = JSON.parse(raw);
    } catch (error) {
        throw new Error('Invalid JSON in Thomads settings. Enter valid JSON.');
    }

    if (parsed === null) {
        return null;
    }
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Thomads settings must be a JSON object.');
    }

    return Object.keys(parsed).length > 0 ? parsed : {};
}

async function saveSettings() {
    try {
        saveSettingsBtn.textContent = 'Saving...';
        const profileAvatarValue = pendingAvatarOverride !== null
            ? safeString(pendingAvatarOverride)
            : safeString(currentPreferences?.profile?.avatar_url);
        const deterministicSeedRaw = safeString(settingAdvDeterministicSeed?.value);
        const deterministicSeed = deterministicSeedRaw ? toInt(deterministicSeedRaw, 0, 0, 2147483647) : null;
        const patch = {
            profile: {
                display_name: safeString(settingsDisplayName?.value),
                avatar_url: profileAvatarValue,
                profile_type: safeString(settingProfileType?.value) || 'adaptive',
            },
            appearance: {
                theme: safeString(settingTheme?.value) || 'auto',
                font_size: toInt(settingFontSize?.value, 16, 12, 28),
                bubble_style: safeString(settingBubbleStyle?.value) || 'rounded',
            },
            memory: {
                enabled_global: Boolean(settingMemoryEnabled?.checked),
            },
            notifications: {
                desktop: Boolean(settingDesktopNotifications?.checked),
                web_push: Boolean(settingWebPush?.checked),
                telegram: Boolean(settingTelegram?.checked),
            },
            autonomy: {
                default_level: safeString(settingAutonomy?.value) || 'L2',
                concurrency_limit: toInt(settingConcurrencyLimit?.value, 2, 1, 64),
            },
            voice: {
                tts_voice: safeString(settingVoice?.value) || 'default',
                speed: toFloat(settingVoiceSpeed?.value, 1, 0.5, 2),
                wake_word_enabled: Boolean(settingWakeWordEnabled?.checked),
                mic_device_id: safeString(settingMicDeviceId?.value),
            },
            advanced: {
                model: {
                    active_profile: safeString(setupProviderSelector?.value) || safeString(currentPreferences?.advanced?.model?.active_profile),
                    model_id: safeString(activeModelOverride) || safeString(currentPreferences?.advanced?.model?.model_id),
                    temperature: toFloat(settingAdvTemperature?.value, 0.7, 0, 2),
                    top_p: toFloat(settingAdvTopP?.value, 1, 0, 1),
                    frequency_penalty: toFloat(settingAdvFrequencyPenalty?.value, 0, -2, 2),
                    presence_penalty: toFloat(settingAdvPresencePenalty?.value, 0, -2, 2),
                    max_output_tokens: toInt(settingAdvMaxOutputTokens?.value, 4096, 128, 32768),
                    reasoning_effort: safeString(settingAdvReasoningEffort?.value) || 'medium',
                    reasoning_token_budget: toInt(settingAdvReasoningBudget?.value, 4096, 128, 65536),
                    json_mode: Boolean(settingAdvJsonMode?.checked),
                    deterministic_seed: deterministicSeed,
                    stop_sequences: safeString(settingAdvStopSequences?.value),
                },
                runtime: {
                    default_mode: safeString(settingAdvDefaultMode?.value) || 'auto',
                    default_token_economy: safeString(settingAdvDefaultTokenEconomy?.value) || 'optimal',
                    max_agent_iterations: toInt(settingAdvMaxAgentIterations?.value, 0, 0, 200),
                    local_background_agents_enabled: Boolean(settingAdvLocalBackgroundAgents?.checked),
                    local_background_min_gpu_headroom_pct: toInt(settingAdvLocalGpuHeadroom?.value, 35, 5, 95),
                    quality_enforce: Boolean(settingAdvQualityEnforce?.checked),
                    quality_require_verification_for_coding: Boolean(settingAdvQualityRequireVerification?.checked),
                    quality_require_tests_for_code_edits: Boolean(settingAdvQualityRequireTests?.checked),
                    quality_require_monolith_guard_for_coding: Boolean(settingAdvQualityRequireMonolithGuard?.checked),
                },
                tools: {
