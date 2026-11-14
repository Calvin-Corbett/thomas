/* Build's composer controls: the primary button, and the stack above the card.

   Pure rendering. This module owns no run state and calls no endpoint; the
   caller hands it what the run is doing and gets clicks back by id.

   1. The primary button (#tc-send). In Build it is Send, Pause, Resume or
      Stop. primaryState() picks one from the run and the composer, the same
      rule everywhere: typed text always means Send (a send mid-run queues), an
      empty composer means Pause while a run is going, Resume while it is
      paused, and Stop when this run cannot pause (the Claude Code lead holds
      no hook to wait on). applyPrimary() puts that state on the button: icon,
      accessible name, `data-primary` for the stylesheet, and the fill -- accent
      only for a Send that has something to send. chat_message_view.js asks on
      every syncDynamic; chat_shell_bindings.js hands an empty-composer click
      to ThomasCodeMode.primaryAction(), which acts on the same rule.

   2. The stack directly above the composer card (#tc-code-composer-extras):
      each message you sent while Thomas was working, with Steer (hand it to
      the run now) and ✕, then one status line: a short phrase of at most
      about four words ("Thomas is editing") and, on the right, "Step 4 of 5 ·
      1m 12s". There is no Stop here; the primary button is the control.
      extrasHtml() is that markup. render()
      writes it into the mount and afterwards patches only what changed: Build
      re-renders on every live event and on a 1 s clock, and rebuilding the
      buttons each time would swallow a click whose mousedown landed on the
      old node, and restart the status dot's pulse every second.

   Build's queue itself is state.queuedSends in unified_code_mode.js. */
