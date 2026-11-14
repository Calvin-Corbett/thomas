/* The event-render cluster, lifted out of unified_code_mode.js.
 *
 * It left because that file was 1808 lines against a 1500-line ceiling, and this
 * is the one part of it with a boundary you can state in a sentence: everything
 * that turns a run's event stream into HTML, and nothing that talks to the
 * server or owns the run. Twelve names go in, eleven came back.
 *
 * The 2026-08-10 pass added the two remaining pieces of transcript CHROME that
 * had stayed behind: the empty state's starter cards (what the transcript shows
 * with no turns in it) and the copy-reply action that belongs to the button
 * turnHtml already stamps on every Thomas turn. Same boundary, same direction:
 * markup and the clipboard, still no server and still no run.
 *
 * `codeResults` and `surface` arrive as accessors, not values, for the same
 * reason unified_code_mode.js reaches its own siblings that way -- captured once,
 * they would freeze whatever happened to be on window at create() time and make
 * load order a second ordering rule. chat.html must load this file first.
 *
 * Since the 2026-10 redesign the rows, STEPS card, proof card and the other
 * pieces are drawn by unified_code_cards.js; this file still decides what each
 * event IS and in what order a turn tells its story.
 */
(function () {
  'use strict';

  const CONTINUATION_PREFIX = 'Autopilot: continuing';
  const STEER_LINE = 'Steering update: ';
  // What a run's controls write: neither tool output nor prose, each its own
  // card, and never folded by the narrative dedupe (two plan updates can carry
  // the same "2 of 5 done" text and different steps).
  const CARD_KINDS = new Set(['plan', 'stepnote', 'paused', 'resumed', 'steering', 'ask', 'answered']);

  function create(deps) {
    const {
      MAX_PROGRESS_EVENT_CHARS, NARRATIVE_EVENT_KINDS, state, esc,
      codeResults, surface,
    } = deps;

    // Code-Thomas wears the anvil — he builds (owner, 2026-08-10). Chat keeps
    // its own avatar; this badge is Code mode's only.
    const ANVIL_SVG = '<svg viewBox="0 0 256 256" aria-hidden="true"><path d="M240 60h-92a12 12 0 0 0 0 24h6.6c-4 24.5-22.8 44-47 48.6C82.9 137.4 64 121.4 64 96V84h12a12 12 0 0 0 0-24H24a12 12 0 0 0 0 24h16v12c0 34.6 24.7 58.5 56 63.4v10.2c0 11-4.7 21.4-13 28.6l-18.9 16.5A12 12 0 0 0 72 236h112a12 12 0 0 0 7.9-21.1L173 198.4a38.2 38.2 0 0 1-13-28.6v-10.6c37.5-6 66.2-35 70.7-71.2H240a12 12 0 0 0 0-24Z"/></svg>';

    // Read at call time, like `codeResults`; a page without the cards says why
    // instead of drawing a transcript with holes in it.
    function cards() {
      const api = window.ThomasCodeCards;
      if (!api) throw new Error('unified_code_cards.js must load before the Build transcript renders');
      return api;
    }

    // Which of a team's events the transcript shows (unified_code_agents.js); without it, all of them.
    const rows = () => window.ThomasCodeAgentRows || null;

    function eventLabel(event) {
      const type = String(event.type || event.fc || 'activity').replace(/_/g, ' ');
      return String(event.text || event.message || event.name || event.tool || event.error || type);
    }
    function eventKind(event) {
      const kind = String(event.kind || event.fc || event.type || 'activity').toLowerCase();
      if (kind === 'reason') return 'Reasoning';
      if (kind === 'insight') return 'Insight';
      if (kind === 'say') return 'Update';
      if (kind === 'final') return 'Thomas';
      if (kind === 'planning') return 'Planning';
      if (kind === 'steering') return 'Steering';
      if (kind === 'error') return 'Error';
      // A reconnect is not a failure: the run went on, and the row says so.
      if (kind === 'reconnected') return 'Reconnected';
      if (kind === 'disconnected') return 'Connection lost';
      return kind.replace(/_/g, ' ');
    }

    function isTerminalTool(name) {
      return /(?:^|[._-])(shell|bash|powershell|cmd|terminal|command)(?:$|[._-])/i.test(String(name || ''));
    }

    function annotateTerminalEvent(event, tracker) {
      const kind = String(event.kind || event.fc || event.type || 'activity').toLowerCase();
      if (kind === 'tool' || kind === 'tool_result') {
        const name = String(event.name || (kind === 'tool_result' && !event.agent_id ? tracker.name : '') || '');
        const terminalTool = isTerminalTool(name) ? name : '';
        if (terminalTool) { event.terminal = true; event.terminalTool = terminalTool; }
        if (!event.agent_id) tracker.name = kind === 'tool' ? terminalTool : '';
      }
      return event;
    }

    function eventType(event) {
      return String(event.kind || event.fc || event.type || 'output').toLowerCase();
    }

    function containsToolProtocol(event) {
      const label = eventLabel(event);
      return /recipient_name|multi_tool_use\.parallel|to=functions\.|<\|assistant\s+to=|\{"tool_uses"\s*:/i.test(label);
    }

    function isTechnicalEvent(event) {
      const kind = eventType(event);
      // A helper's status, its one failure line and a team notice are quiet lines (unified_code_agents.js).
      if (rows() ? rows().isLine(event) : (event.agent_id && /^agent_(?:spawned|status|event)$/.test(kind))) return false;
      if (CARD_KINDS.has(kind)) return false;
      return event.terminal === true || containsToolProtocol(event) || !NARRATIVE_EVENT_KINDS.has(kind);
    }

    // The very first read of a brand-new project is an existence check, not a
    // fault: the model asks for the file before writing it, and on an empty
    // project that read HAS to fail. Measured on a flawless clock build: the
    // activity header advertised "8 issues", of which one was exactly this
    // probe -- an alarming red row about a project that simply did not have
    // files yet. Flagged at ingestion (transcript parse and live push both call
    // this) rather than at render, so the grouped saved log, the streamed live
    // row, and both issue counters read the one flag instead of four sites
    // re-deriving "was this the probe" and drifting.
    //
    // Position does the heavy lifting: only the FIRST tool_result in a run can
    // be the probe. A later failing read is a real recovered attempt and keeps
    // its count -- the caller says whether a tool_result came before this one.
    const EXPECTED_PROBE_PATTERN = /no such file|not found|does not exist|could not (?:read|find|open)|is empty|empty director|enoent/i;
    function flagExpectedProbe(event, hasPriorToolResult) {
      if (hasPriorToolResult || eventType(event) !== 'tool_result') return event;
      if (event.is_error === true && EXPECTED_PROBE_PATTERN.test(eventLabel(event))) event.expectedProbe = true;
      return event;
    }

    // Share one failure predicate so live error rows cannot show a success tick.
    function eventFailed(event, kind) {
      // The expected first read probe of an empty project is not a failure --
      // see flagExpectedProbe. Decided here so every consumer of "did this row
      // fail" (icon, row class, both issue counters) agrees at once.
      if (event.expectedProbe === true) return false;
      return event.is_error === true || (kind == null ? eventType(event) : kind) === 'error';
    }

    function technicalHeading(event, kind) {
      if (kind === 'reason') return 'Reviewed the approach';
      // The existence probe of a brand-new project (see flagExpectedProbe).
      // Named for what it is rather than falling through to "<tool> failed",
      // which asserts a fault about a folder that simply has nothing in it yet.
      if (event.expectedProbe === true) return 'Looked for existing files — nothing there yet';
      // Not a check. Nothing was verified: this is the run, or the client,
      // reporting that something broke. `pushLiveEvent({ type: 'error' })` carries
      // client faults too -- a failed file preview, a task that cannot be opened.
      // The dead-deep-link case read "Technical check failed / not found" about a
      // conversation that does not exist, which asserts a check ran on work that
      // was never done.
      if (kind === 'error') return 'Something went wrong';
      if (event.terminal === true) {
        if (kind === 'tool') return 'Ran terminal command';
        return event.is_error === true ? 'Terminal check failed' : 'Read terminal result';
      }
      if (kind === 'tool') return humanToolHeading(event.name, `Used ${event.name || 'a project tool'}`);
      // The same overloading the comment below describes: a tool that returned an
      // error is a failed tool CALL, not a failed check. The verb is humanized
      // the same way successful rows are — "shell.exec failed" told the owner
      // nothing across five repeats; "A terminal command failed" reads.
      if (event.is_error === true) {
        const humanized = event.name ? humanToolHeading(event.name, '') : '';
        if (humanized) return `${humanized} — it failed`;
        return event.name ? `${event.name} failed` : 'Tool call failed';
      }
      // Neither of these is a check, and both used to say they were.
      //
      // `tool_result` read "Checked tool result" on every row. Measured on one
      // turn: 27 of them, all with that identical heading, sitting above a folder
      // listing, three separate "Wrote N chars to <file>" lines and a source
      // excerpt. A file WRITE was labelled a check -- the same overloading of the
      // word that made the activity header advertise "26 checks" on a run with
      // ONE validation. "check" means an engine check everywhere else in this
      // UI, and the verdict card counts them.
      //
      // The tool's own name was there the whole time: 25 of those 27 carried
      // `name` (`code.project_structure`, and so on), and the heading threw it
      // away in favour of a word that was wrong.
      //
      // `meta` read "Verified the result". A meta event is a workspace action --
      // `pushLiveEvent({ type: 'meta', text: 'Kept index.html.' })` -- so keeping
      // or reverting a file announced itself as a verification of it.
      if (kind === 'meta') return event.receipt === 'model' ? 'Model that answered' : 'Workspace update';
      return event.name ? humanToolHeading(event.name, `Result from ${event.name}`) : 'Tool result';
    }

    // "Result from fs.read_file" tells a non-technical reader nothing (owner,
    // 2026-08-10). The tool's own name still appears in the expanded body;
    // the ROW says what happened in words a person uses.
    // diff.create is the str-replace EDIT, so it is named before the generic
    // /diff/ rule; Claude's own tools are plain "Read"/"Write"/"Edit".
    const TOOL_HEADINGS = [
      [/fs[._-]?read|(?:^|> )(?:read|view)$/i, 'Read a file'],
      [/fs[._-]?write|(?:^|> )write$/i, 'Wrote a file'],
      [/diff[._-]?create|apply_patch|str_replace|(?:^|> )(?:multi)?edit$/i, 'Edited a file'],
      [/fs[._-]?(list|dir)/i, 'Looked in a folder'],
      [/fs[._-]?(delete|remove)/i, 'Removed a file'],
      [/project_structure/i, 'Looked at the project layout'],
      [/search|grep|find/i, 'Searched the code'],
      [/check[._-]?run|^run$/i, 'Ran a check'],
      [/diff/i, 'Compared changes'],
      [/shell|terminal|bash|powershell|cmd/i, 'Ran a terminal command'],
      [/http|fetch|web|download/i, 'Fetched from the web'],
      [/image|render|screenshot/i, 'Made an image'],
    ];
    function humanToolHeading(name, fallback) {
      const match = TOOL_HEADINGS.find(([pattern]) => pattern.test(String(name || '')));
      return match ? match[1] : fallback;
    }

    function technicalSummary(events, ok) {
      const tools = events.filter(event => eventType(event) === 'tool').length;
      // "results", and NOT counting `meta`. This said "checks", which is a
      // load-bearing word elsewhere in this UI: the verdict card counts engine
      // checks, and "1/2 checks passed" means two real validations. Using the same
      // word here for arbitrary tool output taught the header to claim
      // verification that never happened -- the same overloading as the old
      // "1 pass", which meant one EDIT pass and read as one test passing.
      //
      // The Godot run advertised "26 checks" in this header while its report
      // recorded ONE validation. Measured after the change, the same run reads
      // "25 results", so exactly ONE of the 26 was a `meta` status note ("Kept
      // index.html") and the other 25 were tool output. The misnaming was the
      // bigger half of this by a wide margin; folding meta in was a smaller,
      // separate inaccuracy, and both are fixed here.
      const results = events.filter(event => eventType(event) === 'tool_result').length;
      // Through eventFailed, not a third inline is_error test, so the counter
      // agrees with the row styling -- and so the expected first read probe of
      // an empty project (flagExpectedProbe) is counted by neither.
      const issues = events.filter(event => eventFailed(event)).length;
      const other = Math.max(0, events.length - tools - results - issues);
      const parts = [];
      if (tools) parts.push(`${tools} tool ${tools === 1 ? 'run' : 'runs'}`);
      if (results) parts.push(`${results} ${results === 1 ? 'result' : 'results'}`);
      if (other) parts.push(`${other} ${other === 1 ? 'detail' : 'details'}`);
      // "issue" is only honest about a run that failed. Measured on a flawless
      // clock build: the header read "8 issues" over a run whose outcome was ok
      // -- 7 of them the model's own scratch-verifier retries that it then
      // recovered from. An error the run recovered from is a failed attempt,
      // and the header now says so when the caller vouches for the outcome.
      // Callers that do not pass `ok` keep the old wording -- an unknown
      // outcome must not be advertised as a recovered one.
      if (issues) parts.push(ok === true
        ? `${issues} failed ${issues === 1 ? 'attempt' : 'attempts'}, recovered`
        : `${issues} ${issues === 1 ? 'issue' : 'issues'}`);
      return parts.length ? `Worked through ${parts.join(' · ')}` : 'Technical details';
    }

    function elapsedLabel(startedAt, now) {
      const seconds = Math.max(0, Math.floor(((now == null ? Date.now() : now) - Number(startedAt || 0)) / 1000));
      if (seconds < 60) return `${seconds}s`;
      const minutes = Math.floor(seconds / 60);
      return `${minutes}m ${seconds % 60}s`;
    }

    // What every work row needs from this file: the ONE failure predicate (so
    // a row's tint and its ✓/✕ cannot disagree with the counters), the
    // plain-words heading its body opens with.
    function workRowOptions(saved) {
      return {
        esc, saved, root: state && state.projectRoot,
        failed: event => eventFailed(event),
        heading: event => technicalHeading(event, eventType(event)),
      };
    }

    // A note that comes straight after the person's steer is Thomas answering
    // them, so it keeps his name. Looks back past work rows only.
    function answersSteer(event, context) {
      const list = (context && context.list) || (state && state.liveEvents) || [];
      let at = list.indexOf(event) - 1;
      while (at >= 0 && isTechnicalEvent(list[at])) at -= 1;
      return at >= 0 && eventType(list[at]) === 'steering';
    }

    function eventHtml(event, saved, context) {
      const kind = eventType(event);
      const agentRow = window.ThomasCodeAgentRows?.render(event, esc, saved); if (agentRow) return agentRow;
      // What a run's controls wrote (a plan, a pause, a read steer, a question
      // and its answer) draws as its own card; null means "not one of those".
      const card = cards().controlEventHtml(event, { esc, saved, answered: context && context.answered });
      if (card !== null) return card;
      if (isTechnicalEvent(event)) {
        // One dim row a person can read -- "Edited  app.js  +11 −2" -- with the
        // full output behind the click (the page scrolls; no box-in-a-box).
        // eventLabel is handed over as TEXT, and the card escapes it into a
        // <pre>: raw tool output never goes through the markdown renderers the
        // prose below uses (tests/test_the_run_report_escapes_what_thomas_wrote.py
        // reads this branch on its own to confirm the two never swap).
        return cards().workRowHtml(event, {
          ...workRowOptions(saved), text: eventLabel(event), recheck: Boolean(context && context.recheck),
        });
      }
      const label = eventLabel(event);
      if (kind === 'say' || kind === 'final') {
        // Two voices. A mid-run note is an UPDATE: quiet text, no name, nothing
        // to decide. Thomas's name (accent blue) marks the few things that are
        // him speaking: the closing reply, a problem, a question, and the answer
        // to a message you sent while he worked. A note past the char cap still
        // folds behind one disclosure so a monster paragraph cannot swamp the run.
        const speaks = kind === 'final' || answersSteer(event, context);
        const head = speaks ? cards().headHtml({ esc }) : '';
        const voice = speaks ? 'tc-code-say is-speaker' : 'tc-code-say is-update';
        if (label.length > MAX_PROGRESS_EVENT_CHARS) {
          return `<div class="${voice}" data-code-kind="${esc(kind)}"${saved ? ' data-saved="true"' : ''}>${head}<div class="tc-code-say-text">${progressHtml(`${label.slice(0, 360).trimEnd()}…`)}<details class="tc-code-progress-full"><summary>Show full update</summary><span>${progressBodyHtml(label)}</span></details></div></div>`;
        }
        return `<div class="${voice}" data-code-kind="${esc(kind)}"${event.delta ? ' data-code-delta="true"' : ''}${saved ? ' data-saved="true"' : ''}>${head}<div class="tc-code-say-text">${progressBodyHtml(label)}</div></div>`;
      }
      const content = label.length <= MAX_PROGRESS_EVENT_CHARS
        ? `<span>${progressHtml(label)}</span>`
        : `<span>${progressHtml(`${label.slice(0, 360).trimEnd()}…`)}</span><details class="tc-code-progress-full"><summary>Show full update</summary><span>${progressHtml(label)}</span></details>`;
      return `<div class="tc-code-event is-${esc(kind)}" data-code-kind="${esc(kind)}"${event.delta ? ' data-code-delta="true"' : ''}${saved ? ' data-saved="true"' : ''}><strong>${esc(eventKind(event))}</strong>${content}</div>`;
    }

    function interleavedActivityHtml(events, saved) {
      // Chronological truth: Thomas's sentences in order, and the work rows
      // that back each one up clustered UNDER it until he talks again. Inside a
      // cluster the cards fold a call into its result and show every row
      // (ThomasCodeCards.workRowsHtml); nothing is merged or hidden.
      //
      // A question and its answer are one thing: the answer folds into the ask
      // card, which then reads as the compact "You chose: …" line.
      const answers = new Map();
      events.forEach(event => {
        if (eventType(event) === 'answered' && event.question_id) answers.set(String(event.question_id), event);
      });
      const asked = new Set(events.filter(event => eventType(event) === 'ask' && event.question_id).map(event => String(event.question_id)));
      const parts = [];
      let cluster = [];
      // A check after the first one in the same story is a recheck: Thomas
      // changed something and looked again.
      let checksSeen = 0;
      const flush = () => {
        if (!cluster.length) return;
        const paired = cards().pairToolCalls(cluster);
        const rechecks = new Set();
        paired.forEach(event => {
          if (cards().workRowFace(event).verb !== 'Checked') return;
          if (checksSeen) rechecks.add(event);
          checksSeen += 1;
        });
        parts.push(cards().workRowsHtml(paired, {
          ...workRowOptions(saved), textOf: eventLabel, recheck: event => rechecks.has(event),
        }));
        cluster = [];
      };
      events.forEach(event => {
        const kind = eventType(event);
        if (kind === 'plan') return;  // the STEPS card, never an inline row
        if (!saved && (kind === 'ask' || kind === 'answered')) return;  // live: the question's own slot
        if (kind === 'answered' && asked.has(String(event.question_id || ''))) return;
        if (isTechnicalEvent(event)) { cluster.push(event); return; }
        flush();
        parts.push(eventHtml(event, saved, { list: events, answered: kind === 'ask' ? answers.get(String(event.question_id || '')) : null }));
      });
      flush();
      return parts.join('');
    }

    function finalReplyEvent(events, turn) {
      const explicit = events.filter(event => eventType(event) === 'final').at(-1);
      if (explicit) return explicit;
      if (turn && turn.ok) return events.filter(event => eventType(event) === 'say' && !event.agent_id).at(-1) || null;
      return null;
    }

    function progressEvents(events, finalEvent) {
      const finalText = finalEvent ? eventLabel(finalEvent) : '';
      // A run can emit more than one `final`. `finalReplyEvent` takes `.at(-1)`,
      // so only the LAST one is recognised as the reply and filtered here --
      // an earlier `final` fell through into the narrative, where it repeated
      // verbatim the `say` that had just streamed the same text. The reader got
      // the same paragraph twice, once labelled UPDATE and once THOMAS.
      //
      // Measured on a real failed run: blocks [3] and [4] carried byte-identical
      // 476-character labels. The existing say-vs-final check could not catch it
      // because it compares against the LAST final only, and this pair matched an
      // earlier one.
      //
      // Only a `final` whose text a `say` already carried is dropped, not every
      // non-last `final`: the two finals in that run said different things and
      // one of them was the only place its text appeared. Nothing else is
      // merged -- a note said twice is shown twice, in order, like a tool row.
      // A plan draws nothing inline, so it leaves the list here, and so does a
      // helper's work (the drawer's), live and saved alike.
      const said = new Set(events.filter(event => eventType(event) === 'say').map(event => eventSourceKey(event, eventLabel(event))));
      const kept = (rows() ? rows().forTranscript(cards().withStepNotes(events)) : cards().withStepNotes(events)).filter(event => {
        if (event === finalEvent) return false;
        if (eventType(event) === 'final' && said.has(eventSourceKey(event, eventLabel(event)))) return false;
        if (finalText && eventType(event) === 'say' && eventSourceKey(event) === eventSourceKey(finalEvent) && eventLabel(event) === finalText) return false;
        // The engine's own closing summary ("dispatched via GPT (...)", "GPT replied without
        // changing files") is bookkeeping, not part of the conversation: the proof card owns it.
        if (eventType(event) === 'meta' && (event.terminal === true || /^\s*(?:dispatched via|GPT replied)/i.test(String(eventLabel(event) || '')))) return false;
        if (isTechnicalEvent(event)) return true;
        if (eventType(event) === 'plan') return false;
        if (CARD_KINDS.has(eventType(event))) return true;
        const label = String(eventLabel(event) || '').trim();
        // A row whose text only repeats its own heading says nothing. The stream's
        // `done` event carries the literal string "done", so every run grew a
        // "DONE / done" line -- transient while running, but left sitting in the
        // transcript after a Stop, where it reads as debug output beside the real
        // "Stopped — you interrupted this run." note.
        //
        // Keyed on the label adding nothing to its kind, not on the kind itself,
        // so a `done` event that ever carries real text still gets its row. Placed
        // here rather than in a saved-only renderer because the LIVE feed maps
        // eventHtml straight off this list -- a filter anywhere else fixed the
        // saved transcript and left the live one untouched. This is the seam both
        // paths share.
        return Boolean(label) && label.toLowerCase() !== String(eventKind(event) || '').trim().toLowerCase();
      });
      return kept;
    }

    // A turn persisted before the store normalized transcript shapes can carry
    // its transcript as an array -- of single characters (measured: 2541
    // one-char entries, w2-code-explain sweep) or of lines. String() on an
    // array comma-joins it, so nothing parsed as a forge event and the agent's
    // produced answer never reached the screen. Join characters back into the
    // string they were split from; join anything else with the newline the
    // parser splits on. A string passes through untouched.
    function transcriptText(turn) {
      const raw = turn && turn.transcript;
      if (Array.isArray(raw)) {
        const parts = raw.map(part => part == null ? '' : String(part));
        return parts.every(part => part.length <= 1) ? parts.join('') : parts.join('\n');
      }
      return String(raw || '');
    }

    function eventSourceKey(event, label = '') {
      return JSON.stringify(['agent_id', 'agent_title', 'agent_mode', 'model', 'team_id', 'parent_agent_id'].map(key => event[key] || '').concat(label));
    }

    // What a saved line keeps beyond its kind and text: who wrote it, and what
    // the rows and cards read (times, paths, +/- counts, the ids tying a steer
    // or an answer to its message). Malformed values stay out.
    const KEPT_TEXT = ['agent_id', 'agent_title', 'agent_mode', 'model', 'receipt', 'team_id', 'parent_agent_id',
      'agent_state', 'path', 'steer_id', 'question_id', 'question', 'answer', 'command', 'check'];
    const KEPT_COUNTS = ['ts', 'added', 'removed', 'paused_ms'];
    function keepFields(parsed, event) {
      for (const key of KEPT_TEXT) if (typeof parsed[key] === 'string' && parsed[key].trim()) event[key] = parsed[key];
      for (const key of KEPT_COUNTS) if (Number.isInteger(parsed[key]) && parsed[key] >= 0) event[key] = parsed[key];
      for (const key of ['items', 'options']) if (Array.isArray(parsed[key])) event[key] = parsed[key];
      if (typeof parsed.allow_free_text === 'boolean') event.allow_free_text = parsed.allow_free_text;
      return event;
    }

    function transcriptEvents(turn) {
      const events = [];
      const terminalTracker = { name: '' };
      // Tracks whether a tool_result has been seen yet, so only the FIRST one
      // can be flagged as the expected read probe of an empty project.
      let sawToolResult = false;
      // When each step STARTED, by who ran it and which tool: the GPT engine
      // writes a `tool_started` line ahead of a long step, and its time is what
      // lets the result's row say how long the step took.
      const starts = new Map();
      const startKey = event => `${eventSourceKey(event)}\u0000${event.name || ''}`;
      transcriptText(turn).split('\n').forEach(raw => {
        const line = raw.trim(); if (!line) return;
        let parsed = null;
        if (line.startsWith('{')) {
          try { parsed = JSON.parse(line); } catch (error) { parsed = null; }
        }
        if (parsed && parsed.fc === 'tool_started') {
          // A watcher's line: the step's result is its row. Only its clock is kept.
          const started = keepFields(parsed, { name: parsed.name || '' });
          if (started.ts != null) starts.set(startKey(started), started.ts);
          return;
        }
        const event = parsed && parsed.fc ? { type: 'output', kind: parsed.fc, name: parsed.name || '', text: parsed.text || '', is_error: parsed.is_error === true, delta: parsed.delta === true } : { type: 'output', text: raw };
        if (parsed?.fc) keepFields(parsed, event);
        if (eventType(annotateTerminalEvent(event, terminalTracker)) === 'tool_result') {
          flagExpectedProbe(event, sawToolResult);
          sawToolResult = true;
          if (starts.has(startKey(event))) { event.started_ts = starts.get(startKey(event)); starts.delete(startKey(event)); }
        }
        const previous = events[events.length - 1];
        const priorSayText = events.filter(item => item.kind === 'say' && item.delta && eventSourceKey(event) === eventSourceKey(item)).map(item => item.text || '').join('');
        if (event.kind === 'say' && event.delta && previous && previous.kind === 'say' && previous.delta && eventSourceKey(event) === eventSourceKey(previous)) previous.text += event.text;
        else if (event.kind === 'say' && !event.delta && priorSayText && eventLabel(event) === priorSayText) return;
        else if (eventLabel(event) && (isTechnicalEvent(event) || CARD_KINDS.has(event.kind) || !previous || eventSourceKey(event) !== eventSourceKey(previous) || event.kind !== previous.kind || eventLabel(event) !== eventLabel(previous))) events.push(event);
      });
      return events;
    }

    function failureSummary(turn, events) {
      if (turn.ok) return String(turn.reason || '').trim() || 'Verified Build result';
      const labels = events.map(eventLabel);
      // Checked BEFORE the verification branch, because a run that was cut off did
      // not "fail its repair attempts" -- it never got to finish them. Being
      // truncated is the cause; the failing check is the symptom.
      //
      // Measured on the study-planner run, whose recorded errors were exactly:
      //   "Pass budget exhausted after 10 passes while work was still active.
      //    The task is incomplete; continue it in the same conversation."
      //   "verification failed (exit 1) after fix attempts"
      // The branch below matched first, so the screen read "the final verification
      // still failed after its repair attempts" and sent the owner to go inspect a
      // check. The sentence that actually says what to do -- continue it in the
      // same conversation -- was in hand the whole time and reached nobody: it sat
      // in an open risk headed "error surfaced during the run", behind a collapsed
      // Show details, one of two rows sharing that same generic heading.
      //
      // Deliberately does NOT claim the project is fine. The planner it was
      // measured on was genuinely half-broken; unfinished and broken are not
      // exclusive, and only the first one is knowable from a truncated run.
      if (labels.some(label => /pass budget exhausted|budget exhausted.*while work was still active/i.test(label))) {
        return 'Thomas ran out of passes while still working, so this task is unfinished. Ask it to continue in this same conversation.';
      }
      if (labels.some(label => /verification failed.*after fix attempts/i.test(label))) {
        return 'Thomas changed the project, but the final verification still failed after its repair attempts. Open the activity details for the failing check.';
      }
      if (labels.some(label => /tool loop stability issue|failed repeatedly/i.test(label))) {
        return 'Thomas got stuck repeating a project check and stopped before finishing.';
      }
      if (labels.some(label => /remoteprotocolerror|stream disconnected|incomplete chunked|connection.*closed/i.test(label))) {
        return 'The model connection ended before Thomas could finish. Retry this task.';
      }
      // Named, because it is not a fault in the project and the owner should not
      // go looking for one. Observed live: "Our servers are currently overloaded.
      // Please try again later." -- which reads as THOMAS's servers unless it
      // says whose, and the only useful action is to send it again.
      if (labels.some(label => /\boverloaded\b|\brate.?limit(?:ed)?\b|too many requests|\bover capacity\b|\b429\b/i.test(label))) {
        return 'The model provider is busy right now — this is not a problem with your project or your request. Send it again in a moment.';
      }
      // Filter FIRST, then take the last survivor. Errors arrive oldest-first and
      // the final one is almost always a wrapper: `agent loop exited 1` follows
      // whatever actually went wrong. Taking `.at(-1)` before filtering therefore
      // picked the wrapper every time, the guard below correctly rejected it as
      // unhelpful, and the real cause -- sitting one entry earlier -- was thrown
      // away. Measured on a real run whose recorded errors were exactly
      // ["Our servers are currently overloaded. Please try again later.",
      //  "agent loop exited 1"]: the owner was shown "Thomas hit a technical
      // problem" and told to go open the raw error, while the plain-language
      // reason was already in hand.
      const errorLabels = events.filter(event => eventType(event) === 'error').map(eventLabel).filter(Boolean);
      const structured = errorLabels.filter(label => (
        label.length <= 240
        && !/[{}\r\n]|traceback|http\s*\d{3}|remoteprotocolerror/i.test(label)
        && !/^agent loop exited|^exited \d+/i.test(label)
      )).at(-1);
      if (structured) return structured;
      // Errors existed but none of them were fit to show, which is a different
      // situation from no errors at all -- keep the two messages distinct.
      if (errorLabels.length) return 'Thomas hit a technical problem and stopped before finishing. Open the technical details for the raw error.';
      // Say the two things that ARE known: how it ended, and that nothing said why.
      //
      // Measured on four consecutive runs of the same goal (15:42, 15:44, 15:46,
      // 15:48). Each recorded exactly three events -- Thomas stating its plan, the
      // project structure, "(empty directory)" -- then exited 1 with no error
      // event at all. Every one of them told the owner "The Build task stopped
      // before it finished." and nothing else, four times over, while `reason`
      // held "exited 1" the whole time.
      //
      // "no error was recorded" is worth saying out loud: it distinguishes a run
      // that failed silently from one whose reason is being withheld, and it is
      // the difference between looking for a message and knowing there is none.
      // Still no invented cause -- there genuinely was not one.
      const ending = String((turn && turn.reason) || '').trim();
      return ending
        ? `The Build task stopped before it finished — ${ending}, with no error recorded.`
        : 'The Build task stopped before it finished.';
    }

    function turnHtml(turn) {
      if (turn.role === 'user') {
        const text = String(turn.text || '');
        if (text.startsWith(CONTINUATION_PREFIX)) {
          const title = text.split('\n', 1)[0].split(/\s+(?:toward|on) the goal\b/, 1)[0];
          const secondParagraph = text.split('\n\n', 3)[1] || '';
          const steer = secondParagraph.startsWith(STEER_LINE)
            ? `<div class="tc-code-autopilot-steer">${esc(secondParagraph)}</div>` : '';
          return `<aside class="tc-code-autopilot-note"><span>${esc(title)}</span>${steer}<details><summary>Full message</summary><div class="tc-code-autopilot-full">${esc(text)}</div></details></aside>`;
        }
        // Your words, in one bright bubble with no name over it: whose they are
        // is plain from the bubble itself.
        // What you attached sits above your words: live from the pending message, or remembered by name.
        const strip = window.ThomasAttachmentStrip;
        const attached = Array.isArray(turn.attachments) && turn.attachments.length ? turn.attachments : (strip ? strip.recall(text) : []);
        return `<article class="tc-code-turn is-user">${strip ? strip.html(attached) : ''}<div class="tc-code-user-text">${esc(text)}</div></article>`;
      }
      const events = transcriptEvents(turn);
      const finalEvent = finalReplyEvent(events, turn);
      const activityEvents = progressEvents(events, finalEvent);
      const modelFinal = finalEvent ? eventLabel(finalEvent) : '';
      const staleLimitReply = /execution review|review limit|forbid(?:s|den)? (?:another|further) tool|no files were changed and verification/i.test(modelFinal);
      // The answer the model actually produced, minus the stale review-limit
      // excuse -- that one is a claim about the engine that the engine's own
      // evidence contradicts, not an answer, and the contract in
      // unified_code_mode_lifecycle.mjs pins its suppression on BOTH outcomes.
      const answer = modelFinal && !staleLimitReply ? modelFinal : '';
      // A deliberately stopped run. The recorder files `outcome: 'stopped'`
      // with reason "stopped by you" (or "stopped for your steering update");
      // older turns carry only the reason, so both are read.
      const wasStopped = String(turn.outcome || '').toLowerCase() === 'stopped'
        || /\bstopped (?:by you|for your steering update)\b/i.test(String(turn.reason || ''));
      let replySection;
      if (turn.ok) {
        // Do not infer verification from turn.ok; the report card owns check results.
        const fallback = 'Finished the requested changes.';
        replySection = replyBlockHtml(answer || fallback, { report: turn.report, ...cards().turnMeta(turn, events), copy: true });
      } else if (wasStopped) {
        // A stop the user asked for is not a failure and must not wear the red
        // pipeline. This rendered through failureSummary -- "The Build task
        // stopped before it finished — stopped by you..." in error styling --
        // which scolded the reader for their own deliberate click. `is-stopped`
        // instead of `is-error`: unstyled today, which is exactly the neutral
        // default this note wants; a stylesheet may pick it up later. The
        // recorder's reason is kept verbatim (it names how much work had
        // already changed), only capitalised.
        const reason = String(turn.reason || '').trim();
        const note = reason
          ? `${reason.charAt(0).toUpperCase()}${reason.slice(1)}. Anything already changed is in Outputs with Keep/Revert.`
          : 'Stopped — you interrupted this run. Anything already changed is in Outputs with Keep/Revert.';
        replySection = `${answer ? replyBlockHtml(answer, { report: turn.report, ...cards().turnMeta(turn, events), copy: true }) : ''}<div class="tc-code-reply is-stopped">${esc(note)}</div>`;
      } else {
        // NEVER suppress a produced answer. A run filed as failed whose
        // transcript nevertheless carries a `final` event with text rendered
        // ONLY failureSummary(): the model's answer existed nowhere on screen,
        // because this branch discarded it and progressEvents (correctly)
        // filters the final event out of the narrative. That is the auto-reject
        // shape applied to rendering -- work the model produced, dropped by
        // plumbing. The answer renders first; the failure note renders
        // alongside it, never instead of it.
        const failure = failureSummary(turn, events);
        replySection = answer
          ? `${replyBlockHtml(answer, { report: turn.report, ...cards().turnMeta(turn, events), copy: true })}<div class="tc-code-reply is-error">${replyHtml(failure)}</div>`
          : `<div class="tc-code-reply is-error">${cards().headHtml({ esc })}<div class="tc-code-reply-text">${replyHtml(failure)}</div></div>`;
      }
      // Design 4a's order: the work, dim, every row in order (nothing folds), the
      // Verifier's card, the reply, what he made. Each prose block from Thomas
      // carries its own head, so the turn has none of its own.
      const interleaved = interleavedActivityHtml(activityEvents, true);
      const technicalEvents = activityEvents.filter(isTechnicalEvent);
      // An error the run RECOVERED from is a failed attempt, not an issue. The
      // rows show the red ones on their own, so without this line a successful
      // run reads as alarming. Same wording, same honesty rule (guarded by
      // test_a_failed_run_still_shows_the_answer_it_produced).
      const recoveredNote = technicalEvents.some(event => eventFailed(event))
        ? technicalSummary(technicalEvents, turn.ok === true) : '';
      const plan = cards().newestPlan(events);
      // A plan is the pinned STEPS card (top right); without one, the team's newest tally, one quiet line.
      const steps = plan ? '' : (rows() ? rows().teamHtml(rows().latestTeamProgress(events), esc) : '');
      const work = steps + interleaved + (recoveredNote ? `<div class="tc-code-attempt-note">${esc(recoveredNote)}</div>` : '');
      // Fix it / Show the trace / Keep as is go under the reply that explains the
      // failure (design 4c), so the report is asked for its card alone.
      return `<article class="tc-code-turn is-agent" data-code-turn-key="${esc(turn.run_id || turn.ts || '')}"><div class="tc-code-turn-body">${work}${codeResults().runReportHtml(turn.report, { actions: false })}${replySection}${cards().workedLine(events, esc)}${cards().proofActionsHtml({ esc, report: turn.report })}${codeResults().artifactCardsHtml(turn, turn.run_id || turn.ts || '0')}</div></article>`;
    }

    // Thomas's answer: his head (tile and name, a dim meta line when there is
    // one, and the copy button for a saved turn) over the rendered text.
    function replyBlockHtml(text, { report, meta, metaTitle, copy } = {}) {
      const head = cards().headHtml({ esc, meta, metaTitle, copy });
      return `<div class="tc-code-reply">${head}<div class="tc-code-reply-text">${replyHtml(text, report)}</div></div>`;
    }

    // Reuse Chat's safe markdown renderer, escaping plainly if it is unavailable.
    function replyHtml(text, report) {
      let clean = String(text || '').replace(/^TITLE:[^\n]*(?:\n|$)/gim, '').replace(/^(?:DONE|NEXT):\s*/gim, '');
      // The report card already lists missing evidence and grades the checks.
      // Do not echo a second, potentially contradictory status in the reply.
      if (report) {
        clean = clean.replace(/^Unchecked \(no evidence either way\):[^\n]*(?:\n- [^\n]*)*/gim, '');
        clean = clean.replace(/^Verification:[^\n]*(?:\n|$)/gim, '');
      } else {
        clean = clean.replace(/^Unchecked \(no evidence either way\):[ \t]*(.+)$/gim, (_match, claim) =>
          `I haven't checked ${claim.trim().replace(/[.!?]+$/, '').replace(/^./, first => first.toLowerCase())} yet.`);
        clean = clean.replace(/^Unchecked \(no evidence either way\):[ \t]*\r?\n((?:- [^\n]*\r?\n?)+)/gim,
          (_match, items) => items.trim().replace(/^- /gm, 'I haven\'t checked: '));
      }
      clean = clean.replace(/\bVerification:\s*/gi, '');
      // The engine reads the closing EVIDENCE:/VERIFY: lines from the reply, so they
      // stay in it; the person is shown prose only. A stray ::: fence line is dropped.
      clean = clean.replace(/^[ \t]*`?(?:EVIDENCE|VERIFY):.*$/gim, '').replace(/^[ \t]*:{3,}[ \t\w-]*$/gm, '').replace(/\n{3,}/g, '\n\n');
      text = clean.trim();
      // The reply is one markdown block through the display kernel: same HTML as before, and the words if it cannot draw.
      const display = typeof window !== 'undefined' && window.ThomasDisplay;
      if (display && text && display.has('markdown')) return display.renderBlocks([display.blocks.markdown(text)]);
      const markdown = typeof window !== 'undefined' && window.ThomasMarkdown;
      if (markdown && typeof markdown.mdToHtml === 'function') return markdown.mdToHtml(text);
      return esc(text);
    }

    // Progress notes have the same problem as the reply -- 39 of 71 real ones carry
    // backticks or bold -- but they render inside a <span>, so the INLINE renderer
    // is the one to use: it emits <code>/<strong>/<em>/<a> and nothing block-level,
    // which drops into the existing markup without a container or stylesheet
    // change. Only 11% carry bullet lines, and a leading "- " left as a literal
    // dash reads fine in prose.
    //
    // Same escape-first guarantee as the reply path: `_mdInline` runs `esc` before
    // it introduces any tag.
    function progressHtml(text) {
      const markdown = typeof window !== 'undefined' && window.ThomasMarkdown;
      if (markdown && typeof markdown.mdInline === 'function') return markdown.mdInline(text);
      return esc(text);
    }

    // A pasted diff or file in an update can run to hundreds of lines and bury
    // the narrative around it. A fenced block longer than FOLD_CODE_LINES folds
    // behind its own disclosure; shorter blocks and all prose render as before.
    // split() with a capture group puts the fences at the odd indexes.
    const FOLD_CODE_LINES = 12;
    function progressBodyHtml(text) {
      return String(text || '').split(/(```[\s\S]*?```)/).map((part, index) => {
        if (index % 2 === 0) return part ? progressHtml(part) : '';
        const lines = part.split('\n').length - 2;
        if (lines <= FOLD_CODE_LINES) return progressHtml(part);
        return `<details class="tc-code-progress-full"><summary>Show ${lines} lines of code</summary>${progressHtml(part)}</details>`;
      }).join('');
    }

    // A blank Code surface used to be one line of encouragement above 700px of
    // empty space -- measured on a 1920x1080 screen, the hero sat at the top and
    // nothing else occupied the view down to the composer. It told you to
    // describe an outcome without showing what a good one looks like.
    //
    // These fill the composer rather than sending. A starter is a suggestion, and
    // a click that silently spends a model call on a prompt nobody read is a
    // worse surprise than one extra keystroke. The click handler lives with the
    // rest of the surface's bindings in unified_code_mode.js; what a starter
    // SAYS is transcript content, which is this file's job.
    const CODE_STARTERS = [
      { icon: 'ph-play-circle', title: 'A small game', text: 'Build a playable Minesweeper in index.html. A 9x9 grid with 10 mines, left click reveals, right click flags, and a mine counter. Plain HTML/CSS/JS.' },
      { icon: 'ph-chart-bar', title: 'A chart from data', text: 'Build report.html that reads sales.csv from the same folder and draws a bar chart of revenue per region on a canvas, with the grand total shown as text.' },
      { icon: 'ph-app-window', title: 'A little tool', text: 'Build a habit tracker in index.html: a seven day grid, click a day to toggle it done, a current streak count, and it remembers what I ticked after a reload.' },
      { icon: 'ph-wrench', title: 'Work on my code', text: 'Look at the project I have selected, tell me what it does, and suggest the three changes that would improve it most.' },
    ];

    function emptyStateHtml() {
      // A slideshow of how Thomas is doing, with the starters as its last slide (unified_code_home.js).
      if (window.ThomasCodeHome) return window.ThomasCodeHome.html(esc, CODE_STARTERS, window.ThomasIcons ? window.ThomasIcons.face('build', 15) : ANVIL_SVG);
      const cards = CODE_STARTERS.map(s => `<button class="tc-code-starter" type="button" data-code-starter="${esc(s.text)}">
      <i class="ph ${s.icon}" aria-hidden="true"></i>
      <span class="tc-code-starter-title">${esc(s.title)}</span>
      <span class="tc-code-starter-text">${esc(s.text.length > 96 ? `${s.text.slice(0, 96).trim()}…` : s.text)}</span>
    </button>`).join('');
      return `<div class="tc-code-empty">
      <span class="tc-code-avatar is-anvil" aria-hidden="true">${window.ThomasIcons ? window.ThomasIcons.face('build', 15) : ANVIL_SVG}</span>
      <strong>What should we make?</strong>
      <span class="tc-code-empty-intro">Describe the outcome in the composer below. Keep using this same conversation for changes, tests, and review.</span>
      <div class="tc-code-starters">${cards}</div>
    </div>`;
    }

    // The copy button turnHtml stamps on every Thomas turn, and what happens when
    // it is pressed. Both halves live here so the label the button reverts to
    // ("Copy reply") is written once, beside the markup that first sets it.
    //
    // The textarea path is the fallback for a browser (or an insecure origin)
    // with no async clipboard; execCommand is deprecated and still the only
    // thing that works there.
    async function copyReplyText(text, button) {
      const value = String(text || '');
      let copied = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
          copied = true;
        }
      } catch (_error) { copied = false; }
      if (!copied) {
        const area = document.createElement('textarea');
        area.value = value;
        area.setAttribute('readonly', '');
        area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
        document.body.appendChild(area);
        area.select();
        try { copied = document.execCommand('copy'); } catch (_error) { copied = false; }
        area.remove();
      }
      if (button) {
        button.title = copied ? 'Copied' : 'Copy failed';
        button.setAttribute('aria-label', button.title);
        button.textContent = copied ? 'Copied' : 'Copy';
        setTimeout(() => {
          button.title = 'Copy reply';
          button.setAttribute('aria-label', 'Copy reply');
          button.textContent = 'Copy';
        }, 1400);
      }
      return copied;
    }

    return {
      eventLabel, annotateTerminalEvent, eventType, isTechnicalEvent,
      eventHtml, finalReplyEvent, progressEvents, failureSummary, turnHtml, replyHtml, replyBlockHtml,
      elapsedLabel, transcriptEvents, transcriptText, flagExpectedProbe, interleavedActivityHtml,
      emptyStateHtml, copyReplyText, workRowOptions,
    };
  }

  window.ThomasCodeEvents = { create };
})();
