/* The composer's microphone: continuous Web Speech input that says in plain words why it cannot listen.
 * Moved out of chat_composer_panels.js (at its 800-line limit) when speech errors stopped being swallowed. */
"use strict";
(function () {
  function create(deps) {
    const { state, inputEl, autosize, syncDynamic } = deps;
    let recognition = null;
    // What the browser's own error codes mean, in words (they were swallowed, so a blocked microphone sat on "Listening…").
    const MIC_BLOCKED = "Microphone is blocked for this page. Allow it in the browser's address bar, then try again.";
    const MIC_MESSAGES = {
      'not-allowed': MIC_BLOCKED,
      'service-not-allowed': MIC_BLOCKED,
      'network': "The browser's speech service could not be reached.",
      'audio-capture': 'No microphone was found.',
    };
    function setupMic() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      const btn = document.getElementById('tc-mic-btn'); if (!btn) return;
      // One plain line just under the composer card; it exists only once there is something to say.
      let note = null, noteTimer = null;
      function say(text) {
        if (!note) {
          if (!text) return;
          note = document.createElement('p'); note.id = 'tc-mic-note';
          note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite');
          note.style.cssText = 'margin:8px 0 0;text-align:center;font-size:12.5px;line-height:1.4;font-family:inherit;color:var(--c-text);';
          const row = btn.parentElement, host = (row && row.parentElement) || row;
          if (host && host.parentNode) host.parentNode.insertBefore(note, host.nextSibling);
        }
        note.textContent = text || ''; note.style.display = text ? '' : 'none';
        if (noteTimer) { clearTimeout(noteTimer); noteTimer = null; }
        if (text) noteTimer = setTimeout(() => say(''), 15000);
      }
      if (!SR) {
        const none = 'Voice input is not supported in this browser.';
        btn.title = none; btn.style.opacity = '0.45'; btn.addEventListener('click', () => say(none)); return;
      }
      // Continuous listening: stays on through pauses, stops only after ~5s of
      // silence (or a manual click). No auto cut-off mid-sentence.
      recognition = new SR(); recognition.continuous = true; recognition.interimResults = true; recognition.lang = 'en-US';
      const SILENCE_MS = 5000;
      let base = '', finalChunk = '', silenceTimer = null, stopRequested = false;
      function micOn() { btn.style.color = 'var(--c-accent-ink)'; btn.style.background = 'var(--c-accent)'; btn.title = 'Listening… (stops after a pause)'; }
      function micOff() { btn.style.color = 'var(--c-dim)'; btn.style.background = 'transparent'; btn.title = 'Voice input'; }
      function resetSilence() { if (silenceTimer) clearTimeout(silenceTimer); silenceTimer = setTimeout(() => { silenceTimer = null; stopRequested = true; try { recognition.stop(); } catch (e) {} }, SILENCE_MS); }
      // A hard error ends listening for good: no restart, the button goes back, and the page says why.
      function giveUp(text) {
        stopRequested = true; state.listening = false;
        if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
        micOff(); if (text) say(text);
        try { recognition.abort(); } catch (e) {}
      }
      recognition.onresult = (e) => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) { const r = e.results[i]; if (r.isFinal) finalChunk += r[0].transcript; else interim += r[0].transcript; }
        const combined = ((base ? base + ' ' : '') + finalChunk + interim).replace(/\s+/g, ' ').replace(/^\s+/, '');
        state.input = combined; inputEl.value = combined; autosize(); syncDynamic();
        resetSilence();
      };
      // The silence clock starts when the microphone is really open, not at the click: a permission prompt can outlast it.
      recognition.onaudiostart = () => { if (!silenceTimer) resetSilence(); };
      recognition.onerror = (e) => {
        const code = e && e.error;
        if (code === 'aborted') return;
        if (code === 'no-speech') { giveUp(''); return; }
        giveUp(MIC_MESSAGES[code] || ('Voice input stopped (' + (code || 'unknown error') + ').'));
      };
      recognition.onend = () => {
        if (state.listening && !stopRequested) { try { recognition.start(); return; } catch (e) {} }
        state.listening = false; if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; } micOff();
      };
      btn.addEventListener('click', () => {
        if (state.listening) { stopRequested = true; try { recognition.stop(); } catch (e) {} return; }
        say(''); base = state.input.trim(); finalChunk = ''; stopRequested = false; state.listening = true; micOn();
        try { recognition.start(); } catch (e) { giveUp('Voice input could not start. Try again in a moment.'); }
      });
    }

    return { setupMic };
  }
  window.ThomasChatMic = { create: create };
})();
