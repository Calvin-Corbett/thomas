
        // State
        const state = {
            currentChannel: 'general',
            currentTab: 'timeline',
            memories: [],
            facts: [],
            documents: [],
            editingFactId: null
        };

        // API Endpoints
        const API = {
            getMemory: () => `/api/memory?channel=${state.currentChannel}`,
            getFacts: () => `/api/memory/facts`,
            addFact: () => `/api/memory/facts`,
            updateFact: (id) => `/api/memory/facts/${id}`,
            deleteFact: (id) => `/api/memory/facts/${id}`,
            getDocuments: () => `/api/rag/documents`,
            searchRag: () => `/api/rag/search`,
            uploadDocument: () => `/api/rag/upload`,
            getStats: () => `/api/memory/stats`
        };

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            setupEventListeners();
            loadChannels();
            loadData();
        });

        function setupEventListeners() {
            // Tab switching
            document.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', () => switchTab(tab.dataset.tab));
            });

            // Channel switching
            document.addEventListener('click', (e) => {
                if (e.target.classList.contains('channel-item')) {
                    switchChannel(e.target.dataset.channel);
                }
            });

            // Timeline filters
            document.getElementById('typeFilter').addEventListener('change', filterTimeline);
            document.getElementById('dateFilter').addEventListener('change', filterTimeline);

            // Fact management
            document.getElementById('addFactBtn').addEventListener('click', openFactModal);
            document.getElementById('factForm').addEventListener('submit', saveFact);

            // Upload
            const uploadZone = document.getElementById('uploadZone');
            uploadZone.addEventListener('click', () => document.getElementById('fileInput').click());
            uploadZone.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadZone.classList.add('dragover');
            });
            uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
            uploadZone.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadZone.classList.remove('dragover');
                handleFileUpload(e.dataTransfer.files);
            });
            document.getElementById('fileInput').addEventListener('change', (e) => handleFileUpload(e.target.files));

            // Search
            document.getElementById('searchBtn').addEventListener('click', performSearch);
            document.getElementById('searchInput').addEventListener('keyup', (e) => {
                if (e.key === 'Enter') performSearch();
            });

            // Buttons
            document.getElementById('refreshBtn').addEventListener('click', loadData);
            document.getElementById('exportBtn').addEventListener('click', exportData);
            document.getElementById('importBtn').addEventListener('click', () => document.getElementById('importModal').classList.add('active'));
            document.getElementById('importForm').addEventListener('submit', importData);
        }

        async function loadChannels() {
            try {
                const response = await fetch('/api/memory/channels');
                const data = await response.json();
                renderChannels(data.channels || ['general']);
            } catch (error) {
                console.error('Error loading channels:', error);
            }
        }

        function renderChannels(channels) {
            const selector = document.getElementById('channelSelector');
            selector.innerHTML = channels.map(ch => `
                <div class="channel-item ${ch === state.currentChannel ? 'active' : ''}" data-channel="${ch}">
                    # ${ch}
                </div>
            `).join('');
        }

        function switchChannel(channel) {
            state.currentChannel = channel;
            document.querySelectorAll('.channel-item').forEach(el => el.classList.remove('active'));
            document.querySelector(`[data-channel="${channel}"]`).classList.add('active');
            loadData();
        }

        function switchTab(tab) {
            state.currentTab = tab;
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.content-area').forEach(el => el.classList.remove('active'));
            document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
            document.getElementById(tab).classList.add('active');
        }

        async function loadData() {
            await Promise.all([loadMemories(), loadFacts(), loadDocuments(), loadStats()]);
        }

        async function loadMemories() {
            try {
                const response = await fetch(API.getMemory());
                const data = await response.json();
                state.memories = data.memories || [];
                renderTimeline(state.memories);
            } catch (error) {
                console.error('Error loading memories:', error);
                document.getElementById('timelineContent').innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">⚠️</div>
                        <div class="empty-title">Error loading memories</div>
                    </div>
                `;
            }
        }

        async function loadFacts() {
            try {
                const response = await fetch(API.getFacts());
                const data = await response.json();
                state.facts = data.facts || [];
                renderFacts(state.facts);
            } catch (error) {
                console.error('Error loading facts:', error);
            }
        }

        async function loadDocuments() {
            try {
                const response = await fetch(API.getDocuments());
                const data = await response.json();
                state.documents = data.documents || [];
                renderDocuments(state.documents);
            } catch (error) {
                console.error('Error loading documents:', error);
            }
        }

        async function loadStats() {
            try {
                const response = await fetch(API.getStats());
                const data = await response.json();
                document.getElementById('memoryCount').textContent = data.memoryCount || 0;
                document.getElementById('factCount').textContent = data.factCount || 0;
                document.getElementById('docCount').textContent = data.docCount || 0;
                document.getElementById('indexSize').textContent = formatBytes(data.indexSize || 0);
            } catch (error) {
                console.error('Error loading stats:', error);
            }
        }

        function renderTimeline(memories) {
            const content = document.getElementById('timelineContent');
            if (!memories.length) {
                content.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">📝</div>
                        <div class="empty-title">No memories yet</div>
                        <div>Memories will appear here as Thomas learns about you</div>
                    </div>
                `;
                return;
            }

            content.innerHTML = memories.map(mem => `
                <div class="memory-card">
                    <div class="memory-header">
                        <span class="memory-type ${mem.type}">${mem.type}</span>
                        <span class="memory-timestamp">${formatDate(mem.timestamp)}</span>
                    </div>
                    <div class="memory-content">${escapeHtml(mem.content)}</div>
                    <div class="memory-footer">
                        <span class="memory-relevance">Channel: ${mem.channel}</span>
                        <span class="relevance-score">${(mem.relevance * 100).toFixed(0)}% relevant</span>
                    </div>
                </div>
            `).join('');
        }

        function renderFacts(facts) {
            const content = document.getElementById('factsContent');
            if (!facts.length) {
                content.innerHTML = `
                    <div class="empty-state" style="grid-column: 1/-1;">
                        <div class="empty-icon">💡</div>
                        <div class="empty-title">No facts yet</div>
                        <div>Add important facts about yourself, your preferences, or project context</div>
                    </div>
                `;
                return;
            }

            content.innerHTML = facts.map(fact => `
                <div class="fact-card">
                    <div class="fact-category">${fact.category}</div>
                    <div class="fact-title">${escapeHtml(fact.title)}</div>
                    <div class="fact-value">${escapeHtml(fact.value)}</div>
                    <div class="fact-actions">
                        <button class="btn" onclick="editFact('${fact.id}')" style="flex: 1;">Edit</button>
                        <button class="btn btn-danger" onclick="deleteFact('${fact.id}')" style="flex: 1;">Delete</button>
                    </div>
                </div>
            `).join('');
        }

        function renderDocuments(docs) {
            const content = document.getElementById('documentsContent');
            if (!docs.length) {
                content.innerHTML = `
                    <div class="empty-state" style="grid-column: 1/-1;">
                        <div class="empty-icon">📚</div>
                        <div class="empty-title">No documents indexed</div>
                        <div>Upload documents to build your knowledge base</div>
                    </div>
                `;
                return;
            }

            content.innerHTML = docs.map(doc => `
                <div class="document-card">
                    <div class="document-icon">${getFileIcon(doc.name)}</div>
                    <div class="document-name">${escapeHtml(doc.name)}</div>
                    <div class="document-meta">
                        <div class="document-meta-item">
                            <span>Size:</span>
                            <span>${formatBytes(doc.size)}</span>
                        </div>
                        <div class="document-meta-item">
                            <span>Indexed:</span>
                            <span>${formatDate(doc.indexedAt)}</span>
                        </div>
                        <div class="document-meta-item">
                            <span>Chunks:</span>
                            <span>${doc.chunks || 0}</span>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function filterTimeline() {
            const typeFilter = document.getElementById('typeFilter').value;
            const dateFilter = document.getElementById('dateFilter').value;

            const filtered = state.memories.filter(mem => {
                const typeMatch = !typeFilter || mem.type === typeFilter;
                const dateMatch = !dateFilter || formatDate(mem.timestamp).startsWith(dateFilter);
                return typeMatch && dateMatch;
            });

            renderTimeline(filtered);
        }

        function openFactModal() {
            state.editingFactId = null;
            document.getElementById('factModalTitle').textContent = 'Add New Fact';
            document.getElementById('factForm').reset();
            document.getElementById('factModal').classList.add('active');
        }

        function closeFactModal() {
            document.getElementById('factModal').classList.remove('active');
            state.editingFactId = null;
        }

        async function editFact(id) {
            const fact = state.facts.find(f => f.id === id);
            if (!fact) return;

            state.editingFactId = id;
            document.getElementById('factModalTitle').textContent = 'Edit Fact';
            document.getElementById('factCategory').value = fact.category;
            document.getElementById('factTitle').value = fact.title;
            document.getElementById('factValue').value = fact.value;
            document.getElementById('factModal').classList.add('active');
        }

        async function saveFact(e) {
            e.preventDefault();
            const category = document.getElementById('factCategory').value;
            const title = document.getElementById('factTitle').value;
            const value = document.getElementById('factValue').value;

            try {
                const method = state.editingFactId ? 'PUT' : 'POST';
                const url = state.editingFactId
                    ? API.updateFact(state.editingFactId)
                    : API.addFact();

                const response = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category, title, value })
                });

                if (response.ok) {
                    closeFactModal();
                    loadFacts();
                }
            } catch (error) {
                console.error('Error saving fact:', error);
            }
        }

        async function deleteFact(id) {
            if (!confirm('Delete this fact?')) return;
            try {
                const response = await fetch(API.deleteFact(id), { method: 'DELETE' });
                if (response.ok) loadFacts();
            } catch (error) {
                console.error('Error deleting fact:', error);
            }
        }

        async function handleFileUpload(files) {
            const formData = new FormData();
            for (const file of files) {
                if (file.size > 10 * 1024 * 1024) {
                    alert(`${file.name} exceeds 10MB limit`);
                    continue;
                }
                formData.append('files', file);
            }

            if (formData.has('files')) {
                try {
                    const response = await fetch(API.uploadDocument(), {
                        method: 'POST',
                        body: formData
                    });
                    if (response.ok) {
                        loadDocuments();
                        document.getElementById('fileInput').value = '';
                    }
                } catch (error) {
                    console.error('Error uploading files:', error);
                }
            }
        }

        async function performSearch() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) return;

            const content = document.getElementById('searchContent');
            content.innerHTML = '<div class="loading"><div class="spinner"></div>Searching...</div>';

            try {
                const response = await fetch(API.searchRag(), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query, limit: 10 })
                });
                const data = await response.json();

                if (!data.results || data.results.length === 0) {
                    content.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">🔍</div>
                            <div class="empty-title">No results found</div>
                            <div>Try different keywords</div>
                        </div>
                    `;
                    return;
                }

                content.innerHTML = data.results.map(result => `
                    <div class="search-result">
                        <div class="result-header">
                            <div class="result-title">${escapeHtml(result.title)}</div>
                            <div class="result-source">${result.source}</div>
                        </div>
                        <div class="result-content">${escapeHtml(result.snippet)}</div>
                        <span class="result-relevance">Relevance: ${(result.score * 100).toFixed(0)}%</span>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Error searching:', error);
                content.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Search error</div></div>';
            }
        }

        async function exportData() {
            try {
                const memories = state.memories;
                const facts = state.facts;
                const documents = state.documents;
                const timestamp = new Date().toISOString();

                const data = { memories, facts, documents, exportedAt: timestamp };
                const json = JSON.stringify(data, null, 2);
                const blob = new Blob([json], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `thomas-memory-${timestamp.split('T')[0]}.json`;
                a.click();
                URL.revokeObjectURL(url);
            } catch (error) {
                console.error('Error exporting:', error);
            }
        }

        async function importData(e) {
            e.preventDefault();
            const file = document.getElementById('importFile').files[0];
            if (!file) return;

            try {
                const text = await file.text();
                const data = JSON.parse(text);

                const formData = new FormData();
                formData.append('backup', file);

                const response = await fetch('/api/memory/import', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    document.getElementById('importModal').classList.remove('active');
                    loadData();
                }
            } catch (error) {
                console.error('Error importing:', error);
                alert('Invalid backup file');
            }
        }

        function closeImportModal() {
            document.getElementById('importModal').classList.remove('active');
        }

        // Utilities
        function formatDate(timestamp) {
            if (!timestamp) return 'Unknown';
            const date = new Date(timestamp);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        function formatBytes(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function getFileIcon(filename) {
            const ext = filename.split('.').pop().toLowerCase();
            const icons = {
                pdf: '📕', docx: '📄', txt: '📝', md: '📋',
                doc: '📄', jpg: '🖼️', png: '🖼️'
            };
            return icons[ext] || '📄';
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    
