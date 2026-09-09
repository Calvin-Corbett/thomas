// The unified shell's chat reply must RENDER PROGRESSIVELY as the server
// streams it, and still render (buffered, honestly) when it cannot stream.
//
// Measured 2026-08-05: every /api/v2/chat reply painted ONCE after a silent
// typing-dots wait. The server half of the fix streams sentences
// (thomas/marketplace/specialists/reasoning.py); this harness drives the
// CLIENT half — js/chat_stream_consumer.js — in a vm, plus the chat.html
// wiring that loads it:
//
//   1. wiring — chat.html loads the module, streamReal consumes through it,
//      the old inline reader (and its "no stream body" hard failure) is gone,
//      and the queued-message drain still fires on completion;
//   2. behavior — NDJSON frames split across arbitrary chunk boundaries parse
//      in order; a partial frame renders BEFORE the stream closes (the actual
//      "streaming" claim); the painter coalesces to one paint per frame and
//      settle() applies the final text; an abort mid-stream rejects (so the
//      shell's catch/finally — stop note, queue drain — still runs); a
//      response with NO readable body falls back to the buffered text and
//      applies the same events in the same order.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
const modulePath = process.argv[3];
if (!htmlPath || !modulePath) throw new Error('usage: node chat_stream_consumer.mjs <chat.html> <chat_stream_consumer.js>');
const html = fs.readFileSync(htmlPath, 'utf8');
const moduleSource = fs.readFileSync(modulePath, 'utf8');

const checks = {};

// ---- 1. chat.html wiring ----
checks.moduleScriptTagPresent = html.includes('/static/js/chat_stream_consumer.js');

const streamStart = html.indexOf('async function streamReal(');
const streamEnd = html.indexOf('\n    function newChat(', streamStart);
if (streamStart < 0 || streamEnd < 0) throw new Error('could not extract streamReal from chat.html');
const streamSource = html.slice(streamStart, streamEnd);

checks.streamRealConsumesThroughModule = streamSource.includes('ThomasChatStreamConsumer.consume(');
checks.streamRealPaintsThroughPainter = streamSource.includes('createTextPainter') && streamSource.includes('painter.paint(acc)');
checks.streamRealSettlesFinalText = (streamSource.match(/painter\.settle\(\)/g) || []).length >= 2; // stream end AND error path
// The replaced inline reader must be GONE, including its hard failure on a
// response without a readable stream (the fallback now handles that).
checks.inlineReaderDeleted = !streamSource.includes('res.body.getReader');
checks.noStreamBodyFailureDeleted = !streamSource.includes('no stream body');
// Completion still drains the mid-reply queue (chat_v2_send_durability's
// client contract: a message queued during the reply sends when it finishes).
checks.streamCompletionStillDrains = streamSource.includes('drainQueued');

