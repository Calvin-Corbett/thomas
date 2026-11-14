// Drive setupMic in js/chat_composer_panels.js with a fake SpeechRecognition that fails in each way a real one does.
// A blocked, unreachable or missing microphone must say so in plain words and must not restart in a loop.
import fs from 'node:fs';
import vm from 'node:vm';

const modulePath = process.argv[2];
if (!modulePath) throw new Error('usage: node chat_mic_errors.mjs <chat_composer_panels.js>');

function fakeEl(tag) {
  return {
    tag, style: {}, title: '', value: '', textContent: '', id: '', _on: {}, children: [], attrs: {},
    addEventListener(type, fn) { this._on[type] = fn; },
    setAttribute(k, v) { this.attrs[k] = v; },
    insertBefore(node) { this.children.push(node); return node; },
  };
}

function build({ withSpeech = true } = {}) {
  const timers = [];
  const card = fakeEl('div');
  const wrap = fakeEl('div'); // the column that holds the card and the footnote
  const row = fakeEl('div');
  const btn = fakeEl('button');
  btn.parentElement = row; row.parentElement = card; card.parentNode = wrap; row.parentNode = card;
  const created = [];
  const doc = {
    getElementById: (id) => (id === 'tc-mic-btn' ? btn : null),
    createElement: (tag) => { const el = fakeEl(tag); created.push(el); return el; },
  };
  const win = { addEventListener() {} };
  const ctx = {
    window: win, document: doc,
    setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length; },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].live = false; },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(modulePath.replace(/chat_composer_panels\.js$/, 'chat_mic.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(modulePath, 'utf8'), ctx);
  const rec = { starts: 0, stops: 0, aborts: 0 };
  if (withSpeech) {
    win.SpeechRecognition = function Fake() {
      rec.self = this;
      this.start = () => { rec.starts += 1; };
      this.stop = () => { rec.stops += 1; };
      this.abort = () => { rec.aborts += 1; };
    };
  }
  const state = { input: '', listening: false };
  const panels = win.ThomasChatComposerPanels.create({
    state, esc: String, inputEl: { value: '' }, autosize() {}, syncDynamic() {}, DIAL_FIELDS: [], saveDials() {},
  });
  panels.setupMic();
  return { btn, wrap, rec, state, timers, note: () => created.find((el) => el.id === 'tc-mic-note') };
}

const checks = {};
const BLOCKED = "Microphone is blocked for this page. Allow it in the browser's address bar, then try again.";
const MESSAGES = {
  'not-allowed': BLOCKED,
  'service-not-allowed': BLOCKED,
  'network': "The browser's speech service could not be reached.",
  'audio-capture': 'No microphone was found.',
};
for (const [code, text] of Object.entries(MESSAGES)) {
  const t = build();
  t.btn._on.click();
  const listening = t.state.listening === true && t.btn.title.startsWith('Listening');
  // The browser fires the error and then end; end must not start it again.
  t.rec.self.onerror({ error: code });
  t.rec.self.onend();
  const note = t.note();
  checks[`${code} says why`] = !!note && note.textContent === text && note.attrs.role === 'status';
  checks[`${code} sits under the composer`] = !!note && t.wrap.children.includes(note);
  checks[`${code} does not loop`] = listening && t.rec.starts === 1 && t.state.listening === false;
  checks[`${code} resets the button`] = t.btn.style.background === 'transparent' && t.btn.title === 'Voice input';
}

// No speech: stop quietly, nothing to read, no restart.
{
  const t = build();
  t.btn._on.click();
  t.rec.self.onerror({ error: 'no-speech' });
  t.rec.self.onend();
  checks['no-speech is quiet'] = !t.note() && t.state.listening === false && t.rec.starts === 1;
  checks['no-speech resets the button'] = t.btn.title === 'Voice input';
}

// An unknown error is still reported, never swallowed.
{
  const t = build();
  t.btn._on.click();
  t.rec.self.onerror({ error: 'language-not-supported' });
  t.rec.self.onend();
  checks['an unknown error is named'] = !!t.note() && t.note().textContent.includes('language-not-supported') && t.rec.starts === 1;
}

// A normal end while listening still restarts (continuous listening is kept); 'aborted' is not an error to show.
{
  const t = build();
  t.btn._on.click();
  t.rec.self.onerror({ error: 'aborted' });
  t.rec.self.onend();
  checks['a plain end keeps listening'] = t.rec.starts === 2 && t.state.listening === true && !t.note();
}

// The 5 s silence stop is kept, and it starts when the microphone opens, not at the click.
{
  const t = build();
  t.btn._on.click();
  const armedAtClick = t.timers.some((x) => x.live && x.ms === 5000);
  t.rec.self.onaudiostart();
  const silence = t.timers.find((x) => x.live && x.ms === 5000);
  silence.fn();
  t.rec.self.onend();
  checks['silence clock waits for the microphone'] = !armedAtClick && !!silence;
  checks['silence stops after a pause'] = t.rec.stops === 1 && t.state.listening === false && t.rec.starts === 1;
}

// The next press clears an old message.
{
  const t = build();
  t.btn._on.click();
  t.rec.self.onerror({ error: 'network' });
  t.rec.self.onend();
  t.btn._on.click();
  checks['a new press clears the message'] = t.note().textContent === '' && t.rec.starts === 2;
}

// No speech support: the button says so when pressed.
{
  const t = build({ withSpeech: false });
  t.btn._on.click();
  checks['unsupported browsers are told'] = !!t.note() && t.note().textContent.includes('not supported');
}

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`mic check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
