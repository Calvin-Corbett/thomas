/* chat_auto_title.js -- ask for a better name for a chat once a reply has been saved.

   The server decides whether it is time (the first prompt, then the whole chat after the fifth) and does the naming with
   the title model; this only tells it a reply was saved and refreshes the sidebar if a new name came back. It never waits
   for the answer and a failure changes nothing: the chat keeps the name it had. */
(function () {
  'use strict';

  const asked = new Map();  // session id -> the number of replies when it was last asked

  function after(sessionId, replies, onTitle) {
    const id = String(sessionId || '').trim();
    if (!id || typeof fetch !== 'function') return;
    if (asked.get(id) === replies) return;  // one ask per saved reply
    asked.set(id, replies);
    fetch('/api/chats/auto-title', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: id }) })
      .then(response => (response.ok ? response.json() : null))
      .then(data => { if (data && data.title && !data.skipped && typeof onTitle === 'function') onTitle(data.title); })
      .catch(() => { /* the name it had stays */ });
  }

  window.ThomasAutoTitle = { after };
}());
