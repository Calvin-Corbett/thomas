/* Advanced model settings: a centred modal over the dimmed chat, opened from
   "Advanced..." at the foot of the model pill's dropdown.

   It owns only the dialog (open, close, Esc, click outside, the X, focus). The
   table inside it, one row per job with its model and agent, is drawn and saved
   by renderSpecialistModels in chat_model_accounts.js, so it keeps the one
   store the old per-role selectors used. */
(function () {
  'use strict';
  function create(deps) {
    let overlay = null;
    let opener = null;
    let onKey = null;

    function close() {
      if (!overlay) return;
      overlay.remove(); overlay = null;
      document.removeEventListener('keydown', onKey, true);
      if (opener && typeof opener.focus === 'function') opener.focus();
      opener = null;
    }

    function fill(body) {
      body.textContent = '';
      const wrap = body;
      deps.renderSpecialistModels(wrap);
    }

    function open() {
      if (overlay) return;
      opener = document.getElementById('tc-model-btn');
      overlay = document.createElement('div');
      overlay.className = 'tc-adv-overlay';
      overlay.addEventListener('mousedown', event => { if (event.target === overlay) close(); });
      const dialog = document.createElement('div');
      dialog.className = 'tc-adv-dialog';
      dialog.setAttribute('role', 'dialog');
      dialog.setAttribute('aria-modal', 'true');
      dialog.setAttribute('aria-labelledby', 'tc-adv-title');
      const head = document.createElement('div');
      head.className = 'tc-adv-head';
      const title = document.createElement('h2');
      title.id = 'tc-adv-title'; title.textContent = 'Advanced model settings';
      const x = document.createElement('button');
      x.type = 'button'; x.className = 'tc-adv-close'; x.textContent = '✕';
      x.setAttribute('aria-label', 'Close');
      x.addEventListener('click', close);
      head.appendChild(title); head.appendChild(x);
      const body = document.createElement('div');
      body.className = 'tc-adv-body';
      dialog.appendChild(head); dialog.appendChild(body);
      overlay.appendChild(dialog);
      document.body.appendChild(overlay);
      fill(body);
      onKey = event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } };
      document.addEventListener('keydown', onKey, true);
      x.focus();
    }

    return { open, close };
  }
  window.ThomasChatModelAdvanced = { create };
})();