(function () {
  'use strict';

  const PRIMARY = {
    send: { icon: 'ph-arrow-up', label: 'Send' },
    pause: { icon: 'ph-pause', label: 'Pause', title: 'Pause this run. Agents hold after their current step.' },
    resume: { icon: 'ph-play', label: 'Resume', title: 'Resume this run' },
    stop: { icon: 'ph-stop', label: 'Stop', title: 'Stop this run. It cannot be paused.' },
  };
  // The fill rides on the button's own --send-* properties, which its inline
  // style already reads. Set on the button rather than the shell so leaving
  // Build (clearPrimary) hands Chat back exactly the look it had.
  const FILLS = {
    ready: { '--send-bg': 'var(--c-accent)', '--send-ink': 'var(--c-accent-ink)', '--send-op': '1', '--send-cursor': 'pointer' },
    control: { '--send-bg': 'var(--c-surface-2)', '--send-ink': 'var(--c-text)', '--send-op': '1', '--send-cursor': 'pointer' },
    empty: { '--send-bg': 'var(--c-surface-2)', '--send-ink': 'var(--c-muted)', '--send-op': '0.85', '--send-cursor': 'default' },
  };
  const FILL_PROPS = Object.keys(FILLS.ready);
  const TONES = new Set(['working', 'paused', 'idle']);
  const QUEUE_ACTIONS = ['data-code-queue-steer', 'data-code-queue-remove'];

  // The page's one escaper, handed in (unified_code_mode.js owns it); a second
  // copy here is one that could drift. Without it nothing is drawn.
  function escaper(ctx) {
    if (!ctx || typeof ctx.esc !== 'function') throw new Error('ThomasCodeComposer needs ctx.esc');
    return ctx.esc;
  }
  function clip(text, max) { return text.length > max ? `${text.slice(0, max - 1)}…` : text; }

  // ---------- Primary button ----------

  function primaryState(ctx) {
    const c = ctx || {};
    if (c.hasText || !c.running) return 'send';
    if (c.paused) return 'resume';
    return c.canPause ? 'pause' : 'stop';
  }

  // `ctx` is the object primaryState() was asked with. Without it the caller is
  // vouching that a Send has something to send.
  function applyPrimary(button, iconEl, state, ctx) {
    const key = PRIMARY[state] ? state : 'send';
    const spec = PRIMARY[key];
    const empty = key === 'send' && ctx != null && !ctx.hasText;
    if (iconEl) {
      const icon = `ph ${spec.icon}`;
      if (iconEl.className !== icon) iconEl.className = icon;
    }
    if (!button) return key;
    // The page's own tooltip, put back when the button leaves Build.
    if (!('chatTitle' in button.dataset)) button.dataset.chatTitle = button.getAttribute('title') || '';
    button.dataset.primary = key;
    button.setAttribute('aria-label', spec.label);
    let title = spec.title;
    if (key === 'send') title = empty ? 'Send' : ctx && ctx.running ? 'Send. It waits above the composer until Thomas is free, or until you steer it in.' : 'Send';
    button.setAttribute('title', title);
    // An empty Send does nothing, so it says so; Pause, Resume and Stop act
    // on an empty composer and are never disabled.
    if (empty) button.setAttribute('aria-disabled', 'true');
    else button.removeAttribute('aria-disabled');
    const fill = key !== 'send' ? FILLS.control : empty ? FILLS.empty : FILLS.ready;
    for (const prop of FILL_PROPS) button.style.setProperty(prop, fill[prop]);
    return key;
  }

  // Leaving Build: drop everything applyPrimary put on the button, so Chat's
  // own send/stop styling (set on the shell) shows through again.
  function clearPrimary(button) {
    if (!button || !button.dataset || !('primary' in button.dataset)) return;
    delete button.dataset.primary;
    button.removeAttribute('aria-label');
    button.removeAttribute('aria-disabled');
    if ('chatTitle' in button.dataset) {
      if (button.dataset.chatTitle) button.setAttribute('title', button.dataset.chatTitle);
      else button.removeAttribute('title');
      delete button.dataset.chatTitle;
    }
    for (const prop of FILL_PROPS) button.style.removeProperty(prop);
  }

  // ---------- Queue + status line ----------

  // The same clock as the transcript's elapsedLabel (unified_code_events.js),
  // with hours added: a long run read "95m 12s".
  function formatElapsed(ms) {
    const value = Number(ms);
    if (!Number.isFinite(value)) return '';
    const seconds = Math.max(0, Math.floor(value / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
  }

  function statusOf(raw) {
    if (!raw) return null;
    const words = String(raw.words == null ? '' : raw.words).trim();
    const elapsed = typeof raw.elapsed === 'number' ? formatElapsed(raw.elapsed) : String(raw.elapsed == null ? '' : raw.elapsed).trim();
    const meta = [String(raw.stepText == null ? '' : raw.stepText).trim(), elapsed].filter(Boolean).join(' · ');
    if (!words && !meta) return null;
    return { words, meta, tone: TONES.has(raw.tone) ? raw.tone : 'idle' };
  }

  function queueItemsHtml(esc, queued, steerDisabled) {
    return (Array.isArray(queued) ? queued : []).filter(Boolean).map(item => {
      const id = item.id == null ? '' : String(item.id);
      const text = String(item.message == null ? '' : item.message);
      const line = text.replace(/\s+/g, ' ').trim();
      const busy = Boolean(item.busy);
      // No id, no way to name it back to the caller: shown, but inert.
      const off = !id || busy;
      return `<div class="tc-code-queue-item${busy ? ' is-busy' : ''}" role="listitem" data-code-queue-item="${esc(id)}">`
        + '<span class="tc-code-queue-label">Queued</span>'
        + `<span class="tc-code-queue-text" title="${esc(clip(text.trim(), 600))}">${esc(line)}</span>`
        + `<button type="button" class="tc-code-queue-steer" data-code-queue-steer="${esc(id)}" title="Hand this to Thomas now instead of after this run"${off || steerDisabled ? ' disabled' : ''}>${busy ? 'Steering…' : 'Steer'}</button>`
        + `<button type="button" class="tc-code-queue-remove" data-code-queue-remove="${esc(id)}" title="Remove from the queue" aria-label="${esc(`Remove queued message: ${clip(line, 80)}`)}"${off ? ' disabled' : ''}>✕</button>`
        + '</div>';
    }).join('');
  }

  function statusHtml(esc, status) {
    const s = status || { words: '', meta: '', tone: 'idle' };
    return `<div class="tc-code-status" data-code-status data-tone="${s.tone}"${status ? '' : ' hidden'}>`
      + '<span class="tc-code-status-dot" aria-hidden="true"></span>'
      + `<span class="tc-code-status-words" data-code-status-words title="${esc(s.words)}">${esc(s.words)}</span>`
      + `<span class="tc-code-status-meta" data-code-status-meta${s.meta ? '' : ' hidden'}>${esc(s.meta)}</span>`
      + '</div>';
  }

  function frameHtml(esc, items, status) {
    return `<div class="tc-code-queue" data-code-queue role="list" aria-label="Queued messages"${items ? '' : ' hidden'}>${items}</div>`
      + statusHtml(esc, status);
  }

  // ctx = {esc, queued:[{id, message, busy?}], status:{words, tone, stepText,
  // elapsed}|null, steerDisabled?}. `elapsed` is a label or milliseconds.
  function extrasHtml(ctx) {
    const c = ctx || {};
    const escape = escaper(c);
    const items = queueItemsHtml(escape, c.queued, c.steerDisabled);
    const status = statusOf(c.status);
    return items || status ? frameHtml(escape, items, status) : '';
  }

  const renderedQueue = new WeakMap();

  // Which queue button has focus, so a rebuild can put it somewhere sensible
  // rather than dropping it on the page body.
  function queueFocus(queueEl) {
    const doc = queueEl.ownerDocument;
    const active = doc && doc.activeElement;
    if (!active || active === queueEl || !queueEl.contains(active)) return null;
    for (const attr of QUEUE_ACTIONS) {
      if (!active.hasAttribute(attr)) continue;
      const all = Array.from(queueEl.querySelectorAll(`[${attr}]`));
      return { attr, id: active.getAttribute(attr), index: all.indexOf(active) };
    }
    return null;
  }

  function restoreQueueFocus(root, queueEl, focus) {
    const all = Array.from(queueEl.querySelectorAll(`[${focus.attr}]`));
    const same = all.find(node => node.getAttribute(focus.attr) === focus.id);
    let next = same && !same.disabled ? same : null;
    // ✕ walks on to the row that slid into its place, the way a list of
    // removable things usually behaves. Steer never hands focus to another
    // Steer: a second Enter would interrupt the run with a message nobody chose.
    if (!next && !same && focus.attr === 'data-code-queue-remove') {
      const live = all.filter(node => !node.disabled);
      next = live[Math.min(focus.index, live.length - 1)] || null;
    }
    if (next) { next.focus(); return; }
    // Otherwise back to where you type.
    const input = root.ownerDocument && root.ownerDocument.getElementById('tc-input');
    if (input) input.focus();
  }

  function render(root, ctx) {
    if (!root) return false;
    const c = ctx || {};
    const escape = escaper(c);
    const items = queueItemsHtml(escape, c.queued, c.steerDisabled);
    const status = statusOf(c.status);
    let queueEl = root.querySelector('[data-code-queue]');
    let statusEl = root.querySelector('[data-code-status]');
    if (!queueEl || !statusEl) {
      root.innerHTML = frameHtml(escape, items, status);
      queueEl = root.querySelector('[data-code-queue]');
      statusEl = root.querySelector('[data-code-status]');
      renderedQueue.set(queueEl, items);
    }
    if (renderedQueue.get(queueEl) !== items) {
      const focus = queueFocus(queueEl);
      queueEl.innerHTML = items;
      renderedQueue.set(queueEl, items);
      if (focus) restoreQueueFocus(root, queueEl, focus);
    }
    queueEl.hidden = !items;
    statusEl.hidden = !status;
    if (status) {
      if (statusEl.getAttribute('data-tone') !== status.tone) statusEl.setAttribute('data-tone', status.tone);
      const words = statusEl.querySelector('[data-code-status-words]');
      const meta = statusEl.querySelector('[data-code-status-meta]');
      if (words && words.textContent !== status.words) { words.textContent = status.words; words.title = status.words; }
      if (meta) {
        if (meta.textContent !== status.meta) meta.textContent = status.meta;
        meta.hidden = !status.meta;
      }
    }
    const visible = Boolean(items || status);
    root.hidden = !visible;
    return visible;
  }

  // One delegated listener per mount, however often bind() is called; the
  // newest handlers win. Ids come back as the strings the markup carries.
  const handlersByRoot = new WeakMap();

  function bind(root, handlers) {
    if (!root) return;
    const known = handlersByRoot.has(root);
    handlersByRoot.set(root, handlers || {});
    if (known) return;
    root.addEventListener('click', event => {
      const target = event.target;
      if (!target || typeof target.closest !== 'function') return;
      const button = target.closest('[data-code-queue-steer], [data-code-queue-remove]');
      if (!button || !root.contains(button) || button.disabled) return;
      const current = handlersByRoot.get(root) || {};
      if (button.hasAttribute('data-code-queue-steer')) {
        if (typeof current.onSteer === 'function') current.onSteer(button.getAttribute('data-code-queue-steer'));
        return;
      }
      if (typeof current.onRemove === 'function') current.onRemove(button.getAttribute('data-code-queue-remove'));
    });
  }

  window.ThomasCodeComposer = { primaryState, applyPrimary, clearPrimary, extrasHtml, render, bind, formatElapsed };
})();
