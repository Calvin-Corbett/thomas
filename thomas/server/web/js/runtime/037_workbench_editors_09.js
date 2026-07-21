function moduleChannelsProbeResultMarkup(state) {
    const result = state?.voiceProbeResult && typeof state.voiceProbeResult === 'object' ? state.voiceProbeResult : null;
    if (!result) {
        return `
            <article class="module-channels-section-card" data-ui-id="channels.discord.voice-probe-result" data-ui-label="Discord voice probe result" data-ui-component="status-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=140,maxHeight=720,collision=avoid">
                <div class="module-channels-section-header">
                    <div>
                        <span class="module-channels-section-kicker">Voice self-test</span>
                        <h4>Last probe</h4>
                    </div>
                    <span>not run yet</span>
                </div>
                <p class="module-channels-section-copy">Run a Thomas-managed wake-word probe to join Discord voice, simulate a real "Hey Thomas" request, and verify the spoken reply with local transcription.</p>
            </article>
        `;
    }
    const matched = Boolean(result.reply_matches_transcript);
    const wakeMode = safeString(result.mode) === 'wake';
    const requestedText = wakeMode ? safeString(result.raw_transcript) : safeString(result.prompt);
    const requestedLabel = wakeMode ? 'Wake phrase' : 'Requested line';
    const replyLabel = wakeMode ? 'Thomas replied' : 'Spoken reply';
    const durationMs = Number(result.duration_ms || 0);
    return `
        <article class="module-channels-section-card" data-ui-id="channels.discord.voice-probe-result" data-ui-label="Discord voice probe result" data-ui-component="status-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=220,maxHeight=900,collision=avoid">
            <div class="module-channels-section-header">
                <div>
                    <span class="module-channels-section-kicker">Voice self-test</span>
                    <h4>Last probe</h4>
                </div>
                <span>${matched ? 'match confirmed' : 'review needed'}</span>
            </div>
            <div class="module-channels-meta-grid">
                <div><span>Backend</span><strong>${escapeHtml(safeString(result.probe_backend) || 'unknown')}</strong></div>
                <div><span>Synth</span><strong>${escapeHtml(safeString(result.synth_backend) || 'unknown')}</strong></div>
                <div><span>STT</span><strong>${escapeHtml(safeString(result.stt_backend) || 'unknown')}</strong></div>
                <div><span>Channel</span><strong>${escapeHtml(safeString(result.voice_channel_name) || 'unknown')}</strong></div>
                <div><span>Probe time</span><strong>${escapeHtml(durationMs > 0 ? `${(durationMs / 1000).toFixed(1)}s` : 'n/a')}</strong></div>
            </div>
            <div class="module-channels-turn-list">
                <article class="module-channels-turn-card">
                    <div class="module-channels-turn-head"><strong>${escapeHtml(requestedLabel)}</strong><span>${escapeHtml(safeString(result.mode) || 'probe')}</span></div>
                    <p>${escapeHtml(requestedText || '(no prompt recorded)')}</p>
                </article>
                <article class="module-channels-turn-card">
                    <div class="module-channels-turn-head"><strong>${escapeHtml(replyLabel)}</strong><span>${matched ? 'matches' : 'differs'}</span></div>
                    <p>${escapeHtml(safeString(result.reply_text) || '(no reply text)')}</p>
                </article>
                <article class="module-channels-turn-card">
                    <div class="module-channels-turn-head"><strong>Heard back</strong><span>${matched ? 'matches' : 'differs'}</span></div>
                    <p>${escapeHtml(safeString(result.transcribed_reply) || '(no transcription)')}</p>
                </article>
            </div>
        </article>
    `;
}

function moduleChannelsCatalogMarkup(model) {
    return model.catalog.map((entry) => {
        const isDiscord = entry.id === 'discord';
        const isSelected = entry.id === model.selectedChannelId;
        const tileStatus = isDiscord ? model.statusLabel : 'Coming soon';
        const tileTone = isDiscord ? model.statusTone : 'catalog';
        const tileMeta = isDiscord
            ? `${model.enabled ? 'Channel on' : 'Channel off'} | ${model.configured ? 'Securely configured' : 'Setup required'}`
            : 'Reorder this slot now. Bridge lifecycle lands here later.';
        const instanceKey = moduleChannelsUiInstanceKey(entry.id);
        return `
            <button
                type="button"
                class="module-channel-card${isSelected ? ' is-selected' : ''}"
                data-channel-card-select="${escapeHtml(entry.id)}"
                data-channel-card-id="${escapeHtml(entry.id)}"
                data-ui-id="channels.catalog-card.${escapeHtml(instanceKey)}"
                data-ui-instance-key="${escapeHtml(instanceKey)}"
                data-ui-label="${escapeHtml(`${entry.title} channel card`)}"
                data-ui-component="repeating-card"
                data-ui-policy="move resize-deny contain=parent collision=avoid"
                data-ui-constraints="items-runtime-owned,preserve-runtime-ids,preserve-handlers,minWidth=180,minHeight=150"
                draggable="true">
                <div class="module-channel-card-head">
                    <div class="module-channel-card-brand">
                        <i class="ph ${escapeHtml(entry.icon)}"></i>
                        <div>
                            <span>${escapeHtml(entry.eyebrow || 'Channel')}</span>
                            <strong>${escapeHtml(entry.title)}</strong>
                        </div>
                    </div>
                    <span class="module-channel-card-status" data-channel-status="${escapeHtml(tileTone)}">${escapeHtml(tileStatus)}</span>
                </div>
                <p class="module-channel-card-summary">${escapeHtml(entry.summary)}</p>
                <div class="module-channel-card-foot">
                    <span>${escapeHtml(entry.capabilityLabel || '')}</span>
                    <span>${escapeHtml(tileMeta)}</span>
                </div>
            </button>
        `;
    }).join('');
}

