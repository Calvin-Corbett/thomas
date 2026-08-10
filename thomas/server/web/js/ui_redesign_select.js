(function () {
  'use strict';

  // Redesign with AI — a permanent control, on every page.
  //
  //   press  -> point at anything on screen, click to select (as many as you like)
  //   lock   -> the selection freezes and stops eating your clicks
  //   say    -> what should change; only the locked elements are touched
  //
  // The result is reported from what actually changed, never from what the
  // model proposed. If nothing changed, this says so.

  const T = () => window.ThomasRedesignTarget;
  const L = () => window.ThomasUiLayout || null;

  // Drawn, not a font glyph: a rewind arrow curling anticlockwise back to its
  // own tail. The icon map has no such name, and an unmapped name renders as a
  // bare dot rather than failing.
  const REWIND_ICON = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.9"'
    + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M2.6 4.2v3.6h3.6"/><path d="M3.4 7.4a5.2 5.2 0 1 1 .7 4"/></svg>';

  const state = {
    phase: 'off', // off | selecting | locked | applying | result
    picks: [], // { descriptor, element }
    hover: null,
    frame: 0,
    result: null,
    error: '',
    notice: '',
    draft: '',
  };

  let ui = null;
  let contextProvider = null;

  const esc = value => String(value == null ? '' : value)
    .replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function build() {
    if (ui) return ui;
    const root = document.createElement('div');
    root.className = 'tr-root';
    root.setAttribute('data-redesign-ui', '');
    root.hidden = true;
    root.innerHTML = '<div class="tr-banner" role="status" hidden>'
      + '<i class="ph ph-hammer" aria-hidden="true"></i><span>Redesign mode</span>'
      + '<small>click what you want changed · Esc to leave</small></div>'
      + '<div class="tr-hover" hidden><span></span></div>'
      + '<div class="tr-marks"></div>'
      + '<section class="tr-bar" role="dialog" aria-label="Redesign with AI" aria-live="polite"></section>';
    document.body.appendChild(root);
    ui = {
      root,
      banner: root.querySelector('.tr-banner'),
      hover: root.querySelector('.tr-hover'),
      hoverLabel: root.querySelector('.tr-hover span'),
      marks: root.querySelector('.tr-marks'),
      bar: root.querySelector('.tr-bar'),
    };
    ui.bar.addEventListener('click', event => {
      const button = event.target.closest('[data-tr]');
      if (button) { event.preventDefault(); act(button.dataset.tr, button.dataset.trIndex); }
    });
    ui.bar.addEventListener('keydown', event => {
      if (event.target.matches('.tr-input') && event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        void apply();
      }
    });
    return ui;
  }

  function box(element) {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, top: rect.top, width: rect.width, height: rect.height, visible: rect.width > 0 && rect.height > 0 };
  }

  function place(node, element) {
    const rect = box(element);
    node.hidden = !rect.visible;
    node.style.left = `${rect.left}px`;
    node.style.top = `${rect.top}px`;
    node.style.width = `${rect.width}px`;
    node.style.height = `${rect.height}px`;
  }

  function paintMarks() {
    const marks = ui.marks;
    while (marks.children.length > state.picks.length) marks.lastElementChild.remove();
    state.picks.forEach((pick, index) => {
      let node = marks.children[index];
      if (!node) {
        node = document.createElement('div');
        node.className = 'tr-mark';
        node.innerHTML = '<b></b>';
        marks.appendChild(node);
      }
      // A locked selection survives the surface re-rendering under it.
      if (!pick.element.isConnected) {
        const found = T().resolve(pick.descriptor);
        if (found) pick.element = found;
      }
      node.querySelector('b').textContent = String(index + 1);
      place(node, pick.element);
    });
  }

  function tick() {
    state.frame = 0;
    if (state.phase === 'off') return;
    paintMarks();
    if (state.phase === 'selecting' && state.hover && state.hover.isConnected) place(ui.hover, state.hover);
    else ui.hover.hidden = true;
    schedule();
  }

  function schedule() {
    if (state.frame || state.phase === 'off') return;
    state.frame = requestAnimationFrame(tick);
  }

  function chipsHtml() {
    return state.picks.map((pick, index) => `<span class="tr-chip"><b>${index + 1}</b>${esc(pick.descriptor.label)}<button type="button" data-tr="drop" data-tr-index="${index}" aria-label="Remove ${esc(pick.descriptor.label)} from the selection">&times;</button></span>`).join('');
  }

  function resultHtml() {
    const result = state.result || {};
    const changed = Number(result.changed || 0);
    const blocked = Array.isArray(result.unsupported) ? result.unsupported : [];
    const headline = changed
      ? `<strong class="tr-good">Changed ${changed} ${changed === 1 ? 'thing' : 'things'}.</strong>`
      : '<strong class="tr-bad">Nothing changed.</strong>';
    const why = blocked.length
      ? `<ul class="tr-blocked">${blocked.map(row => `<li><b>${esc(row.label || 'That element')}</b> — ${esc(row.reason || 'no reason given')}</li>`).join('')}</ul>`
      : '';
    const note = !changed && !blocked.length
      ? '<p class="tr-note">Thomas returned no edits for that instruction. Try naming the change more concretely.</p>'
      : '';
    // Every change opens a Code thread on Thomas's own source, so a tweak you
    // like can become a real edit instead of a per-browser style override.
    const thread = result.thread
      ? `<p class="tr-thread"><i class="ph ph-code" aria-hidden="true"></i> Code thread ready: <b>${esc(result.thread.title || 'this change')}</b></p>`
      : '';
    const open = result.thread
      ? '<button type="button" data-tr="code">Open in Code</button>'
      : '';
    return `<div class="tr-result">${headline}${why}${note}${thread}</div>`
      + `<div class="tr-actions"><button type="button" class="tr-primary" data-tr="again">Change something else</button>${open}<button type="button" data-tr="close">Done</button></div>`;
  }

  function paintBar() {
    if (state.phase === 'off') return;
    const count = state.picks.length;
    if (state.phase === 'selecting') {
      const revertable = editedPicks();
      ui.bar.innerHTML = '<header><i class="ph ph-hammer" aria-hidden="true"></i><div><strong>Point at anything you want changed</strong>'
        + `<small>${count ? `${count} selected — click again to unselect` : 'Click any part of the page. Select as many as you like.'}</small></div></header>`
        + (count ? `<div class="tr-chips">${chipsHtml()}</div>` : '')
        + `<div class="tr-actions"><button type="button" class="tr-primary" data-tr="lock" ${count ? '' : 'disabled'}>Lock in ${count || ''}</button>`
        // Always present, so it can be found before it is needed. Disabled with
        // a reason beats appearing out of nowhere only once it would work.
        + `<button type="button" class="tr-undo" data-tr="revert" ${revertable.length ? '' : 'disabled'} aria-label="Undo the last change"`
        + ` title="${revertable.length
          ? `Undo the last change to ${revertable.length === 1 ? 'this' : `these ${revertable.length}`}`
          : count ? 'Nothing to undo on what you picked' : 'Pick something you changed to undo it'}">`
        + REWIND_ICON + `<span>Undo${revertable.length > 1 ? ` ${revertable.length}` : ''}</span></button>`
        + '<button type="button" data-tr="close">Cancel</button></div>'
        + (state.notice ? `<p class="tr-note" role="status">${esc(state.notice)}</p>` : '');
      return;
    }
    if (state.phase === 'locked' || state.phase === 'applying') {
      const busy = state.phase === 'applying';
      ui.bar.innerHTML = '<header><i class="ph ph-sparkle" aria-hidden="true"></i><div><strong>What should change?</strong>'
        + `<small>${count} locked in. Only these will be touched.</small></div></header>`
        + `<div class="tr-chips">${chipsHtml()}</div>`
        + `<textarea class="tr-input" rows="2" aria-label="Describe the change" placeholder="Make these bigger and put the delay count first…" ${busy ? 'disabled' : ''}></textarea>`
        + (state.error ? `<p class="tr-error" role="alert">${esc(state.error)}</p>` : '')
        + `<div class="tr-actions"><button type="button" class="tr-primary" data-tr="apply" ${busy ? 'disabled' : ''}>${busy ? 'Working…' : 'Apply'}</button><button type="button" data-tr="unlock" ${busy ? 'disabled' : ''}>Back</button><button type="button" data-tr="close" ${busy ? 'disabled' : ''}>Cancel</button></div>`;
      const field = ui.bar.querySelector('.tr-input');
      if (field && !busy) { field.value = state.draft || ''; field.focus(); }
      return;
    }
    ui.bar.innerHTML = resultHtml();
  }

  function paint() {
    build();
    ui.root.hidden = state.phase === 'off';
    ui.banner.hidden = state.phase !== 'selecting';
    document.documentElement.classList.toggle('tr-selecting', state.phase === 'selecting');
    document.documentElement.classList.toggle('tr-active', state.phase !== 'off');
    const button = document.getElementById('tc-redesign-btn');
    if (button) {
      button.setAttribute('aria-pressed', state.phase === 'off' ? 'false' : 'true');
      button.classList.toggle('is-active', state.phase !== 'off');
    }
    paintBar();
    paintMarks();
    schedule();
  }

  function indexOfElement(element) {
    return state.picks.findIndex(pick => pick.element === element);
  }

  // Anything that is currently changed can be undone — whether or not a
  // version was recorded for it. Changes made before per-element history
  // existed have no stack to pop, and offering nothing for those left the
  // control invisible with no way to find out why.
  function editedPicks() {
    const layout = L();
    if (!layout) return [];
    return state.picks.filter(pick => {
      const id = pick.descriptor.uiId;
      if (!id) return false;
      if (layout.versionCount && layout.versionCount(id) > 0) return true;
      const item = layout.get(id) || {};
      return Object.keys(item).some(key => key !== 'x' && key !== 'y');
    });
  }

  function revertSelected() {
    const layout = L();
    const targets = editedPicks();
    if (!layout || !targets.length) return;
    const undone = targets.filter(pick => {
      const id = pick.descriptor.uiId;
      if (layout.versionCount && layout.versionCount(id) > 0) return layout.revert(id);
      // No recorded history: clearing the entry restores the authored look,
      // which is the only honest meaning "undo" can have here.
      const had = Object.keys(layout.get(id) || {}).some(key => key !== 'x' && key !== 'y');
      if (!had) return false;
      layout.remove(id);
      layout.applyAll();
      return true;
    });
    // Reported from what the book actually rolled back, not from what was
    // asked — the same rule the apply path follows.
    state.notice = undone.length
      ? `Rolled back ${undone.length} of ${targets.length}: ${undone.map(pick => pick.descriptor.label).join(', ')}.`
      : 'Nothing to roll back — these are already at their original look.';
    paint();
  }

  function toggle(element) {
    state.notice = '';
    const existing = indexOfElement(element);
    if (existing >= 0) { state.picks.splice(existing, 1); paint(); return; }
    const descriptor = T().describe(element);
    if (!descriptor) return;
    state.picks.push({ descriptor, element });
    paint();
  }

  function onPointerOver(event) {
    if (state.phase !== 'selecting') return;
    const target = T().pick(event.target);
    state.hover = target;
    ui.hoverLabel.textContent = target ? T().labelFor(target) : '';
    ui.hover.classList.toggle('is-picked', Boolean(target) && indexOfElement(target) >= 0);
  }

  // While selecting, the page must not act on clicks — you are pointing, not
  // using. Capture phase and stopImmediatePropagation keep this ahead of the
  // app's own listeners, the same way UI Edit Mode does it.
  function swallow(event) {
    if (state.phase !== 'selecting') return;
    if (event.target.closest('[data-redesign-ui]')) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (event.type === 'click') {
      const target = T().pick(event.target);
      if (target) toggle(target);
    }
  }

  function onKeyDown(event) {
    if (state.phase === 'off') return;
    if (event.key === 'Escape') { event.preventDefault(); stop(); return; }
    if (state.phase === 'selecting' && event.key === 'Enter' && state.picks.length) { event.preventDefault(); act('lock'); }
  }

  function start() {
    if (state.phase !== 'off') { stop(); return; }
    build();
    state.phase = 'selecting';
    state.picks = [];
    state.result = null;
    state.error = '';
    state.notice = '';
    state.draft = '';
    paint();
  }

  function stop() {
    state.phase = 'off';
    state.picks = [];
    state.hover = null;
    state.result = null;
    state.error = '';
    state.notice = '';
    state.draft = '';
    if (state.frame) { cancelAnimationFrame(state.frame); state.frame = 0; }
    paint();
  }

  function act(name, index) {
    if (name === 'close') { stop(); return; }
    if (name === 'lock') { if (!state.picks.length) return; state.phase = 'locked'; state.error = ''; paint(); return; }
    if (name === 'unlock') { state.draft = currentDraft(); state.phase = 'selecting'; paint(); return; }
    if (name === 'drop') { state.picks.splice(Number(index), 1); if (!state.picks.length && state.phase === 'locked') state.phase = 'selecting'; paint(); return; }
    if (name === 'again') { state.phase = 'selecting'; state.picks = []; state.result = null; state.draft = ''; paint(); return; }
    if (name === 'code') { openThread(); return; }
    if (name === 'revert') { revertSelected(); return; }
    if (name === 'apply') void apply();
  }

  // Park a Code task on Thomas's own source for this change. Created, never
  // started: a redesign is a per-browser override, and the thread is where it
  // can become a real source edit if you decide you want that. Failing to
  // create one is not a failed redesign — the change already landed.
  async function openCodeThread(brief) {
    if (!brief || !brief.title) return null;
    try {
      const response = await fetch('/api/evolve/agent/conversations/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: brief.title, project_root: brief.project_root, project_choice: 'picked' }),
      });
      const data = await response.json();
      const id = String((data && (data.conversation_id || data.id || (data.conversation || {}).id)) || '');
      if (!response.ok || !id) return null;
      return { id, title: brief.title, prompt: String(brief.prompt || '') };
    } catch (_) { return null; }
  }

  // Hand the change to Code: open the thread and put the deeper-change prompt
  // in the composer WITHOUT sending it. The thread is a place to pick the work
  // up from, not a run that starts itself and edits source unasked.
  function openThread() {
    const thread = (state.result || {}).thread;
    if (!thread || !thread.id) return;
    const prompt = String(thread.prompt || '');
    stop();
    const open = window.ThomasCodeMode && window.ThomasCodeMode.openConversation
      ? window.ThomasCodeMode.openConversation(thread.id)
      : Promise.reject(new Error('code mode unavailable'));
    Promise.resolve(open).then(() => {
      const field = document.getElementById('tc-input');
      if (!field || !prompt) return;
      field.value = prompt;
      field.dispatchEvent(new Event('input', { bubbles: true }));
      field.focus();
    }).catch(() => {
      // Falling back to the deliverable deep link costs a reload but always
      // lands on the right thread.
      location.href = `/?forge_code=${encodeURIComponent(thread.id)}`;
    });
  }

  function currentDraft() {
    const field = ui && ui.bar.querySelector('.tr-input');
    return field ? String(field.value || '') : '';
  }

  function provideContext(fn) { contextProvider = typeof fn === 'function' ? fn : null; }

  function callContext() {
    try { return contextProvider ? (contextProvider() || {}) : {}; }
    catch (_) { return {}; }
  }

  // Apply the layout half locally and count what genuinely moved. A style
  // the page already had is not a change, and saying it was is the exact
  // lie this feature exists to stop telling.
  function applyLayout(entries, rejected) {
    const layout = L();
    if (!layout || !Array.isArray(entries)) return 0;
    const iconChecks = [];
    let changed = 0;
    entries.forEach(entry => {
      const uiId = String(entry.ui_id || '');
      if (!uiId) return;
      const before = JSON.stringify(layout.get(uiId) || {});
      const merged = Object.assign({ x: 0, y: 0 }, layout.get(uiId) || {});
      const style = layout.cleanStyle ? layout.cleanStyle(entry.style) : {};
      if (Object.keys(style).length) merged.style = Object.assign({}, merged.style || {}, style);
      ['x', 'y', 'width', 'height', 'z'].forEach(key => {
        const value = Number(entry[key]);
        if (Number.isFinite(value)) merged[key] = value;
      });
      if (entry.hidden === true) merged.hidden = true;
      if (entry.hidden === false) delete merged.hidden;
      const icon = String(entry.icon || '').trim();
      if (/^ph-[a-z0-9-]+$/.test(icon)) { merged.icon = icon; iconChecks.push({ entry, uiId, icon, previous: (layout.get(uiId) || {}).icon || '' }); }
      if (JSON.stringify(merged) === before) return;
      // Record what it looked like BEFORE, so this one element can be rolled
      // back later even after other things have been changed around it.
      if (layout.pushVersion) layout.pushVersion(uiId);
      layout.set(uiId, merged);
      changed += 1;
    });
    if (changed) layout.applyAll();

    // Verify each icon actually RENDERED. Thomas's icons are a Unicode map in
    // chat_shell.css, so a name outside it silently degrades to a bullet — the
    // stylesheet's own comment says it "has to be checked by looking". This is
    // that check: an unresolved glyph is rolled back and reported, never left
    // sitting on the button looking like a broken control.
    iconChecks.forEach(check => {
      const node = state.picks[Number(check.entry.target_index)];
      const element = node && node.element && node.element.isConnected
        ? node.element
        : (node ? T().resolve(node.descriptor) : null);
      if (!element || !T().iconRendersAsFallback(element)) return;
      const item = Object.assign({}, layout.get(check.uiId) || {});
      if (check.previous) item.icon = check.previous; else delete item.icon;
      if (Object.keys(item).filter(key => key !== 'x' && key !== 'y').length) layout.set(check.uiId, item);
      else layout.remove(check.uiId);
      layout.applyAll();
      changed = Math.max(0, changed - 1);
      rejected.push({
        target_index: check.entry.target_index,
        label: node ? node.descriptor.label : 'That icon',
        reason: `"${check.icon}" is not in Thomas's icon set, so it rendered as a blank dot — I put the original back. Open this in Code to add the glyph properly.`,
      });
    });
    return changed;
  }

  async function apply() {
    if (state.phase !== 'locked') return;
    const instruction = currentDraft().trim();
    if (!instruction) { state.error = 'Say what should change first.'; paint(); return; }
    state.draft = instruction;
    state.error = '';
    state.phase = 'applying';
    paint();
    const layout = L();
    const payload = {
      instruction,
      workspace: layout ? layout.workspace() : 'chat',
      breakpoint: layout ? layout.currentPoint() : 'desktop',
      targets: state.picks.map(pick => pick.descriptor),
      context: callContext(),
    };
    // Only when an icon is actually selected — the vocabulary is ~40 names and
    // there is no reason to spend them on a request about a sidebar's width.
    if (state.picks.some(pick => pick.descriptor.isIcon)) payload.icon_vocabulary = T().iconVocabulary();
    try {
      const response = await fetch('/api/ui/redesign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      let data;
      try { data = await response.json(); }
      catch (_) {
        // A non-JSON body on a failed status is the status' story to tell;
        // blaming the payload hid "this server predates the endpoint".
        throw new Error(response.status === 404
          ? 'This Thomas server does not have the redesign endpoint yet — restart it to pick it up.'
          : response.ok
            ? `Redesign returned an unreadable response (${response.status})`
            : `Redesign failed (${response.status})`);
      }
      if (!response.ok || data.ok === false) throw new Error(data.error || `Redesign failed (${response.status})`);
      const iconRejected = [];
      const layoutChanged = applyLayout(data.layout, iconRejected);
      const specChanged = Number((data.dashboard || {}).changed || 0);
      if (specChanged) {
        window.dispatchEvent(new CustomEvent('thomas:work-dashboard-updated', { detail: data.dashboard || {} }));
      }
      const blocked = Array.isArray(data.unsupported) ? data.unsupported.slice() : [];
      iconRejected.forEach(row => blocked.push(row));
      // Anything we selected that neither channel touched is reported as
      // untouched rather than quietly folded into a success count.
      const touched = new Set([
        ...(Array.isArray(data.layout) ? data.layout : []).map(row => String(row.target_index)),
        ...(((data.dashboard || {}).applied) || []).map(row => String(row.target_index)),
      ]);
      state.picks.forEach((pick, index) => {
        if (touched.has(String(index))) return;
        if (blocked.some(row => String(row.target_index) === String(index))) return;
        blocked.push({ target_index: index, label: pick.descriptor.label, reason: 'Thomas returned no edit for this one' });
      });
      blocked.forEach(row => {
        if (row.label) return;
        const pick = state.picks[Number(row.target_index)];
        row.label = pick ? pick.descriptor.label : 'That element';
      });
      const changedTotal = layoutChanged + specChanged;
      state.result = {
        changed: changedTotal,
        unsupported: blocked,
        thread: changedTotal ? await openCodeThread(data.code_thread) : null,
      };
      state.phase = 'result';
    } catch (error) {
      state.error = error && error.message ? error.message : 'Redesign could not complete.';
      state.phase = 'locked';
    }
    paint();
  }

  function bind() {
    build();
    const button = document.getElementById('tc-redesign-btn');
    if (button) button.addEventListener('click', start);
    document.addEventListener('pointerover', onPointerOver, true);
    document.addEventListener('pointerdown', swallow, true);
    document.addEventListener('click', swallow, true);
    document.addEventListener('submit', swallow, true);
    document.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('resize', schedule);
  }

  window.ThomasRedesign = {
    start,
    stop,
    provideContext,
    phase: () => state.phase,
    selection: () => state.picks.map(pick => pick.descriptor),
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, { once: true });
  else bind();
})();
