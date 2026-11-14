(function () {
  'use strict';

  const button = document.getElementById('tc-attach-btn');
  const menu = document.getElementById('tc-create-menu');
  const addFilesButton = document.getElementById('tc-create-add-files');
  const input = document.getElementById('tc-input');
  const fileInput = document.getElementById('tc-file-input');
  if (!button || !menu || !addFilesButton || !input || !fileInput) return;

  function close(restoreFocus) {
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    if (restoreFocus) button.focus();
  }
  function open() {
    // Image, music and video are made in Chat. In Build and Work the items did nothing and said nothing, so they are not offered there.
    const inChat = !window.ThomasUnifiedModes || window.ThomasUnifiedModes.mode() === 'chat';
    menu.querySelectorAll('[data-create-action="image"], [data-create-action="video"], [data-create-action="music"]').forEach(item => { item.style.display = inChat ? '' : 'none'; });
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    addFilesButton.focus();
  }
  window.ThomasCreateMenu = { close: () => close(false) };
  button.addEventListener('click', () => { if (menu.hidden) open(); else close(false); });
  addFilesButton.addEventListener('click', event => { event.stopPropagation(); close(false); fileInput.click(); });
  menu.addEventListener('click', event => {
    const item = event.target.closest('[data-create-action]');
    if (!item) return;
    if (item.disabled) return;
    const action = item.getAttribute('data-create-action'); close(false);
    if (action === 'redesign') { if (window.ThomasRedesign) window.ThomasRedesign.start(); return; }
    if (['image', 'video', 'music'].includes(action) && window.ThomasMediaGeneration) {
      void window.ThomasMediaGeneration.create(action);
    }
  });
  document.addEventListener('mousedown', event => { if (!menu.hidden && !event.target.closest('[data-create-wrap]')) close(false); });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!menu.hidden && !document.body.classList.contains('thomas-ui-editing')) { event.preventDefault(); close(true); }
  });
})();
