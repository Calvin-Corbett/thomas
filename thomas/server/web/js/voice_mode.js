/* Live talk: the microphone that becomes a switch.
 *
 * Booting asks GET /api/voice/status once. Anything but 200 (the plugin is off, or the server is old) draws nothing and
 * asks nothing more, and the microphone stays exactly as it was. Otherwise nothing new shows until you rest the pointer
 * on the microphone: a ring fills around it, and after HOLD_MS it stretches into a slider with the microphone as its knob
 * and a speaker waiting at the far end. Clicking the slider sends the knob across, the microphone turns into a speaker,
 * and live talk is on: speak, pause, and Thomas answers out loud (voice_live.js does the talking). Click it again and
 * the knob slides back. Leave the slider alone without turning it on and it folds back. A click on the microphone with
 * no rest first still types what you say, as before. Right-clicking the slider, or the voice's name in the line under
 * the message box, opens the voice choices.
 */
(function () {
  'use strict';

  var HOLD_MS = 1400, FOLD_MS = 900;
  var MIC = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">'
    + '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  var SPEAKER = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path class="tc-vw1" d="M15.5 9.2a4 4 0 0 1 0 5.6"/><path class="tc-vw2" d="M18.3 6.6a7.6 7.6 0 0 1 0 10.8"/></svg>';
  var STYLE = [
    '#tc-voice-dock{position:relative;display:inline-flex;justify-content:flex-end;width:36px;height:36px;flex:none;transition:width .32s cubic-bezier(.3,1.3,.5,1)}',
    '#tc-shell[data-surface-mode="code"] #tc-voice-dock{width:32px;height:32px}',
    '#tc-voice-dock[data-open="true"]{width:84px}',
    '#tc-voice-dock #tc-mic-btn{position:relative;z-index:1;transition:opacity .15s}',
    '#tc-voice-dock[data-open="true"] #tc-mic-btn{opacity:0;pointer-events:none}', // the themes' surfaces are see-through
    '#tc-voice-dock::before{content:"";position:absolute;right:-3px;top:-3px;width:calc(100% + 6px);max-width:42px;height:calc(100% + 6px);border-radius:13px;pointer-events:none;',
    '  background:conic-gradient(var(--c-accent) calc(var(--tc-hold,0) * 1turn),transparent 0);opacity:.6;',
    '  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 2px),#000 0);mask:radial-gradient(farthest-side,transparent calc(100% - 2px),#000 0)}',
    '#tc-voice-dock[data-open="true"]::before{opacity:0}',
    '#tc-voice-btn{all:unset;box-sizing:border-box;position:absolute;inset:0;z-index:2;border-radius:999px;cursor:pointer;opacity:0;pointer-events:none;',
    '  border:1px solid var(--c-border-2,var(--c-border));background:var(--c-surface-2,var(--c-surface));transition:opacity .2s,background .3s,border-color .3s}',
    '#tc-voice-btn[hidden]{display:none}',
    '#tc-voice-dock[data-open="true"] #tc-voice-btn{opacity:1;pointer-events:auto}',
    '#tc-voice-btn:focus-visible{outline:2px solid var(--c-accent);outline-offset:2px}',
    '#tc-voice-btn .tc-vend{position:absolute;right:10px;top:50%;transform:translateY(-50%);color:var(--c-muted);opacity:.55;display:grid;transition:opacity .2s}',
    '#tc-voice-btn .tc-vknob{position:absolute;left:3px;top:3px;bottom:3px;aspect-ratio:1;border-radius:999px;display:grid;place-items:center;',
    '  background:color-mix(in srgb,var(--c-text,#eee) 92%,var(--c-accent,#888));color:var(--c-bg,#111);box-shadow:0 1px 3px rgba(0,0,0,.35);',
    '  transition:transform .38s cubic-bezier(.3,1.4,.5,1),color .3s,box-shadow .12s}',
    '#tc-voice-btn .tc-vknob>span{grid-area:1/1;display:grid;transition:opacity .22s,transform .3s}',
    '#tc-voice-btn .tc-vk-speaker{opacity:0;transform:scale(.6) rotate(-20deg)}',
    '#tc-voice-btn[aria-checked="true"]{background:var(--c-accent);border-color:var(--c-accent)}',
    '#tc-voice-btn[aria-checked="true"] .tc-vend{opacity:0}',
    '#tc-voice-btn[aria-checked="true"] .tc-vknob{transform:translateX(48px);color:var(--c-accent);',
    '  box-shadow:0 0 0 calc(var(--tc-level,0) * 7px) color-mix(in srgb,var(--c-accent) 35%,transparent),0 1px 3px rgba(0,0,0,.25)}',
    '#tc-shell[data-surface-mode="code"] #tc-voice-btn[aria-checked="true"] .tc-vknob{transform:translateX(52px)}',
    '#tc-voice-btn[aria-checked="true"] .tc-vk-mic{opacity:0;transform:scale(.6) rotate(20deg)}',
    '#tc-voice-btn[aria-checked="true"] .tc-vk-speaker{opacity:1;transform:none}',
    '#tc-voice-btn[data-voice-state="speaking"] .tc-vw1{animation:tc-vwave 1s ease-in-out infinite}',
    '#tc-voice-btn[data-voice-state="speaking"] .tc-vw2{animation:tc-vwave 1s ease-in-out .18s infinite}',
    '#tc-voice-btn[data-voice-state="thinking"] .tc-vknob{animation:tc-vthink 1.1s ease-in-out infinite}',
    '@keyframes tc-vwave{0%,100%{opacity:.25}50%{opacity:1}}',
    '@keyframes tc-vthink{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--c-accent) 40%,transparent)}50%{box-shadow:0 0 0 6px transparent}}',
    '@media (prefers-reduced-motion:reduce){#tc-voice-dock,#tc-voice-btn .tc-vknob,#tc-voice-btn .tc-vknob>span{transition:none}',
    '  #tc-voice-btn .tc-vw1,#tc-voice-btn .tc-vw2,#tc-voice-btn .tc-vknob{animation:none!important}}',
    // The line takes the place of the note under the message box ("Thomas can make mistakes...") at exactly its size,
    // so turning live talk on never moves the message box: it moved up by a line's height before.
    '#tc-voice-line{margin:9px 0 0;height:18.4px;line-height:18.4px;text-align:center;font-size:12.5px;color:var(--c-dim);'
      + 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '#tc-composer-rail:has(#tc-voice-line:not([hidden])) .tc-composer-note{display:none}',
    '#tc-voice-line[hidden]{display:none}#tc-voice-line q{color:var(--c-text);font-style:italic}',
    '#tc-voice-line button{all:unset;cursor:pointer;color:var(--c-accent);text-decoration:underline dotted;text-underline-offset:3px}',
    '#tc-voice-panel{position:fixed;z-index:80;width:min(320px,calc(100vw - 24px));padding:12px;border-radius:14px;',
    '  background:var(--c-menu-bg,var(--c-surface));border:1px solid var(--c-border-2);box-shadow:var(--c-shadow);',
    '  color:var(--c-text);font:13px var(--font-sans);display:flex;flex-direction:column;gap:8px}',
    '#tc-voice-panel[hidden]{display:none}#tc-voice-panel select{width:100%;padding:6px;border-radius:8px;',
    '  background:var(--c-surface);color:var(--c-text);border:1px solid var(--c-border)}',
    '#tc-voice-panel .tc-voice-note{color:var(--c-dim)}',
    // The set-up window: in the middle of the screen, over a dimmed page, the first time live talk needs it.
    '#tc-voice-setup{position:fixed;inset:0;z-index:200;display:grid;place-items:center;padding:16px;background:rgba(0,0,0,.45)}',
    '#tc-voice-setup .tc-vs-card{box-sizing:border-box;width:min(440px,100%);padding:22px;border-radius:16px;display:flex;flex-direction:column;gap:10px;',
    '  background:var(--c-menu-bg,var(--c-surface));color:var(--c-text);border:1px solid var(--c-border-2,var(--c-border));',
    '  box-shadow:var(--c-shadow);font:14px/1.5 var(--font-sans)}',
    '#tc-voice-setup h2{margin:0;font-size:17px;font-weight:600}#tc-voice-setup p{margin:0}',
    '#tc-voice-setup .tc-vs-small{color:var(--c-dim);font-size:12px}#tc-voice-setup .tc-vs-status:empty{display:none}',
    '#tc-voice-setup .tc-vs-bar{height:6px;border-radius:99px;overflow:hidden;background:var(--c-surface-2,var(--c-border))}',
    '#tc-voice-setup .tc-vs-bar[hidden]{display:none}',
    '#tc-voice-setup .tc-vs-bar span{display:block;height:100%;width:0;background:var(--c-accent);transition:width .3s}',
    '#tc-voice-setup .tc-vs-buttons{display:flex;justify-content:flex-end;gap:8px;margin-top:6px}',
    '#tc-voice-setup button{cursor:pointer;padding:8px 14px;border-radius:10px;font:inherit;background:transparent;color:var(--c-text);',
    '  border:1px solid var(--c-border-2,var(--c-border))}',
    '#tc-voice-setup .tc-vs-now{background:var(--c-accent);border-color:var(--c-accent);color:var(--c-on-accent,#fff)}',
    '#tc-voice-setup button[disabled]{opacity:.5;cursor:default}#tc-voice-setup button:focus-visible{outline:2px solid var(--c-accent);outline-offset:2px}',
  ].join('');
  var SAYING = {
    listening: 'Listening. Just talk, and pause when you are done.',
    thinking: 'Thomas is answering.',
    speaking: 'Thomas is talking. Start talking to cut in.',
  };

  var status = null, dock = null, btn = null, mic = null, line = null, panel = null, opened = false;
  var holdTimer = 0, holdStart = 0, holdFrame = 0, foldTimer = 0, noteTimer = 0, starting = false;

  function live() { return window.ThomasVoiceLive; }
  function mode() { return window.ThomasUnifiedModes && window.ThomasUnifiedModes.mode ? window.ThomasUnifiedModes.mode() : 'chat'; }
  function on() { return !!(btn && btn.getAttribute('aria-checked') === 'true'); }

  function load(url, init) {
    return fetch(url, Object.assign({ cache: 'no-store' }, init || {})).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) { return { ok: res.ok, status: res.status, body: body }; });
    }, function () { return { ok: false, status: 0, body: {} }; });
  }

  /* ---------- the slider ---------- */
  function setOpen(next) {
    if (!dock) return;
    dock.dataset.open = next ? 'true' : 'false';
    btn.tabIndex = next ? 0 : -1;
    if (!next) dock.style.setProperty('--tc-hold', '0');
  }

  function cancelHold() {
    clearTimeout(holdTimer);
    cancelAnimationFrame(holdFrame);
    holdTimer = 0;
    if (dock) dock.style.setProperty('--tc-hold', '0');
  }

  function beginHold() {
    if (!dock || btn.hidden || dock.dataset.open === 'true' || holdTimer) return;
    holdStart = performance.now();
    (function fill() {
      var part = Math.min(1, (performance.now() - holdStart) / HOLD_MS);
      dock.style.setProperty('--tc-hold', String(part));
      if (part < 1) holdFrame = requestAnimationFrame(fill);
    })();
    holdTimer = setTimeout(function () { holdTimer = 0; setOpen(true); }, HOLD_MS);
  }

  function leave() {
    cancelHold();
    clearTimeout(foldTimer);
    if (!on() && !opened) foldTimer = setTimeout(function () { if (!on()) setOpen(false); }, FOLD_MS);
  }

  function setLevel(level) { if (btn) btn.style.setProperty('--tc-level', String(Math.round(level * 100) / 100)); }

  function setState(next) {
    if (!btn) return;
    btn.dataset.voiceState = next;
    btn.title = next === 'off' ? 'Turn on live talk' : 'Live talk is on. Click to turn it off.';
    if (next !== 'listening') setLevel(0);
    say(next === 'off' ? '' : SAYING[next] || '');
  }

  function build() {
    mic = document.getElementById('tc-mic-btn');
    if (!mic || dock) return;
    var style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);
    dock = document.createElement('span');
    dock.id = 'tc-voice-dock';
    dock.dataset.open = 'false';
    mic.parentNode.insertBefore(dock, mic);
    dock.appendChild(mic);
    btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'tc-voice-btn';
    btn.setAttribute('role', 'switch');
    btn.setAttribute('aria-checked', 'false');
    btn.setAttribute('aria-label', 'Live talk with Thomas');
    btn.tabIndex = -1;
    btn.dataset.voiceState = 'off';
    btn.title = 'Turn on live talk';
    btn.innerHTML = '<span class="tc-vend">' + SPEAKER + '</span><span class="tc-vknob"><span class="tc-vk-mic">' + MIC
      + '</span><span class="tc-vk-speaker">' + SPEAKER + '</span></span>';
    dock.appendChild(btn);
    line = document.createElement('p');
    line.id = 'tc-voice-line';
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    line.hidden = true;
    var row = dock.parentElement, host = (row && row.parentElement) || row;
    if (host && host.parentNode) host.parentNode.insertBefore(line, host.nextSibling);
    panel = document.createElement('div');
    panel.id = 'tc-voice-panel';
    panel.hidden = true;
    panel.innerHTML = '<div role="status" aria-live="polite"></div><label>Voice<select id="tc-voice-pick"></select></label>'
      + '<div class="tc-voice-note" id="tc-voice-model"></div>';
    document.body.appendChild(panel);

    mic.addEventListener('pointerenter', beginHold);
    mic.addEventListener('focus', function () { if (mic.matches(':focus-visible')) beginHold(); });
    mic.addEventListener('pointerdown', cancelHold); // a quick click on the microphone is dictation, as before
    dock.addEventListener('pointerleave', leave);
    dock.addEventListener('pointerenter', function () { clearTimeout(foldTimer); });
    dock.addEventListener('focusout', function (e) { if (!dock.contains(e.relatedTarget)) leave(); });
    btn.addEventListener('click', function () { void toggle(); });
    btn.addEventListener('contextmenu', function (e) { e.preventDefault(); openPanel(true); });
    panel.querySelector('select').addEventListener('change', function (e) { void choose(e.target.value); });
    line.addEventListener('click', function (e) { if (e.target.closest('button')) openPanel(!opened); });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (opened) openPanel(false);
      else if (dock.dataset.open === 'true' && !on()) setOpen(false);
    });
    window.addEventListener('resize', place);
  }

  /* ---------- the line under the message box, and the voice choices ---------- */
  function voiceName() {
    var saved = (status && status.settings) || {}, pick = document.getElementById('tc-voice-pick');
    var option = pick && pick.selectedOptions && pick.selectedOptions[0];
    if (option && option.value !== 'auto|default') return option.textContent.replace(/^[^:]+:\s*/, '');
    if (!saved.voice || saved.voice === 'default') return 'default voice';
    return (status && status.voice_name) || saved.voice_name || saved.voice;
  }

  // One plain line under the message box. While live talk is off it is the panel's line instead, so a reason why it
  // could not start is shown beside the switch.
  function say(text, ms) {
    clearTimeout(noteTimer);
    if (!line) return;
    if (on()) {
      line.hidden = !text;
      line.textContent = text || '';
      if (text) {
        var change = document.createElement('button');
        change.type = 'button';
        change.textContent = voiceName();
        change.title = 'Change the voice';
        line.append(' Voice: ', change);
      }
    } else {
      line.hidden = true;
      var slot = panel.querySelector('[role="status"]');
      slot.textContent = text || '';
      panel.hidden = !(text || opened);
      place();
    }
    if (text && ms) noteTimer = setTimeout(function () { say(''); }, ms);
  }

  function heard(text) {
    if (!line || !on()) return;
    if (!text) { setState(btn.dataset.voiceState); return; }
    line.hidden = false;
    line.textContent = '';
    var quote = document.createElement('q');
    quote.textContent = text.length > 110 ? '…' + text.slice(-110) : text; // one line: the latest words show
    line.appendChild(quote);
  }

  function place() {
    if (!panel || panel.hidden || !dock) return;
    var box = dock.getBoundingClientRect();
    panel.style.right = Math.max(8, window.innerWidth - box.right) + 'px';
    panel.style.bottom = (window.innerHeight - box.top + 10) + 'px';
  }

  function openPanel(next) {
    opened = next;
    if (!panel) return;
    panel.querySelector('[role="status"]').textContent = '';
    panel.hidden = !next;
    if (next) { void fillChoices(); place(); }
  }

  function describeModel() {
    var model = document.getElementById('tc-voice-model');
    if (!model) return;
    var fast = status && status.fast_model, listen = status && status.live;
    var words = fast ? 'Answers with ' + fast.label + ', your smallest and fastest model.'
      : 'No small model is set up, so answers use the model you chose.';
    if (listen && listen.by === 'thomas') words += ' Listens with ' + listen.model + '.';
    else if (listen && !listen.model) words += ' Live listening is not ready, so the browser listens: ' + listen.why;
    model.textContent = words;
  }

  function fillChoices() {
    var select = document.getElementById('tc-voice-pick'), saved = (status && status.settings) || {};
    describeModel();
    var studio = status && status.studio && status.studio.running ? load('/api/voice/voices') : Promise.resolve({ body: {} });
    return studio.then(function (found) {
      var synth = window.speechSynthesis, options = [['auto|default', 'Default voice']];
      ((found.body && found.body.voices) || []).forEach(function (v) { options.push(['voicestudio|' + v.id, 'Voice Studio: ' + v.name]); });
      ((synth && synth.getVoices && synth.getVoices()) || []).forEach(function (v) { options.push(['browser|' + v.name, 'This browser: ' + v.name]); });
      select.innerHTML = '';
      options.forEach(function (row) {
        var option = document.createElement('option');
        option.value = row[0];
        option.textContent = row[1];
        select.appendChild(option);
      });
      var now = saved.engine + '|' + saved.voice;
      select.value = options.some(function (row) { return row[0] === now; }) ? now : 'auto|default';
      var named = line && line.querySelector('button'); // a line written before the names arrived gets the name now
      if (named) named.textContent = voiceName();
    });
  }

  function choose(value) {
    var cut = value.indexOf('|'), engine = value.slice(0, cut), voice = value.slice(cut + 1);
    return load('/api/voice/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ engine: engine, voice: voice }) })
      .then(function (res) {
        if (!res.ok) { say('That voice could not be saved.', 6000); return; }
        status.settings = res.body.settings;
        return load('/api/voice/status?surface=' + mode()).then(function (fresh) {
          if (!fresh.ok) return;
          status = fresh.body;
          var session = live().session();
          if (session) session.status = status; // the next sentence already uses the new voice
          if (on()) setState(btn.dataset.voiceState);
        });
      });
  }

  /* ---------- setting up Thomas's own ears, the first time ---------- */
  // When live talk is turned on and Thomas cannot hear by himself yet (status.setup says what that would take), a window
  // in the middle of the screen offers to set him up, once per page. Set up later goes on with the browser's hearing.
  // Set up now has Thomas do all of it (his speech engine if missing, then the model, every file checked) and shows how
  // far he has got; hiding the window lets it carry on, and live talk switches to his own ears the moment it is done.
  var asked = false, setupBox = null, setupWaiting = null, setupPoll = 0;

  function megabytes(bytes) { return Math.round((bytes || 0) / 1e6) + ' MB'; }

  function finishSetup(result) {
    var waiting = setupWaiting;
    setupWaiting = null;
    if (waiting) waiting(result);
  }

  function closeSetup() {
    if (setupBox) setupBox.remove();
    setupBox = null;
  }

  function offerSetup() {
    var setup = status && status.setup;
    if (!setup || asked) return Promise.resolve(false);
    asked = true;
    return new Promise(function (resolve) {
      setupWaiting = resolve;
      openSetup(setup);
      if (setup.progress && setup.progress.state === 'working') followSetup();
    });
  }

  function openSetup(setup) {
    closeSetup();
    setupBox = document.createElement('div');
    setupBox.id = 'tc-voice-setup';
    setupBox.innerHTML = '<div class="tc-vs-card" role="dialog" aria-modal="true" aria-labelledby="tc-vs-title">'
      + '<h2 id="tc-vs-title">You don’t have voice set up</h2><p class="tc-vs-what"></p><p class="tc-vs-small"></p>'
      + '<div class="tc-vs-bar" hidden><span></span></div><p class="tc-vs-status" role="status" aria-live="polite"></p>'
      + '<div class="tc-vs-buttons"><button type="button" class="tc-vs-later">Set up later</button>'
      + '<button type="button" class="tc-vs-now">Set up now</button></div></div>';
    setupBox.querySelector('.tc-vs-what').textContent = 'To hear you while you talk, Thomas runs a speech model on this '
      + 'computer, so what you say stays here. Setting up downloads ' + setup.name + ' (' + megabytes(setup.bytes)
      + ') once, from its makers, and checks every file.' + (setup.engine ? '' : ' It installs his speech engine first.')
      + ' Until then your browser listens.';
    setupBox.querySelector('.tc-vs-small').textContent = setup.about + ' Licence: ' + setup.licence + '. ' + setup.credit + '.';
    setupBox.querySelector('.tc-vs-later').addEventListener('click', function () { closeSetup(); finishSetup(false); });
    setupBox.querySelector('.tc-vs-now').addEventListener('click', beginSetup);
    setupBox.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      closeSetup();
      finishSetup(false);
    });
    document.body.appendChild(setupBox);
    setupBox.querySelector('.tc-vs-now').focus();
  }

  function showSetup(progress, total) {
    if (!setupBox) return;
    var bar = setupBox.querySelector('.tc-vs-bar'), words = setupBox.querySelector('.tc-vs-status');
    var now = setupBox.querySelector('.tc-vs-now'), later = setupBox.querySelector('.tc-vs-later');
    if (progress.state === 'failed') {
      bar.hidden = true;
      words.textContent = 'Setting up stopped: ' + (progress.error || 'something went wrong') + '.';
      now.disabled = false;
      now.textContent = 'Try again';
      later.textContent = 'Set up later';
      return;
    }
    var all = progress.total || total || 1;
    bar.hidden = false;
    bar.firstChild.style.width = Math.min(100, Math.round((progress.done || 0) * 100 / all)) + '%';
    words.textContent = progress.step === 'engine' ? 'Installing Thomas’s speech engine…'
      : 'Downloading ' + megabytes(progress.done) + ' of ' + megabytes(all) + '. You can hide this; it carries on.';
    now.disabled = true;
    later.textContent = 'Hide';
  }

  function beginSetup() {
    var setup = status && status.setup, total = setup && setup.bytes;
    showSetup({ state: 'working', step: 'starting', done: 0, total: total }, total);
    load('/api/voice/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: setup && setup.model }) }).then(function (res) {
      if (!res.ok) { showSetup({ state: 'failed', error: (res.body && res.body.error) || 'Thomas could not start it' }); return; }
      if (res.body.setup === null) { setupDone(); return; }
      followSetup();
    });
  }

  function followSetup() {
    clearTimeout(setupPoll);
    (function look() {
      load('/api/voice/setup').then(function (res) {
        var setup = res.ok ? res.body.setup : undefined;
        if (setup === null) { setupDone(); return; }
        var progress = (setup && setup.progress) || {};
        if (progress.state === 'failed') {
          showSetup(progress);
          if (!setupBox && on()) say('Thomas could not set up his hearing: ' + progress.error, 12000);
          return;
        }
        showSetup(progress, setup && setup.bytes);
        setupPoll = setTimeout(look, res.ok ? 700 : 2000);
      });
    })();
  }

  function setupDone() {
    clearTimeout(setupPoll);
    load('/api/voice/status?fresh=1&surface=' + mode()).then(function (fresh) {
      if (fresh.ok) status = fresh.body;
      closeSetup();
      if (setupWaiting) { finishSetup(true); return; }
      if (on() && live().session()) { live().stop(); void listen(); } // was hidden: change to his own ears now
    });
  }

  /* ---------- turning live talk on and off ---------- */
  function turnOff(message) {
    live().stop();
    btn.setAttribute('aria-checked', 'false');
    setState('off');
    if (message) say(message, 12000);
    setTimeout(function () { if (!on() && !dock.matches(':hover')) setOpen(false); }, 600);
  }

  function hide() {
    live().stop();
    btn.setAttribute('aria-checked', 'false');
    setOpen(false);
    btn.hidden = true;
  }

  function toggle() {
    if (on()) { turnOff(''); return Promise.resolve(); }
    if (starting) return Promise.resolve();
    var which = mode();
    if (which !== 'chat' && which !== 'code') { say('Live talk works in Chat and in Code.', 6000); return Promise.resolve(); }
    starting = true;
    btn.setAttribute('aria-checked', 'true'); // the knob goes across at once; it comes back if listening cannot start
    setState('listening');
    say('Getting ready to listen.');
    return load('/api/voice/status?fresh=1&surface=' + which).then(function (fresh) {
      if (fresh.status === 404) {
        hide();
        say('Voice is turned off. You can turn Talk to Thomas back on in Plugins.', 12000);
        return;
      }
      if (!fresh.ok) { turnOff('Voice is not available right now.'); return; }
      status = fresh.body;
      return offerSetup().then(function () {
        if (!on()) return;
        // The line under the message box names the voice from this list, so wait for it (a short while at most):
        // started at once, the line said "Voice: 7444d461" before the names had arrived.
        var named = fillChoices().catch(function () { /* the line falls back to the saved voice */ });
        return Promise.race([named, new Promise(function (resolve) { setTimeout(resolve, 1500); })]);
      });
    }).then(function () {
      if (!status || !on() || btn.getAttribute('aria-checked') !== 'true') return;
      return listen();
    }).then(function () { starting = false; }, function () { starting = false; });
  }

  function listen() {
    return live().start({
      status: status,
      onState: function (state) { if (on()) setState(state); },
      onPartial: heard,
      onLevel: setLevel,
      onError: function (message) { turnOff(message); },
    }).then(function () { if (on()) setState(live().session() ? live().session().state() : 'listening'); }, function (error) {
      var denied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
      var why = status.live && !status.live.model && status.studio && status.studio.running ? ' Voice Studio: ' + status.live.why : '';
      turnOff(denied ? 'Thomas cannot use the microphone. Allow it in your browser, then try again.'
        : String((error && error.message) || 'Thomas could not start listening.') + why);
    });
  }

  function boot() {
    if (!document.getElementById('tc-mic-btn')) return;
    load('/api/voice/status').then(function (res) {
      if (!res.ok) return;
      status = res.body;
      build();
    });
  }

  window.ThomasVoice = { toggle: toggle, open: function () { setOpen(true); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
