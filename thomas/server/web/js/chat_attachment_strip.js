/* What you attached to a message, drawn on the message (window.ThomasAttachmentStrip).
 *
 * Items are { name, kind: 'image' | 'doc', thumb? }: a picture shows as a small picture while its data is at hand (just
 * after you send), and as a named chip after that; a PDF or any other file is a named chip. Build's server keeps the
 * files themselves in the project but not a record on the turn, so this remembers, in this browser only, which names
 * went with which message text, and gives them back when the conversation is opened again.
 */
(function () {
  'use strict';

  const KEY = 'thomas_message_attachments';
  const KEEP = 120;

  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  function itemsFrom(docs, images) {
    const out = [];
    // The picture's data is not an enumerable property: it draws now, but is left out of anything saved or copied.
    (Array.isArray(images) ? images : []).forEach(image => {
      if (!image || !image.name) return;
      const item = { name: String(image.name), kind: 'image' };
      Object.defineProperty(item, 'thumb', { value: String(image.data_url || ''), enumerable: false });
      out.push(item);
    });
    (Array.isArray(docs) ? docs : []).forEach(doc => { if (doc && doc.name) out.push({ name: String(doc.name), kind: 'doc' }); });
    return out;
  }

  function html(items) {
    const list = Array.isArray(items) ? items.filter(item => item && item.name) : [];
    if (!list.length) return '';
    const cells = list.map(item => {
      const label = esc(item.name);
      if (item.kind === 'image' && item.thumb && /^data:image\//.test(item.thumb)) {
        return `<figure class="tc-att is-image" title="${label}"><img src="${esc(item.thumb)}" alt="${label}"><figcaption>${label}</figcaption></figure>`;
      }
      const icon = item.kind === 'image'
        ? '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m4 18 5-5 4 4 3-3 4 4"/></svg>'
        : '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M9.5 14h5M9.5 17h5"/></svg>';
      return `<span class="tc-att is-file" title="${label}">${icon}<span>${label}</span></span>`;
    }).join('');
    return `<div class="tc-att-strip">${cells}</div>`;
  }

  function read() {
    try { const raw = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(raw) ? raw : []; } catch (error) { return []; }
  }

  // Remember names only (never picture data), keyed by the message text.
  function remember(text, items) {
    const key = String(text || '').trim();
    const names = (Array.isArray(items) ? items : []).filter(item => item && item.name).map(item => ({ name: item.name, kind: item.kind }));
    if (!key || !names.length) return;
    try {
      const rows = read().filter(row => row && row.text !== key);
      rows.push({ text: key, items: names });
      localStorage.setItem(KEY, JSON.stringify(rows.slice(-KEEP)));
    } catch (error) { /* storage blocked or full: the chips are just not remembered */ }
  }

  function recall(text) {
    const key = String(text || '').trim();
    const row = key ? read().find(entry => entry && entry.text === key) : null;
    return row && Array.isArray(row.items) ? row.items : [];
  }

  // A Build send: keep what rides with this message for its pending bubble, and remember the names for later.
  function stage(state, message, context) {
    state.pendingAttachments = itemsFrom(context && context.docs, context && context.images);
    if (state.pendingAttachments.length) remember(message, state.pendingAttachments);
  }

  window.ThomasAttachmentStrip = { html, itemsFrom, remember, recall, stage };
})();
