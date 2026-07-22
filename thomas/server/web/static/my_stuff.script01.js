(function () {
    var SCRIPT_VERSION = '20260721-modernized-1';

    // The shared workspace shell owns initial theme and postMessage handling.
    // Storage events keep an already-open standalone tab in sync as well.
    window.addEventListener('storage', function (event) {
        if (event.key !== 'thomas_chat_theme' || !event.newValue || !window.ThomasWorkspaceShell) return;
        window.ThomasWorkspaceShell.applyTheme(event.newValue, { persist: false });
    });

    var state = {
        projects: [],
        installedPlugins: [],
        loading: false,
        activeProjectId: '',
        activeProject: null,
        statusMessage: 'Loading Library...',
        statusTone: 'info',
        importOpen: false,
        importBusy: false,
        drag: null,
        suppressClickUntil: 0,
        detailResult: null,
        forgeBuilds: [],
        viewMode: 'library',
        libraryFilter: 'all',
        libraryQuery: '',
        activeLibraryItem: null
    };

    var SNAP = {
        left: 32,
        top: 36,
        width: 170,
        height: 180,
        tileWidth: 148,
        tileHeight: 156
    };

    var elements = {
        boardView: document.getElementById('boardView'),
        board: document.getElementById('board'),
        installedAppsShelf: document.getElementById('installedAppsShelf'),
        installedAppsList: document.getElementById('installedAppsList'),
        stuffSearch: document.getElementById('stuffSearch'),
        libraryTitle: document.getElementById('libraryTitle'),
        librarySummary: document.getElementById('librarySummary'),
        itemDetail: document.getElementById('itemDetail'),
        itemDetailContent: document.getElementById('itemDetailContent'),
        detailView: document.getElementById('detailView'),
        detailShell: document.getElementById('detailShell'),
        statusPill: document.getElementById('statusPill'),
        statusText: document.getElementById('statusText'),
        refreshButton: document.getElementById('refreshButton'),
        openImportButton: document.getElementById('openImportButton'),
        backToBoardButton: document.getElementById('backToBoardButton'),
        importSheet: document.getElementById('importSheet'),
        closeImportButton: document.getElementById('closeImportButton'),
        dropzone: document.getElementById('dropzone'),
        pickFolderButton: document.getElementById('pickFolderButton'),
        toggleAdvancedButton: document.getElementById('toggleAdvancedButton'),
        advancedImport: document.getElementById('advancedImport'),
        projectPathInput: document.getElementById('projectPathInput'),
        projectNameInput: document.getElementById('projectNameInput'),
        submitImportButton: document.getElementById('submitImportButton'),
        importNote: document.getElementById('importNote')
    };

    function safeString(value) {
        return typeof value === 'string' ? value : (value == null ? '' : String(value));
    }

    function escapeHtml(value) {
        return safeString(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatRelativeTime(value) {
        var raw = safeString(value);
        if (!raw) return 'Not yet';
        var dt = new Date(raw);
        if (Number.isNaN(dt.getTime())) return 'Not yet';
        var deltaMs = Date.now() - dt.getTime();
        var minute = 60 * 1000;
        var hour = 60 * minute;
        var day = 24 * hour;
        if (Math.abs(deltaMs) < minute) return 'just now';
        if (Math.abs(deltaMs) < hour) return Math.round(deltaMs / minute) + 'm ago';
        if (Math.abs(deltaMs) < day) return Math.round(deltaMs / hour) + 'h ago';
        return Math.round(deltaMs / day) + 'd ago';
    }

    function toneForState(readinessState) {
        var value = safeString(readinessState).toLowerCase();
        if (value === 'launch_ready' || value === 'open_ready') return 'good';
        if (value === 'preparation_required' || value === 'review_needed') return 'warn';
        if (value === 'environment_issue' || value === 'missing') return 'bad';
        return 'info';
    }

    function reservedModuleSlots() {
        return 0;
    }

    function pluginPosition(plugin, index) {
        var rawSlot = Number(plugin && plugin.my_stuff_slot);
        if (Number.isFinite(rawSlot) && rawSlot > 0) return slotToPosition(rawSlot);
        return slotToPosition(1 + Math.max(0, index || 0));
    }

    function pluginTone(plugin) {
        return plugin && plugin.enabled === false ? 'warn' : 'good';
    }

    function pluginMeta(plugin) {
        return safeString(plugin && plugin.subtitle)
            || safeString(plugin && plugin.description)
            || safeString(plugin && plugin.marketplace_type)
            || 'Thomas module';
    }

    function pluginLabel(plugin) {
        return safeString(plugin && plugin.display_name)
            || safeString(plugin && plugin.surface_title)
            || safeString(plugin && plugin.plugin_id)
            || 'Module';
    }

    function pluginMode(plugin) {
        return safeString(plugin && (plugin.mode_id || plugin.workspace_id || plugin.plugin_id)).toLowerCase();
    }

    function pluginId(plugin) {
        return safeString(plugin && plugin.plugin_id).toLowerCase();
    }

    function pluginShelfRank(plugin) {
        var id = pluginId(plugin);
        var mode = pluginMode(plugin);
        var label = pluginLabel(plugin).toLowerCase();
        if (id === 'paper-trading' || mode === 'paper_trading' || label === 'paper trading') return 0;
        if (label.indexOf('paper trading') >= 0) return 0;
        if (id === 'freedom-transit' || mode === 'freedom_transit' || label === 'workforce') return 10;
        return 100 + (Number(plugin && plugin.default_nav_order) || 900);
    }

    function pluginInitials(plugin) {
        var label = pluginLabel(plugin).replace(/[^a-z0-9 ]/gi, ' ').trim();
        if (!label) return 'APP';
        var parts = label.split(/\s+/).filter(Boolean);
        if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
        return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
    }

    function installedWorkspacePlugins() {
        var seen = {};
        return (Array.isArray(state.installedPlugins) ? state.installedPlugins : [])
            .filter(function (plugin) {
                if (!plugin || plugin.enabled === false) return false;
                if (safeString(plugin.left_nav_behavior).toLowerCase() !== 'workspace') return false;
                var mode = pluginMode(plugin);
                if (!mode || seen[mode]) return false;
                seen[mode] = true;
                return Boolean(pluginLabel(plugin));
            })
            .sort(function (left, right) {
                var leftRank = pluginShelfRank(left);
                var rightRank = pluginShelfRank(right);
                if (leftRank !== rightRank) return leftRank - rightRank;
                var leftOrder = Number(left && left.default_nav_order) || 900;
                var rightOrder = Number(right && right.default_nav_order) || 900;
                if (leftOrder !== rightOrder) return leftOrder - rightOrder;
                return pluginLabel(left).localeCompare(pluginLabel(right));
            });
    }

    function findInstalledPluginByMode(modeRaw) {
        var mode = safeString(modeRaw).toLowerCase();
        if (!mode) return null;
        return installedWorkspacePlugins().find(function (row) {
            return pluginMode(row) === mode || safeString(row && row.workspace_id).toLowerCase() === mode;
        }) || null;
    }

    function launchInstalledPlugin(plugin) {
        var mode = pluginMode(plugin);
        var url = safeString(plugin && plugin.surface_url);
        try {
            if (mode && window.parent && window.parent !== window && typeof window.parent.setSidebarNavMode === 'function') {
                window.parent.setSidebarNavMode(mode);
                return;
            }
        } catch (_error) {}
        if (url) {
            window.location.href = url;
            return;
        }
        setStatus('That module does not expose a launch surface yet.', 'warn');
    }

    function launchInstalledPluginMode(modeRaw) {
        var plugin = findInstalledPluginByMode(modeRaw);
        launchInstalledPlugin(plugin || { mode_id: safeString(modeRaw) });
    }

    function statusToneClass(tone) {
        var value = safeString(tone).toLowerCase();
        return value === 'good' || value === 'warn' || value === 'bad' || value === 'info' ? value : 'info';
    }

    function setStatus(message, tone) {
        state.statusMessage = safeString(message) || 'Ready.';
        state.statusTone = statusToneClass(tone);
        renderStatus();
    }

    function renderStatus() {
        if (elements.statusText) {
            elements.statusText.textContent = state.statusMessage;
        }
        if (elements.statusPill) {
            elements.statusPill.textContent = state.activeProject ? 'Project Detail' : (state.viewMode === 'arrange' ? 'Arrange' : 'Library');
            elements.statusPill.className = 'stuff-status-pill is-' + statusToneClass(state.activeProject && state.activeProject.readiness && state.activeProject.readiness.state ? toneForState(state.activeProject.readiness.state) : state.statusTone);
        }
    }

    async function fetchJson(url, options) {
        var response = await fetch(url, Object.assign({
            headers: { 'Accept': 'application/json' }
        }, options || {}));
        var text = await response.text();
        var payload = {};
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch (_error) {
                payload = {};
            }
        }
        if (!response.ok) {
            throw new Error((payload && (payload.error || payload.message || payload.detail)) || text || (response.status + ' ' + response.statusText));
        }
        return payload || {};
    }

    function installedPluginsFromPayload(payload) {
        if (Array.isArray(payload && payload.plugins)) return payload.plugins;
        if (Array.isArray(payload && payload.installed)) return payload.installed;
        return [];
    }

    async function refreshInstalledPlugins() {
        try {
            var installedPayload = await fetchJson(window.location.origin + '/api/marketplace/installed');
            state.installedPlugins = installedPluginsFromPayload(installedPayload);
        } catch (_error) {
            state.installedPlugins = [];
        }
        renderInstalledAppsShelf();
        return state.installedPlugins;
    }

    function boardColumnCount() {
        var liveWidth = elements.board instanceof HTMLElement ? elements.board.clientWidth : 0;
        var fallbackWidth = Math.max(560, document.documentElement.clientWidth - 100);
        var available = Math.max(liveWidth, fallbackWidth) - SNAP.left - 24;
        return Math.max(1, Math.floor((available - SNAP.tileWidth) / SNAP.width) + 1);
    }

    function slotToPosition(slot) {
        var normalized = Math.max(0, Number(slot) || 0);
        var columns = boardColumnCount();
        var col = normalized % columns;
        var row = Math.floor(normalized / columns);
        return {
            x: SNAP.left + col * SNAP.width,
            y: SNAP.top + row * SNAP.height
        };
    }

    function positionToSlot(pos) {
        var x = Number(pos && pos.x) || SNAP.left;
        var y = Number(pos && pos.y) || SNAP.top;
        var columns = boardColumnCount();
        var col = Math.max(0, Math.min(columns - 1, Math.round((x - SNAP.left) / SNAP.width)));
        var row = Math.max(0, Math.round((y - SNAP.top) / SNAP.height));
        return row * columns + col;
    }

    function boardKey(pos) {
        return String(Number(pos && pos.x) || 0) + ':' + String(Number(pos && pos.y) || 0);
    }

    function projectPosition(project) {
        var position = project && project.board_position && typeof project.board_position === 'object'
            ? project.board_position
            : slotToPosition(1);
        return {
            x: Number(position.x) || SNAP.left,
            y: Number(position.y) || SNAP.top
        };
    }

    function projectBoardPosition(project, moduleSlots) {
        var slot = Math.max(1, positionToSlot(projectPosition(project)));
        return slotToPosition(slot + Math.max(0, Number(moduleSlots) || 0));
    }

    function storagePositionFromBoardPosition(position, moduleSlots) {
        var slot = Math.max(1, positionToSlot(position) - Math.max(0, Number(moduleSlots) || 0));
        return slotToPosition(slot);
    }

    function updateBoardMinHeight(positions) {
        if (!elements.board) return;
        var maxY = SNAP.top;
        (Array.isArray(positions) ? positions : []).forEach(function (position) {
            maxY = Math.max(maxY, Number(position && position.y) || SNAP.top);
        });
        elements.board.style.minHeight = String(Math.max(520, maxY + SNAP.tileHeight + SNAP.top)) + 'px';
    }

    function normalizeProjectPositions(projects) {
        var rows = Array.isArray(projects) ? projects : [];
        var usedSlots = { 0: true };
        var changes = [];
        rows
            .slice()
            .sort(function (left, right) {
                var leftPos = projectPosition(left);
                var rightPos = projectPosition(right);
                return leftPos.y - rightPos.y || leftPos.x - rightPos.x || safeString(left && left.name).localeCompare(safeString(right && right.name));
            })
            .forEach(function (project, index) {
                if (!project || typeof project !== 'object') return;
                var original = projectPosition(project);
                var slot = Math.max(1, positionToSlot(original));
                while (usedSlots[slot]) {
                    slot += 1;
                }
                usedSlots[slot] = true;
                var next = slotToPosition(slot);
                if (next.x !== original.x || next.y !== original.y) {
                    project.board_position = { x: next.x, y: next.y };
                    changes.push({ id: safeString(project.id), x: next.x, y: next.y });
                }
                if (!safeString(project.id) && index >= 0) {
                    project.board_position = { x: next.x, y: next.y };
                }
            });
        return changes;
    }

    function findNextOpenPosition(projectId, preferred) {
        var occupied = { '32:36': true };
        (state.projects || []).forEach(function (project) {
            if (!project || safeString(project.id) === safeString(projectId)) return;
            occupied[boardKey(projectPosition(project))] = true;
        });
        var slot = Math.max(1, positionToSlot(preferred));
        while (occupied[boardKey(slotToPosition(slot))]) {
            slot += 1;
        }
        return slotToPosition(slot);
    }

    function openImportSheet(note) {
        state.importOpen = true;
        if (elements.importSheet) elements.importSheet.classList.remove('hidden');
        if (elements.importNote && note) elements.importNote.textContent = safeString(note);
    }

    function closeImportSheet() {
        state.importOpen = false;
        if (elements.importSheet) elements.importSheet.classList.add('hidden');
        if (elements.dropzone) elements.dropzone.classList.remove('is-active');
        if (elements.importNote) {
            elements.importNote.textContent = 'Best path for everyday users: choose a folder and let Thomas do the first read for you.';
        }
    }

    function openBoardView() {
        state.activeProjectId = '';
        state.activeProject = null;
        state.detailResult = null;
        if (elements.detailView) elements.detailView.classList.add('hidden');
        setViewMode(state.viewMode);
    }

    async function openProject(projectId, options) {
        if (!projectId) return;
        state.activeProjectId = projectId;
        if (!(options && options.preserveResult)) {
            state.detailResult = null;
        }
        setStatus('Opening project page...', 'info');
        var payload = await fetchJson('/api/local/projects/' + encodeURIComponent(projectId));
        state.activeProject = payload && payload.project ? payload.project : null;
        if (elements.installedAppsShelf) elements.installedAppsShelf.classList.add('hidden');
        if (elements.boardView) elements.boardView.classList.add('hidden');
        if (elements.detailView) elements.detailView.classList.remove('hidden');
        renderDetail();
        setStatus('Project page ready.', toneForState(state.activeProject && state.activeProject.readiness && state.activeProject.readiness.state));
    }

    async function refresh(options) {
        var preserveStatus = Boolean(options && options.preserveStatus);
        state.loading = true;
        if (!preserveStatus) {
            setStatus('Refreshing Library...', 'info');
        }
        var installedPromise = refreshInstalledPlugins();
        var buildsPromise = loadForgeBuilds({ deferRender: true });
        try {
            var payload = await fetchJson('/api/local/projects');
            state.projects = Array.isArray(payload && payload.projects) ? payload.projects : [];
            await installedPromise;
            await buildsPromise;
            var changedPositions = normalizeProjectPositions(state.projects);
            if (changedPositions.length) {
                changedPositions.slice(0, 12).forEach(function (row) {
                    if (row && row.id) {
                        void persistBoardPosition(row.id, row.x, row.y, true);
                    }
                });
            }
            if (state.activeProjectId) {
                var match = state.projects.find(function (project) {
                    return safeString(project && project.id) === state.activeProjectId;
                });
                if (!match) {
                    openBoardView();
                }
            }
            renderBoard();
            if (!preserveStatus) {
                var moduleCount = installedWorkspacePlugins().length;
                setStatus(
                    'Library ready. '
                    + String(moduleCount) + ' installed app' + (moduleCount === 1 ? '' : 's')
                    + ' and '
                    + String(state.projects.length) + ' project' + (state.projects.length === 1 ? '' : 's')
                    + '/artifact' + (state.projects.length === 1 ? '' : 's') + ' loaded.',
                    'info'
                );
            } else {
                renderStatus();
            }
        } catch (error) {
            setStatus(safeString(error && error.message) || 'Could not load Library.', 'bad');
        } finally {
            state.loading = false;
        }
    }

    async function importProject(pathValue, nameValue, importMethod) {
        var path = safeString(pathValue);
        if (!path) {
            setStatus('Choose a project folder first.', 'warn');
            return;
        }
        state.importBusy = true;
        setStatus('Thomas is reading that repo...', 'info');
        try {
            var payload = await fetchJson('/api/local/projects/import', {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    path: path,
                    name: safeString(nameValue),
                    import_method: safeString(importMethod) || 'path'
                })
            });
            closeImportSheet();
            await refresh({ preserveStatus: true });
            var project = payload && payload.project ? payload.project : null;
            setStatus('Imported ' + safeString(project && project.name) + '. Thomas staged the repo and built its project page.', 'good');
            if (project && project.id) {
                await openProject(project.id);
            }
        } catch (error) {
            setStatus(safeString(error && error.message) || 'Could not import that project.', 'bad');
        } finally {
            state.importBusy = false;
        }
    }

    async function chooseFolder() {
        setStatus('Opening the local folder picker...', 'info');
        try {
            var payload = await fetchJson('/api/local/projects/pick-folder', { method: 'POST' });
            if (payload && payload.cancelled) {
                setStatus('Folder picker cancelled.', 'info');
                return;
            }
            if (elements.projectPathInput) {
                elements.projectPathInput.value = safeString(payload && payload.path);
            }
            await importProject(payload && payload.path, elements.projectNameInput && elements.projectNameInput.value, 'picker');
        } catch (error) {
            setStatus(safeString(error && error.message) || 'Could not open the folder picker.', 'bad');
        }
    }

    // -- Forge Code deliverables recorded in Library --------------------------
    // A run that produced a coherent deliverable (a built page/app, a doc, an
    // image, a data file) is registered server-side at run completion; we surface
    // those here so a build becomes a durable, openable thing -- not a diff that
    // scrolled away. Additive + default-safe: if the endpoint is missing or empty
    // (e.g. before any deliverable exists), the section stays hidden and the board
    // is unchanged.
    function forgeBuildGlyph(kind) {
        var value = safeString(kind).toLowerCase();
        if (value === 'html') return '🌐';
        if (value === 'image') return '🖼️';
        if (value === 'markdown') return '📄';
        if (value === 'data') return '📊';
        return '📦';
    }

    async function loadForgeBuilds(options) {
        try {
            var payload = await fetchJson('/api/evolve/agent/deliverables');
            state.forgeBuilds = Array.isArray(payload && payload.deliverables) ? payload.deliverables : [];
        } catch (_error) {
            state.forgeBuilds = [];
        }
        if (!(options && options.deferRender)) renderInstalledAppsShelf();
    }

    function forgeBuildKey(build) {
        return safeString(build && (build.id || build.deliverable_id || build.path || build.open_url || build.deep_link))
            || (safeString(build && build.kind) + '-' + safeString(build && build.title));
    }

    function libraryItems() {
        var items = installedWorkspacePlugins().map(function (plugin) {
            return { key: 'app:' + (pluginId(plugin) || pluginMode(plugin)), type: 'app', title: pluginLabel(plugin), summary: pluginMeta(plugin), meta: 'Installed workspace', updated: '', icon: pluginInitials(plugin), raw: plugin };
        });
        (state.projects || []).forEach(function (project) {
            var generated = Boolean(project && project.generated);
            items.push({ key: 'project:' + safeString(project && project.id), type: generated ? 'creation' : 'project', title: safeString(project && project.name) || 'Project', summary: safeString(project && (project.scope_summary || project.summary)), meta: safeString(project && project.framework) || 'Local project', updated: safeString(project && (project.updated_at || project.created_at)), icon: safeString(project && project.board_icon && project.board_icon.emoji) || (generated ? 'AI' : '{}'), raw: project, project: true });
        });
        (state.forgeBuilds || []).forEach(function (build) {
            var openUrl = safeString(build && build.open_url);
            var duplicate = openUrl && (state.projects || []).some(function (project) { return safeString(project && project.artifact_url) === openUrl; });
            if (!duplicate) items.push({ key: 'creation:' + forgeBuildKey(build), type: 'creation', title: safeString(build && build.title) || 'Thomas creation', summary: safeString(build && build.summary) || 'A durable artifact created with Thomas.', meta: safeString(build && build.kind) || 'artifact', updated: safeString(build && (build.updated_at || build.created_at)), icon: forgeBuildGlyph(build && build.kind), raw: build, build: true });
        });
        return items.sort(function (left, right) { return (Date.parse(right.updated) || 0) - (Date.parse(left.updated) || 0) || left.title.localeCompare(right.title); });
    }

    function libraryCardMarkup(item) {
        var rawKey = item.key.replace(/^[^:]+:/, '');
        var uiPrefix = item.type === 'app' ? 'my-stuff.library.installed-app-card.' : (item.build ? 'my-stuff.library.forge-build-card.' : 'my-stuff.library.project-card.');
        var tone = item.type === 'app' ? pluginTone(item.raw) : toneForState(item.raw && item.raw.readiness && item.raw.readiness.state);
        return '<button class="stuff-installed-app' + (item.type === 'app' ? ' stuff-module-app' : '') + '" type="button" data-library-key="' + escapeHtml(item.key) + '"' + (item.type === 'app' ? ' data-plugin-mode="' + escapeHtml(pluginMode(item.raw)) + '"' : '') + ' data-ui-id="' + uiPrefix + escapeHtml(rawKey) + '" data-ui-instance-key="' + escapeHtml(rawKey) + '" data-ui-component="repeating-card-item" data-ui-policy="layout-style" data-ui-constraints="preserve-instance-key,preserve-handler,preserve-runtime-content">'
            + '<span class="stuff-installed-icon stuff-module-icon">' + escapeHtml(item.icon) + '</span><span class="stuff-installed-copy"><span class="stuff-app-title">' + escapeHtml(item.title) + '</span><span class="stuff-app-meta">' + escapeHtml(item.summary || item.meta) + '</span></span>'
            + '<span class="stuff-library-card-kind">' + escapeHtml(item.type === 'creation' ? 'Created' : item.type) + '</span><span class="stuff-installed-action">Details</span><span class="stuff-app-badge is-' + escapeHtml(tone) + '">' + escapeHtml(item.updated ? formatRelativeTime(item.updated) : item.meta) + '</span></button>';
    }

    function renderInstalledAppCard(plugin) {
        return libraryCardMarkup({ key: 'app:' + (pluginId(plugin) || pluginMode(plugin)), type: 'app', title: pluginLabel(plugin), summary: pluginMeta(plugin), meta: 'Installed workspace', updated: '', icon: pluginInitials(plugin), raw: plugin });
    }

    function renderInstalledAppsShelf() {
        if (!elements.installedAppsShelf || !elements.installedAppsList) return;
        var items = libraryItems();
        var recentKeys = items.slice(0, 12).map(function (item) { return item.key; });
        var query = state.libraryQuery.toLowerCase();
        var visible = items.filter(function (item) {
            var typeMatch = state.libraryFilter === 'all' || item.type === state.libraryFilter || (state.libraryFilter === 'recent' && recentKeys.indexOf(item.key) >= 0);
            var text = (item.title + ' ' + item.summary + ' ' + item.meta + ' ' + item.type).toLowerCase();
            return typeMatch && (!query || text.indexOf(query) >= 0);
        });
        elements.installedAppsShelf.classList.remove('hidden');
        document.querySelectorAll('[data-filter-count]').forEach(function (node) { var key = safeString(node.getAttribute('data-filter-count')); node.textContent = String(key === 'all' ? items.length : key === 'recent' ? recentKeys.length : items.filter(function (item) { return item.type === key; }).length); });
        if (elements.libraryTitle) elements.libraryTitle.textContent = state.libraryFilter === 'all' ? 'All Stuff' : state.libraryFilter.charAt(0).toUpperCase() + state.libraryFilter.slice(1);
        if (elements.librarySummary) elements.librarySummary.textContent = String(visible.length) + ' of ' + String(items.length) + ' items';
        elements.installedAppsList.innerHTML = visible.length ? visible.map(libraryCardMarkup).join('') : '<div class="stuff-installed-empty stuff-library-empty">Nothing matches this collection yet.<br>New Thomas creations will appear automatically when a canonical source records them.</div>';
    }

    function closeLibraryItemDetails() {
        state.activeLibraryItem = null;
        if (elements.itemDetail) elements.itemDetail.classList.add('hidden');
    }

    function openLibraryItemDetails(key) {
        var item = libraryItems().find(function (row) { return row.key === key; });
        if (!item) return;
        if (item.project) { void openProject(safeString(item.raw && item.raw.id)); return; }
        state.activeLibraryItem = item;
        var isApp = item.type === 'app';
        var source = isApp ? 'Installed marketplace registry' : 'Thomas Code deliverables registry';
        var type = isApp ? 'Installed app' : (safeString(item.raw && item.raw.kind) || 'Artifact');
        var target = isApp ? (pluginMode(item.raw) || safeString(item.raw && item.raw.surface_url)) : safeString(item.raw && (item.raw.path || item.raw.open_url));
        var actions = isApp
            ? '<button class="stuff-btn stuff-btn-primary" type="button" data-detail-plugin-mode="' + escapeHtml(pluginMode(item.raw)) + '" data-ui-id="my-stuff.action.launch-app.' + escapeHtml(item.key) + '" data-ui-component="runtime-action" data-ui-policy="control" data-ui-constraints="preserve-handler,preserve-target">Open App</button>'
            : ((item.raw && item.raw.available === false) ? '<button class="stuff-btn stuff-btn-ghost" type="button" disabled>Artifact unavailable</button>' : (safeString(item.raw && item.raw.open_url) ? '<button class="stuff-btn stuff-btn-primary" type="button" data-forge-open="' + escapeHtml(item.raw.open_url) + '">Open Artifact</button>' : ''))
                + (safeString(item.raw && item.raw.deep_link) ? '<button class="stuff-btn stuff-btn-ghost" type="button" data-forge-convo="' + escapeHtml(item.raw.deep_link) + '">Open Source Chat</button>' : '');
        if (elements.itemDetailContent) elements.itemDetailContent.innerHTML = '<div class="stuff-item-detail-icon">' + escapeHtml(item.icon) + '</div><p class="stuff-item-detail-kicker">' + escapeHtml(type) + '</p><h2 id="itemDetailTitle">' + escapeHtml(item.title) + '</h2><p class="stuff-item-detail-summary">' + escapeHtml(item.summary || 'Ready in Library.') + '</p><dl class="stuff-item-detail-meta"><div><dt>Source</dt><dd>' + escapeHtml(source) + '</dd></div><div><dt>Location</dt><dd>' + escapeHtml(target || 'Managed by Thomas') + '</dd></div><div><dt>Updated</dt><dd>' + escapeHtml(item.updated ? formatRelativeTime(item.updated) : 'Installed now') + '</dd></div></dl><div class="stuff-item-detail-actions" data-ui-id="my-stuff.item-detail.actions" data-ui-component="action-group" data-ui-policy="layout-style" data-ui-constraints="preserve-order,preserve-handlers">' + actions + '</div>';
        if (elements.itemDetail) { elements.itemDetail.classList.remove('hidden'); var close = elements.itemDetail.querySelector('.stuff-close-btn'); if (close) close.focus(); }
    }

    function setViewMode(mode) {
        state.viewMode = mode === 'arrange' ? 'arrange' : 'library';
        if (elements.installedAppsShelf) elements.installedAppsShelf.classList.toggle('hidden', state.viewMode !== 'library');
        if (elements.boardView) elements.boardView.classList.toggle('hidden', state.viewMode !== 'arrange');
        document.querySelectorAll('[data-view-mode]').forEach(function (button) { var active = button.getAttribute('data-view-mode') === state.viewMode; button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', active ? 'true' : 'false'); });
        renderStatus();
    }

    function renderBoard() {
        if (!elements.board) return;
        normalizeProjectPositions(state.projects);
        renderInstalledAppsShelf();
        var moduleSlots = reservedModuleSlots();
        var projects = Array.isArray(state.projects) ? state.projects.slice() : [];
        projects.sort(function (left, right) {
            var leftPos = projectPosition(left);
            var rightPos = projectPosition(right);
            return leftPos.y - rightPos.y || leftPos.x - rightPos.x || safeString(left && left.name).localeCompare(safeString(right && right.name));
        });
        var renderedPositions = [slotToPosition(0)];
        var cards = projects.map(function (project) {
            var tone = toneForState(project && project.readiness && project.readiness.state);
            var pos = projectBoardPosition(project, moduleSlots);
            renderedPositions.push(pos);
            var icon = project && project.board_icon && project.board_icon.emoji ? project.board_icon.emoji : '[]';
            var accent = project && project.board_icon && project.board_icon.accent ? project.board_icon.accent : '#4c8eff';
            var projectId = safeString(project && project.id);
            return ''
                + '<button class="stuff-app" type="button" data-project-id="' + escapeHtml(projectId) + '" data-ui-id="my-stuff.board.project-card.' + escapeHtml(projectId) + '" data-ui-instance-key="' + escapeHtml(projectId) + '" data-ui-component="repeating-card-item" data-ui-policy="layout-style" data-ui-constraints="preserve-instance-key,preserve-handler,preserve-drag-state,resize-deny" style="left:' + String(pos.x) + 'px;top:' + String(pos.y) + 'px;">'
                + '  <span class="stuff-app-emoji" style="background:' + escapeHtml(accent) + ';">' + escapeHtml(icon) + '</span>'
                + '  <span class="stuff-app-title">' + escapeHtml(safeString(project && project.name) || 'Project') + '</span>'
                + '  <span class="stuff-app-meta">' + escapeHtml(safeString(project && project.framework) || safeString(project && project.project_type) || 'Workspace') + '</span>'
                + '  <span class="stuff-app-badge is-' + escapeHtml(tone) + '">' + escapeHtml(safeString(project && project.readiness && project.readiness.label) || 'Linked') + '</span>'
                + '</button>';
        }).join('');
        var importPos = slotToPosition(0);
        elements.board.innerHTML = ''
            + '<button class="stuff-import-hub" id="boardImportHub" type="button" data-ui-id="my-stuff.action.add-project-card" data-ui-component="runtime-action" data-ui-policy="style-only" data-ui-constraints="preserve-id,preserve-handler,position-locked" style="left:' + String(importPos.x) + 'px;top:' + String(importPos.y) + 'px;">'
            + '  <span class="stuff-app-emoji" style="background:linear-gradient(135deg, #66b5ff 0%, #6ee2b0 100%);">+</span>'
            + '  <span class="stuff-app-title">Add Project</span>'
            + '  <span class="stuff-app-meta">Link a local repo and let Thomas stage it.</span>'
            + '</button>'
            + cards;
        updateBoardMinHeight(renderedPositions);
        if (!state.activeProject) setViewMode(state.viewMode);
    }

    function actionButtonMarkup(action, label, extraClass, disabled) {
        var destructive = action === 'remove';
        var instanceKey = safeString(state.activeProjectId) + '.' + action;
        return '<button class="stuff-btn ' + escapeHtml(extraClass || 'stuff-btn-ghost') + '" type="button" data-detail-action="' + escapeHtml(action) + '" data-ui-id="my-stuff.project-action.' + escapeHtml(instanceKey) + '" data-ui-instance-key="' + escapeHtml(action) + '" data-ui-component="' + (destructive ? 'privileged-action' : 'runtime-action') + '" data-ui-policy="' + (destructive ? 'protected' : 'control') + '" data-ui-constraints="preserve-handler,preserve-action' + (destructive ? ',preserve-confirmation-flow' : '') + '"' + (disabled ? ' disabled' : '') + '>' + escapeHtml(label) + '</button>';
    }

    function renderProjectChatMarkup(project) {
        var projectId = safeString(project && project.id);
        return ''
            + '<section class="stuff-project-chat" data-ui-id="my-stuff.project-thomas.' + escapeHtml(projectId) + '" data-ui-component="workspace-region" data-ui-policy="layout-style" data-ui-constraints="preserve-project-scope,preserve-handler">'
            + '  <div class="stuff-chat-head">'
            + '    <div class="stuff-chat-head-copy">'
            + '      <h3>Thomas</h3>'
            + '      <p>Open the Library specialist with ' + escapeHtml(safeString(project && project.name) || 'this project') + ' already in context.</p>'
            + '    </div>'
            + '    <button class="stuff-btn stuff-btn-primary" type="button" data-open-workspace-chat data-ui-id="my-stuff.action.open-thomas.' + escapeHtml(projectId) + '" data-ui-component="runtime-action" data-ui-policy="control" data-ui-constraints="preserve-handler">Ask Thomas</button>'
            + '  </div>'
            + '</section>';
    }

    function renderDetail() {
        if (!elements.detailShell) return;
        var project = state.activeProject;
        if (!project) {
            elements.detailShell.innerHTML = '<div class="stuff-panel"><h3>Nothing selected</h3><p>Go back to the board and pick a project.</p></div>';
            return;
        }
        var tone = toneForState(project && project.readiness && project.readiness.state);
        var emoji = project && project.board_icon && project.board_icon.emoji ? project.board_icon.emoji : '[]';
        var accent = project && project.board_icon && project.board_icon.accent ? project.board_icon.accent : '#4c8eff';
        var candidates = Array.isArray(project && project.launch_candidates) ? project.launch_candidates : [];
        var actionsMarkup = [];
        var seenActions = {};
        candidates.forEach(function (candidate) {
            var action = safeString(candidate && candidate.action);
            if (!action || seenActions[action]) return;
            seenActions[action] = true;
            actionsMarkup.push(actionButtonMarkup(
                action,
                safeString(candidate && candidate.label) || 'Action',
                action === 'prepare' || action === 'launch' ? 'stuff-btn-primary' : 'stuff-btn-ghost',
                candidate && candidate.available === false
            ));
        });
        if (!seenActions.troubleshoot) actionsMarkup.push(actionButtonMarkup('troubleshoot', 'Troubleshoot', 'stuff-btn-ghost', false));
        actionsMarkup.push(actionButtonMarkup('refresh_read', 'Refresh Read', 'stuff-btn-ghost', false));
        if (!(project && project.generated)) {
            actionsMarkup.push(actionButtonMarkup('remove', 'Remove Project', 'stuff-btn-danger', false));
        }

        var findings = Array.isArray(project && project.findings_preview) ? project.findings_preview : [];
        var commands = candidates.filter(function (candidate) {
            return safeString(candidate && candidate.command_display);
        }).map(function (candidate) {
            return '<li><strong>' + escapeHtml(safeString(candidate && candidate.label) || 'Command') + ':</strong> <span class="stuff-command">' + escapeHtml(safeString(candidate && candidate.command_display)) + '</span></li>';
        }).join('');
        var topLevel = project && project.analysis && Array.isArray(project.analysis.top_level)
            ? project.analysis.top_level.map(function (value) { return '<li>' + escapeHtml(safeString(value)) + '</li>'; }).join('')
            : '';
        var result = state.detailResult && safeString(state.detailResult.projectId) === safeString(project.id) ? state.detailResult : null;

        elements.detailShell.innerHTML = ''
            + '<div class="stuff-detail-hero" data-ui-id="my-stuff.project-detail.hero" data-ui-component="content-group" data-ui-policy="layout-style" data-ui-constraints="preserve-runtime-content">'
            + '  <div class="stuff-detail-identity">'
            + '    <div class="stuff-detail-emoji" style="background:' + escapeHtml(accent) + ';">' + escapeHtml(emoji) + '</div>'
            + '    <div>'
            + '      <p class="stuff-kicker">' + escapeHtml(safeString(project && project.framework) || safeString(project && project.project_type) || 'Project') + '</p>'
            + '      <h2>' + escapeHtml(safeString(project && project.name) || 'Project') + '</h2>'
            + '      <div class="stuff-app-badge is-' + escapeHtml(tone) + '">' + escapeHtml(safeString(project && project.readiness && project.readiness.label) || 'Linked') + '</div>'
            + '      <p class="stuff-detail-summary">' + escapeHtml(safeString(project && project.scope_summary) || safeString(project && project.summary)) + '</p>'
            + '      <p class="stuff-detail-path">' + escapeHtml(safeString(project && project.root_path)) + '</p>'
            + '    </div>'
            + '  </div>'
            + '</div>'
            + '<div class="stuff-detail-actions" data-ui-id="my-stuff.project-detail.actions" data-ui-component="action-group" data-ui-policy="layout-style" data-ui-constraints="preserve-order,preserve-handlers">' + actionsMarkup.join('') + '</div>'
            + (result ? '<div class="stuff-action-result is-' + escapeHtml(statusToneClass(result.tone)) + '"><strong>' + escapeHtml(safeString(result.title)) + '</strong><br>' + escapeHtml(safeString(result.text)) + '</div>' : '')
            + '<div class="stuff-detail-grid">'
            + '  <section class="stuff-panel" data-ui-id="my-stuff.project-detail.read" data-ui-component="content-panel" data-ui-policy="layout-style" data-ui-constraints="preserve-runtime-content">'
            + '    <h3>Thomas Read</h3>'
            + '    <p>' + escapeHtml(safeString(project && project.summary)) + '</p>'
            + '    <ul>'
            + '      <li><strong>Project type:</strong> ' + escapeHtml(safeString(project && project.project_type) || 'workspace') + '</li>'
            + '      <li><strong>Package manager:</strong> ' + escapeHtml(safeString(project && project.package_manager) || 'Not detected') + '</li>'
            + '      <li><strong>Last launch:</strong> ' + escapeHtml(formatRelativeTime(project && project.last_launched_at)) + '</li>'
            + '      <li><strong>Launch count:</strong> ' + escapeHtml(String(project && project.launch_count || 0)) + '</li>'
            + '    </ul>'
            + '  </section>'
            + '  <section class="stuff-panel" data-ui-id="my-stuff.project-detail.launch" data-ui-component="content-panel" data-ui-policy="layout-style" data-ui-constraints="preserve-runtime-content">'
            + '    <h3>Launch + Verify</h3>'
            + (commands ? '<ul>' + commands + '</ul>' : '<p>Thomas has not found a trustworthy launch or test command yet.</p>')
            + '  </section>'
            + '  <section class="stuff-panel" data-ui-id="my-stuff.project-detail.findings" data-ui-component="repeating-content-group" data-ui-policy="layout-style" data-ui-constraints="preserve-runtime-content,items-runtime-owned">'
            + '    <h3>Findings</h3>'
            + '    <div class="stuff-finding-list">' + findings.map(function (finding) {
                var findingTone = safeString(finding && finding.level).toLowerCase();
                var findingClass = findingTone === 'good' ? 'good' : (findingTone === 'warn' ? 'warn' : (findingTone === 'bad' ? 'bad' : 'info'));
                return '<div class="stuff-finding is-' + findingClass + '"><strong>' + escapeHtml(safeString(finding && finding.title) || 'Finding') + '</strong><span>' + escapeHtml(safeString(finding && finding.detail)) + '</span></div>';
            }).join('') + '</div>'
            + '  </section>'
            + '  <section class="stuff-panel" data-ui-id="my-stuff.project-detail.top-level" data-ui-component="content-panel" data-ui-policy="layout-style" data-ui-constraints="preserve-runtime-content">'
            + '    <h3>Top Level</h3>'
            + (topLevel ? '<ul>' + topLevel + '</ul>' : '<p>Thomas has not cached a top-level file read for this repo yet.</p>')
            + '  </section>'
            + '</div>'
            + renderProjectChatMarkup(project);
    }

    function quickPrompt(kind, project) {
        var name = safeString(project && project.name) || 'this project';
        if (kind === 'launch_verify') {
            return 'Launch ' + name + ', tell me what command or entry path you expect to use, and then tell me the safest verification step.';
        }
        if (kind === 'troubleshoot') {
            return 'Troubleshoot ' + name + '. Check the current launch/setup path, likely blocker, and tell me the next safest fix.';
        }
        return 'Explain what ' + name + ' is, what stack it uses, and what the most important files are.';
    }

    async function sendProjectChat(message) {
        var project = state.activeProject;
        var projectId = safeString(project && project.id);
        var text = safeString(message);
        if (!projectId || !text) return;
        window.parent.postMessage({
            type: 'thomas:workspace-chat:open',
            mode: 'my_stuff',
            draft: 'For ' + (safeString(project && project.name) || 'this project') + ' at ' + safeString(project && project.root_path) + ': ' + text
        }, window.location.origin);
    }

    async function runDetailAction(action) {
        var project = state.activeProject;
        var projectId = safeString(project && project.id);
        if (!projectId || !action) return;

        if (action === 'remove') {
            if (!window.confirm('Remove this project from Library?')) return;
            await fetchJson('/api/local/projects/' + encodeURIComponent(projectId), {
                method: 'DELETE',
                headers: { 'Accept': 'application/json' }
            });
            openBoardView();
            await refresh({ preserveStatus: true });
            setStatus('Removed ' + safeString(project && project.name) + ' from Library.', 'good');
            return;
        }

        if (action === 'troubleshoot') {
            await sendProjectChat(quickPrompt('troubleshoot', project));
            return;
        }

        if (action === 'refresh_read') {
            await openProject(projectId, { preserveResult: true });
            state.detailResult = {
                projectId: projectId,
                tone: 'info',
                title: 'Project page refreshed',
                text: 'Thomas reloaded the latest project dossier from disk.'
            };
            renderDetail();
            return;
        }

        setStatus('Thomas is handling "' + action + '"...', 'info');
        var payload = await fetchJson('/api/local/projects/' + encodeURIComponent(projectId) + '/action', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ action: action })
        });
        var result = payload && payload.result ? payload.result : {};
        if (safeString(result && result.kind) === 'open_url' && safeString(result && result.url)) {
            window.open(safeString(result.url), '_blank', 'noopener');
        }
        await refresh({ preserveStatus: true });
        await openProject(projectId, { preserveResult: true });
        var commandBits = Array.isArray(result && result.launched_command) ? result.launched_command.join(' ') : '';
        var detail = safeString(commandBits || result && (result.command_display || result.url || result.target || result.cwd));
        var title = action === 'launch'
            ? 'Launch started'
            : action === 'prepare'
                ? 'Prepare started'
                : action === 'test'
                    ? 'Verification started'
                    : action === 'open_entry'
                        ? 'Entry opened'
                        : 'Folder opened';
        state.detailResult = {
            projectId: projectId,
            tone: 'good',
            title: title,
            text: detail ? detail : ('Thomas completed ' + action + ' for this project.')
        };
        renderDetail();
        setStatus(title + '.', 'good');
    }

    function snapCoordinate(value, start, size, maxValue) {
        var snapped = start + Math.round((value - start) / size) * size;
        if (snapped < start) snapped = start;
        if (snapped > maxValue) snapped = maxValue;
        return snapped;
    }

    async function persistBoardPosition(projectId, x, y, silent) {
        try {
            await fetchJson('/api/local/projects/' + encodeURIComponent(projectId) + '/layout', {
                method: 'PATCH',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ x: x, y: y })
            });
        } catch (error) {
            if (!silent) {
                setStatus(safeString(error && error.message) || 'Could not save that icon position.', 'bad');
            }
        }
    }

    function resolveDroppedPath(dataTransfer) {
        if (!dataTransfer) return '';
        var plain = safeString(dataTransfer.getData && dataTransfer.getData('text/plain'));
        if (plain && (plain.indexOf(':\\') > 0 || plain.indexOf(':/') > 0 || plain.charAt(0) === '/' || plain.charAt(0) === '\\')) {
            return plain.trim();
        }
        var files = Array.prototype.slice.call(dataTransfer.files || []);
        if (!files.length) return '';
        var first = files[0];
        var filePath = safeString(first && first.path);
        if (filePath && safeString(first && first.webkitRelativePath)) {
            var relativePath = safeString(first.webkitRelativePath).replace(/\\/g, '/');
            var parts = relativePath.split('/').filter(Boolean);
            if (parts.length > 1) {
                for (var count = 0; count < parts.length - 1; count += 1) {
                    filePath = filePath.replace(/[\\/][^\\/]+$/, '');
                }
            } else {
                filePath = filePath.replace(/[\\/][^\\/]+$/, '');
            }
        } else if (filePath && !/\.[a-z0-9]+$/i.test(filePath)) {
            return filePath;
        } else if (filePath) {
            filePath = filePath.replace(/[\\/][^\\/]+$/, '');
        }
        return filePath;
    }

    if (elements.openImportButton) {
        elements.openImportButton.addEventListener('click', function () {
            openImportSheet();
        });
    }

    if (elements.closeImportButton) {
        elements.closeImportButton.addEventListener('click', closeImportSheet);
    }

    if (elements.refreshButton) {
        elements.refreshButton.addEventListener('click', function () {
            void refresh();
        });
    }

    if (elements.backToBoardButton) {
        elements.backToBoardButton.addEventListener('click', openBoardView);
    }

    if (elements.toggleAdvancedButton) {
        elements.toggleAdvancedButton.addEventListener('click', function () {
            if (!elements.advancedImport) return;
            elements.advancedImport.classList.toggle('hidden');
        });
    }

    if (elements.submitImportButton) {
        elements.submitImportButton.addEventListener('click', function () {
            void importProject(
                elements.projectPathInput && elements.projectPathInput.value,
                elements.projectNameInput && elements.projectNameInput.value,
                'path'
            );
        });
    }

    if (elements.pickFolderButton) {
        elements.pickFolderButton.addEventListener('click', function () {
            void chooseFolder();
        });
    }

    if (elements.board) {
        elements.board.addEventListener('click', function (event) {
            var target = event.target instanceof Element ? event.target.closest('[data-project-id], [data-plugin-mode], #boardImportHub') : null;
            if (!target) return;
            if (Date.now() < state.suppressClickUntil) return;
            if (target.id === 'boardImportHub') {
                openImportSheet();
                return;
            }
            var pluginMode = safeString(target.getAttribute('data-plugin-mode'));
            if (pluginMode) {
                launchInstalledPluginMode(pluginMode);
                return;
            }
            var projectId = safeString(target.getAttribute('data-project-id'));
            if (!projectId) return;
            void openProject(projectId);
        });

        elements.board.addEventListener('pointerdown', function (event) {
            var target = event.target instanceof Element ? event.target.closest('.stuff-app[data-project-id]') : null;
            if (!target || !(elements.board instanceof HTMLElement)) return;
            var projectId = safeString(target.getAttribute('data-project-id'));
            var project = (state.projects || []).find(function (row) {
                return safeString(row && row.id) === projectId;
            });
            if (!project) return;
            var moduleSlots = reservedModuleSlots();
            var pos = projectBoardPosition(project, moduleSlots);
            state.drag = {
                id: projectId,
                moduleSlots: moduleSlots,
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                baseX: pos.x,
                baseY: pos.y,
                moved: false,
                target: target
            };
            target.classList.add('is-dragging');
            try {
                target.setPointerCapture(event.pointerId);
            } catch (_error) {}
        });

        elements.board.addEventListener('pointermove', function (event) {
            if (!state.drag || state.drag.pointerId !== event.pointerId || !(elements.board instanceof HTMLElement)) return;
            var deltaX = event.clientX - state.drag.startX;
            var deltaY = event.clientY - state.drag.startY;
            if (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4) {
                state.drag.moved = true;
            }
            if (!state.drag.target) return;
            state.drag.target.style.left = String(state.drag.baseX + deltaX) + 'px';
            state.drag.target.style.top = String(state.drag.baseY + deltaY) + 'px';
        });

        elements.board.addEventListener('pointerup', function (event) {
            if (!state.drag || state.drag.pointerId !== event.pointerId || !(elements.board instanceof HTMLElement)) return;
            var drag = state.drag;
            state.drag = null;
            if (drag.target) drag.target.classList.remove('is-dragging');
            if (!drag.moved) return;
            state.suppressClickUntil = Date.now() + 250;
            var boardRect = elements.board.getBoundingClientRect();
            var maxX = Math.max(SNAP.left, Math.round(boardRect.width - SNAP.tileWidth - 24));
            var maxY = Math.max(SNAP.top, Math.round(boardRect.height - SNAP.tileHeight - 24));
            var deltaX = event.clientX - drag.startX;
            var deltaY = event.clientY - drag.startY;
            var snappedX = snapCoordinate(drag.baseX + deltaX, SNAP.left, SNAP.width, maxX);
            var snappedY = snapCoordinate(drag.baseY + deltaY, SNAP.top, SNAP.height, maxY);
            var storagePreferred = storagePositionFromBoardPosition({ x: snappedX, y: snappedY }, drag.moduleSlots);
            var nextPos = findNextOpenPosition(drag.id, storagePreferred);
            state.projects = (state.projects || []).map(function (project) {
                if (safeString(project && project.id) !== drag.id) return project;
                project.board_position = { x: nextPos.x, y: nextPos.y };
                return project;
            });
            renderBoard();
            void persistBoardPosition(drag.id, nextPos.x, nextPos.y, false);
            setStatus('Saved icon position.', 'good');
        });

        elements.board.addEventListener('pointercancel', function (event) {
            if (!state.drag || state.drag.pointerId !== event.pointerId) return;
            if (state.drag.target) state.drag.target.classList.remove('is-dragging');
            state.drag = null;
            renderBoard();
        });

        ['dragenter', 'dragover'].forEach(function (eventName) {
            elements.board.addEventListener(eventName, function (event) {
                event.preventDefault();
                elements.board.classList.add('is-drop-target');
                if (elements.dropzone) elements.dropzone.classList.add('is-active');
            });
        });

        ['dragleave', 'drop'].forEach(function (eventName) {
            elements.board.addEventListener(eventName, function (event) {
                if (eventName === 'dragleave' && event.target !== elements.board) return;
                elements.board.classList.remove('is-drop-target');
                if (elements.dropzone) elements.dropzone.classList.remove('is-active');
            });
        });

        elements.board.addEventListener('drop', function (event) {
            event.preventDefault();
            var pathValue = resolveDroppedPath(event.dataTransfer);
            if (pathValue) {
                void importProject(pathValue, '', 'drop');
                return;
            }
            openImportSheet('This browser did not expose the dropped folder path. Use Choose Folder to finish the import cleanly.');
        });
    }

    if (elements.installedAppsList) {
        elements.installedAppsList.addEventListener('click', function (event) {
            var target = event.target instanceof Element ? event.target.closest('[data-library-key]') : null;
            if (!target) return;
            openLibraryItemDetails(safeString(target.getAttribute('data-library-key')));
        });
    }

    document.querySelectorAll('[data-library-filter]').forEach(function (button) {
        button.addEventListener('click', function () {
            state.libraryFilter = safeString(button.getAttribute('data-library-filter')) || 'all';
            document.querySelectorAll('[data-library-filter]').forEach(function (row) { var active = row === button; row.classList.toggle('is-active', active); row.setAttribute('aria-pressed', active ? 'true' : 'false'); });
            renderInstalledAppsShelf();
        });
    });

    document.querySelectorAll('[data-view-mode]').forEach(function (button) {
        button.addEventListener('click', function () { setViewMode(button.getAttribute('data-view-mode')); });
    });

    if (elements.stuffSearch) {
        elements.stuffSearch.addEventListener('input', function () { state.libraryQuery = safeString(elements.stuffSearch.value); renderInstalledAppsShelf(); });
    }

    if (elements.itemDetail) {
        elements.itemDetail.addEventListener('click', function (event) {
            var close = event.target instanceof Element ? event.target.closest('[data-close-item-detail]') : null;
            if (close) { closeLibraryItemDetails(); return; }
            var app = event.target instanceof Element ? event.target.closest('[data-detail-plugin-mode]') : null;
            if (app) { launchInstalledPluginMode(app.getAttribute('data-detail-plugin-mode')); return; }
            var open = event.target instanceof Element ? event.target.closest('[data-forge-open]') : null;
            if (open) { var openUrl = safeString(open.getAttribute('data-forge-open')); if (openUrl) window.open(openUrl, '_blank', 'noopener'); return; }
            var convo = event.target instanceof Element ? event.target.closest('[data-forge-convo]') : null;
            if (convo) { var deepLink = safeString(convo.getAttribute('data-forge-convo')); if (deepLink) { try { (window.top || window).location.href = deepLink; } catch (_error) { window.location.href = deepLink; } } }
        });
    }

    document.addEventListener('keydown', function (event) {
        if ((event.ctrlKey || event.metaKey) && safeString(event.key).toLowerCase() === 'k' && elements.stuffSearch) { event.preventDefault(); elements.stuffSearch.focus(); }
        if (event.key === 'Escape' && state.activeLibraryItem) closeLibraryItemDetails();
    });

    if (elements.detailShell) {
        elements.detailShell.addEventListener('click', function (event) {
            var openThomas = event.target instanceof Element ? event.target.closest('button[data-open-workspace-chat]') : null;
            if (openThomas && state.activeProject) {
                void sendProjectChat('What should I know or do next with this project?');
                return;
            }
            var actionTarget = event.target instanceof Element ? event.target.closest('button[data-detail-action]') : null;
            if (actionTarget) {
                var action = safeString(actionTarget.getAttribute('data-detail-action'));
                if (action) {
                    void runDetailAction(action);
                }
                return;
            }
        });
    }

    renderStatus();
    renderBoard();
    openBoardView();
    void refresh();
})();
