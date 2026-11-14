/* Preserve the reader's place while Build replaces its rendered transcript. */
(function () {
  'use strict';
  const renderedScopes = new WeakMap();

  function detailKey(detail) {
    const turn = detail.closest('[data-code-turn-key]');
    const change = detail.closest('.tc-code-change');
    const receipt = detail.matches('.tc-code-receipt') ? detail
      : detail.querySelector('.tc-code-receipt');
    // Match the actual tool/output, not a row number: the event ring can drop
    // earlier rows.
    const content = receipt ? [receipt.dataset.codeEventSeq, receipt.dataset.codeKind, receipt.dataset.codeTool,
      receipt.querySelector('pre')?.textContent || ''] : [detail.textContent];
    return JSON.stringify([turn?.dataset.codeTurnKey || '',
      change?.querySelector('[data-code-keep]')?.dataset.codeKeep || '',
      detail.className, content]);
  }

  function visiblyOpen(detail, root) {
    for (let node = detail; node && node !== root; node = node.parentElement) {
      if (node.tagName === 'DETAILS' && !node.open) return false;
    }
    return detail.open;
  }

  // A live preview is a running page (a game someone is playing). render()
  // rewrites innerHTML, which would destroy it; moveBefore() relocates a frame
  // without reloading it, so loaded frames wait in a hidden holder and go back
  // into the figure with the same slot when it is drawn again. Without
  // moveBefore (older browsers) the frame simply reloads, as it always did.
  function stashPreviews(root) {
    const doc = root.ownerDocument;
    if (!doc || !doc.body || typeof doc.createElement !== 'function') return;
    let holder = doc.getElementById('tc-live-stash');
    if (!holder) {
      holder = doc.createElement('div');
      holder.id = 'tc-live-stash';
      holder.hidden = true;
      doc.body.appendChild(holder);
    }
    if (typeof holder.moveBefore !== 'function') return;
    root.querySelectorAll('[data-code-live]').forEach(figure => {
      const frame = figure.querySelector('iframe[src]');
      if (!frame) return;
      frame.dataset.liveSlot = figure.dataset.codeLive;
      try { holder.moveBefore(frame, null); } catch (error) { /* it reloads instead */ }
    });
  }

  function unstashPreviews(root) {
    const doc = root.ownerDocument;
    const holder = doc && typeof doc.getElementById === 'function' ? doc.getElementById('tc-live-stash') : null;
    if (!holder || !holder.children) return;
    const kept = Array.from(holder.children);
    root.querySelectorAll('[data-code-live]').forEach(figure => {
      const frame = kept.find(item => item.dataset.liveSlot === figure.dataset.codeLive
        && item.dataset.liveSrc === figure.dataset.liveDoc);
      const fresh = figure.querySelector('iframe');
      if (!frame || !fresh || typeof figure.moveBefore !== 'function') return;
      try {
        figure.moveBefore(frame, fresh);
        fresh.remove();
        kept.splice(kept.indexOf(frame), 1);
      } catch (error) { /* the new frame loads normally */ }
    });
    kept.forEach(item => item.remove());
  }

  function capture(root, transcript) {
    stashPreviews(root);
    const active = root.ownerDocument.activeElement;
    // A text field you are typing in (the side chat's box) keeps its caret.
    const field = active && root.contains(active) && typeof active.selectionStart === 'number' ? active : null;
    const disclosures = new Map();
    root.querySelectorAll('details').forEach(detail => {
      const previous = { open: detail.open, visible: visiblyOpen(detail, root),
        focused: active === detail.querySelector('summary') };
      const key = detailKey(detail);
      if (!disclosures.has(key)) disclosures.set(key, []);
      disclosures.get(key).push(previous);
    });
    return {
      scope: renderedScopes.get(root), disclosures,
      activeId: active && root.contains(active) ? active.id : '',
      fieldStart: field ? field.selectionStart : null,
      fieldEnd: field ? field.selectionEnd : null,
      transcriptScroll: transcript ? transcript.scrollTop : 0,
    };
  }

  function restore(root, saved, scope, transcript) {
    renderedScopes.set(root, scope);
    unstashPreviews(root);
    if (saved.scope !== scope) return;
    const visible = [];
    let focusedSummary = null;
    root.querySelectorAll('details').forEach(detail => {
      const previous = saved.disclosures.get(detailKey(detail))?.shift();
      if (!previous) return;
      detail.open = previous.open;
      if (previous.visible) visible.push(detail);
      if (previous.focused) focusedSummary = detail.querySelector('summary');
    });
    // A receipt that was visible before folding must remain reachable. Do not
    // reopen a group the reader explicitly closed with an open receipt inside.
    visible.forEach(detail => {
      for (let node = detail.parentElement; node && node !== root; node = node.parentElement) {
        if (node.tagName === 'DETAILS') node.open = true;
      }
    });
    if (focusedSummary) focusedSummary.focus({ preventScroll: true });
    const active = saved.activeId && root.ownerDocument.getElementById(saved.activeId);
    if (active && root.contains(active)) {
      active.focus({ preventScroll: true });
      if (typeof active.setSelectionRange === 'function' && saved.fieldStart !== null) {
        active.setSelectionRange(saved.fieldStart, saved.fieldEnd);
      }
    }
    // Opening disclosures changes layout, so restore scroll after their state.
    if (transcript) transcript.scrollTop = saved.transcriptScroll;
  }

  function replaceActivity(root, list, html, scope, transcript) {
    const saved = capture(root, transcript);
    list.innerHTML = html;
    restore(root, saved, scope, transcript);
  }

  window.ThomasCodeViewState = { capture, restore, replaceActivity };
})();
