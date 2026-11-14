/* Settings > Plugins: the ready-made sets and the Pause control, which sit above the long list.

   The panel's own script (settings.plugins-panel.js) builds the list of every plugin and asks this one for the rest. A
   set is a button, not a hundred switches: it asks first how many plugins it will turn on and off, and then does it.
   Nothing here loops. Sets are fetched once each time the plugin that serves them comes on, and Pause is read when the
   panel reads, and never again once Thomas has said there is no such thing. Every word is set as text.
*/
(function pluginSets() {
  'use strict';

  const SETS = '/api/plugins/sets';
  const PAUSE = '/api/thomas/pause';
  const RESUME = '/api/thomas/resume';
  const SERVES_SETS = 'plugin_sets';
  const HEADERS = { Accept: 'application/json' };
  const ELSEWHERE = 'You can change these only on the computer Thomas runs on.';
  const FAILED = "Thomas couldn't do that. Try again.";
  const GONE = "That set isn't available any more.";

  function plural(count, one, many) {
    return `${count} ${count === 1 ? one : many}`;
  }

  function create({ element, button, rows, onChange, onLayout }) {
    const top = element('div', 'plugins-top');
    const bar = element('div', 'plugins-pause');
    const barText = element('span', 'plugins-pause-text');
    const barButton = button('btn btn-secondary', 'Pause', () => pressPause());
    const barNote = element('span', 'plugins-pause-note');
    const setsBox = element('div', 'plugin-sets');
    const heading = element('h3', 'plugins-heading', 'Pick a ready-made set');
    const cards = element('ul', 'plugin-set-cards');
    const state = { sets: null, groups: null, tried: false, loading: false, busy: null };
    const pause = { gone: false, known: false, paused: false, still: 0, reading: false, pressing: false };
    const memos = new Map(); // set id to { stage: 'idle' | 'asking' | 'working', result: '' }
    const views = new Map();
    bar.append(barText, barButton, barNote);
    setsBox.append(heading, cards);
    bar.hidden = true;
    setsBox.hidden = true;
    top.append(bar, setsBox);

    async function getJson(url) {
      try {
        const response = await fetch(url, { headers: HEADERS, cache: 'no-store' });
        const body = response.ok ? await response.json().catch(() => null) : null;
        return { status: response.status, body };
      } catch (error) {
        return { status: 0, body: null };
      }
    }

    // Counts what applying a set would change, the way the server decides it: a plugin that cannot be turned off, and the
    // one that serves the sets, are never touched.
    function changesOf(chosen) {
      let turnOn = 0;
      let turnOff = 0;
      for (const [id, row] of rows) {
        if (id === SERVES_SETS || row.required) continue;
        const wanted = chosen.rows.includes(id);
        if (wanted && (row.enabled === false || row.state === 'failed')) turnOn += 1;
        if (!wanted && row.enabled !== false) turnOff += 1;
      }
      return { turnOn, turnOff };
    }

    function titleOf(id) {
      const row = rows.get(id);
      return (row && row.title) || 'A part of Thomas';
    }

    function listed(items) {
      return items.map((item) => `${titleOf(item.id)} (${item.why})`).join(' ');
    }

    function resultOf(answer) {
      const parts = [`Done. Turned on ${answer.turned_on.length}, turned off ${answer.turned_off.length}.`];
      const kept = answer.left_alone.filter((item) => item.id !== SERVES_SETS);
      if (kept.length) parts.push(`Left alone: ${listed(kept)}`);
      if (answer.failed.length) parts.push(`Could not change: ${listed(answer.failed)}`);
      return parts.join(' ');
    }

    async function applySet(chosen, memo) {
      memo.stage = 'working';
      memo.result = '';
      state.busy = chosen.id;
      paintSets();
      let result = FAILED;
      try {
        const response = await fetch(`${SETS}/${encodeURIComponent(chosen.id)}/apply`, { method: 'POST', headers: HEADERS });
        if (response.status === 401 || response.status === 403) result = ELSEWHERE;
        else if (response.status === 404) result = GONE;
        else if (response.ok) {
          const answer = await response.json().catch(() => null);
          if (answer && Array.isArray(answer.turned_on) && Array.isArray(answer.turned_off)) {
            answer.left_alone = Array.isArray(answer.left_alone) ? answer.left_alone : [];
            answer.failed = Array.isArray(answer.failed) ? answer.failed : [];
            result = resultOf(answer);
          }
        }
      } catch (error) {
        result = FAILED;
      }
      memo.stage = 'idle';
      memo.result = result;
      state.busy = null;
      paintSets();
      onChange();
    }

    function buildCard(chosen) {
      const memo = { stage: 'idle', result: '' };
      memos.set(chosen.id, memo);
      const node = element('li', 'plugin-set-card');
      const title = element('h4', 'plugin-set-title', chosen.title);
      const about = element('p', 'plugin-set-about', chosen.about);
      const ask = element('p', 'plugin-set-ask');
      const note = element('p', 'plugin-set-note');
      const apply = button('btn btn-primary', 'Apply', () => {
        memo.stage = 'asking';
        memo.result = '';
        paintSets();
        views.get(chosen.id).go.focus();
      });
      const go = button('btn btn-primary', 'Go', () => applySet(chosen, memo));
      const cancel = button('btn btn-secondary', 'Cancel', () => {
        memo.stage = 'idle';
        paintSets();
        apply.focus();
      });
      const actions = element('div', 'plugin-set-actions');
      actions.append(apply, go, cancel);
      node.append(title, about, ask, actions, note);
      cards.append(node);
      return { node, ask, note, apply, go, cancel };
    }

    function paintCard(chosen) {
      if (!views.has(chosen.id)) views.set(chosen.id, buildCard(chosen));
      const view = views.get(chosen.id);
      const memo = memos.get(chosen.id);
      const { turnOn, turnOff } = changesOf(chosen);
      const same = turnOn + turnOff === 0;
      const asking = memo.stage === 'asking' && !same;
      const working = memo.stage === 'working';
      const held = document.activeElement;
      view.ask.textContent = asking ? `This turns on ${plural(turnOn, 'plugin', 'plugins')} and turns off ${turnOff}. Go?` : '';
      view.ask.hidden = !asking;
      view.apply.hidden = asking || working;
      view.go.hidden = !asking;
      view.cancel.hidden = !asking;
      view.apply.setAttribute('aria-disabled', same || state.busy ? 'true' : 'false');
      let note = memo.result;
      if (working) note = 'Working on it...';
      else if (same && !note) note = 'Things are already set up like this.';
      view.note.textContent = note;
      view.note.hidden = !note;
      if (memo.stage === 'asking' && same) memo.stage = 'idle';
      if (held && held.hidden && view.node.contains(held)) (view.apply.hidden ? view.go : view.apply).focus();
    }

    function paintSets() {
      const ready = Array.isArray(state.sets) && state.sets.length > 0;
      setsBox.hidden = !ready;
      if (ready) state.sets.forEach(paintCard);
    }

    async function readSets() {
      state.loading = true;
      const { status, body } = await getJson(SETS);
      state.loading = false;
      if (status === 200 && body && Array.isArray(body.sets)) {
        state.sets = body.sets.filter((item) => item && typeof item.id === 'string' && Array.isArray(item.rows));
        state.groups = Array.isArray(body.groups) ? body.groups.filter((group) => group && Array.isArray(group.rows)) : [];
        state.tried = true;
      } else if (status !== 0) {
        state.tried = true; // an answer that is not a set list will not change by asking again
      }
      paintSets();
      onLayout();
    }

    function paintPause() {
      bar.hidden = !pause.known || pause.gone;
      if (bar.hidden) return;
      const finishing = pause.still > 0 ? ` (${plural(pause.still, 'run', 'runs')} still finishing)` : '';
      barText.textContent = pause.paused ? `Thomas is paused${finishing}` : 'Thomas is working';
      barButton.textContent = pause.paused ? 'Resume' : 'Pause';
      barButton.setAttribute('aria-disabled', pause.pressing ? 'true' : 'false');
    }

    function takePause(body) {
      if (!body || typeof body.paused !== 'boolean') {
        pause.gone = true; // not the answer of a pause route, and asking again will not make it one
        return;
      }
      pause.known = true;
      pause.paused = body.paused;
      pause.still = Number.isFinite(body.still_running) ? body.still_running : 0;
    }

    async function readPause() {
      if (pause.gone || pause.reading || pause.pressing) return;
      pause.reading = true;
      const { status, body } = await getJson(PAUSE);
      pause.reading = false;
      if (status === 404) pause.gone = true;
      else if (status === 200) takePause(body);
      paintPause();
    }

    async function pressPause() {
      if (pause.pressing || pause.gone) return;
      pause.pressing = true;
      paintPause();
      try {
        const response = await fetch(pause.paused ? RESUME : PAUSE, { method: 'POST', headers: HEADERS });
        if (response.status === 404) pause.gone = true;
        else if (response.ok) takePause(await response.json().catch(() => null));
      } catch (error) {
        // Nothing changed, and the next read shows what is true.
      }
      pause.pressing = false;
      paintPause();
    }

    // Called after each read of the plugins, with how the page stands.
    function sync(connection) {
      const serving = rows.get(SERVES_SETS);
      const on = Boolean(serving) && serving.state === 'active';
      if (!on && (state.sets || state.tried)) {
        state.sets = null;
        state.groups = null;
        state.tried = false;
        paintSets();
        onLayout();
      } else if (on && !state.sets && !state.tried && !state.loading && connection === 'ok') {
        readSets();
      } else if (state.sets) {
        paintSets();
      }
      if (connection === 'ok') readPause();
      else if (pause.known) paintPause();
    }

    return {
      top,
      sync,
      // The plugin that serves the sets is on and has not answered yet, so the page cannot say which way to show the list.
      settling: () => {
        const serving = rows.get(SERVES_SETS);
        return Boolean(serving) && serving.state === 'active' && !state.tried;
      },
      available: () => Array.isArray(state.sets) && state.sets.length > 0,
      groups: () => (Array.isArray(state.groups) && state.groups.length ? state.groups : null),
    };
  }

  window.thomasPluginSets = { create };
}());
