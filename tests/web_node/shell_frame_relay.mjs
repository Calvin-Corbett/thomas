// Thomas's internal frame traffic, aimed only at frames that can receive it.
//
// `isOurFrame` decided ownership from the `src` attribute alone, and a srcdoc
// frame reports an empty src, so it was read as same-origin. A sandbox WITHOUT
// allow-same-origin gives the document an OPAQUE origin whatever its content
// is, so those posts were refused by the browser -- once per frame, per
// message, on Chat's live canvas frames and Build's file-preview shot, which
// are exactly the frames on screen while someone is switching themes.
//
// Companion to tests/test_shell_does_not_talk_to_generated_pages.py, which
// pins the source text; this runs the function.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const filename = process.argv[2];
if (!filename) throw new Error('usage: node shell_frame_relay.mjs <workspace_shell.js>');

const ORIGIN = 'http://127.0.0.1:8899';

// `readyState: 'loading'` defers init() onto a DOMContentLoaded listener this
// stub records and never fires, so loading the file wires up the exports
// without booting the theme, the storage listener or the browser chrome.
const frames = [];
const listeners = [];
const context = {
  URL,
  location: { origin: ORIGIN, href: `${ORIGIN}/`, search: '' },
  document: {
    readyState: 'loading',
    addEventListener: (type, handler) => listeners.push({ type, handler }),
    querySelectorAll: selector => (selector === 'iframe' ? frames.slice() : []),
    getElementById: () => null,
  },
  window: {
    // Short-circuits overlayView()'s DOM read; safeTheme() runs on every send.
    ThomasOverlayView: { present: false },
    addEventListener: (type, handler) => listeners.push({ type, handler }),
  },
};
context.window.parent = context.window;
vm.createContext(context);
vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename });
const shell = context.window.ThomasWorkspaceShell;

function makeFrame(label, attributes, options) {
  const received = [];
  const frame = {
    label,
    received,
    getAttribute: name => (name in attributes ? attributes[name] : null),
    contentWindow: {
      postMessage(message, targetOrigin) {
        if (options && options.throws) throw new Error(`refused: ${label}`);
        received.push({ message, targetOrigin });
      },
    },
  };
  frames.push(frame);
  return frame;
}

// The three frames Thomas actually ships sandboxed without allow-same-origin.
// All are srcdoc, so all report an empty src and used to read as ours.
const chatLive = makeFrame('chat .tc-live-frame', { sandbox: 'allow-scripts' });
const chatBuild = makeFrame('chat .tc-build-frame', { sandbox: 'allow-scripts' });
const buildShot = makeFrame('build .tc-code-file-shot', { sandbox: 'allow-scripts' });
// An empty sandbox is the MOST restrictive form, not the absent one.
const sealed = makeFrame('sandbox=""', { sandbox: '' });
// Substring matching would accept this; the token is not allow-same-origin.
const lookalike = makeFrame('lookalike token', { sandbox: 'allow-same-origin-please' });
// The workspace frames, which must keep working.
const workspace = makeFrame('workspace srcdoc', {});
const embedded = makeFrame('workspace embed', { src: '/settings?embed=1' });
const thumbnail = makeFrame('artifact thumbnail', { sandbox: 'allow-scripts allow-same-origin', src: `${ORIGIN}/api/evolve/agent/artifact/x/index.html` });
// A generated deliverable on its own loopback port: allowed to be same-origin
// to ITSELF, but it is not Thomas's origin, so it stays foreign.
const generated = makeFrame('generated page', { sandbox: 'allow-scripts allow-same-origin', src: 'http://127.0.0.1:49358/index.html' });

shell.relayFrames({ type: 'thomas:ui-edit:set', active: true });

for (const frame of [chatLive, chatBuild, buildShot, sealed, lookalike, generated]) {
  assert.equal(frame.received.length, 0, `${frame.label} has an opaque or foreign origin and must not be posted to`);
}
for (const frame of [workspace, embedded, thumbnail]) {
  assert.equal(frame.received.length, 1, `${frame.label} is ours and must still receive the relay`);
  assert.equal(frame.received[0].targetOrigin, ORIGIN, 'the target origin must stay Thomas, never "*"');
  assert.equal(frame.received[0].message.active, true);
}

// skipWindow still excludes the sender.
workspace.received.length = 0;
embedded.received.length = 0;
thumbnail.received.length = 0;
shell.relayFrames({ type: 'thomas:ui-edit:set', active: false }, embedded.contentWindow);
assert.equal(embedded.received.length, 0, 'the frame a message came from must not be echoed back to it');
assert.equal(workspace.received.length, 1);

// A frame that throws must not cost the frames after it their message. Before
// the per-frame guard, the uncaught throw abandoned the rest of the forEach.
const thrower = makeFrame('throws on post', {}, { throws: true });
const after = makeFrame('after the thrower', {});
assert.ok(frames.indexOf(thrower) < frames.indexOf(after), 'the throwing frame must come first for this to mean anything');
workspace.received.length = 0;
shell.relayFrames({ type: 'thomas:theme', theme: 'dark' });
assert.equal(after.received.length, 1, 'one refusing frame must not drop the rest of the fan-out');
assert.equal(workspace.received.length, 1);

// sendTheme is the same gate: it reports refusal instead of throwing.
assert.equal(shell.sendTheme(chatLive, 'dark', null), false, 'a sandboxed preview must not be themed');
assert.equal(chatLive.received.length, 0);
assert.equal(shell.sendTheme(thrower, 'dark', null), false, 'a frame that refuses the post reports false');
assert.equal(shell.sendTheme(workspace, 'dark', null), true);
assert.equal(workspace.received[1].message.type, 'thomas:theme');
// Dark travels under the old default's name: there are two looks now, and that name is where saved looks are filed.
assert.equal(workspace.received[1].message.theme, 'nebula');
assert.equal(shell.sendTheme(null, 'dark', null), false);

process.stdout.write('Shell frame relay skips opaque-origin previews and survives a refusal: passed\n');