function moduleRenderPlaceholderChannelDetail(model) {
    const instanceKey = moduleChannelsUiInstanceKey(model.selectedChannel.id);
    return `
        <section class="module-channels-detail-shell" data-ui-id="channels.detail.${escapeHtml(instanceKey)}" data-ui-instance-key="${escapeHtml(instanceKey)}" data-ui-label="${escapeHtml(`${model.selectedChannel.title} channel detail`)}" data-ui-component="workspace-detail" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=360,maxHeight=1400,preserve-runtime-ids,preserve-handlers">
            <div class="module-channels-detail-toolbar">
                <button type="button" class="module-channels-btn" data-channels-action="back_to_catalog" ${moduleChannelsProtectedAttrs('action', 'back-to-catalog', 'Back to all channels', 'controls required-navigation')}>Back To All Channels</button>
                <span class="module-channel-card-status" data-channel-status="catalog">Coming soon</span>
            </div>
            <div class="module-channels-detail-head">
                <div>
                    <span class="module-channels-section-kicker">Channel detail</span>
                    <h3>${escapeHtml(model.selectedChannel.title)}</h3>
                    <p>${escapeHtml(model.selectedChannel.summary)}</p>
                </div>
            </div>
            <div class="module-channels-detail-grid">
                <article class="module-channels-section-card" data-ui-id="channels.planned-overview.${escapeHtml(instanceKey)}" data-ui-instance-key="${escapeHtml(instanceKey)}" data-ui-label="${escapeHtml(`${model.selectedChannel.title} planned channel overview`)}" data-ui-component="content-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=240,maxHeight=760,collision=avoid">
                    <div class="module-channels-section-header">
                        <div>
                            <span class="module-channels-section-kicker">Planned surface</span>
                            <h4>Why this slot exists</h4>
                        </div>
                        ${moduleChannelsHelpButton('Planned surface', 'This channel is a placeholder slot. Thomas is not connected here yet, but the UI and ordering are ready so the channel can become first-class without redesigning the workspace.')}
                    </div>
                    <p class="module-channels-section-copy">This tile keeps ${escapeHtml(model.selectedChannel.title)} visible in the catalog now, so the future bridge can inherit the same Thomas-owned lifecycle, history, settings, and safety model as Discord.</p>
                    <div class="module-channels-meta-grid">
                        <div><span>Status</span><strong>Placeholder</strong></div>
                        <div><span>Configure path</span><strong>Guided Thomas prompt</strong></div>
                        <div><span>History model</span><strong>Searchable channel memory</strong></div>
                        <div><span>Permissions</span><strong>Owner scoped by default</strong></div>
                    </div>
                </article>
                <article class="module-channels-section-card" data-ui-id="channels.planned-setup.${escapeHtml(instanceKey)}" data-ui-instance-key="${escapeHtml(instanceKey)}" data-ui-label="${escapeHtml(`${model.selectedChannel.title} guided setup`)}" data-ui-component="action-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=180,maxHeight=620,collision=avoid">
                    <div class="module-channels-section-header">
                        <div>
                            <span class="module-channels-section-kicker">Guided setup</span>
                            <h4>Generate a Thomas setup prompt</h4>
                        </div>
                        ${moduleChannelsHelpButton('Guided setup', 'This sends a structured setup prompt into Thomas chat so Thomas can walk through the API, permissions, and product-side requirements for this channel.')}
                    </div>
                    <p class="module-channels-section-copy">Use the guided configure action to send a prebuilt planning prompt into Thomas chat for ${escapeHtml(model.selectedChannel.title)}.</p>
                    <div class="module-channels-actions">
                        <button type="button" class="module-channels-btn primary" data-channels-action="configure_channel" data-channels-channel-id="${escapeHtml(model.selectedChannel.id)}" ${moduleChannelsProtectedAttrs('planned-action', `configure-${model.selectedChannel.id}`, `Configure ${model.selectedChannel.title}`, 'controls bridge')}>Configure ${escapeHtml(model.selectedChannel.title)}</button>
                    </div>
                </article>
            </div>
        </section>
    `;
}

