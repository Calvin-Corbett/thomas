
    // State and Helpers
    const PREFERENCES_API = '/api/preferences';
    const DESKTOP_STATUS_API = '/api/onboarding/desktop/status';
    const DESKTOP_INSTALL_API = '/api/onboarding/desktop/install';
    const DESKTOP_TRUST_API = '/api/onboarding/desktop/trust';
    const DESKTOP_VM_SOURCE_API = '/api/onboarding/desktop/vm-source';
    const DESKTOP_VIEWER_API = '/api/onboarding/desktop/open-viewer';
    const settings = {};
    let currentSection = 'general';
    let pendingConfirmAction = null;
    let isolatedDesktopState = null;

    function defaultLegacySettings() {
      return {
        agentName: 'Thomas-Main',
        defaultModel: 'claude-opus',
        defaultProvider: 'anthropic',
        theme: 'dark',
        language: 'en',
        workflowMode: 'guided',
        startupBehavior: false,
        openaiKey: '',
        openaiModel: 'gpt-4',
        anthropicKey: '',
        anthropicModel: 'claude-opus',
        googleKey: '',
        googleModel: 'gemini-pro',
        ollamaUrl: 'http://localhost:11434',
        ollamaModel: 'llama2',
        temperature: 0.7,
        maxTokens: 2000,
        slackWebhook: '',
        autonomyLevel: 'L2',
        costLimit: 1,
        timeCommitment: 4,
        autoApproveNotify: false,
        idleTimeout: 30,
        initiativeOnErrors: true,
        toolPermissions: {
          allowShell: false,
          allowBrowser: false,
          allowGit: false,
          allowFilesystem: true,
          allowWebSearch: true,
          allowEmail: false,
          allowDatabase: false,
          allowSSH: false,
        },
        dataRetention: '90d',
        autoDeleteSensitive: true,
        sessionEncryption: true,
        rateLimit: 100,
        allowedDomains: [],
        fontSize: 'normal',
        sidebarPosition: 'left',
        compactMode: false,
        bubbleStyle: 'rounded',
        monospaceCode: true,
        desktopNotifications: true,
        soundAlerts: false,
        debugMode: false,
        logLevel: 'info',
        pluginDirectory: '',
        autoLoadPlugins: true,
        toolPaths: [],
        dbConnection: '',
        poolSize: 10,
      };
    }

    function toUiTheme(theme) {
      return theme === 'auto' ? 'system' : (theme || 'dark');
    }

    function toApiTheme(theme) {
      return theme === 'system' ? 'auto' : (theme || 'dark');
    }

    function toUiFontSize(fontSize) {
      const px = Number(fontSize);
      if (!Number.isFinite(px)) return 'normal';
      if (px <= 14) return 'small';
      if (px >= 22) return 'xlarge';
      if (px >= 18) return 'large';
      return 'normal';
    }

    function toApiFontSize(fontSize) {
      switch (String(fontSize || 'normal')) {
        case 'small':
          return 14;
        case 'large':
          return 18;
        case 'xlarge':
          return 22;
        default:
          return 16;
      }
    }

    function toUiBubbleStyle(style) {
      return style === 'compact' ? 'minimal' : (style || 'rounded');
    }

    function toApiBubbleStyle(style) {
      return style === 'minimal' ? 'compact' : (style || 'rounded');
    }

    function toUiRetention(retentionDays) {
      const days = Number(retentionDays);
      if (!Number.isFinite(days)) return '90d';
      if (days >= 3650) return 'forever';
      if (days >= 365) return '1y';
      if (days >= 90) return '90d';
      if (days >= 30) return '30d';
      return '7d';
    }

    function toApiRetention(retention) {
      switch (String(retention || '90d')) {
        case '7d':
          return 7;
        case '30d':
          return 30;
        case '1y':
          return 365;
        case 'forever':
          return 3650;
        default:
          return 90;
      }
    }

    function toUiProvider(activeProfile) {
      const raw = String(activeProfile || '').toLowerCase();
      if (raw.includes('openai')) return 'openai';
      if (raw.includes('google')) return 'google';
      if (raw.includes('ollama') || raw.includes('local')) return 'ollama';
      if (raw.includes('anthropic')) return 'anthropic';
      return raw || 'anthropic';
    }

    function isMaskedSecret(value) {
      return typeof value === 'string' && /[\u2022]/.test(value);
    }

    function toNumber(value, fallback) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function toInteger(value, fallback) {
      const parsed = parseInt(value, 10);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function buildLegacySettings(preferences) {
      const defaults = defaultLegacySettings();
      const storedLegacy = preferences && preferences.thomads && typeof preferences.thomads.legacy_settings === 'object'
        ? preferences.thomads.legacy_settings
        : {};
      const storedToolPermissions = storedLegacy.toolPermissions && typeof storedLegacy.toolPermissions === 'object'
        ? storedLegacy.toolPermissions
        : {};
      const advanced = preferences && preferences.advanced ? preferences.advanced : {};
      const model = advanced.model || {};
      const tools = advanced.tools || {};
      const privacy = advanced.privacy || {};
      const iface = advanced.interface || {};

      return {
        ...defaults,
        ...storedLegacy,
        agentName: (preferences && preferences.profile && preferences.profile.display_name) || storedLegacy.agentName || defaults.agentName,
        defaultModel: model.model_id || storedLegacy.defaultModel || defaults.defaultModel,
        defaultProvider: toUiProvider(model.active_profile || storedLegacy.defaultProvider || defaults.defaultProvider),
        theme: toUiTheme((preferences && preferences.appearance && preferences.appearance.theme) || storedLegacy.theme || defaults.theme),
        workflowMode: (preferences && preferences.advanced && preferences.advanced.interface && preferences.advanced.interface.workflow_mode) || storedLegacy.workflowMode || defaults.workflowMode,
        openaiKey: preferences && preferences.api_keys ? (preferences.api_keys.openai ?? storedLegacy.openaiKey ?? defaults.openaiKey) : (storedLegacy.openaiKey ?? defaults.openaiKey),
        anthropicKey: preferences && preferences.api_keys ? (preferences.api_keys.anthropic ?? storedLegacy.anthropicKey ?? defaults.anthropicKey) : (storedLegacy.anthropicKey ?? defaults.anthropicKey),
        googleKey: preferences && preferences.api_keys ? (preferences.api_keys.google ?? storedLegacy.googleKey ?? defaults.googleKey) : (storedLegacy.googleKey ?? defaults.googleKey),
        temperature: model.temperature ?? storedLegacy.temperature ?? defaults.temperature,
        maxTokens: model.max_output_tokens ?? storedLegacy.maxTokens ?? defaults.maxTokens,
        autonomyLevel: (preferences && preferences.autonomy && preferences.autonomy.default_level) || storedLegacy.autonomyLevel || defaults.autonomyLevel,
        toolPermissions: {
          ...defaults.toolPermissions,
          ...storedToolPermissions,
          allowShell: tools.allow_shell ?? storedToolPermissions.allowShell ?? defaults.toolPermissions.allowShell,
          allowBrowser: tools.allow_browser ?? storedToolPermissions.allowBrowser ?? defaults.toolPermissions.allowBrowser,
          allowGit: tools.allow_git ?? storedToolPermissions.allowGit ?? defaults.toolPermissions.allowGit,
          allowFilesystem: tools.allow_file_write ?? storedToolPermissions.allowFilesystem ?? defaults.toolPermissions.allowFilesystem,
          allowWebSearch: tools.allow_network ?? storedToolPermissions.allowWebSearch ?? defaults.toolPermissions.allowWebSearch,
        },
        dataRetention: toUiRetention(privacy.retention_days ?? toApiRetention(storedLegacy.dataRetention || defaults.dataRetention)),
        autoDeleteSensitive: privacy.redact_secrets_in_logs ?? storedLegacy.autoDeleteSensitive ?? defaults.autoDeleteSensitive,
        fontSize: toUiFontSize((preferences && preferences.appearance && preferences.appearance.font_size) ?? toApiFontSize(storedLegacy.fontSize || defaults.fontSize)),
        bubbleStyle: toUiBubbleStyle((preferences && preferences.appearance && preferences.appearance.bubble_style) || storedLegacy.bubbleStyle || defaults.bubbleStyle),
        compactMode: iface.ui_density ? iface.ui_density !== 'comfortable' : (storedLegacy.compactMode ?? defaults.compactMode),
        desktopNotifications: (preferences && preferences.notifications && preferences.notifications.desktop) ?? storedLegacy.desktopNotifications ?? defaults.desktopNotifications,
        debugMode: iface.debug_panel_enabled ?? storedLegacy.debugMode ?? defaults.debugMode,
        __legacySettings: {
          ...defaults,
          ...storedLegacy,
          toolPermissions: {
            ...defaults.toolPermissions,
            ...storedToolPermissions,
          },
        },
      };
    }

    function buildPreferencesPatch(sectionData) {
      const defaults = defaultLegacySettings();
      const currentLegacy = settings.__legacySettings && typeof settings.__legacySettings === 'object'
        ? settings.__legacySettings
        : defaults;
      const nextToolPermissions = sectionData.toolPermissions && typeof sectionData.toolPermissions === 'object'
        ? sectionData.toolPermissions
        : {};
      const mergedLegacy = {
        ...defaults,
        ...currentLegacy,
        ...sectionData,
        toolPermissions: {
          ...defaults.toolPermissions,
          ...(currentLegacy.toolPermissions || {}),
          ...nextToolPermissions,
        },
      };

      const patch = {
        profile: {
          display_name: String(mergedLegacy.agentName || defaults.agentName).trim(),
        },
        appearance: {
          theme: toApiTheme(mergedLegacy.theme),
          font_size: toApiFontSize(mergedLegacy.fontSize),
          bubble_style: toApiBubbleStyle(mergedLegacy.bubbleStyle),
        },
        notifications: {
          desktop: !!mergedLegacy.desktopNotifications,
        },
        autonomy: {
          default_level: mergedLegacy.autonomyLevel || defaults.autonomyLevel,
        },
        advanced: {
          model: {
            active_profile: mergedLegacy.defaultProvider || defaults.defaultProvider,
            model_id: mergedLegacy.defaultModel || defaults.defaultModel,
            temperature: toNumber(mergedLegacy.temperature, defaults.temperature),
            max_output_tokens: toInteger(mergedLegacy.maxTokens, defaults.maxTokens),
          },
          tools: {
            allow_shell: !!mergedLegacy.toolPermissions.allowShell,
            allow_browser: !!mergedLegacy.toolPermissions.allowBrowser,
            allow_git: !!mergedLegacy.toolPermissions.allowGit,
            allow_file_write: mergedLegacy.toolPermissions.allowFilesystem !== false,
            allow_network: mergedLegacy.toolPermissions.allowWebSearch !== false,
          },
          privacy: {
            retention_days: toApiRetention(mergedLegacy.dataRetention),
            redact_secrets_in_logs: mergedLegacy.autoDeleteSensitive !== false,
          },
          interface: {
            ui_density: mergedLegacy.compactMode ? 'compact' : 'comfortable',
            debug_panel_enabled: !!mergedLegacy.debugMode,
            workflow_mode: mergedLegacy.workflowMode || defaults.workflowMode,
          },
        },
        thomads: {
          legacy_settings: mergedLegacy,
        },
      };

      const apiKeys = {};
      [
        ['openaiKey', 'openai'],
        ['anthropicKey', 'anthropic'],
        ['googleKey', 'google'],
      ].forEach(([field, provider]) => {
        const value = mergedLegacy[field];
        if (isMaskedSecret(value)) return;
        apiKeys[provider] = value && String(value).trim() ? String(value).trim() : null;
      });
      if (Object.keys(apiKeys).length) {
        patch.api_keys = apiKeys;
      }

      return patch;
    }

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', async () => {
      await loadSettings();
      setupEventListeners();
      setupSearch();
    });

    // Load settings from API
    async function loadSettings() {
      try {
        const response = await fetch(PREFERENCES_API);
        if (!response.ok) throw new Error('Failed to load settings');
        const data = await response.json();
        Object.assign(settings, buildLegacySettings(data));
        populateForm();
        await refreshIsolatedDesktopStatus();
      } catch (error) {
        console.error('Error loading settings:', error);
        Object.assign(settings, buildLegacySettings({}));
        populateForm();
        await refreshIsolatedDesktopStatus();
        showToast('Failed to load settings', 'error');
      }
    }

    // Populate form with loaded settings
    function populateForm() {
      // General
      setInputValue('agentName', settings.agentName || 'Thomas-Main');
      setSelectValue('defaultModel', settings.defaultModel || 'claude-opus');
      setSelectValue('defaultProvider', settings.defaultProvider || 'anthropic');
      setSelectValue('theme', settings.theme || 'dark');
      setSelectValue('language', settings.language || 'en');
      setSelectValue('workflowMode', settings.workflowMode || 'guided');
      setToggle('startupBehavior', settings.startupBehavior);

      // Models
      setInputValue('openaiKey', settings.openaiKey || '');
      setSelectValue('openaiModel', settings.openaiModel || 'gpt-4');
      setInputValue('anthropicKey', settings.anthropicKey || '');
      setSelectValue('anthropicModel', settings.anthropicModel || 'claude-opus');
      setInputValue('googleKey', settings.googleKey || '');
      setSelectValue('googleModel', settings.googleModel || 'gemini-pro');
      setInputValue('ollamaUrl', settings.ollamaUrl || 'http://localhost:11434');
      setInputValue('ollamaModel', settings.ollamaModel || 'llama2');
      setInputValue('temperature', settings.temperature || 0.7);
      setInputValue('maxTokens', settings.maxTokens || 2000);

      // Integrations (status handled by separate check)
      setInputValue('slackWebhook', settings.slackWebhook || '');

      // Autonomy
      setSelectValue('autonomyLevel', settings.autonomyLevel || 'L2');
      setInputValue('costLimit', settings.costLimit || 1.00);
      setInputValue('timeCommitment', settings.timeCommitment || 4);
      setToggle('autoApproveNotify', settings.autoApproveNotify);
      setInputValue('idleTimeout', settings.idleTimeout || 30);
      setToggle('initiativeOnErrors', settings.initiativeOnErrors !== false);

      // Tool Permissions
      const tp = settings.toolPermissions || {};
      setToggle('allowShell', tp.allowShell);
      setToggle('allowBrowser', tp.allowBrowser);
      setToggle('allowGit', tp.allowGit);
      setToggle('allowFilesystem', tp.allowFilesystem !== false);
      setToggle('allowWebSearch', tp.allowWebSearch !== false);
      setToggle('allowEmail', tp.allowEmail);
      setToggle('allowDatabase', tp.allowDatabase);
      setToggle('allowSSH', tp.allowSSH);

      // Privacy
      setSelectValue('dataRetention', settings.dataRetention || '90d');
      setToggle('autoDeleteSensitive', settings.autoDeleteSensitive !== false);
      setToggle('sessionEncryption', settings.sessionEncryption !== false);
      setInputValue('rateLimit', settings.rateLimit || 100);
      setInputValue('allowedDomains', (settings.allowedDomains || []).join('\n'));

      // Appearance
      setSelectValue('fontSize', settings.fontSize || 'normal');
      setSelectValue('sidebarPosition', settings.sidebarPosition || 'left');
      setToggle('compactMode', settings.compactMode);
      setSelectValue('bubbleStyle', settings.bubbleStyle || 'rounded');
      setToggle('monospaceCode', settings.monospaceCode !== false);
      setToggle('desktopNotifications', settings.desktopNotifications !== false);
      setToggle('soundAlerts', settings.soundAlerts);

      // Advanced
      setToggle('debugMode', settings.debugMode);
      setSelectValue('logLevel', settings.logLevel || 'info');
      setInputValue('pluginDirectory', settings.pluginDirectory || '');
      setToggle('autoLoadPlugins', settings.autoLoadPlugins !== false);
      setInputValue('toolPaths', (settings.toolPaths || []).join('\n'));
      setInputValue('dbConnection', settings.dbConnection || '');
      setInputValue('poolSize', settings.poolSize || 10);
    }

    // Helper functions
    function setInputValue(id, value) {
      const el = document.getElementById(id);
      if (el) el.value = value;
    }

    function setSelectValue(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      const nextValue = String(value ?? '');
      const hasOption = Array.from(el.options || []).some(option => option.value === nextValue);
      if (hasOption) {
        el.value = nextValue;
      }
    }

    function setToggle(id, checked) {
      const el = document.getElementById(id);
      if (el) {
        const isOn = !!checked;
        el.classList.toggle('on', isOn);
        el.setAttribute('aria-checked', isOn);
      }
    }

    // Setup event listeners
    function setupEventListeners() {
      // Sidebar navigation
      document.querySelectorAll('.sidebar-nav-item').forEach(btn => {
        btn.addEventListener('click', () => switchSection(btn.dataset.section));
      });

      // Toggle switches
      document.querySelectorAll('.toggle-switch').forEach(btn => {
        btn.addEventListener('click', () => {
          btn.classList.toggle('on');
          const isOn = btn.classList.contains('on');
          btn.setAttribute('aria-checked', isOn);
        });
        btn.addEventListener('keydown', (e) => {
          if (e.code === 'Space' || e.code === 'Enter') {
            e.preventDefault();
            btn.click();
          }
        });
      });

      // Escape to close modal
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
      });
    }

    // Setup search functionality
    function setupSearch() {
      const searchInput = document.getElementById('searchInput');
      searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        if (!query) return;

        // Find matching settings and switch to relevant section
        const sections = {
          'isolated desktop': 'advanced',
          'desktop mode': 'advanced',
          'vm': 'advanced',
          'agent name': 'general',
          'theme': 'general',
          'language': 'general',
          'startup': 'general',
          'api key': 'models',
          'openai': 'models',
          'anthropic': 'models',
          'google': 'models',
          'ollama': 'models',
          'temperature': 'models',
          'tokens': 'models',
          'integration': 'integrations',
          'slack': 'integrations',
          'notion': 'integrations',
          'workspace': 'integrations',
          'autonomy': 'autonomy',
          'approval': 'autonomy',
          'idle': 'autonomy',
          'privacy': 'privacy',
          'security': 'privacy',
          'retention': 'privacy',
          'encryption': 'privacy',
          'domain': 'privacy',
          'appearance': 'appearance',
          'font': 'appearance',
          'sidebar': 'appearance',
          'bubble': 'appearance',
          'notification': 'appearance',
          'debug': 'advanced',
          'plugin': 'advanced',
          'database': 'advanced',
          'log': 'advanced',
        };

        for (const [term, section] of Object.entries(sections)) {
          if (query.includes(term)) {
            switchSection(section);
            searchInput.blur();
            break;
          }
        }
      });
    }

    // Switch sections
    function switchSection(section) {
      currentSection = section;

      // Update active panel
      document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
      document.getElementById(section).classList.add('active');

      // Update active nav button
      document.querySelectorAll('.sidebar-nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.section === section);
        btn.setAttribute('aria-current', btn.dataset.section === section ? 'page' : 'false');
      });

      // Scroll to top of content
      document.querySelector('.settings-content').scrollTop = 0;
    }

    // Save section
    async function saveSection(section) {
      const formData = gatherFormData(section);
      try {
        const response = await fetch(PREFERENCES_API, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildPreferencesPatch(formData)),
        });

        if (!response.ok) throw new Error('Failed to save settings');
        const data = await response.json();
        Object.assign(settings, buildLegacySettings(data));
        populateForm();
        await refreshIsolatedDesktopStatus();
        showToast('Settings saved successfully', 'success');
      } catch (error) {
        console.error('Error saving settings:', error);
        showToast('Failed to save settings', 'error');
      }
    }

    // Reset section
    function resetSection(section) {
      if (confirm('Reset all settings in this section to defaults?')) {
        populateForm();
        showToast('Settings reset to defaults', 'info');
      }
    }

    // Gather form data from section
    function gatherFormData(section) {
      const data = {};

      switch (section) {
        case 'general':
          data.agentName = document.getElementById('agentName').value;
          data.defaultModel = document.getElementById('defaultModel').value;
          data.defaultProvider = document.getElementById('defaultProvider').value;
          data.theme = document.getElementById('theme').value;
          data.language = document.getElementById('language').value;
          data.workflowMode = document.getElementById('workflowMode').value;
          data.startupBehavior = document.getElementById('startupBehavior').classList.contains('on');
          break;

        case 'models':
          data.openaiKey = document.getElementById('openaiKey').value;
          data.openaiModel = document.getElementById('openaiModel').value;
          data.anthropicKey = document.getElementById('anthropicKey').value;
          data.anthropicModel = document.getElementById('anthropicModel').value;
          data.googleKey = document.getElementById('googleKey').value;
          data.googleModel = document.getElementById('googleModel').value;
          data.ollamaUrl = document.getElementById('ollamaUrl').value;
          data.ollamaModel = document.getElementById('ollamaModel').value;
          data.temperature = parseFloat(document.getElementById('temperature').value);
          data.maxTokens = parseInt(document.getElementById('maxTokens').value);
          break;

        case 'integrations':
          data.slackWebhook = document.getElementById('slackWebhook').value;
          break;

        case 'autonomy':
          data.autonomyLevel = document.getElementById('autonomyLevel').value;
          data.costLimit = parseFloat(document.getElementById('costLimit').value);
          data.timeCommitment = parseFloat(document.getElementById('timeCommitment').value);
          data.autoApproveNotify = document.getElementById('autoApproveNotify').classList.contains('on');
          data.idleTimeout = parseInt(document.getElementById('idleTimeout').value);
          data.initiativeOnErrors = document.getElementById('initiativeOnErrors').classList.contains('on');
          data.toolPermissions = {
            allowShell: document.getElementById('allowShell').classList.contains('on'),
            allowBrowser: document.getElementById('allowBrowser').classList.contains('on'),
            allowGit: document.getElementById('allowGit').classList.contains('on'),
            allowFilesystem: document.getElementById('allowFilesystem').classList.contains('on'),
            allowWebSearch: document.getElementById('allowWebSearch').classList.contains('on'),
            allowEmail: document.getElementById('allowEmail').classList.contains('on'),
            allowDatabase: document.getElementById('allowDatabase').classList.contains('on'),
            allowSSH: document.getElementById('allowSSH').classList.contains('on'),
          };
          break;

        case 'privacy':
          data.dataRetention = document.getElementById('dataRetention').value;
          data.autoDeleteSensitive = document.getElementById('autoDeleteSensitive').classList.contains('on');
          data.sessionEncryption = document.getElementById('sessionEncryption').classList.contains('on');
          data.rateLimit = parseInt(document.getElementById('rateLimit').value);
          data.allowedDomains = document.getElementById('allowedDomains').value.split('\n').filter(d => d.trim());
          break;

        case 'appearance':
          data.fontSize = document.getElementById('fontSize').value;
          data.sidebarPosition = document.getElementById('sidebarPosition').value;
          data.compactMode = document.getElementById('compactMode').classList.contains('on');
          data.bubbleStyle = document.getElementById('bubbleStyle').value;
          data.monospaceCode = document.getElementById('monospaceCode').classList.contains('on');
          data.desktopNotifications = document.getElementById('desktopNotifications').classList.contains('on');
          data.soundAlerts = document.getElementById('soundAlerts').classList.contains('on');
          break;

        case 'advanced':
          data.debugMode = document.getElementById('debugMode').classList.contains('on');
          data.logLevel = document.getElementById('logLevel').value;
          data.pluginDirectory = document.getElementById('pluginDirectory').value;
          data.autoLoadPlugins = document.getElementById('autoLoadPlugins').classList.contains('on');
          data.toolPaths = document.getElementById('toolPaths').value.split('\n').filter(p => p.trim());
          data.dbConnection = document.getElementById('dbConnection').value;
          data.poolSize = parseInt(document.getElementById('poolSize').value);
          break;
      }

      return data;
    }

    // Toggle key visibility
    function toggleKeyVisibility(button) {
      const input = button.previousElementSibling;
      const isPassword = input.type === 'password';
      input.type = isPassword ? 'text' : 'password';
      button.innerHTML = isPassword ? '<i class="ph ph-eye-slash"></i>' : '<i class="ph ph-eye"></i>';
      button.setAttribute('aria-label', isPassword ? 'Hide key' : 'Show key');
    }

    // Integration connections (mock implementations)
    function connectGoogleWorkspace() {
      showToast('Opening Google OAuth consent screen...', 'info');
      // In production, redirect to OAuth endpoint
      setTimeout(() => {
        document.getElementById('googleWorkspaceStatus').className = 'status-badge status-connected';
        document.getElementById('googleWorkspaceStatus').innerHTML = '<span class="status-indicator"></span><span>Connected</span>';
        showToast('Google Workspace connected', 'success');
      }, 1500);
    }

    function connectSlack() {
      showToast('Opening Slack OAuth consent screen...', 'info');
      setTimeout(() => {
        document.getElementById('slackStatus').className = 'status-badge status-connected';
        document.getElementById('slackStatus').innerHTML = '<span class="status-indicator"></span><span>Connected</span>';
        document.getElementById('slackWebhookItem').style.display = 'block';
        showToast('Slack workspace connected', 'success');
      }, 1500);
    }

    function connectNotion() {
      showToast('Opening Notion OAuth consent screen...', 'info');
      setTimeout(() => {
        document.getElementById('notionStatus').className = 'status-badge status-connected';
        document.getElementById('notionStatus').innerHTML = '<span class="status-indicator"></span><span>Connected</span>';
        showToast('Notion workspace connected', 'success');
      }, 1500);
    }

    // Maintenance functions
    function clearCache() {
      pendingConfirmAction = async () => {
        try {
          const response = await fetch('/api/cache/clear', { method: 'POST' });
          if (!response.ok) throw new Error('Failed to clear cache');
          showToast('Cache cleared successfully', 'success');
        } catch (error) {
          showToast('Failed to clear cache', 'error');
        }
      };
      showConfirmModal('Clear Cache?', 'This will remove all cached data. This operation cannot be undone.', 'Clear');
    }

    function exportLogs() {
      try {
        fetch('/api/logs/export')
          .then(r => r.blob())
          .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `thomas-logs-${new Date().toISOString()}.zip`;
            a.click();
            showToast('Logs exported successfully', 'success');
          });
      } catch (error) {
        showToast('Failed to export logs', 'error');
      }
    }

    function confirmReset() {
      pendingConfirmAction = async () => {
        try {
          const response = await fetch(PREFERENCES_API, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buildPreferencesPatch(defaultLegacySettings())),
          });
          if (!response.ok) throw new Error('Failed to reset settings');
          const data = await response.json();
          Object.assign(settings, buildLegacySettings(data));
          populateForm();
          showToast('All settings reset to factory defaults', 'success');
        } catch (error) {
          showToast('Failed to reset settings', 'error');
        }
      };
      showConfirmModal('Reset All Settings?', 'This will restore all settings to factory defaults. This action cannot be undone.', 'Reset All');
    }

    // Modal functions
    function showConfirmModal(title, message, confirmText) {
      document.querySelector('.modal-title').textContent = title;
      document.getElementById('confirmMessage').textContent = message;
      document.getElementById('confirmButton').textContent = confirmText;
      document.getElementById('confirmModal').classList.add('active');
      document.getElementById('confirmButton').focus();
    }

    function closeModal() {
      document.getElementById('confirmModal').classList.remove('active');
      pendingConfirmAction = null;
    }

    function executeConfirm() {
      if (pendingConfirmAction) {
        pendingConfirmAction();
      }
      closeModal();
    }

    // Toast notifications
    function showToast(message, type = 'info') {
      const container = document.getElementById('toastContainer');
      const toast = document.createElement('div');
      toast.className = `toast ${type}`;

      let icon = '';
      if (type === 'success') icon = '<i class="ph ph-check-circle toast-icon"></i>';
      else if (type === 'error') icon = '<i class="ph ph-warning-circle toast-icon"></i>';
      else icon = '<i class="ph ph-info toast-icon"></i>';

      toast.innerHTML = `
        ${icon}
        <span>${message}</span>
        <button class="toast-close" onclick="this.parentElement.remove()" aria-label="Close notification">
          <i class="ph ph-x"></i>
        </button>
      `;

      container.appendChild(toast);
      setTimeout(() => toast.remove(), 5000);
    }
  


    async function refreshIsolatedDesktopStatus() {
      try {
        const response = await fetch(DESKTOP_STATUS_API);
        if (!response.ok) throw new Error('Failed to load isolated desktop status');
        const payload = await response.json();
        isolatedDesktopState = payload.isolated_desktop || null;
        renderIsolatedDesktopState();
      } catch (error) {
        console.error('Error loading isolated desktop status:', error);
        showToast('Failed to load isolated desktop status', 'error');
      }
    }

    function renderIsolatedDesktopState() {
      const state = isolatedDesktopState || {};
      setToggle('isolatedDesktopEnabled', !!state.enabled);
      setSelectValue('isolatedDesktopTrustMode', state.trust_mode || 'ask_every_time');
      const localVm = state.local_vm || {};
      setSelectValue('isolatedDesktopVmSource', localVm.source_type || 'unconfigured');
      setInputValue('isolatedDesktopVmName', localVm.vm_name || '');
      setInputValue('isolatedDesktopTemplateVhdx', localVm.template_vhdx || '');
      const badge = document.getElementById('isolatedDesktopStatusBadge');
      const statusText = document.getElementById('isolatedDesktopStatusText');
      const nextAction = document.getElementById('isolatedDesktopNextAction');
      const note = document.getElementById('isolatedDesktopNote');
      const templateItem = document.getElementById('isolatedDesktopTemplateItem');
      const installBtn = document.getElementById('installHostServiceButton');
      const viewerBtn = document.getElementById('openViewerButton');
      if (badge) {
        badge.classList.remove('status-connected', 'status-disconnected', 'status-pending');
        const installationState = String(state.installation_state || 'not_enabled');
        if (installationState === 'local_vm_ready') badge.classList.add('status-connected');
        else if (installationState === 'host_service_installing') badge.classList.add('status-pending');
        else badge.classList.add('status-disconnected');
      }
      if (statusText) statusText.textContent = String(state.installation_state || 'not_enabled').replaceAll('_', ' ');
      if (nextAction) nextAction.textContent = state.next_action || 'Select an existing worker VM or a template disk.';
      if (note) note.textContent = state.note || 'Configure a worker VM source so Thomas can provision or attach the isolated desktop worker.';
      if (templateItem) templateItem.style.display = (localVm.source_type || 'unconfigured') === 'template_disk' ? 'flex' : 'none';
      if (installBtn) installBtn.disabled = !state.enabled;
      if (viewerBtn) viewerBtn.disabled = !(state.viewer && state.viewer.available);
    }

    async function saveIsolatedDesktopSettings() {
      const enabled = document.getElementById('isolatedDesktopEnabled').classList.contains('on');
      const trustMode = document.getElementById('isolatedDesktopTrustMode').value;
      const sourceType = document.getElementById('isolatedDesktopVmSource').value;
      const vmName = document.getElementById('isolatedDesktopVmName').value.trim();
      const templateVhdx = document.getElementById('isolatedDesktopTemplateVhdx').value.trim();
      try {
        await fetch('/api/onboarding/desktop/opt-in', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled, hidden_by_default: true }),
        });
        await fetch(DESKTOP_TRUST_API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trust_mode: trustMode }),
        });
        await fetch(DESKTOP_VM_SOURCE_API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_type: sourceType, vm_name: vmName, template_vhdx: templateVhdx }),
        });
        await refreshIsolatedDesktopStatus();
        showToast('Isolated desktop settings saved', 'success');
      } catch (error) {
        console.error('Error saving isolated desktop settings:', error);
        showToast('Failed to save isolated desktop settings', 'error');
      }
    }

    async function installIsolatedDesktopMode() {
      try {
        const response = await fetch(DESKTOP_INSTALL_API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: true, hidden_by_default: true }),
        });
        if (!response.ok) throw new Error('Failed to launch isolated desktop install');
        await refreshIsolatedDesktopStatus();
        showToast('Host service install launched', 'success');
      } catch (error) {
        console.error('Error launching isolated desktop install:', error);
        showToast('Failed to launch isolated desktop install', 'error');
      }
    }

    async function openIsolatedDesktopViewer() {
      try {
        const response = await fetch(DESKTOP_VIEWER_API, { method: 'POST' });
        if (!response.ok) throw new Error('Failed to open isolated desktop viewer');
        showToast('Viewer launch requested', 'success');
      } catch (error) {
        console.error('Error opening isolated desktop viewer:', error);
        showToast('Failed to open isolated desktop viewer', 'error');
      }
    }
