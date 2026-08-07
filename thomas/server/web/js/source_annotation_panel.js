/*
 * CAP-147 — Inline annotation editing panel.
 *
 * Self-contained classic script (loaded via a plain <script src> tag, NOT a module).
 * Defines exactly one global entry point:
 *
 *     window.mountSourceAnnotationPanel(containerEl)
 *
 * It renders a source viewer with a clickable line gutter, lets the user author an
 * annotation anchored to the selected line range, lists existing annotations with
 * their live anchor status (including ORPHANED), opens an agent conversation for an
 * annotation, and emits + displays the resulting unified source diff.
 *
 * Wire protocol (thomas/server/routes/source_annotation_routes.py):
 *   GET  /api/source-annotations/source?file=<path>
 *   POST /api/source-annotations
 *   POST /api/source-annotations/<id>/conversation
 *   POST /api/source-annotations/<id>/diff
 *
 * No frameworks, no CDN, no build step: plain DOM APIs + fetch.
 */
(function () {
  'use strict';

  var STYLE_ID = 'tsa-panel-styles';
  var MOUNT_FLAG = 'tsaPanelMounted';

  /* Palette: canonical Chat tokens first (tokens.css --c-*), with fallbacks to
     the host page's own variables (frontier.html --card/--ink/...) so the panel
     stays legible on token-less hosts. No raw hex anywhere. */
  var CSS = [
    '.tsa-root{--tsa-bg:var(--c-surface,var(--card,transparent));--tsa-panel:var(--c-surface-2,var(--sheet,transparent));',
    '--tsa-well:var(--c-surface-2,var(--sheet,transparent));--tsa-line:var(--c-border,var(--rule,currentColor));--tsa-fg:var(--c-text,var(--ink,currentColor));',
    '--tsa-dim:var(--c-muted,var(--ink-soft,currentColor));--tsa-accent:var(--c-accent,var(--signal,currentColor));--tsa-accent-ink:var(--c-accent-ink,var(--card,white));',
    '--tsa-warn:var(--c-warn,var(--signal,goldenrod));--tsa-ok:var(--c-success,var(--live,seagreen));--tsa-bad:var(--c-danger,tomato);',
    'background:var(--tsa-bg);color:var(--tsa-fg);border:1px solid var(--tsa-line);border-radius:12px;',
    'font:13px/1.45 var(--font-sans,ui-sans-serif,system-ui,sans-serif);padding:14px;box-sizing:border-box;}',
    '.tsa-root *{box-sizing:border-box;}',
    '.tsa-h{font:700 11px/1 var(--font-label,ui-sans-serif,system-ui,sans-serif);letter-spacing:.14em;text-transform:uppercase;',
    'color:var(--tsa-dim);margin:0 0 8px;}',
    '.tsa-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;}',
    '.tsa-grid{display:grid;grid-template-columns:minmax(260px,1.3fr) minmax(260px,1fr);gap:14px;}',
    '@media (max-width:820px){.tsa-grid{grid-template-columns:1fr;}}',
    '.tsa-card{background:var(--tsa-panel);border:1px solid var(--tsa-line);border-radius:10px;padding:10px;}',
    '.tsa-input,.tsa-text{background:var(--tsa-well);color:var(--tsa-fg);border:1px solid var(--tsa-line);',
    'border-radius:8px;padding:7px 9px;font:12.5px/1.4 var(--font-mono,ui-monospace,monospace);',
    'width:100%;min-width:0;}',
    '.tsa-text{resize:vertical;min-height:56px;}',
    '.tsa-btn{background:var(--tsa-accent);color:var(--tsa-accent-ink);border:none;border-radius:9px;padding:7px 12px;',
    'font:600 12px/1 var(--font-sans,ui-sans-serif,system-ui,sans-serif);cursor:pointer;white-space:nowrap;}',
    '.tsa-btn:hover{background:color-mix(in srgb,var(--tsa-accent) 86%,var(--tsa-fg));}',
    '.tsa-btn[disabled]{opacity:.5;cursor:not-allowed;}',
    '.tsa-btn.tsa-ghost{background:transparent;color:var(--tsa-fg);border:1px solid var(--tsa-line);}',
    '.tsa-lines{max-height:320px;overflow:auto;border:1px solid var(--tsa-line);border-radius:8px;',
    'background:var(--tsa-well);font:12.5px/1.55 var(--font-mono,ui-monospace,monospace);}',
    '.tsa-line{display:flex;gap:10px;padding:0 8px;cursor:pointer;white-space:pre;}',
    '.tsa-line:hover{background:color-mix(in srgb,var(--tsa-fg) 7%,transparent);}',
    '.tsa-line.tsa-sel{background:color-mix(in srgb,var(--tsa-accent) 26%,transparent);}',
    '.tsa-line.tsa-note{box-shadow:inset 3px 0 0 var(--tsa-warn);}',
    '.tsa-num{color:var(--tsa-dim);text-align:right;min-width:3.2em;user-select:none;}',
    '.tsa-code{flex:1;overflow:hidden;text-overflow:ellipsis;}',
    '.tsa-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;',
    'max-height:320px;overflow:auto;}',
    '.tsa-item{border:1px solid var(--tsa-line);border-radius:8px;padding:8px;background:var(--tsa-well);}',
    '.tsa-item .tsa-body{white-space:pre-wrap;word-break:break-word;margin:4px 0 6px;}',
    '.tsa-meta{color:var(--tsa-dim);font-size:11.5px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;}',
    '.tsa-badge{border-radius:999px;padding:2px 8px;font:700 10px/1.5 var(--font-label,ui-sans-serif,system-ui,sans-serif);',
    'letter-spacing:.08em;text-transform:uppercase;}',
    '.tsa-badge.tsa-anchored{background:color-mix(in srgb,var(--tsa-ok) 16%,transparent);color:var(--tsa-ok);}',
    '.tsa-badge.tsa-orphaned{background:color-mix(in srgb,var(--tsa-bad) 16%,transparent);color:var(--tsa-bad);}',
    '.tsa-ref{color:var(--tsa-accent);word-break:break-all;}',
    '.tsa-diff{margin:0;padding:10px;background:var(--tsa-well);border:1px solid var(--tsa-line);border-radius:8px;',
    'max-height:260px;overflow:auto;font:12px/1.5 var(--font-mono,ui-monospace,monospace);',
    'white-space:pre;}',
    '.tsa-diff .tsa-add{color:var(--tsa-ok);}',
    '.tsa-diff .tsa-del{color:var(--tsa-bad);}',
    '.tsa-diff .tsa-hunk{color:var(--tsa-accent);}',
    '.tsa-diff .tsa-file{color:var(--tsa-dim);}',
    '.tsa-status{min-height:18px;font-size:12px;color:var(--tsa-dim);}',
    '.tsa-status.tsa-err{color:var(--tsa-bad);}',
    '.tsa-status.tsa-good{color:var(--tsa-ok);}',
    '.tsa-empty{color:var(--tsa-dim);font-style:italic;}'
  ].join('');

  function injectStyles(doc) {
    if (doc.getElementById(STYLE_ID)) return;
    var style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(style);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function readErrorMessage(payload, fallback) {
    if (payload && typeof payload === 'object' && typeof payload.error === 'string' && payload.error) {
      return payload.error;
    }
    return fallback;
  }

  function requestJson(url, options) {
    var opts = options || {};
    return fetch(url, opts).then(function (response) {
      return response.text().then(function (raw) {
        var payload = null;
        if (raw) {
          try { payload = JSON.parse(raw); } catch (err) { payload = null; }
        }
        if (!response.ok) {
          var message = readErrorMessage(payload, raw || ('HTTP ' + response.status));
          var error = new Error(message);
          error.status = response.status;
          throw error;
        }
        return payload || {};
      });
    });
  }

  function postJson(url, body) {
    return requestJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
  }

  window.mountSourceAnnotationPanel = function mountSourceAnnotationPanel(containerEl) {
    if (!containerEl || !containerEl.appendChild) return null;
    if (containerEl.dataset && containerEl.dataset[MOUNT_FLAG] === '1') {
      return containerEl.__tsaPanel || null;
    }
    if (containerEl.dataset) containerEl.dataset[MOUNT_FLAG] = '1';
    injectStyles(containerEl.ownerDocument || document);

    var state = { file: '', lines: [], annotations: [], selStart: 0, selEnd: 0 };

    var root = el('div', 'tsa-root');
    root.appendChild(el('h3', 'tsa-h', 'Inline annotations'));

    /* ---- file loader ------------------------------------------------- */
    var loadRow = el('div', 'tsa-row');
    var fileInput = el('input', 'tsa-input');
    fileInput.type = 'text';
    fileInput.placeholder = 'thomas/tools/source_annotations.py';
    fileInput.style.flex = '1';
    var loadBtn = el('button', 'tsa-btn', 'Load file');
    loadBtn.type = 'button';
    loadRow.appendChild(fileInput);
    loadRow.appendChild(loadBtn);
    root.appendChild(loadRow);

    var status = el('div', 'tsa-status', 'Enter a workspace-relative file path and load it.');
    root.appendChild(status);

    var grid = el('div', 'tsa-grid');
    root.appendChild(grid);

    /* ---- left: source + author form ---------------------------------- */
    var left = el('div', 'tsa-card');
    left.appendChild(el('div', 'tsa-h', 'Source'));
    var linesBox = el('div', 'tsa-lines');
    linesBox.appendChild(el('div', 'tsa-empty', ' no file loaded '));
    left.appendChild(linesBox);

    var selLabel = el('div', 'tsa-meta', 'Selection: none');
    selLabel.style.margin = '8px 0 6px';
    left.appendChild(selLabel);

    var bodyInput = el('textarea', 'tsa-text');
    bodyInput.placeholder = 'Your annotation (what should change and why)…';
    left.appendChild(bodyInput);

    var editInput = el('textarea', 'tsa-text');
    editInput.placeholder = 'Optional suggested replacement text for the selected lines (enables diff)';
    editInput.style.marginTop = '8px';
    left.appendChild(editInput);

    var saveRow = el('div', 'tsa-row');
    saveRow.style.margin = '8px 0 0';
    var saveBtn = el('button', 'tsa-btn', 'Save annotation');
    saveBtn.type = 'button';
    var clearBtn = el('button', 'tsa-btn tsa-ghost', 'Clear selection');
    clearBtn.type = 'button';
    saveRow.appendChild(saveBtn);
    saveRow.appendChild(clearBtn);
    left.appendChild(saveRow);
    grid.appendChild(left);

    /* ---- right: annotation list + diff -------------------------------- */
    var right = el('div', 'tsa-card');
    right.appendChild(el('div', 'tsa-h', 'Annotations'));
    var list = el('ul', 'tsa-list');
    right.appendChild(list);
    var diffHeading = el('div', 'tsa-h', 'Source diff');
    diffHeading.style.marginTop = '12px';
    right.appendChild(diffHeading);
    var diffBox = el('pre', 'tsa-diff');
    diffBox.appendChild(el('span', 'tsa-file', 'No diff emitted yet.'));
    right.appendChild(diffBox);
    grid.appendChild(right);

    containerEl.appendChild(root);

    /* ---- rendering ----------------------------------------------------- */
    function setStatus(message, kind) {
      status.className = 'tsa-status' + (kind ? ' tsa-' + kind : '');
      status.textContent = message;
    }

    function annotatedLineNumbers() {
      var marked = {};
      state.annotations.forEach(function (ann) {
        if (!ann || ann.status === 'orphaned') return;
        var from = Number(ann.line_start || 0);
        var to = Number(ann.line_end || 0);
        for (var n = from; n <= to; n += 1) marked[n] = true;
      });
      return marked;
    }

    function renderLines() {
      linesBox.textContent = '';
      if (!state.lines.length) {
        linesBox.appendChild(el('div', 'tsa-empty', ' no file loaded '));
        return;
      }
      var marked = annotatedLineNumbers();
      state.lines.forEach(function (line) {
        var number = Number(line.number || 0);
        var row = el('div', 'tsa-line');
        row.setAttribute('data-line', String(number));
        if (state.selStart && number >= state.selStart && number <= state.selEnd) {
          row.className += ' tsa-sel';
        }
        if (marked[number]) row.className += ' tsa-note';
        row.appendChild(el('span', 'tsa-num', number));
        row.appendChild(el('span', 'tsa-code', line.text === '' ? ' ' : line.text));
        row.addEventListener('click', function (event) {
          if (event.shiftKey && state.selStart) {
            state.selStart = Math.min(state.selStart, number);
            state.selEnd = Math.max(state.selEnd, number);
          } else {
            state.selStart = number;
            state.selEnd = number;
          }
          renderLines();
          renderSelection();
        });
        linesBox.appendChild(row);
      });
    }

    function renderSelection() {
      if (!state.selStart) {
        selLabel.textContent = 'Selection: none — click a line (shift-click to extend).';
        return;
      }
      selLabel.textContent = 'Selection: lines ' + state.selStart + '–' + state.selEnd +
        ' of ' + (state.file || '(no file)');
    }

    function renderDiff(text) {
      diffBox.textContent = '';
      var lines = String(text || '').split('\n');
      lines.forEach(function (line) {
        var cls = '';
        if (line.indexOf('@@') === 0) cls = 'tsa-hunk';
        else if (line.indexOf('+++') === 0 || line.indexOf('---') === 0) cls = 'tsa-file';
        else if (line.charAt(0) === '+') cls = 'tsa-add';
        else if (line.charAt(0) === '-') cls = 'tsa-del';
        diffBox.appendChild(el('span', cls, line + '\n'));
      });
    }

    function renderAnnotations() {
      list.textContent = '';
      if (!state.annotations.length) {
        var empty = el('li', 'tsa-empty', 'No annotations on this file yet.');
        list.appendChild(empty);
        return;
      }
      state.annotations.forEach(function (ann) {
        var item = el('li', 'tsa-item');
        item.setAttribute('data-annotation-id', String(ann.id || ''));

        var head = el('div', 'tsa-meta');
        var orphaned = ann.status === 'orphaned';
        head.appendChild(el('span', 'tsa-badge ' + (orphaned ? 'tsa-orphaned' : 'tsa-anchored'), ann.status));
        head.appendChild(el('span', null, (ann.file || '') + ':' + ann.line_start + '–' + ann.line_end));
        item.appendChild(head);

        item.appendChild(el('div', 'tsa-body', ann.body || ''));

        var refRow = el('div', 'tsa-meta');
        var refText = el('span', 'tsa-ref', ann.conversation_ref ? ('conversation: ' + ann.conversation_ref) : '');
        refRow.appendChild(refText);
        item.appendChild(refRow);

        var actions = el('div', 'tsa-row');
        actions.style.margin = '8px 0 0';
        var convBtn = el('button', 'tsa-btn tsa-ghost', 'Open conversation');
        convBtn.type = 'button';
        convBtn.addEventListener('click', function () {
          convBtn.disabled = true;
          postJson('/api/source-annotations/' + encodeURIComponent(ann.id) + '/conversation', {})
            .then(function (payload) {
              ann.conversation_ref = payload.conversation_ref || '';
              refText.textContent = 'conversation: ' + ann.conversation_ref;
              setStatus('Conversation opened: ' + ann.conversation_ref, 'good');
            })
            .catch(function (err) { setStatus('Open conversation failed: ' + err.message, 'err'); })
            .then(function () { convBtn.disabled = false; });
        });
        var diffBtn = el('button', 'tsa-btn', 'Emit diff');
        diffBtn.type = 'button';
        diffBtn.addEventListener('click', function () {
          diffBtn.disabled = true;
          postJson('/api/source-annotations/' + encodeURIComponent(ann.id) + '/diff', {})
            .then(function (payload) {
              renderDiff(payload.diff || '');
              setStatus('Diff emitted for annotation ' + ann.id, 'good');
            })
            .catch(function (err) { setStatus('Emit diff failed: ' + err.message, 'err'); })
            .then(function () { diffBtn.disabled = false; });
        });
        actions.appendChild(convBtn);
        actions.appendChild(diffBtn);
        item.appendChild(actions);
        list.appendChild(item);
      });
    }

    /* ---- data ---------------------------------------------------------- */
    function loadFile(path) {
      var target = String(path === undefined ? fileInput.value : path || '').trim();
      if (!target) {
        setStatus('Enter a file path first.', 'err');
        return Promise.resolve(null);
      }
      loadBtn.disabled = true;
      setStatus('Loading ' + target + '…');
      return requestJson('/api/source-annotations/source?file=' + encodeURIComponent(target))
        .then(function (payload) {
          state.file = payload.file || target;
          state.lines = payload.lines || [];
          state.annotations = payload.annotations || [];
          state.selStart = 0;
          state.selEnd = 0;
          fileInput.value = state.file;
          renderLines();
          renderSelection();
          renderAnnotations();
          setStatus('Loaded ' + state.file + ' (' + state.lines.length + ' lines, ' +
            state.annotations.length + ' annotations).', 'good');
          return payload;
        })
        .catch(function (err) {
          setStatus('Load failed: ' + err.message, 'err');
          return null;
        })
        .then(function (result) {
          loadBtn.disabled = false;
          return result;
        });
    }

    function saveAnnotation() {
      if (!state.file) {
        setStatus('Load a file before annotating.', 'err');
        return Promise.resolve(null);
      }
      if (!state.selStart) {
        setStatus('Select a line range first.', 'err');
        return Promise.resolve(null);
      }
      var body = String(bodyInput.value || '').trim();
      if (!body) {
        setStatus('Write the annotation text first.', 'err');
        return Promise.resolve(null);
      }
      var payload = {
        file: state.file,
        line_start: state.selStart,
        line_end: state.selEnd,
        body: body
      };
      var edit = String(editInput.value || '');
      if (edit.trim()) payload.suggested_edit = edit;

      saveBtn.disabled = true;
      return postJson('/api/source-annotations', payload)
        .then(function (result) {
          bodyInput.value = '';
          editInput.value = '';
          setStatus('Annotation saved on lines ' + payload.line_start + '–' + payload.line_end + '.', 'good');
          return loadFile(state.file).then(function () { return result; });
        })
        .catch(function (err) {
          setStatus('Save failed: ' + err.message, 'err');
          return null;
        })
        .then(function (result) {
          saveBtn.disabled = false;
          return result;
        });
    }

    loadBtn.addEventListener('click', function () { loadFile(); });
    fileInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); loadFile(); }
    });
    saveBtn.addEventListener('click', function () { saveAnnotation(); });
    clearBtn.addEventListener('click', function () {
      state.selStart = 0;
      state.selEnd = 0;
      renderLines();
      renderSelection();
    });

    renderSelection();
    renderAnnotations();

    var api = {
      root: root,
      state: state,
      loadFile: loadFile,
      saveAnnotation: saveAnnotation,
      renderDiff: renderDiff
    };
    containerEl.__tsaPanel = api;
    return api;
  };
})();
