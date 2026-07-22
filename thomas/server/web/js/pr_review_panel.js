/*
 * In-flow PR review surface (CAP-149, Level 2).
 *
 * Self-contained classic script -- loaded with a plain <script src> tag, no
 * modules, no build step, no external libraries. It defines exactly one global:
 *
 *     window.mountPrReviewPanel(containerEl)
 *
 * The panel renders hunks HIGHEST-RISK-FIRST with their risk score visible,
 * threaded per-hunk comments (add / reply / resolve), an APPROVE button that is
 * visibly disabled while a high-risk hunk carries an unresolved blocking
 * comment (with the blocking reason shown) and enabled once resolved, and a
 * HAND OFF FIX action on every unresolved comment that renders the created fix
 * task bound to its hunk.
 *
 * It talks to thomas/server/routes/pr_review_routes.py over /api/pr-review.
 */
(function () {
  'use strict';

  var API = '/api/pr-review';
  var STYLE_ID = 'prr-panel-styles';

  var SAMPLE_DIFF = [
    'diff --git a/docs/README.md b/docs/README.md',
    '--- a/docs/README.md',
    '+++ b/docs/README.md',
    '@@ -1,3 +1,3 @@',
    '-Thomas',
    '+Thomas workspace',
    ' second line',
    ' third line',
    'diff --git a/app/auth/session_login.py b/app/auth/session_login.py',
    '--- a/app/auth/session_login.py',
    '+++ b/app/auth/session_login.py',
    '@@ -10,8 +10,9 @@ def login(user):',
    '-    token = make_token(user)',
    '-    if not verify_password(user.password):',
    '-        return None',
    '+    token = make_token(user, ttl=None)',
    '+    secret = load_api_key()',
    '+    if not verify_password(user.password, secret):',
    '+        return None',
    '+    grant_permission(user, "admin")',
    ' return token',
    'diff --git a/tests/test_ttl.py b/tests/test_ttl.py',
    '--- a/tests/test_ttl.py',
    '+++ b/tests/test_ttl.py',
    '@@ -1,4 +1,5 @@',
    ' import pytest',
    '+',
    '+def test_ttl_default():',
    '+    assert compute_ttl() == 900',
    ' # end'
  ].join('\n');

  var CSS = [
    '.prr-root{--prr-bg:#0f1216;--prr-panel:#161b22;--prr-line:#2a323d;--prr-fg:#e6edf3;',
    '--prr-dim:#9aa7b4;--prr-accent:#4c8dff;--prr-high:#ff6b6b;--prr-med:#f2b134;--prr-low:#4fbf7b;',
    'background:var(--prr-bg);color:var(--prr-fg);border:1px solid var(--prr-line);border-radius:10px;',
    'padding:16px;font:13px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;box-sizing:border-box;}',
    '.prr-root *{box-sizing:border-box;}',
    '.prr-h1{margin:0;font-size:16px;font-weight:650;}',
    '.prr-sub{margin:2px 0 12px;color:var(--prr-dim);font-size:12px;}',
    '.prr-open{display:flex;flex-direction:column;gap:8px;margin-bottom:12px;}',
    '.prr-diff{width:100%;min-height:110px;background:#0b0e12;color:var(--prr-fg);border:1px solid var(--prr-line);',
    'border-radius:8px;padding:8px;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;resize:vertical;}',
    '.prr-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}',
    '.prr-input{flex:1 1 180px;min-width:120px;background:#0b0e12;color:var(--prr-fg);',
    'border:1px solid var(--prr-line);border-radius:8px;padding:6px 8px;font:inherit;}',
    '.prr-btn{background:#20262e;color:var(--prr-fg);border:1px solid var(--prr-line);border-radius:8px;',
    'padding:6px 12px;font:inherit;cursor:pointer;}',
    '.prr-btn:hover:not(:disabled){border-color:var(--prr-accent);}',
    '.prr-btn:disabled{opacity:.45;cursor:not-allowed;}',
    '.prr-primary{background:var(--prr-accent);border-color:var(--prr-accent);color:#08121f;font-weight:600;}',
    '.prr-status{min-height:18px;font-size:12px;color:var(--prr-dim);margin-bottom:8px;}',
    '.prr-status.prr-err{color:var(--prr-high);}',
    '.prr-approve{display:flex;flex-direction:column;gap:6px;border:1px solid var(--prr-line);border-radius:8px;',
    'padding:10px;margin-bottom:12px;background:var(--prr-panel);}',
    '.prr-blocked{color:var(--prr-high);font-size:12px;margin:0;padding-left:16px;}',
    '.prr-ok{color:var(--prr-low);font-size:12px;}',
    '.prr-hunk{border:1px solid var(--prr-line);border-radius:8px;margin-bottom:10px;background:var(--prr-panel);}',
    '.prr-hunk-head{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 10px;',
    'border-bottom:1px solid var(--prr-line);}',
    '.prr-rank{color:var(--prr-dim);font-variant-numeric:tabular-nums;font-size:12px;}',
    '.prr-file{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;word-break:break-all;}',
    '.prr-risk{border-radius:999px;padding:2px 9px;font-size:11px;font-weight:700;color:#0b0e12;white-space:nowrap;}',
    '.prr-risk-high{background:var(--prr-high);}',
    '.prr-risk-medium{background:var(--prr-med);}',
    '.prr-risk-low{background:var(--prr-low);}',
    '.prr-meta{color:var(--prr-dim);font-size:11px;}',
    '.prr-hunk-body{padding:8px 10px;}',
    '.prr-header-line{font:11px/1.4 ui-monospace,Consolas,monospace;color:var(--prr-dim);',
    'margin:0 0 8px;word-break:break-all;}',
    '.prr-thread{border-left:2px solid var(--prr-line);padding-left:8px;margin-bottom:8px;}',
    '.prr-comment{padding:5px 0;}',
    '.prr-reply{margin-left:16px;border-left:1px dashed var(--prr-line);padding-left:8px;}',
    '.prr-author{font-weight:650;font-size:12px;}',
    '.prr-body{margin:2px 0;font-size:12px;white-space:pre-wrap;word-break:break-word;}',
    '.prr-tag{font-size:10px;border-radius:4px;padding:1px 6px;margin-left:6px;border:1px solid var(--prr-line);',
    'color:var(--prr-dim);}',
    '.prr-tag-block{color:var(--prr-high);border-color:var(--prr-high);}',
    '.prr-tag-res{color:var(--prr-low);border-color:var(--prr-low);}',
    '.prr-acts{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;}',
    '.prr-acts .prr-btn{padding:3px 8px;font-size:11px;}',
    '.prr-empty{color:var(--prr-dim);font-size:12px;margin:0 0 8px;}',
    '.prr-tasks{border:1px dashed var(--prr-accent);border-radius:8px;padding:10px;margin-top:12px;}',
    '.prr-task{border-top:1px solid var(--prr-line);padding:6px 0;font-size:12px;}',
    '.prr-task:first-of-type{border-top:0;}',
    '.prr-task-id{font:12px/1.4 ui-monospace,Consolas,monospace;color:var(--prr-accent);font-weight:700;}'
  ].join('');

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) { return; }
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function button(label, className, onClick) {
    var b = el('button', 'prr-btn' + (className ? ' ' + className : ''), label);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  function apiCall(method, path, body) {
    return fetch(API + path, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          var msg = (data && (data.message || data.error)) || ('HTTP ' + res.status);
          var err = new Error(msg);
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function getJson(path) {
    return fetch(API + path, { headers: { 'Accept': 'application/json' } }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          var err = new Error((data && (data.message || data.error)) || ('HTTP ' + res.status));
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  window.mountPrReviewPanel = function mountPrReviewPanel(containerEl) {
    if (!containerEl || containerEl.nodeType !== 1) { return null; }
    if (containerEl.getAttribute('data-prr-mounted') === '1') { return containerEl.__prrPanel || null; }
    containerEl.setAttribute('data-prr-mounted', '1');

    injectStyles();
    containerEl.textContent = '';

    var state = { reviewId: null, review: null };

    var root = el('div', 'prr-root');
    root.appendChild(el('h2', 'prr-h1', 'In-flow PR review'));
    root.appendChild(el(
      'p',
      'prr-sub',
      'Risk-ranked hunks - threaded comments - gated approval - fix handoff'
    ));

    // ---- diff intake -----------------------------------------------------
    var openBox = el('div', 'prr-open');
    var diffInput = el('textarea', 'prr-diff');
    diffInput.setAttribute('placeholder', 'Paste a unified diff (git diff) here...');
    diffInput.setAttribute('aria-label', 'Unified diff');
    var openRow = el('div', 'prr-row');
    var titleInput = el('input', 'prr-input');
    titleInput.type = 'text';
    titleInput.setAttribute('placeholder', 'Review title (optional)');
    titleInput.setAttribute('aria-label', 'Review title');
    var openBtn = button('Open review', 'prr-primary prr-open-btn', function () { openReview(); });
    var sampleBtn = button('Load sample diff', 'prr-sample-btn', function () {
      diffInput.value = SAMPLE_DIFF;
      setStatus('Sample diff loaded - press "Open review".', false);
    });
    openRow.appendChild(titleInput);
    openRow.appendChild(openBtn);
    openRow.appendChild(sampleBtn);
    openBox.appendChild(diffInput);
    openBox.appendChild(openRow);
    root.appendChild(openBox);

    var statusEl = el('div', 'prr-status');
    statusEl.setAttribute('role', 'status');
    root.appendChild(statusEl);

    var reviewEl = el('section', 'prr-review');
    root.appendChild(reviewEl);
    containerEl.appendChild(root);

    function setStatus(message, isError) {
      statusEl.textContent = message || '';
      statusEl.className = 'prr-status' + (isError ? ' prr-err' : '');
    }

    function fail(err) {
      setStatus((err && err.message) ? err.message : 'Request failed', true);
    }

    function applyReview(payload) {
      var review = payload && payload.review ? payload.review : payload;
      if (!review) { return; }
      state.review = review;
      state.reviewId = review.review_id || state.reviewId;
      render();
    }

    function openReview() {
      var diff = diffInput.value || '';
      if (!diff.trim()) {
        setStatus('Paste a unified diff first (or load the sample).', true);
        return;
      }
      setStatus('Opening review...', false);
      apiCall('POST', '/reviews', { diff: diff, title: titleInput.value || '' })
        .then(function (data) {
          applyReview(data);
          setStatus('Review ' + state.reviewId + ' opened - ' +
            (state.review.hunks || []).length + ' hunks ranked highest-risk-first.', false);
        })
        .catch(fail);
    }

    function refresh() {
      if (!state.reviewId) { return Promise.resolve(null); }
      return getJson('/reviews/' + encodeURIComponent(state.reviewId))
        .then(function (data) { applyReview(data); return data; })
        .catch(function (err) { fail(err); return null; });
    }

    function addComment(hunkId, author, body, blocking) {
      return apiCall('POST', '/reviews/' + encodeURIComponent(state.reviewId) + '/comments', {
        hunk_id: hunkId, author: author, body: body, blocking: blocking
      }).then(function (data) {
        applyReview(data);
        setStatus('Comment ' + data.comment.comment_id + ' added on ' + hunkId + '.', false);
      }).catch(fail);
    }

    function replyTo(commentId, author, body) {
      return apiCall(
        'POST',
        '/reviews/' + encodeURIComponent(state.reviewId) + '/comments/' + encodeURIComponent(commentId) + '/replies',
        { author: author, body: body }
      ).then(function (data) {
        applyReview(data);
        setStatus('Replied to ' + commentId + '.', false);
      }).catch(fail);
    }

    function resolveThread(commentId) {
      return apiCall(
        'POST',
        '/reviews/' + encodeURIComponent(state.reviewId) + '/comments/' + encodeURIComponent(commentId) + '/resolve',
        {}
      ).then(function (data) {
        applyReview(data);
        setStatus('Thread ' + commentId + ' resolved.', false);
      }).catch(fail);
    }

    function handOffFix(commentId) {
      return apiCall(
        'POST',
        '/reviews/' + encodeURIComponent(state.reviewId) + '/comments/' + encodeURIComponent(commentId) + '/fix-task',
        {}
      ).then(function (data) {
        applyReview(data);
        setStatus('Fix task ' + data.fix_task.task_id + ' created for hunk ' + data.fix_task.hunk_id + '.', false);
      }).catch(fail);
    }

    function approve() {
      return apiCall('POST', '/reviews/' + encodeURIComponent(state.reviewId) + '/approve', { approver: 'reviewer' })
        .then(function (data) {
          applyReview(data);
          setStatus('Approved by ' + (data.approved_by || 'reviewer') + '.', false);
        })
        .catch(function (err) {
          if (err && err.data && err.data.review) { applyReview(err.data); }
          fail(err);
        });
    }

    // ---- rendering -------------------------------------------------------
    function commentsForHunk(hunkId) {
      var all = (state.review && state.review.comments) || [];
      var out = [];
      for (var i = 0; i < all.length; i++) {
        if (all[i].hunk_id === hunkId) { out.push(all[i]); }
      }
      return out;
    }

    function renderCommentNode(comment, isReply) {
      var node = el('div', 'prr-comment' + (isReply ? ' prr-reply' : ''));
      node.setAttribute('data-comment-id', comment.comment_id);
      var head = el('div', '');
      head.appendChild(el('span', 'prr-author', comment.author || 'reviewer'));
      head.appendChild(el('span', 'prr-tag', comment.comment_id));
      if (comment.blocking) { head.appendChild(el('span', 'prr-tag prr-tag-block', 'blocking')); }
      if (comment.resolved) { head.appendChild(el('span', 'prr-tag prr-tag-res', 'resolved')); }
      node.appendChild(head);
      node.appendChild(el('p', 'prr-body', comment.body || ''));

      var acts = el('div', 'prr-acts');
      if (!comment.resolved) {
        acts.appendChild(button('Reply', 'prr-reply-btn', function () {
          var text = window.prompt('Reply to ' + comment.comment_id + ':');
          if (text && text.trim()) { replyTo(comment.comment_id, 'reviewer', text.trim()); }
        }));
        acts.appendChild(button('Resolve thread', 'prr-resolve-btn', function () {
          resolveThread(comment.comment_id);
        }));
        acts.appendChild(button('Hand off fix', 'prr-fix-btn', function () {
          handOffFix(comment.comment_id);
        }));
      }
      if (acts.childNodes.length) { node.appendChild(acts); }
      return node;
    }

    function renderThreads(hunkId) {
      var frag = document.createDocumentFragment();
      var comments = commentsForHunk(hunkId);
      var roots = comments.filter(function (c) { return !c.parent_id; });
      if (!roots.length) {
        frag.appendChild(el('p', 'prr-empty', 'No comments on this hunk yet.'));
        return frag;
      }
      roots.forEach(function (root_) {
        var thread = el('div', 'prr-thread');
        thread.appendChild(renderCommentNode(root_, false));
        comments.filter(function (c) { return c.parent_id === root_.comment_id; })
          .forEach(function (reply) { thread.appendChild(renderCommentNode(reply, true)); });
        frag.appendChild(thread);
      });
      return frag;
    }

    function renderHunk(hunk, rank) {
      var box = el('article', 'prr-hunk');
      box.setAttribute('data-hunk-id', hunk.hunk_id);
      box.setAttribute('data-risk-score', String(hunk.risk_score));

      var head = el('div', 'prr-hunk-head');
      head.appendChild(el('span', 'prr-rank', '#' + rank));
      var band = String(hunk.risk_band || 'low');
      head.appendChild(el('span', 'prr-risk prr-risk-' + band, 'risk ' + hunk.risk_score + ' - ' + band));
      head.appendChild(el('span', 'prr-file', hunk.file_path));
      var meta = '+' + hunk.added + ' / -' + hunk.removed;
      if (hunk.touches_security) { meta += ' - security'; }
      if (hunk.touches_tests) { meta += ' - tests'; }
      head.appendChild(el('span', 'prr-meta', meta));
      box.appendChild(head);

      var body = el('div', 'prr-hunk-body');
      body.appendChild(el('p', 'prr-header-line', hunk.header || ''));
      body.appendChild(renderThreads(hunk.hunk_id));

      var form = el('div', 'prr-row');
      var input = el('input', 'prr-input prr-comment-input');
      input.type = 'text';
      input.setAttribute('placeholder', 'Add a comment on ' + hunk.hunk_id + '...');
      input.setAttribute('aria-label', 'Comment on ' + hunk.hunk_id);
      var blockLabel = el('label', 'prr-meta');
      var blockBox = document.createElement('input');
      blockBox.type = 'checkbox';
      blockBox.className = 'prr-blocking-box';
      blockLabel.appendChild(blockBox);
      blockLabel.appendChild(document.createTextNode(' blocking'));
      var addBtn = button('Add comment', 'prr-add-btn', function () {
        var text = (input.value || '').trim();
        if (!text) {
          setStatus('Comment body cannot be empty.', true);
          return;
        }
        addComment(hunk.hunk_id, 'reviewer', text, blockBox.checked);
      });
      form.appendChild(input);
      form.appendChild(blockLabel);
      form.appendChild(addBtn);
      body.appendChild(form);

      box.appendChild(body);
      return box;
    }

    function renderApprovalBar() {
      var review = state.review;
      var bar = el('div', 'prr-approve');
      var row = el('div', 'prr-row');
      var blocked = !review.can_approve;
      var label = review.approved ? 'Approved' : 'Approve PR';
      var btn = button(label, 'prr-primary prr-approve-btn', function () { approve(); });
      btn.disabled = blocked || !!review.approved;
      btn.setAttribute('data-blocked', blocked ? '1' : '0');
      row.appendChild(btn);
      if (review.approved) {
        row.appendChild(el('span', 'prr-ok', 'Approved by ' + (review.approved_by || 'reviewer')));
      } else if (blocked) {
        row.appendChild(el('span', 'prr-err prr-meta', 'Approval blocked'));
      } else {
        row.appendChild(el('span', 'prr-ok', 'No blocking comments - approval permitted'));
      }
      bar.appendChild(row);

      var reasons = review.blocking_reasons || [];
      if (reasons.length) {
        var list = el('ul', 'prr-blocked prr-reasons');
        reasons.forEach(function (reason) { list.appendChild(el('li', '', reason)); });
        bar.appendChild(list);
      }
      return bar;
    }

    function renderFixTasks() {
      var tasks = (state.review && state.review.fix_tasks) || [];
      if (!tasks.length) { return null; }
      var box = el('div', 'prr-tasks');
      box.appendChild(el('div', 'prr-author', 'Fix handoffs (' + tasks.length + ')'));
      tasks.forEach(function (task) {
        var row = el('div', 'prr-task');
        row.setAttribute('data-task-id', task.task_id);
        row.setAttribute('data-hunk-id', task.hunk_id);
        var head = el('div', '');
        head.appendChild(el('span', 'prr-task-id', task.task_id));
        head.appendChild(el('span', 'prr-tag', 'hunk ' + task.hunk_id));
        head.appendChild(el('span', 'prr-tag', 'from ' + task.comment_id));
        head.appendChild(el('span', 'prr-risk prr-risk-' + String(task.risk_band),
          'risk ' + task.risk_score + ' - ' + task.risk_band));
        if (task.blocking) { head.appendChild(el('span', 'prr-tag prr-tag-block', 'blocking')); }
        row.appendChild(head);
        row.appendChild(el('div', 'prr-file', task.file_path + '  ' + (task.hunk_header || '')));
        row.appendChild(el('p', 'prr-body', task.instruction || ''));
        box.appendChild(row);
      });
      return box;
    }

    function render() {
      reviewEl.textContent = '';
      var review = state.review;
      if (!review) { return; }

      reviewEl.appendChild(renderApprovalBar());

      var hunks = review.hunks || [];
      var list = el('div', 'prr-hunks');
      hunks.forEach(function (hunk, index) { list.appendChild(renderHunk(hunk, index + 1)); });
      reviewEl.appendChild(list);

      var tasks = renderFixTasks();
      if (tasks) { reviewEl.appendChild(tasks); }
    }

    var panel = {
      element: root,
      state: state,
      openReview: openReview,
      refresh: refresh,
      approve: approve,
      addComment: addComment,
      replyTo: replyTo,
      resolveThread: resolveThread,
      handOffFix: handOffFix,
      loadSample: function () { diffInput.value = SAMPLE_DIFF; },
      sampleDiff: SAMPLE_DIFF,
      destroy: function () {
        containerEl.textContent = '';
        containerEl.removeAttribute('data-prr-mounted');
        delete containerEl.__prrPanel;
      }
    };
    containerEl.__prrPanel = panel;
    return panel;
  };
})();
