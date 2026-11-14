// Runs thomas/server/web/settings.plugins-panel.js for tests/test_plugins_panel_ui.py: a small page, a server the test
// scripts and a clock it moves by hand. Nothing here decides what the panel shows, so a test reads what a person would.
const fs = require('fs');
const vm = require('vm');

class Element {
  constructor(page, tag) {
    this.page = page;
    this.tag = tag;
    this.className = '';
    this.children = [];
    this.parent = null;
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
    this.own = '';
  }

  get classList() {
    const read = () => this.className.split(/\s+/).filter(Boolean);
    const write = (names) => { this.className = names.join(' '); };
    return {
      contains: (name) => read().includes(name),
      add: (name) => write([...new Set([...read(), name])]),
      remove: (name) => write(read().filter((item) => item !== name)),
      toggle: (name, on) => write(on ? [...new Set([...read(), name])] : read().filter((item) => item !== name)),
    };
  }

  get textContent() {
    return this.own + this.children.map((child) => child.textContent).join('');
  }

  set textContent(value) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    this.own = String(value);
    if (this === this.page.status) this.page.spoken.push(this.own);
  }

  set innerHTML(_value) {
    throw new Error('the panel must set words as text: a reason for a failure can hold anything');
  }

  append(...children) {
    for (const child of children) {
      if (child.parent) child.parent.children = child.parent.children.filter((item) => item !== child);
      child.parent = this;
      this.children.push(child);
    }
  }

  remove() {
    this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  getAttribute(name) {
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }

  addEventListener(name, handler) {
    (this.listeners[name] ||= []).push(handler);
  }

  contains(other) {
    for (let node = other; node; node = node.parent) if (node === this) return true;
    return false;
  }

  focus() {
    this.page.document.activeElement = this;
  }

  click() {
    for (const handler of this.listeners.click || []) handler({ target: this });
  }

  isShown() {
    for (let node = this; node; node = node.parent) if (node.hidden) return false;
    return true;
  }

  all(test, found = []) {
    for (const child of this.children) {
      if (test(child)) found.push(child);
      child.all(test, found);
    }
    return found;
  }

  byClass(name) {
    return this.all((node) => node.classList.contains(name))[0] || null;
  }

  // What a person reads: hidden parts are not on the screen, and the status line is for screen readers.
  visibleText() {
    if (this.hidden || this === this.page.status) return '';
    return [this.own, ...this.children.map((child) => child.visibleText())].filter(Boolean).join(' ');
  }
}

class Page {
  constructor({ search = '', embedded = true, watches = true } = {}) {
    this.now = 1000000;
    this.timers = [];
    this.calls = [];
    this.spoken = [];
    this.posted = [];
    this.sections = [];
    this.report = { rows: [], notes: [], note_codes: [] };
    this.sets = 404; // a status, or the sets themselves ({ sets, groups }), for GET /api/plugins/sets
    this.applied = null; // what POST /api/plugins/sets/{id}/apply answers: a status, 'down' or a body
    this.pauseAnswer = 404; // a status, or { paused, since, reason, still_running }, for GET /api/thomas/pause
    this.others = []; // every call to the sets and the pause control, kept apart so reads() counts only the plugins
    this.getAnswer = null; // a status, 'down', 'silent' or a held promise, to change what a status read gets
    this.pressAnswers = []; // one per press, oldest first: a status, a row, 'down' or a held promise
    const host = new Element(this, 'div');
    const panel = new Element(this, 'div');
    panel.append(host);
    this.host = host;
    this.document = {
      readyState: 'loading',
      hidden: false,
      activeElement: null,
      createElement: (tag) => new Element(this, tag),
      getElementById: (id) => ({ pluginsHost: host, plugins: panel })[id] || null,
      addEventListener: (name, handler) => { (this.listeners ||= {})[name] = handler; },
    };
    const page = this;
    class Watcher {
      constructor(report) { page.seeing = report; }

      observe() {}
    }
    const context = {
      document: this.document,
      window: {
        location: { search, origin: 'http://thomas.test' },
        parent: embedded ? { postMessage: (...call) => this.posted.push(call) } : null,
      },
      Date: { now: () => this.now },
      setTimeout: (handler, delay) => {
        const timer = { handler, due: this.now + delay };
        this.timers.push(timer);
        return timer;
      },
      clearTimeout: (timer) => { this.timers = this.timers.filter((item) => item !== timer); },
      fetch: (url, options) => this.fetch(url, options),
      switchSection: (section) => this.sections.push(section),
      AbortController,
      URLSearchParams,
      console,
    };
    if (!embedded) context.window.parent = context.window;
    if (watches) context.IntersectionObserver = Watcher;
    vm.createContext(context);
    for (const script of ['settings.plugins-sets.js', 'settings.plugins-panel.js']) {
      vm.runInContext(fs.readFileSync(`thomas/server/web/${script}`, 'utf8'), context);
    }
    this.listeners.DOMContentLoaded();
    this.status = host.byClass('sr-only');
  }