function moduleRenderDiscordChannelDetail(model, state) {
    const ttsBackend = safeString(model.config?.voice_tts_backend).toLowerCase() || 'piper';
    const sttBackend = safeString(model.config?.voice_stt_backend).toLowerCase() || 'faster-whisper';
    const sttDevice = safeString(model.config?.voice_stt_device).toLowerCase() || 'cpu';
    const sttComputeType = safeString(model.config?.voice_stt_compute_type).toLowerCase() || 'int8';
    const sttVadFilterEnabled = safeString(model.config?.voice_stt_vad_filter ?? true).toLowerCase() !== 'false';
    const primaryControlLabel = model.running ? 'Stop Bridge' : 'Start Bridge';
    const primaryControlAction = model.running ? 'stop' : 'start';
    return `
        <section class="module-channels-detail-shell" data-ui-id="channels.detail.discord" data-ui-instance-key="discord" data-ui-label="Discord channel detail" data-ui-component="workspace-detail" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=520,maxHeight=2400,preserve-runtime-ids,preserve-handlers">
            <div class="module-channels-detail-toolbar">
                <button type="button" class="module-channels-btn" data-channels-action="back_to_catalog" ${moduleChannelsProtectedAttrs('action', 'back-to-catalog', 'Back to all channels', 'controls required-navigation')}>Back To All Channels</button>
                <span class="module-channel-card-status" data-channel-status="${escapeHtml(model.statusTone)}">${escapeHtml(model.statusLabel)}</span>
            </div>
            <div class="module-channels-detail-head">
                <div class="module-channels-title-lockup">
                    <span class="thomas-eyes-mark module-channels-eyes-mark" aria-hidden="true"><i></i><i></i></span>
                    <div>
                        <span class="module-channels-section-kicker">Channel detail</span>
                        <h3>Discord bridge</h3>
                        <p>Lifecycle, voice behavior, secure configuration, owner-scoped access rules, and indexed conversation lookup all live here on the Thomas side.</p>
                    </div>
                </div>
            </div>
            <div class="module-channels-stat-grid" data-ui-id="channels.discord-status-grid" data-ui-label="Discord status summary" data-ui-component="panel-group" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=280,minHeight=120,maxHeight=520,collision=avoid">
                <article class="module-channels-stat-card" data-ui-id="channels.discord-status.bridge" data-ui-label="Bridge state" data-ui-policy="move resize-deny contain=parent"><span>Bridge state</span><strong>${escapeHtml(model.statusLabel)}</strong><em>${escapeHtml(model.bridge?.pid ? `PID ${model.bridge.pid}` : 'not running')}</em></article>
                <article class="module-channels-stat-card" data-ui-id="channels.discord-status.channel" data-ui-label="Channel state" data-ui-policy="move resize-deny contain=parent"><span>Channel</span><strong>${model.enabled ? 'On' : 'Off'}</strong><em>${model.configured ? 'owner-scoped controls active' : 'secure config still required'}</em></article>
                <article class="module-channels-stat-card" data-ui-id="channels.discord-status.conversations" data-ui-label="Conversation index" data-ui-policy="move resize-deny contain=parent"><span>Conversation index</span><strong>${escapeHtml(String(model.indexedTurnCount))}</strong><em>${escapeHtml(String(model.conversations?.indexed_sessions || 0))} indexed sessions</em></article>
                <article class="module-channels-stat-card" data-ui-id="channels.discord-status.access" data-ui-label="Runtime access" data-ui-policy="move resize-deny contain=parent"><span>Runtime access</span><strong>${escapeHtml(String(model.runtime?.access_grants_count || 0))}</strong><em>${model.runtime?.voice_require_wake_word ? 'wake word required' : 'wake word optional'}</em></article>
            </div>
            <div class="module-channels-detail-grid">
                <article class="module-channels-section-card" data-ui-id="channels.discord.lifecycle" data-ui-label="Discord bridge lifecycle" data-ui-component="control-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=300,maxHeight=900,collision=avoid,preserve-runtime-ids,preserve-handlers">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Bridge controls</span><h4>Lifecycle + status</h4></div><span>${escapeHtml(model.bridge?.pid ? `PID ${model.bridge.pid}` : 'offline')}</span>${moduleChannelsHelpButton('Lifecycle + status', 'Start, stop, restart, or wake-probe the managed Discord bridge from Thomas without touching the bot repo manually.')}</div>
                    <p class="module-channels-section-copy">Use the primary control to start or stop the bridge. Restart reapplies runtime settings, and the wake probe exercises the live Discord voice path.</p>
                    <div class="module-channels-actions">
                        <button type="button" class="module-channels-btn primary" data-channels-action="${primaryControlAction}" ${moduleChannelsProtectedAttrs('action', 'lifecycle-primary', primaryControlLabel, model.running ? 'controls bridge destructive' : 'controls bridge')}>${primaryControlLabel}</button>
                        <button type="button" class="module-channels-btn" data-channels-action="restart" ${moduleChannelsProtectedAttrs('action', 'restart', 'Restart Discord bridge', 'controls bridge')}>Restart Bridge</button>
                        <button type="button" class="module-channels-btn" data-channels-action="toggle_enabled" ${moduleChannelsProtectedAttrs('action', 'toggle-enabled', model.enabled ? 'Turn Discord channel off' : 'Turn Discord channel on', model.enabled ? 'controls bridge destructive' : 'controls bridge')}>${model.enabled ? 'Turn Channel Off' : 'Turn Channel On'}</button>
                        <button type="button" class="module-channels-btn" data-channels-action="voice_probe" ${moduleChannelsProtectedAttrs('action', 'voice-probe', 'Run Discord wake probe', 'controls bridge')}>${state?.voiceProbeRunning ? 'Running Wake Probe' : 'Run Wake Probe'}</button>
                        <button type="button" class="module-channels-btn" data-channels-action="refresh" ${moduleChannelsProtectedAttrs('action', 'refresh', 'Refresh Discord status', 'controls bridge')}>Refresh Status</button>
                    </div>
                    <div class="module-channels-meta-grid">
                        <div><span>Last started</span><strong>${escapeHtml(safeString(model.bridge?.last_started_at) ? missionRelativeTime(safeString(model.bridge.last_started_at)) : 'never')}</strong></div>
                        <div><span>Last stopped</span><strong>${escapeHtml(safeString(model.bridge?.last_stopped_at) ? missionRelativeTime(safeString(model.bridge.last_stopped_at)) : 'unknown')}</strong></div>
                        <div><span>Secure config</span><strong>${model.configured ? 'ready' : 'missing values'}</strong></div>
                        <div><span>Wake probe</span><strong>${state?.voiceProbeRunning ? 'running' : 'ready'}</strong></div>
                    </div>
                    ${safeString(model.bridge?.last_error) ? `<div class="module-empty">${escapeHtml(safeString(model.bridge.last_error).slice(0, 320))}</div>` : ''}
                </article>
                <form class="module-channels-section-card" data-channels-config-form data-ui-id="channels.discord.secure-config" data-ui-label="Discord secure configuration" data-ui-component="config-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=300,maxHeight=1000,collision=avoid,preserve-runtime-ids,preserve-handlers">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Connect + configure</span><h4>Secure local store</h4></div><span>${escapeHtml(model.secretStorageLabel)}</span>${moduleChannelsHelpButton('Secure local store', 'Discord secrets stay in Thomas local secure storage and are only injected into the managed bridge process when the bridge starts.')}</div>
                    <p class="module-channels-section-copy">Discord secrets are stored in Thomas secure local storage and only injected into the managed bridge process when it launches.</p>
                    <div class="module-channels-form-grid">
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('config-field', 'bot-token', 'Discord bot token', 'controls secrets')}><span>Discord bot token</span><input type="password" class="form-control" data-channels-config-field="bot_token" placeholder="${escapeHtml(safeString(model.config?.bot_token_masked) || 'Enter new bot token')}" autocomplete="new-password" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('config-field', 'thomas-api-token', 'Thomas API token', 'controls secrets')}><span>Thomas API token</span><input type="password" class="form-control" data-channels-config-field="thomas_api_token" placeholder="${escapeHtml(safeString(model.config?.thomas_api_token_masked) || 'Optional server token')}" autocomplete="new-password" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('config-field', 'thomas-base-url', 'Thomas base URL', 'controls')}><span>Thomas base URL</span><input type="text" class="form-control" data-channels-config-field="thomas_base_url" value="${escapeHtml(safeString(model.config?.thomas_base_url) || 'http://127.0.0.1:8899')}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('config-field', 'session-prefix', 'Discord session prefix', 'controls')}><span>Session prefix</span><input type="text" class="form-control" data-channels-config-field="session_prefix" value="${escapeHtml(safeString(model.config?.session_prefix) || 'thomas-discord')}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('config-field', 'primary-guild-id', 'Primary Discord guild ID', 'controls')}><span>Primary guild ID</span><input type="text" class="form-control" data-channels-config-field="guild_id" value="${escapeHtml(safeString(model.config?.guild_id) || '')}" /></label>
                    </div>
                    <div class="module-channels-actions compact"><button type="button" class="module-channels-btn primary" data-channels-action="save_config" ${moduleChannelsProtectedAttrs('action', 'save-configuration', 'Save Discord configuration', 'controls secrets bridge')}>Save Configuration</button></div>
                </form>
                <article class="module-channels-section-card" data-ui-id="channels.discord.access" data-ui-label="Discord owner access rules" data-ui-component="config-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=320,maxHeight=1000,collision=avoid,preserve-runtime-ids,preserve-handlers">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Access + safety</span><h4>Owner-scoped permissions</h4></div><span>${model.config?.owner_only_mode ? 'owner only' : 'delegated access enabled'}</span>${moduleChannelsHelpButton('Owner-scoped permissions', 'Random Discord users cannot change Thomas settings. Settings actions remain owner-only unless the owner explicitly grants narrower delegated capabilities.')}</div>
                    <p class="module-channels-section-copy">Keep settings and machine-side actions owner scoped. Delegated access should stay narrow and channel-appropriate.</p>
                    <div class="module-channels-form-grid">
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('access-field', 'owner-user-ids', 'Discord owner user IDs', 'controls')}><span>Owner user IDs</span><input type="text" class="form-control" data-channels-config-field="owner_user_ids" value="${escapeHtml((Array.isArray(model.config?.owner_user_ids) ? model.config.owner_user_ids.join(', ') : ''))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('access-field', 'allowed-guild-ids', 'Allowed Discord guild IDs', 'controls')}><span>Allowed guild IDs</span><input type="text" class="form-control" data-channels-config-field="allowed_guild_ids" value="${escapeHtml((Array.isArray(model.config?.allowed_guild_ids) ? model.config.allowed_guild_ids.join(', ') : ''))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('access-field', 'auto-channel-ids', 'Automatic Discord channel IDs', 'controls')}><span>Auto channel IDs</span><input type="text" class="form-control" data-channels-config-field="auto_channel_ids" value="${escapeHtml((Array.isArray(model.config?.auto_channel_ids) ? model.config.auto_channel_ids.join(', ') : ''))}" /></label>
                    </div>
                    <div class="module-channels-checks">
                        <label class="module-channels-check" ${moduleChannelsProtectedAttrs('access-field', 'owner-only-mode', 'Discord owner-only mode', 'controls')}><input type="checkbox" data-channels-config-field="owner_only_mode" ${model.config?.owner_only_mode ? 'checked' : ''} /><span>Owner-only mode</span></label>
                        <label class="module-channels-check" ${moduleChannelsProtectedAttrs('access-field', 'require-mention', 'Require Discord mention', 'controls')}><input type="checkbox" data-channels-config-field="require_mention" ${model.config?.require_mention !== false ? 'checked' : ''} /><span>Require mention</span></label>
                    </div>
                    <div class="module-channels-meta-grid">
                        <div><span>Wake word</span><strong>${model.runtime?.voice_require_wake_word ? 'Required' : 'Optional'}</strong></div>
                        <div><span>Voice profile</span><strong>${escapeHtml(safeString(model.runtime?.voice_profile) || 'unknown')}</strong></div>
                        <div><span>Media volume</span><strong>${escapeHtml(String(model.runtime?.voice_media_volume || 0))}%</strong></div>
                        <div><span>Delegated grants</span><strong>${escapeHtml(String(model.runtime?.access_grants_count || 0))}</strong></div>
                    </div>
                    <div class="module-channels-actions compact"><button type="button" class="module-channels-btn" data-channels-action="save_config" ${moduleChannelsProtectedAttrs('action', 'save-access-rules', 'Save Discord access rules', 'controls bridge')}>Save Access Rules</button></div>
                </article>
                <article class="module-channels-section-card" data-ui-id="channels.discord.voice" data-ui-label="Discord voice and speech settings" data-ui-component="config-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=520,maxHeight=1800,collision=avoid,preserve-runtime-ids,preserve-handlers">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Voice + speech</span><h4>Discord-specific runtime</h4></div><span>${escapeHtml(safeString(model.runtime?.voice_profile) || safeString(model.config?.voice_tts_backend) || 'voice unset')}</span>${moduleChannelsHelpButton('Voice + speech', 'Voice profile, wake-word behavior, TTS backend, media volume, and speech-to-text options are Discord-specific. Saving here reapplies the bridge runtime so Discord uses the new settings.')}</div>
                    <p class="module-channels-section-copy">Change the Discord voice profile, wake-word behavior, TTS backend, media volume, and speech-to-text settings here. Thomas will reapply the bridge if it is already running.</p>
                    <div class="module-channels-form-grid">
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'tts-backend', 'Discord TTS backend', 'controls')}><span>TTS backend</span><select class="form-control" data-channels-voice-config-field="voice_tts_backend"><option value="piper"${ttsBackend === 'piper' ? ' selected' : ''}>piper</option><option value="openai"${ttsBackend === 'openai' ? ' selected' : ''}>openai</option><option value="windows"${ttsBackend === 'windows' ? ' selected' : ''}>windows</option></select></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'tts-model', 'Discord TTS model', 'controls')}><span>TTS model</span><input type="text" class="form-control" data-channels-voice-config-field="voice_tts_model" value="${escapeHtml(safeString(model.config?.voice_tts_model) || '')}" placeholder="${escapeHtml(ttsBackend === 'openai' ? 'gpt-4o-mini-tts' : 'en_US-ryan-high')}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'cloud-voice', 'Discord cloud voice', 'controls')}><span>Cloud voice</span><input type="text" class="form-control" data-channels-voice-config-field="voice_cloud_voice" value="${escapeHtml(safeString(model.config?.voice_cloud_voice) || '')}" placeholder="alloy" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'voice-profile', 'Discord voice profile', 'controls')}><span>Voice profile</span><input type="text" class="form-control" data-channels-runtime-field="voice_profile" value="${escapeHtml(safeString(model.runtime?.voice_profile) || '')}" placeholder="en_US-ryan-high" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'preferred-channel', 'Preferred Discord voice channel', 'controls')}><span>Preferred voice channel</span><input type="text" class="form-control" data-channels-voice-config-field="default_voice_channel_name" value="${escapeHtml(safeString(model.config?.default_voice_channel_name) || '')}" placeholder="Music" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'end-of-speech', 'End of speech timing', 'controls')}><span>End-of-speech ms</span><input type="number" min="200" max="5000" class="form-control" data-channels-voice-config-field="voice_silence_ms" value="${escapeHtml(String(model.config?.voice_silence_ms ?? 700))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'wake-capture-max', 'Wake capture maximum', 'controls')}><span>Wake capture max ms</span><input type="number" min="500" max="30000" class="form-control" data-channels-voice-config-field="voice_wake_capture_ms" value="${escapeHtml(String(model.config?.voice_wake_capture_ms ?? 6500))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'wake-words', 'Discord wake words', 'controls')}><span>Wake words</span><input type="text" class="form-control" data-channels-runtime-field="voice_wake_words" value="${escapeHtml((Array.isArray(model.runtime?.voice_wake_words) ? model.runtime.voice_wake_words.join(', ') : ''))}" placeholder="thomas, hey thomas" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'media-volume', 'Discord media volume', 'controls')}><span>Media volume</span><input type="number" min="0" max="200" class="form-control" data-channels-runtime-field="voice_media_volume" value="${escapeHtml(String(model.runtime?.voice_media_volume ?? 100))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-backend', 'Discord STT backend', 'controls')}><span>STT backend</span><select class="form-control" data-channels-voice-config-field="voice_stt_backend"><option value="faster-whisper"${sttBackend === 'faster-whisper' ? ' selected' : ''}>faster-whisper</option><option value="openai"${sttBackend === 'openai' ? ' selected' : ''}>openai</option><option value="windows"${sttBackend === 'windows' ? ' selected' : ''}>windows</option></select></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-model', 'Discord STT model', 'controls')}><span>STT model</span><input type="text" class="form-control" data-channels-voice-config-field="voice_stt_model" value="${escapeHtml(safeString(model.config?.voice_stt_model) || '')}" placeholder="${escapeHtml(sttBackend === 'openai' ? 'gpt-4o-transcribe' : 'distil-large-v3')}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-device', 'Discord STT device', 'controls')}><span>STT device</span><select class="form-control" data-channels-voice-config-field="voice_stt_device"><option value="cpu"${sttDevice === 'cpu' ? ' selected' : ''}>cpu</option><option value="cuda"${sttDevice === 'cuda' ? ' selected' : ''}>cuda</option></select></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-compute-type', 'Discord STT compute type', 'controls')}><span>Compute type</span><select class="form-control" data-channels-voice-config-field="voice_stt_compute_type"><option value="int8"${sttComputeType === 'int8' ? ' selected' : ''}>int8</option><option value="float16"${sttComputeType === 'float16' ? ' selected' : ''}>float16</option><option value="float32"${sttComputeType === 'float32' ? ' selected' : ''}>float32</option></select></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-beam-size', 'Discord STT beam size', 'controls')}><span>Beam size</span><input type="number" min="1" max="10" class="form-control" data-channels-voice-config-field="voice_stt_beam_size" value="${escapeHtml(String(model.config?.voice_stt_beam_size ?? 5))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-vad-filter', 'Discord STT VAD filter', 'controls')}><span>STT VAD filter</span><select class="form-control" data-channels-voice-config-field="voice_stt_vad_filter"><option value="true"${sttVadFilterEnabled ? ' selected' : ''}>on</option><option value="false"${!sttVadFilterEnabled ? ' selected' : ''}>off</option></select></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'vad-min-silence', 'Discord VAD minimum silence', 'controls')}><span>VAD min silence ms</span><input type="number" min="100" max="5000" class="form-control" data-channels-voice-config-field="voice_stt_vad_min_silence_ms" value="${escapeHtml(String(model.config?.voice_stt_vad_min_silence_ms ?? 500))}" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-language', 'Discord STT language', 'controls')}><span>STT language</span><input type="text" class="form-control" data-channels-voice-config-field="voice_stt_language" value="${escapeHtml(safeString(model.config?.voice_stt_language) || '')}" placeholder="en" /></label>
                        <label class="module-channels-field" ${moduleChannelsProtectedAttrs('voice-field', 'stt-hint-phrases', 'Discord STT hint phrases', 'controls')}><span>STT hint phrases</span><input type="text" class="form-control" data-channels-voice-config-field="voice_stt_hint_phrases" value="${escapeHtml((Array.isArray(model.config?.voice_stt_hint_phrases) ? model.config.voice_stt_hint_phrases.join(', ') : ''))}" placeholder="music, soundboard, hey thomas" /></label>
                        <label class="module-channels-field module-channels-field-wide" ${moduleChannelsProtectedAttrs('voice-field', 'stt-prompt', 'Discord STT prompt', 'controls')}><span>STT prompt</span><textarea class="form-control" rows="3" data-channels-voice-config-field="voice_stt_prompt" placeholder="Tell STT what names or Discord commands matter most.">${escapeHtml(safeString(model.config?.voice_stt_prompt) || '')}</textarea></label>
                    </div>
                    <div class="module-channels-checks">
                        <label class="module-channels-check" ${moduleChannelsProtectedAttrs('voice-field', 'require-wake-word', 'Require Discord wake phrase', 'controls')}><input type="checkbox" data-channels-runtime-field="voice_require_wake_word" ${model.runtime?.voice_require_wake_word ? 'checked' : ''} /><span>Require wake phrase before voice actions</span></label>
                    </div>
                    <div class="module-channels-actions compact"><button type="button" class="module-channels-btn primary" data-channels-action="save_voice_settings" ${moduleChannelsProtectedAttrs('action', 'save-voice-settings', 'Save Discord voice and speech settings', 'controls bridge')}>Save Voice + Speech</button></div>
                </article>
            </div>
            <article class="module-channels-section-card" data-ui-id="channels.discord.history" data-ui-label="Indexed Discord memory" data-ui-component="history-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=340,minHeight=480,maxHeight=1500,collision=avoid,preserve-runtime-ids,preserve-handlers">
                <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Conversation access</span><h4>Indexed Discord memory</h4></div><span>${state?.loading ? 'refreshing' : `updated ${escapeHtml(model.lastUpdatedLabel)}`}</span>${moduleChannelsHelpButton('Indexed Discord memory', 'Thomas indexes Discord turns here so it can search past conversations, select a session, and reuse the correct context later.')}</div>
                <div class="module-channels-searchbar">
                    <input type="search" class="form-control" data-channels-search value="${escapeHtml(model.searchText)}" placeholder="Search Discord history" ${moduleChannelsProtectedAttrs('history-control', 'search-input', 'Search Discord history', 'controls')} />
                    <button type="button" class="module-channels-btn" data-channels-action="search" ${moduleChannelsProtectedAttrs('history-control', 'search', 'Run Discord history search', 'controls')}>Search</button>
                    <button type="button" class="module-channels-btn" data-channels-action="clear_search" ${moduleChannelsProtectedAttrs('history-control', 'clear-search', 'Clear Discord history search', 'controls')}>Clear</button>
                </div>
                ${moduleChannelsHitMarkup(model)}
                <div class="module-channels-history-frame" data-ui-id="channels.history-layout" data-ui-label="Discord history layout" data-ui-component="panel-group" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=360,maxHeight=1100,collision=avoid">
                    <aside class="module-channels-session-rail" data-ui-id="channels.history.sessions" data-ui-label="Discord sessions" data-ui-component="repeating-record-group" data-ui-policy="move resize" data-ui-constraints="items-runtime-owned,reposition-deny,resize-deny,add-deny,remove-deny,contain=parent,minWidth=240,minHeight=280,maxHeight=900">
                        <div class="module-channels-session-rail-head">
                            <strong>Sessions</strong>
                            <span>${escapeHtml(String(model.sessions.length))}</span>
                        </div>
                        <div class="module-channels-session-list" data-ui-id="channels.history.session-list" data-ui-label="Discord session records" data-ui-component="repeating-record-group" data-ui-policy="protected live-record-group" data-ui-constraints="items-runtime-owned,reposition-deny,resize-deny,add-deny,remove-deny,preserve-runtime-ids,preserve-handlers">${moduleChannelsSessionMarkup(model, state)}</div>
                    </aside>
                    <section class="module-channels-transcript-shell" data-ui-id="channels.history.transcript" data-ui-label="Selected Discord transcript" data-ui-component="content-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=300,minHeight=320,maxHeight=1000,collision=avoid">
                        <div class="module-channels-section-header compact">
                            <div>
                                <span class="module-channels-section-kicker">Selected session</span>
                                <h4>${escapeHtml(safeString(model.selectedMeta?.display_name) || safeString(model.selectedMeta?.session_id) || 'No session selected')}</h4>
                            </div>
                            <span>${escapeHtml(safeString(model.selectedMeta?.session_id) || 'none')}</span>
                        </div>
                        ${moduleChannelsSessionSummaryMarkup(model)}
                        <div class="module-channels-transcript-list" data-ui-id="channels.history.turn-list" data-ui-label="Discord transcript turns" data-ui-component="repeating-record-group" data-ui-policy="protected live-record-group" data-ui-constraints="items-runtime-owned,reposition-deny,resize-deny,add-deny,remove-deny,preserve-runtime-ids,preserve-handlers">${moduleChannelsTurnMarkup(model)}</div>
                    </section>
                </div>
            </article>
            ${moduleChannelsProbeResultMarkup(state)}
        </section>
    `;
}

