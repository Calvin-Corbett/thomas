/* Who is working on a Build run, rebuilt from the run's own events.

   No route lists the agents on a live run, so the Activity drawer and the
   agent side chat learn them the same way the transcript does: from the frames.
   The lead's frames carry no `agent_id`. A task.spawn / task.team helper's
   frames carry `agent_id: child_<12hex>`, its title, its mode and a "[Title] "
   prefix on its text; its lifecycle exists only as text ("Spawned Scout",
   "Scout finished"). Server-run helpers send agent_spawned / agent_status /
   agent_event with an explicit `agent_state`. One `feed(event)` takes all of
   them, live or replayed from a saved turn, so both read the same. */
(function () {
  'use strict';

  const LEAD = 'lead';
  const VERIFIER = 'verifier';
  const FEED_LIMIT = 12;
  const HISTORY_LIMIT = 80;
  const REPLY_LIMIT = 1600;
  // Run-channel `agent_state` -> the drawer's five states.
  const STATE_OF = {
    running: 'working', retrying: 'working',
    starting: 'waiting', queued: 'waiting', quota_wait: 'waiting',
    completed: 'done', failed: 'failed',
    cancelled: 'stopped', stopped: 'stopped', interrupted: 'stopped',
  };
  const ENDED = new Set(['done', 'failed', 'stopped']);
  // Run-level frames say something about the run, not about one agent, so they
  // never create the lead on their own.
  const RUN_LEVEL = new Set(['done', 'stopped', 'disconnected', 'settings', 'approval', 'paused', 'resumed']);
  // Reports written after an agent's answer. They must not read as the agent
  // starting work again; anything else arriving after "finished" does.
  const AFTERWORD = new Set(['final', 'meta', 'acceptance', 'error', 'engine_debug', 'plan']);
  // Tool names as either engine writes them (GPT loop: fs.read_file; Claude
  // Code: Read). Compared lower-case with any "Title > " prefix removed.
  const EDIT_TOOLS = new Set(['fs.write_file', 'fs.write_protected_file', 'diff.create', 'diff.apply_patch',
    'write', 'edit', 'multiedit', 'notebookedit']);
  const READ_TOOLS = new Set(['fs.read_file', 'read', 'fs.list_dir', 'ls', 'glob', 'notebookread',
    'code.project_structure', 'diff.preview', 'diff.preview_patch']);
  const SEARCH_TOOLS = new Set(['fs.search', 'grep', 'code.search', 'code.semantic_search', 'code.find_definition',
    'code.find_references', 'code.repo_index', 'rag.search']);
  const DELEGATE_TOOLS = new Set(['task.spawn', 'task.team', 'task.spawn_agents', 'task',
    'mcp__thomas_praxis__spawn_agents']);
  const WAIT_TOOLS = new Set(['task.wait_agents', 'mcp__thomas_praxis__wait_agents']);
  const TEST_COMMAND = /(?:^|[\s;&|])(?:[\w./\\-]*[\\/])?(?:pytest|py\.test|tox|jest|vitest|mocha|npm\s+(?:run\s+)?test|node\s+--test|python(?:\d+(?:\.\d+)?)?\s+-m\s+pytest)(?:\s|$)/i;

  function kindOf(event) {
    const kind = event.kind || event.fc || (event.type && event.type !== 'output' ? event.type : '');
    return String(kind || '').toLowerCase();
  }

  function stamp(event) {
    const ts = Number(event.ts);
    return Number.isFinite(ts) && ts > 0 ? ts : Date.now();
  }

  // A team child's text arrives as "[Scout] read app.js"; a streamed reply
  // opens with "\n[Scout] " each time the speaker changes, so only that exact
  // title is removed and a reply that itself starts with "[" survives.
  function withoutTitle(text, title) {
    const raw = String(text || '');
    if (!title) return raw;
    for (const prefix of [`\n[${title}] `, `[${title}] `, `\n[${title}]`, `[${title}]`]) {
      if (raw.startsWith(prefix)) return raw.slice(prefix.length);
    }
    return raw;
  }

  function toolName(event) {
    return String(event.name || '').replace(/^.{1,80}? > /, '').trim().toLowerCase();
  }

  function baseName(path) {
    const parts = String(path || '').split('/');
    return parts[parts.length - 1] || String(path || '');
  }

  function clip(text, size) {
    const flat = String(text || '').replace(/\s+/g, ' ').trim();
    return flat.length > size ? `${flat.slice(0, size - 1)}…` : flat;
  }

  function count(value) {
    const number = Number(value);
    return Number.isInteger(number) && number >= 0 ? number : null;
  }

  function cleanPath(path) {
    return String(path || '').trim().replace(/\\/g, '/').replace(/^\.\//, '');
  }

  // What a tool line says about its file: the fields the backend adds (`path`,
  // `added`, `removed`) or, on transcripts written before them, the text the
  // tools already wrote. A start line's text is the argument summary ("path:
  // x"); a result's is the tool's own message ("Wrote N chars to x", "Replaced
  // N line(s) with M line(s) in x"). A read's result is the file itself, so it
  // is never searched for a path.
  function fileFacts(event, text, isStart) {
    let path = typeof event.path === 'string' ? event.path : '';
    let added = count(event.added);
    let removed = count(event.removed);
    if (isStart) {
      const named = /^(?:file_path|path|notebook_path): (.+)$/m.exec(text);
      if (!path && named) path = named[1];
    } else {
      const replaced = /^Replaced (\d+) line\(s\) with (\d+) line\(s\) in (.+)$/m.exec(text);
      const wrote = /^Wrote \d+ chars to (.+)$/m.exec(text);
      if (replaced) {
        if (removed === null) removed = Number(replaced[1]);
        if (added === null) added = Number(replaced[2]);
        if (!path) path = replaced[3];
      } else if (!path && wrote) {
        path = wrote[1];
      }
    }
    return { path: cleanPath(path), added, removed };
  }

  function argument(text, key) {
    const match = new RegExp(`^${key}: (.+)$`, 'm').exec(text);
    return match ? match[1].trim() : '';
  }

  // The spawn call's arguments, when its start line carried them: task.spawn
  // writes `{"title": "Scout", "instructions": "..."}` (cut at 200 characters),
  // task.team an `assignments` list of the same plus `path`.
  function spawnBriefs(text) {
    const briefs = [];
    String(text || '').split('{').forEach(chunk => {
      const field = key => {
        const match = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"?`).exec(chunk);
        if (!match) return '';
        try { return JSON.parse(`"${match[1].replace(/\\$/, '')}"`); } catch (error) { return match[1]; }
      };
      const title = field('title');
      if (title) briefs.push({ title, instructions: field('instructions'), path: field('path') });
    });
    return briefs;
  }

  // The feed verb, the action-line words, and whether the call reads or edits
  // the file it names.
  function describeTool(name, text, path) {
    const file = baseName(path);
    if (EDIT_TOOLS.has(name)) {
      const verb = name === 'fs.write_file' || name === 'write' ? 'write' : 'patch';
      return { verb, target: path, op: 'edit', action: file ? `Editing ${file}` : 'Editing a file' };
    }
    if (READ_TOOLS.has(name)) {
      return { verb: 'read', target: path, op: 'read', action: file ? `Reading ${file}` : 'Reading the code' };
    }
    if (SEARCH_TOOLS.has(name)) {
      const pattern = argument(text, 'pattern') || argument(text, 'query');
      return { verb: 'search', target: pattern ? `"${clip(pattern, 40)}"` : '', op: '', action: 'Searching the code' };
    }
    if (name === 'shell.exec' || name === 'bash' || name === 'powershell') {
      const command = argument(text, 'command');
      const tests = TEST_COMMAND.test(command);
      return { verb: 'run', target: clip(command, 60), op: '', action: tests ? 'Running tests' : 'Running a command' };
    }
    if (name === 'check.run' || name === 'run') {
      return { verb: 'check', target: clip(argument(text, 'command'), 60), op: '', action: 'Running checks' };
    }
    if (name === 'web.playtest') return { verb: 'playtest', target: '', op: '', action: 'Playtesting the page' };
    if (name.startsWith('browser.')) return { verb: 'browse', target: clip(argument(text, 'url'), 50), op: '', action: 'Using the browser' };
    if (name === 'web.search' || name === 'websearch' || name === 'webfetch' || name === 'http.client') {
      return { verb: 'web', target: clip(argument(text, 'query') || argument(text, 'url'), 50), op: '', action: 'Searching the web' };
    }
    if (DELEGATE_TOOLS.has(name)) {
      const titles = spawnBriefs(text).map(brief => brief.title);
      return { verb: 'spawn', target: titles.join(', '), op: '', action: titles.length ? `Handing work to ${titles.join(', ')}` : 'Handing out work' };
    }
    if (WAIT_TOOLS.has(name)) return { verb: 'wait', target: '', op: '', action: 'Waiting on helpers' };
    if (name === 'plan.update' || name === 'todo.write') return { verb: 'plan', target: '', op: '', action: 'Updating the plan' };
    if (name === 'ask.user' || name === 'ask_user') return { verb: 'ask', target: '', op: '', action: 'Asking you a question' };
    const short = name.replace(/^mcp__\w+?__/, '') || 'tool';
    return { verb: short, target: clip(String(text || '').split('\n')[0], 50), op: '', action: `Using ${short}` };
  }

  // A helper's lifecycle, which task.spawn records only as text.
  function lifecycleOf(text, title, isError) {
    if (text.startsWith(`Spawned ${title}`)) return { state: 'working', action: 'Starting' };
    if (text === `${title} finished`) return { state: 'done', action: 'Finished' };
    if (text === `${title} cancelled`) return { state: 'stopped', action: 'Cancelled' };
    if (isError && text.startsWith(`${title} failed: `)) {
      return { state: 'failed', action: `Failed: ${clip(text.slice(title.length + 9), 70)}` };
    }
    return null;
  }

  function roleFor(agent) {
    if (agent.id === LEAD) return 'lead';
    if (agent.mode === 'read_only') return 'read-only';
    if (agent.mode === 'builder') {
      const owned = [...agent.files.values()].filter(file => file.op === 'edit').map(file => file.path);
      if (owned.length) return owned.join(', ');
      return agent.ownedPath || 'builder';
    }
    return agent.mode || 'helper';
  }

  function plural(number, word) {
    return `${number} ${word}${number === 1 ? '' : 's'}`;
  }

  function create() {
    let agentsById = new Map();
    let order = [];
    let briefs = new Map();
    let reachable = new Set();
    let verifier = null;
    let plan = null;
    let paused = false;
    let editClock = 0;

    function reset() {
      agentsById = new Map();
      order = [];
      briefs = new Map();
      plan = null;
      paused = false;
      editClock = 0;
    }

    function ensure(id, ts) {
      let agent = agentsById.get(id);
      if (agent) return agent;
      agent = {
        id, name: id === LEAD ? 'Thomas' : 'Helper', mode: id === LEAD ? 'lead' : '', model: '',
        state: 'working', action: '', startedAt: ts, lastAt: ts, endedAt: null,
        files: new Map(), history: [], brief: '', ownedPath: '', pending: [],
        openReply: null, delegations: 0, askOpen: false,
      };
      agentsById.set(id, agent);
      if (id === LEAD) order.unshift(id); else order.push(id);
      return agent;
    }

    function setState(agent, state, ts) {
      if (ENDED.has(state)) {
        if (!ENDED.has(agent.state) || agent.endedAt === null) agent.endedAt = ts;
        agent.pending = [];
        agent.delegations = 0;
      } else {
        agent.endedAt = null;
      }
      agent.state = state;
    }

    function push(agent, entry) {
      agent.openReply = null;
      agent.history.push(entry);
      if (agent.history.length > HISTORY_LIMIT) agent.history.splice(0, agent.history.length - HISTORY_LIMIT);
      return entry;
    }

    function attachBrief(agent) {
      const brief = briefs.get(agent.name.toLowerCase());
      if (!brief) return;
      if (!agent.brief && brief.instructions) agent.brief = brief.instructions;
      if (!agent.ownedPath && brief.path) agent.ownedPath = cleanPath(brief.path);
    }

    // An edit claims its file as soon as it starts (that is the moment the
    // agent is working on it); its line counts land when the result does.
    function noteFile(agent, facts, op, ts) {
      if (!facts.path) return;
      const file = agent.files.get(facts.path) || { path: facts.path, added: null, removed: null, op: 'read', editedAt: 0 };
      if (op === 'edit') {
        file.op = 'edit';
        editClock += 1;
        file.editedAt = editClock;
        if (facts.added !== null) file.added = (file.added || 0) + facts.added;
        if (facts.removed !== null) file.removed = (file.removed || 0) + facts.removed;
      }
      file.at = ts;
      agent.files.set(facts.path, file);
    }

    // "+9 −1", or just "+31" for a new file: a zero says nothing.
    function feedLine(info, facts) {
      const target = info.op ? (facts.path || info.target) : info.target;
      const counts = [facts.added ? `+${facts.added}` : '', facts.removed ? `−${facts.removed}` : ''].filter(Boolean).join(' ');
      return `${info.verb}${target ? ` ${target}` : ''}${counts ? ` · ${counts}` : ''}`;
    }

    function toolStart(agent, event, text, ts) {
      const name = toolName(event);
      const facts = fileFacts(event, text, true);
      const info = describeTool(name, text, facts.path);
      if (DELEGATE_TOOLS.has(name)) {
        spawnBriefs(text).forEach(brief => {
          briefs.set(brief.title.toLowerCase(), brief);
          order.forEach(id => {
            const other = agentsById.get(id);
            if (other.name.toLowerCase() === brief.title.toLowerCase()) attachBrief(other);
          });
        });
      }
      if (DELEGATE_TOOLS.has(name) || WAIT_TOOLS.has(name)) agent.delegations += 1;
      if (info.op === 'edit') noteFile(agent, { path: facts.path, added: null, removed: null }, 'edit', ts);
      agent.action = info.action;
      const line = push(agent, { text: feedLine(info, facts), kind: 'tool', ts, ok: null });
      agent.pending.push({ name, info, facts, line });
    }

    // Calls can run in parallel and finish in any order, so a result closes the
    // open call with its name (and path, when both say one), oldest first.
    function takePending(agent, name, path) {
      const fits = call => (!name || !call.name || call.name === name) && (!path || !call.facts.path || call.facts.path === path);
      const index = agent.pending.findIndex(fits);
      return index < 0 ? null : agent.pending.splice(index, 1)[0];
    }

    function toolResult(agent, event, text, ts) {
      const name = toolName(event);
      const own = fileFacts(event, text, false);
      const call = takePending(agent, name, own.path);
      const facts = {
        path: own.path || (call ? call.facts.path : ''),
        added: own.added !== null ? own.added : (call ? call.facts.added : null),
        removed: own.removed !== null ? own.removed : (call ? call.facts.removed : null),
      };
      const info = call ? call.info : describeTool(name, text, facts.path);
      const ok = !event.is_error;
      if (info.op === 'edit' && ok) noteFile(agent, facts, 'edit', ts);
      else if (info.op) noteFile(agent, facts, 'read', ts);
      if (call) {
        call.line.text = feedLine(info, facts);
        call.line.ok = ok;
        call.line.ts = ts;
      } else {
        push(agent, { text: feedLine(info, facts), kind: 'tool', ts, ok });
        if (!agent.action) agent.action = info.action;
      }
      const callName = call ? call.name : name;
      if (DELEGATE_TOOLS.has(callName) || WAIT_TOOLS.has(callName)) agent.delegations = Math.max(0, agent.delegations - 1);
      agent.openReply = null;
    }

    function reply(agent, event, text, ts) {
      if (!text.trim() && !agent.openReply) return;
      if (event.delta && agent.openReply) {
        agent.openReply.text = `${agent.openReply.text}${text}`.slice(0, REPLY_LIMIT);
        agent.openReply.ts = ts;
      } else {
        const entry = push(agent, { text: text.trimStart().slice(0, REPLY_LIMIT), kind: 'reply', ts, ok: true });
        if (event.delta) agent.openReply = entry;
      }
      agent.action = agent.id === LEAD ? 'Writing to you' : 'Writing its report';
    }

    // The run ended. A stop ends everyone; a finished run's `done` frame
    // finishes the lead, and anyone still marked busy simply never said so. A
    // run that FAILED did not stop because you asked: its lead, and whoever
    // was still at it, read as failed.
    function settleRun(kind, event, ts) {
      const failed = kind === 'done' && event.ok === false;
      order.forEach(id => {
        const agent = agentsById.get(id);
        if (ENDED.has(agent.state)) return;
        if (kind === 'done' && id === LEAD && !failed) {
          setState(agent, 'done', ts);
          agent.action = 'Finished';
          return;
        }
        setState(agent, failed ? 'failed' : 'stopped', ts);
        agent.action = !failed ? 'Stopped' : id === LEAD ? 'Failed' : 'Ended when the run failed';
      });
      paused = false;
    }

    // An answer streamed as `say` deltas arrives again whole as `final` (a
    // helper's as `meta`): one answer, one entry.
    function answerEntry(agent, text, ts) {
      const body = text.trim().slice(0, REPLY_LIMIT);
      const last = [...agent.history].reverse().find(entry => entry.kind === 'reply');
      if (last && last.text.trim() === body) {
        Object.assign(last, { text: body, ts });
        agent.openReply = null;
        return;
      }
      push(agent, { text: body, kind: 'reply', ts, ok: true });
    }

    function helperMeta(agent, event, text, ts) {
      const life = lifecycleOf(text, agent.name, Boolean(event.is_error));
      if (life) {
        setState(agent, life.state, ts);
        agent.action = life.action;
        if (life.state === 'failed') push(agent, { text: clip(text, 160), kind: 'error', ts, ok: false });
      } else if (event.is_error) {
        push(agent, { text: clip(text, 160), kind: 'error', ts, ok: false });
      } else {
        // The helper's own answer, demoted to `meta` so it cannot settle the lead.
        answerEntry(agent, text, ts);
      }
    }

    function feed(event) {
      if (!event || typeof event !== 'object') return;
      const kind = kindOf(event);
      const ts = stamp(event);
      if (kind === 'paused') { paused = true; return; }
      if (kind === 'resumed') { paused = false; return; }
      if (kind === 'done' || kind === 'stopped') { settleRun(kind, event, ts); return; }
      if (RUN_LEVEL.has(kind) || !kind) return;
      if (kind === 'plan' && Array.isArray(event.items)) plan = { items: event.items, ts };
      const id = event.agent_id ? String(event.agent_id) : LEAD;
      const agent = ensure(id, ts);
      if (ts < agent.startedAt) agent.startedAt = ts;
      agent.lastAt = Math.max(agent.lastAt, ts);
      if (id !== LEAD) {
        const title = String(event.agent_title || '').trim();
        if (title && title !== agent.name) { agent.name = title; attachBrief(agent); }
        if (event.agent_mode) agent.mode = String(event.agent_mode);
        if (typeof event.brief === 'string' && event.brief.trim()) agent.brief = event.brief.trim();
      }
      if (event.model) agent.model = String(event.model);
      const text = id === LEAD ? String(event.text || '') : withoutTitle(event.text, agent.name);
      const explicit = STATE_OF[String(event.agent_state || '')];
      if (explicit) {
        setState(agent, explicit, ts);
        if (explicit === 'waiting') agent.action = event.agent_state === 'quota_wait' ? 'Waiting for the provider' : 'Waiting to start';
        if (explicit === 'done') agent.action = 'Finished';
        if (explicit === 'stopped') agent.action = 'Stopped';
        if (explicit === 'failed') agent.action = 'Failed';
      } else if (ENDED.has(agent.state) && !AFTERWORD.has(kind) && !event.receipt) {
        // Frames after "finished" mean the agent is at it again: a Build run
        // can take another pass after the lead's first answer.
        setState(agent, 'working', ts);
      }

      if (event.receipt === 'model') return;
      if (kind === 'tool_started' || kind === 'tool') {
        toolStart(agent, event, text, ts);
      } else if (kind === 'tool_result') {
        toolResult(agent, event, text, ts);
      } else if (kind === 'say') {
        reply(agent, event, text, ts);
      } else if (kind === 'reason' || kind === 'insight') {
        agent.action = 'Thinking it through';
      } else if (kind === 'final') {
        if (text.trim()) answerEntry(agent, text, ts);
        if (id === LEAD) { setState(agent, 'done', ts); agent.action = 'Finished'; }
      } else if (kind === 'steering') {
        push(agent, { text: 'read your message', kind: 'steer', ts, ok: true });
        agent.action = 'Reading your message';
      } else if (kind === 'ask') {
        agent.askOpen = true;
      } else if (kind === 'answered') {
        agent.askOpen = false;
        agent.action = 'Got your answer';
      } else if (kind === 'error') {
        push(agent, { text: clip(text || 'Something went wrong', 160), kind: 'error', ts, ok: false });
      } else if (kind === 'agent_spawned') {
        if (!agent.action) agent.action = 'Starting';
      } else if (kind === 'agent_event' && text.trim()) {
        push(agent, { text: clip(text, 160), kind: event.is_error ? 'error' : 'note', ts, ok: !event.is_error });
        if (!ENDED.has(agent.state)) agent.action = clip(text, 70);
      } else if (kind === 'meta' && id !== LEAD && text.trim()) {
        helperMeta(agent, event, text.trim(), ts);
      } else if (kind === 'planning' && id === LEAD) {
        agent.action = event.team_progress ? 'Coordinating the team' : agent.action || 'Planning';
      }
    }

    function planStep() {
      if (!plan || !plan.items.length) return '';
      const items = plan.items;
      const current = items.findIndex(item => item && item.status === 'in_progress');
      const done = items.filter(item => item && item.status === 'completed').length;
      const step = current >= 0 ? current + 1 : Math.min(done + 1, items.length);
      return `step ${step} of ${items.length}`;
    }

    function leadAction(agent, helpers) {
      if (agent.askOpen) return 'Waiting on you';
      const busy = helpers.filter(helper => helper.state === 'working' || helper.state === 'waiting');
      if (!agent.delegations || !busy.length) return agent.action;
      const step = planStep();
      if (step) return `Coordinating · ${step}`;
      if (busy.length > 2) return `Waiting on ${plural(busy.length, 'helper')}`;
      return `Waiting on ${busy.map(helper => helper.name).join(' and ')}`;
    }

    function view(agent, now, helpers) {
      const ended = ENDED.has(agent.state);
      let state = agent.state;
      let action = agent.action || (ended ? 'Finished' : 'Starting');
      if (!ended && agent.id === LEAD) action = leadAction(agent, helpers) || action;
      // A helper that finished says what it found ("Found 3 hard-coded
      // colours"), which is the line worth reading in the list.
      if (agent.state === 'done' && agent.id !== LEAD) {
        const report = [...agent.history].reverse().find(entry => entry.kind === 'reply' && entry.text.trim());
        if (report) action = clip(report.text.split('\n').find(line => line.trim()), 80);
      }
      if (!ended && agent.askOpen) state = 'waiting';
      if (!ended && paused) { state = 'waiting'; action = 'Paused'; }
      const files = [...agent.files.values()].map(file => ({ path: file.path, added: file.added, removed: file.removed, op: file.op }));
      const history = agent.history.map(entry => ({ ...entry }));
      return {
        id: agent.id,
        name: agent.name,
        role: roleFor(agent),
        model: agent.model,
        state,
        action,
        startedAt: agent.startedAt,
        lastAt: agent.lastAt,
        elapsedMs: Math.max(0, (ended ? (agent.endedAt || agent.lastAt) : now) - agent.startedAt),
        files,
        feed: history.slice(-FEED_LIMIT),
        history,
        brief: agent.brief,
        reachable: reachable.has(agent.id),
      };
    }

    function agents() {
      const now = Date.now();
      const list = order.map(id => agentsById.get(id));
      const helpers = list.filter(agent => agent.id !== LEAD);
      const out = list.map(agent => view(agent, now, helpers));
      if (verifier) {
        const ended = ENDED.has(verifier.state);
        out.push({
          id: VERIFIER, name: 'Verifier', role: 'separate evaluator', model: '', state: verifier.state,
          action: verifier.note || (verifier.state === 'waiting' ? 'Waiting for the work to land' : ''),
          startedAt: verifier.startedAt, lastAt: verifier.lastAt,
          elapsedMs: Math.max(0, (ended ? verifier.lastAt : now) - verifier.startedAt),
          files: [], feed: [], history: [], brief: '', reachable: false,
        });
      }
      return out;
    }

    // A file an agent edited is held while that agent works and released once
    // it is done. Two agents on one file: the most recent editor holds it.
    function claims() {
      const latest = new Map();
      order.forEach(id => {
        const agent = agentsById.get(id);
        agent.files.forEach(file => {
          if (file.op !== 'edit') return;
          const held = latest.get(file.path);
          if (!held || held.editedAt < file.editedAt) {
            latest.set(file.path, { agent, editedAt: file.editedAt, first: held ? held.first : file.editedAt });
          }
        });
      });
      return [...latest.entries()]
        .sort((a, b) => a[1].first - b[1].first)
        .map(([path, claim]) => ({
          path,
          agentId: claim.agent.id,
          agentName: claim.agent.name,
          state: ENDED.has(claim.agent.state) ? 'released' : 'held',
        }));
    }

    function setVerifier(next) {
      if (!next) { verifier = null; return; }
      const now = Date.now();
      const state = ['working', 'done', 'waiting', 'failed', 'stopped'].includes(next.state) ? next.state : 'waiting';
      if (!verifier) verifier = { startedAt: now, lastAt: now, ended: false };
      if (!verifier.ended || !ENDED.has(state)) verifier.lastAt = now;
      verifier.state = state;
      verifier.ended = ENDED.has(state);
      verifier.note = String(next.note || '');
    }

    function setReachable(ids) {
      reachable = new Set((Array.isArray(ids) ? ids : []).map(String));
    }

    // Changes whenever something the drawer or side chat shows changes, and
    // never just because a clock moved, so a caller can skip identical repaints.
    function snapshotKey() {
      return JSON.stringify(agents().map(agent => {
        const last = agent.history[agent.history.length - 1];
        return [agent.id, agent.name, agent.role, agent.state, agent.action, agent.reachable, agent.brief.length,
          agent.files.map(file => `${file.path}:${file.op}:${file.added}:${file.removed}`).join('|'),
          agent.history.length, last ? `${last.ok}:${last.text.length}:${last.text.slice(-24)}` : ''];
      }).concat([paused, claims().map(claim => claim.state).join('')]));
    }

    return {
      reset,
      feed,
      agents,
      claims,
      count: () => order.length,
      working: () => agents().filter(agent => agent.state === 'working' || agent.state === 'waiting').length,
      setVerifier,
      setReachable,
      snapshotKey,
    };
  }

  // A saved turn's transcript, as the frames feed() takes: its JSON lines that
  // name a kind. A line of plain output names no agent.
  function linesOf(text) {
    const lines = [];
    String(text || '').split('\n').forEach(raw => {
      const line = raw.trim();
      if (!line.startsWith('{')) return;
      try {
        const parsed = JSON.parse(line);
        if (parsed && parsed.fc) lines.push(parsed);
      } catch (error) { /* not a frame */ }
    });
    return lines;
  }

  // The Verifier's card on a saved turn ({state, note} for setVerifier), from
  // its report's per-ask rows; null when no ask was judged.
  const RUN_ROW = 'the run finished without error';
  function verifierFrom(report) {
    const asked = (report && Array.isArray(report.rubric_mapping) ? report.rubric_mapping : [])
      .filter(row => row && String(row.criterion || '').trim() && String(row.criterion).trim().toLowerCase() !== RUN_ROW);
    const judged = asked.filter(row => row.status === 'met' || row.status === 'not_met');
    if (!judged.length) return null;
    const failed = judged.filter(row => row.status === 'not_met').length;
    const asks = asked.length === 1 ? 'ask' : 'asks';
    return failed
      ? { state: 'failed', note: `${failed} of ${asked.length} ${asks} failed` }
      : { state: 'done', note: `Checked ${judged.length} of ${asked.length} ${asks}` };
  }

  window.ThomasCodeRoster = { create, linesOf, verifierFrom };
})();
