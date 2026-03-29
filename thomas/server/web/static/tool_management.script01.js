
        // State Management
        const state = {
            tools: [],
            selectedCategory: 'all',
            searchQuery: '',
            selectedTools: new Set(),
            currentTool: null
        };

        // API Functions
        function normalizeToolList(payload) {
            const rawTools = Array.isArray(payload)
                ? payload
                : (Array.isArray(payload?.tools) ? payload.tools : []);

            return rawTools.map((tool) => {
                const params = tool?.params && typeof tool.params === 'object'
                    ? tool.params
                    : (tool?.parameters && typeof tool.parameters === 'object' ? tool.parameters : {});
                return {
                    id: tool?.id || tool?.name || '',
                    name: tool?.name || tool?.id || 'Unnamed tool',
                    description: tool?.description || '',
                    category: tool?.category || 'general',
                    status: tool?.status || 'active',
                    params,
                    avgLatency: Number(tool?.avgLatency || 0),
                    successRate: Number(tool?.successRate || 0),
                    icon: tool?.icon || '',
                    examples: tool?.examples || '',
                };
            });
        }

        async function fetchTools() {
            try {
                const response = await fetch('/api/tools');
                state.tools = normalizeToolList(await response.json());
                updateStats();
                renderTools();
                return true;
            } catch (error) {
                console.error('Failed to fetch tools:', error);
                renderEmpty('Failed to load tools');
                return false;
            }
        }

        async function fetchToolLogs() {
            try {
                const response = await fetch('/api/tools/logs');
                return await response.json();
            } catch (error) {
                console.error('Failed to fetch logs:', error);
                return [];
            }
        }

        async function fetchToolHealth() {
            try {
                const response = await fetch('/api/tools/health');
                return await response.json();
            } catch (error) {
                console.error('Failed to fetch health:', error);
                return [];
            }
        }

        async function saveToolConfig(toolId, config) {
            try {
                const response = await fetch(`/api/tools/${toolId}/config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
                return await response.json();
            } catch (error) {
                console.error('Failed to save config:', error);
                throw error;
            }
        }

        async function testTool(toolId) {
            try {
                const response = await fetch(`/api/tools/${toolId}/test`, {
                    method: 'POST'
                });
                return await response.json();
            } catch (error) {
                console.error('Failed to test tool:', error);
                throw error;
            }
        }

        // UI Functions
        function updateStats() {
            const total = state.tools.length;
            const active = state.tools.filter(t => t.status === 'active').length;
            const errors = state.tools.filter(t => t.status === 'error').length;

            document.getElementById('statTotal').textContent = total;
            document.getElementById('statActive').textContent = active;
            document.getElementById('statErrors').textContent = errors;
        }

        function filterTools() {
            return state.tools.filter(tool => {
                const matchCategory = state.selectedCategory === 'all' || tool.category === state.selectedCategory;
                const matchSearch = tool.name.toLowerCase().includes(state.searchQuery.toLowerCase()) ||
                                  (tool.description || '').toLowerCase().includes(state.searchQuery.toLowerCase());
                return matchCategory && matchSearch;
            });
        }

        function renderTools() {
            const filtered = filterTools();
            const grid = document.getElementById('toolGrid');

            if (filtered.length === 0) {
                renderEmpty('No tools found');
                return;
            }

            grid.innerHTML = filtered.map(tool => `
                <div class="tool-card" data-tool-id="${tool.id}">
                    <div class="tool-card-header">
                        <div class="tool-icon">${tool.icon || '⚙'}</div>
                        <div class="tool-status status-${tool.status}">
                            <span class="status-dot ${tool.status}"></span>
                            ${tool.status}
                        </div>
                    </div>
                    <input type="checkbox" class="tool-checkbox" style="position: absolute; top: 1rem; left: 1.5rem; width: 18px; height: 18px; cursor: pointer;">
                    <div class="tool-name">${tool.name}</div>
                    <div class="tool-category">${tool.category}</div>
                    <div class="tool-description">${tool.description}</div>
                    <div class="tool-footer">
                        <div class="tool-meta">
                            <span>⏱ ${tool.avgLatency || 0}ms</span>
                            <span>✓ ${tool.successRate || 0}%</span>
                        </div>
                        <div class="tool-actions">
                            <button class="icon-btn" title="View Details">👁</button>
                            <button class="icon-btn" title="Configure">⚙</button>
                        </div>
                    </div>
                </div>
            `).join('');

            // Add event listeners
            grid.querySelectorAll('.tool-card').forEach(card => {
                const toolId = card.dataset.toolId;
                const checkbox = card.querySelector('.tool-checkbox');

                checkbox.addEventListener('change', (e) => {
                    e.stopPropagation();
                    if (checkbox.checked) {
                        state.selectedTools.add(toolId);
                    } else {
                        state.selectedTools.delete(toolId);
                    }
                    updateBulkActions();
                });

                card.querySelector('.tool-actions').addEventListener('click', (e) => {
                    e.stopPropagation();
                    const btn = e.target.closest('.icon-btn');
                    if (btn) {
                        if (btn.title === 'View Details') {
                            showToolModal(toolId);
                        } else if (btn.title === 'Configure') {
                            showToolModal(toolId, 'config');
                        }
                    }
                });

                card.addEventListener('click', () => showToolModal(toolId));
            });
        }

        function renderEmpty(message) {
            document.getElementById('toolGrid').innerHTML = `
                <div class="empty-state" style="grid-column: 1/-1;">
                    <div class="empty-state-icon">⚙</div>
                    <div class="empty-state-title">${message}</div>
                </div>
            `;
        }

        async function showToolModal(toolId, tab = 'overview') {
            const tool = state.tools.find(t => t.id === toolId);
            if (!tool) return;

            state.currentTool = tool;

            // Overview
            document.getElementById('modalToolName').textContent = tool.name;
            document.getElementById('modalDescription').textContent = tool.description;
            document.getElementById('modalCategory').textContent = tool.category;
            document.getElementById('modalParams').textContent = JSON.stringify(tool.params || {}, null, 2);
            document.getElementById('modalExamples').textContent = tool.examples || 'No examples available';

            // Config Form
            renderConfigForm(tool);

            // Logs
            await renderToolLogs(toolId);

            // Health
            await renderToolHealth(toolId);

            // Show Tab
            setModalTab(tab);
            document.getElementById('toolModal').classList.add('active');
        }

        function renderConfigForm(tool) {
            const form = document.getElementById('configForm');
            const params = tool.params?.properties || {};

            form.innerHTML = Object.entries(params).map(([key, param]) => `
                <div class="form-group">
                    <label>${param.title || key}</label>
                    <input type="text" data-param="${key}" placeholder="${param.description || ''}">
                    ${param.description ? `<div class="help-text">${param.description}</div>` : ''}
                </div>
            `).join('');
        }

        async function renderToolLogs(toolId) {
            try {
                const logs = await fetchToolLogs();
                const toolLogs = logs.filter(log => log.toolId === toolId);
                const tbody = document.getElementById('toolLogsBody');

                if (toolLogs.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem;">No execution logs</td></tr>';
                    return;
                }

                tbody.innerHTML = toolLogs.slice(0, 10).map(log => `
                    <tr>
                        <td>${new Date(log.timestamp).toLocaleString()}</td>
                        <td><span class="log-status ${log.status}">${log.status}</span></td>
                        <td><code style="color: #a0aec0;">${JSON.stringify(log.input || {})}</code></td>
                        <td><code style="color: #a0aec0; max-width: 200px; overflow: hidden; text-overflow: ellipsis;">${JSON.stringify(log.output || {})}</code></td>
                        <td>${log.duration || 0}ms</td>
                    </tr>
                `).join('');
            } catch (error) {
                console.error('Failed to render logs:', error);
            }
        }

        async function renderToolHealth(toolId) {
            try {
                const health = await fetchToolHealth();
                const toolHealth = health.find(h => h.toolId === toolId) || {};

                document.getElementById('healthSuccessRate').textContent = `${toolHealth.successRate || 0}%`;
                document.getElementById('healthSuccessBar').style.width = `${toolHealth.successRate || 0}%`;
                document.getElementById('healthLatency').textContent = `${toolHealth.avgLatency || 0}`;
                document.getElementById('healthErrorRate').textContent = `${toolHealth.errorRate || 0}%`;
                document.getElementById('healthErrorBar').style.width = `${toolHealth.errorRate || 0}%`;
                document.getElementById('healthTotalCalls').textContent = toolHealth.totalCalls || 0;
                document.getElementById('healthLastCalled').textContent =
                    toolHealth.lastCalled ? new Date(toolHealth.lastCalled).toLocaleString() : 'Never';
            } catch (error) {
                console.error('Failed to render health:', error);
            }
        }

        async function renderLogs() {
            const logs = await fetchToolLogs();
            const tbody = document.getElementById('logsBody');

            if (logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 2rem;">No execution logs</td></tr>';
                return;
            }

            tbody.innerHTML = logs.slice(0, 50).map(log => `
                <tr>
                    <td>${new Date(log.timestamp).toLocaleString()}</td>
                    <td>${log.toolName || 'Unknown'}</td>
                    <td><code style="color: #a0aec0; font-size: 0.8rem;">${JSON.stringify(log.input || {}).substring(0, 50)}...</code></td>
                    <td><span class="log-status ${log.status}">${log.status}</span></td>
                    <td>${log.duration || 0}ms</td>
                    <td><code style="color: #a0aec0; font-size: 0.8rem;">${JSON.stringify(log.output || {}).substring(0, 50)}...</code></td>
                </tr>
            `).join('');
        }

        async function renderHealth() {
            const health = await fetchToolHealth();
            const grid = document.getElementById('healthGrid');

            if (health.length === 0) {
                grid.innerHTML = `
                    <div class="empty-state" style="grid-column: 1/-1;">
                        <div class="empty-state-icon">❤</div>
                        <div class="empty-state-title">No health data available</div>
                    </div>
                `;
                return;
            }

            grid.innerHTML = health.map(h => `
                <div class="health-card">
                    <div class="health-label">${h.toolName || 'Unknown'}</div>
                    <div style="margin-bottom: 1rem;">
                        <div style="font-size: 0.9rem; color: #a0aec0; margin-bottom: 0.5rem;">Success Rate</div>
                        <div class="health-bar">
                            <div class="health-bar-fill" style="width: ${h.successRate || 0}%"></div>
                        </div>
                        <div style="color: #6c5ce7; font-weight: bold;">${h.successRate || 0}%</div>
                    </div>
                    <div style="font-size: 0.85rem; color: #a0aec0;">
                        <div>Latency: ${h.avgLatency || 0}ms</div>
                        <div>Errors: ${h.errorRate || 0}%</div>
                        <div>Calls: ${h.totalCalls || 0}</div>
                    </div>
                </div>
            `).join('');
        }

        function updateBulkActions() {
            const count = state.selectedTools.size;
            const bulkActions = document.getElementById('bulkActions');
            const bulkCount = document.getElementById('bulkCount');

            bulkCount.textContent = count;

            if (count > 0) {
                bulkActions.classList.add('active');
            } else {
                bulkActions.classList.remove('active');
            }
        }

        function setModalTab(tabName) {
            document.querySelectorAll('.modal-tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.modalTab === tabName);
            });
            document.querySelectorAll('.modal-tab-content').forEach(content => {
                content.classList.toggle('active', content.id === `modal-${tabName}`);
            });
        }

        function setMainTab(tabName) {
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === tabName);
            });
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.toggle('active', content.id === `${tabName}-tab`);
            });

            if (tabName === 'logs') renderLogs();
            if (tabName === 'health') renderHealth();
        }

        // Event Listeners
        document.getElementById('searchInput').addEventListener('input', (e) => {
            state.searchQuery = e.target.value;
            renderTools();
        });

        document.querySelectorAll('.category-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.selectedCategory = btn.dataset.category;
                renderTools();
            });
        });

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => setMainTab(btn.dataset.tab));
        });

        document.querySelectorAll('.modal-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => setModalTab(btn.dataset.modalTab));
        });

        document.getElementById('refreshBtn').addEventListener('click', fetchTools);

        document.getElementById('newToolBtn').addEventListener('click', () => {
            document.getElementById('newToolModal').classList.add('active');
        });

        document.getElementById('modalCloseBtn').addEventListener('click', () => {
            document.getElementById('toolModal').classList.remove('active');
        });

        document.getElementById('newToolCloseBtn').addEventListener('click', () => {
            document.getElementById('newToolModal').classList.remove('active');
        });

        document.getElementById('saveConfigBtn').addEventListener('click', async () => {
            const config = {};
            document.querySelectorAll('[data-param]').forEach(input => {
                config[input.dataset.param] = input.value;
            });
            try {
                await saveToolConfig(state.currentTool.id, config);
                alert('Configuration saved successfully');
            } catch (error) {
                alert('Failed to save configuration');
            }
        });

        document.getElementById('testToolBtn').addEventListener('click', async () => {
            try {
                const result = await testTool(state.currentTool.id);
                const resultDiv = document.getElementById('testResult');
                resultDiv.style.display = 'block';
                document.getElementById('testResultText').textContent = JSON.stringify(result, null, 2);
            } catch (error) {
                alert('Test failed: ' + error.message);
            }
        });

        document.getElementById('selectAllCheckbox').addEventListener('change', (e) => {
            if (e.target.checked) {
                filterTools().forEach(tool => state.selectedTools.add(tool.id));
            } else {
                state.selectedTools.clear();
            }
            updateBulkActions();
            document.querySelectorAll('.tool-checkbox').forEach(checkbox => {
                checkbox.checked = e.target.checked;
            });
        });

        document.getElementById('enableSelectedBtn').addEventListener('click', async () => {
            for (const toolId of state.selectedTools) {
                await saveToolConfig(toolId, { enabled: true });
            }
            state.selectedTools.clear();
            updateBulkActions();
            fetchTools();
        });

        document.getElementById('disableSelectedBtn').addEventListener('click', async () => {
            for (const toolId of state.selectedTools) {
                await saveToolConfig(toolId, { enabled: false });
            }
            state.selectedTools.clear();
            updateBulkActions();
            fetchTools();
        });

        document.getElementById('deleteSelectedBtn').addEventListener('click', async () => {
            if (confirm(`Delete ${state.selectedTools.size} tool(s)?`)) {
                for (const toolId of state.selectedTools) {
                    try {
                        await fetch(`/api/tools/${toolId}`, { method: 'DELETE' });
                    } catch (error) {
                        console.error('Failed to delete tool:', error);
                    }
                }
                state.selectedTools.clear();
                updateBulkActions();
                fetchTools();
            }
        });

        document.getElementById('createToolBtn').addEventListener('click', async () => {
            const newTool = {
                name: document.getElementById('newToolName').value,
                category: document.getElementById('newToolCategory').value,
                icon: document.getElementById('newToolIcon').value,
                description: document.getElementById('newToolDescription').value,
                params: JSON.parse(document.getElementById('newToolParams').value),
                code: document.getElementById('newToolCode').value
            };

            try {
                const response = await fetch('/api/tools', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newTool)
                });
                if (response.ok) {
                    document.getElementById('newToolModal').classList.remove('active');
                    fetchTools();
                }
            } catch (error) {
                alert('Failed to create tool');
            }
        });

        document.getElementById('testNewToolBtn').addEventListener('click', async () => {
            try {
                const code = document.getElementById('newToolCode').value;
                const response = await fetch('/api/tools/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code })
                });
                const result = await response.json();
                const resultDiv = document.getElementById('newToolTestResult');
                resultDiv.style.display = 'block';
                document.getElementById('newToolTestText').textContent = JSON.stringify(result, null, 2);
            } catch (error) {
                alert('Test failed');
            }
        });

        // Close modals on outside click
        document.getElementById('toolModal').addEventListener('click', (e) => {
            if (e.target.id === 'toolModal') {
                document.getElementById('toolModal').classList.remove('active');
            }
        });

        document.getElementById('newToolModal').addEventListener('click', (e) => {
            if (e.target.id === 'newToolModal') {
                document.getElementById('newToolModal').classList.remove('active');
            }
        });

        // Initialize
        fetchTools();
    