function moduleRenderChannelsSurfaceNext(container, state) {
    const model = moduleBuildChannelsSurfaceModel(state);
    state.selectedChannelId = model.selectedChannelId;
    const detailOpen = Boolean(state?.detailOpen);
    const detailMarkup = model.selectedChannel?.id === 'discord'
        ? moduleRenderDiscordChannelDetail(model, state)
        : moduleRenderPlaceholderChannelDetail(model);
    container.innerHTML = detailOpen ? `
        <section class="module-channels-shell" data-ui-workspace="channels" data-ui-id="channels.shell" data-ui-label="Channels workspace" data-ui-component="workspace-shell" data-ui-policy="root protected" data-ui-constraints="preserve-runtime-ids,preserve-handlers">
            ${detailMarkup}
            ${safeString(state?.error) ? `<div class="module-empty">${escapeHtml(state.error)}</div>` : ''}
        </section>
    ` : `
        <section class="module-channels-shell" data-ui-workspace="channels" data-ui-id="channels.shell" data-ui-label="Channels workspace" data-ui-component="workspace-shell" data-ui-policy="root protected" data-ui-constraints="preserve-runtime-ids,preserve-handlers">
            <section class="module-channels-catalog" data-ui-id="channels.catalog" data-ui-label="Channel catalog" data-ui-component="content-panel" data-ui-policy="move resize" data-ui-constraints="contain=parent,minWidth=320,minHeight=420,maxHeight=1800,collision=avoid,preserve-runtime-ids,preserve-handlers">
                <div class="module-channels-title-lockup">
                    <span class="thomas-eyes-mark module-channels-eyes-mark" aria-hidden="true"><i></i><i></i></span>
                    <div>
                        <span class="module-channels-section-kicker">Channels workspace</span>
                        <h3>All channels</h3>
                        <p>Drag channels into the order you want, then open one to manage it.</p>
                    </div>
                </div>
                <div class="module-channels-section-header">
                    <div>
                        <span class="module-channels-section-kicker">Channel catalog</span>
                        <h4>${escapeHtml(String(model.catalog.length))} channel slots ready</h4>
                    </div>
                    <span>${state?.loading ? 'refreshing' : `updated ${escapeHtml(model.lastUpdatedLabel)}`}</span>
                </div>
                <div class="module-channels-grid" data-channel-grid data-ui-id="channels.catalog-grid" data-ui-label="Channel cards" data-ui-component="repeating-card-group" data-ui-policy="move resize" data-ui-constraints="items-runtime-owned,reposition-allow,resize-deny,add-deny,remove-deny,contain=parent,minWidth=280,minHeight=260,maxHeight=1600,collision=avoid">
                    ${moduleChannelsCatalogMarkup(model)}
                </div>
            </section>
            ${safeString(state?.error) ? `<div class="module-empty">${escapeHtml(state.error)}</div>` : ''}
        </section>
    `;
    return container.firstElementChild;
}

