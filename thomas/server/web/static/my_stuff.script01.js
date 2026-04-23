(function () {
    var CHAT_STORE_KEY = 'thomas.myStuff.projectChats.v2';
    var SESSION_STORE_KEY = 'thomas.myStuff.projectSessions.v2';
    var SCRIPT_VERSION = '20260318-project-board-2';

    var state = {
        projects: [],
        loading: false,
        activeProjectId: '',
        activeProject: null,
        statusMessage: 'Loading project board...',
        statusTone: 'info',
        importOpen: false,
        importBusy: false,
        drag: null,
        suppressClickUntil: 0,
        detailResult: null,
        projectChats: readStore(CHAT_STORE_KEY),
        projectSessions: readStore(SESSION_STORE_KEY),
        chatBusyProjectId: ''
    };

    var SNAP = {
        left: 32,
        top: 36,
        width: 170,
        height: 180,
        tileWidth: 148,
        tileHeight: 156,
        columns: 5
    };

    var elements = {
        boardView: document.getElementById('boardView'),
        board: document.getElementById('board'),
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

    function readStore(key) {
        try {
            var raw = window.localStorage.getItem(key);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (_error) {
            return {};
        }
    }

    function writeStore(key, value) {
        try {
            window.localStorage.setItem(key, JSON.stringify(value || {}));
        } catch (_error) {}
    }

    function makeLocalId(prefix) {
        return prefix + '-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
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
            elements.statusPill.textContent = state.activeProject ? 'Project Detail' : 'Project Board';
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

    function slotToPosition(slot) {
        var normalized = Math.max(0, Number(slot) || 0);
        var col = normalized % SNAP.columns;
        var row = Math.floor(normalized / SNAP.columns);
        return {
            x: SNAP.left + col * SNAP.width,
            y: SNAP.top + row * SNAP.height
        };
    }

    function positionToSlot(pos) {
        var x = Number(pos && pos.x) || SNAP.left;
        var y = Number(pos && pos.y) || SNAP.top;
        var col = Math.max(0, Math.round((x - SNAP.left) / SNAP.width));
        var row = Math.max(0, Math.round((y - SNAP.top) / SNAP.height));
        return row * SNAP.columns + col;
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
        if (elements.boardView) elements.boardView.classList.remove('hidden');
        if (elements.detailView) elements.detailView.classList.add('hidden');
        renderStatus();
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
        if (elements.boardView) elements.boardView.classList.add('hidden');
        if (elements.detailView) elements.detailView.classList.remove('hidden');
        renderDetail();
        setStatus('Project page ready.', toneForState(state.activeProject && state.activeProject.readiness && state.activeProject.readiness.state));
    }

    async function refresh(options) {
        var preserveStatus = Boolean(options && options.preserveStatus);
        state.loading = true;
        if (!preserveStatus) {
            setStatus('Refreshing project board...', 'info');
        }
        try {
            var payload = await fetchJson('/api/local/projects');
            state.projects = Array.isArray(payload && payload.projects) ? payload.projects : [];
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
                setStatus('Project board ready. ' + String(state.projects.length) + ' project' + (state.projects.length === 1 ? '' : 's') + ' loaded.', 'info');
            } else {
                renderStatus();
            }
        } catch (error) {
            setStatus(safeString(error && error.message) || 'Could not load Project Board.', 'bad');
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

    function renderBoard() {
        if (!elements.board) return;
        normalizeProjectPositions(state.projects);
        var projects = Array.isArray(state.projects) ? state.projects.slice() : [];
        projects.sort(function (left, right) {
            var leftPos = projectPosition(left);
            var rightPos = projectPosition(right);
            return leftPos.y - rightPos.y || leftPos.x - rightPos.x || safeString(left && left.name).localeCompare(safeString(right && right.name));
        });
        var cards = projects.map(function (project) {
            var tone = toneForState(project && project.readiness && project.readiness.state);
            var pos = projectPosition(project);
            var icon = project && project.board_icon && project.board_icon.emoji ? project.board_icon.emoji : '[]';
            var accent = project && project.board_icon && project.board_icon.accent ? project.board_icon.accent : '#4c8eff';
            return ''
                + '<button class="stuff-app" type="button" data-project-id="' + escapeHtml(safeString(project && project.id)) + '" style="left:' + String(pos.x) + 'px;top:' + String(pos.y) + 'px;">'
                + '  <span class="stuff-app-emoji" style="background:' + escapeHtml(accent) + ';">' + escapeHtml(icon) + '</span>'
                + '  <span class="stuff-app-title">' + escapeHtml(safeString(project && project.name) || 'Project') + '</span>'
                + '  <span class="stuff-app-meta">' + escapeHtml(safeString(project && project.framework) || safeString(project && project.project_type) || 'Workspace') + '</span>'
                + '  <span class="stuff-app-badge is-' + escapeHtml(tone) + '">' + escapeHtml(safeString(project && project.readiness && project.readiness.label) || 'Linked') + '</span>'
                + '</button>';
        }).join('');
        var importPos = slotToPosition(0);
        elements.board.innerHTML = ''
            + '<button class="stuff-import-hub" id="boardImportHub" type="button" style="left:' + String(importPos.x) + 'px;top:' + String(importPos.y) + 'px;">'
            + '  <span class="stuff-app-emoji" style="background:linear-gradient(135deg, #66b5ff 0%, #6ee2b0 100%);">+</span>'
            + '  <span class="stuff-app-title">Add Project</span>'
            + '  <span class="stuff-app-meta">Link a local repo and let Thomas stage it.</span>'
            + '</button>'
            + cards;
    }

    function actionButtonMarkup(action, label, extraClass, disabled) {
        return '<button class="stuff-btn ' + escapeHtml(extraClass || 'stuff-btn-ghost') + '" type="button" data-detail-action="' + escapeHtml(action) + '"' + (disabled ? ' disabled' : '') + '>' + escapeHtml(label) + '</button>';
    }

    function getProjectChat(projectId) {
        var key = safeString(projectId);
        return Array.isArray(state.projectChats[key]) ? state.projectChats[key].slice() : [];
    }

    function saveProjectChat(projectId, rows) {
        var key = safeString(projectId);
        state.projectChats[key] = (Array.isArray(rows) ? rows : []).slice(-80);
        writeStore(CHAT_STORE_KEY, state.projectChats);
    }

    function appendProjectChat(projectId, message) {
        var rows = getProjectChat(projectId);
        rows.push(message);
        saveProjectChat(projectId, rows);
    }

    function updateProjectChatMessage(projectId, messageId, patch) {
        var rows = getProjectChat(projectId).map(function (row) {
            if (safeString(row && row.id) !== safeString(messageId)) return row;
            return Object.assign({}, row || {}, patch || {});
        });
        saveProjectChat(projectId, rows);
    }

    function resetProjectChat(projectId) {
        var key = safeString(projectId);
        delete state.projectChats[key];
        delete state.projectSessions[key];
        writeStore(CHAT_STORE_KEY, state.projectChats);
        writeStore(SESSION_STORE_KEY, state.projectSessions);
    }

    function renderProjectChatMessages(projectId) {
        var rows = getProjectChat(projectId);
        if (!rows.length) {
            return '<div class="stuff-chat-empty">This lane is project-scoped. Ask Thomas to troubleshoot, explain the repo, or launch and verify it from here.</div>';
        }
        return rows.map(function (row) {
            var role = safeString(row && row.role).toLowerCase() === 'user' ? 'user' : 'assistant';
            return ''
                + '<div class="stuff-chat-row role-' + role + (row && row.pending ? ' is-pending' : '') + '">'
                + '  <div class="stuff-chat-bubble">' + escapeHtml(safeString(row && row.text) || (row && row.pending ? 'Thomas is thinking...' : '')) + '</div>'
                + '</div>';
        }).join('');
    }

    function renderProjectChatMarkup(project) {
        var projectId = safeString(project && project.id);
        var busy = safeString(state.chatBusyProjectId) === projectId;
        return ''
            + '<section class="stuff-project-chat">'
            + '  <div class="stuff-chat-head">'
            + '    <div class="stuff-chat-head-copy">'
            + '      <h3>Thomas Project Chat</h3>'
            + '      <p>This lane stays tied to ' + escapeHtml(safeString(project && project.name) || 'this project') + ' so Thomas can work from the repo context instead of the main chat.</p>'
            + '    </div>'
            + '    <div class="stuff-chat-head-actions">'
            +        actionButtonMarkup('troubleshoot', 'Troubleshoot', 'stuff-btn-primary', busy)
            +        actionButtonMarkup('new_thread', 'New Thread', 'stuff-btn-ghost', busy)
            + '    </div>'
            + '  </div>'
            + '  <div class="stuff-chat-quick-row">'
            + '    <button class="stuff-chat-chip" type="button" data-chat-prompt="explain">Explain Project</button>'
            + '    <button class="stuff-chat-chip" type="button" data-chat-prompt="launch_verify">Launch + Verify</button>'
            + '    <button class="stuff-chat-chip" type="button" data-chat-prompt="troubleshoot">Troubleshoot</button>'
            + '  </div>'
            + '  <div class="stuff-chat-log" data-project-chat-log>' + renderProjectChatMessages(projectId) + '</div>'
            + '  <form class="stuff-chat-form" data-project-chat-form>'
            + '    <textarea data-project-chat-input placeholder="Talk to Thomas about this project only..."' + (busy ? ' disabled' : '') + '></textarea>'
            + '    <button class="stuff-btn stuff-btn-primary" type="submit"' + (busy ? ' disabled' : '') + '>' + (busy ? 'Working...' : 'Send') + '</button>'
            + '  </form>'
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
        actionsMarkup.push(actionButtonMarkup('remove', 'Remove Project', 'stuff-btn-danger', false));

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
            + '<div class="stuff-detail-hero">'
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
            + '<div class="stuff-detail-actions">' + actionsMarkup.join('') + '</div>'
            + (result ? '<div class="stuff-action-result is-' + escapeHtml(statusToneClass(result.tone)) + '"><strong>' + escapeHtml(safeString(result.title)) + '</strong><br>' + escapeHtml(safeString(result.text)) + '</div>' : '')
            + '<div class="stuff-detail-grid">'
            + '  <section class="stuff-panel">'
            + '    <h3>Thomas Read</h3>'
            + '    <p>' + escapeHtml(safeString(project && project.summary)) + '</p>'
            + '    <ul>'
            + '      <li><strong>Project type:</strong> ' + escapeHtml(safeString(project && project.project_type) || 'workspace') + '</li>'
            + '      <li><strong>Package manager:</strong> ' + escapeHtml(safeString(project && project.package_manager) || 'Not detected') + '</li>'
            + '      <li><strong>Last launch:</strong> ' + escapeHtml(formatRelativeTime(project && project.last_launched_at)) + '</li>'
            + '      <li><strong>Launch count:</strong> ' + escapeHtml(String(project && project.launch_count || 0)) + '</li>'
            + '    </ul>'
            + '  </section>'
            + '  <section class="stuff-panel">'
            + '    <h3>Launch + Verify</h3>'
            + (commands ? '<ul>' + commands + '</ul>' : '<p>Thomas has not found a trustworthy launch or test command yet.</p>')
            + '  </section>'
            + '  <section class="stuff-panel">'
            + '    <h3>Findings</h3>'
            + '    <div class="stuff-finding-list">' + findings.map(function (finding) {
                var findingTone = safeString(finding && finding.level).toLowerCase();
                var findingClass = findingTone === 'good' ? 'good' : (findingTone === 'warn' ? 'warn' : (findingTone === 'bad' ? 'bad' : 'info'));
                return '<div class="stuff-finding is-' + findingClass + '"><strong>' + escapeHtml(safeString(finding && finding.title) || 'Finding') + '</strong><span>' + escapeHtml(safeString(finding && finding.detail)) + '</span></div>';
            }).join('') + '</div>'
            + '  </section>'
            + '  <section class="stuff-panel">'
            + '    <h3>Top Level</h3>'
            + (topLevel ? '<ul>' + topLevel + '</ul>' : '<p>Thomas has not cached a top-level file read for this repo yet.</p>')
            + '  </section>'
            + '</div>'
            + renderProjectChatMarkup(project);
    }

    function prefillProjectPrompt(text) {
        if (!elements.detailShell) return;
        var input = elements.detailShell.querySelector('[data-project-chat-input]');
        if (!(input instanceof HTMLTextAreaElement)) return;
        input.value = safeString(text);
        input.focus();
        input.selectionStart = input.value.length;
        input.selectionEnd = input.value.length;
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

    function buildProjectScopedPrompt(project, userMessage) {
        var launchCandidates = Array.isArray(project && project.launch_candidates) ? project.launch_candidates : [];
        var findings = Array.isArray(project && project.findings_preview) ? project.findings_preview : [];
        var candidateText = launchCandidates.map(function (candidate) {
            return '- ' + safeString(candidate && candidate.label) + ': ' + safeString(candidate && candidate.command_display);
        }).filter(Boolean).join('\n');
        var findingText = findings.map(function (finding) {
            return '- ' + safeString(finding && finding.title) + ': ' + safeString(finding && finding.detail);
        }).filter(Boolean).join('\n');
        return [
            'You are Thomas working inside a single linked local project from Project Board.',
            'Treat the project root below as the active workspace for this conversation.',
            'If you suggest commands or file paths, anchor them to this repo.',
            '',
            'Project name: ' + safeString(project && project.name),
            'Project root: ' + safeString(project && project.root_path),
            'Framework: ' + safeString(project && project.framework),
            'Project type: ' + safeString(project && project.project_type),
            'Readiness: ' + safeString(project && project.readiness && project.readiness.label),
            'Summary: ' + safeString(project && project.summary),
            'Scope summary: ' + safeString(project && project.scope_summary),
            candidateText ? ('Launch candidates:\n' + candidateText) : 'Launch candidates: none detected',
            findingText ? ('Findings preview:\n' + findingText) : 'Findings preview: none',
            '',
            'User request:',
            safeString(userMessage)
        ].join('\n');
    }

    async function consumeNdjson(response, onEvent) {
        var reader = response && response.body && response.body.getReader ? response.body.getReader() : null;
        var decoder = new TextDecoder();
        var buffer = '';
        if (!reader) {
            var whole = await response.text();
            buffer = whole || '';
        } else {
            while (true) {
                var chunk = await reader.read();
                if (!chunk || chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                var newlineIndex = buffer.indexOf('\n');
                while (newlineIndex >= 0) {
                    var line = buffer.slice(0, newlineIndex).trim();
                    buffer = buffer.slice(newlineIndex + 1);
                    if (line) {
                        try {
                            onEvent(JSON.parse(line));
                        } catch (_error) {}
                    }
                    newlineIndex = buffer.indexOf('\n');
                }
            }
            buffer += decoder.decode();
        }
        if (buffer.trim()) {
            buffer.trim().split(/\n+/).forEach(function (line) {
                if (!line) return;
                try {
                    onEvent(JSON.parse(line));
                } catch (_error) {}
            });
        }
    }

    function syncProjectChatUi() {
        if (!elements.detailShell || !state.activeProject) return;
        var projectId = safeString(state.activeProject.id);
        var log = elements.detailShell.querySelector('[data-project-chat-log]');
        if (log) {
            log.innerHTML = renderProjectChatMessages(projectId);
            log.scrollTop = log.scrollHeight;
        }
        var input = elements.detailShell.querySelector('[data-project-chat-input]');
        var formButton = elements.detailShell.querySelector('[data-project-chat-form] button[type="submit"]');
        var busy = safeString(state.chatBusyProjectId) === projectId;
        if (input instanceof HTMLTextAreaElement) input.disabled = busy;
        if (formButton instanceof HTMLButtonElement) {
            formButton.disabled = busy;
            formButton.textContent = busy ? 'Working...' : 'Send';
        }
    }

    async function sendProjectChat(message) {
        var project = state.activeProject;
        var projectId = safeString(project && project.id);
        var text = safeString(message);
        if (!projectId || !text) return;
        if (safeString(state.chatBusyProjectId) === projectId) return;

        appendProjectChat(projectId, {
            id: makeLocalId('user'),
            role: 'user',
            text: text,
            created_at: new Date().toISOString()
        });

        var assistantId = makeLocalId('assistant');
        appendProjectChat(projectId, {
            id: assistantId,
            role: 'assistant',
            text: '',
            pending: true,
            created_at: new Date().toISOString()
        });

        state.chatBusyProjectId = projectId;
        syncProjectChatUi();
        setStatus('Thomas is working inside ' + safeString(project && project.name) + '...', 'info');

        try {
            var sessionId = safeString(state.projectSessions[projectId]);
            var response = await fetch('/api/v2/chat', {
                method: 'POST',
                headers: {
                    'Accept': 'application/x-ndjson, application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: buildProjectScopedPrompt(project, text),
                    session_id: sessionId || undefined,
                    mode: 'auto',
                    autonomy_level: 3
                })
            });
            if (!response.ok) {
                var errorText = await response.text();
                throw new Error(errorText || 'Thomas could not answer from this project lane.');
            }

            var assistantText = '';
            await consumeNdjson(response, function (event) {
                var type = safeString(event && event.type).toLowerCase();
                if (type === 'text') {
                    assistantText += safeString(event && event.text);
                    updateProjectChatMessage(projectId, assistantId, { text: assistantText, pending: true });
                    syncProjectChatUi();
                    return;
                }
                if (type === 'done') {
                    var nextSessionId = safeString(event && event.session_id);
                    if (nextSessionId) {
                        state.projectSessions[projectId] = nextSessionId;
                        writeStore(SESSION_STORE_KEY, state.projectSessions);
                    }
                    return;
                }
                if (type === 'error') {
                    throw new Error(safeString(event && event.error) || 'Thomas hit an error in this project lane.');
                }
            });

            updateProjectChatMessage(projectId, assistantId, {
                text: assistantText || 'Thomas finished the project pass but did not stream a text reply.',
                pending: false
            });
            setStatus('Project chat updated.', 'good');
        } catch (error) {
            updateProjectChatMessage(projectId, assistantId, {
                text: safeString(error && error.message) || 'Thomas could not answer from this project lane.',
                pending: false
            });
            setStatus('Project chat failed to answer.', 'bad');
        } finally {
            state.chatBusyProjectId = '';
            syncProjectChatUi();
        }
    }

    async function runDetailAction(action) {
        var project = state.activeProject;
        var projectId = safeString(project && project.id);
        if (!projectId || !action) return;

        if (action === 'remove') {
            if (!window.confirm('Remove this project from Project Board?')) return;
            await fetchJson('/api/local/projects/' + encodeURIComponent(projectId), {
                method: 'DELETE',
                headers: { 'Accept': 'application/json' }
            });
            resetProjectChat(projectId);
            openBoardView();
            await refresh({ preserveStatus: true });
            setStatus('Removed ' + safeString(project && project.name) + ' from Project Board.', 'good');
            return;
        }

        if (action === 'new_thread') {
            resetProjectChat(projectId);
            state.detailResult = {
                projectId: projectId,
                tone: 'info',
                title: 'Project chat reset',
                text: 'Thomas will start a fresh project-only lane the next time you send a message.'
            };
            renderDetail();
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
        await refresh({ preserveStatus: true });
        await openProject(projectId, { preserveResult: true });
        var result = payload && payload.result ? payload.result : {};
        var commandBits = Array.isArray(result && result.launched_command) ? result.launched_command.join(' ') : '';
        var detail = safeString(commandBits || result && (result.command_display || result.target || result.cwd));
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
            var target = event.target instanceof Element ? event.target.closest('[data-project-id], #boardImportHub') : null;
            if (!target) return;
            if (Date.now() < state.suppressClickUntil) return;
            if (target.id === 'boardImportHub') {
                openImportSheet();
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
            var pos = projectPosition(project);
            state.drag = {
                id: projectId,
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
            var nextPos = findNextOpenPosition(drag.id, { x: snappedX, y: snappedY });
            state.projects = (state.projects || []).map(function (project) {
                if (safeString(project && project.id) !== drag.id) return project;
                project.board_position = { x: nextPos.x, y: nextPos.y };
                return project;
            });
            renderBoard();
            void persistBoardPosition(drag.id, nextPos.x, nextPos.y, false);
            setStatus('Saved icon position.', 'good');
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

    if (elements.detailShell) {
        elements.detailShell.addEventListener('click', function (event) {
            var actionTarget = event.target instanceof Element ? event.target.closest('button[data-detail-action]') : null;
            if (actionTarget) {
                var action = safeString(actionTarget.getAttribute('data-detail-action'));
                if (action) {
                    void runDetailAction(action);
                }
                return;
            }
            var promptTarget = event.target instanceof Element ? event.target.closest('button[data-chat-prompt]') : null;
            if (!promptTarget || !state.activeProject) return;
            var promptKey = safeString(promptTarget.getAttribute('data-chat-prompt'));
            if (!promptKey) return;
            prefillProjectPrompt(quickPrompt(promptKey, state.activeProject));
        });

        elements.detailShell.addEventListener('submit', function (event) {
            var form = event.target instanceof Element ? event.target.closest('[data-project-chat-form]') : null;
            if (!form) return;
            event.preventDefault();
            var input = elements.detailShell.querySelector('[data-project-chat-input]');
            if (!(input instanceof HTMLTextAreaElement)) return;
            var message = safeString(input.value);
            if (!message) return;
            input.value = '';
            void sendProjectChat(message);
        });
    }

    renderStatus();
    renderBoard();
    openBoardView();
    void refresh();
})();