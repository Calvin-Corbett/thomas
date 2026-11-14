// How an attention card is drawn (js/attention_card_view.js), checked without a browser (2026-11-09).
//
// A card's words come from a model or another program, so every one of them is escaped; a preview and a layout the
// model wrote go in sandboxed frames that cannot reach this page; and a card that has not changed keeps its
// signature, which is what lets the page leave a half-typed reply and a running preview alone between refreshes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const viewPath = process.argv[2];
if (!viewPath) throw new Error('usage: node attention_cards.mjs <attention_card_view.js>');
globalThis.window = {};
vm.runInThisContext(fs.readFileSync(viewPath, 'utf8'), { filename: viewPath });
const view = window.ThomasAttentionView;

const base = { id: 'c1', kind: 'notice', tone: 'info', title: 'Plain', body: '', options: [], image_url: '', preview_url: '', html: '' };
const kinds = {
  notice: view.cardHtml({ ...base, body: 'A sentence.' }),
  question: view.cardHtml({ ...base, kind: 'question', tone: 'ask', options: [{ id: 'yes', label: 'Do it' }, { id: 'no', label: 'Not now' }] }),
  reply: view.cardHtml({ ...base, kind: 'reply', tone: 'ask' }),
  image: view.cardHtml({ ...base, kind: 'image', image_url: '/api/evolve/agent/artifact/x/pong.png' }),
  preview: view.cardHtml({ ...base, kind: 'preview', tone: 'done', preview_url: 'http://127.0.0.1:9123/__enter/abc' }),
  html: view.cardHtml({ ...base, kind: 'html', html: '<b>mine</b><script>fetch("http://example.com")</script>' }),
};

// Each kind draws its own part.
assert.match(kinds.notice, /<p class="tc-attn-body">A sentence\.<\/p>/);
assert.equal((kinds.question.match(/data-attn-option=/g) || []).length, 2);
assert.match(kinds.question, /data-attn-option="yes">Do it</);
assert.match(kinds.reply, /<form class="tc-attn-reply" data-attn-reply>/);
assert.match(kinds.reply, /<textarea id="tc-attn-reply-c1" name="reply"/);
assert.match(kinds.reply, /<label class="tc-attn-sr" for="tc-attn-reply-c1">Your reply<\/label>/, 'the reply box has a name');
assert.match(kinds.image, /<img class="tc-attn-image" src="\/api\/evolve\/agent\/artifact\/x\/pong\.png" alt="Plain">/);

// A preview and a model's own layout are frames that cannot reach this page: no allow-same-origin on either.
const previewFrame = kinds.preview.match(/<iframe[^>]*>/)[0];
assert.match(previewFrame, /sandbox="allow-scripts allow-pointer-lock"/);
assert.match(previewFrame, /src="http:\/\/127\.0\.0\.1:9123\/__enter\/abc"/);
const ownFrame = kinds.html.match(/<iframe[^>]*>/)[0];
assert.match(ownFrame, /sandbox="allow-scripts"/);
assert.ok(!/allow-same-origin/.test(previewFrame + ownFrame), 'neither frame shares this origin');
assert.ok(!/allow-forms|allow-top-navigation|allow-popups/.test(previewFrame + ownFrame));
assert.ok(!kinds.html.includes('<b>mine</b>'), 'the layout is never put into this page as markup');
assert.match(ownFrame, /srcdoc="[^"]*&lt;b&gt;mine&lt;\/b&gt;/, 'it is the escaped text of the frame document');

// The frame document allows no network at all.
const doc = view.frameDoc('<p>x</p>');
assert.match(doc, /Content-Security-Policy" content="default-src 'none';/);
assert.ok(!/connect-src|frame-src|form-action [^']/.test(doc), 'nothing reopens what default-src closed');
assert.match(doc, /<p>x<\/p>$/);
// Seen in the live app: with no colour scheme of its own the frame got a white canvas inside the dark page.
assert.match(doc, /<meta name="color-scheme" content="dark">/);
assert.match(doc, /html,body\{margin:0;background:#0e0f13;/);

// Every word that came from the card is escaped, in text and in attributes.
const hostile = view.cardHtml({
  ...base, id: '"><x', kind: 'question', title: '<img src=x onerror=alert(1)>', body: '</p><script>alert(2)</script>',
  options: [{ id: '"onclick="x', label: '<b>bold</b>', open_task: '"><script>' }],
});
assert.ok(!/<img src=x|<script>alert|<b>bold<\/b>|<x/.test(hostile), 'no card text reaches the page as markup');
assert.match(hostile, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.match(hostile, /data-attn-option="&quot;onclick=&quot;x"/);

// The tone is said in words for a screen reader, a warning interrupts, and every card can be closed by name.
assert.match(view.cardHtml({ ...base, tone: 'warn', title: 'Hot' }), /role="alert" aria-label="Warning: Hot"/);
assert.match(kinds.notice, /role="status" aria-label="Notice: Plain"/);
assert.match(kinds.notice, /data-attn-dismiss aria-label="Close: Plain"/);
assert.match(view.cardHtml({ ...base, tone: 'nonsense' }), /is-info/, 'an unknown tone is drawn as a notice');

// A button may open a Build task; that is the only thing besides answering a button can do.
assert.match(view.cardHtml({ ...base, kind: 'question', options: [{ id: 'open', label: 'Open it', open_task: 'fc_123' }] }), /data-attn-open-task="fc_123"/);

// Unchanged card, unchanged signature; any shown field changes it.
assert.equal(view.signature(base), view.signature({ ...base, created: 5, expires: 9 }));
assert.notEqual(view.signature(base), view.signature({ ...base, body: 'now with words' }));

// The counter that stands in for the cards where there is no gutter.
assert.match(view.pillHtml(1), /aria-label="1 card from Thomas\. Show it\.">1</);
assert.match(view.pillHtml(3), /aria-label="3 cards from Thomas\. Show them\.">3</);

console.log(JSON.stringify({ everyKindDraws: true, framesAreSealed: true, wordsAreEscaped: true }));