function moduleRenderSpecialSurface(mode, container) {
    const config = moduleGetSpecialSurfaceConfig(mode);
    if (!config) return null;
    return moduleRenderEmbeddedSurface(container, config);
}

function moduleRenderList(container, { mode, section, rows, emptyText }) {
    if (!container) return;
    container.innerHTML = '';
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
        moduleRenderEmpty(container, emptyText || 'No items right now.');
        return;
    }
    const frag = document.createDocumentFragment();
    items.forEach((item) => {
        const card = document.createElement('article');
        card.className = 'module-item-card';
        const toneClass = moduleToneClass(item?.tone);
        const badgeClass = toneClass ? `module-item-badge ${toneClass}` : 'module-item-badge';
        const actions = Array.isArray(item?.actions) ? item.actions : [];
        const actionsHtml = actions.map((action) => `
            <button
                type="button"
                class="module-item-btn"
                data-module-mode="${escapeHtml(mode)}"
                data-module-section="${escapeHtml(section)}"
                data-module-item-id="${escapeHtml(safeString(item?.id))}"
                data-module-action-id="${escapeHtml(safeString(action?.id))}"
                data-module-action-label="${escapeHtml(safeString(action?.label))}"
                data-module-action-url="${escapeHtml(safeString(action?.actionUrl || action?.url || ''))}">
                ${escapeHtml(safeString(action?.label) || 'Run')}
            </button>
        `).join('');
        card.innerHTML = `
            <div class="module-item-top">
                <h4 class="module-item-title">${escapeHtml(safeString(item?.title) || 'Item')}</h4>
                ${safeString(item?.badge) ? `<span class="${badgeClass}">${escapeHtml(safeString(item?.badge))}</span>` : ''}
            </div>
            <p class="module-item-meta">${escapeHtml(safeString(item?.meta) || '')}</p>
            ${actionsHtml ? `<div class="module-item-actions">${actionsHtml}</div>` : ''}
        `;
        frag.appendChild(card);
    });
    container.appendChild(frag);
}

