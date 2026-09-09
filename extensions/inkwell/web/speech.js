/* Inkwell speech-to-text: browser SpeechRecognition into the page. */
(function () {
  'use strict';
  const IW = window.IW;

  let recognition = null;
  let listening = false;
  let micBtn;
  let silenceTimer = null;

  // The mic switches itself off after a stretch of silence (configurable).
  function armSilenceTimer() {
    clearTimeout(silenceTimer);
    const seconds = Number(IW.settings.mic_silence_s) || 8;
    silenceTimer = setTimeout(() => {
      if (listening) {
        stop();
        IW.toast('Mic off — heard nothing for ' + seconds + 's.');
      }
    }, seconds * 1000);
  }

  function supported() {
    return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  function build() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = navigator.language || 'en-US';
    rec.onresult = (event) => {
      armSilenceTimer();
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) IW.appendDictation(result[0].transcript);
      }
    };
    rec.onspeechstart = armSilenceTimer;
    rec.onerror = (event) => {
      if (event.error === 'not-allowed') {
        IW.toast('Microphone blocked — allow mic access to dictate.', 'warn');
        stop();
      } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
        IW.toast('Speech recognition hiccup: ' + event.error, 'warn');
      }
    };
    rec.onend = () => {
      // Chrome stops after silence; restart while the mic toggle is on.
      if (listening) {
        try { rec.start(); } catch (e) { /* already starting */ }
      }
    };
    return rec;
  }

  function start() {
    if (!supported()) {
      IW.toast('This browser has no speech recognition — try the desktop app or Chrome.', 'warn');
      return;
    }
    if (!recognition) recognition = build();
    try { recognition.start(); } catch (e) { /* already running */ }
    listening = true;
    armSilenceTimer();
    micBtn.classList.add('iw-mic-live');
    micBtn.textContent = '🎙 Listening…';
    IW.toast('Listening — talk, and it lands on the page.');
  }

  function stop() {
    listening = false;
    clearTimeout(silenceTimer);
    if (recognition) { try { recognition.stop(); } catch (e) { /* fine */ } }
    micBtn.classList.remove('iw-mic-live');
    micBtn.textContent = '🎙 Speak';
  }

  IW.initSpeech = function () {
    micBtn = document.getElementById('micBtn');
    micBtn.addEventListener('click', () => (listening ? stop() : start()));
  };
})();
