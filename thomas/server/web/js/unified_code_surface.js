/* Build surface. The mode supplies shared state and actions. */
(function () {
  'use strict';
  function create(deps) {

    function shellWindow() {
      try { if (window.top && window.top.ThomasBrowserShell) return window.top.ThomasBrowserShell; } catch (error) { /* another origin */ }
      return window.ThomasBrowserShell || null;
    }

    async function keepAll() {
      const paths = deps.state.changes.map(change => change.file).filter(file => !deps.isInternalResultPath(file));
      for (const file of paths) {
        if (!(await deps.changeAction('keep', file, undefined, { deferRender: true }))) break;
      }
      render();
    }

    // The transcript's own buttons, delegated once per surface: they are drawn
    // by unified_code_cards.js inside markup that is rebuilt on every render
    // (an ask's options answer through the run's controls).
    const boundRoots = new WeakSet();
    const keptTurns = new Set();
    function bindTranscript(root) {
      if (boundRoots.has(root) || typeof root.addEventListener !== 'function') return;
      boundRoots.add(root);
      root.addEventListener('click', event => {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) return;
        const option = target.closest('[data-code-ask-option]');
        if (option && !option.disabled) { void deps.controls.answer(option.dataset.questionId, option.dataset.label); return; }
        const fix = target.closest('[data-code-proof-fix]');
        if (fix) {
          const context = deps.host().getContext ? deps.host().getContext() : deps.state.lastContext || {};
          void deps.safely(() => deps.send(fix.dataset.codeProofFix, context), 'Could not start the fix.');
          return;
        }
        const turn = target.closest('.tc-code-turn');
        if (target.closest('[data-code-proof-trace]')) {
          turn?.querySelector('.tc-code-receipts')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
          return;
        }
        if (target.closest('[data-code-proof-keep]')) {
          keptTurns.add(turn?.dataset.codeTurnKey || '');
          turn?.querySelector('.tc-code-proof-actions')?.remove();
          return;
        }
        if (target.closest('[data-code-keep-all]')) { void deps.safely(keepAll, 'Could not keep every change.'); return; }
        if (target.closest('[data-code-review-files]')) { deps.state.drawerOpen = true; render(); return; }
        const open = target.closest('[data-code-artifact-open]');
        const shell = open ? shellWindow() : null;
        if (open && shell && typeof shell.openTab === 'function') {
          event.preventDefault();
          shell.openTab(new URL(open.getAttribute('href'), location.href).href);
        }
      });
      root.addEventListener('toggle', event => {
        if (event.target && event.target.matches && event.target.matches('[data-code-files]')) deps.state.drawerFilesOpen = event.target.open;
      }, true);
    }

    function render() {
      if (!deps.adapterActive) return;
      const root = deps.surface(); if (!root) return;
      if (deps.state.actionLine && deps.state.actionLine.conversationId !== deps.state.activeId) deps.state.actionLine = null;
      // The run's controls: who is on it (live frames, or the newest saved turn).
      const controls = deps.controls;
      controls.syncRoster();
      const savedRenderState = window.ThomasCodeViewState.capture(root, deps.transcriptScroller(root));
      const opening = Boolean(deps.state.openingConversationId);
      if (!opening && window.ThomasCodeLoading) window.ThomasCodeLoading.hide();
      const statusLabels = { ready: 'Ready', blocked: 'Check Tools', working: 'Working', stopping: 'Stopping', approval: 'Approval required', completed: 'Completed', noop: 'No changes made', stopped: 'Stopped', disconnected: 'Disconnected', failed: 'Needs attention' };
      // While another task is opening, the one that was on screen is gone at once: no old turns, no old live lines.
      const turns = !opening && deps.state.conversation && Array.isArray(deps.state.conversation.turns) ? deps.state.conversation.turns : [];
      const liveEvents = opening ? [] : deps.state.liveEvents;
      // A long task drew every turn's whole narrative (34 turns: 14,000 elements, 1.7 MB, laid out on every render).
      // Only the newest few are drawn; the rest open in place from a button, kept for this task while it is on screen.
      const KEEP = 8;
      if (!deps.state.turnWindow || deps.state.turnWindow.id !== deps.state.activeId) deps.state.turnWindow = { id: deps.state.activeId, from: Math.max(0, turns.length - KEEP) };
      const firstShown = Math.min(deps.state.turnWindow.from, turns.length);
      const earlierHtml = firstShown > 0 ? `<button type="button" class="tc-code-earlier" data-code-earlier>Show ${firstShown} earlier ${firstShown === 1 ? 'turn' : 'turns'}</button>` : '';
      const history = deps.state.conversation && deps.state.conversation.continuation_history;
      // Autopilot's own follow-ups are a card: what it is doing now, how each ended, a summary of the task.
      const lastUser = turns.slice().reverse().find(turn => turn && turn.role === 'user');
      const header = window.ThomasCodeHeader;
      const sums = header && header.totals ? { ...header.totals(deps.state), files: header.fileCount ? header.fileCount(deps.state) : 0 } : null;
      const continuationHtml = window.ThomasCodeContinuation
        ? window.ThomasCodeContinuation.html({ history, running: Boolean(deps.state.running), live: /^Autopilot:/.test(String((lastUser && lastUser.text) || deps.state.pendingUserText || '')), totals: sums }, deps.esc)
        : '';
      const liveFinalEvent = deps.finalReplyEvent(liveEvents);
      const liveActivityEvents = deps.progressEvents(liveEvents, liveFinalEvent);
      // Codex-style: stream EVERY action inline in arrival order as it happens —
      // tool runs and terminal commands ("Used Read", "Ran terminal command") land
      // right next to the narrative updates instead of being hidden in a collapsed
      // "Show details" block. (Owner: "he doesn't output stuff in the chat, he
      // outputs it in the activity thing on the side.")
      const liveNarrative = deps.interleavedActivityHtml(liveActivityEvents, false);
      const liveErrors = liveEvents.filter(event => deps.eventType(event) === 'error');
      // The live half of the never-suppress rule (the durable half lives in
      // turnHtml): a failed run that nevertheless produced a final answer used to
      // show only the answer here -- the `? :` made the two mutually exclusive --
      // so the failure was invisible until the durable render replaced this, and
      // when that render was the OLD one it dropped the answer instead. Both
      // render now: the answer first, the failure note alongside. The note joins
      // the answer only once the run has actually landed as failed; a recovered
      // mid-run error next to a successful final would be an alarm about a
      // problem the run already solved.
      const liveAnswer = liveFinalEvent ? deps.replyBlockHtml(deps.eventLabel(liveFinalEvent)) : '';
      // Named for what it tests -- the RUN's landed status, not any one event's
      // failure. Per-event failure flags must route through eventFailed() (the
      // guard in test_a_failure_row_does_not_show_a_success_tick.py pins that);
      // this is the other axis.
      const liveRunLandedBad = deps.state.runStatus === 'failed' || deps.state.runStatus === 'disconnected';
      const liveFailureNote = liveErrors.length && (!liveFinalEvent || liveRunLandedBad)
        ? `<div class="tc-code-reply is-error">${deps.esc(deps.failureSummary({ ok: false }, liveErrors))}</div>` : '';
      const liveReply = liveAnswer + liveFailureNote;
      const liveTechnical = '';
      // Hoisted so the empty state below is decided by the SAME condition that
      // decides whether a live turn is drawn. Two expressions meaning "a run is on
      // screen" is how they drift apart and both render at once -- which is
      // precisely the bug this fixes.
      const hasLiveTurn = Boolean(!opening && (deps.state.running || liveEvents.length));
      // The page you SEND from never showed you your own message. `turns` comes
      // from `state.conversation`, which is only refreshed from the server, so
      // between pressing Enter and the run finishing the words you just typed were
      // nowhere on screen. Measured on a live run at 1920:
      // `.tc-code-turn.is-user` count was 0 while the live turn was already
      // streaming, and the same conversation opened in a second tab showed the
      // message fine -- so it was never missing data, only a missing render.
      //
      // Suppressed as soon as the server's copy arrives, decided at RENDER time
      // rather than cleared on a lifecycle event. A clear that fires at the wrong
      // moment leaves either no bubble or two identical ones; this cannot do
      // either, because the pending copy is simply not drawn once `turns` has it.
      // Compared on trimmed text, which is what the server round-trips.
      const pendingUser = opening ? '' : String(deps.state.pendingUserText || '').trim();
      const serverHasPending = Boolean(
        pendingUser
        && turns.some(turn => turn && turn.role === 'user' && String(turn.text || '').trim() === pendingUser),
      );
      const pendingUserTurn = pendingUser && !serverHasPending
        ? `<div class="tc-code-pending-user">${deps.turnHtml({ role: 'user', text: pendingUser, attachments: deps.state.pendingAttachments })}</div>`
        : '';
      // The live turn reads in design 3a's order: the STEPS card (or the team's tally), the feed,
      // the file being written right now, your steers on their way, then any
      // question Thomas is asking you -- in its own slot, so a busy feed never
      // scrolls it away. `is-live` only while the run actually is: a stopped
      // run's turn must not read as working.
      const liveTurn = hasLiveTurn
        ? `<article class="tc-code-turn is-agent${deps.state.running ? ' is-live' : ''}" data-code-live-turn data-code-turn-key="${deps.esc(deps.state.runId || '')}"><div class="tc-code-turn-body"><div data-code-live-steps>${controls.liveStepsHtml()}</div><div id="tc-code-live-events" aria-live="polite" aria-relevant="additions text">${liveNarrative}</div><div id="tc-code-live-technical">${liveTechnical}</div><div data-code-live-diff>${controls.liveDiffHtml()}</div><div data-code-live-steers>${controls.steerChipsHtml()}</div><div data-code-live-ask>${controls.liveAskHtml()}</div>${liveReply}</div></article>`
        : '<div id="tc-code-live-events" hidden></div><div id="tc-code-live-technical" hidden></div>';
      const visibleChanges = deps.state.changes.filter(change => !deps.isInternalResultPath(change.file));
      const historyNotice = deps.state.changesNotice && deps.state.changesNotice.id === deps.state.activeId
        ? `<li class="tc-code-muted" role="status" data-code-history-notice>${deps.esc(deps.state.changesNotice.text)}</li>` : '';
      const treeRows = historyNotice + deps.state.tree.slice(0, 120).map(row => row.kind === 'directory' ? `<li class="is-dir"><button data-code-tree-dir="${deps.esc(row.path)}"><i class="ph ph-caret-right"></i>${deps.esc(row.name)}</button></li>` : row.kind === 'file' ? `<li><button data-code-tree-file="${deps.esc(row.path)}"><i class="ph ph-file-code"></i><span>${deps.esc(row.name || row.path || '')}</span></button></li>` : `<li><i class="ph ph-file"></i>${deps.esc(row.name || row.path || '')}</li>`).join('');
      const artifacts = [];
      const artifactKeys = new Set();
      turns.flatMap(turn => turn.artifacts || []).concat(deps.state.artifacts).filter(artifact => !deps.isInternalResultPath(artifact.file)).forEach(artifact => {
        const key = `${artifact.file || ''}\u0000${artifact.kind || ''}`;
        if (!artifactKeys.has(key)) { artifactKeys.add(key); artifacts.push(artifact); }
      });
      // The drawer (design 3a) lists the agents, the files they hold, and the
      // changed files with Keep / Revert under OUTPUTS. What it held before --
      // the deliverable's rows, a file you opened, the checkpoint and the
      // project's file tree -- folds into one "Files" section beneath them, so
      // the deliverable is no longer listed twice under one heading.
      const artifactRows = artifacts.map(deps.codeResults().artifactHtml).join('');
      // Watch it build. A generated page is far more useful rendered than as
      // source, and during a run this refreshes, so you see the thing take shape
      // instead of reading a diff and hoping. Sandboxed WITHOUT allow-same-origin:
      // srcdoc inherits this page's origin, and a generated app must never be
      // able to reach into Thomas. Scripts run, so games and animations work;
      // localStorage does not, which a small number of generated apps rely on.
      const previewIsPage = deps.state.filePreview && /\.x?html?$/i.test(String(deps.state.filePreview.path || ''));
      const previewBody = (previewIsPage && deps.state.filePreviewRendered !== false)
        // A miniature of the page, not a crop of its top-left corner.
        //
        // This rendered the document at 1:1 into the drawer's ~247px column, so a
        // layout built for ~1200px arrived as a keyhole: "Sort by amount" cut to
        // "Sort by", the table header reading "DATE DESCRIPTION AM…", about a
        // fifth of the page visible and every edge sliced mid-word. It reads as a
        // broken render rather than a preview.
        //
        // Exactly the mistake the artifact thumbnail had and had already fixed --
        // a different element, so the fix never reached here. Same fixed box and
        // same fixed scale, deliberately not percentages: the drawer is resizable
        // (280-520px) and a proportional preview would drift with it instead of
        // being the same picture every time. 1280x1600 at 0.19375 lands on
        // 248x310, which is the thumbnail's scale over twice its height, because
        // this one was opened on purpose.
        ? `<div class="tc-code-file-shot"><iframe title="Preview of ${deps.esc(deps.state.filePreview.path)}" sandbox="allow-scripts" srcdoc="${deps.esc(String(deps.state.filePreview.content || ''))}" tabindex="-1" scrolling="no"></iframe></div>`
        : (deps.state.filePreview ? `<pre>${deps.esc(deps.state.filePreview.content)}</pre>` : '');
      const previewToggle = previewIsPage
        ? `<button data-code-preview-toggle style="margin-right:6px;">${deps.state.filePreviewRendered === false ? 'Show page' : 'Show code'}</button>`
        : '';
      const preview = deps.state.filePreview ? `<section class="tc-code-file-preview"><header><strong>${deps.esc(deps.state.filePreview.path)}</strong>${previewToggle}<button data-code-file-close aria-label="Close file preview"><i class="ph ph-x"></i></button></header>${previewBody}</section>` : '';
      const approval = deps.state.pendingApproval ? `<section class="tc-code-approval" role="alert" data-ui-id="code.approval" data-ui-label="Approval required" data-ui-policy="protected"><strong>Approval required</strong><p>${deps.esc(deps.state.pendingApproval.summary)}</p><div><button data-code-approve ${deps.state.approvalBusy ? 'disabled' : ''}>${deps.state.approvalBusy ? 'Approving...' : 'Approve once'}</button><button data-code-approval-cancel ${deps.state.approvalBusy ? 'disabled' : ''}>Cancel</button></div></section>` : '';
      // The history question -- raised by newConversation's 409 branch, asked and
      // answered in the projects module beside it.
      const historyAsk = deps.historyAskHtml();
      const projectLabel = deps.state.projectRoot ? deps.codeProjects().projectDisplayLabel() : 'Choose a project';
      // An empty file list has three different causes and used to name only one:
      // it always read "Choose a project beside Tools to browse its files."
      //
      // Measured on a new task: for 45 seconds -- the whole run -- the drawer
      // header said "Build task 2026-07-30 1018" while the list directly beneath it
      // told you to choose a project. The header has always used `state.projectRoot`
      // for exactly this decision; the list simply did not ask.
      //
      // `treeLoaded` separates the other two, which no existing field could: a
      // fetch that has not returned yet is not the same as a folder with nothing
      // in it, and saying "no files" while still loading would be the same kind of
      // guess in a new coat.
      const filesEmptyMessage = !deps.state.projectRoot
        ? 'Choose a project beside Tools to browse its files.'
        : (deps.state.treeLoaded ? 'This folder has no files yet.' : 'Loading files…');
      // `is-viewer-open` lets the layout make room for the viewer.
      //
      // The artifact card promises "Click to open it beside the chat" and the
      // viewer's own stylesheet comment says "beside the conversation", but it is
      // `position: absolute`, so it never moved anything: measured at 1920 wide,
      // the transcript stayed 768px at x=716 while the viewer covered x=1160
      // onward -- 324px of the conversation underneath it, clipping 300px off
      // every line of Thomas's reply mid-word.
      //
      // Not applied when the viewer is full-bleed: it covers the surface
      // deliberately then, and reserving room behind it would only squeeze a
      // layout nobody can see.
      const viewerOpen = Boolean(deps.state.viewer && deps.state.viewer.file);
      const viewerFull = Boolean(deps.state.viewer && deps.state.viewer.full);
      deps.codeResults().publishColumnState(viewerOpen && !viewerFull);
      const statusLabel = opening ? 'Opening…' : statusLabels[deps.state.runStatus] || 'Ready';
      // The checkpoint commits the changed files, so it waits for the run to end.
      const checkpoint = visibleChanges.length && !deps.state.running ? `<button id="tc-code-checkpoint" class="tc-code-checkpoint" data-ui-id="code.action.checkpoint" data-ui-label="Checkpoint changes" data-ui-policy="protected" title="Commit these changes on a thomas-code/ branch">Checkpoint — commit these changes</button>` : '';
      const tree = `<section class="tc-code-rail-section tc-code-tree" data-ui-id="code.files" data-ui-label="Project files" data-ui-policy="move resize" data-ui-constraints="minWidth=240;minHeight=120"><div class="tc-code-tree-head"><div class="tc-code-section-title">${deps.esc(deps.state.treePath || '/')}</div>${deps.state.treePath ? '<button id="tc-code-tree-up">Up</button>' : ''}</div><ul>${treeRows || `<li class="tc-code-muted">${deps.esc(filesEmptyMessage)}</li>`}</ul></section>`;
      const files = `<details class="tc-code-files" data-code-files data-ui-id="code.outputs" data-ui-label="Files and previews" data-ui-policy="move resize" data-ui-constraints="minWidth=240;minHeight=120"${deps.state.drawerFilesOpen || deps.state.filePreview ? ' open' : ''}><summary class="tc-agents-label">Files</summary>${preview}${artifactRows}${checkpoint}${tree}</details>`;
      const drawer = deps.controls.drawerHtml({ changes: visibleChanges, projectLabel, extraHtml: approval + files });
      root.innerHTML = `<div class="tc-code-panel${deps.state.drawerOpen ? ' is-drawer-open' : ''}${viewerOpen && !viewerFull ? ' is-viewer-open' : ''}">
        <header class="tc-code-context" data-ui-id="code.context" data-ui-label="Build activity bar" data-ui-policy="move">${window.ThomasCodeHeader ? window.ThomasCodeHeader.rowHtml(deps.state, deps.esc, deps.isInternalResultPath) : ''}<button data-code-results-jump type="button" aria-expanded="${deps.state.drawerOpen ? 'true' : 'false'}" data-code-status-label="${deps.esc(statusLabel)}">${controls.activityButtonHtml(statusLabel)}</button>${controls.stepPillHtml()}</header>
        <button class="tc-code-jump-badge" data-code-jump-bottom type="button" hidden><i class="ph ph-arrow-down" aria-hidden="true"></i> Scroll to the bottom</button>
        <div class="tc-code-layout">
          <section class="tc-code-transcript" aria-label="Build conversation" data-ui-id="code.transcript" data-ui-label="Build conversation" data-ui-policy="move resize" data-ui-constraints="minWidth=320;minHeight=200">${historyAsk}<div id="tc-code-turns">${opening ? '<div class="tc-code-empty" role="status" aria-live="polite"><strong>Opening build…</strong><p>Loading your conversation.</p></div>' : earlierHtml + turns.map((turn, index, all) => (index < firstShown ? '' : deps.turnHtml(turn, index, all))).join('') || (hasLiveTurn || pendingUserTurn ? '' : deps.emptyStateHtml())}</div>${opening ? '' : continuationHtml}${pendingUserTurn}${liveTurn}${deps.codeResults().playtestChatCardHtml()}</section>
          <aside class="tc-code-actions" aria-label="Build activity" aria-hidden="${deps.state.drawerOpen ? 'false' : 'true'}"${deps.state.drawerOpen ? '' : ' inert'} data-ui-id="code.activity" data-ui-label="Build activity drawer" data-ui-policy="move resize" data-ui-constraints="minWidth=280;minHeight=240;maxWidth=520">${drawer}</aside>
        </div>${deps.codeResults().viewerHtml()}${controls.agentChatHtml()}</div>`;
      const activityDrawer = root.querySelector('.tc-code-actions');
      const transcript = root.querySelector('.tc-code-transcript');
      transcript?.insertAdjacentHTML('afterbegin', window.ThomasSelfEdit?.html(deps.state) || '');
      window.ThomasSelfEdit?.bind(root, deps.state, render);
      window.ThomasSelfEdit?.loadSpeed(root);
      deps.codeResults().bindViewer(root, render);
      activityDrawer?.insertAdjacentHTML('afterbegin', `<div class="tc-code-drawer-resize" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Resize activity drawer" aria-valuemin="280" aria-valuemax="520" aria-valuenow="${deps.state.drawerWidth}"></div>`);
      root.querySelector('[data-code-earlier]')?.addEventListener('click', () => {
        const scroller = deps.transcriptScroller(root);
        const before = scroller ? scroller.scrollHeight - scroller.scrollTop : 0;
        deps.state.turnWindow.from = Math.max(0, deps.state.turnWindow.from - 10);
        render();
        const after = deps.transcriptScroller(root);
        if (after) after.scrollTop = after.scrollHeight - before;  // the turns above appear without moving what you are reading
      });
      root.querySelector('[data-code-results-jump]')?.addEventListener('click', () => { deps.state.drawerOpen = !deps.state.drawerOpen; render(); });
      root.querySelector('[data-code-drawer-close]')?.addEventListener('click', () => { deps.state.drawerOpen = false; render(); });
      if (window.ThomasCodeHeader) window.ThomasCodeHeader.open = file => { void deps.safely(() => deps.loadFile(file), 'Could not preview that file.'); };
      deps.codeResults().bindDrawerResize(root);
      root.querySelector('#tc-code-tree-up')?.addEventListener('click', () => { const parts = deps.state.treePath.split('/'); parts.pop(); void deps.safely(() => deps.loadTree(parts.join('/')), 'Could not open that folder.'); });
      root.querySelectorAll('[data-code-tree-dir]').forEach(button => button.addEventListener('click', () => { void deps.safely(() => deps.loadTree(button.dataset.codeTreeDir), 'Could not open that folder.'); }));
      root.querySelectorAll('[data-code-tree-file]').forEach(button => button.addEventListener('click', () => { void deps.safely(() => deps.loadFile(button.dataset.codeTreeFile), 'Could not preview that file.'); }));
      root.querySelector('[data-code-file-close]')?.addEventListener('click', () => { deps.codeResults().invalidateFileRequest(); deps.state.filePreview = null; render(); });
      root.querySelector('[data-code-preview-toggle]')?.addEventListener('click', () => { deps.state.filePreviewRendered = deps.state.filePreviewRendered === false; render(); });
      deps.codeResults().bindArtifactActions(root);
      root.querySelector('[data-code-approve]')?.addEventListener('click', () => { void deps.safely(deps.approvePending, 'Approval could not be completed.'); });
      root.querySelector('[data-code-approval-cancel]')?.addEventListener('click', () => { deps.state.pendingApproval = null; deps.state.pendingRequest = null; deps.state.runStatus = 'stopped'; deps.pushLiveEvent({ type: 'stopped', text: 'Approval cancelled. No Code action was run.' }); render(); });
      deps.bindHistoryChoice(root);
      // A starter loads the composer and hands the cursor over. It deliberately
      // does NOT send: the text is a suggestion to edit, and a click that quietly
      // spends a model call on a prompt nobody read is the worse surprise.
      root.querySelectorAll('[data-code-starter]').forEach(card => card.addEventListener('click', () => {
        const input = document.getElementById('tc-input');
        if (!input) return;
        input.value = card.dataset.codeStarter || '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        try { input.setSelectionRange(input.value.length, input.value.length); } catch (error) { /* not a text input */ }
      }));
      // Playtest recommendation buttons: a click starts a real fix run with the
      // exact instruction Thomas recommended; "or tell Thomas…" focuses the
      // composer. Either way the verdict card is cleared once acted on.
      root.querySelectorAll('[data-code-playtest-rec]').forEach(button => button.addEventListener('click', () => {
        const prompt = button.dataset.codePlaytestRec || '';
        if (window.ThomasChatModelSelection?.ensureCurrent && !window.ThomasChatModelSelection.ensureCurrent()) return;
        const context = deps.host().getContext ? deps.host().getContext() : deps.state.lastContext || {};
        deps.state.playtestResult = null;
        render();
        if (prompt) void deps.safely(() => deps.send(prompt, context), 'Could not start the fix.');
      }));
      root.querySelector('[data-code-playtest-type]')?.addEventListener('click', () => {
        deps.state.playtestResult = null;
        render();
        document.getElementById('tc-input')?.focus();
      });
      root.querySelector('#tc-code-checkpoint')?.addEventListener('click', () => { void deps.safely(() => deps.checkpointChanges(), 'Could not checkpoint the changes.'); });
      root.querySelectorAll('[data-code-copy-reply]').forEach(button => button.addEventListener('click', () => {
        const reply = button.closest('.tc-code-turn')?.querySelector('.tc-code-reply-text')?.textContent || '';
        void deps.copyReplyText(reply, button);
      }));
      root.querySelectorAll('[data-code-keep]').forEach(button => button.addEventListener('click', () => { void deps.safely(() => deps.changeAction('keep', button.dataset.codeKeep), 'Could not keep that change.'); }));
      root.querySelectorAll('[data-code-revert]').forEach(button => button.addEventListener('click', () => { void deps.safely(() => deps.changeAction('revert', button.dataset.codeRevert), 'Could not revert that change.'); }));
      // The agents (drawer and side chat), the transcript's own buttons, the
      // header, the composer's queue and status line. Bound before the restore,
      // which hands focus back to the side chat's box by id.
      bindTranscript(root);
      // "Keep as is" stays said: a redraw does not bring the turn's buttons back.
      root.querySelectorAll('.tc-code-turn[data-code-turn-key]').forEach(turn => {
        if (keptTurns.has(turn.dataset.codeTurnKey)) turn.querySelector('.tc-code-proof-actions')?.remove();
      });
      controls.afterRender(root);
      window.ThomasCodeViewState.restore(root, savedRenderState, JSON.stringify([deps.state.activeId, deps.state.contextEpoch]), deps.transcriptScroller(root));
      window.ThomasCodeLiveView?.paintExtras?.(deps.state);
      deps.codeProjects().updateProjectButton();
    }
    return { render };
  }
  window.ThomasCodeSurface = { create };
})();