function moduleRenderActions(definition, mode) {
    if (!moduleActionsGrid) return;
    moduleActionsGrid.innerHTML = '';
    const actions = Array.isArray(definition?.actions) ? definition.actions : [];
    if (!actions.length) {
        moduleRenderEmpty(moduleActionsGrid, 'No quick actions configured.');
        return;
    }
    const frag = document.createDocumentFragment();
    actions.forEach((action) => {
        const actionLabel = withAgentName(safeString(action?.label));
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'module-action-btn';
        button.dataset.moduleMode = mode;
        button.dataset.moduleActionId = safeString(action?.id);
        button.dataset.moduleActionLabel = actionLabel;
        button.innerHTML = `
            <strong>${escapeHtml(actionLabel || 'Action')}</strong>
            <span>${escapeHtml(safeString(action?.meta) || '')}</span>
        `;
        frag.appendChild(button);
    });
    moduleActionsGrid.appendChild(frag);
}

function moduleRenderTriage(definition, mode) {
    if (!moduleTriagePanel || !moduleTriageTitle || !moduleTriageMeta || !moduleTriageFilters || !moduleTriageMessages) return;
    const triage = definition?.triage;
    if (!triage) {
        moduleTriagePanel.classList.add('hidden');
        moduleTriageFilters.innerHTML = '';
        moduleTriageMessages.innerHTML = '';
        return;
    }
    moduleTriagePanel.classList.remove('hidden');
    moduleTriageTitle.textContent = safeString(triage?.title) || 'Triage';
    moduleTriageMeta.textContent = safeString(triage?.meta) || 'Filter and act';

    const state = moduleEnsureRuntime();
    const defaultFilter = safeString(triage?.defaultFilter) || 'all';
    const activeFilter = safeString(state?.triageFilters?.[mode]) || defaultFilter;
    if (state && !safeString(state.triageFilters[mode])) {
        state.triageFilters[mode] = activeFilter;
    }

    moduleTriageFilters.innerHTML = '';
    (triage.filters || []).forEach((filter) => {
        const id = safeString(filter).toLowerCase();
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `module-filter-btn${activeFilter === id ? ' active' : ''}`;
        btn.dataset.moduleMode = mode;
        btn.dataset.moduleFilter = id;
        btn.textContent = id.replace(/_/g, ' ');
        moduleTriageFilters.appendChild(btn);
    });

    const rows = moduleVisibleItems(mode, 'triage', triage.rows || []).filter((row) => {
        if (activeFilter === 'all') return true;
        const tags = Array.isArray(row?.tags) ? row.tags.map((tag) => safeString(tag).toLowerCase()) : [];
        return tags.includes(activeFilter);
    }).map((row) => ({
        ...row,
        actions: [{ id: 'open', label: 'Open' }, { id: 'ack', label: 'Acknowledge' }],
    }));

    moduleRenderList(moduleTriageMessages, {
        mode,
        section: 'triage',
        rows,
        emptyText: 'No rows for this triage filter.',
    });
}

