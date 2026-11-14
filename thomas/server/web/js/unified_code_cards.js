/* The pieces a Build conversation is drawn from (window.ThomasCodeCards).
 *
 * The 2026-10 Build redesign reads as a conversation: what you and Thomas say
 * is bright prose, and the work underneath it is dim, one-line, mono. This
 * module is every piece of that page that is not prose: the Thomas head, the
 * STEPS card, the work rows, the steer chip, the live diff, the Verifier's
 * proof card, the ask-the-user card, and the
 * actions under a deliverable.
 *
 * Markup only. Nothing here fetches, keeps state or binds a click: callers hand
 * in `esc` and plain data, and every control carries a data-* hook that the
 * module owning the action binds. The escaper is injected, never copied -- two
 * escapers is how one of them stops escaping.
 */
(function () {
  'use strict';

  const MINUS = '\u2212';

  function count(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : null;
  }

  function firstLine(value, max) {
    const line = String(value == null ? '' : value).split('\n').map(part => part.trim()).find(Boolean) || '';
    const limit = max || 96;
    return line.length > limit ? `${line.slice(0, limit - 1).trimEnd()}…` : line;
  }

  function kindOf(ev) {
    return String((ev && (ev.kind || ev.fc || ev.type)) || 'output').toLowerCase();
  }

  // 0.4s, 9s, 1m 48s, 2h 5m -- the way the design writes how long something took.
  function durationLabel(ms) {
    const n = Number(ms);
    if (!Number.isFinite(n) || n < 0) return '';
    if (n < 100) return '<0.1s';
    if (n < 950) return `${(n / 1000).toFixed(1)}s`;
    const seconds = Math.round(n / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  // "+9 −1" with each half in its own ink. Digits only, so nothing to escape.
  function changeHtml(added, removed) {
    const a = count(added);
    const r = count(removed);
    const parts = [];
    if (a) parts.push(`<span class="tc-code-add">+${a}</span>`);
    if (r) parts.push(`<span class="tc-code-del">${MINUS}${r}</span>`);
    return parts.join(' ');
  }

  // ---------------------------------------------------------------- the head

  // A plain "Thomas" name with one dim sans line of meta: "thought
  // 14s", "4 agents · 1m 48s", "working". `metaTitle` keeps whatever the meta
  // replaced (the exact model that answered) one hover away.
  function headHtml({ esc, meta, metaTitle, copy, extraHtml } = {}) {
    // Which model actually answered stays one hover away on the name: nothing beside it, nothing lost.
    const title = metaTitle ? ` title="${esc(metaTitle)}"` : '';
    const copyButton = copy
      ? '<button class="tc-code-copy" data-code-copy-reply type="button" aria-label="Copy Thomas reply">Copy</button>'
      : '';
    return `<div class="tc-code-message-head"><strong${title}>Thomas</strong>${extraHtml || ''}${copyButton}</div>`;
  }

  // ---------------------------------------------------------- the STEPS card

  const PLAN_STATES = new Set(['pending', 'in_progress', 'completed', 'blocked']);

  function planItems(plan) {
    const raw = plan && Array.isArray(plan.items) ? plan.items : [];
    return raw
      .filter(item => item && typeof item.text === 'string' && item.text.trim())
      .slice(0, 30)
      .map(item => ({ ...item, status: PLAN_STATES.has(item.status) ? item.status : 'pending' }));
  }

  // "4 of 5" names the step being worked on, so an in-progress step counts; the
  // bar shows only what is finished.
  function planProgress(plan) {
    const items = planItems(plan);
    const done = items.filter(item => item.status === 'completed').length;
    const active = items.some(item => item.status === 'in_progress');
    return { items, done, total: items.length, current: Math.min(items.length, done + (active ? 1 : 0)) };
  }

  function stepsHtml({ esc, plan } = {}) {
    const { items, done, total, current } = planProgress(plan);
    if (!total) return '';
    const rows = items.map(item => {
      const started = Number(item.started_at);
      const ended = Number(item.done_at);
      const took = item.status === 'completed' && Number.isFinite(started) && Number.isFinite(ended) && started > 0 && ended >= started
        ? durationLabel(ended - started) : '';
      const time = item.status === 'in_progress' ? 'now' : (item.status === 'blocked' ? 'blocked' : took);
      return `<li class="tc-code-plan-row is-${item.status}"><span class="tc-code-plan-mark" title="${item.status.replace('_', ' ')}" aria-hidden="true">${item.status === 'completed' ? '✓' : ''}</span>`
        + `<span class="tc-code-plan-text">${esc(item.text.trim())}</span>`
        + `<span class="tc-code-plan-owner">${esc(String(item.owner || '').trim())}</span>`
        + `<span class="tc-code-plan-time">${esc(time)}</span></li>`;
    }).join('');
    const width = Math.round((done / total) * 100);
    return `<section class="tc-code-plan" aria-label="Steps, ${current} of ${total}"><header class="tc-code-plan-head"><span class="tc-code-plan-label">Steps</span><span class="tc-code-plan-bar" aria-hidden="true"><span style="width:${width}%"></span></span><span class="tc-code-plan-count">${current} of ${total}</span></header><ol class="tc-code-plan-rows">${rows}</ol></section>`;
  }

  // ------------------------------------------------------------- work rows

  // The verb column. Matched against the tool's own name with any "Title > "
  // prefix a team child adds stripped off. Order matters: TodoWrite is planning
  // before it is a write, and diff.preview_patch is a preview before it is a patch.
  const TOOL_VERBS = [
    [/^(?:run|check[._-]?run)$/, 'Checked'],
    [/playtest/, 'Tested'],
    [/^browser[._-]/, 'Browsed'],
    [/todo|^goal[._-]/, 'Planned'],
    [/preview/, 'Compared'],
    [/(?:^|[._-])(?:read_file|read|view|cat|notebookread)$/, 'Read'],
    [/write_file|write_protected_file|^write$|create_file/, 'Wrote'],
    [/edit|patch|str_replace|diff[._-]create|replace/, 'Edited'],
    [/search|grep|find|glob/, 'Searched'],
    [/list_dir|^ls$|project_structure|repo_index/, 'Looked'],
    [/shell|bash|powershell|terminal|^cmd$|exec|command/, 'Ran'],
    [/diff|compare/, 'Compared'],
    [/^git[._-]commit$/, 'Committed'],
    [/pull_request/, 'Opened'],
    [/^git[._-]/, 'Looked'],
    [/web|fetch|http|download|url/, 'Fetched'],
    [/image|render|screenshot/, 'Made'],
    [/delete|remove/, 'Removed'],
    [/spawn|^task$/, 'Started'],
    [/wait/, 'Waited'],
    [/stop/, 'Stopped'],
  ];
  const CHECK_VERBS = new Set(['Checked', 'Rechecked', 'Tested']);
  const PATH_VERBS = new Set(['Read', 'Wrote', 'Edited', 'Removed', 'Looked']);
  // What the engines write: Claude's tool lines are "file_path: C:\x\app.js";
  // fs.write_file answers "Wrote 4871 chars to index.html"; diff.create answers
  // "Replaced 3 line(s) with 5 line(s) in app.js".
  const ARG_LINE = /^(file_path|notebook_path|path|pattern|command|url|query|prompt)\s*:\s*(.+)$/;
  const WROTE_LINE = /^Wrote \d+ chars? to (.+?)(?: \(via [^)]*\))?$/i;
  const REPLACED_LINE = /^Replaced (\d+) line\(s\) with (\d+) line\(s\) in (.+?)(?: \(.*\))?$/i;

  function toolName(name) {
    return String(name || '').split(' > ').pop().trim();
  }

  function argOf(text) {
    const match = ARG_LINE.exec(firstLine(text, 400));
    return match ? { key: match[1], value: match[2].trim() } : null;
  }

  // Project-relative and forward-slashed, the way a person names a file. An
  // absolute path outside the project keeps its last two parts, so two
  // index.html files in different folders still read differently.
  function shortPath(value, root) {
    const path = String(value || '').trim().replace(/\\/g, '/');
    if (!path) return '';
    const base = String(root || '').trim().replace(/\\/g, '/').replace(/\/+$/, '');
    if (base && path.toLowerCase().startsWith(`${base.toLowerCase()}/`)) return path.slice(base.length + 1);
    if (/^(?:[a-z]:)?\//i.test(path)) return path.split('/').filter(Boolean).slice(-2).join('/');
    return path;
  }

  function verbFor(ev, kind) {
    if (ev.expectedProbe === true) return 'Looked';
    if (kind === 'error') return 'Error';
    if (kind === 'reason') return 'Thought';
    if (kind === 'meta') return ev.receipt === 'model' ? 'Model' : 'Noted';
    if (kind === 'engine_debug') return 'Hook';
    if (kind === 'acceptance') return 'Checked';
    if (kind !== 'tool' && kind !== 'tool_result') return 'Output';
    const name = toolName(ev.name).toLowerCase();
    const hit = name && TOOL_VERBS.find(([pattern]) => pattern.test(name));
    if (hit) return hit[1];
    if (ev.terminal === true) return 'Ran';
    return name ? 'Used' : 'Result';
  }

  // Rows the main transcript leaves out: the model receipt and directory
  // look-ups. The data stays in the Activity drawer and the agent feed.
  // The engine's own bookkeeping ("Noted" lines, its `run` check receipts) is the proof
  // card's to show, never a loose row.
  const QUIET_VERBS = new Set(['Model', 'Looked', 'Noted']);
  function isQuietRow(ev) {
    return QUIET_VERBS.has(verbFor(ev, kindOf(ev))) || toolName(ev.name).toLowerCase() === 'run';
  }

  // Verb, detail and right-hand meta for one row. Pure, so a test can read it
  // and the clustering below can key on exactly what the row shows.
  function workRowFace(ev, opts) {
    const options = opts || {};
    const kind = kindOf(ev);
    let verb = verbFor(ev, kind);
    if (verb === 'Checked' && options.recheck) verb = 'Rechecked';
    const text = String(ev.text || ev.message || '');
    const first = firstLine(text);
    const call = argOf(ev.call_text) || (kind === 'tool' ? argOf(text) : null);
    const wrote = WROTE_LINE.exec(first);
    const replaced = REPLACED_LINE.exec(first);
    const callPath = call && /path$/.test(call.key) ? call.value : '';
    const path = shortPath(ev.path || callPath || (wrote && wrote[1]) || (replaced && replaced[3]) || '', options.root);
    let detail;
    // The settled contract carries one item per ask, each satisfied or not.
    const asks = kind === 'acceptance' && Array.isArray(ev.items) ? ev.items.filter(item => item && typeof item.satisfied === 'boolean') : [];
    if (ev.expectedProbe === true) detail = 'for existing files — nothing there yet';
    else if (kind === 'acceptance') detail = asks.length ? `${asks.filter(item => item.satisfied).length} of ${asks.length} asks met` : 'your asks';
    else if (verb === 'Ran') detail = String(ev.command || (call && call.key === 'command' ? call.value : '') || first);
    else if (CHECK_VERBS.has(verb)) detail = String(ev.check || ev.command || first || 'the build');
    else if (verb === 'Searched') {
      const query = call && /pattern|query/.test(call.key) ? call.value : '';
      detail = [path, query].filter(Boolean).join(' · ') || first;
    } else if (path && PATH_VERBS.has(verb)) detail = path;
    else if (call) detail = call.value;
    else if (verb === 'Used') detail = [toolName(ev.name), first].filter(Boolean).join(' · ');
    else detail = first || toolName(ev.name);
    let added = count(ev.added);
    let removed = count(ev.removed);
    if (added === null && removed === null && replaced) { removed = Number(replaced[1]); added = Number(replaced[2]); }
    const change = changeHtml(added, removed);
    const started = Number(ev.started_ts);
    const ended = Number(ev.ts);
    let meta = change;
    // A check's own verdict, once its result is in (a call alone has none).
    if (!meta && CHECK_VERBS.has(verb) && kind === 'tool_result') meta = ev.waiting ? '…' : (options.failed ? '✕' : '✓'); // no verdict yet: neither mark
    if (!meta && started > 0 && Number.isFinite(ended) && ended >= started) meta = durationLabel(ended - started);
    return { verb, detail: firstLine(detail, 160), meta, metaText: meta.replace(/<[^>]+>/g, '') };
  }

  // One line of background work: who did it, what, to what, and how it went.
  // The row is a <details> whose body holds the full text the old receipts
  // showed, so nothing is lost by the line being short. `tc-code-receipt` and
  // the data-code-* attributes stay: unified_code_view_state.js keys a reader's
  // open rows on exactly those across a redraw.
  //
  // opts: esc; text (the full body, escaped here into a <pre>, never rendered as
  // markdown); failed (bool, or a predicate -- the caller's one failure test);
  // heading (the plain-words name of the step, for the body); recheck; root; saved.
  function workRowHtml(ev, opts) {
    const options = opts || {};
    const { esc } = options;
    const failed = typeof options.failed === 'function' ? Boolean(options.failed(ev)) : Boolean(options.failed);
    const face = workRowFace(ev, { ...options, failed });
    const kind = kindOf(ev);
    const full = String(options.text != null ? options.text : (ev.text || ''));
    const heading = typeof options.heading === 'function' ? options.heading(ev) : String(options.heading || '');
    const tool = String(ev.name || '').trim();
    const toolAttr = tool ? ` data-code-tool="${esc(tool)}" title="${esc(tool)}"` : '';
    const what = [heading, tool].filter(Boolean).join(' · ');
    const call = ev.call_text ? `<span class="tc-code-work-call">${esc(ev.call_text)}</span>` : '';
    return `<details class="tc-code-work tc-code-receipt tc-code-technical${failed ? ' is-error' : ''}" data-code-kind="${esc(kind)}" data-code-event-seq="${esc(String(ev.event_seq || ''))}"${toolAttr}${options.saved ? ' data-saved="true"' : ''}>`
      + `<summary><span class="tc-code-work-verb">${esc(face.verb)}</span>`
      + `<span class="tc-code-work-detail">${esc(face.detail)}</span>`
      + `<span class="tc-code-work-meta">${face.meta}</span></summary>`
      + `<div class="tc-code-work-body">${what ? `<span class="tc-code-work-what">${esc(what)}</span>` : ''}${call}<pre>${esc(full)}</pre></div></details>`;
  }

  function sameSource(a, b) {
    return ['agent_id', 'agent_title', 'agent_mode', 'model', 'team_id', 'parent_agent_id']
      .every(key => (a[key] || '') === (b[key] || ''));
  }

  // A call and its result are one step. The Claude engine writes both (`tool`,
  // then `tool_result` with the same name), which drew every action twice. A
  // result directly after its own call folds into one row that keeps the call's
  // arguments and start time, so the row can say how long the step took.
  function pairsWith(previous, ev) {
    if (!previous || !ev || kindOf(previous) !== 'tool' || kindOf(ev) !== 'tool_result') return false;
    if (!sameSource(previous, ev)) return false;
    const name = String(ev.name || '');
    return !name || name === String(previous.name || '');
  }

  function pairedEvent(call, result) {
    const pick = key => (result[key] !== undefined && result[key] !== null && result[key] !== '' ? result[key] : call[key]);
    return {
      ...result,
      name: pick('name'),
      call_text: String(call.text || ''),
      started_ts: call.ts != null ? call.ts : result.started_ts,
      path: pick('path'),
      added: pick('added'),
      removed: pick('removed'),
      command: pick('command'),
      event_seq: pick('event_seq'),
    };
  }

  function pairToolCalls(events) {
    const out = [];
    (Array.isArray(events) ? events : []).forEach(ev => {
      const previous = out[out.length - 1];
      if (pairsWith(previous, ev)) out[out.length - 1] = pairedEvent(previous, ev);
      else out.push(ev);
    });
    return out;
  }

  // A run of work rows: pairs folded, then every row, in order. Nothing is
  // merged and nothing is hidden behind a fold -- the transcript just keeps
  // scrolling like a chat. Returns the railed cluster the live view appends into.
  function workRowsHtml(events, opts) {
    const options = opts || {};
    const recheckOf = ev => (typeof options.recheck === 'function' ? Boolean(options.recheck(ev)) : false);
    const textOf = ev => String(typeof options.textOf === 'function' ? options.textOf(ev) : (ev.text || ''));
    const rows = pairToolCalls(events).filter(ev => !isQuietRow(ev)).map(ev => workRowHtml(ev, { ...options, recheck: recheckOf(ev), text: textOf(ev) }));
    return rows.length ? `<div class="tc-code-receipts">${rows.join('')}</div>` : '';
  }

  // ------------------------------------------------------------ steer chip

  const STEER_STATES = new Set(['sending', 'queued', 'acked', 'undelivered', 'restarting', 'failed']);

  // Your words to a running agent, and how far they got: queued in its inbox,
  // acked once it read them at a tool boundary. `to` names a helper; a steer
  // for the lead names nobody.
  function steerChipHtml({ esc, text, state, to } = {}) {
    const word = STEER_STATES.has(state) ? state : 'queued';
    const target = String(to || '').trim();
    return `<div class="tc-code-steerchip is-${word}"><span class="tc-code-steerchip-label">Steer${target ? ` → ${esc(target)}` : ''}</span><span class="tc-code-steerchip-text">${esc(String(text || ''))}</span><span class="tc-code-steerchip-state">${word}</span></div>`;
  }

  // ------------------------------------------------------------- live diff

  // The file an agent is writing right now, as the last few lines of its newest
  // change. `diff` is ThomasCodeLiveDiff's state: {file, added, removed,
  // lines:[{n, sign, text}], agentTitle}.
  function liveDiffHtml({ esc, diff, paused } = {}) {
    if (!diff || !diff.file) return '';
    const lines = Array.isArray(diff.lines) ? diff.lines : [];
    const who = String(diff.agentTitle || '').trim() || 'Thomas';
    const body = lines.map((line, index) => {
      const sign = line && (line.sign === '+' || line.sign === '-') ? line.sign : ' ';
      const tone = sign === '+' ? ' is-add' : (sign === '-' ? ' is-del' : '');
      const caret = index === lines.length - 1 && !paused ? '<span class="tc-code-livediff-caret" aria-hidden="true"></span>' : '';
      const number = line && line.n != null ? esc(String(line.n)) : '';
      return `<div class="tc-code-livediff-line${tone}"><span class="tc-code-livediff-n">${number}</span><span class="tc-code-livediff-sign">${sign === '+' ? '+' : (sign === '-' ? MINUS : '')}</span><span class="tc-code-livediff-text">${esc(String((line && line.text) || ''))}${caret}</span></div>`;
    }).join('');
    const doing = paused ? 'Paused' : `${who} is writing`;
    return `<section class="tc-code-livediff${paused ? ' is-paused' : ''}" data-code-live-diff aria-label="Live changes to ${esc(diff.file)}">`
      + `<header class="tc-code-livediff-head">`
      + `<span class="tc-code-livediff-file">${esc(diff.file)}</span><span class="tc-code-livediff-who">${esc(doing)}</span>`
      + `<span class="tc-code-livediff-count">${changeHtml(diff.added, diff.removed)}</span></header>`
      + `${body ? `<div class="tc-code-livediff-body">${body}</div>` : ''}</section>`;
  }

  // ------------------------------------------------------------ proof card

  const RUN_ROW = 'the run finished without error';

  function askStatus(row) {
    const status = String(row.status || '').toLowerCase();
    return status === 'met' || status === 'not_met' ? status : 'unverified';
  }

  // The Verifier's reading of a report, or null when there is nothing to show
  // a proof card for. Only a run whose acceptance contract settled carries
  // per-ask verdicts (met / not_met); the generic run-level row is not an ask,
  // and a rubric that is all "unverified" is a run nobody checked one ask at a
  // time -- the compact report says that honestly, a "Verifier checked" card
  // would not.
  function proofModel(report) {
    if (!report || typeof report !== 'object') return null;
    const outcome = String(report.outcome || '');
    if (outcome === 'conversation' || outcome === 'stopped') return null;
    const asks = (Array.isArray(report.rubric_mapping) ? report.rubric_mapping : [])
      .filter(row => row && typeof row === 'object' && String(row.criterion || '').trim())
      .filter(row => String(row.criterion).trim().toLowerCase() !== RUN_ROW);
    const judged = asks.filter(row => askStatus(row) !== 'unverified').length;
    if (!judged) return null;
    const failedAsks = asks.filter(row => askStatus(row) === 'not_met');
    // Same test the compact report counts failed checks with: a check that did
    // not say it passed did not pass.
    const failedChecks = (Array.isArray(report.validations) ? report.validations : [])
      .filter(item => item && item.passed !== true).length;
    return { asks, judged, failedAsks, failedChecks, problem: failedAsks.length > 0 || failedChecks > 0 };
  }

  // The buttons under a card that found a problem. Split out so a turn can put
  // them under the reply that explains the problem, the order 4c reads in.
  function proofActionsHtml({ esc, report } = {}) {
    const model = proofModel(report);
    if (!model || !model.problem) return '';
    const fix = model.failedAsks.length
      ? `Fix what the Verifier found. These asks failed: ${model.failedAsks.map(row => `"${String(row.criterion).trim()}"`).join('; ')}`
      : 'Fix the engine checks that failed in the last run.';
    return `<div class="tc-code-proof-actions"><button type="button" class="tc-code-proof-act is-primary" data-code-proof-fix="${esc(fix)}">Fix it</button><button type="button" class="tc-code-proof-act" data-code-proof-trace>Show the trace</button><button type="button" class="tc-code-proof-act" data-code-proof-keep>Keep as is</button></div>`;
  }

  // The Verifier's card: one row per ask you made, in your words, with the
  // evidence it was judged on. Green rule when every judged ask passed, red
  // when any failed (or an engine check did), and then it says so plainly.
  // `checks` carries the compact report's own engine-check counts for the sub
  // line; `detailsHtml` is the compact report's sections, kept one click away.
  function proofHtml({ esc, report, checks, detailsHtml, actions } = {}) {
    const model = proofModel(report);
    if (!model) return '';
    const total = model.asks.length;
    const failedAsks = model.failedAsks.length;
    let title;
    if (failedAsks) title = `Verifier found a problem: ${failedAsks} of ${total} ${total === 1 ? 'ask' : 'asks'} failed`;
    else if (model.failedChecks) title = `Verifier found a problem: ${model.failedChecks} engine ${model.failedChecks === 1 ? 'check' : 'checks'} failed`;
    else if (model.judged < total) title = `Verifier checked ${model.judged} of your ${total} asks`;
    else if (total === 1) title = 'Verifier checked your ask';
    else if (total === 2) title = 'Verifier checked both of your asks';
    else title = `Verifier checked all ${total} of your asks`;
    let sub = "I'm not calling this done.";
    if (!model.problem) {
      const facts = ['Separate evaluator'];
      const ran = count(checks && checks.ran);
      if (ran) facts.push(`${count(checks.passed) || 0} of ${ran} engine ${ran === 1 ? 'check' : 'checks'} passed`);
      const skipped = count(checks && checks.skipped);
      if (skipped) facts.push(`${skipped} skipped`);
      if (model.judged < total) facts.push(`${total - model.judged} not checked`);
      const risks = Array.isArray(report.open_risks) ? report.open_risks.length : 0;
      if (risks) facts.push(`${risks} open ${risks === 1 ? 'risk' : 'risks'} in details`);
      sub = facts.join(' · ');
    }
    const marks = { met: '✓', not_met: '✕', unverified: '○' };
    const words = { met: 'passed', not_met: 'failed', unverified: 'not checked' };
    const rows = model.asks.map(row => {
      const status = askStatus(row);
      const evidence = String(row.evidence || '').trim();
      return `<li class="tc-code-proof-row is-${status}"><span class="tc-code-proof-mark" title="${words[status]}">${marks[status]}</span><span class="tc-code-proof-ask">“${esc(String(row.criterion).trim())}”</span>${evidence ? `<span class="tc-code-proof-evidence">${esc(evidence)}</span>` : ''}</li>`;
    }).join('');
    const more = detailsHtml
      ? `<details class="tc-code-proof-more"><summary>details</summary><div class="tc-code-technical-log">${detailsHtml}</div></details>` : '';
    const card = `<section class="tc-code-proof${model.problem ? ' is-problem' : ''}" data-saved="true" aria-label="${esc(title)}">`
      + `<header class="tc-code-proof-head">`
      + `<span class="tc-code-proof-title"><strong>${esc(title)}</strong><small>${esc(sub)}</small></span></header>`
      + `<ul class="tc-code-proof-rows">${rows}</ul>${more}</section>`;
    return actions === false ? card : card + proofActionsHtml({ esc, report });
  }

  // --------------------------------------------------- ask-the-user card

  // A question that is genuinely yours to answer. Each option answers on
  // click (data-code-ask-option, bound by the run's owner); typing in the
  // composer answers too. An answered or expired question shrinks to one line.
  // `othersWorking` adds "Other agents keep going" only when that is true.
  function askHtml({ esc, question, busy, waitingOn, othersWorking } = {}) {
    const q = question || {};
    const id = String(q.question_id || q.id || '');
    const text = String(q.question || q.text || '').trim();
    const answer = q.answer == null ? '' : String(q.answer).trim();
    const state = q.state || (answer ? 'answered' : 'open');
    if (state === 'answered' || state === 'expired') {
      const said = String(q.note || '').trim();
      const line = said || (state === 'expired'
        ? `No answer in time${answer ? `; Thomas went with “${answer}”` : ''}.`
        : `You chose: ${answer}`);
      return `<div class="tc-code-ask is-${state}" data-question-id="${esc(id)}">${text ? `<span class="tc-code-ask-q">${esc(text)}</span>` : ''}<span class="tc-code-ask-chosen">${esc(line)}</span></div>`;
    }
    const options = (Array.isArray(q.options) ? q.options : [])
      .filter(option => option && String(option.label || '').trim())
      .slice(0, 6)
      .map(option => {
        const label = String(option.label).trim();
        const description = String(option.description || '').trim();
        const tag = option.recommended ? '<span class="tc-code-ask-tag">Recommended</span>' : '';
        return `<button type="button" class="tc-code-ask-option${option.recommended ? ' is-recommended' : ''}" data-code-ask-option data-question-id="${esc(id)}" data-label="${esc(label)}"${busy ? ' disabled' : ''}>`
          + '<span class="tc-code-ask-radio" aria-hidden="true"></span>'
          + `<span class="tc-code-ask-option-body"><span class="tc-code-ask-option-title">${esc(label)}${tag}</span>`
          + `${description ? `<span class="tc-code-ask-option-desc">${esc(description)}</span>` : ''}</span></button>`;
      }).join('');
    const who = String(waitingOn || '').trim();
    const waiting = who
      ? `<span class="tc-code-ask-waiting">${esc(who)} is waiting on this</span>` : '';
    const note = [q.allow_free_text === false ? '' : 'Or type your own answer below.', othersWorking ? 'Other agents keep going while you decide.' : '']
      .filter(Boolean).join(' ');
    return `<section class="tc-code-ask${busy ? ' is-busy' : ''}" data-question-id="${esc(id)}" aria-label="Thomas is asking"${busy ? ' aria-busy="true"' : ''}>`
      + `<header class="tc-code-ask-head"><strong class="tc-code-ask-label">Thomas</strong><span class="tc-code-ask-sub">is asking</span>${waiting}</header>`
      + `<p class="tc-code-ask-q">${esc(text)}</p><div class="tc-code-ask-options" role="group" aria-label="${esc(text || 'Choices')}">${options}</div>`
      + `${note ? `<p class="tc-code-ask-note">${esc(note)}</p>` : ''}</section>`;
  }

  // ------------------------------------------- what a run's controls wrote

  // A plan draws nothing inline (the STEPS card shows it); a pause and its
  // release are one quiet line each; a steer an agent READ is a chip; a
  // question is the ask card, compact once answered. null means the event is
  // none of these, so the caller carries on to prose and work rows.
  //
  // opts: esc; saved (a saved turn's open question was never answered, so it
  // reads as expired); answered (the `answered` event for an `ask`, when the
  // caller has it).
  function controlEventHtml(ev, opts) {
    const options = opts || {};
    const { esc } = options;
    const kind = kindOf(ev);
    if (kind === 'plan') return '';
    if (kind === 'stepnote') {
      return `<div class="tc-code-stepnote" data-code-kind="stepnote"${options.saved ? ' data-saved="true"' : ''}>${esc(String(ev.text || ''))}</div>`;
    }
    if (kind === 'paused' || kind === 'resumed') {
      const words = String(ev.text || '').trim() || (kind === 'paused' ? 'Paused.' : 'Resumed.');
      return `<div class="tc-code-quietline is-${kind}" data-code-kind="${kind}"${options.saved ? ' data-saved="true"' : ''}>${esc(words)}</div>`;
    }
    // A read steer carries the id of the message it read. The old restart
    // flow's own notes ("Applying your update…") carry none and stay ordinary
    // lines -- they describe a restart, not a delivery.
    if (kind === 'steering' && ev.steer_id) {
      return steerChipHtml({ esc, text: ev.text, state: 'acked', to: ev.agent_title });
    }
    const note = said => (said && said.text && said.text !== said.answer ? said.text : '');
    if (kind === 'ask') {
      const answered = options.answered || null;
      const question = {
        question_id: ev.question_id, question: ev.question || ev.text, options: ev.options,
        allow_free_text: ev.allow_free_text, state: answered ? 'answered' : (options.saved ? 'expired' : 'open'),
        answer: answered ? answered.answer : null, note: note(answered),
      };
      return askHtml({ esc, question, waitingOn: ev.agent_title || 'Thomas' });
    }
    if (kind === 'answered') {
      return askHtml({ esc, question: { question_id: ev.question_id, state: 'answered', answer: ev.answer || '', note: note(ev) } });
    }
    return null;
  }

  // ------------------------------------------- update lines from the plan

  // A step finishing or starting is news. Each change between two plans becomes
  // one quiet line -- "Built the Pong page (1m 28s)", "Now testing the controls"
  // -- so a long run keeps telling you where it is. Derived from the plan alone:
  // the same events give the same lines live and saved, and a status that did
  // not change says nothing. A leading verb is bent when it is a common one.
  const PAST = { build: 'Built', add: 'Added', create: 'Created', write: 'Wrote', test: 'Tested', check: 'Checked', make: 'Made', fix: 'Fixed', set: 'Set', update: 'Updated', design: 'Designed', implement: 'Implemented', review: 'Reviewed', verify: 'Verified', run: 'Ran', wire: 'Wired', style: 'Styled', draft: 'Drafted', install: 'Installed', read: 'Read', refactor: 'Refactored', polish: 'Polished' };
  const ING = { build: 'building', add: 'adding', create: 'creating', write: 'writing', test: 'testing', check: 'checking', make: 'making', fix: 'fixing', set: 'setting', update: 'updating', design: 'designing', implement: 'implementing', review: 'reviewing', verify: 'verifying', run: 'running', wire: 'wiring', style: 'styling', draft: 'drafting', install: 'installing', read: 'reading', refactor: 'refactoring', polish: 'polishing' };
  function stepNotes(previous, plan) {
    const before = new Map();
    planItems(previous).forEach((item, i) => before.set(String(item.id || item.text || i), item));
    const notes = [];
    planItems(plan).forEach((item, i) => {
      const was = before.get(String(item.id || item.text || i));
      if (was && was.status === item.status) return;
      const text = String(item.text || '').trim().replace(/[.!?]+$/, '');
      const head = text.split(/\s+/)[0].toLowerCase();
      const rest = text.split(/\s+/).slice(1).join(' ');
      if (item.status === 'completed') {
        const took = item.started_at && item.done_at ? durationLabel(item.done_at - item.started_at) : '';
        notes.push(`${PAST[head] ? `${PAST[head]} ${rest}`.trim() : `Finished: ${text}`}${took ? ` (${took})` : ''}`);
      } else if (item.status === 'in_progress') {
        notes.push(ING[head] ? `Now ${ING[head]} ${rest}`.trim() : `Now: ${text}`);
      }
    });
    return notes;
  }

  // The event list with a `stepnote` after every plan that changed something.
  function withStepNotes(events) {
    const list = Array.isArray(events) ? events : [];
    if (!list.some(ev => ev && kindOf(ev) === 'plan')) return list;
    const out = [];
    let last = null;
    list.forEach(ev => {
      out.push(ev);
      if (!ev || kindOf(ev) !== 'plan') return;
      stepNotes(last, ev).forEach(text => out.push({ type: 'stepnote', text, ts: ev.ts }));
      last = ev;
    });
    return out;
  }

  // ------------------------------------------------------ a turn's facts

  // Who worked on a turn, lead first: the seeds the mascot colours bots by.
  function agentSeeds(events) {
    const seen = new Map([['lead', 'thomas']]);
    (Array.isArray(events) ? events : []).forEach(ev => {
      const id = ev && ev.agent_id ? String(ev.agent_id) : '';
      if (id && !seen.has(id)) seen.set(id, String(ev.agent_title || 'agent'));
    });
    return [...seen.values()];
  }

  // The newest plan.update a run wrote is its plan; earlier ones are history.
  function newestPlan(events) {
    const plan = (Array.isArray(events) ? events : []).filter(ev => ev && kindOf(ev) === 'plan').at(-1);
    return plan && planProgress(plan).total ? { items: plan.items, ts: plan.ts } : null;
  }

  // "Worked for 2m 24s": how long the run took, from the first to the last event time.
  // One quiet line after Thomas's reply; empty when the events carry no times.
  function workedLine(events, esc) {
    const times = (Array.isArray(events) ? events : []).map(ev => Number(ev && ev.ts)).filter(n => Number.isFinite(n) && n > 0);
    if (times.length < 2) return '';
    const took = durationLabel(Math.max(...times) - Math.min(...times));
    return took ? `<div class="tc-code-worked">Worked for ${esc(took)}</div>` : '';
  }

  // The head's meta for a saved turn: "4 agents · 1m 48s" once its lines carry
  // times; for a turn recorded before they did, the model that answered, exactly
  // as the head always showed it. The model is never dropped -- with times
  // showing it rides as the title, one hover away.
  function turnMeta(turn, events) {
    const t = turn || {};
    // The head shows only "Thomas"; this note becomes its hover title, so the model that ran is never hidden.
    const metaTitle = t.model_used
      ? `Ran on ${t.model_used}${t.model ? ` (asked for ${t.model})` : ''}`
      : (t.model ? `Asked for ${t.model}; the engine did not report which exact model ran this turn` : '');
    const times = (Array.isArray(events) ? events : []).map(ev => Number(ev && ev.ts)).filter(n => Number.isFinite(n) && n > 0);
    if (times.length < 2) return { meta: '', metaTitle };
    const agents = agentSeeds(events).length;
    const took = durationLabel(Math.max(...times) - Math.min(...times));
    return { meta: `${agents} ${agents === 1 ? 'agent' : 'agents'} · ${took}`, metaTitle };
  }

  window.ThomasCodeCards = {
    headHtml, stepsHtml, isQuietRow, workRowHtml, workRowsHtml, steerChipHtml, liveDiffHtml,
    proofHtml, proofActionsHtml, askHtml, controlEventHtml,
    // Pure helpers, exported for callers that need the same reading and for tests.
    durationLabel, planProgress, newestPlan, stepNotes, withStepNotes, agentSeeds, turnMeta, workedLine, workRowFace, pairToolCalls,
    pairsWith, shortPath,
  };
})();
