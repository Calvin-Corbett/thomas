import { installScript } from './chat_feature_fixture.mjs';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_edit_resend_failure.mjs <chat.html>');

const messages = [{ role: 'user', text: 'Original' }, { role: 'assistant', text: 'Reply' }];
const state = { messages, sessionId: 'session-1', streaming: false };
const alerts = [];
const pending = [];
let current = true;
const inputEl = { value: '' };
const threadEl = { innerHTML: 'existing transcript', appendChild() {} };
const context = {
  state, inputEl, threadEl, msgRefs: [{}, {}],
  captureConversation: () => () => current,
  reportFriction: () => {},
  fetch: async url => url === '/api/issues' ? ({ ok: true }) : ({ ok: false, status: 403 }),
  console: { warn() {} },
  window: { alert: message => alerts.push(message) },
};
installScript(context, htmlPath, 'chat_message_view.js');
const view = context.window.ThomasChatMessageView.create(context);
await view.editMessageFrom(0);
if (alerts.length !== 1 || state.messages !== messages || threadEl.innerHTML !== 'existing transcript' || inputEl.value !== '') {
  throw new Error('A rejected edit must not discard the visible or saved conversation');
}
context.fetch = async url => url === '/api/issues' ? ({ ok: true }) : Promise.reject(new Error('offline'));
await view.editMessageFrom(0);
if (alerts.length !== 2 || state.messages !== messages || threadEl.innerHTML !== 'existing transcript') {
  throw new Error('An offline edit must not discard the conversation');
}
context.fetch = url => url === '/api/issues' ? Promise.resolve({ ok: true })
  : new Promise(resolve => pending.push(resolve));
const obsoleteEdit = view.editMessageFrom(0);
current = false;
pending[0]({ ok: true });
await obsoleteEdit;
if (alerts.length !== 2 || state.messages !== messages || threadEl.innerHTML !== 'existing transcript') {
  throw new Error('A completed edit for a conversation that is no longer current must not change it');
}
process.stdout.write('rejected, offline, and obsolete edits preserve the transcript\n');

// Reporting a failure must not manufacture the next one. Every other harness
// stubs /api/issues as reachable, so nothing exercised the path that matters:
// `fetch` rejects ASYNCHRONOUSLY, so the try/catch inside reportFriction never
// sees an unreachable endpoint and the rejection escapes. chat.html routes
// `unhandledrejection` back into reportPageError -> reportFriction -> the same
// failing post, so the reporter became a source of the errors it exists to
// report -- worst exactly when the server is already down.
const escaped = [];
process.on('unhandledRejection', reason => escaped.push(reason));
context.fetch = url => url === '/api/issues'
  ? Promise.reject(new Error('issues endpoint unreachable'))
  : Promise.resolve({ ok: true });
view.reportPageError('TypeError: Failed to fetch');
// Node reports an unhandled rejection after the microtask queue drains, so the
// `.catch` has to be attached synchronously for this to stay quiet.
await new Promise(resolve => setTimeout(resolve, 10));
if (escaped.length) {
  throw new Error(`reporting a page error escaped as an unhandled rejection: ${escaped[0]}`);
}
process.stdout.write('an unreachable issue ledger does not become another page error: passed\n');