// 
//   MODULE RENDERING & DISPATCH                                            
//   moduleRender(), moduleEnterMode(), initModuleWorkspace()               
// 

function moduleRender(modeRaw, { touch = true } = {}) {
    const mode = MODULE_NAV_MODE_SET.has(modeRaw) ? modeRaw : 'dashboard';
    const state = moduleEnsureRuntime();
    if (!state) return;
    const modeChanged = safeString(state.lastRenderedMode) !== mode;
    const snapshot = moduleBuildSnapshot();
    const signals = moduleCollectSignals(snapshot);
    const definition = moduleBuildDefinition(mode, snapshot, signals);
    if (touch) moduleTouch(mode);
    const layout = safeString(definition?.layout) || 'hub';
    const specialSurfaceOnly = moduleModeUsesSpecialSurface(mode);
    const specialSurfaceMode = specialSurfaceOnly ? moduleGetSpecialSurfaceMode(mode) : '';
    const queueSurfaceOnly = specialSurfaceOnly || mode === 'marketplace' || mode === 'channels';

    if (moduleWorkspaceTitle) moduleWorkspaceTitle.textContent = definition.title;
    if (moduleWorkspaceSubtitle) moduleWorkspaceSubtitle.textContent = definition.subtitle;
    if (moduleWorkspaceModePill) moduleWorkspaceModePill.textContent = definition.pill;
    if (moduleWorkspace) {
        moduleWorkspace.dataset.layout = layout;
        moduleWorkspace.dataset.mode = mode;
        if (specialSurfaceMode) {
            moduleWorkspace.dataset.embeddedSurfaceMode = specialSurfaceMode;
        } else {
            delete moduleWorkspace.dataset.embeddedSurfaceMode;
        }
        if (queueSurfaceOnly) {
            moduleWorkspace.dataset.surfaceLayout = "full";
        } else {
            delete moduleWorkspace.dataset.surfaceLayout;
        }
        moduleSyncSurfaceScrollState();
        if (modeChanged) {
            if (state.modeEnterTimer) {
                window.clearTimeout(state.modeEnterTimer);
                state.modeEnterTimer = 0;
            }
            moduleWorkspace.classList.remove('mode-enter');
            void moduleWorkspace.offsetWidth;
            moduleWorkspace.classList.add('mode-enter');
            state.modeEnterTimer = window.setTimeout(() => {
                if (moduleWorkspace) moduleWorkspace.classList.remove('mode-enter');
                state.modeEnterTimer = 0;
            }, 420);
        }
    }
    if (moduleWorkspaceMeta) {
        if (mode === 'marketplace') {
            moduleWorkspaceMeta.textContent = 'Marketplace catalog';
        } else if (mode === 'channels') {
            moduleWorkspaceMeta.textContent = 'Discord bridge lifecycle, safety, and searchable conversation context';
        } else if (mode === 'my_stuff') {
            moduleWorkspaceMeta.textContent = 'Local launch shortcuts';
        } else {
            const refreshed = state.refreshedAt[mode] || Date.now();
            moduleWorkspaceMeta.textContent = `Auto-refresh enabled | refreshed ${missionRelativeTime(new Date(refreshed).toISOString())}`;
        }
    }

    const labels = definition?.panelLabels || {};
    if (moduleQueueTitle) moduleQueueTitle.textContent = safeString(labels.queueTitle) || 'Priority Queue';
    if (moduleQueueMeta) moduleQueueMeta.textContent = safeString(labels.queueMeta) || 'Most relevant work on top';
    if (moduleHealthTitle) moduleHealthTitle.textContent = safeString(labels.healthTitle) || 'Health + Status';
    if (moduleHealthMeta) moduleHealthMeta.textContent = safeString(labels.healthMeta) || 'Critical checks and integrations';
    if (moduleActionsTitle) moduleActionsTitle.textContent = safeString(labels.actionsTitle) || 'Quick Actions';
    if (moduleActionsMeta) moduleActionsMeta.textContent = safeString(labels.actionsMeta) || 'Run immediate actions';
    if (moduleActivityTitle) moduleActivityTitle.textContent = safeString(labels.activityTitle) || 'Activity';
    if (moduleActivityMeta) moduleActivityMeta.textContent = safeString(labels.activityMeta) || 'Recent events and auto updates';

    const queueWide = layout === 'hub' || layout === 'catalog' || layout === 'board';
    const activityWide = layout === 'editor_media' || layout === 'editor_code' || layout === 'editor_game' || layout === 'editor_3d' || layout === 'research';
    if (moduleQueuePanel) moduleQueuePanel.classList.toggle('module-panel-wide', queueWide);
    if (moduleActivityPanel) moduleActivityPanel.classList.toggle('module-panel-wide', activityWide);
    if (moduleKpiGrid) {
        if (queueSurfaceOnly) {
            moduleKpiGrid.innerHTML = '';
            moduleKpiGrid.classList.add('hidden');
        } else {
            moduleKpiGrid.classList.remove('hidden');
            moduleRenderKpis(definition);
        }
    }
    if (moduleSubnavRow) {
        if (queueSurfaceOnly) {
            moduleSubnavRow.classList.add('hidden');
        } else {
            moduleRenderSubnav(mode);
        }
    }
    if (moduleFlairRow) {
        if (queueSurfaceOnly) {
            moduleFlairRow.classList.add('hidden');
            moduleFlairRow.innerHTML = '';
        } else {
            moduleRenderFlair(moduleBuildFlair(mode, signals, snapshot));
        }
    }
    if (moduleFocusStrip) {
        if (queueSurfaceOnly) {
            moduleFocusStrip.classList.add('hidden');
            moduleFocusStrip.innerHTML = '';
        } else {
            moduleRenderFocus(moduleBuildFocusCards(mode, snapshot, signals));
        }
    }
    if (moduleSpecialGrid) {
        if (queueSurfaceOnly) {
            moduleSpecialGrid.classList.add('hidden');
            moduleSpecialGrid.innerHTML = '';
        } else {
            moduleRenderSpecialCards(moduleBuildSpecialCards(mode, snapshot, signals, definition));
        }
    }
    if (moduleHealthPanel) moduleHealthPanel.classList.toggle('hidden', queueSurfaceOnly);
    if (moduleActionsPanel) moduleActionsPanel.classList.toggle('hidden', queueSurfaceOnly);
    if (moduleActivityPanel) moduleActivityPanel.classList.toggle('hidden', queueSurfaceOnly);
    if (moduleTriagePanel) moduleTriagePanel.classList.toggle('hidden', queueSurfaceOnly);
    moduleRenderWorkbench(mode, snapshot, signals, definition, { force: modeChanged });
        if (queueSurfaceOnly) {
        if (mode === 'marketplace') {
  moduleApplyMarketplaceUiContracts(moduleRenderMarketplaceSurface(moduleQueueList));
        } else if (mode === 'channels') {
            moduleRenderChannelsSurface(moduleQueueList);
        } else {
            moduleRenderSpecialSurface(mode, moduleQueueList);
        }
        if (moduleHealthList) moduleHealthList.innerHTML = '';
        if (moduleActionsGrid) moduleActionsGrid.innerHTML = '';
        if (moduleActivityList) moduleActivityList.innerHTML = '';
        if (moduleTriageFilters) moduleTriageFilters.innerHTML = '';
        if (moduleTriageMessages) moduleTriageMessages.innerHTML = '';
    } else {
        moduleRenderList(moduleQueueList, {
            mode,
            section: 'queue',
            rows: moduleVisibleItems(mode, 'queue', definition.queueRows),
            emptyText: modulePanelEmptyText(mode, 'queue'),
        });
    }
    if (!queueSurfaceOnly) {
        moduleRenderList(moduleHealthList, {
            mode,
            section: 'health',
            rows: moduleVisibleItems(mode, 'health', definition.healthRows),
            emptyText: modulePanelEmptyText(mode, 'health'),
        });
        moduleRenderActions(definition, mode);
        moduleRenderList(moduleActivityList, {
            mode,
            section: 'activity',
            rows: definition.activityRows,
            emptyText: modulePanelEmptyText(mode, 'activity'),
        });
        moduleRenderTriage(definition, mode);
    }
    state.lastRenderedMode = mode;
}

