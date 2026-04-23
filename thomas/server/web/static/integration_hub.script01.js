
        // Configuration
        const API_BASE = '/api';
        const INTEGRATIONS = [
            {
                id: 'gmail',
                name: 'Gmail',
                category: 'Google Workspace',
                icon: '📧',
                description: 'Read and send emails, manage labels and drafts',
                scopes: ['mail.google.com', 'calendar.google.com']
            },
            {
                id: 'google-calendar',
                name: 'Google Calendar',
                category: 'Google Workspace',
                icon: '📅',
                description: 'Create and manage events, check availability',
                scopes: ['calendar.google.com']
            },
            {
                id: 'google-drive',
                name: 'Google Drive',
                category: 'Google Workspace',
                icon: '☁️',
                description: 'Access files, create documents, and manage folders',
                scopes: ['drive.google.com']
            },
            {
                id: 'slack',
                name: 'Slack',
                category: 'Communication',
                icon: '💬',
                description: 'Send messages, read channels, manage workflows',
                scopes: ['chat:write', 'channels:read', 'users:read']
            },
            {
                id: 'notion',
                name: 'Notion',
                category: 'Productivity',
                icon: '📝',
                description: 'Create pages, query databases, manage content',
                scopes: ['content:read', 'content:write', 'database:query']
            },
            {
                id: 'webhook',
                name: 'Webhook',
                category: 'Custom',
                icon: '🔗',
                description: 'Receive real-time events via HTTP callbacks',
                scopes: []
            },
            {
                id: 'rest-api',
                name: 'REST API',
                category: 'Custom',
                icon: '⚙️',
                description: 'Generic HTTP requests and RESTful API calls',
                scopes: []
            },
            {
                id: 'database',
                name: 'Database',
                category: 'Custom',
                icon: '🗄️',
                description: 'Connect to external databases and data sources',
                scopes: []
            }
        ];

        // State
        let integrationStates = {};
        let eventLogs = [];
        let webhooks = [];
        let expandedCard = null;

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initializeStates();
            renderIntegrations();
            loadHealthMetrics();
            loadEventLogs();
            loadWebhooks();
            setupAutoRefresh();
        });

        function initializeStates() {
            INTEGRATIONS.forEach(int => {
                integrationStates[int.id] = {
                    status: Math.random() > 0.3 ? 'connected' : 'disconnected',
                    lastSync: new Date(Date.now() - Math.random() * 86400000),
                    errorCount: Math.floor(Math.random() * 5),
                    rateLimit: Math.floor(Math.random() * 100),
                    uptime: 99 + Math.random() * 1
                };
            });
        }

        function renderIntegrations() {
            const grid = document.getElementById('integrationsGrid');
            grid.innerHTML = INTEGRATIONS.map(int => {
                const state = integrationStates[int.id];
                const statusClass = `status-${state.status}`;
                const isExpanded = expandedCard === int.id;

                return `
                    <div class="card" onclick="toggleDetail('${int.id}')">
                        <div class="card-header">
                            <div class="card-icon">${int.icon}</div>
                            <div class="card-title-section">
                                <div class="card-title">${int.name}</div>
                                <span class="status-badge ${statusClass}">
                                    <span class="status-dot"></span>
                                    ${state.status.charAt(0).toUpperCase() + state.status.slice(1)}
                                </span>
                            </div>
                        </div>
                        <div class="card-description">${int.description}</div>
                        <div class="card-footer">
                            <button class="btn-primary btn-connect btn-sm" onclick="handleConnect('${int.id}', event)">
                                ${state.status === 'connected' ? 'Reconnect' : 'Connect'}
                            </button>
                            <button class="btn-secondary btn-settings btn-sm" onclick="handleSettings('${int.id}', event)">
                                ⚙️
                            </button>
                        </div>
                    </div>
                    ${isExpanded ? createDetailPanel(int) : ''}
                `;
            }).join('');
        }

        function createDetailPanel(integration) {
            const state = integrationStates[integration.id];
            const lastSyncTime = formatTime(state.lastSync);

            return `
                <div class="detail-panel open">
                    <div class="detail-content">
                        <div class="panel-section">
                            <div class="section-title">Health Status</div>
                            <div class="health-grid">
                                <div class="health-item">
                                    <div class="health-label">Last Sync</div>
                                    <div class="health-value">${lastSyncTime}</div>
                                </div>
                                <div class="health-item">
                                    <div class="health-label">Error Count</div>
                                    <div class="health-value">${state.errorCount}</div>
                                </div>
                                <div class="health-item">
                                    <div class="health-label">Rate Limit</div>
                                    <div class="health-value">${state.rateLimit}%</div>
                                </div>
                                <div class="health-item">
                                    <div class="health-label">Uptime</div>
                                    <div class="health-value">${state.uptime.toFixed(2)}%</div>
                                </div>
                            </div>
                        </div>

                        ${integration.scopes.length > 0 ? `
                            <div class="panel-section">
                                <div class="section-title">Permissions</div>
                                <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                                    ${integration.scopes.map(scope => `
                                        <span style="background: var(--bg-tertiary); padding: 6px 12px; border-radius: 6px; font-size: 12px;">
                                            ✓ ${scope}
                                        </span>
                                    `).join('')}
                                </div>
                            </div>
                        ` : ''}

                        <div class="panel-section">
                            <div class="section-title">Configuration</div>
                            <div class="form-group">
                                <label>Sync Interval (minutes)</label>
                                <input type="number" value="60" min="5" max="1440">
                            </div>
                            <div class="form-group">
                                <label>API Key / Token</label>
                                <input type="password" value="••••••••••••••••" placeholder="Enter API key">
                            </div>
                            <button class="btn-primary btn-sm" style="width: 100%; justify-content: center;" onclick="handleSave('${integration.id}')">
                                Save Configuration
                            </button>
                        </div>

                        <div class="panel-section">
                            <div class="section-title">Actions</div>
                            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                <button class="btn-secondary btn-sm" onclick="handleSync('${integration.id}')">
                                    🔄 Sync Now
                                </button>
                                <button class="btn-secondary btn-sm" onclick="handleTest('${integration.id}')">
                                    ✓ Test Connection
                                </button>
                                <button class="btn-secondary btn-sm" onclick="handleDisconnect('${integration.id}')">
                                    ✕ Disconnect
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        function toggleDetail(integrationId) {
            if (expandedCard === integrationId) {
                expandedCard = null;
            } else {
                expandedCard = integrationId;
            }
            renderIntegrations();
        }

        function handleConnect(integrationId, event) {
            event.stopPropagation();
            showToast(`Initiating OAuth flow for ${integrationId}...`, 'success');

            setTimeout(() => {
                integrationStates[integrationId].status = 'connected';
                integrationStates[integrationId].lastSync = new Date();
                addEvent(`Connected to ${integrationId}`, '✓', 'success');
                renderIntegrations();
                showToast(`Successfully connected ${integrationId}!`, 'success');
            }, 2000);
        }

        function handleSettings(integrationId, event) {
            event.stopPropagation();
            toggleDetail(integrationId);
        }

        function handleSave(integrationId, event) {
            showToast(`Configuration saved for ${integrationId}`, 'success');
            addEvent(`Saved config for ${integrationId}`, '💾', 'info');
        }

        function handleSync(integrationId) {
            showToast(`Syncing ${integrationId}...`, 'success');
            addEvent(`Initiated sync for ${integrationId}`, '🔄', 'info');

            setTimeout(() => {
                integrationStates[integrationId].lastSync = new Date();
                renderIntegrations();
                showToast(`Sync completed for ${integrationId}`, 'success');
                addEvent(`Sync completed for ${integrationId}`, '✓', 'success');
            }, 3000);
        }

        function handleTest(integrationId) {
            showToast(`Testing ${integrationId}...`, 'success');
            addEvent(`Testing connection to ${integrationId}`, '🧪', 'info');

            setTimeout(() => {
                showToast(`Connection test passed for ${integrationId}`, 'success');
                addEvent(`Connection test passed for ${integrationId}`, '✓', 'success');
            }, 2000);
        }

        function handleDisconnect(integrationId) {
            if (confirm(`Are you sure you want to disconnect ${integrationId}?`)) {
                integrationStates[integrationId].status = 'disconnected';
                expandedCard = null;
                renderIntegrations();
                showToast(`Disconnected ${integrationId}`, 'error');
                addEvent(`Disconnected from ${integrationId}`, '✕', 'error');
            }
        }

        function loadHealthMetrics() {
            const container = document.getElementById('healthMetrics');

            const metrics = INTEGRATIONS.map(int => {
                const state = integrationStates[int.id];
                return `
                    <div style="background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <div style="font-size: 24px;">${int.icon}</div>
                                <div>
                                    <div style="font-weight: 700;">${int.name}</div>
                                    <div style="font-size: 12px; color: var(--text-secondary);">${int.category}</div>
                                </div>
                            </div>
                            <span class="status-badge status-${state.status}">
                                <span class="status-dot"></span>
                                ${state.status.charAt(0).toUpperCase() + state.status.slice(1)}
                            </span>
                        </div>
                        <div class="health-grid">
                            <div class="health-item">
                                <div class="health-label">Requests Today</div>
                                <div class="health-value">${Math.floor(Math.random() * 500)}</div>
                            </div>
                            <div class="health-item">
                                <div class="health-label">Avg Latency</div>
                                <div class="health-value">${Math.floor(Math.random() * 200)}ms</div>
                            </div>
                            <div class="health-item">
                                <div class="health-label">Error Rate</div>
                                <div class="health-value">${(Math.random() * 2).toFixed(2)}%</div>
                            </div>
                            <div class="health-item">
                                <div class="health-label">Circuit Breaker</div>
                                <div class="health-value" style="font-size: 14px; color: var(--success);">CLOSED</div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            container.innerHTML = metrics;
        }

        function loadEventLogs() {
            addEvent('Integration Hub initialized', '🚀', 'info');
            addEvent('All integrations loaded successfully', '✓', 'success');
            renderEventLog();
        }

        function loadWebhooks() {
            webhooks = [
                {
                    id: 'wh1',
                    name: 'Slack Notifications',
                    url: 'https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX',
                    events: ['sync_complete', 'error'],
                    lastTriggered: new Date(Date.now() - 300000)
                },
                {
                    id: 'wh2',
                    name: 'Analytics Endpoint',
                    url: 'https://analytics.example.com/webhook',
                    events: ['api_call', 'rate_limit_hit'],
                    lastTriggered: new Date(Date.now() - 60000)
                }
            ];
            renderWebhooks();
        }

        function renderWebhooks() {
            const container = document.getElementById('webhooksList');

            if (webhooks.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">🔗</div>
                        <p>No webhooks configured yet</p>
                        <p style="font-size: 12px; margin-top: 8px;">Create webhooks to receive real-time integration events</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = `
                <div class="webhook-list">
                    ${webhooks.map(webhook => `
                        <div class="webhook-item">
                            <div class="webhook-info">
                                <div class="webhook-name">${webhook.name}</div>
                                <div class="webhook-url">${webhook.url}</div>
                                <div style="font-size: 11px; color: var(--text-secondary); margin-top: 6px;">
                                    Events: ${webhook.events.join(', ')} • Last triggered: ${formatTime(webhook.lastTriggered)}
                                </div>
                            </div>
                            <div class="webhook-actions">
                                <button class="btn-secondary btn-sm" onclick="handleWebhookTest('${webhook.id}')">Test</button>
                                <button class="btn-secondary btn-sm" onclick="handleWebhookEdit('${webhook.id}')">Edit</button>
                                <button class="btn-secondary btn-sm" onclick="handleWebhookDelete('${webhook.id}')">Delete</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        function showAddWebhook() {
            const url = prompt('Enter webhook URL:');
            if (url) {
                const webhook = {
                    id: `wh${Date.now()}`,
                    name: prompt('Enter webhook name:') || 'New Webhook',
                    url: url,
                    events: ['sync_complete'],
                    lastTriggered: new Date()
                };
                webhooks.push(webhook);
                renderWebhooks();
                showToast(`Webhook "${webhook.name}" created successfully`, 'success');
                addEvent(`Created webhook: ${webhook.name}`, '✓', 'success');
            }
        }

        function handleWebhookTest(webhookId) {
            showToast(`Testing webhook...`, 'success');
            const webhook = webhooks.find(w => w.id === webhookId);
            addEvent(`Testing webhook: ${webhook.name}`, '🧪', 'info');

            setTimeout(() => {
                webhook.lastTriggered = new Date();
                renderWebhooks();
                showToast(`Webhook test successful`, 'success');
                addEvent(`Webhook test passed for: ${webhook.name}`, '✓', 'success');
            }, 1500);
        }

        function handleWebhookEdit(webhookId) {
            const webhook = webhooks.find(w => w.id === webhookId);
            const newUrl = prompt('Edit webhook URL:', webhook.url);
            if (newUrl) {
                webhook.url = newUrl;
                renderWebhooks();
                showToast(`Webhook updated successfully`, 'success');
                addEvent(`Updated webhook: ${webhook.name}`, '✏️', 'info');
            }
        }

        function handleWebhookDelete(webhookId) {
            const webhook = webhooks.find(w => w.id === webhookId);
            if (confirm(`Delete webhook "${webhook.name}"?`)) {
                webhooks = webhooks.filter(w => w.id !== webhookId);
                renderWebhooks();
                showToast(`Webhook deleted`, 'error');
                addEvent(`Deleted webhook: ${webhook.name}`, '✕', 'error');
            }
        }

        function addEvent(title, icon, type = 'info') {
            eventLogs.unshift({
                title: title,
                icon: icon,
                type: type,
                timestamp: new Date()
            });
            if (eventLogs.length > 50) eventLogs.pop();
            renderEventLog();
        }

        function renderEventLog() {
            const container = document.getElementById('eventLog');

            if (eventLogs.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📋</div>
                        <p>No events yet</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = eventLogs.map(event => `
                <div class="event-item">
                    <div class="event-icon" style="background: ${getTypeColor(event.type)};">${event.icon}</div>
                    <div class="event-content">
                        <div class="event-title">${event.title}</div>
                        <div class="event-time">${formatTime(event.timestamp)}</div>
                    </div>
                </div>
            `).join('');
        }

        function getTypeColor(type) {
            const colors = {
                success: 'rgba(0, 184, 148, 0.2)',
                error: 'rgba(214, 48, 49, 0.2)',
                info: 'rgba(108, 92, 231, 0.2)',
                warning: 'rgba(253, 203, 110, 0.2)'
            };
            return colors[type] || colors.info;
        }

        function showToast(message, type = 'info') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = `
                <div style="width: 20px; height: 20px; display: flex; align-items: center; justify-content: center;">
                    ${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}
                </div>
                <span>${message}</span>
            `;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));

            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
        }

        function formatTime(date) {
            const now = new Date();
            const diff = now - date;
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);

            if (minutes < 1) return 'Just now';
            if (minutes < 60) return `${minutes}m ago`;
            if (hours < 24) return `${hours}h ago`;
            return `${days}d ago`;
        }

        function setupAutoRefresh() {
            setInterval(() => {
                if (document.getElementById('integrations').classList.contains('active')) {
                    loadHealthMetrics();
                }
            }, 30000);
        }
    