// ---- 2. module behavior in a vm ----
const context = { window: {}, console, TextDecoder, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(moduleSource, context);
const mod = context.window.ThomasChatStreamConsumer;
checks.moduleExports = Boolean(mod) && typeof mod.parseNdjson === 'function'
  && typeof mod.consume === 'function' && typeof mod.createTextPainter === 'function';

// parseNdjson: frames split anywhere, junk skipped, tail preserved.
const p1 = mod.parseNdjson('{"type":"text","text":"a"}\n{"type":"te');
checks.parseSplitsFrames = p1.events.length === 1 && p1.events[0].text === 'a' && p1.rest === '{"type":"te';
const p2 = mod.parseNdjson('not json\n\r\n{"type":"done"}\npartial');
checks.parseSkipsJunkAndBlankLines = p2.events.length === 1 && p2.events[0].type === 'done' && p2.rest === 'partial';

// A controllable fake streaming response: the test pushes encoded chunks and
// decides when the stream closes — so "rendered before close" is structural.
function streamingRes(pushes) {
  const encoder = new TextEncoder();
  let waiting = null;
  const queue = [];
  const res = {
    ok: true,
    body: {
      getReader() {
        return {
          read() {
            if (queue.length) return Promise.resolve(queue.shift());
            return new Promise((resolve, reject) => { waiting = { resolve, reject }; });
          },
        };
      },
    },
  };
  pushes.feed = (text) => {
    const step = { done: false, value: encoder.encode(text) };
    if (waiting) { waiting.resolve(step); waiting = null; } else queue.push(step);
  };
  pushes.close = () => {
    const step = { done: true, value: undefined };
    if (waiting) { waiting.resolve(step); waiting = null; } else queue.push(step);
  };
  pushes.fail = (err) => {
    if (waiting) { waiting.reject(err); waiting = null; } else queue.push(Promise.reject(err));
  };
  return res;
}

const microtasks = () => new Promise((resolve) => setTimeout(resolve, 0));

// Partial frames render before the stream closes; split frames reassemble.
{
  const pushes = {};
  const res = streamingRes(pushes);
  const seen = [];
  const done = mod.consume(res, (evt) => seen.push(evt));
  pushes.feed('{"type":"text","text":"First sentence. "}\n{"type":"text","te');
  await microtasks();
  checks.partialFrameAppliedBeforeClose = seen.length === 1 && seen[0].text === 'First sentence. ';
  pushes.feed('xt":"Second half."}\n');
  await microtasks();
  checks.splitFrameReassembled = seen.length === 2 && seen[1].text === 'Second half.';
  pushes.feed('{"type":"done"}'); // no trailing newline — the tail flush must catch it
  pushes.close();
  const result = await done;
  checks.tailFrameWithoutNewlineApplied = seen.length === 3 && seen[2].type === 'done';
  checks.streamedPathReports = result.streamed === true && result.events === 3;
}

// An abort mid-stream rejects out of consume — the shell's catch/finally
// (stop note, busy reset, queue drain) depends on that propagation.
{
  const pushes = {};
  const res = streamingRes(pushes);
  const done = mod.consume(res, () => {});
  const abortErr = Object.assign(new Error('The user pressed stop'), { name: 'AbortError' });
  pushes.fail(abortErr);
  let rejected = null;
  try { await done; } catch (err) { rejected = err; }
  checks.abortRejectsOutOfConsume = rejected === abortErr;
}

// No readable body → the buffered fallback still applies every event, in order.
{
  const res = {
    ok: true,
    body: undefined,
    text: async () => '{"type":"text","text":"whole "}\n{"type":"text","text":"reply"}\n{"type":"done"}',
  };
  const seen = [];
  const result = await mod.consume(res, (evt) => seen.push(evt));
  checks.bufferedFallbackStillRenders = seen.length === 3
    && seen[0].text === 'whole ' && seen[1].text === 'reply' && seen[2].type === 'done'
    && result.streamed === false;
}

// Painter: many paints in one frame → ONE apply with the LATEST text; settle
// cancels the queued frame and applies immediately; nothing applies twice.
{
  const frames = [];
  const applied = [];
  const painter = mod.createTextPainter(
    (t) => applied.push(t),
    (fn) => { frames.push(fn); return frames.length - 1; },
    (h) => { frames[h] = null; },
  );
  painter.paint('T');
  painter.paint('Th');
  painter.paint('The full sentence.');
  checks.paintCoalescesWithinFrame = applied.length === 0 && frames.filter(Boolean).length === 1;
  frames[0](); // the frame fires
  checks.paintAppliesLatestOnce = applied.length === 1 && applied[0] === 'The full sentence.';
  painter.paint('The full sentence. And more.');
  painter.settle();
  checks.settleAppliesImmediately = applied.length === 2 && applied[1] === 'The full sentence. And more.';
  const before = applied.length;
  for (const fn of frames) if (fn) fn();
  painter.settle();
  checks.settleNeverDoubleApplies = applied.length === before;
}

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`chat stream consumer checks failed: ${failures.join(', ')}`);
assert.ok(true);
process.stdout.write(`${JSON.stringify(checks)}\n`);
