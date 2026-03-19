
        // ===== State Management =====
        const state = {
            connections: JSON.parse(localStorage.getItem('connections')) || [],
            selectedConnection: localStorage.getItem('selectedConnection') || '',
            currentQuery: '',
            queryResults: null,
            queryHistory: JSON.parse(localStorage.getItem('queryHistory')) || [],
            savedQueries: JSON.parse(localStorage.getItem('savedQueries')) || [],
            currentPage: 0,
            pageSize: 50,
            sortColumn: null,
            sortDirection: 'asc',
            schema: null,
            chart: null,
        };

        const ROWS_PER_PAGE = 50;
        const MAX_HISTORY = 50;
        const API_BASE = '/api/tools';

        // ===== Initialization =====
        document.addEventListener('DOMContentLoaded', () => {
            initializeConnections();
            setupEventListeners();
            createNewTab();
            loadHistory();
        });

        function initializeConnections() {
            const select = document.getElementById('connectionSelect');
            select.innerHTML = '<option value="">Select connection...</option>';
            state.connections.forEach(conn => {
                const opt = document.createElement('option');
                opt.value = conn.id;
                opt.textContent = conn.name;
                select.appendChild(opt);
            });
            if (state.selectedConnection) {
                select.value = state.selectedConnection;
                loadSchema();
            }
        }

        function setupEventListeners() {
            // Buttons
            document.getElementById('addConnectionBtn').addEventListener('click', () => openModal('connectionModal'));
            document.getElementById('testConnectionBtn').addEventListener('click', testConnection);
            document.getElementById('executeBtn').addEventListener('click', executeQuery);
            document.getElementById('exportCSVBtn').addEventListener('click', () => exportResults('csv'));
            document.getElementById('exportJSONBtn').addEventListener('click', () => exportResults('json'));
            document.getElementById('toggleVisualizerBtn').addEventListener('click', toggleVisualizer);
            document.getElementById('toggleLeftPanel').addEventListener('click', togglePanel.bind(null, 'left'));
            document.getElementById('toggleRightPanel').addEventListener('click', togglePanel.bind(null, 'right'));

            // Connection selector
            document.getElementById('connectionSelect').addEventListener('change', (e) => {
                state.selectedConnection = e.target.value;
                localStorage.setItem('selectedConnection', state.selectedConnection);
                if (state.selectedConnection) {
                    loadSchema();
                } else {
                    document.getElementById('schemaContainer').innerHTML = '<div class="empty-state">No connection selected</div>';
                }
            });

            // Query editor
            const editor = document.getElementById('queryEditor');
            editor.addEventListener('keydown', (e) => {
                if (e.key === 'Tab') {
                    e.preventDefault();
                    const start = editor.selectionStart;
                    const end = editor.selectionEnd;
                    editor.value = editor.value.substring(0, start) + '\t' + editor.value.substring(end);
                    editor.selectionStart = editor.selectionEnd = start + 1;
                    updateLineNumbers();
                }
                if (e.key === 'Enter' && e.ctrlKey) {
                    executeQuery();
                }
            });
            editor.addEventListener('input', (e) => {
                state.currentQuery = e.target.value;
                updateLineNumbers();
            });

            // NL input
            document.getElementById('nlInput').addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && e.ctrlKey) {
                    executeQuery();
                }
            });

            // Query mode toggle
            document.querySelectorAll('.query-mode-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    document.querySelectorAll('.query-mode-btn').forEach(b => b.classList.remove('active'));
                    e.target.classList.add('active');
                    switchQueryMode(e.target.dataset.mode);
                });
            });

            // Connection type selector
            document.getElementById('connType').addEventListener('change', (e) => {
                document.getElementById('sqlitePathGroup').style.display = e.target.value === 'sqlite' ? 'flex' : 'none';
                document.getElementById('postgresConnGroup').style.display = e.target.value === 'postgresql' ? 'flex' : 'none';
            });

            // Chart options
            document.getElementById('chartType').addEventListener('change', renderChart);
            document.getElementById('chartX').addEventListener('change', renderChart);
            document.getElementById('chartY').addEventListener('change', renderChart);
        }

        function updateLineNumbers() {
            const editor = document.getElementById('queryEditor');
            const lineCount = editor.value.split('\n').length;
            let lines = '';
            for (let i = 1; i <= Math.max(lineCount, 10); i++) {
                lines += i + '\n';
            }
            document.getElementById('lineNumbers').textContent = lines;
        }

        function switchQueryMode(mode) {
            document.getElementById('sqlEditorMode').style.display = mode === 'sql' ? 'flex' : 'none';
            document.getElementById('nlEditorMode').style.display = mode === 'nl' ? 'block' : 'none';
            updateLineNumbers();
        }

        // ===== Schema Loading =====
        async function loadSchema() {
            if (!state.selectedConnection) return;
            const container = document.getElementById('schemaContainer');
            container.innerHTML = '<div class="empty-state"><div class="spinner"></div> Loading...</div>';

            try {
                const resp = await fetch(`${API_BASE}/database/schema?connection_id=${encodeURIComponent(state.selectedConnection)}`);
                if (!resp.ok) throw new Error('Failed to load schema');
                state.schema = await resp.json();
                renderSchema();
            } catch (err) {
                container.innerHTML = `<div class="empty-state" style="color: var(--error);">Error: ${err.message}</div>`;
            }
        }

        function renderSchema() {
            const container = document.getElementById('schemaContainer');
            if (!state.schema || !state.schema.databases || state.schema.databases.length === 0) {
                container.innerHTML = '<div class="empty-state">No schema available</div>';
                return;
            }

            let html = '';
            state.schema.databases.forEach(db => {
                const dbId = `db-${Math.random()}`;
                html += `
                    <div class="tree-node">
                        <span class="tree-toggle collapsed" onclick="toggleNode(this)"></span>
                        <span>📦 ${escapeHtml(db.name)}</span>
                    </div>
                    <div id="${dbId}" style="display: none;">
                `;
                if (db.tables) {
                    db.tables.forEach(table => {
                        const tableId = `tbl-${Math.random()}`;
                        html += `
                            <div class="tree-node table">
                                <span class="tree-toggle collapsed" onclick="toggleNode(this)"></span>
                                <span>📋 ${escapeHtml(table.name)}</span>
                            </div>
                            <div id="${tableId}" style="display: none;">
                        `;
                        if (table.columns) {
                            table.columns.forEach(col => {
                                html += `
                                    <div class="tree-node column">
                                        <span>📄</span>
                                        <span>${escapeHtml(col.name)}</span>
                                        <span class="column-type">${escapeHtml(col.type)}</span>
                                    </div>
                                `;
                            });
                        }
                        html += '</div>';
                    });
                }
                html += '</div>';
            });

            container.innerHTML = html;
        }

        function toggleNode(el) {
            const toggle = el.classList.toggle('expanded') || el.classList.toggle('collapsed');
            const parent = el.closest('.tree-node');
            const nextDiv = parent.nextElementSibling;
            if (nextDiv && nextDiv.id) {
                nextDiv.style.display = el.classList.contains('expanded') ? 'block' : 'none';
            }
        }

        // ===== Query Execution =====
        async function executeQuery() {
            const mode = document.querySelector('.query-mode-btn.active').dataset.mode;
            let query = state.currentQuery;

            if (mode === 'nl') {
                query = await convertNLToSQL();
                if (!query) return;
                document.getElementById('queryEditor').value = query;
                state.currentQuery = query;
                updateLineNumbers();
            }

            if (!query.trim()) {
                showAlert('Please enter a query', 'error');
                return;
            }

            if (!state.selectedConnection) {
                showAlert('Please select a connection', 'error');
                return;
            }

            const startTime = performance.now();
            const execBtn = document.getElementById('executeBtn');
            execBtn.disabled = true;
            execBtn.innerHTML = '<span class="spinner"></span>';

            try {
                const resp = await fetch(`${API_BASE}/database/query`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        connection_id: state.selectedConnection,
                        query: query
                    })
                });

                if (!resp.ok) throw new Error('Query execution failed');
                const data = await resp.json();

                state.queryResults = data.rows || [];
                state.columns = data.columns || (state.queryResults.length > 0 ? Object.keys(state.queryResults[0]) : []);
                state.currentPage = 0;
                state.sortColumn = null;

                const execTime = ((performance.now() - startTime) / 1000).toFixed(2);
                document.getElementById('execTime').textContent = `${execTime}s`;
                document.getElementById('rowCount').textContent = state.queryResults.length;

                addToHistory(query);
                renderResults();

                // Show export buttons
                document.getElementById('exportCSVBtn').style.display = 'inline-block';
                document.getElementById('exportJSONBtn').style.display = 'inline-block';
                document.getElementById('toggleVisualizerBtn').style.display = 'inline-block';

                showAlert(`Query executed: ${state.queryResults.length} rows returned`, 'success');
            } catch (err) {
                showAlert(`Error: ${err.message}`, 'error');
            } finally {
                execBtn.disabled = false;
                execBtn.innerHTML = '▶ Execute';
            }
        }

        async function convertNLToSQL() {
            const nlText = document.getElementById('nlInput').value.trim();
            if (!nlText) {
                showAlert('Please describe your query', 'error');
                return null;
            }

            try {
                const resp = await fetch(`${API_BASE}/nl-to-sql`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        natural_language: nlText,
                        schema: state.schema
                    })
                });

                if (!resp.ok) throw new Error('NL conversion failed');
                const data = await resp.json();
                return data.sql || null;
            } catch (err) {
                showAlert(`Error: ${err.message}`, 'error');
                return null;
            }
        }

        // ===== Results Rendering =====
        function renderResults() {
            const container = document.getElementById('resultsTableContainer');
            if (!state.queryResults || state.queryResults.length === 0) {
                container.innerHTML = '<div class="empty-state">No results</div>';
                return;
            }

            const start = state.currentPage * ROWS_PER_PAGE;
            const end = start + ROWS_PER_PAGE;
            const pageData = state.queryResults.slice(start, end);

            let html = '<table class="results-table"><thead><tr>';
            state.columns.forEach(col => {
                const sorted = state.sortColumn === col ? ` sorted-${state.sortDirection}` : '';
                html += `<th class="sortable${sorted}" onclick="sortResults('${col}')">${escapeHtml(col)}</th>`;
            });
            html += '</tr></thead><tbody>';

            pageData.forEach(row => {
                html += '<tr>';
                state.columns.forEach(col => {
                    const value = row[col];
                    const displayValue = value === null ? '<em>NULL</em>' : escapeHtml(String(value));
                    html += `<td>${displayValue}</td>`;
                });
                html += '</tr>';
            });

            html += '</tbody></table>';
            container.innerHTML = html;

            // Pagination
            const totalPages = Math.ceil(state.queryResults.length / ROWS_PER_PAGE);
            if (totalPages > 1) {
                renderPagination(totalPages);
            } else {
                document.getElementById('paginationContainer').style.display = 'none';
            }
        }

        function sortResults(column) {
            if (state.sortColumn === column) {
                state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortColumn = column;
                state.sortDirection = 'asc';
            }

            state.queryResults.sort((a, b) => {
                const aVal = a[column];
                const bVal = b[column];
                if (aVal === null) return 1;
                if (bVal === null) return -1;
                if (typeof aVal === 'string') {
                    return state.sortDirection === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
                }
                return state.sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
            });

            state.currentPage = 0;
            renderResults();
        }

        function renderPagination(totalPages) {
            const container = document.getElementById('paginationContainer');
            let html = '';

            if (state.currentPage > 0) {
                html += '<button class="pagination-btn" onclick="goToPage(0)">First</button>';
                html += '<button class="pagination-btn" onclick="goToPage(' + (state.currentPage - 1) + ')">Prev</button>';
            }

            const start = Math.max(0, state.currentPage - 2);
            const end = Math.min(totalPages, state.currentPage + 3);

            for (let i = start; i < end; i++) {
                if (i === state.currentPage) {
                    html += `<button class="pagination-btn" style="background-color: var(--accent); color: white;">${i + 1}</button>`;
                } else {
                    html += `<button class="pagination-btn" onclick="goToPage(${i})">${i + 1}</button>`;
                }
            }

            if (state.currentPage < totalPages - 1) {
                html += '<button class="pagination-btn" onclick="goToPage(' + (state.currentPage + 1) + ')">Next</button>';
                html += '<button class="pagination-btn" onclick="goToPage(' + (totalPages - 1) + ')">Last</button>';
            }

            container.innerHTML = html;
            container.style.display = 'flex';
        }

        function goToPage(page) {
            state.currentPage = page;
            renderResults();
            document.getElementById('resultsTableContainer').scrollTop = 0;
        }

        // ===== Export Functions =====
        function exportResults(format) {
            if (!state.queryResults || state.queryResults.length === 0) {
                showAlert('No results to export', 'error');
                return;
            }

            let content, filename, type;

            if (format === 'csv') {
                content = state.columns.join(',') + '\n';
                state.queryResults.forEach(row => {
                    const vals = state.columns.map(col => {
                        const val = row[col];
                        if (val === null) return '';
                        if (typeof val === 'string' && (val.includes(',') || val.includes('"'))) {
                            return '"' + val.replace(/"/g, '""') + '"';
                        }
                        return val;
                    });
                    content += vals.join(',') + '\n';
                });
                filename = 'export_' + Date.now() + '.csv';
                type = 'text/csv';
            } else {
                content = JSON.stringify(state.queryResults, null, 2);
                filename = 'export_' + Date.now() + '.json';
                type = 'application/json';
            }

            const blob = new Blob([content], { type });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);

            showAlert(`Exported ${state.queryResults.length} rows to ${format.toUpperCase()}`, 'success');
        }

        // ===== Visualizer =====
        function toggleVisualizer() {
            const viz = document.getElementById('visualizerContainer');
            viz.classList.toggle('active');
            if (viz.classList.contains('active')) {
                updateChartSelects();
                renderChart();
            }
        }

        function updateChartSelects() {
            const xSelect = document.getElementById('chartX');
            const ySelect = document.getElementById('chartY');
            xSelect.innerHTML = '<option value="">Select X axis</option>';
            ySelect.innerHTML = '<option value="">Select Y axis</option>';

            state.columns.forEach(col => {
                xSelect.appendChild(new Option(col, col));
                ySelect.appendChild(new Option(col, col));
            });

            if (state.columns.length > 0) xSelect.value = state.columns[0];
            if (state.columns.length > 1) ySelect.value = state.columns[1];
        }

        function renderChart() {
            if (!state.queryResults || state.queryResults.length === 0) return;

            const type = document.getElementById('chartType').value;
            const xCol = document.getElementById('chartX').value;
            const yCol = document.getElementById('chartY').value;

            if (!xCol || !yCol) return;

            const labels = state.queryResults.map(r => r[xCol]);
            const data = state.queryResults.map(r => r[yCol]);

            const ctx = document.getElementById('resultsChart').getContext('2d');
            if (state.chart) state.chart.destroy();

            state.chart = new Chart(ctx, {
                type: type === 'pie' ? 'doughnut' : type,
                data: {
                    labels,
                    datasets: [{
                        label: yCol,
                        data,
                        backgroundColor: type === 'pie' ? [
                            'rgba(108, 92, 231, 0.8)',
                            'rgba(116, 184, 255, 0.8)',
                            'rgba(0, 212, 170, 0.8)',
                            'rgba(255, 159, 243, 0.8)',
                            'rgba(255, 107, 107, 0.8)',
                        ] : 'rgba(108, 92, 231, 0.7)',
                        borderColor: 'rgba(108, 92, 231, 1)',
                        borderWidth: 1,
                        tension: 0.3,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            labels: { color: 'rgba(232, 233, 243, 0.8)' }
                        }
                    },
                    scales: type !== 'pie' ? {
                        y: {
                            ticks: { color: 'rgba(232, 233, 243, 0.6)' },
                            grid: { color: 'rgba(50, 58, 77, 0.3)' }
                        },
                        x: {
                            ticks: { color: 'rgba(232, 233, 243, 0.6)' },
                            grid: { color: 'rgba(50, 58, 77, 0.3)' }
                        }
                    } : {}
                }
            });
        }

        // ===== Tab Management =====
        function createNewTab() {
            const tabsContainer = document.getElementById('queryTabs');
            const tabId = 'tab-' + Date.now();
            const html = `
                <button class="tab active" data-tab="${tabId}">
                    Untitled Query
                    <span class="tab-close" onclick="closeTab('${tabId}')">✕</span>
                </button>
            `;
            tabsContainer.insertAdjacentHTML('beforeend', html);
            document.querySelector(`button[data-tab="${tabId}"]`).addEventListener('click', switchTab.bind(null, tabId));
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelector(`button[data-tab="${tabId}"]`).classList.add('active');
            state.currentQuery = document.getElementById('queryEditor').value;
        }

        function closeTab(tabId) {
            const tab = document.querySelector(`button[data-tab="${tabId}"]`);
            tab.remove();
            if (document.querySelectorAll('.tab').length === 0) {
                createNewTab();
            }
        }

        // ===== History =====
        function addToHistory(query) {
            state.queryHistory.unshift({
                id: Date.now(),
                query,
                timestamp: new Date().toLocaleTimeString()
            });
            if (state.queryHistory.length > MAX_HISTORY) {
                state.queryHistory.pop();
            }
            localStorage.setItem('queryHistory', JSON.stringify(state.queryHistory));
            loadHistory();
        }

        function loadHistory() {
            const container = document.getElementById('historyContainer');
            if (state.queryHistory.length === 0) {
                container.innerHTML = '<div class="empty-state">No queries yet</div>';
                return;
            }

            let html = '';
            state.queryHistory.forEach(item => {
                html += `
                    <div class="history-item">
                        <div class="history-timestamp">${item.timestamp}</div>
                        <div class="history-query">${escapeHtml(item.query.substring(0, 100))}</div>
                        <div class="history-actions">
                            <button class="history-btn" onclick="rerunQuery('${item.id}')">⟲ Run</button>
                            <button class="history-btn" onclick="copyQuery('${item.id}')">📋 Copy</button>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
        }

        function rerunQuery(id) {
            const item = state.queryHistory.find(h => h.id === parseInt(id));
            if (item) {
                document.getElementById('queryEditor').value = item.query;
                state.currentQuery = item.query;
                updateLineNumbers();
                executeQuery();
            }
        }

        function copyQuery(id) {
            const item = state.queryHistory.find(h => h.id === parseInt(id));
            if (item) {
                navigator.clipboard.writeText(item.query);
                showAlert('Copied to clipboard', 'success');
            }
        }

        // ===== Connections =====
        async function saveConnection() {
            const name = document.getElementById('connName').value.trim();
            const type = document.getElementById('connType').value;
            const path = document.getElementById('sqlitePath').value.trim();
            const connStr = document.getElementById('postgresConn').value.trim();

            if (!name || (type === 'sqlite' && !path) || (type === 'postgresql' && !connStr)) {
                showAlert('Please fill in all required fields', 'error');
                return;
            }

            const conn = {
                id: 'conn-' + Date.now(),
                name,
                type,
                sqlite_path: type === 'sqlite' ? path : null,
                postgresql_connection_string: type === 'postgresql' ? connStr : null
            };

            state.connections.push(conn);
            localStorage.setItem('connections', JSON.stringify(state.connections));
            closeModal('connectionModal');
            document.getElementById('connName').value = '';
            document.getElementById('sqlitePath').value = '';
            document.getElementById('postgresConn').value = '';
            initializeConnections();
            showAlert('Connection added', 'success');
        }

        async function testConnection() {
            if (!state.selectedConnection) {
                showAlert('Please select a connection', 'error');
                return;
            }

            const btn = document.getElementById('testConnectionBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span>';

            try {
                const resp = await fetch(`${API_BASE}/database/schema?connection_id=${encodeURIComponent(state.selectedConnection)}`);
                if (resp.ok) {
                    showAlert('Connection successful!', 'success');
                } else {
                    showAlert('Connection failed', 'error');
                }
            } catch (err) {
                showAlert(`Error: ${err.message}`, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = 'Test';
            }
        }

        // ===== Utilities =====
        function openModal(id) {
            document.getElementById(id).classList.add('active');
        }

        function closeModal(id) {
            document.getElementById(id).classList.remove('active');
        }

        function showAlert(message, type) {
            const container = document.querySelector('.query-input-area');
            const alert = document.createElement('div');
            alert.className = `alert ${type}`;
            alert.textContent = message;
            container.insertBefore(alert, container.firstChild);
            setTimeout(() => alert.remove(), 4000);
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function togglePanel(panel) {
            const panelEl = panel === 'left' ? document.querySelector('.left-panel') : document.querySelector('.right-panel');
            panelEl.style.display = panelEl.style.display === 'none' ? 'flex' : 'none';
        }

        function confirmSaveQuery() {
            // Placeholder for save query functionality
            closeModal('saveQueryModal');
            showAlert('Query saved', 'success');
        }

        // Initialize
        updateLineNumbers();
    