  answer(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(JSON.stringify(body)) };
  }

  fetch(url, options = {}) {
    const method = options.method || 'GET';
    if (url.startsWith('/api/plugins/sets') || url.startsWith('/api/thomas/')) return this.fetchOther(method, url);
    this.calls.push(`${method} ${url}`);
    if (method === 'GET') {
      if (this.getAnswer === 'down') return Promise.reject(new TypeError('Failed to fetch'));
      if (this.getAnswer === 'silent') {
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        });
      }
      if (this.getAnswer instanceof Promise) return this.getAnswer.then((report) => this.answer(200, report));
      return Promise.resolve(this.answer(this.getAnswer || 200, this.report));
    }
    const next = this.pressAnswers.length ? this.pressAnswers.shift() : new Promise(() => {});
    if (next === 'down') return Promise.reject(new TypeError('Failed to fetch'));
    if (typeof next === 'number') return Promise.resolve(this.answer(next, {}));
    return Promise.resolve(next).then((row) => this.pressed(row));
  }

  // The sets and the pause control, which a test scripts with this.sets, this.applied and this.pauseAnswer.
  fetchOther(method, url) {
    this.others.push(`${method} ${url}`);
    if (method === 'GET' && url === '/api/plugins/sets') return this.reply(this.sets);
    if (method === 'GET') return this.reply(this.pauseAnswer);
    if (url.startsWith('/api/plugins/sets/')) return this.reply(this.applied === null ? 404 : this.applied);
    const paused = url === '/api/thomas/pause';
    this.pauseAnswer = { paused, since: 1, reason: '', still_running: paused ? this.stillRunning || 0 : 0 };
    return this.reply(this.pauseAnswer);
  }

  reply(what) {
    if (what === 'down') return Promise.reject(new TypeError('Failed to fetch'));
    if (typeof what === 'number') return Promise.resolve(this.answer(what, {}));
    return Promise.resolve(this.answer(200, what));
  }

  // A press the server answered has changed what the server reads back.
  pressed(row) {
    this.report.rows = this.report.rows.map((item) => (item.id === row.id ? row : item));
    return this.answer(200, row);
  }

  async settle() {
    for (let turn = 0; turn < 8; turn += 1) await new Promise((resolve) => setImmediate(resolve));
  }

  // Moves the clock, one timer at a time, as a browser would.
  async tick(milliseconds) {
    const end = this.now + milliseconds;
    for (;;) {
      await this.settle();
      const due = this.timers.filter((timer) => timer.due <= end).sort((a, b) => a.due - b.due)[0];
      if (!due) break;
      this.timers = this.timers.filter((timer) => timer !== due);
      this.now = Math.max(this.now, due.due);
      due.handler();
    }
    this.now = end;
    await this.settle();
  }

  async show(seen = true) {
    this.seeing([{ isIntersecting: seen }]);
    await this.settle();
  }

  reads() {
    return this.calls.filter((call) => call.startsWith('GET')).length;
  }

  presses() {
    return this.calls.filter((call) => call.startsWith('POST'));
  }

  text() {
    return this.host.visibleText();
  }

  // The row a person would call by its name, as they see it.
  row(name) {
    const node = this.host.all((item) => item.classList.contains('plugin-row')).find((item) => item.byClass('plugin-name').textContent === name);
    if (!node) throw new Error(`no row reads ${name}: ${this.text()}`);
    const named = (words) => node.all((item) => item.tag === 'button' && item.textContent === words)[0] || null;
    return {
      node,
      text: () => node.visibleText(),
      label: () => node.byClass('plugin-state').textContent,
      toggle: node.byClass('toggle-switch'),
      button: named,
      shown: (words) => { const found = named(words); return Boolean(found && found.isShown()); },
    };
  }
}

const row = (fields = {}) => ({
  id: 'companion',
  title: 'Companion apps',
  about: 'Runs the apps.',
  off_means: 'While this is off, those apps stop working.',
  stop_now: 'Anything those apps are waiting on will fail.',
  enabled: true,
  state: 'active',
  error: '',
  waiting_for: 0,
  ...fields,
});

async function open(rows, options) {
  const page = new Page(options);
  page.report.rows = rows;
  await page.show();
  return page;
}

module.exports = { Page, open, row };
