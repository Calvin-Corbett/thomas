/* Chat message view. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Messages ----------
    function bubbleInner(m) {
      const isUser = m.role === 'user';
      const showDots = !isUser && m.streaming && (!m.text || m.text.length === 0);
      const showCursor = !isUser && m.streaming && m.text && m.text.length > 0;
      let html = isUser ? deps.esc(m.text) : deps.mdToHtml(m.streaming ? m.text : (_settledStatusText(m) ?? m.text));
      if (showCursor) html += `<span style="display: inline-block; width: 8px; height: 17px; transform: translateY(2px); margin-left: 2px; background: var(--c-accent); animation: tc-blink 1s step-end infinite;"></span>`;
      if (showDots) html = `<span style="display: inline-flex; gap: 5px; padding: 4px 0;"><span style="width: 7px; height: 7px; border-radius: 999px; background: var(--c-muted); animation: tc-dot 1.3s ease-in-out infinite;"></span><span style="width: 7px; height: 7px; border-radius: 999px; background: var(--c-muted); animation: tc-dot 1.3s ease-in-out .2s infinite;"></span><span style="width: 7px; height: 7px; border-radius: 999px; background: var(--c-muted); animation: tc-dot 1.3s ease-in-out .4s infinite;"></span></span>`;
      if (m.mediaArtifact) html += window.ThomasMediaGeneration.renderArtifact(m.mediaArtifact, deps.esc);
      return html;
    }

    // A delegation opens with a present-tense bubble — "On it — this is running now, and I'll share the result when it's ready." (reasoning.py stores it verbatim; reasoning_context.py a sibling wording). The Done pill and deliverable card render ABOVE it, so a finished task's transcript ENDED on a false statement, on every store re-render, forever (measured live, 2026-08-05). The stored text is history; the rendering is ours: once every handoff on this message is terminal, the ONE stale sentence renders as what actually happened, naming the deliverable when known — surrounding prose survives untouched.
    // Null = nothing to settle: no promise in the text, no delegation activity attached, or a handoff genuinely still running. Honest text and user text are never touched — this never fires while the claim is still true.
    function _settledStatusText(m) {
      const text = String(m.text || ''), sentence = /[^.!?\n]*\b(?:running now|getting this done now)\b[^.!?\n]*[.!?]?/i;
      if (!sentence.test(text) || !/\bshare the result\b/i.test(text)) return null;
      const a = m.activity, handoffs = ((a && a.steps) || []).filter(s => s && s.kind === 'handoff');
      if (!handoffs.length || handoffs.some(s => s.status === 'running')) return null;
      const names = ((Array.isArray(m.artifacts) && m.artifacts.length) ? m.artifacts : (Array.isArray(a.artifacts) && a.artifacts.length) ? a.artifacts : (a.artifact ? [a.artifact] : [])).map(x => String((x && (x.name || x.path)) || '')).filter(Boolean);
      const done = handoffs.some(s => s.status === 'failed') ? 'This ran into a problem — the details are in the card above.' : (a.cancelled || handoffs.some(s => s.status === 'cancelled')) ? 'Stopped — this task was cancelled before it finished.' : names.length === 1 ? ('Done — ' + names[0] + ' is ready above.') : names.length > 1 ? ('Done — ' + names.length + ' results are ready above.') : 'Done — the result is ready above.';
      return text.replace(sentence, done);
    }

    async function copyMessageText(text, button) {
      const value = String(text || '');
      let copied = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
          copied = true;
        }
      } catch (e) {}
      if (!copied) {
        const area = document.createElement('textarea');
        area.value = value;
        area.setAttribute('readonly', '');
        area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
        document.body.appendChild(area);
        area.select();
        try { copied = document.execCommand('copy'); } catch (e) { copied = false; }
        area.remove();
      }
      if (button) {
        button.title = copied ? 'Copied' : 'Copy failed';
        button.setAttribute('aria-label', button.title);
        const icon = button.querySelector('i');
        if (icon && copied) icon.className = 'ph ph-check';
        setTimeout(() => {
          button.title = 'Copy message';
          button.setAttribute('aria-label', 'Copy message');
          if (icon) icon.className = 'ph ph-copy';
        }, 1400);
      }
      return copied;
    }

    function buildMessageNode(m, idx) {
      const isUser = m.role === 'user';
      const meta = deps.THEME_META[deps.state.theme];
      const rule = (meta.msgRule !== '0') ? meta.msgRule : 'none';
      const wrap = document.createElement('div');
      const head = isUser ? 'none' : 'flex';
      const mMax = isUser ? 'min(78%, 540px)' : '100%';
      const mBg = isUser ? 'var(--c-user-bg)' : 'transparent';
      const mColor = isUser ? 'var(--c-user-text)' : 'var(--c-text)';
      const mBorder = isUser ? '1px solid var(--c-border)' : '0';
      const mRadius = isUser ? '16px 16px 4px 16px' : '0';
      const mPad = isUser ? '11px 15px' : (meta.msgRule !== '0' ? '2px 0 2px 16px' : '0');
      wrap.style.cssText = `display: flex; flex-direction: column; gap: 8px; align-items: ${isUser ? 'flex-end' : 'flex-start'}; animation: tc-rise .3s ease both;`;

      let html = '';
      if (!isUser) {
        html += `<div style="display: flex; align-items: center; gap: 9px;">
          ${deps.avatar(26, 8, 4, 5)}
          <span style="font-size: 13px; font-weight: 700;">Thomas</span>
          ${m.model ? `<span class="tc-message-model" style="font-size: 11.5px; color: var(--c-muted); font-family: var(--font-label);">${deps.esc(m.model)}</span>` : ''}
        </div>`;
        html += `<div class="tc-activity" style="display: flex; flex-direction: column; gap: 8px; width: 100%; max-width: 768px;"></div>`;
      }
      // What you attached to this message, above its words.
      if (isUser && Array.isArray(m.attachments) && m.attachments.length && window.ThomasAttachmentStrip) html += window.ThomasAttachmentStrip.html(m.attachments);
      html += `<div class="tc-bubble${isUser ? '' : ' tc-markdown'}" style="max-width: ${mMax}; background: ${mBg}; color: ${mColor}; border: ${mBorder}; border-left: ${rule}; border-radius: ${mRadius}; padding: ${mPad}; font-size: 16px; line-height: 1.72; white-space: pre-wrap; word-wrap: break-word; letter-spacing: 0.003em;">${bubbleInner(m)}</div>`;

      if (m.artifact) {
        const a = m.artifact;
        html += `<button class="tc-art hv-surface" style="display: flex; align-items: center; gap: 11px; width: 100%; max-width: 360px; margin-top: 2px; padding: 11px 13px; border-radius: 12px; border: 1px solid var(--c-accent-line); background: var(--c-accent-soft); color: var(--c-text); font-family: inherit; cursor: pointer; text-align: left; transition: all .15s;">
          <span style="width: 34px; height: 34px; border-radius: 9px; background: var(--c-accent); color: var(--c-accent-ink); display: grid; place-items: center; flex: 0 0 auto;"><i class="ph ${a.icon}" style="font-size: 18px;"></i></span>
          <span style="flex: 1; min-width: 0;">
            <span style="display: block; font-size: 13.5px; font-weight: 700;">${deps.esc(a.title)}</span>
            <span style="display: block; font-size: 11.5px; color: var(--c-muted);">${deps.esc(a.sub)}</span>
          </span>
          <i class="ph ph-arrow-right" style="font-size: 15px; color: var(--c-muted);"></i>
        </button>`;
      }
      // A completion ("here it is") bubble carries its own result artifact(s),
      // presented right in this reply — one place, not a chip on an earlier card.
      if (m.artifacts && m.artifacts.length) {
        html += `<div class="tc-msg-artifacts" style="width:100%;">` + deps.artifactHTML({ artifacts: m.artifacts, artifact: m.artifacts.length === 1 ? m.artifacts[0] : null, artifactOpen: !!m.artifactOpen }) + `</div>`;
      }
      html += `<div style="display:flex;align-items:center;gap:4px;margin-top:2px;">
        <button type="button" data-msg-copy class="hv-soft" title="Copy message" aria-label="Copy message" style="width:28px;height:28px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--c-muted);display:grid;place-items:center;cursor:pointer;transition:all .14s;"><i class="ph ph-copy" style="font-size:15px;"></i></button>
        ${m.role === 'user' ? `<button type="button" data-msg-edit class="hv-soft" title="Edit &amp; resend from here" aria-label="Edit and resend from here" style="width:28px;height:28px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--c-muted);display:grid;place-items:center;cursor:pointer;transition:all .14s;"><i class="ph ph-pencil-simple" style="font-size:15px;"></i></button>` : ''}
      </div>`;
      wrap.innerHTML = html;
      const bubbleEl = wrap.querySelector('.tc-bubble');
      const activityEl = wrap.querySelector('.tc-activity');
      deps.msgRefs[idx] = { wrapEl: wrap, bubbleEl, activityEl, modelEl: wrap.querySelector('.tc-message-model') };
      if (m.activity) deps.renderActivity(idx);
      const artBtn = wrap.querySelector('.tc-art');
      if (artBtn && m.artifact) artBtn.addEventListener('click', () => { void deps.canvasRender(m.artifact.url, m.artifact.name, m.artifact.kind || ''); });
      // Wire the completion-bubble artifact chips (open in canvas / toggle preview).
      const artHolder = wrap.querySelector('.tc-msg-artifacts');
      if (artHolder) {
        artHolder.querySelectorAll('[data-artifact-open]').forEach(button => button.addEventListener('click', (e) => { e.stopPropagation(); void deps.canvasRender(button.dataset.artifactUrl || '', button.dataset.artifactName || 'result', button.dataset.artifactKind || ''); }));
        const at = artHolder.querySelector('[data-artifact-toggle]');
        if (at) at.addEventListener('click', (e) => { e.stopPropagation(); m.artifactOpen = !m.artifactOpen; deps.threadEl.replaceChild(buildMessageNode(m, idx), wrap); });
      }
      const copyBtn = wrap.querySelector('[data-msg-copy]');
      if (copyBtn) copyBtn.addEventListener('click', () => { void copyMessageText(m.text, copyBtn); });
      const editBtn = wrap.querySelector('[data-msg-edit]');
      if (editBtn) editBtn.addEventListener('click', () => { void editMessageFrom(idx); });
      return wrap;
    }

    // Edit-and-resend: fork the conversation at a past user message. The
    // server truncates the stored history to BEFORE that message (and evicts
    // the live LLM so removed turns can't leak back), the client mirrors the
    // cut, and the old text lands in the composer ready to edit and send.
    // Friction telemetry: retries, cancels, and edit-resends are "this didn't
    // land" signals — they feed the issue ledger so the self-review sees them.
    // `.catch`, not the try/catch alone. A fetch rejects ASYNCHRONOUSLY, so the
    // try below never sees an unreachable /api/issues and the rejection escapes
    // as an "Uncaught (in promise) TypeError: Failed to fetch" page error.
    // chat.html:455 routes `unhandledrejection` straight back into
    // reportPageError -> reportFriction -> this same fetch, so reporting one
    // failure manufactured the next one, and the reporter became a source of the
    // errors it exists to report -- bounded only by the five-error cap above.
    // The try/catch stays: a stubbed or absent fetch can still throw on the spot.
    function reportFriction(kind, message) {
      try { fetch('/api/issues', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ surface: 'chat-ui', kind: 'friction', message: kind + ': ' + String(message || '').slice(0, 200), context: { session: deps.state.sessionId || '' } }) }).catch(() => {}); } catch (e) {}
    }

    // Uncaught page errors feed the same ledger: a broken send path took the
    // whole surface down for days while the self-review saw nothing, because
    // only deliberate friction was reported. Capped so a render-loop error
    // cannot flood the ledger.
    let _jsErrorsReported = 0;

    function reportPageError(message) {
      if (_jsErrorsReported >= 5) return;
      _jsErrorsReported += 1;
      reportFriction('js_error', message);
    }

    async function editMessageFrom(idx) {
      if (deps.state.streaming) return;
      const isCurrent = deps.captureConversation();
      const m = deps.state.messages[idx];
      if (!m || m.role !== 'user') return;
      reportFriction('edit_resend', m.text);
      const sid = deps.state.sessionId;
      if (sid) {
        try {
          const response = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/truncate', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keep_messages: idx }),
          });
          if (!response.ok) throw new Error('Could not update the saved conversation.');
          if (!isCurrent()) return;
        } catch (e) {
          if (isCurrent()) {
            reportFriction('edit_resend_failed', String(e));
            window.alert('Could not edit this conversation. Your messages are unchanged; please try again.');
          }
          return;
        }
      }
      if (!isCurrent()) return;
      deps.state.messages = deps.state.messages.slice(0, idx);
      deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
      deps.state.messages.forEach((msg, i) => deps.threadEl.appendChild(buildMessageNode(msg, i)));
      if (deps.turnFlow && deps.turnFlow.restoreQueued) deps.turnFlow.restoreQueued();
      deps.state.input = m.text; deps.inputEl.value = m.text;
      autosize(); syncDynamic(); deps.inputEl.focus(); scrollEnd();
    }

    function appendMessage(m) {
      const idx = deps.state.messages.length - 1;
      deps.threadEl.appendChild(buildMessageNode(m, idx));
    }

    function updateStreamingBubble(idx) {
      const ref = deps.msgRefs[idx]; if (!ref) return;
      ref.bubbleEl.innerHTML = bubbleInner(deps.state.messages[idx]);
    }

    // ---------- The open conversation's name, in the top bar ----------
    // Chat mode only: Build and Work name their own surfaces, and borrowing
    // this slot for them would put a chat's name over a build's transcript.
    // Nothing is shown when there is no named conversation open — an empty
    // string beats a placeholder, which would be a claim about a chat that
    // does not exist yet.
    const chatTitleEl = document.getElementById('tc-chat-title');

    function syncChatTitle() {
      if (!chatTitleEl) return;
      const open = deps.state.surfaceMode === 'chat' && deps.state.activeChat
        ? deps.chatList.find(c => c.id === deps.state.activeChat)
        : null;
      // The sidebar's own name wins. A chat's readable name (a rename the owner
      // typed, or the short one the title service wrote back) lives in the
      // history overlay, NOT in chatList — reading chatList alone would put the
      // raw first prompt in the top bar while the row beside it said something
      // else, and two names for one chat is worse than none.
      const named = open && window.ThomasSidebarHistory && window.ThomasSidebarHistory.displayTitle
        ? String(window.ThomasSidebarHistory.displayTitle(open.id) || '').trim()
        : '';
      const name = named || (open ? String(open.title || '').trim() : '');
      chatTitleEl.textContent = name;
      // The full name on hover: the element ellipsises, so the tooltip is the
      // only place a truncated name stays readable.
      if (name) chatTitleEl.title = name; else chatTitleEl.removeAttribute('title');
      chatTitleEl.hidden = !name;
    }

    function syncView() {
      if (window.ThomasCostReadout && window.ThomasCostReadout.setContext) window.ThomasCostReadout.setContext(deps.state);
      const hasMsgs = deps.state.messages.length > 0;
      deps.welcomeEl.style.display = hasMsgs ? 'none' : 'flex';
      deps.threadEl.style.display = hasMsgs ? 'flex' : 'none';
      syncChatTitle();
    }


    // ---------- Composer dynamic state (send button) ----------
    function syncDynamic() {
      if (window.ThomasCostReadout && window.ThomasCostReadout.setContext) window.ThomasCostReadout.setContext(deps.state);
      window.ThomasChatMediaBridge.syncContext();
      const unified = window.ThomasUnifiedModes;
      const modeBusy = unified && unified.isBusy ? unified.isBusy() : deps.isChatBusy();
      const sendEl = typeof deps.sendIconEl.closest === 'function' ? deps.sendIconEl.closest('#tc-send') : null;
      const composer = window.ThomasCodeComposer;
      if (composer && unified && typeof unified.mode === 'function' && unified.mode() === 'code') {
        // Build: Send, Pause, Resume or Stop (unified_code_composer.js).
        // runControls() is the run's own word on whether it can pause; until
        // it answers, a busy run keeps the Stop this button always was.
        const code = window.ThomasCodeMode;
        const controls = code && typeof code.runControls === 'function' ? code.runControls() : null;
        const primary = {
          running: controls ? Boolean(controls.running) : modeBusy,
          paused: Boolean(controls && controls.paused),
          canPause: Boolean(controls && controls.canPause),
          hasText: Boolean(deps.state.input.trim()),
        };
        composer.applyPrimary(sendEl, deps.sendIconEl, composer.primaryState(primary), primary);
        deps.syncAttachmentState(modeBusy);
        return;
      }
      if (composer) composer.clearPrimary(sendEl);
      const active = !!(deps.state.input.trim() || modeBusy);
      deps.shell.style.setProperty('--send-bg', active ? 'var(--c-accent)' : 'var(--c-surface-2)');
      deps.shell.style.setProperty('--send-ink', active ? 'var(--c-accent-ink)' : 'var(--c-muted)');
      deps.shell.style.setProperty('--send-op', active ? '1' : '0.85');
      deps.shell.style.setProperty('--send-cursor', active ? 'pointer' : 'default');
      // Stop icon only when busy with an EMPTY composer; typed text keeps the
      // send arrow because clicking it queues the new task (Codex-style).
      deps.sendIconEl.className = 'ph ' + (modeBusy && !deps.state.input.trim() ? 'ph-stop' : 'ph-arrow-up');
      deps.syncAttachmentState(modeBusy);
    }

    function autosize() { deps.inputEl.style.height = 'auto'; deps.inputEl.style.height = Math.min(deps.inputEl.scrollHeight, 180) + 'px'; }

    function scrollEnd() { requestAnimationFrame(() => { deps.scrollEl.scrollTop = deps.scrollEl.scrollHeight; }); }
    return { bubbleInner, _settledStatusText, copyMessageText, buildMessageNode, reportFriction, reportPageError, editMessageFrom, appendMessage, updateStreamingBubble, syncChatTitle, syncView, syncDynamic, autosize, scrollEnd };
  }
  window.ThomasChatMessageView = { create };
})();
