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
 */
(function () {
  'use strict';

  function create(deps) {
    const {
      MAX_VISIBLE_PROGRESS_EVENTS, MAX_PROGRESS_EVENT_CHARS, NARRATIVE_EVENT_KINDS, state, esc,
      codeResults, surface, isInternalResultPath, safely, pushLiveEvent, render, send,
    } = deps;

    // Code-Thomas wears the anvil — he builds (owner, 2026-08-10). Chat keeps
    // its own avatar; this badge is Code mode's only.
    const ANVIL_SVG = '<svg viewBox="0 0 256 256" aria-hidden="true"><path d="M240 60h-92a12 12 0 0 0 0 24h6.6c-4 24.5-22.8 44-47 48.6C82.9 137.4 64 121.4 64 96V84h12a12 12 0 0 0 0-24H24a12 12 0 0 0 0 24h16v12c0 34.6 24.7 58.5 56 63.4v10.2c0 11-4.7 21.4-13 28.6l-18.9 16.5A12 12 0 0 0 72 236h112a12 12 0 0 0 7.9-21.1L173 198.4a38.2 38.2 0 0 1-13-28.6v-10.6c37.5-6 66.2-35 70.7-71.2H240a12 12 0 0 0 0-24Z"/></svg>';

    function _safe(value) { return typeof value === 'string' ? value.trim() : ''; }

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
      return kind.replace(/_/g, ' ');
    }

    function isTerminalTool(name) {
      return /(?:^|[._-])(shell|bash|powershell|cmd|terminal|command)(?:$|[._-])/i.test(String(name || ''));
    }

    function annotateTerminalEvent(event, tracker) {
      const kind = String(event.kind || event.fc || event.type || 'activity').toLowerCase();
      if (kind === 'tool') {
        tracker.name = isTerminalTool(event.name) ? String(event.name || 'terminal') : '';
        if (tracker.name) { event.terminal = true; event.terminalTool = tracker.name; }
      } else if (kind === 'tool_result' && tracker.name) {
        event.terminal = true; event.terminalTool = tracker.name; tracker.name = '';
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
      return event.terminal === true || containsToolProtocol(event) || !NARRATIVE_EVENT_KINDS.has(eventType(event));
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

    // One failure predicate for the whole file. There used to be two, and they
    // disagreed: `eventHtml` asked `is_error === true`, while
    // `groupedTechnicalEvents` asked `is_error === true || kind === 'error'`.
    // `technicalHeading` sided with the second.
    //
    // So a live `error` event -- the shape `pushLiveEvent({ type: 'error' })`
    // produces, which never sets `is_error` -- rendered the failure WORDS under a
    // green `ph-check-circle`, and without the `is-error` class that colours the
    // row. Seen on screen by opening a deliverable deep link whose task no longer
    // exists: a green tick directly above the word "failed".
    //
    // Live-vs-saved is the axis that hid it. The grouped path was already right,
    // so the finished transcript of the same run looked correct; only the run you
    // were watching lied.
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
      if (kind === 'meta') return 'Workspace update';
      return event.name ? humanToolHeading(event.name, `Result from ${event.name}`) : 'Tool result';
    }

    // "Result from fs.read_file" tells a non-technical reader nothing (owner,
    // 2026-08-10). The tool's own name still appears in the expanded body;
    // the ROW says what happened in words a person uses.
    const TOOL_HEADINGS = [
      [/fs[._-]?read/i, 'Read a file'],
      [/fs[._-]?write/i, 'Wrote a file'],
      [/fs[._-]?(list|dir)/i, 'Looked in a folder'],
      [/fs[._-]?(delete|remove)/i, 'Removed a file'],
      [/project_structure/i, 'Looked at the project layout'],
      [/search|grep|find/i, 'Searched the code'],
      [/diff/i, 'Compared changes'],
      [/shell|terminal|bash|powershell|cmd/i, 'Ran a terminal command'],
      [/http|fetch|web|download/i, 'Fetched from the web'],
      [/image|render|screenshot/i, 'Made an image'],
    ];
    function humanToolHeading(name, fallback) {
      const match = TOOL_HEADINGS.find(([pattern]) => pattern.test(String(name || '')));
      return match ? match[1] : fallback;
    }

    function groupedTechnicalEvents(events) {
      const groups = [];
      const byKey = new Map();
      events.forEach(event => {
        const kind = eventType(event);
        const heading = technicalHeading(event, kind);
        const label = eventLabel(event);
        const failed = eventFailed(event, kind);
        const key = `${kind}\u0000${failed ? '1' : '0'}\u0000${heading}\u0000${label}`;
        const existing = byKey.get(key);
        if (existing) { existing.count += 1; return; }
        const group = { kind, heading, label, failed, count: 1, name: _safe(event.name) };
        groups.push(group);
        byKey.set(key, group);
      });
      return groups;
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

    function refreshElapsed() {
      const label = surface()?.querySelector('[data-code-elapsed]');
      if (label && state.running && state.runStartedAt) label.textContent = `Working · ${elapsedLabel(state.runStartedAt)}`;
      // The Activity pill up top AND the live turn head carry the same clock
      // (owner: "working up top needs the timer for how long next to it").
      if (state.running && state.runStartedAt) {
        const clock = elapsedLabel(state.runStartedAt);
        surface()?.querySelectorAll('[data-code-elapsed-top]').forEach(node => { node.textContent = clock; });
      }
    }

    function eventHtml(event, saved, count) {
      const kind = eventType(event);
      if (isTechnicalEvent(event)) {
        // The prototype contract (owner, 2026-08-10): a receipt is ONE line a
        // non-technical reader can parse — humanized verb, first line of the
        // result, a chevron — and the full output lives behind the click,
        // expanding inline (the page scrolls; no box-in-a-box).
        const failed = eventFailed(event, kind);
        const heading = technicalHeading(event, kind);
        // eventLabel is called directly rather than through a shared `label`
        // const: raw tool output must be ESCAPED here, while prose below is
        // rendered as inline markdown, and tests/test_the_run_report_escapes_
        // what_thomas_wrote.py reads this branch on its own to confirm the two
        // never swap. A shared const hides the escaper from that check.
        const preview = eventLabel(event).split('\n')[0].trim().slice(0, 96);
        const times = Number(count) > 1 ? `<span class="tc-code-receipt-count">×${Number(count)}</span>` : '';
        // The ROW speaks human ("Wrote a file"), because the raw tool id told
        // the owner nothing. The tool that produced it is not thrown away:
        // it rides the row as data + tooltip and heads the expanded body, so
        // "which tool did this" stays answerable without cluttering the line.
        const toolName = _safe(event.name);
        const toolAttr = toolName ? ` data-code-tool="${esc(toolName)}" title="${esc(toolName)}"` : '';
        const toolLine = toolName ? `<span class="tc-code-receipt-tool">${esc(toolName)}</span>` : '';
        return `<details class="tc-code-receipt tc-code-technical${failed ? ' is-error' : ''}" data-code-kind="${esc(kind)}"${toolAttr}${saved ? ' data-saved="true"' : ''}><summary><i class="ph ${failed ? 'ph-warning' : 'ph-check-circle'}"></i><strong>${esc(heading)}</strong>${times}<span class="tc-code-receipt-preview">${esc(preview)}</span><i class="ph ph-caret-down tc-code-receipt-chev"></i></summary>${toolLine}<pre>${esc(eventLabel(event))}</pre></details>`;
      }
      const label = eventLabel(event);
      if (kind === 'say' || kind === 'final') {
        // Thomas's own words ARE the feed: no kind chip, full text, prominent.
        // A note past the char cap still folds behind one disclosure so a
        // single monster paragraph cannot swamp the run - normal speech is far
        // under the cap and never folds.
        if (label.length > MAX_PROGRESS_EVENT_CHARS) {
          return `<div class="tc-code-say" data-code-kind="${esc(kind)}"${saved ? ' data-saved="true"' : ''}>${progressHtml(`${label.slice(0, 360).trimEnd()}…`)}<details class="tc-code-progress-full"><summary>Show full update</summary><span>${progressHtml(label)}</span></details></div>`;
        }
        return `<div class="tc-code-say" data-code-kind="${esc(kind)}"${event.delta ? ' data-code-delta="true"' : ''}${saved ? ' data-saved="true"' : ''}>${progressHtml(label)}</div>`;
      }
      const content = label.length <= MAX_PROGRESS_EVENT_CHARS
        ? `<span>${progressHtml(label)}</span>`
        : `<span>${progressHtml(`${label.slice(0, 360).trimEnd()}…`)}</span><details class="tc-code-progress-full"><summary>Show full update</summary><span>${progressHtml(label)}</span></details>`;
      return `<div class="tc-code-event is-${esc(kind)}" data-code-kind="${esc(kind)}"${event.delta ? ' data-code-delta="true"' : ''}${saved ? ' data-saved="true"' : ''}><strong>${esc(eventKind(event))}</strong>${content}</div>`;
    }

    function interleavedActivityHtml(events, saved) {
      // Chronological truth, prototype layout: narration sits at the left
      // edge, consecutive receipts cluster on a railed vertical UNDER the
      // sentence they back up, and the rail breaks whenever Thomas talks.
      // Runs read the same file dozens of times back to back — consecutive
      // receipts with the same row face merge into one row with a count, and
      // a cluster longer than eight rows folds its middle behind one line.
      const MAX_OPEN_RECEIPTS = 8;
      const parts = [];
      let cluster = [];
      const receiptKey = event => {
        const kind = eventType(event);
        return `${technicalHeading(event, kind)}\0${eventFailed(event, kind) ? 1 : 0}\0${eventLabel(event).split('\n')[0].trim().slice(0, 96)}`;
      };
      const flush = () => {
        if (!cluster.length) return;
        const merged = [];
        cluster.forEach(event => {
          const key = receiptKey(event);
          const last = merged[merged.length - 1];
          if (last && last.key === key) { last.count += 1; return; }
          merged.push({ key, event, count: 1 });
        });
        const rows = merged.map(entry => eventHtml(entry.event, saved, entry.count));
        let body;
        if (rows.length > MAX_OPEN_RECEIPTS) {
          const hidden = rows.slice(3, rows.length - 2);
          body = rows.slice(0, 3).join('')
            + `<details class="tc-code-receipts-more"><summary>${hidden.length} more steps</summary>${hidden.join('')}</details>`
            + rows.slice(rows.length - 2).join('');
        } else {
          body = rows.join('');
        }
        parts.push(`<div class="tc-code-receipts">${body}</div>`);
        cluster = [];
      };
      events.forEach(event => {
        if (isTechnicalEvent(event)) { cluster.push(event); return; }
        flush();
        parts.push(eventHtml(event, saved));
      });
      flush();
      return parts.join('');
    }

    function finalReplyEvent(events, turn) {
      const explicit = events.filter(event => eventType(event) === 'final').at(-1);
      if (explicit) return explicit;
      if (turn && turn.ok) return events.filter(event => eventType(event) === 'say').at(-1) || null;
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
      // Deduped on the label rather than by dropping every non-last `final`,
      // because the two finals in that run said different things and one of them
      // was the only place its text appeared. Keeping the FIRST occurrence
      // preserves the content and drops only the verbatim repeat.
      //
      // Technical events are exempt: repeated tool rows are the log, and
      // collapsing them would hide real repetition rather than noise.
      const seen = new Set();
      const repeats = new Map();
      const kept = events.filter(event => {
        if (event === finalEvent) return false;
        if (finalText && eventType(event) === 'say' && eventLabel(event) === finalText) return false;
        if (isTechnicalEvent(event)) return true;
        const label = String(eventLabel(event) || '').trim();
        // A row whose text only repeats its own heading says nothing. The stream's
        // `done` event carries the literal string "done", so every run grew a
        // "DONE / done" line -- transient while running, but left sitting in the
        // transcript after a Stop, where it reads as debug output beside the real
        // "Stopped — you interrupted this run." note.
        //
        // Keyed on the label adding nothing to its kind, not on the kind itself,
        // so a `done` event that ever carries real text still gets its row. Placed
        // here rather than in narrativeActivityHtml because the LIVE feed does not
        // go through that function -- it maps eventHtml straight off this list, so
        // a filter over there fixed the saved transcript and left the live one
        // untouched. This is the seam both paths share.
        if (!label || label.toLowerCase() === String(eventKind(event) || '').trim().toLowerCase()) return false;
        if (seen.has(label)) {
          repeats.set(label, (repeats.get(label) || 1) + 1);
          return false;
        }
        seen.add(label);
        return true;
      });
      // Keep the collapse, keep the count.
      //
      // The exemption above says repeated tool rows must survive because
      // "collapsing them would hide real repetition rather than noise". That
      // argument does not stop being true for the notes the OWNER reads. A run
      // that announced "Running the test suite." five times looped five times;
      // with the repeats dropped and nothing in their place it read as one clean
      // step, and the clean step is the wrong story.
      //
      // So the feed stays short -- one row per distinct note -- and the row says
      // how many times it happened. Annotated on a copy, never on the stored
      // event, because this list is rendered repeatedly and mutating it would
      // multiply the counter on every repaint.
      if (!repeats.size) return kept;
      return kept.map(event => {
        const times = repeats.get(String(eventLabel(event) || '').trim());
        return times ? { ...event, text: `${String(eventLabel(event) || '').trim()} ×${times}` } : event;
      });
    }

    function narrativeActivityHtml(events, saved) {
      const narrative = events.filter(event => !isTechnicalEvent(event));
      const progressIndexes = narrative
        .map((event, index) => ['insight', 'planning', 'say'].includes(eventType(event)) ? index : -1)
        .filter(index => index >= 0);
      if (progressIndexes.length <= MAX_VISIBLE_PROGRESS_EVENTS) {
        return narrative.map(event => eventHtml(event, saved)).join('');
      }
      const visibleProgress = new Set([
        progressIndexes[0],
        ...progressIndexes.slice(-(MAX_VISIBLE_PROGRESS_EVENTS - 1)),
      ]);
      const hiddenProgress = progressIndexes.filter(index => !visibleProgress.has(index));
      const hiddenAt = hiddenProgress[0];
      return narrative.map((event, index) => {
        if (index === hiddenAt) {
          const rows = hiddenProgress.map(hiddenIndex => eventHtml(narrative[hiddenIndex], saved)).join('');
          return `<details class="tc-code-progress-history"><summary>${hiddenProgress.length} earlier progress ${hiddenProgress.length === 1 ? 'note' : 'notes'}</summary><div>${rows}</div></details>`;
        }
        return hiddenProgress.includes(index) ? '' : eventHtml(event, saved);
      }).join('');
    }

    function technicalActivityHtml(events, saved, ok) {
      if (!events.length) return '';
      const groups = groupedTechnicalEvents(events);
      const rows = groups.map(group => {
        const count = group.count > 1 ? `<span class="tc-code-tech-count">×${group.count}</span>` : '';
        // Human heading, tool still named (owner redline 2026-08-10): the
        // reader gets "Wrote a file", and "which tool" stays answerable.
        const tool = group.name ? ` data-code-tool="${esc(group.name)}" title="${esc(group.name)}"` : '';
        const toolTag = group.name ? `<span class="tc-code-receipt-tool">${esc(group.name)}</span>` : '';
        return `<div class="tc-code-technical${group.failed ? ' is-error' : ''}" data-code-kind="${esc(group.kind)}"${tool}><i class="ph ${group.failed ? 'ph-warning' : 'ph-check-circle'}"></i><div><strong>${esc(group.heading)}${count}</strong>${toolTag}<code>${esc(group.label)}</code></div></div>`;
      }).join('');
      const issueCount = events.filter(event => eventFailed(event)).length;
      // The warning icon and the has-issues tint belong to runs that FAILED.
      // On an ok run the same errors are recovered attempts (see
      // technicalSummary), and an alarm over a delivered result teaches the
      // reader to ignore the alarm. Full detail stays behind Show details
      // either way -- nothing is dropped, only labelled by outcome.
      const alarming = issueCount > 0 && ok !== true;
      const status = !saved && state.running && state.runStartedAt
        ? `<span data-code-elapsed>Working · ${esc(elapsedLabel(state.runStartedAt))}</span>`
        : 'Show details';
      return `<details class="tc-code-saved-activity${alarming ? ' has-issues' : ''}"${saved ? ' data-saved="true"' : ''}><summary><span class="tc-code-activity-summary"><i class="ph ${alarming ? 'ph-warning' : 'ph-terminal-window'}"></i>${esc(technicalSummary(events, ok))}</span><span>${status}</span></summary><div class="tc-code-technical-log">${rows}</div></details>`;
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

    function transcriptEvents(turn) {
      const events = [];
      const terminalTracker = { name: '' };
      // Tracks whether a tool_result has been seen yet, so only the FIRST one
      // can be flagged as the expected read probe of an empty project.
      let sawToolResult = false;
      transcriptText(turn).split('\n').forEach(raw => {
        const line = raw.trim(); if (!line) return;
        let parsed = null;
        if (line.startsWith('{')) {
          try { parsed = JSON.parse(line); } catch (error) { parsed = null; }
        }
        const event = annotateTerminalEvent(parsed && parsed.fc ? { type: 'output', kind: parsed.fc, name: parsed.name || '', text: parsed.text || '', is_error: parsed.is_error === true, delta: parsed.delta === true } : { type: 'output', text: raw }, terminalTracker);
        if (eventType(event) === 'tool_result') {
          flagExpectedProbe(event, sawToolResult);
          sawToolResult = true;
        }
        const previous = events[events.length - 1];
        const priorSayText = events.filter(item => item.kind === 'say' && item.delta).map(item => item.text || '').join('');
        if (event.kind === 'say' && event.delta && previous && previous.kind === 'say' && previous.delta) previous.text += event.text;
        else if (event.kind === 'say' && !event.delta && priorSayText && eventLabel(event) === priorSayText) return;
        else if (eventLabel(event) && (isTechnicalEvent(event) || !previous || event.kind !== previous.kind || eventLabel(event) !== eventLabel(previous))) events.push(event);
      });
      return events;
    }

    function failureSummary(turn, events) {
      if (turn.ok) return String(turn.reason || '').trim() || 'Verified Code result';
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
      // event at all. Every one of them told the owner "The Code task stopped
      // before it finished." and nothing else, four times over, while `reason`
      // held "exited 1" the whole time.
      //
      // "no error was recorded" is worth saying out loud: it distinguishes a run
      // that failed silently from one whose reason is being withheld, and it is
      // the difference between looking for a message and knowing there is none.
      // Still no invented cause -- there genuinely was not one.
      const ending = String((turn && turn.reason) || '').trim();
      return ending
        ? `The Code task stopped before it finished — ${ending}, with no error recorded.`
        : 'The Code task stopped before it finished.';
    }

    function turnHtml(turn) {
      if (turn.role === 'user') return `<article class="tc-code-turn is-user"><div>${esc(turn.text)}</div></article>`;
      const changedCount = (turn.changed_files || []).filter(file => !isInternalResultPath(file)).length;
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
        // Keep "passed Thomas's verification" -- it is EARNED where this fires,
        // and I tried to remove it before understanding that.
        //
        // This fallback has two routes. The one that occurs is `staleLimitReply`:
        // the model claims it could not act ("no files were changed and
        // verification has not been claimed") while the same transcript carries
        // BROWSER_SMOKE_OK and "engine checks passed" and the turn is ok with a
        // changed file. The model's reply is simply wrong, engine evidence wins,
        // and the claim is true. `proveEvidenceAndRefresh` pins exactly that.
        //
        // The other route -- ok with no `final` event at all -- would claim a
        // verification on the strength of `turn.ok`, which is only exit 0 with
        // files changed. Measured across 56 agent turns: 0 of 41 successful ones
        // lacked a final event, so it does not happen today. If it ever does, the
        // fix is to condition the wording on real passing evidence, NOT to drop
        // it -- dropping it throws away the correction in the case that matters.
        replySection = `<div class="tc-code-reply">${replyHtml(answer || 'Finished the requested changes and passed Thomas’s verification.')}</div>`;
      } else if (wasStopped) {
        // A stop the user asked for is not a failure and must not wear the red
        // pipeline. This rendered through failureSummary -- "The Code task
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
        replySection = `${answer ? `<div class="tc-code-reply">${replyHtml(answer)}</div>` : ''}<div class="tc-code-reply is-stopped">${esc(note)}</div>`;
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
          ? `<div class="tc-code-reply">${replyHtml(answer)}</div><div class="tc-code-reply is-error">${replyHtml(failure)}</div>`
          : `<div class="tc-code-reply is-error">${replyHtml(failure)}</div>`;
      }
      const interleaved = interleavedActivityHtml(activityEvents, true);
      const resultCount = (turn.artifacts || []).filter(artifact => !isInternalResultPath(artifact.file)).length;
      // An error the run RECOVERED from is a failed attempt, not an issue.
      // The old collapsed activity block carried that framing; the inline feed
      // shows the red rows on their own, so without this line a successful run
      // reads as alarming. Same wording, same honesty rule (guarded by
      // test_a_failed_run_still_shows_the_answer_it_produced).
      const technicalEvents = activityEvents.filter(isTechnicalEvent);
      const recoveredNote = technicalEvents.some(event => eventFailed(event))
        ? `<div class="tc-code-attempt-note">${esc(technicalSummary(technicalEvents, turn.ok === true))}</div>`
        : '';
      // The turn ends in a CLOSING SECTION the owner can feel (2026-08-10):
      // activity first, then the verdict and the change list, then a labelled
      // horizontal rule — "this is the end of the reply" — and below it only
      // the final words and the deliverable.
      const changedList = (turn.changed_files || []).filter(file => !isInternalResultPath(file));
      const changesBlock = changedList.length
        ? `<details class="tc-code-artifact-changes"><summary>See every change · ${changedList.length} file${changedList.length === 1 ? '' : 's'}</summary><div>${changedList.map(file => `<span class="tc-code-change-row"><i class="ph ph-file-text" aria-hidden="true"></i>${esc(String(file))}</span>`).join('')}</div></details>`
        : '';
      const closingLabel = turn.ok ? 'Work completed' : (wasStopped ? 'Stopped here' : 'Run ended');
      const closing = `<div class="tc-code-closing"><span class="tc-code-closing-label">${esc(closingLabel)}</span></div>`;
      return `<article class="tc-code-turn is-agent"><div class="tc-code-message-head"><span class="tc-code-avatar is-anvil" aria-hidden="true">${window.ThomasIcons ? window.ThomasIcons.face('build', 15) : ANVIL_SVG}</span><strong>Thomas</strong><small>${esc(turn.model || 'Code')}</small><button class="tc-code-copy" data-code-copy-reply type="button" aria-label="Copy Thomas reply"><i class="ph ph-copy"></i></button></div><div class="tc-code-turn-body">${interleaved}${recoveredNote}${codeResults().runReportHtml(turn.report)}${changesBlock}${closing}${replySection}${codeResults().artifactCardsHtml(turn, turn.run_id || turn.ts || '0')}</div></article>`;
    }

    // Thomas writes markdown in his Code replies -- 16 of 17 real replies carry it
    // -- and this surface printed it raw: "Built it as a standalone **Nova**
    // calculator experience in `index.html`." The same prose in Chat renders
    // properly, because Chat runs it through mdToHtml. Same model, same sentence,
    // two treatments.
    //
    // Uses Chat's renderer rather than a second copy: `_mdInline` escapes first
    // and only then introduces tags, so untrusted model text stays inert. The
    // fallback is the plain escaper, which is what the Node contract harness gets
    // -- it loads this module with no shell around it, so `window.ThomasMarkdown`
    // is absent there and the reply must still render safely.
    function replyHtml(text) {
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
        const icon = button.querySelector('i');
        button.title = copied ? 'Copied' : 'Copy failed';
        button.setAttribute('aria-label', button.title);
        if (icon && copied) icon.className = 'ph ph-check';
        setTimeout(() => {
          button.title = 'Copy reply';
          button.setAttribute('aria-label', 'Copy reply');
          if (icon) icon.className = 'ph ph-copy';
        }, 1400);
      }
      return copied;
    }

    return {
      eventLabel, annotateTerminalEvent, eventType, isTechnicalEvent, refreshElapsed,
      eventHtml, finalReplyEvent, progressEvents, failureSummary, turnHtml, replyHtml,
      elapsedLabel, narrativeActivityHtml, technicalActivityHtml, transcriptEvents,
      flagExpectedProbe, interleavedActivityHtml, emptyStateHtml, copyReplyText,
    };
  }

  window.ThomasCodeEvents = { create };
})();
