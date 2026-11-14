/* How one attention card is drawn. Strings in, markup out, so it can be checked without a browser.
 *
 * A card is a notice, a question with buttons, a reply box, a picture, a live preview of a page Thomas built, or a
 * layout he wrote himself. Every word that came from a card is escaped. The two things that are not words are kept
 * apart from this page: a preview is a frame on the loopback address Thomas serves his builds from, sandboxed with no
 * access to this origin, and his own layout is a sandboxed frame whose document carries a policy that allows no
 * network at all. Neither can read the page, the cookie or the conversation.
 */
(function () {
  'use strict';

  const TONES = { info: 'Notice', done: 'Done', warn: 'Warning', ask: 'Question' };
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  // The document a layout Thomas wrote is put in. `default-src 'none'` is the point: it may draw and run its own
  // script, and it may show a picture it carries inside itself (a data: URL), and it can fetch, post or load nothing.
  function frameDoc(html) {
    return '<!doctype html><meta charset="utf-8">'
      + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'">'
      // Dark by declaration: a frame with no colour scheme of its own is given a white canvas inside a dark page.
      + '<meta name="color-scheme" content="dark"><style>html,body{margin:0;background:#0e0f13;color:#e7e9ee;font:13px/1.45 system-ui,sans-serif}</style>'
      + String(html || '');
  }

  function mediaHtml(card) {
    const title = esc(card.title);
    if (card.kind === 'image' && card.image_url) return `<img class="tc-attn-image" src="${esc(card.image_url)}" alt="${title}">`;
    if (card.kind === 'preview' && card.preview_url) {
      return `<iframe class="tc-attn-frame is-preview" title="Preview: ${title}" sandbox="allow-scripts allow-pointer-lock" loading="lazy" src="${esc(card.preview_url)}"></iframe>`;
    }
    if (card.kind === 'html' && card.html) {
      return `<iframe class="tc-attn-frame" title="${title}" sandbox="allow-scripts" srcdoc="${esc(frameDoc(card.html))}"></iframe>`;
    }
    return '';
  }

  function cardHtml(card) {
    const id = esc(card.id);
    const tone = TONES[card.tone] ? card.tone : 'info';
    const title = esc(card.title);
    // A widget's body is blocks drawn natively (attention_widget_view.js); its buttons are among them.
    const widget = card.kind === 'widget' && typeof window !== 'undefined' && window.ThomasAttentionWidgetView;
    const blocks = widget ? `<div class="tc-attn-blocks" data-attn-blocks>${widget.blocksHtml(card.blocks)}</div>` : '';
    const options = (widget || !Array.isArray(card.options) ? [] : card.options).map((row, index) => (
      `<button type="button" class="tc-attn-option${index === 0 ? ' is-first' : ''}" data-attn-option="${esc(row.id)}"${row.open_task ? ` data-attn-open-task="${esc(row.open_task)}"` : ''}>${esc(row.label)}</button>`
    )).join('');
    const reply = card.kind === 'reply'
      ? `<form class="tc-attn-reply" data-attn-reply><label class="tc-attn-sr" for="tc-attn-reply-${id}">Your reply</label>`
        + `<textarea id="tc-attn-reply-${id}" name="reply" rows="2" required placeholder="Type your reply…"></textarea><button type="submit" class="tc-attn-option is-first">Send reply</button></form>`
      : '';
    // The tone is said in words for a screen reader. On screen every card looks the same: the app's own panel.
    return `<article class="tc-attn-card is-${tone}" data-attn-card="${id}" role="${tone === 'warn' ? 'alert' : 'status'}" aria-label="${esc(TONES[tone])}: ${title}">`
      + `<header class="tc-attn-head" data-attn-grip title="Drag to move these cards. Double-click to put them back.">`
      + `<strong class="tc-attn-title">${title}</strong>`
      + `<button type="button" class="tc-attn-close" data-attn-dismiss aria-label="Close: ${title}">×</button></header>`
      + (card.body ? `<p class="tc-attn-body">${esc(card.body)}</p>` : '')
      + mediaHtml(card)
      + blocks
      + (options ? `<div class="tc-attn-actions">${options}</div>` : '')
      + reply
      + '<p class="tc-attn-error" data-attn-error role="alert" hidden></p>'
      + '</article>';
  }

  // What makes a card need redrawing. An unchanged card keeps its node, so a reply half typed and a preview that is
  // running are not thrown away each time the list is asked for again.
  function signature(card) {
    return JSON.stringify([card.kind, card.tone, card.title, card.body, card.options, card.image_url, card.preview_url, card.html]);
  }

  // A widget's readings change every few seconds. They are compared apart from the rest, so a refresh swaps the
  // blocks inside the card and the card itself stays where it is.
  function blocksSignature(card) {
    return JSON.stringify(card.blocks || []);
  }

  function pillHtml(count) {
    return `<button type="button" class="tc-attn-pill" data-attn-pill aria-label="${count} card${count === 1 ? '' : 's'} from Thomas. Show ${count === 1 ? 'it' : 'them'}.">${count}</button>`;
  }

  const api = { cardHtml, frameDoc, signature, blocksSignature, pillHtml, esc };
  if (typeof window !== 'undefined') window.ThomasAttentionView = api;
})();
