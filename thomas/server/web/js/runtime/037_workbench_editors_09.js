function moduleChannelsProbeResultMarkup(state) {
    const result = state?.voiceProbeResult && typeof state.voiceProbeResult === 'object' ? state.voiceProbeResult : null;
    if (!result) {
        return `
            <article class="module-channels-section-card">
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
        <article class="module-channels-section-card">
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
        return `
            <button
                type="button"
                class="module-channel-card${isSelected ? ' is-selected' : ''}"
                data-channel-card-select="${escapeHtml(entry.id)}"
                data-channel-card-id="${escapeHtml(entry.id)}"
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
    return `
        <section class="module-channels-detail-shell">
            <div class="module-channels-detail-toolbar">
                <button type="button" class="module-channels-btn" data-channels-action="back_to_catalog">Back To All Channels</button>
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
                <article class="module-channels-section-card">
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
                <article class="module-channels-section-card">
                    <div class="module-channels-section-header">
                        <div>
                            <span class="module-channels-section-kicker">Guided setup</span>
                            <h4>Generate a Thomas setup prompt</h4>
                        </div>
                        ${moduleChannelsHelpButton('Guided setup', 'This sends a structured setup prompt into Thomas chat so Thomas can walk through the API, permissions, and product-side requirements for this channel.')}
                    </div>
                    <p class="module-channels-section-copy">Use the guided configure action to send a prebuilt planning prompt into Thomas chat for ${escapeHtml(model.selectedChannel.title)}.</p>
                    <div class="module-channels-actions">
                        <button type="button" class="module-channels-btn primary" data-channels-action="configure_channel" data-channels-channel-id="${escapeHtml(model.selectedChannel.id)}">Configure ${escapeHtml(model.selectedChannel.title)}</button>
                    </div>
                </article>
            </div>
        </section>
    `;
}

function moduleChannelsSliderDecimals(stepValue) {
    const stepText = safeString(stepValue);
    if (!stepText.includes('.')) return 0;
    return Math.max(0, stepText.split('.')[1].replace(/0+$/, '').length);
}

function moduleChannelsFormatSliderValue(valueRaw, formatRaw, suffixRaw = '') {
    const value = Number(valueRaw);
    const format = safeString(formatRaw).toLowerCase() || 'int';
    const suffix = safeString(suffixRaw);
    if (!Number.isFinite(value)) return `0${suffix}`;
    if (format === 'float2') return `${value.toFixed(2)}${suffix}`;
    if (format === 'float1') return `${value.toFixed(1)}${suffix}`;
    return `${Math.round(value)}${suffix}`;
}

const moduleChannelsVoiceConfigFieldMarkers = [
    'data-channels-voice-config-field="voice_silence_ms"',
    'data-channels-voice-config-field="voice_wake_capture_ms"',
    'data-channels-voice-config-field="voice_stt_beam_size"',
    'data-channels-voice-config-field="voice_stt_vad_min_silence_ms"',
];

function moduleChannelsFieldLabelMarkup(label, description = '') {
    const helpText = safeString(description);
    if (!helpText) return `<span class="module-channels-field-label">${escapeHtml(label)}</span>`;
    return `
        <span
            class="module-channels-field-label"
            data-help="${escapeHtml(helpText)}"
            tabindex="0">${escapeHtml(label)}</span>
    `;
}

function moduleChannelsSliderField({
    fieldAttr,
    fieldKey,
    label,
    description = '',
    value,
    min,
    max,
    step = 1,
    suffix = '',
    format = '',
    className = '',
}) {
    const numericValue = Number(value);
    const floor = Number(min);
    const ceiling = Number(max);
    const resolvedStep = Number(step);
    const safeValue = Number.isFinite(numericValue)
        ? Math.max(floor, Math.min(ceiling, numericValue))
        : floor;
    const resolvedFormat = safeString(format) || (moduleChannelsSliderDecimals(step) > 0 ? 'float2' : 'int');
    const classes = ['module-channels-field', 'module-channels-field-slider'];
    if (safeString(className)) classes.push(safeString(className));
    return `
        <label class="${classes.join(' ')}">
            ${moduleChannelsFieldLabelMarkup(label, description)}
            <div class="module-channels-slider-control">
                <div class="module-channels-slider-row">
                    <input
                        type="range"
                        min="${escapeHtml(String(floor))}"
                        max="${escapeHtml(String(ceiling))}"
                        step="${escapeHtml(String(Number.isFinite(resolvedStep) && resolvedStep > 0 ? resolvedStep : 1))}"
                        value="${escapeHtml(String(safeValue))}"
                        class="module-channels-slider"
                        ${escapeHtml(fieldAttr)}="${escapeHtml(fieldKey)}"
                        data-channels-slider-format="${escapeHtml(resolvedFormat)}"
                        data-channels-slider-suffix="${escapeHtml(suffix)}" />
                    <output class="module-channels-slider-value" data-channels-slider-value>${escapeHtml(moduleChannelsFormatSliderValue(safeValue, resolvedFormat, suffix))}</output>
                </div>
                <div class="module-channels-slider-range">${escapeHtml(`${min} to ${max}${safeString(suffix)}`)}</div>
            </div>
        </label>
    `;
}

function moduleRenderDiscordChannelDetail(model, state) {
    const ttsBackend = safeString(model.config?.voice_tts_backend).toLowerCase() || 'piper';
    const sttBackend = safeString(model.config?.voice_stt_backend).toLowerCase() || 'faster-whisper';
    const sttDevice = safeString(model.config?.voice_stt_device).toLowerCase() || 'cpu';
    const sttComputeType = safeString(model.config?.voice_stt_compute_type).toLowerCase() || 'int8';
    const sttVadFilterEnabled = safeString(model.config?.voice_stt_vad_filter ?? true).toLowerCase() !== 'false';
    const ttsUseCuda = safeString(model.config?.voice_tts_use_cuda ?? false).toLowerCase() === 'true';
    const primaryControlLabel = model.running ? 'Stop Bridge' : 'Start Bridge';
    const primaryControlAction = model.running ? 'stop' : 'start';
    return `
        <section class="module-channels-detail-shell">
            <div class="module-channels-detail-toolbar">
                <button type="button" class="module-channels-btn" data-channels-action="back_to_catalog">Back To All Channels</button>
                <span class="module-channel-card-status" data-channel-status="${escapeHtml(model.statusTone)}">${escapeHtml(model.statusLabel)}</span>
            </div>
            <div class="module-channels-detail-head">
                <div>
                    <span class="module-channels-section-kicker">Channel detail</span>
                    <h3>Discord bridge</h3>
                    <p>Lifecycle, voice behavior, secure configuration, owner-scoped access rules, and indexed conversation lookup all live here on the Thomas side.</p>
                </div>
            </div>
            <div class="module-channels-primary-stack">
                <article class="module-channels-section-card">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Bridge controls</span><h4>Start, stop, and check the live bridge</h4></div><span>${escapeHtml(model.bridge?.pid ? `PID ${model.bridge.pid}` : 'offline')}</span></div>
                    <p class="module-channels-section-copy">Start and stop live from here. Restart reapplies current settings, and the wake probe exercises the real Discord voice path.</p>
                    <div class="module-channels-actions">
                        <button type="button" class="module-channels-btn primary" data-channels-action="${primaryControlAction}">${primaryControlLabel}</button>
                        <button type="button" class="module-channels-btn" data-channels-action="restart">Restart Bridge</button>
                        <button type="button" class="module-channels-btn" data-channels-action="toggle_enabled">${model.enabled ? 'Turn Channel Off' : 'Turn Channel On'}</button>
                        <button type="button" class="module-channels-btn" data-channels-action="voice_probe">${state?.voiceProbeRunning ? 'Running Wake Probe' : 'Run Wake Probe'}</button>
                        <button type="button" class="module-channels-btn" data-channels-action="refresh">Refresh Status</button>
                    </div>
                    <div class="module-channels-stat-grid">
                        <article class="module-channels-stat-card"><span>Bridge state</span><strong>${escapeHtml(model.statusLabel)}</strong><em>${escapeHtml(model.bridge?.pid ? `PID ${model.bridge.pid}` : 'not running')}</em></article>
                        <article class="module-channels-stat-card"><span>Channel</span><strong>${model.enabled ? 'On' : 'Off'}</strong><em>${model.configured ? 'owner-scoped controls active' : 'secure config still required'}</em></article>
                        <article class="module-channels-stat-card"><span>Conversation index</span><strong>${escapeHtml(String(model.indexedTurnCount))}</strong><em>${escapeHtml(String(model.conversations?.indexed_sessions || 0))} indexed sessions</em></article>
                        <article class="module-channels-stat-card"><span>Runtime access</span><strong>${escapeHtml(String(model.runtime?.access_grants_count || 0))}</strong><em>${model.runtime?.voice_require_wake_word ? 'wake word required' : 'wake word optional'}</em></article>
                    </div>
                    <div class="module-channels-meta-grid">
                        <div><span>Last started</span><strong>${escapeHtml(safeString(model.bridge?.last_started_at) ? missionRelativeTime(safeString(model.bridge.last_started_at)) : 'never')}</strong></div>
                        <div><span>Last stopped</span><strong>${escapeHtml(safeString(model.bridge?.last_stopped_at) ? missionRelativeTime(safeString(model.bridge.last_stopped_at)) : 'unknown')}</strong></div>
                        <div><span>Secure config</span><strong>${model.configured ? 'ready' : 'missing values'}</strong></div>
                        <div><span>Wake probe</span><strong>${state?.voiceProbeRunning ? 'running' : 'ready'}</strong></div>
                    </div>
                    ${safeString(model.bridge?.last_error) ? `<div class="module-empty">${escapeHtml(safeString(model.bridge.last_error).slice(0, 320))}</div>` : ''}
                </article>
                <article class="module-channels-section-card">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Conversation access</span><h4>Indexed Discord memory</h4></div><span>${state?.loading ? 'refreshing' : `updated ${escapeHtml(model.lastUpdatedLabel)}`}</span></div>
                    <p class="module-channels-section-copy">This is the live Discord transcript index Thomas can search, reuse, and carry forward. It refreshes while this page is open.</p>
                    <div class="module-channels-searchbar">
                        <input type="search" class="form-control" data-channels-search value="${escapeHtml(model.searchText)}" placeholder="Search Discord history" />
                        <button type="button" class="module-channels-btn" data-channels-action="search">Search</button>
                        <button type="button" class="module-channels-btn" data-channels-action="clear_search">Clear</button>
                    </div>
                    ${moduleChannelsHitMarkup(model)}
                    <div class="module-channels-history-frame">
                        <aside class="module-channels-session-rail">
                            <div class="module-channels-session-rail-head"><strong>Sessions</strong><span>${escapeHtml(String(model.sessions.length))}</span></div>
                            <div class="module-channels-session-list">${moduleChannelsSessionMarkup(model, state)}</div>
                        </aside>
                        <section class="module-channels-transcript-shell">
                            <div class="module-channels-section-header compact"><div><span class="module-channels-section-kicker">Selected session</span><h4>${escapeHtml(safeString(model.selectedMeta?.display_name) || safeString(model.selectedMeta?.session_id) || 'No session selected')}</h4></div><span>${escapeHtml(safeString(model.selectedMeta?.session_id) || 'none')}</span></div>
                            ${moduleChannelsSessionSummaryMarkup(model)}
                            <div class="module-channels-transcript-list">${moduleChannelsTurnMarkup(model)}</div>
                        </section>
                    </div>
                </article>
                ${moduleChannelsProbeResultMarkup(state)}
            </div>
            <div class="module-channels-settings-grid">
                <form class="module-channels-section-card" data-channels-config-form>
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Connect + configure</span><h4>Secure local store</h4></div><span>${escapeHtml(model.secretStorageLabel)}</span></div>
                    <p class="module-channels-section-copy">Discord secrets are stored in Thomas secure local storage and only injected into the managed bridge process when it launches.</p>
                    <div class="module-channels-form-grid">
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Discord bot token', 'The bot token is stored securely and only injected when the Discord bridge launches.')}<input type="password" class="form-control" data-channels-config-field="bot_token" placeholder="${escapeHtml(safeString(model.config?.bot_token_masked) || 'Enter new bot token')}" autocomplete="new-password" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Thomas API token', 'Optional local API token used by the bridge when the Thomas server requires authenticated calls.')}<input type="password" class="form-control" data-channels-config-field="thomas_api_token" placeholder="${escapeHtml(safeString(model.config?.thomas_api_token_masked) || 'Optional server token')}" autocomplete="new-password" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Thomas base URL', 'Where the Discord bridge sends chat requests back into Thomas.')}<input type="text" class="form-control" data-channels-config-field="thomas_base_url" value="${escapeHtml(safeString(model.config?.thomas_base_url) || 'http://127.0.0.1:8899')}" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Session prefix', 'The prefix Thomas uses when it creates Discord-owned chat session IDs.')}<input type="text" class="form-control" data-channels-config-field="session_prefix" value="${escapeHtml(safeString(model.config?.session_prefix) || 'thomas-discord')}" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Primary guild ID', 'The main Discord server this bridge should treat as the default home guild.')}<input type="text" class="form-control" data-channels-config-field="guild_id" value="${escapeHtml(safeString(model.config?.guild_id) || '')}" /></label>
                    </div>
                    <div class="module-channels-actions compact"><button type="button" class="module-channels-btn primary" data-channels-action="save_config">Save Configuration</button></div>
                </form>
                <article class="module-channels-section-card">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Access + safety</span><h4>Owner-scoped permissions</h4></div><span>${model.config?.owner_only_mode ? 'owner only' : 'delegated access enabled'}</span></div>
                    <p class="module-channels-section-copy">Keep settings and machine-side actions owner scoped. Delegated access should stay narrow and channel-appropriate.</p>
                    <div class="module-channels-form-grid">
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Owner user IDs', 'Only these Discord user IDs can change bridge settings or use owner-only controls from Discord.')}<input type="text" class="form-control" data-channels-config-field="owner_user_ids" value="${escapeHtml((Array.isArray(model.config?.owner_user_ids) ? model.config.owner_user_ids.join(', ') : ''))}" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Allowed guild IDs', 'Limit the bridge to these server IDs so it cannot answer in unexpected servers.')}<input type="text" class="form-control" data-channels-config-field="allowed_guild_ids" value="${escapeHtml((Array.isArray(model.config?.allowed_guild_ids) ? model.config.allowed_guild_ids.join(', ') : ''))}" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Auto channel IDs', 'Channels Thomas can answer in automatically without extra per-channel wiring.')}<input type="text" class="form-control" data-channels-config-field="auto_channel_ids" value="${escapeHtml((Array.isArray(model.config?.auto_channel_ids) ? model.config.auto_channel_ids.join(', ') : ''))}" /></label>
                    </div>
                    <div class="module-channels-checks">
                        <label class="module-channels-check"><input type="checkbox" data-channels-config-field="owner_only_mode" ${model.config?.owner_only_mode ? 'checked' : ''} /><span>Owner-only mode</span></label>
                        <label class="module-channels-check"><input type="checkbox" data-channels-config-field="require_mention" ${model.config?.require_mention !== false ? 'checked' : ''} /><span>Require mention</span></label>
                    </div>
                    <div class="module-channels-meta-grid">
                        <div><span>Wake word</span><strong>${model.runtime?.voice_require_wake_word ? 'Required' : 'Optional'}</strong></div>
                        <div><span>Voice profile</span><strong>${escapeHtml(safeString(model.runtime?.voice_profile) || 'unknown')}</strong></div>
                        <div><span>Media volume</span><strong>${escapeHtml(String(model.runtime?.voice_media_volume || 0))}%</strong></div>
                        <div><span>Delegated grants</span><strong>${escapeHtml(String(model.runtime?.access_grants_count || 0))}</strong></div>
                    </div>
                    <div class="module-channels-actions compact"><button type="button" class="module-channels-btn" data-channels-action="save_config">Save Access Rules</button></div>
                </article>
                <article class="module-channels-section-card module-channels-section-card-wide">
                    <div class="module-channels-section-header"><div><span class="module-channels-section-kicker">Voice + speech</span><h4>Discord-specific runtime</h4></div><span>${escapeHtml(safeString(model.runtime?.voice_profile) || safeString(model.config?.voice_tts_backend) || 'voice unset')}</span></div>
                    <p class="module-channels-section-copy">Change the Discord voice profile, wake-word behavior, latency caps, TTS backend, media volume, and speech-to-text settings here. Thomas will reapply the bridge if it is already running.</p>
                    <div class="module-channels-form-grid">
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('TTS backend', 'Pick the speech synthesizer Discord should use for spoken replies.')}<select class="form-control" data-channels-voice-config-field="voice_tts_backend"><option value="piper"${ttsBackend === 'piper' ? ' selected' : ''}>piper</option><option value="openai"${ttsBackend === 'openai' ? ' selected' : ''}>openai</option><option value="windows"${ttsBackend === 'windows' ? ' selected' : ''}>windows</option></select></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('TTS model', 'This is the local or cloud voice model identifier the selected TTS backend should load.')}<input type="text" class="form-control" data-channels-voice-config-field="voice_tts_model" value="${escapeHtml(safeString(model.config?.voice_tts_model) || '')}" placeholder="${escapeHtml(ttsBackend === 'openai' ? 'gpt-4o-mini-tts' : 'en_US-ryan-high')}" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Cloud voice', 'When the TTS backend is cloud-based, this selects the voice preset Thomas should use.')}<input type="text" class="form-control" data-channels-voice-config-field="voice_cloud_voice" value="${escapeHtml(safeString(model.config?.voice_cloud_voice) || '')}" placeholder="alloy" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Voice profile', 'The active local voice profile Thomas should speak with in Discord.')}<input type="text" class="form-control" data-channels-runtime-field="voice_profile" value="${escapeHtml(safeString(model.runtime?.voice_profile) || '')}" placeholder="en_US-ryan-high" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Preferred voice channel', 'Thomas joins this voice channel name by default when auto-join behavior is enabled.')}<input type="text" class="form-control" data-channels-voice-config-field="default_voice_channel_name" value="${escapeHtml(safeString(model.config?.default_voice_channel_name) || '')}" placeholder="Music" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Wake words', 'These are the phrases Thomas listens for when wake-word mode is on.')}<input type="text" class="form-control" data-channels-runtime-field="voice_wake_words" value="${escapeHtml((Array.isArray(model.runtime?.voice_wake_words) ? model.runtime.voice_wake_words.join(', ') : ''))}" placeholder="thomas, hey thomas" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('STT backend', 'Choose the speech-to-text engine Thomas uses to hear Discord voice input.')}<select class="form-control" data-channels-voice-config-field="voice_stt_backend"><option value="faster-whisper"${sttBackend === 'faster-whisper' ? ' selected' : ''}>faster-whisper</option><option value="openai"${sttBackend === 'openai' ? ' selected' : ''}>openai</option><option value="windows"${sttBackend === 'windows' ? ' selected' : ''}>windows</option></select></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('STT model', 'The recognition model Thomas should load for Discord voice transcription.')}<input type="text" class="form-control" data-channels-voice-config-field="voice_stt_model" value="${escapeHtml(safeString(model.config?.voice_stt_model) || '')}" placeholder="${escapeHtml(sttBackend === 'openai' ? 'gpt-4o-transcribe' : 'distil-large-v3')}" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('STT device', 'Pick the compute device for speech recognition. CUDA is fastest when the GPU runtime is available.')}<select class="form-control" data-channels-voice-config-field="voice_stt_device"><option value="cpu"${sttDevice === 'cpu' ? ' selected' : ''}>cpu</option><option value="cuda"${sttDevice === 'cuda' ? ' selected' : ''}>cuda</option></select></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('Compute type', 'Lower-precision compute is usually faster, while higher precision can trade speed for accuracy. Mixed int8/float16 is a strong CUDA option when you want higher throughput without dropping back to CPU.')}<select class="form-control" data-channels-voice-config-field="voice_stt_compute_type"><option value="int8"${sttComputeType === 'int8' ? ' selected' : ''}>int8</option><option value="int8_float16"${sttComputeType === 'int8_float16' ? ' selected' : ''}>int8_float16</option><option value="float16"${sttComputeType === 'float16' ? ' selected' : ''}>float16</option><option value="float32"${sttComputeType === 'float32' ? ' selected' : ''}>float32</option></select></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('STT language', 'Force a preferred recognition language when you want Thomas to stop auto-detecting.')}<input type="text" class="form-control" data-channels-voice-config-field="voice_stt_language" value="${escapeHtml(safeString(model.config?.voice_stt_language) || '')}" placeholder="en" /></label>
                        <label class="module-channels-field">${moduleChannelsFieldLabelMarkup('STT hint phrases', 'Comma-separated words to bias recognition toward names, commands, and terms you say often.')}<input type="text" class="form-control" data-channels-voice-config-field="voice_stt_hint_phrases" value="${escapeHtml((Array.isArray(model.config?.voice_stt_hint_phrases) ? model.config.voice_stt_hint_phrases.join(', ') : ''))}" placeholder="music, soundboard, hey thomas" /></label>
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_silence_ms', label: 'End-of-speech ms', description: 'Moving right makes Thomas wait longer for silence before treating your sentence as finished. Moving left makes turn-taking faster but can clip pauses.', value: Number(model.config?.voice_silence_ms ?? 700), min: 200, max: 5000, step: 50, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_min_speech_ms', label: 'Minimum speech ms', description: 'Moving right requires longer speech before Thomas treats a capture as real voice. Moving left makes him more responsive to short bursts but more sensitive to noise.', value: Number(model.config?.voice_min_speech_ms ?? 400), min: 100, max: 10000, step: 50, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_max_speech_ms', label: 'Max listen ms', description: 'Moving right lets Thomas listen longer before forcing a cutoff. Moving left makes replies start faster but can interrupt long requests.', value: Number(model.config?.voice_max_speech_ms ?? 20000), min: 1000, max: 120000, step: 500, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_wake_capture_ms', label: 'Wake capture max ms', description: 'When wake-word mode is on, moving right gives Thomas more time after the wake phrase. Moving left keeps wake interactions snappier.', value: Number(model.config?.voice_wake_capture_ms ?? 6500), min: 500, max: 30000, step: 250, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_no_wake_cooldown_ms', label: 'Missed-wake cooldown ms', description: 'Moving right makes Thomas back off longer after hearing speech without a wake phrase. Moving left makes him recover faster between missed wake attempts.', value: Number(model.config?.voice_no_wake_cooldown_ms ?? 8000), min: 0, max: 60000, step: 250, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_max_reply_chars', label: 'Max reply chars', description: 'Moving right lets Thomas speak longer answers. Moving left keeps responses shorter and faster.', value: Number(model.config?.voice_max_reply_chars ?? 320), min: 40, max: 600, step: 10 })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-runtime-field', fieldKey: 'voice_media_volume', label: 'Media volume', description: 'Moving right makes Thomas and media playback louder in Discord. Moving left reduces output volume.', value: Number(model.runtime?.voice_media_volume ?? 100), min: 0, max: 200, step: 5, suffix: '%' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_stt_beam_size', label: 'Beam size', description: 'Moving right can improve recognition quality by exploring more transcript candidates, but it increases latency. Moving left is faster.', value: Number(model.config?.voice_stt_beam_size ?? 5), min: 1, max: 10, step: 1 })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_stt_vad_min_silence_ms', label: 'VAD min silence ms', description: 'Moving right makes the detector wait for longer quiet gaps before ending a capture. Moving left ends turns sooner.', value: Number(model.config?.voice_stt_vad_min_silence_ms ?? 500), min: 100, max: 5000, step: 50, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_tts_sentence_pause_ms', label: 'Piper pause ms', description: 'Moving right adds more silence between spoken sentences. Moving left makes Thomas sound quicker and more tightly paced.', value: Number(model.config?.voice_tts_sentence_pause_ms ?? 140), min: 0, max: 1000, step: 10, suffix: ' ms' })}
                        ${moduleChannelsSliderField({ fieldAttr: 'data-channels-voice-config-field', fieldKey: 'voice_tts_length_scale', label: 'Piper speed scale', description: 'Moving right slows the voice down. Moving left speeds it up. Around 1.0 is neutral.', value: Number(model.config?.voice_tts_length_scale ?? 1), min: 0.5, max: 1.5, step: 0.05, format: 'float2' })}
                        <label class="module-channels-field module-channels-field-wide">${moduleChannelsFieldLabelMarkup('STT prompt', 'Extra transcription guidance Thomas should prepend when speech recognition needs more context about names or command vocabulary.')}<textarea class="form-control" rows="3" data-channels-voice-config-field="voice_stt_prompt" placeholder="Tell STT what names or Discord commands matter most.">${escapeHtml(safeString(model.config?.voice_stt_prompt) || '')}</textarea></label>
                    </div>
                    <div class="module-channels-checks">
                        <label class="module-channels-check"><input type="checkbox" data-channels-runtime-field="voice_require_wake_word" ${model.runtime?.voice_require_wake_word ? 'checked' : ''} /><span>Require wake phrase before voice actions</span></label>
                        <label class="module-channels-check"><input type="checkbox" data-channels-voice-config-field="voice_tts_use_cuda" ${ttsUseCuda ? 'checked' : ''} /><span>Use CUDA for local TTS when available</span></label>
                        <label class="module-channels-check"><input type="checkbox" data-channels-voice-config-field="voice_stt_vad_filter" ${sttVadFilterEnabled ? 'checked' : ''} /><span>Enable STT VAD filter</span></label>
                    </div>
                    <div class="module-channels-actions compact"><button type="button" class="module-channels-btn primary" data-channels-action="save_voice_settings">Save Voice + Speech</button></div>
                </article>
            </div>
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
        <section class="module-channels-shell">
            ${detailMarkup}
            ${safeString(state?.error) ? `<div class="module-empty">${escapeHtml(state.error)}</div>` : ''}
        </section>
    ` : `
        <section class="module-channels-shell">
            <section class="module-channels-catalog">
                <div>
                    <span class="module-channels-section-kicker">Channels workspace</span>
                    <h3>All channels</h3>
                    <p>Drag channels into the order you want, then open one to manage it.</p>
                </div>
                <div class="module-channels-section-header">
                    <div>
                        <span class="module-channels-section-kicker">Channel catalog</span>
                        <h4>${escapeHtml(String(model.catalog.length))} channel slots ready</h4>
                    </div>
                    <span>${state?.loading ? 'refreshing' : `updated ${escapeHtml(model.lastUpdatedLabel)}`}</span>
                </div>
                <div class="module-channels-grid" data-channel-grid>
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
            moduleRenderMarketplaceSurface(moduleQueueList);
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
