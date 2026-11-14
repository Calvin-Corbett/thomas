/* Talk to Thomas: the ears and the mouth.
 *
 * Listening records with the microphone (sent to Voice Studio when it is running) and, where the browser has it, also
 * lets the browser's own speech recognition write down what it heard, as the backup. Speaking plays Voice Studio's
 * sound when it is running and the browser's own voice otherwise. Nothing here runs until a person presses the button.
 * Pure helpers are on window.ThomasVoiceSpeech for the node harness: cleanForSpeech, chunksOf.
 */
(function () {
  'use strict';

  var current = null; // the piece being played right now: { stop() }
  var session = null; // the reply being spoken: { cancelled }

  function cleanForSpeech(text) {
    return String(text || '')
      .replace(/```[\s\S]*?```/g, ' (code left out) ')
      .replace(/`([^`]*)`/g, '$1')
      .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/^\s{0,3}#{1,6}\s*/gm, '')
      .replace(/[*_>~|]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 3000);
  }

  // Short pieces, so the first words start quickly and the browser's long-sentence cut-off never bites.
  function chunksOf(text, size) {
    var limit = size || 400, parts = String(text || '').match(/[^.!?\n]+[.!?]*\s*/g) || [], out = [], line = '';
    parts.forEach(function (part) {
      if (line && (line + part).length > limit) { out.push(line.trim()); line = ''; }
      line += part;
    });
    if (line.trim()) out.push(line.trim());
    return out;
  }

  function listen(wantRecording) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var chunks = [], heard = '', recorder = null, stream = null, recognition = null, ended = null;
    var begin = wantRecording
      ? navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
        stream = s;
        recorder = new MediaRecorder(s);
        recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
        recorder.start();
      })
      : Promise.resolve();
    return begin.then(function () {
      if (SR) {
        recognition = new SR();
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = navigator.language || 'en-US';
        recognition.onresult = function (e) {
          for (var i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) heard += e.results[i][0].transcript + ' ';
        };
        recognition.onerror = function () { /* the recording, when there is one, is still enough */ };
        ended = new Promise(function (resolve) { recognition.onend = resolve; });
        try { recognition.start(); } catch (e) { recognition = null; }
      }
      if (!recorder && !recognition) throw new Error('This browser cannot listen, and Voice Studio is not running.');
      function release() { if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); }
      return {
        stop: function () {
          var stopped = recorder && recorder.state !== 'inactive'
            ? new Promise(function (resolve) { recorder.onstop = resolve; recorder.stop(); }) : Promise.resolve();
          if (recognition) { try { recognition.stop(); } catch (e) { /* already over */ } }
          var settle = recognition ? Promise.race([ended, new Promise(function (r) { setTimeout(r, 900); })]) : Promise.resolve();
          return Promise.all([stopped, settle]).then(function () {
            release();
            return { blob: chunks.length ? new Blob(chunks, { type: (recorder && recorder.mimeType) || 'audio/webm' }) : null, heard: heard.trim() };
          });
        },
        cancel: function () {
          if (recognition) { try { recognition.abort(); } catch (e) { /* already over */ } }
          if (recorder && recorder.state !== 'inactive') { try { recorder.stop(); } catch (e) { /* already over */ } }
          release();
        },
      };
    });
  }

  function transcribe(blob) {
    var form = new FormData();
    form.append('audio', blob, 'speech.webm');
    return fetch('/api/voice/transcribe', { method: 'POST', body: form }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) throw new Error(body.error || ('Voice Studio could not listen (' + res.status + ')'));
        return String(body.text || '').trim();
      });
    });
  }

  function fetchStudio(text, voice) {
    return fetch('/api/voice/speak', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text, voice: voice }),
    }).then(function (res) {
      if (!res.ok) return res.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.error || 'Voice Studio could not speak'); });
      return res.blob();
    });
  }

  function playBlob(blob) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(blob), audio = new Audio(url);
      function done() { URL.revokeObjectURL(url); resolve(); }
      audio.onended = done;
      audio.onerror = function () { URL.revokeObjectURL(url); reject(new Error('The sound could not be played')); };
      current = { stop: function () { audio.pause(); done(); } };
      audio.play().catch(reject);
    });
  }

  function playStudio(text, voice) { return fetchStudio(text, voice).then(playBlob); }

  function playBrowser(text, voiceName) {
    var synth = window.speechSynthesis;
    if (!synth || !window.SpeechSynthesisUtterance) return Promise.reject(new Error('This browser cannot speak.'));
    var voice = voiceName && voiceName !== 'default'
      ? (synth.getVoices() || []).filter(function (v) { return v.name === voiceName; })[0] : null;
    return new Promise(function (resolve) {
      var u = new window.SpeechSynthesisUtterance(text);
      if (voice) u.voice = voice;
      u.onend = resolve;
      u.onerror = resolve;
      current = { stop: function () { synth.cancel(); resolve(); } };
      synth.speak(u);
    });
  }

  // One piece at a time. Voice Studio's sound is tried first when it is the speaker and the browser's voice takes over
  // for the rest if it fails, so a reply is never silent. Returns how it was spoken: 'voicestudio' or 'browser'.
  function speak(text, status) {
    var pieces = chunksOf(cleanForSpeech(text)), settings = (status && status.settings) || {};
    var studio = status && status.speaker === 'voicestudio', how = studio ? 'voicestudio' : 'browser', mine = { cancelled: false };
    session = mine;
    function next(i) {
      if (mine.cancelled || i >= pieces.length) return Promise.resolve(how);
      var say = studio && how === 'voicestudio'
        ? playStudio(pieces[i], settings.voice).catch(function () { how = 'browser'; return playBrowser(pieces[i], settings.voice); })
        : playBrowser(pieces[i], settings.voice);
      return say.then(function () { return next(i + 1); });
    }
    return next(0).then(function (result) { if (session === mine) { session = null; current = null; } return result; });
  }

  // One piece made ready ahead of its turn: Voice Studio starts making the sound at once, so while one sentence plays the
  // next is already being made. play() uses the browser's voice when the sound cannot be made, so nothing goes silent.
  function prepare(text, status) {
    var settings = (status && status.settings) || {}, studio = !!(status && status.speaker === 'voicestudio');
    var made = studio ? fetchStudio(text, settings.voice).catch(function () { return null; }) : Promise.resolve(null);
    var stopped = false;
    return {
      play: function () {
        return made.then(function (blob) {
          if (stopped) return 'stopped';
          if (blob) return playBlob(blob).then(function () { return 'voicestudio'; });
          return playBrowser(text, studio ? 'default' : settings.voice).then(function () { return 'browser'; });
        });
      },
      stop: function () { stopped = true; },
    };
  }

  function stopSpeaking() {
    if (session) session.cancelled = true;
    if (current) current.stop();
    current = null;
  }

  window.ThomasVoiceSpeech = { listen: listen, transcribe: transcribe, speak: speak, prepare: prepare, stopSpeaking: stopSpeaking, cleanForSpeech: cleanForSpeech, chunksOf: chunksOf };
})();
