/* Thomas chat shell — assistant reply stream consumer (classic script, loaded by chat.html).
 *
 * /api/v2/chat has always streamed NDJSON, but the shell's reader lived inline
 * in chat.html (a file at its hard 3000-line ceiling), threw the whole reply
 * away when `res.body` was unavailable ("no stream body"), and painted the
 * bubble synchronously per event — fine when the server sent ONE text event
 * per reply, DOM thrash now that the server streams sentence-by-sentence
 * (thomas/marketplace/specialists/reasoning.py, 2026-08-06).
 *
 * This module owns TRANSPORT and PAINT CADENCE only. chat.html keeps the event
 * semantics (what 'text'/'thinking'/'tool_start' do to the shell) — the seam is
 * `consume(res, onEvent)` calling back per parsed event, exactly the contract
 * the inline loop had. Pure pieces take plain values so the node harness
 * (tests/web_node/chat_stream_consumer.mjs) drives them without a browser.
 *
 * Fallback honesty: when the response has no readable stream (an old browser,
 * a buffering proxy), the reply still WORKS — the full body is fetched and the
 * SAME events apply in the same order, one paint at the end. Nothing claims to
 * stream, nothing is dropped, and the return value says which path ran.
 */
(function () {
  'use strict';

  // Split an NDJSON buffer into parsed events plus the unfinished tail line.
  // Unparseable lines are skipped — the same tolerance the inline loop had.
  function parseNdjson(buffer) {
    var lines = String(buffer == null ? '' : buffer).split('\n');
    var rest = lines.pop();
    var events = [];
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line) continue;
      try { events.push(JSON.parse(line)); } catch (e) { /* skip non-JSON line */ }
    }
    return { events: events, rest: rest };
  }

  // Read a fetch Response's NDJSON, invoking onEvent per event AS CHUNKS
  // ARRIVE. Abort and network failures reject exactly like the old inline
  // loop, so the shell's stop/error handling is untouched. Resolves only when
  // the stream is fully consumed — the caller's finally (queue drain, busy
  // state) keeps its meaning.
  async function consume(res, onEvent) {
    var body = res && res.body;
    if (!body || typeof body.getReader !== 'function') {
      var whole = parseNdjson(String(await res.text()) + '\n');
      for (var i = 0; i < whole.events.length; i++) onEvent(whole.events[i]);
      return { streamed: false, events: whole.events.length };
    }
    var reader = body.getReader();
    var dec = new TextDecoder();
    var buf = '';
    var count = 0;
    while (true) {
      var step = await reader.read();
      if (step.done) break;
      buf += dec.decode(step.value, { stream: true });
      var part = parseNdjson(buf);
      buf = part.rest;
      for (var j = 0; j < part.events.length; j++) { count += 1; onEvent(part.events[j]); }
    }
    var tail = parseNdjson(buf + dec.decode() + '\n');
    for (var k = 0; k < tail.events.length; k++) { count += 1; onEvent(tail.events[k]); }
    return { streamed: true, events: count };
  }

  // Coalesce text paints to one per animation frame. At sentence cadence a
  // paint per event rebuilds the bubble's markdown DOM many times a second
  // for no visible gain; one paint per frame keeps the stream smooth and the
  // per-block markdown re-render (GFM tables included) flicker-free.
  // settle() paints the latest text NOW and cancels any queued frame — call
  // it on every exit path (stream end, stop, error) so the final bubble text
  // never waits on, or gets overwritten by, a stale queued frame.
  function createTextPainter(apply, schedule, cancel) {
    var raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : null;
    var caf = typeof cancelAnimationFrame === 'function' ? cancelAnimationFrame : null;
    var scheduleFrame = schedule || (raf ? function (fn) { return raf(fn); } : function (fn) { return setTimeout(fn, 16); });
    var cancelFrame = cancel || (caf ? function (h) { caf(h); } : function (h) { clearTimeout(h); });
    var latest = null;
    var handle = null;
    function flush() {
      handle = null;
      if (latest === null) return;
      var text = latest;
      latest = null;
      apply(text);
    }
    return {
      paint: function (text) {
        latest = String(text);
        if (handle === null) handle = scheduleFrame(flush);
      },
      settle: function () {
        if (handle !== null) { try { cancelFrame(handle); } catch (e) {} }
        flush();
      },
    };
  }

  window.ThomasChatStreamConsumer = {
    parseNdjson: parseNdjson,
    consume: consume,
    createTextPainter: createTextPainter,
  };
})();