// ── Module Background System ─────────────────────────────────────
// Marketplace modules can register a page-level background that
// gets injected when they're active and removed when they leave.
//
// Usage from any module JS:
//   window.__moduleBackgrounds = window.__moduleBackgrounds || {};
//   window.__moduleBackgrounds['my_module'] = {
//       mount: () => { /* inject bg onto document.body */ },
//       unmount: () => { /* remove it */ },
//   };
//
// The system calls mount() on enter and unmount() on leave
// automatically. Only one module bg is active at a time.
if (!window.__moduleBackgrounds) window.__moduleBackgrounds = {};
let _activeModuleBg = null;

function _mountModuleBg(mode) {
    // Tear down any previous module background first
    _unmountModuleBg();
    const reg = window.__moduleBackgrounds[mode];
    if (reg && typeof reg.mount === 'function') {
        try { reg.mount(); _activeModuleBg = mode; } catch (e) { console.warn('[module-bg] mount error:', e); }
    }
}

function _unmountModuleBg() {
    if (_activeModuleBg) {
        const reg = window.__moduleBackgrounds[_activeModuleBg];
        if (reg && typeof reg.unmount === 'function') {
            try { reg.unmount(); } catch (e) { console.warn('[module-bg] unmount error:', e); }
        }
        _activeModuleBg = null;
    }
}

function moduleEnterMode(modeRaw) {
    const mode = MODULE_NAV_MODE_SET.has(modeRaw) ? modeRaw : 'dashboard';
    const state = moduleEnsureRuntime();
    if (!state) return;
    state.activeMode = mode;

    // Activate module background if registered (any marketplace module can use this)
    _mountModuleBg(mode);

    // Token Economy uses a custom renderer via token_economy.js
    if (mode === 'token_economy' && window.__tokenEconomy && moduleWorkspace) {
        // hide all existing workspace children so they don't show beneath
        for (const ch of moduleWorkspace.children) {
            if (!ch.hasAttribute('data-te-container')) ch.style.display = 'none';
        }
        let teContainer = moduleWorkspace.querySelector('[data-te-container]');
        if (!teContainer) {
            teContainer = document.createElement('div');
            teContainer.setAttribute('data-te-container', '');
            teContainer.style.cssText = 'flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;';
            moduleWorkspace.appendChild(teContainer);
        }
        teContainer.style.display = '';
        window.__tokenEconomy.mount(teContainer);
        state.lastRenderedMode = mode;
        return;
    }

    // hide token economy container and restore siblings if switching away
    const teEl = moduleWorkspace?.querySelector('[data-te-container]');
    if (teEl) {
        teEl.style.display = 'none';
        if (window.__tokenEconomy) window.__tokenEconomy.unmount();
        // restore all workspace children that were hidden
        for (const ch of moduleWorkspace.children) {
            if (!ch.hasAttribute('data-te-container')) ch.style.display = '';
        }
    }

    moduleRender(mode);
}

function moduleLeaveMode() {
    // Tear down any active module background
    _unmountModuleBg();

    // clean up token economy if active
    const teEl = document.querySelector('[data-te-container]');
    if (teEl) {
        teEl.classList.add('hidden');
        if (window.__tokenEconomy) window.__tokenEconomy.unmount();
    }
}

function moduleSyncSurfaceScrollState() {
    if (!moduleWorkspace) return;
    const useSurfaceLayout = safeString(moduleWorkspace.dataset.surfaceLayout) === 'full';
    const isScrolled = useSurfaceLayout && Number(moduleWorkspace.scrollTop) > 8;
    if (isScrolled) {
        moduleWorkspace.dataset.surfaceScrolled = 'true';
    } else {
        delete moduleWorkspace.dataset.surfaceScrolled;
    }
}

