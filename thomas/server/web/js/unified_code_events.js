/* The event-render cluster, lifted out of unified_code_mode.js.
 *
 * It left because that file was 1808 lines against a 1500-line ceiling, and this
 * is the one part of it with a boundary you can state in a sentence: everything
 * that turns a run's event stream into HTML, and nothing that talks to the
 * server or owns the run. Twelve names go in, eleven come back.
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
      return event.is_error === true || (kind == null ? eventType(event) : kind) === 'error';
    }

    function technicalHeading(event, kind) {
      if (kind === 'reason') return 'Reviewed the approach';
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
      if (kind === 'tool') return `Used ${event.name || 'a project tool'}`;
      // The same overloading the comment below describes: a tool that returned an
      // error is a failed tool CALL, not a failed check. The tool's own name is
      // present on most of these and says more than the word "technical" did.
      if (event.is_error === true) return event.name ? `${event.name} failed` : 'Tool call failed';
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
      return event.name ? `Result from ${event.name}` : 'Tool result';
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
        const group = { kind, heading, label, failed, count: 1 };
        groups.push(group);
        byKey.set(key, group);
      });
      return groups;
    }

    function technicalSummary(events) {
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
      const issues = events.filter(event => event.is_error === true || eventType(event) === 'error').length;
      const other = Math.max(0, events.length - tools - results - issues);
      const parts = [];
      if (tools) parts.push(`${tools} tool ${tools === 1 ? 'run' : 'runs'}`);
      if (results) parts.push(`${results} ${results === 1 ? 'result' : 'results'}`);
      if (other) parts.push(`${other} ${other === 1 ? 'detail' : 'details'}`);
      if (issues) parts.push(`${issues} ${issues === 1 ? 'issue' : 'issues'}`);
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
    }

    function eventHtml(event, saved) {
      const kind = eventType(event);
      if (isTechnicalEvent(event)) {
        const failed = eventFailed(event, kind);
        const heading = technicalHeading(event, kind);
        return `<div class="tc-code-technical${failed ? ' is-error' : ''}" data-code-kind="${esc(kind)}"${saved ? ' data-saved="true"' : ''}><i class="ph ${failed ? 'ph-warning' : 'ph-check-circle'}"></i><div><strong>${esc(heading)}</strong><code>${esc(eventLabel(event))}</code></div></div>`;
      }
      const label = eventLabel(event);
      const content = label.length <= MAX_PROGRESS_EVENT_CHARS
        ? `<span>${progressHtml(label)}</span>`
        : `<span>${progressHtml(`${label.slice(0, 360).trimEnd()}…`)}</span><details class="tc-code-progress-full"><summary>Show full update</summary><span>${progressHtml(label)}</span></details>`;
      return `<div class="tc-code-event is-${esc(kind)}" data-code-kind="${esc(kind)}"${event.delta ? ' data-code-delta="true"' : ''}${saved ? ' data-saved="true"' : ''}><strong>${esc(eventKind(event))}</strong>${content}</div>`;
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
      return events.filter(event => {
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
        if (seen.has(label)) return false;
        seen.add(label);
        return true;
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

    function technicalActivityHtml(events, saved) {
      if (!events.length) return '';
      const groups = groupedTechnicalEvents(events);
      const rows = groups.map(group => {
        const count = group.count > 1 ? `<span class="tc-code-tech-count">×${group.count}</span>` : '';
        return `<div class="tc-code-technical${group.failed ? ' is-error' : ''}" data-code-kind="${esc(group.kind)}"><i class="ph ${group.failed ? 'ph-warning' : 'ph-check-circle'}"></i><div><strong>${esc(group.heading)}${count}</strong><code>${esc(group.label)}</code></div></div>`;
      }).join('');
      const issueCount = events.filter(event => event.is_error === true || eventType(event) === 'error').length;
      const status = !saved && state.running && state.runStartedAt
        ? `<span data-code-elapsed>Working · ${esc(elapsedLabel(state.runStartedAt))}</span>`
        : 'Show details';
      return `<details class="tc-code-saved-activity${issueCount ? ' has-issues' : ''}"${saved ? ' data-saved="true"' : ''}><summary><span class="tc-code-activity-summary"><i class="ph ${issueCount ? 'ph-warning' : 'ph-terminal-window'}"></i>${esc(technicalSummary(events))}</span><span>${status}</span></summary><div class="tc-code-technical-log">${rows}</div></details>`;
    }

    function transcriptEvents(turn) {
      const events = [];
      const terminalTracker = { name: '' };
      String(turn && turn.transcript || '').split('\n').forEach(raw => {
        const line = raw.trim(); if (!line) return;
        let parsed = null;
        if (line.startsWith('{')) {
          try { parsed = JSON.parse(line); } catch (error) { parsed = null; }
        }
        const event = annotateTerminalEvent(parsed && parsed.fc ? { type: 'output', kind: parsed.fc, name: parsed.name || '', text: parsed.text || '', is_error: parsed.is_error === true, delta: parsed.delta === true } : { type: 'output', text: raw }, terminalTracker);
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
      const reply = turn.ok
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
        ? (modelFinal && !staleLimitReply ? modelFinal : 'Finished the requested changes and passed Thomas’s verification.')
        : failureSummary(turn, events);
      const narrative = narrativeActivityHtml(activityEvents, true);
      const technicalEvents = activityEvents.filter(isTechnicalEvent);
      const resultCount = (turn.artifacts || []).filter(artifact => !isInternalResultPath(artifact.file)).length;
      return `<article class="tc-code-turn is-agent"><div class="tc-code-message-head"><span class="tc-code-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span><strong>Thomas</strong><small>${esc(turn.model || 'Code')}</small><button class="tc-code-copy" data-code-copy-reply type="button" aria-label="Copy Thomas reply"><i class="ph ph-copy"></i></button></div><div class="tc-code-turn-body">${narrative}${technicalActivityHtml(technicalEvents, true)}<div class="tc-code-reply${turn.ok ? '' : ' is-error'}">${replyHtml(reply)}</div>${codeResults().artifactCardsHtml(turn, turn.run_id || turn.ts || '0')}${codeResults().runReportHtml(turn.report)}${changedCount ? `<div class="tc-code-result-note"><span><i class="ph ph-files"></i>${changedCount} file${changedCount === 1 ? '' : 's'} changed</span></div>` : ''}</div></article>`;
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


    return {
      eventLabel, annotateTerminalEvent, eventType, isTechnicalEvent, refreshElapsed,
      eventHtml, finalReplyEvent, progressEvents, failureSummary, turnHtml, replyHtml,
      elapsedLabel, narrativeActivityHtml, technicalActivityHtml, transcriptEvents,
    };
  }

  window.ThomasCodeEvents = { create };
})();
