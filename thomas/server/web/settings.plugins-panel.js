/* Settings > Plugins: the parts of Thomas you can turn off and on.

   The server sends each row's words and this page only shows them, so a new row needs no change here. The words below
   are the page's own: what each state is called and what a whole-page problem says. Nothing raw reaches the screen, and
   every word is set as text, because a reason for a failure can hold anything.

   Rows are built once and changed in place, so a poll takes keyboard focus off nothing that stays on screen. A screen
   reader hears each change once, through one status line, rather than on every poll, and what a row says reaches it
   there or not at all. A successful answer from the server does not mean a plugin started: the page shows the state it reads back, never
   the one it asked for.

   It keeps reading for as long as you can see it, even with nothing moving, or it could go on saying "Everything is on."
   about a Thomas that has gone. document.hidden cannot see a hidden frame or an inactive section, so the panel itself is
   watched.

   A read that is refused means Thomas has gone. A read that only waits means less: a browser gives one server six
   connections, so with a press held open and five streams the read never leaves the browser, and it waits for as long as
   they stay open. Measured in Chromium, so a longer patience would only delay the same sentence. Every connection dies
   with the server, so a read waiting behind them is refused and the page still finds out.
*/
(function pluginsPanel() {
  'use strict';

  const API = '/api/plugins/thomas';
  const EVERY_SECOND = 1000; // while something is starting or stopping
  const WHILE_NOT_ANSWERING = 2000;
  const WHILE_NOTHING_MOVES = 5000;
  const STOP_NOW_AFTER = 3000; // only keeps the button from flashing on a quick stop: no timer ever ends the work
  const READ_PATIENCE = 10000; // a status read gives up on a silent server, and no work depends on the read

  const UNNAMED = 'A part of Thomas';
  const UNKNOWN_COST = 'Anything it is still doing will be cut off, and may need doing again.';
  const NOT_ANSWERING = "Thomas isn't answering. It may be restarting. This page will catch up by itself.";
  const TAKING_A_WHILE = 'Thomas is taking a while to answer. It may be busy, or too many Thomas tabs may be open. This page will catch up by itself.';
  const BACK = 'Thomas is answering again.';
  const ADVANCED = 'Advanced: choose each plugin yourself';
  const OTHER_GROUP = 'More';
  const ADVANCED_KEY = 'thomas.plugins.advanced-open';
  const ELSEWHERE = 'You can change these only on the computer Thomas runs on.';
  const REQUIRED_DETAIL = 'Always on. Thomas needs this to work.';
  const NOT_SAVED = "Thomas couldn't save that. Try again.";
  const OVERDUE = 'This is taking longer than it should.';
  const NOTES = {
    choices_unreadable: "Your saved plugin choices couldn't be read, so everything is back to its default. Your old choices are kept. Changing any switch saves a fresh copy.",
    list_unreadable: "Thomas couldn't read its list of plugins, so none of them started. The rest of Thomas is working.",
  };
  const OTHER_NOTE = 'Thomas noticed a problem with its plugin list. The rest of Thomas is working.';
  const COUNTS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
  const PHASES = {
    on: { label: 'On', tone: 'is-success', checked: true },
    off: { label: 'Off', tone: '', checked: false },
    waiting: { label: 'Waiting', tone: 'is-warning', checked: true },
    'turning-on': { label: 'Turning on...', tone: 'is-warning', checked: true },
    'turning-off': { label: 'Turning off...', tone: 'is-warning', checked: false },
    restarting: { label: 'Restarting...', tone: 'is-warning', checked: true },
    failed: { label: "Didn't start", tone: 'is-danger', checked: false },
  };

  const rows = new Map(); // id to what the server last said
  const memos = new Map(); // id to what only this page knows
  const views = new Map(); // id to the row's elements
  const page = { connection: 'reading', notes: [], pressNotice: null, shown: '', wasOut: false };
  let parts = null;
  let reading = false;
  let readAgain = false; // a press ended during a read, so what that read brings back cannot be believed
  let timer = 0;
  let inView = false;
  let serial = 0;
  let extras = null; // the sets and Pause, from settings.plugins-sets.js, or null when that script is not there
  let advancedOpen = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function setText(node, text) {
    if (node.textContent !== text) node.textContent = text;
    node.hidden = !text;
  }

  function button(className, text, onPress) {
    const node = element('button', className, text);
    node.type = 'button';
    node.addEventListener('click', () => {
      if (node.getAttribute('aria-disabled') !== 'true') onPress();
    });
    return node;
  }

  function setLocked(node, locked) {
    node.setAttribute('aria-disabled', locked ? 'true' : 'false');
  }

  // What the row is doing now. A press stands in only until the server shows it took it.
  function phaseOf(row, memo) {
    if (memo.press) return memo.press.kind === 'on' ? 'turning-on' : 'turning-off';
    switch (row.state) {
      case 'active': return 'on';
      case 'pending': return 'waiting';
      case 'failed': return 'failed';
      case 'loading': return row.enabled === false ? 'turning-off' : 'turning-on';
      case 'unloading': return row.enabled === false ? 'turning-off' : 'restarting';
      default: return 'off';
    }
  }

  function serverTookIt(row, press) {
    if (press.kind === 'off') return row.enabled === false;
    return row.state === 'loading' || row.state === 'unloading';
  }

  function isMoving(row, memo) {
    return Boolean(memo.press || memo.forcing) || row.state === 'loading' || row.state === 'unloading';
  }

  function waitingWords(count) {
    if (count === 1) return 'Finishing 1 job first.';
    return count > 1 ? `Finishing ${count} jobs first.` : 'Almost done.';
  }

  // Shows only once the wait has gone on, and never without its cost beside it. waiting_for can be 0 on a stop stuck in
  // a stop step, which Stop now can still end, so a row with those words keeps the button then too.
  function stopNowCost(row, memo, now) {
    if (row.state !== 'unloading' || row.required) return '';
    if (!memo.forcing && now - memo.stoppingSince < STOP_NOW_AFTER) return '';
    return row.stop_now || (row.waiting_for > 0 ? UNKNOWN_COST : '');
  }

  function tookTooLong(memo, now) {
    return Boolean(memo.forcing) && (memo.forcing.answered || now - memo.forcing.at >= STOP_NOW_AFTER);
  }

  function describe(row, memo, now) {
    const title = row.title || UNNAMED;
    if (page.connection !== 'ok') {
      const label = page.connection === 'slow' ? 'Checking...' : 'No answer';
      return { title, label, tone: '', unknown: true, locked: true, showSwitch: true };
    }
    const phase = phaseOf(row, memo);
    const view = { ...PHASES[phase], title, moving: isMoving(row, memo), showSwitch: phase !== 'failed' };
    view.locked = Boolean(memo.press) || phase === 'turning-off' || phase === 'restarting' || Boolean(row.required);
    // A required row has no off switch: it reads on and locked, and a failed one can only be tried again.
    if (row.required && phase !== 'failed') view.detail = REQUIRED_DETAIL;
    if (phase === 'waiting') view.lead = 'Waiting for another part of Thomas to come on.';
    if (phase === 'off' && row.stopped_partway) view.lead = 'Off. What it was doing was stopped partway.';
    if (phase === 'failed') {
      const opening = memo.tried ? "It still didn't start." : `${title} didn't start.`;
      view.lead = `${opening} The rest of Thomas is working normally.`;
      view.reason = row.error ? `The reason recorded was: ${row.error}` : '';
      view.failedActions = true;
      view.canLeaveOff = !row.required;
    }
    if (row.state === 'unloading' && !memo.press) {
      const saved = row.enabled === false;
      view.lead = waitingWords(row.waiting_for);
      if (tookTooLong(memo, now)) view.lead = saved ? `${OVERDUE} It stays off when Thomas next restarts.` : OVERDUE;
      if (saved) view.detail = 'This is saved as off, so it stays off even if Thomas restarts.';
      view.stopCost = stopNowCost(row, memo, now);
    }
    return view;
  }

  function buildRow(id) {
    serial += 1;
    const node = element('li', 'plugin-row');
    const name = element('div', 'plugin-name');
    const about = element('div', 'plugin-about');
    const cost = element('div', 'plugin-cost');
    const pill = element('span', 'status-pill plugin-state');
    const word = element('span');
    const toggle = button('toggle-switch', '', () => {
      press(id, toggle.getAttribute('aria-checked') === 'true' ? 'off' : 'on');
    });
    name.id = `plugin-name-${serial}`;
    about.id = `plugin-about-${serial}`;
    cost.id = `plugin-cost-${serial}`;
    word.id = `plugin-state-${serial}`;
    toggle.setAttribute('aria-labelledby', name.id);
    toggle.setAttribute('aria-describedby', `${word.id} ${about.id} ${cost.id}`);
    pill.append(element('i'), word);
    const control = element('div', 'plugin-control');
    control.append(pill, toggle);
    const story = element('div', 'plugin-story');
    const lead = element('div', 'plugin-lead');
    const detail = element('div', 'plugin-detail');
    const reason = element('div', 'plugin-reason');
    const stopBox = element('div', 'plugin-stop');
    const stopNow = button('btn btn-danger', 'Stop now', () => forceStop(id));
    const stopCost = element('div', 'plugin-stop-cost');
    stopCost.id = `plugin-stop-cost-${serial}`;
    stopNow.setAttribute('aria-describedby', stopCost.id);
    stopBox.append(stopNow, stopCost);
    const actions = element('div', 'plugin-actions');
    const tryAgain = button('btn btn-primary', 'Try again', () => press(id, 'on', true));
    const leaveOff = button('btn btn-secondary', 'Leave it off', () => press(id, 'off'));
    const askWhy = button('btn btn-secondary', 'Ask Thomas why', () => askThomas(id));
    actions.append(tryAgain, leaveOff, askWhy);
    // Each is named with its row, because two rows that failed would otherwise give two identical buttons.
    for (const [control, word] of [[stopNow, 'stop'], [tryAgain, 'try'], [leaveOff, 'leave'], [askWhy, 'ask']]) {
      control.id = `plugin-${word}-${serial}`;
      control.setAttribute('aria-labelledby', `${control.id} ${name.id}`);
    }
    story.append(lead, detail, reason, stopBox, actions);
    node.append(name, control, about, cost, story);
    const texts = { name, about, cost, word, lead, detail, reason, stopCost };
    return { ...texts, node, pill, toggle, story, stopBox, stopNow, actions, tryAgain, leaveOff, askWhy, home: null };
  }

  function paintRow(id, row, memo, now) {
    const view = describe(row, memo, now);
    if (!views.has(id)) views.set(id, buildRow(id));
    const v = views.get(id);
    const held = document.activeElement;
    const hadFocus = v.node.contains(held);
    setText(v.name, view.title);
    setText(v.about, row.about || '');
    setText(v.cost, row.off_means || '');
    setText(v.word, view.label);
    v.pill.className = `status-pill plugin-state ${view.tone}${view.moving ? ' is-moving' : ''}`;
    v.node.classList.toggle('is-off', view.checked === false && !view.unknown);
    if (view.unknown) { // a switch can only be on or off, so while neither is known this is a locked button
      v.toggle.removeAttribute('role');
      v.toggle.removeAttribute('aria-checked');
    } else {
      v.toggle.setAttribute('role', 'switch');
      v.toggle.setAttribute('aria-checked', view.checked ? 'true' : 'false');
    }
    v.toggle.classList.toggle('on', !view.unknown && view.checked);
    v.toggle.classList.toggle('is-unknown', Boolean(view.unknown));
    setLocked(v.toggle, view.locked);
    v.toggle.hidden = !view.showSwitch;
    setText(v.lead, view.lead || '');
    setText(v.detail, view.detail || '');
    setText(v.reason, view.reason || '');
    setText(v.stopNow, memo.forcing ? 'Stopping now...' : 'Stop now');
    setText(v.stopCost, view.stopCost || '');
    v.stopNow.hidden = !view.stopCost;
    v.stopBox.hidden = !view.stopCost;
    setLocked(v.stopNow, Boolean(memo.forcing));
    v.tryAgain.hidden = !view.failedActions;
    v.leaveOff.hidden = !view.failedActions || view.canLeaveOff === false;
    v.askWhy.hidden = !view.failedActions || window.parent === window; // the chat drawer lives in the shell around Settings
    v.actions.hidden = !view.failedActions;
    v.story.hidden = !(view.lead || view.detail || view.stopCost || view.failedActions);
    // An outage hides what has focus with nothing pressed, and Enter must not then land on a different action. So focus
    // it moved goes back with Thomas, if its control does. Only then: a stop much later has no claim on focus.
    const moved = outOfTouch() ? null : v.movedFocus;
    if (moved) v.movedFocus = null;
    if (moved && held === moved.to && !moved.from.hidden) {
      moved.from.focus();
    } else if (hadFocus && held.hidden) {
      const next = [v.toggle, v.tryAgain, v.stopNow].find((control) => !control.hidden);
      if (next) next.focus();
      if (next && outOfTouch()) v.movedFocus = { from: held, to: next };
    }
    return view;
  }

  function countWord(count) {
    return COUNTS[count] || String(count);
  }

  function summaryOf(described) {
    const total = described.length;
    const count = (phase) => described.filter((item) => item.phase === phase).length;
    const failed = count('failed');
    const off = count('off');
    const waiting = count('waiting');
    if (!total) return '';
    if (failed) return `${countWord(failed)} ${failed === 1 ? 'needs' : 'need'} a look.`;
    if (described.some((item) => item.moving)) return 'Working on it.';
    if (waiting) return `${countWord(waiting)} ${waiting === 1 ? 'is' : 'are'} waiting.`;
    if (!off) return 'Everything is on.';
    if (off === total) return 'Everything is off.';
    return `${countWord(off)} ${off === 1 ? 'is' : 'are'} off. Everything else is on.`;
  }

  function noticesOf() {
    if (page.connection === 'lost') return [NOT_ANSWERING];
    if (page.connection === 'slow') return [TAKING_A_WHILE];
    if (page.connection === 'elsewhere') return [ELSEWHERE];
    const notes = [...new Set(page.notes.map((code) => NOTES[code] || OTHER_NOTE))];
    return page.pressNotice ? [...notes, page.pressNotice.text] : notes;
  }

  function outOfTouch() {
    return page.connection === 'lost' || page.connection === 'slow';
  }

  function paintNotices(spoken) {
    const notices = noticesOf();
    const shown = notices.join('\n');
    if (shown === page.shown) return false;
    page.shown = shown;
    parts.notices.textContent = '';
    for (const notice of notices) parts.notices.append(element('p', 'plugins-notice', notice));
    parts.notices.hidden = !notices.length;
    spoken.push(...notices);
    return true;
  }

  // What a screen reader has not heard yet about this row. A state's own words are not repeated when the lead says them.
  function newsOf(view, memo) {
    const heard = memo.heard;
    const lead = view.lead || '';
    const stop = view.stopCost ? `Stop now is available. ${view.stopCost}` : '';
    memo.heard = { label: view.label, lead, stop };
    if (!heard) return '';
    const news = [];
    if (view.label !== heard.label && !lead.startsWith(view.label)) news.push(view.label.replace(/[^.]$/, '$&.'));
    if (lead && lead !== heard.lead) news.push(lead);
    if (stop && stop !== heard.stop) news.push(stop);
    return news.length ? `${view.title}: ${news.join(' ')}` : '';
  }

  function paint() {
    const now = Date.now();
    const spoken = [];
    const described = [];
    const groups = extras ? extras.groups() : null;
    showGroups(groups);
    for (const [id, row] of rows) {
      const memo = memos.get(id);
      const view = paintRow(id, row, memo, now);
      placeRow(id, groups);
      const news = page.connection === 'ok' ? newsOf(view, memo) : '';
      if (news) spoken.push(news);
      described.push({ phase: phaseOf(row, memo), moving: isMoving(row, memo) });
    }
    for (const [id, view] of views) {
      if (!rows.has(id)) {
        view.node.remove();
        views.delete(id);
      }
    }
    parts.waiting.hidden = page.connection !== 'reading';
    parts.root.classList.toggle('is-stale', outOfTouch());
    paintAdvanced(groups);
    parts.foot.hidden = page.connection === 'reading';
    setText(parts.summary, page.connection === 'ok' ? summaryOf(described) : '');
    const noticesChanged = paintNotices(spoken);
    if (page.wasOut && page.connection === 'ok') spoken.unshift(BACK);
    page.wasOut = outOfTouch();
    if (spoken.length) parts.status.textContent = spoken.join(' ');
    else if (noticesChanged) parts.status.textContent = ''; // or a notice that has gone stays there to be read
  }

  function newMemo() {
    return { press: null, forcing: null, stoppingSince: 0, tried: false, heard: null, unconfirmed: null };
  }

  function tell(text, id) {
    page.pressNotice = { text, id, rowWas: '' };
  }

  // Says that a press failed, so it holds only while the row stands as the first read after that press found it. That
  // read is the baseline, because an off whose save failed has changed the row on its way.
  function reviewNotice(row) {
    const notice = page.pressNotice;
    if (!notice || notice.id !== row.id || row.state === 'loading' || row.state === 'unloading') return; // still arriving
    const now = `${row.state} ${row.enabled}`;
    if (notice.rowWas && notice.rowWas !== now) page.pressNotice = null;
    else notice.rowWas = now;
  }

  // A failed row is already saved as on, so what shows a retry arrived is the row leaving failed.
  function neverArrived(row, press) {
    return press.retrying ? row.state === 'failed' : row.enabled !== (press.kind === 'on');
  }

  function takeRow(row) {
    const memo = memos.get(row.id) || newMemo();
    memos.set(row.id, memo);
    rows.set(row.id, row);
    if (memo.press && serverTookIt(row, memo.press)) {
      memo.press.taken = true;
      memo.press = null;
    }
    if (memo.unconfirmed) {
      if (neverArrived(row, memo.unconfirmed)) tell(NOT_SAVED, row.id);
      memo.unconfirmed = null;
    }
    reviewNotice(row);
    if (row.state === 'unloading') {
      memo.stoppingSince = memo.stoppingSince || Date.now();
      return;
    }
    memo.forcing = null;
    memo.stoppingSince = 0;
    if (phaseOf(row, memo) === 'off' || row.state === 'active') memo.tried = false;
  }

  function takeReport(report) {
    const named = new Set(report.rows.map((row) => row.id));
    for (const id of [...rows.keys()]) {
      if (!named.has(id)) {
        rows.delete(id);
        memos.delete(id);
        if (page.pressNotice && page.pressNotice.id === id) page.pressNotice = null;
      }
    }
    report.rows.forEach(takeRow);
    page.notes = Array.isArray(report.note_codes) ? report.note_codes : [];
  }

  function watching() {
    return inView && !document.hidden;
  }

  function plan() {
    clearTimeout(timer);
    timer = 0;
    if (!watching() || page.connection === 'elsewhere') return;
    const moving = [...rows].some(([id, row]) => isMoving(row, memos.get(id)));
    if (outOfTouch()) timer = setTimeout(read, WHILE_NOT_ANSWERING);
    else timer = setTimeout(read, moving ? EVERY_SECOND : WHILE_NOTHING_MOVES);
  }

  async function ask() {
    const control = new AbortController();
    const patience = setTimeout(() => control.abort(), READ_PATIENCE);
    try {
      const headers = { Accept: 'application/json' };
      const response = await fetch(API, { headers, cache: 'no-store', signal: control.signal });
      if (response.status === 401 || response.status === 403) return { elsewhere: true };
      const report = response.ok ? await response.json() : null;
      return report && Array.isArray(report.rows) ? { report } : {};
    } catch (error) {
      return { slow: error.name === 'AbortError' };
    } finally {
      clearTimeout(patience);
    }
  }

  async function read() {
    if (reading) {
      readAgain = true;
      return;
    }
    clearTimeout(timer);
    reading = true;
    const answer = await ask();
    reading = false;
    if (readAgain) {
      readAgain = false;
      read();
      return;
    }
    page.connection = answer.report ? 'ok' : answer.elsewhere ? 'elsewhere' : answer.slow ? 'slow' : 'lost';
    if (answer.report) takeReport(answer.report);
    paint();
    if (extras) extras.sync(page.connection);
    plan();
  }

  // The press that turns something off stays open until the stop ends, so nothing here waits on it: the polled state is
  // the truth. A press that drops is not a failure either, because the stop goes on without the page.
  async function post(url) {
    try {
      return await fetch(url, { method: 'POST', headers: { Accept: 'application/json' } });
    } catch (error) {
      return null;
    }
  }

  async function answerOf(id, memo, response, retrying) {
    const answer = response && response.ok ? await response.json().catch(() => null) : null;
    if (response && !response.ok && response.status !== 409) {
      tell(response.status === 401 || response.status === 403 ? ELSEWHERE : NOT_SAVED, id);
    }
    if (answer && answer.id === id) {
      if (retrying) memo.tried = true; // only an answer shows a retry ran, so only that may say it still didn't start
      takeRow(answer);
    }
    paint();
    read();
  }

  async function press(id, kind, retrying = false) {
    const memo = memos.get(id);
    const token = { kind, retrying, taken: false };
    memo.press = token;
    page.pressNotice = null;
    paint();
    plan();
    const response = await post(`${API}/${encodeURIComponent(id)}/${kind}`);
    if (memo.press === token) memo.press = null;
    if (!response && !token.taken) memo.unconfirmed = token;
    await answerOf(id, memo, response, retrying);
  }

  async function forceStop(id) {
    const memo = memos.get(id);
    memo.forcing = { at: Date.now(), answered: false };
    page.pressNotice = null;
    paint();
    plan();
    const response = await post(`${API}/${encodeURIComponent(id)}/off?force=1`);
    if (memo.forcing) {
      if (response && response.ok) memo.forcing.answered = true;
      else memo.forcing = null;
    }
    await answerOf(id, memo, response, false);
  }

  function askThomas(id) {
    const row = rows.get(id);
    const reason = row.error ? `The reason recorded was: ${row.error}.` : 'No reason was recorded.';
    const draft = `${row.title || UNNAMED} didn't start. ${reason} What does that mean, and what should I do?`;
    window.parent.postMessage({ type: 'thomas:workspace-chat:open', mode: 'settings', draft }, window.location.origin);
  }

  function rememberedOpen() {
    try {
      return window.sessionStorage.getItem(ADVANCED_KEY) === '1';
    } catch (error) {
      return false; // storage can be blocked, and the list then starts closed
    }
  }

  function remember(open) {
    try {
      window.sessionStorage.setItem(ADVANCED_KEY, open ? '1' : '0');
    } catch (error) {
      // Not remembered, which is all that is lost.
    }
  }

  // One list for every plugin until the sets arrive, and then one under each heading they came with.
  function groupList(title, about) {
    const known = parts.groups.get(title);
    if (known) return known;
    const section = element('section', 'plugin-group');
    const list = element('ul', 'plugin-rows');
    list.setAttribute('aria-label', title);
    section.append(element('h4', 'plugin-group-title', title), element('p', 'plugin-group-about', about || ''), list);
    parts.advanced.append(section);
    const made = { section, list };
    parts.groups.set(title, made);
    return made;
  }

  function showGroups(groups) {
    if (groups) {
      for (const group of groups) groupList(group.title, group.about);
    }
    for (const made of parts.groups.values()) made.section.hidden = !groups;
  }

  function placeRow(id, groups) {
    const view = views.get(id);
    let home = parts.list;
    if (groups) {
      const group = groups.find((item) => item.rows.includes(id));
      home = (group ? groupList(group.title, group.about) : groupList(OTHER_GROUP, '')).list;
    }
    if (view.home !== home) {
      home.append(view.node);
      view.home = home;
    }
  }

  // With sets on offer the long list is folded away until you ask for it. With none, it is the page, as it always was,
  // and while it is not yet known which, nothing shows rather than a list that then folds.
  function paintAdvanced(groups) {
    const withSets = Boolean(extras) && extras.available();
    const settling = Boolean(extras) && extras.settling();
    const open = withSets ? advancedOpen : !settling;
    parts.toggle.hidden = !withSets || page.connection === 'elsewhere';
    parts.toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    parts.advanced.hidden = !open || !rows.size || page.connection === 'elsewhere';
    parts.list.hidden = Boolean(groups);
  }

  function buildPage(host) {
    const root = element('div', 'plugins-panel');
    const summary = element('div', 'plugins-summary');
    const notices = element('div', 'plugins-notices');
    const waiting = element('div', 'loading-state', 'Reading your plugins...');
    const list = element('ul', 'plugin-rows');
    const advanced = element('div', 'plugins-advanced');
    const toggle = button('btn btn-secondary plugins-advanced-toggle', ADVANCED, () => {
      advancedOpen = !advancedOpen;
      remember(advancedOpen);
      paint();
    });
    const foot = element('div', 'plugins-foot', 'Marketplace is where to find new things.');
    const status = element('div', 'sr-only');
    list.setAttribute('aria-label', 'Plugins');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.setAttribute('aria-atomic', 'true');
    summary.hidden = true;
    notices.hidden = true;
    list.hidden = true;
    foot.hidden = true;
    advanced.id = 'plugins-advanced';
    toggle.setAttribute('aria-controls', advanced.id);
    toggle.setAttribute('aria-expanded', 'false');
    toggle.hidden = true;
    advanced.hidden = true;
    advanced.append(list);
    if (extras) root.append(extras.top);
    root.append(summary, notices, waiting, toggle, advanced, foot, status);
    host.append(root);
    return { root, summary, notices, waiting, list, advanced, toggle, groups: new Map(), foot, status };
  }

  function watchPanel(panel) {
    document.addEventListener('visibilitychange', () => (watching() ? read() : plan()));
    if (typeof IntersectionObserver !== 'function') {
      inView = true;
      read();
      return;
    }
    new IntersectionObserver((entries) => {
      const wasInView = inView;
      inView = entries[entries.length - 1].isIntersecting;
      if (wasInView && !inView && page.pressNotice) {
        page.pressNotice = null; // it answered a press you have left behind
        paint();
      }
      if (inView && !wasInView) read();
      else plan();
    }).observe(panel);
  }

  function start() {
    const host = document.getElementById('pluginsHost');
    if (!host) return;
    const make = window.thomasPluginSets && window.thomasPluginSets.create;
    advancedOpen = rememberedOpen();
    extras = make ? make({ element, button, rows, onChange: read, onLayout: paint }) : null;
    parts = buildPage(host);
    if (new URLSearchParams(window.location.search).get('section') === 'plugins' && typeof switchSection === 'function') {
      switchSection('plugins');
    }
    watchPanel(document.getElementById('plugins'));
  }

  // After script01's own DOMContentLoaded work, which binds the generic switch click: rows come later, from a fetch, so
  // that click is never bound to them.
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());
