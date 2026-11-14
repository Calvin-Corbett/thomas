/* Chat shell bindings. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Wire up ----------
    deps.inputEl.addEventListener('input', e => { deps.state.input = e.target.value; deps.autosize(); deps.syncDynamic(); });

    deps.inputEl.addEventListener('keydown', e => {
      // Enter that ends an IME composition (Japanese, Chinese, Korean input) picks a word; it is not a send.
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); deps.send(); return; }
      // Escape in an EMPTY Build composer stops the live run, paused or not --
      // the status line's Stop, from the keyboard. An open menu keeps Escape.
      if (e.key !== 'Escape' || e.isComposing || deps.state.input.trim()) return;
      if (deps.state.libraryMenuOpen || deps.state.toolsMenuOpen || deps.state.modelMenuOpen) return;
      if (document.body && document.body.classList && document.body.classList.contains('thomas-ui-editing')) return;
      const unified = window.ThomasUnifiedModes;
      const code = window.ThomasCodeMode;
      if (unified && unified.mode() === 'code' && code && typeof code.stopRun === 'function' && code.stopRun()) e.preventDefault();
      // The same key does the same thing in Work: an empty composer and a running reply.
      else if (unified && unified.mode() === 'work' && unified.stop()) e.preventDefault();
    });

    document.getElementById('tc-send').addEventListener('click', () => {
      const unified = window.ThomasUnifiedModes;
      if (unified && unified.mode() !== 'chat') {
        // Typed text sends (queues if the mode is busy — Codex-style).
        if (deps.state.input.trim()) { deps.send(); return; }
        // Build with an EMPTY composer: the button is Pause, Resume or Stop
        // and the run picks which (unified_code_composer.js primaryState).
        // It never falls through to Chat below: Pause must not stop a Chat
        // reply streaming in the same page.
        const code = window.ThomasCodeMode;
        if (unified.mode() === 'code' && code && typeof code.primaryAction === 'function') { void code.primaryAction(); return; }
        // Elsewhere an empty composer while busy stops the run.
        if (unified.stop()) return;
      }
      // Same rule in Chat: typed text sends (send() queues it mid-reply, which
      // is what the arrow icon promises); only an EMPTY composer stops the run.
      if (deps.isChatBusy() && !deps.state.input.trim()) { void deps.stopChat(); }
      else { deps.send(); }
    });

    document.getElementById('tc-search').addEventListener('input', e => { deps.state.search = e.target.value; deps.renderChats(); });
    // Search is an icon beside New chat. Pressing it turns the whole row into the search box; Escape, or leaving the
    // box empty, gives the row back. You said: "clicking it makes the new task button go away and the whole thing be
    // the search bar saves space."
    const newRow = document.getElementById('tc-newrow'), searchOpen = document.getElementById('tc-search-open'), searchBox = document.getElementById('tc-search');
    const setSearching = (on) => { newRow.classList.toggle('is-searching', on); searchOpen.setAttribute('aria-expanded', String(on)); if (on) searchBox.focus(); };
    searchOpen.addEventListener('click', () => setSearching(true));
    searchBox.addEventListener('blur', () => { if (!searchBox.value) setSearching(false); });
    searchBox.addEventListener('keydown', e => { if (e.key !== 'Escape') return; searchBox.value = ''; searchBox.dispatchEvent(new Event('input', { bubbles: true })); setSearching(false); searchOpen.focus(); });

    // Renaming, pinning, archiving or deleting a row re-renders through the
    // owner of the list rather than the decorator patching the DOM behind it.
    if (window.ThomasSidebarHistory) window.ThomasSidebarHistory.onRefresh(deps.renderChats);

    document.getElementById('tc-newchat').addEventListener('click', deps.newChat);

    document.getElementById('tc-sidebar-toggle').addEventListener('click', deps.toggleSidebar);

    document.getElementById('tc-settings').addEventListener('click', () => deps.openWorkspace('settings'));

    // In Chat this button is the Canvas toggle — it opens the inline panel where
    // Thomas is drawing and closes it again, restoring whatever this conversation
    // last rendered. It must NOT navigate to the app_builder workspace: that hides
    // the chat AND the Canvas, which is the opposite of what the control says.
    // The full Canvas workspace is still reachable from the sidebar.
    // Inside a workspace the button keeps its other meaning (resident-Thomas drawer).
    document.getElementById('tc-canvas-btn').addEventListener('click', () => {
      if (deps.state.workspaceOpen && window.ThomasWorkspaceChat) window.ThomasWorkspaceChat.toggle();
      else if (deps.state.artifactOpen) deps.closeCanvas();
      else deps.openConversationCanvas();
    });

    document.getElementById('tc-canvas-close').addEventListener('click', deps.closeCanvas);

    document.getElementById('tc-theme-btn').addEventListener('click', deps.toggleThemeMenu);

    document.getElementById('tc-model-btn').addEventListener('click', deps.toggleModelMenu);

    document.getElementById('tc-tools-btn').addEventListener('click', deps.toggleToolsMenu);

    document.getElementById('tc-code-project-btn').addEventListener('click', deps.toggleLibraryMenu);

    deps.bindLibraryActions();

    document.getElementById('tc-code-library-menu').addEventListener('input', (e) => {
      if (e.target && e.target.id === 'tc-library-filter') {
        deps.state.libraryFilter = e.target.value;
        const body = document.getElementById('tc-library-body');
        const items = deps.libraryVisibleProjects();
        if (!body) return;
        // Re-render only the results, so the field keeps focus and the caret.
        body.innerHTML = items.length
          ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(184px,1fr));gap:12px;">${items.map(deps.libraryCardHTML).join('')}</div>`
          : `<div style="padding:30px 16px;text-align:center;color:var(--c-muted);font-size:13px;">No project matches “${deps.esc(deps.state.libraryFilter)}”.</div>`;
        deps.mountLibraryPreviews();
      }
    });

    document.getElementById('tc-file-input').addEventListener('change', (e) => { deps.onFiles(e.target.files); e.target.value = ''; });

    // Paste and drop take files the way the picker does: a screenshot, a PDF, anything. A pasted screenshot is always
    // called "image.png", so each gets its own name (two of them would otherwise overwrite each other in the project).
    const composerInput = document.getElementById('tc-input');
    const composerBox = document.querySelector?.('[data-ui-id="chat.composer"]') || composerInput;
    const withOwnName = (files) => files.map((file, i) => {
      if (file.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(file.name)) return file;
      const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace(/[^a-z0-9]/gi, '');
      return new File([file], `pasted-${Date.now().toString(36)}-${i + 1}.${ext}`, { type: file.type });
    });
    const carriesFiles = (event) => Array.from((event.dataTransfer && event.dataTransfer.types) || []).includes('Files');
    if (composerInput) {
      composerInput.addEventListener('paste', (event) => {
        const files = Array.from((event.clipboardData && event.clipboardData.files) || []);
        if (!files.length) return;  // plain text pastes as it always did
        event.preventDefault();
        deps.onFiles(withOwnName(files));
      });
    }
    if (composerBox) {
      ['dragenter', 'dragover'].forEach((type) => composerBox.addEventListener(type, (event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        composerBox.classList.add('is-dropping');
      }));
      composerBox.addEventListener('dragleave', (event) => { if (!composerBox.contains(event.relatedTarget)) composerBox.classList.remove('is-dropping'); });
      composerBox.addEventListener('drop', (event) => {
        composerBox.classList.remove('is-dropping');
        const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
        if (!files.length) return;
        event.preventDefault();
        deps.onFiles(withOwnName(files));
      });
    }

    document.addEventListener('mousedown', e => {
      if (deps.state.themeMenuOpen && !e.target.closest('[data-theme-switch]')) { deps.state.themeMenuOpen = false; document.getElementById('tc-theme-menu').style.display = 'none'; }
      if (deps.state.modelMenuOpen && !e.target.closest('[data-model-switch]')) { deps.closeModelMenu(); }
      if (deps.state.toolsMenuOpen && !e.target.closest('[data-tools-wrap]')) { deps.closeToolsMenu(); }
      if (deps.state.libraryMenuOpen && !e.target.closest('[data-code-library-wrap]')) { deps.closeLibraryMenu(); }
    });

    // Escape closes the library. Nothing in this page handled Escape before, so
    // the guard matters: UI Edit Mode uses Escape too and must keep it.
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (document.body.classList.contains('thomas-ui-editing')) return;
      if (deps.state.libraryMenuOpen) { e.preventDefault(); deps.closeLibraryMenu({ restoreFocus: true }); }
    });
    return {  };
  }
  window.ThomasChatShellBindings = { create };
})();
