/* unified_code_loading.js -- the part of Build that is still loading shimmers; the rest stays put.

   Clicking another task used to rebuild the whole Build screen (twice) before and after its content arrived, so
   everything flickered. Now the click only turns the places that change into shimmering placeholders (the title,
   the conversation, the message box) and the one real draw happens when the task's content is there. */
(function () {
  'use strict';

  const SKELETON = '<div class="tc-code-skeleton" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>';

  function mark(on) {
    const root = typeof document !== 'undefined' ? document.documentElement : null;
    if (root && root.classList) root.classList.toggle('tc-code-opening', on);
  }

  function show() {
    if (typeof document === 'undefined' || typeof document.querySelector !== 'function') return false;
    const transcript = document.querySelector('.tc-code-transcript');
    if (!transcript) return false;
    transcript.innerHTML = SKELETON;
    mark(true);
    return true;
  }

  function hide() {
    mark(false);
  }

  window.ThomasCodeLoading = { show, hide };
}());
