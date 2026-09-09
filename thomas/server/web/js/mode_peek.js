(function () {
  'use strict';

  // The peek strip: the ONE place a mode may show conversation beside the
  // shell composer. It lives above the single composer in chat.html, so a
  // mode can never grow a second composer of its own — there is nowhere to
  // put one. Work fills it; Chat and Code leave it hidden.
  //
  // The bump is the only control. Collapsed it shows the last exchange and
  // opens the full conversation; expanded it shows only itself and closes.

  const DURATION = 340;
  const EASE = 'cubic-bezier(.22, 1, .36, 1)';

  const view = {
    visible: false,
    expanded: false,
    rows: [],
    busy: false,
    hint: '',
    label: 'Chat',
  };

  let host = null;
  let bump = null;
  let rowsEl = null;
  let toggleHandler = null;
  let running = null;

  const esc = value => String(value == null ? '' : value)
    .replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function reducedMotion() {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function mount() {
    if (host) return host;
    host = document.getElementById('tc-mode-peek');
    if (!host) return null;
    host.innerHTML = '<div class="tc-peek-rows" aria-live="polite" aria-relevant="additions text"></div>'
      + '<button type="button" class="tc-peek-bump" aria-expanded="false" aria-controls="tc-mode-surface">'
      + '<i class="ph ph-caret-up" aria-hidden="true"></i><span class="tc-peek-bump-label">Chat</span></button>';
    rowsEl = host.querySelector('.tc-peek-rows');
    bump = host.querySelector('.tc-peek-bump');
    bump.addEventListener('click', () => { if (toggleHandler) toggleHandler(!view.expanded); });
    return host;
  }

  // Two lines of the last exchange is the whole point: enough to keep the
  // thread in view beside a dashboard, never enough to become a reading
  // surface. Going deep is what the bump is for.
  function rowHtml(row) {
    const thomas = row.role === 'assistant' || row.role === 'thomas';
    if (row.role === 'system') {
      return `<article class="tc-peek-row is-system"><span class="tc-peek-who">Note</span><p>${esc(row.text || '')}</p></article>`;
    }
    return `<article class="tc-peek-row is-${thomas ? 'thomas' : 'user'}">`
      + `<span class="tc-peek-who">${thomas ? 'Thomas' : 'You'}</span>`
      + `<p>${esc(row.text || '')}</p></article>`;
  }

  function paint() {
    if (!mount()) return;
    host.hidden = !view.visible;
    host.dataset.expanded = view.expanded ? 'true' : 'false';
    bump.setAttribute('aria-expanded', view.expanded ? 'true' : 'false');
    bump.querySelector('i').className = `ph ph-caret-${view.expanded ? 'down' : 'up'}`;
    bump.querySelector('.tc-peek-bump-label').textContent = view.expanded ? 'Close' : view.label;
    bump.title = view.expanded
      ? 'Collapse the conversation and go back to the dashboard'
      : 'Open the full conversation';
    if (view.expanded) { rowsEl.innerHTML = ''; return; }
    const body = view.rows.map(rowHtml).join('');
    const status = view.busy ? '<div class="tc-peek-status" role="status">Thomas is working…</div>' : '';
    const hint = !body && !status && view.hint ? `<div class="tc-peek-hint">${esc(view.hint)}</div>` : '';
    rowsEl.innerHTML = `${body}${status}${hint}`;
  }

  function set(next) {
    Object.assign(view, next || {});
    paint();
  }

  function clear() {
    view.visible = false;
    view.expanded = false;
    view.rows = [];
    view.busy = false;
    paint();
  }

  // Grow the freshly rendered conversation out of the strip's own height.
  // Animating height (not scale) means the text is revealed rather than
  // stretched, which is what "slides up" actually looks like.
  function grow(element, fromHeight) {
    if (!element || reducedMotion() || typeof element.animate !== 'function') return null;
    const to = element.getBoundingClientRect().height;
    if (!to || Math.abs(to - fromHeight) < 8) return null;
    if (running) { try { running.cancel(); } catch (_) { /* superseded */ } }
    running = element.animate(
      [
        { height: `${Math.max(0, fromHeight)}px`, opacity: 0.35, transform: 'translateY(10px)' },
        { height: `${to}px`, opacity: 1, transform: 'translateY(0)' },
      ],
      { duration: DURATION, easing: EASE },
    );
    element.style.overflow = 'hidden';
    // The clip MUST come off. Relying on the finish event alone leaves the
    // transcript permanently cut off if that event is ever missed — which
    // happens whenever the page stops compositing (a background or
    // undisplayed tab). Timer, promise and events all race to undo it, and
    // undoing it twice is harmless.
    const restore = () => {
      element.style.overflow = '';
      if (running && running.effect && running.effect.target === element) running = null;
    };
    running.addEventListener('finish', restore, { once: true });
    running.addEventListener('cancel', restore, { once: true });
    if (running.finished && typeof running.finished.then === 'function') running.finished.then(restore, restore);
    setTimeout(restore, DURATION + 120);
    return running;
  }

  // Runs `apply` (which re-renders the mode surface) between measuring the
  // collapsed strip and the expanded conversation, then animates the gap.
  function transition(apply, findTarget) {
    const before = rowsEl ? rowsEl.getBoundingClientRect().height : 0;
    apply();
    const target = typeof findTarget === 'function' ? findTarget() : null;
    if (!target) return null;
    return grow(target, before);
  }

  function onToggle(handler) { toggleHandler = typeof handler === 'function' ? handler : null; }

  window.ThomasModePeek = {
    set,
    clear,
    onToggle,
    transition,
    grow,
    isExpanded: () => view.expanded,
    element: () => mount(),
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
  else mount();
})();
