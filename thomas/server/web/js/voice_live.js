/* Live talk with Thomas: the microphone stays open, he answers as soon as you pause, and he talks back while he writes.
 *
 * Ears: the microphone's sound, 16 kHz 16-bit, goes over the /api/voice/live websocket to Thomas's own speech model (or
 * Voice Studio's when Thomas's is not installed), which sends back the words while you speak ("partial") and once each
 * time you pause ("final"). When neither can listen the browser's own speech recognition listens instead. The browser's echo cancelling is on, so Thomas does not hear himself.
 * Brain: each pause sends what you said through the ordinary send button, with the smallest and fastest model.
 * Mouth: the reply is read aloud a sentence at a time while it is still being written; the next sentence's sound is made
 * while the one before it plays. Start talking while he speaks and he stops; talk while he is still thinking and that
 * turn is stopped and your new words are sent instead.
 *
 * window.ThomasVoiceLive = { start(hooks), stop(), running(), cutPoint, replyText }
 * hooks: status, onState(state), onPartial(text), onLevel(0..1), onError(message, kind).
 */
(function () {
  'use strict';

  var RATE = 16000, FRAME = 1600; // 100 ms of sound per websocket message
  var WORKLET = "class P extends AudioWorkletProcessor{process(i){var c=i[0]&&i[0][0];if(c)this.port.postMessage(c.slice(0));return true}}"
    + "registerProcessor('tc-voice-pcm',P)";

  var live = null; // the running session

  function speech() { return window.ThomasVoiceSpeech; }
  function modes() { return window.ThomasUnifiedModes; }
  function mode() { return modes() && modes().mode ? modes().mode() : 'chat'; }
  function busy(which) { return !!(modes() && modes().isBusy(which)); }
  function plain(text) { return String(text || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim(); }

  function replyNodes(which, doc) {
    var scope = doc || document;
    return which === 'code'
      ? scope.querySelectorAll('.tc-code-transcript .tc-code-reply:not(.is-error)')
      : scope.querySelectorAll('#tc-thread .tc-bubble.tc-markdown');
  }

  // The words of a reply as a person would read them: code blocks are left out, Build's reply head (Thomas, Copy) too.
  function replyText(node) {
    if (!node) return '';
    var copy = (node.querySelector('.tc-code-reply-text') || node).cloneNode(true);
    copy.querySelectorAll('pre').forEach(function (el) { el.replaceWith(' (code left out) '); });
    copy.querySelectorAll('.tc-code-reply-head, button').forEach(function (el) { el.remove(); });
    return String(copy.innerText || copy.textContent || '').replace(/\s+/g, ' ').trim();
  }

  // How much of the unread reply can be said now: up to the end of its last whole sentence. The very first piece may stop
  // at a comma once it is long enough, so Thomas starts talking sooner. With the reply finished, all of it.
  function cutPoint(rest, first, done) {
    if (done) return rest.length;
    var end = 0, found, sentence = /[.!?]["')\]]*(?=\s)/g;
    while ((found = sentence.exec(rest))) end = found.index + found[0].length;
    if (!end && first) {
      var comma = rest.search(/[,;:](?=\s)/);
      if (comma >= 24) end = comma + 1;
    }
    return end;
  }

  /* ---------- the mouth: pieces said one after another, each made ready ahead of its turn ---------- */
  function Mouth(session) {
    var queue = [], playing = null, gen = 0, heard = '';
    function next() {
      var piece = queue.shift();
      if (!piece) { playing = null; session.changed(); return; }
      playing = piece;
      session.changed();
      var mine = gen;
      piece.play().catch(function () { /* one piece that would not play is skipped */ }).then(function () {
        if (mine === gen) next();
      });
    }
    return {
      say: function (text) {
        heard = (heard + ' ' + text).slice(-600);
        queue.push(speech().prepare(text, session.status));
        if (!playing) next();
      },
      hush: function () {
        gen++;
        queue.forEach(function (piece) { piece.stop(); });
        queue = [];
        if (playing) playing.stop();
        playing = null;
        speech().stopSpeaking();
        session.changed();
      },
      talking: function () { return !!playing || queue.length > 0; },
      // True when what the microphone picked up is Thomas's own last words coming back from the speakers.
      echo: function (text) { var said = plain(heard), got = plain(text); return got.length > 3 && said.indexOf(got) !== -1; },
    };
  }

  /* ---------- the ears: Voice Studio over the websocket, or the browser's own recognition ---------- */
  function studioEars(hooks) {
    var socket = null, stream = null, context = null, frames = [], closed = false;
    function stop() {
      closed = true;
      if (socket && socket.readyState <= 1) {
        try { socket.send(JSON.stringify({ type: 'input_audio.end' })); } catch (e) { /* already gone */ }
        socket.close();
      }
      if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
      if (context) context.close().catch(function () { /* already closed */ });
    }
    function send(samples) {
      var sum = 0;
      for (var i = 0; i < samples.length; i++) { frames.push(samples[i]); sum += samples[i] * samples[i]; }
      hooks.onLevel(Math.min(1, Math.sqrt(sum / Math.max(1, samples.length)) * 6));
      while (frames.length >= FRAME) {
        var chunk = frames.splice(0, FRAME), pcm = new Int16Array(FRAME);
        for (var k = 0; k < FRAME; k++) pcm[k] = Math.max(-1, Math.min(1, chunk[k])) * 0x7fff;
        if (socket && socket.readyState === 1) socket.send(pcm.buffer);
      }
    }
    var ready = new Promise(function (resolve, reject) {
      var scheme = location.protocol === 'https:' ? 'wss://' : 'ws://', started = false;
      socket = new WebSocket(scheme + location.host + '/api/voice/live');
      socket.binaryType = 'arraybuffer';
      socket.onmessage = function (message) {
        var event = {};
        try { event = JSON.parse(message.data); } catch (e) { return; }
        if (event.type === 'live.started') { started = true; resolve(); }
        else if (event.type === 'error') {
          if (!started) reject(Object.assign(new Error(event.message || 'Voice Studio could not listen'), { kind: event.kind }));
          else hooks.onError(event.message || 'Voice Studio could not listen', event.kind);
        } else if (event.type === 'partial') hooks.onHeard(String(event.text || ''), false);
        else if (event.type === 'final' && event.final_kind !== 'summary') hooks.onHeard(String(event.text || ''), true);
      };
      socket.onclose = function () {
        if (!started) reject(new Error('Voice Studio closed the line'));
        else if (!closed) hooks.onError('Voice Studio stopped listening.', 'studio_gone');
      };
    });
    return ready.then(function () {
      return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    }).then(function (mic) {
      stream = mic;
      context = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: RATE });
      var url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      return context.audioWorklet.addModule(url).then(function () {
        URL.revokeObjectURL(url);
        var source = context.createMediaStreamSource(mic), node = new AudioWorkletNode(context, 'tc-voice-pcm'), mute = context.createGain();
        mute.gain.value = 0;
        node.port.onmessage = function (e) { if (!closed) send(e.data); };
        source.connect(node);
        node.connect(mute);
        mute.connect(context.destination);
        return { stop: stop, kind: 'voicestudio' };
      });
    }).catch(function (error) { stop(); throw error; });
  }

  function browserEars(hooks) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return Promise.reject(new Error('This browser cannot listen, and Voice Studio has no live listening model ready.'));
    var recognition = new SR(), on = true;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || 'en-US';
    recognition.onresult = function (e) {
      for (var i = e.resultIndex; i < e.results.length; i++) hooks.onHeard(e.results[i][0].transcript, !!e.results[i].isFinal);
    };
    recognition.onerror = function (e) {
      var code = e && e.error;
      if (code === 'no-speech' || code === 'aborted') return;
      on = false;
      hooks.onError(code === 'not-allowed' || code === 'service-not-allowed'
        ? 'Thomas cannot use the microphone. Allow it for this page, then turn live talk on again.'
        : 'This browser could not listen (' + (code || 'unknown') + ').', code);
    };
    recognition.onend = function () { if (on) { try { recognition.start(); } catch (e) { /* starting again */ } } };
    recognition.start();
    return Promise.resolve({
      stop: function () { on = false; try { recognition.abort(); } catch (e) { /* already over */ } },
      kind: 'browser',
    });
  }

  /* ---------- the session: hearing, sending and speaking, turn after turn ---------- */
  function start(hooks) {
    if (live) return Promise.resolve(live);
    var session = {
      hooks: hooks, status: hooks.status, ears: null, mouth: null, turn: null, waiting: [], stopped: false, which: mode(),
      changed: function () { if (!session.stopped) hooks.onState(session.state()); },
      state: function () {
        if (session.mouth && session.mouth.talking()) return 'speaking';
        if (session.turn) return 'thinking';
        return 'listening';
      },
    };
    session.mouth = Mouth(session);
    live = session;

    function lost(message, kind) { if (!session.stopped) { stop(); hooks.onError(message, kind); } }

    function heard(text, final) {
      if (session.stopped) return;
      var words = plain(text).split(' ').filter(Boolean);
      if (!words.length || session.mouth.echo(text)) return;
      // Talking over Thomas stops him at once; two words, so a cough or a click does not.
      if (session.mouth.talking() && (final || words.length >= 2)) session.mouth.hush();
      hooks.onPartial(final ? '' : text);
      if (!final) return;
      session.waiting.push(String(text).trim());
      if (session.turn) { session.turn.cancel(); return; } // the new words go once the old turn has stopped
      void nextTurn();
    }

    function nextTurn() {
      if (session.stopped || session.turn || !session.waiting.length) return Promise.resolve();
      var text = session.waiting.join(' ');
      session.waiting = [];
      return runTurn(session, text).then(function () { session.turn = null; session.changed(); return nextTurn(); });
    }

    // Whoever the server says can listen live (Thomas himself first, Voice Studio otherwise) gets the microphone.
    var listensLive = session.status && session.status.live && session.status.live.model;
    var opened = listensLive
      ? studioEars({ onHeard: heard, onLevel: hooks.onLevel, onError: lost }).catch(function (error) {
        if (error && error.name === 'NotAllowedError') throw error;
        return browserEars({ onHeard: heard, onError: lost }); // live listening failed: the browser's ears instead
      })
      : browserEars({ onHeard: heard, onError: lost });

    return opened.then(function (ears) {
      if (session.stopped) { ears.stop(); return session; }
      session.ears = ears;
      session.changed();
      return session;
    }, function (error) { stop(); throw error; });
  }

  function runTurn(session, text) {
    var which = session.which, input = document.getElementById('tc-input'), send = document.getElementById('tc-send');
    var picker = window.ThomasModelSelection, model = session.status && session.status.fast_model, before = null, swapped = false;
    var turn = { cancelled: false, cancel: function () { turn.cancelled = true; if (busy(which) && modes().stop) modes().stop(); } };
    session.turn = turn;
    session.changed();
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (model && picker) {
      before = picker.current();
      if (before.profile !== model.profile || String(before.modelId) !== String(model.id)) swapped = !!picker.select(model.profile, model.id);
    }
    var already = replyNodes(which).length;
    send.click(); // the ordinary send path: it reads the model, the mode and the attachments at this moment
    if (swapped) picker.select(before.profile, before.modelId);
    var said = 0, began = Date.now(), seen = false;
    return new Promise(function (resolve) {
      (function look() {
        if (session.stopped) return resolve();
        var running = busy(which);
        seen = seen || running;
        if (!seen && Date.now() - began > 4000) {
          session.hooks.onError('Thomas could not send that. Your words are in the message box.', 'not_sent');
          return resolve();
        }
        var nodes = replyNodes(which), done = seen && !running;
        if (!turn.cancelled && nodes.length > already) {
          var reply = speech().cleanForSpeech(replyText(nodes[nodes.length - 1])), rest = reply.slice(said);
          var cut = cutPoint(rest, said === 0, done);
          if (cut > 0) { var piece = rest.slice(0, cut).trim(); said += cut; if (piece) session.mouth.say(piece); }
        }
        if (done || (turn.cancelled && !running)) return resolve();
        setTimeout(look, seen ? 120 : 20);
      })();
    });
  }

  function stop() {
    var session = live;
    live = null;
    if (!session) return;
    session.stopped = true;
    if (session.ears) session.ears.stop();
    session.mouth.hush();
    if (session.turn) session.turn.cancelled = true;
  }

  window.ThomasVoiceLive = {
    start: start,
    stop: stop,
    running: function () { return !!live; },
    session: function () { return live; },
    cutPoint: cutPoint,
    replyText: replyText,
  };
})();
