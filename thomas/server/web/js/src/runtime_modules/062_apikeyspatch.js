// Extracted from part-032.js
// From apikeyspatch

                    auto_tool_threshold: toFloat(settingAdvAutoToolThreshold?.value, 0.45, 0, 1),
                    require_command_approval: Boolean(settingAdvRequireCommandApproval?.checked),
                    allow_shell: Boolean(settingAdvAllowShell?.checked),
                    allow_file_write: Boolean(settingAdvAllowFileWrite?.checked),
                    allow_network: Boolean(settingAdvAllowNetwork?.checked),
                    allow_browser: Boolean(settingAdvAllowBrowser?.checked),
                    allow_channels: Boolean(settingAdvAllowChannels?.checked),
                    allow_git: Boolean(settingAdvAllowGit?.checked),
                    tool_timeout_s: toInt(settingAdvToolTimeoutS?.value, 120, 5, 1800),
                    max_parallel_tools: toInt(settingAdvMaxParallelTools?.value, 6, 1, 32),
                    allowed_paths: safeString(settingAdvAllowedPaths?.value),
                    blocked_commands: safeString(settingAdvBlockedCommands?.value),
                },
                memory: {
                    include_global_memory: Boolean(settingAdvIncludeGlobalMemory?.checked),
                    include_profile_memory: Boolean(settingAdvIncludeProfileMemory?.checked),
                    include_thread_memory: Boolean(settingAdvIncludeThreadMemory?.checked),
                    pins_only: Boolean(settingAdvPinsOnly?.checked),
                    max_pack_tokens: toInt(settingAdvMaxPackTokens?.value, 1200, 200, 64000),
                    decay_half_life_hours: toFloat(settingAdvDecayHalfLifeHours?.value, 240, 1, 87600),
                    retrieval_top_k: toInt(settingAdvRetrievalTopK?.value, 8, 1, 64),
                    auto_summarize_threshold: toInt(settingAdvAutoSummarizeThreshold?.value, 80, 10, 2000),
                    memory_decay_days: toInt(settingAdvMemoryDecayDays?.value, 90, 1, 3650),
                    auto_compact_enabled: Boolean(settingAdvAutoCompactEnabled?.checked),
                    auto_compact_episode_threshold: toInt(settingAdvAutoCompactEpisodeThreshold?.value, 2000, 10, 1000000),
                    auto_compact_min_interval_hours: toFloat(settingAdvAutoCompactMinIntervalHours?.value, 24, 0.1, 8760),
                    auto_optimize_enabled: Boolean(settingAdvAutoOptimizeEnabled?.checked),
                    auto_optimize_waste_threshold: toFloat(settingAdvAutoOptimizeWasteThreshold?.value, 0.22, 0, 1),
                    auto_optimize_min_interval_hours: toFloat(settingAdvAutoOptimizeMinIntervalHours?.value, 12, 0.1, 8760),
                    contradiction_policy: safeString(settingAdvContradictionPolicy?.value) || 'ask',
                    context_prune_strategy: safeString(settingAdvContextPruneStrategy?.value) || 'balanced',
                    pinned_context: safeString(settingAdvPinnedContext?.value),
                },
                cost: {
                    session_token_budget: toInt(settingAdvSessionTokenBudget?.value, 200000, 1000, 5000000),
                    daily_token_budget: toInt(settingAdvDailyTokenBudget?.value, 2000000, 10000, 50000000),
                    throttle_on_budget: Boolean(settingAdvThrottleOnBudget?.checked),
                    low_cost_mode: Boolean(settingAdvLowCostMode?.checked),
                    max_retries: toInt(settingAdvMaxRetries?.value, 2, 0, 20),
                    retry_backoff_ms: toInt(settingAdvRetryBackoffMs?.value, 800, 0, 120000),
                    provider_failover_chain: safeString(settingAdvProviderFailoverChain?.value),
                    model_failover_chain: safeString(settingAdvModelFailoverChain?.value),
                },
                failover: {
                    enabled: Boolean(settingAdvFailoverEnabled?.checked),
                    chat_auto_failover: Boolean(settingAdvChatAutoFailover?.checked),
                    fallback_on_auth_error: Boolean(settingAdvFallbackOnAuthError?.checked),
                    cooldown_seconds: toInt(settingAdvFailoverCooldownSeconds?.value, 300, 0, 86400),
                },
                privacy: {
                    telemetry_enabled: Boolean(settingAdvTelemetryEnabled?.checked),
                    redact_secrets_in_logs: Boolean(settingAdvRedactSecretsInLogs?.checked),
                    pii_guard_strict: Boolean(settingAdvPiiGuardStrict?.checked),
                    local_only_mode: Boolean(settingAdvLocalOnlyMode?.checked),
                    audit_log_enabled: Boolean(settingAdvAuditLogEnabled?.checked),
                    retention_days: toInt(settingAdvRetentionDays?.value, 90, 1, 3650),
                    export_on_exit: Boolean(settingAdvExportOnExit?.checked),
                },
                interface: {
                    ui_density: safeString(settingAdvUiDensity?.value) || 'comfortable',
                    show_timestamps: Boolean(settingAdvShowTimestamps?.checked),
                    show_token_meter: Boolean(settingAdvShowTokenMeter?.checked),
                    animations_enabled: Boolean(settingAdvAnimationsEnabled?.checked),
                    code_theme: safeString(settingAdvCodeTheme?.value) || 'atom-one-dark',
                    debug_panel_enabled: Boolean(settingAdvDebugPanelEnabled?.checked),
                    event_log_verbosity: safeString(settingAdvEventLogVerbosity?.value) || 'standard',
                    labs_flags: safeString(settingAdvLabsFlags?.value),
                },
            },
        };

        const apiKeysPatch = collectApiKeysPatch();
        if (apiKeysPatch) {
            patch.api_keys = apiKeysPatch;
        }

        const thomadsPatch = collectThomadsPatch();
        if (thomadsPatch !== null) {
            patch.thomads = thomadsPatch;
        }

        const res = await fetch('/api/preferences', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patch)
        });
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }

        currentPreferences = await res.json();
        applyInterfaceMotionPreference();
        updateSidebarIdentity();
        applyApiKeyPlaceholders(currentPreferences.api_keys || {});
        if (setupMemoryToggle) {
            setupMemoryToggle.checked = Boolean(currentPreferences?.memory?.enabled_global);
        }
        setDebugDockOpen(Boolean(currentPreferences?.advanced?.interface?.debug_panel_enabled), { recordEvent: false });
        updateDebugDockSnapshot();
        if (typeof updateWelcomeSupportRail === 'function') {
            updateWelcomeSupportRail(loadStoredBuilderMode());
        }

        saveSettingsBtn.textContent = 'Saved!';
        notifyUser('Settings saved.', {
            tone: 'success',
            durationMs: 1700,
            dedupeMs: 1000,
            debugKind: 'settings',
        });
        setTimeout(() => {
            saveSettingsBtn.textContent = 'Save Settings';
        }, 1000);
    } catch (e) {
        console.error("Failed to save settings", e);
        notifyUser('Could not save settings. Check connection and try again.', {
            tone: 'error',
            debugKind: 'error',
            durationMs: 3200,
        });
        saveSettingsBtn.textContent = 'Error';
        setTimeout(() => {
            saveSettingsBtn.textContent = 'Save Settings';
        }, 1200);
    }
}

// Boot
let __thomasHasBootstrapped = false;
function __thomasBootstrapApp() {
    if (__thomasHasBootstrapped) return;
    __thomasHasBootstrapped = true;
    try {
        init();
    } catch (error) {
        console.error('Failed to bootstrap app', error);
        if (typeof notifyUser === 'function') {
            notifyUser('Thomas did not start correctly. Some features may be limited.', {
                tone: 'error',
                debugKind: 'error',
                durationMs: 4200,
            });
        }
    }
}
if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', __thomasBootstrapApp, { once: true });
} else {
    queueMicrotask(() => __thomasBootstrapApp());
}
