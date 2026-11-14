/* Chat canvas view. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {

    // openWorkspace() parks the Canvas with visibility+inert (not display), and
    // only showChat() clears them. Opening the panel therefore has to clear them
    // too, or a Canvas opened after any workspace visit is display:flex and still
    // invisible and unclickable.
    function openCanvas() { deps.state.artifactOpen = true; deps.canvasEl.style.display = 'flex'; deps.canvasEl.style.visibility = ''; deps.canvasEl.inert = false; deps.canvasEl.style.animation = 'tc-slide-in .3s cubic-bezier(.4,0,.2,1) both'; deps.shell.classList.add('tc-canvas-open'); renderCanvas(); }

    function closeCanvas() { deps.state.artifactOpen = false; deps.canvasEl.style.display = 'none'; deps.shell.classList.remove('tc-canvas-open'); }

    function resetCanvasForConversation() {
      closeCanvas();
      deps.state.restoredCanvas = null;
      deps.canvasState = { mode: 'blank', worker: '', progress: '', url: '', name: '' };
      deps._build = { execId: '', els: [], delivered: 0, ready: false, done: false };
      deps.canvasBody.innerHTML = '';
    }

    function canvasBuilding(worker, progress) {
      if (deps.canvasState.mode === 'render' || deps.canvasState.mode === 'live') return; // finished/live stays put
      deps.canvasState = { mode: 'building', worker: String(worker || deps.canvasState.worker || ''), progress: String(progress || deps.canvasState.progress || ''), url: '', name: '' };
      if (!deps.state.artifactOpen) openCanvas(); else renderCanvas();
    }

    function _isTextArtifact(kind, url, name) {
      return String(kind || '').toLowerCase() === 'text' || /\.(?:md|markdown|txt|csv|json|log|rst)(?:$|[?#\s])/i.test(String(url || '') + ' ' + String(name || ''));
    }

    async function canvasRender(url, name, kind) {
      if (!url) return;
      if (_isTextArtifact(kind, url, name)) {
        const selectionToken = deps.chatSelectionToken;
        const chatId = deps.state.activeChat;
        const sessionId = String(deps.state.sessionId || '');
        try {
          const response = await fetch(String(url), { headers: { Accept: 'text/plain; charset=utf-8, text/markdown; charset=utf-8' } });
          if (!response.ok) throw new Error('Text preview unavailable');
          const utf8Body = new Blob([await response.arrayBuffer()], { type: 'text/plain;charset=utf-8' });
          const markdown = new TextDecoder('utf-8', { fatal: false }).decode(await utf8Body.arrayBuffer());
          if (selectionToken !== deps.chatSelectionToken || deps.state.activeChat !== chatId || String(deps.state.sessionId || '') !== sessionId) return;
          deps.canvasState = { mode: 'document', worker: '', progress: '', url: '', name: String(name || 'Document'), md: markdown, live: false };
          if (!deps.state.artifactOpen) openCanvas(); else renderCanvas();
          return;
        } catch (e) { /* fall back to the browser's native viewer */ }
      }
      deps.canvasState = { mode: 'render', worker: deps.canvasState.worker, progress: '', url: String(url), name: String(name || 'document') };
      if (!deps.state.artifactOpen) openCanvas(); else renderCanvas();
    }

    function openConversationCanvas() {
      const restored = deps.state.restoredCanvas;
      if (deps.canvasState.mode === 'blank' && restored && restored.chatId === deps.state.activeChat && restored.sessionId === String(deps.state.sessionId || '')) {
        if (restored.mode === 'render' && restored.url) {
          deps.canvasState = { mode: 'render', worker: '', progress: '', url: restored.url, name: restored.name || 'Canvas', kind: restored.kind || 'web' };
        } else if (restored.mode === 'construct') {
          deps._build = { execId: restored.executionId, els: restored.elements || [], delivered: 0, ready: false, done: true };
          deps.canvasState = { mode: 'construct', worker: '', name: 'Canvas', shell: restored.shell || '', finalHtml: restored.html || '', done: true, execId: restored.executionId };
        } else {
          deps.canvasState = { mode: 'live', worker: '', progress: '', url: '', name: 'Canvas', html: restored.html || '', live: false, _written: 0, _fresh: false };
        }
      }
      openCanvas();
    }

    // When the worker stops without a renderable result (failed / cancelled), the
    // Canvas must not spin forever — show an honest end state instead.
    function canvasStop(reason) {
      if (deps.canvasState.mode !== 'building' && deps.canvasState.mode !== 'live' && deps.canvasState.mode !== 'construct') return;
      deps.canvasState = { mode: 'ended', worker: deps.canvasState.worker, progress: String(reason || 'This didn’t finish.'), url: '', name: '' };
      if (deps.state.artifactOpen) renderCanvas();
    }


    function renderCanvas() {
      if (deps.canvasState.mode === 'construct') {
        deps.canvasStatus.textContent = deps.canvasState.done ? (deps.canvasState.name || 'Canvas')
          : ((deps.canvasState.worker || 'Canvas worker') + ' is building this…');
        let f = deps.canvasBody.querySelector('iframe.tc-build-frame');
        if (!f) {
          // Re-opening an already-built canvas → show the static final doc (no re-build).
          if (deps.canvasState.done && deps.canvasState.finalHtml) {
            deps.canvasBody.innerHTML = '<iframe class="tc-live-frame" sandbox="allow-scripts" style="flex:0 0 auto;height:min(68vh,720px);width:100%;border:0;border-radius:10px;background:#fff;"></iframe>';
            const sf = deps.canvasBody.querySelector('iframe.tc-live-frame');
            sf.setAttribute('data-doc-key', 'static');
            sf.setAttribute('srcdoc', deps._staticDoc(deps._injectReveal(deps.canvasState.finalHtml)));
            return;
          }
          // Otherwise mount the empty shell and (re-)arm streaming into it.
          deps.canvasBody.innerHTML = '<iframe class="tc-build-frame" sandbox="allow-scripts" style="flex:0 0 auto;height:min(68vh,720px);width:100%;border:0;border-radius:10px;background:#fff;"></iframe>';
          f = deps.canvasBody.querySelector('iframe.tc-build-frame');
          f.setAttribute('srcdoc', deps.canvasState.shell);
          deps._build.ready = false; deps._build.delivered = 0;  // the fresh iframe re-handshakes + gets all elements
        }
        return;
      }
      if (deps.canvasState.mode === 'live') {
        if (deps.canvasState.live) {
          // GENERATING — hold a calm "drawing" state. We deliberately do NOT stream the
          // half-written HTML into the iframe: a chart front-loads its CSS, so each partial
          // reloads at a different size and the canvas flashes/shrinks/grows. We let the
          // COMPLETE visual draw itself in once (below) — the smooth "magic" moment.
          deps.canvasStatus.textContent = (deps.canvasState.worker || 'Canvas worker') + ' is drawing this…';
          if (!deps.canvasBody.querySelector('.tc-canvas-building')) {
            deps.canvasBody.innerHTML = `<div class="tc-canvas-building" style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;text-align:center;padding:28px;">
              <div style="width:46px;height:46px;border-radius:50%;background:var(--c-accent-soft);display:grid;place-items:center;"><i class="ph ph-pen-nib" style="font-size:22px;color:var(--c-accent);animation:tc-spin 1.4s linear infinite;"></i></div>
              <div style="font-size:14px;font-weight:650;color:var(--c-text);">Drawing it…</div>
              <div style="width:210px;height:4px;border-radius:3px;background:var(--c-surface-2);overflow:hidden;"><div style="height:100%;width:38%;border-radius:3px;background:var(--c-accent);animation:tc-indeterminate 1.4s ease-in-out infinite;"></div></div>
            </div>`;
          }
          return;
        }
        // DONE — render the finished visual. It performs its build entrance exactly ONCE
        // (the FIRST time this content is shown). If the canvas is re-opened/re-rendered for
        // content we've already built, mount it STATIC (data-reveal=play, transitions off) so
        // it does NOT re-animate — it's a finished thing, not a replayable asset.
        deps.canvasStatus.textContent = deps.canvasState.name || 'Canvas';
        const _finalDoc = deps._injectReveal(deps.canvasState.html || '<!DOCTYPE html><body style="margin:0;background:#fff"></body>');
        const _key = _finalDoc.length + ':' + (_finalDoc.charCodeAt(0) || 0) + ':' + (_finalDoc.charCodeAt(_finalDoc.length >> 1) || 0);
        let f = deps.canvasBody.querySelector('iframe.tc-live-frame');
        if (!f || f.getAttribute('data-doc-key') !== _key) {
          const _seen = deps._canvasShown.has(_key);
          deps.canvasBody.innerHTML = '<iframe class="tc-live-frame" sandbox="allow-scripts" style="flex:0 0 auto;height:min(68vh,720px);width:100%;border:0;border-radius:10px;background:#fff;"></iframe>';
          f = deps.canvasBody.querySelector('iframe.tc-live-frame');
          f.setAttribute('data-doc-key', _key);
          f.setAttribute('srcdoc', _seen ? deps._staticDoc(_finalDoc) : _finalDoc);
          deps._canvasShown.add(_key);
        }
        return;
      }
      if (deps.canvasState.mode === 'document') {
        deps.canvasStatus.textContent = deps.canvasState.live ? 'Writing…' : (deps.canvasState.name || 'Document');
        const cursor = deps.canvasState.live ? '<span class="tc-doc-cursor"></span>' : '';
        deps.canvasBody.innerHTML = '<div class="tc-doc-page">' + deps.mdToHtml(deps.canvasState.md) + cursor + '</div>';
        if (deps.canvasState.live) deps.canvasBody.scrollTop = deps.canvasBody.scrollHeight;
        return;
      }
      if (deps.canvasState.mode === 'render' && deps.canvasState.url) {
        deps.canvasStatus.textContent = deps.canvasState.name || 'Rendered';
        // allow="fullscreen; clipboard-write" is the SAME defect one layer above
        // the sandbox tokens. Fullscreen and the async clipboard are Permissions
        // Policy features whose default allowlist is "self", so the EMBEDDING page
        // must delegate them or a cross-origin frame is refused. /deliverable/ 302s
        // an HTML artifact onto its own ephemeral 127.0.0.1:PORT, which makes this
        // frame cross-origin, and nothing delegated anything -- so the same bytes
        // that work in a browser tab were dead here.
        //
        // Measured across the owner's 414 generated files: clipboard.writeText 3,
        // requestFullscreen 2. colortoy.html's Copy button awaits
        // navigator.clipboard.writeText with no catch, so the NotAllowedError
        // aborted the handler before its "Copied!" label and the button simply did
        // nothing; snake.html advertises "F fullscreen" on its own start screen and
        // the key was refused. The model's code was right both times.
        deps.canvasBody.innerHTML = `<iframe src="${deps.esc(deps.canvasState.url)}#toolbar=0&navpanes=0&view=FitH" title="${deps.esc(deps.canvasState.name || '')}" allow="fullscreen; clipboard-write" style="flex:0 0 auto;height:min(72vh,760px);width:100%;border:0;border-radius:10px;background:#fff;"></iframe>`;
        return;
      }
      if (deps.canvasState.mode === 'building') {
        const who = deps.canvasState.worker || 'A worker';
        deps.canvasStatus.textContent = who + ' is building this…';
        const line = deps.esc(deps.canvasState.progress || 'Getting started…');
        deps.canvasBody.innerHTML = `<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;text-align:center;padding:28px;">
          <div style="width:46px;height:46px;border-radius:50%;background:var(--c-accent-soft);display:grid;place-items:center;"><i class="ph ph-circle-notch" style="font-size:22px;color:var(--c-accent);animation:tc-spin 1s linear infinite;"></i></div>
          <div style="font-size:14px;font-weight:650;color:var(--c-text);">${deps.esc(who)} is building this</div>
          <div style="font-size:12.5px;color:var(--c-muted);max-width:280px;line-height:1.5;min-height:18px;">${line}</div>
          <div style="width:210px;height:4px;border-radius:3px;background:var(--c-surface-2);overflow:hidden;"><div style="height:100%;width:38%;border-radius:3px;background:var(--c-accent);animation:tc-indeterminate 1.4s ease-in-out infinite;"></div></div>
          <div style="font-size:11px;color:var(--c-dim);max-width:260px;line-height:1.45;">The finished result renders here the moment it's ready.</div>
        </div>`;
        return;
      }
      if (deps.canvasState.mode === 'ended') {
        deps.canvasStatus.textContent = deps.canvasState.worker ? (deps.canvasState.worker + ' stopped') : 'Stopped';
        deps.canvasBody.innerHTML = `<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--c-muted);text-align:center;padding:28px;"><i class="ph ph-warning-circle" style="font-size:28px;color:var(--c-dim);"></i><div style="font-size:13px;line-height:1.5;max-width:260px;color:var(--c-text);">${deps.esc(deps.canvasState.progress)}</div><div style="font-size:11.5px;color:var(--c-dim);max-width:260px;line-height:1.45;">Nothing was rendered. You can try again from the chat.</div></div>`;
        return;
      }
      deps.canvasStatus.textContent = 'Ready';
      deps.canvasBody.innerHTML = `<div style="flex:1;min-height:280px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--c-muted);text-align:center;padding:24px;"><i class="ph ph-cards-three" style="font-size:30px;color:var(--c-border-2);"></i><div style="font-size:13px;line-height:1.5;max-width:240px;">When a worker builds something renderable, it shows up here — live as it works, then rendered.</div></div>`;
    }
    return { openCanvas, closeCanvas, resetCanvasForConversation, canvasBuilding, _isTextArtifact, canvasRender, openConversationCanvas, canvasStop, renderCanvas };
  }
  window.ThomasChatCanvasView = { create };
})();
