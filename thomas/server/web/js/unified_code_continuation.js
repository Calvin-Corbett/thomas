/* unified_code_continuation.js -- the autopilot card.

   When Thomas keeps going on his own (a "done check" or a repair after a run), the page used to say "Self-continuations
   that ran: N" in a closed disclosure. This draws it as a card instead: what autopilot is doing right now (a shimmering
   line, "Initializing autopilot fix..." until it has a reason to show), each follow-up run with how it ended, and, when
   nothing is running, a summary of the whole task: how many follow-ups, how many files changed, lines added and removed.
   The data is conversation.continuation_history from /api/evolve/agent/conversations/{id}; nothing new is asked of the
   server. */
(function () {
  'use strict';

  const SHOWN = 5;
  const BAD = /fail|error|refus|crash|stopp|abort|limit|timeout|unavailable|blocked/i;
  const GOOD = /complete|done|success|pass|finish|ok\b|fixed|clean/i;

  function tone(outcome) {
    const text = String(outcome || '');
    return BAD.test(text) ? 'bad' : GOOD.test(text) ? 'ok' : 'plain';
  }

  function words(outcome) {
    const text = String(outcome || 'unknown').replace(/[_-]+/g, ' ').trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function when(ts) {
    const date = ts ? new Date(ts) : null;
    if (!date || Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function plural(count, one, many) {
    return `${count} ${count === 1 ? one : many}`;
  }

  const LOOP = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 0 1-13.7 5.6"/><path d="M4 12A8 8 0 0 1 17.7 6.4"/><path d="M17.7 2.5v3.9h-3.9M6.3 21.5v-3.9h3.9"/></svg>';

  /* history: continuation_history. running: a run is live. live: the live run is one of autopilot's own.
     totals: { added, removed, files } for the whole task. */
  function html(options, esc) {
    const history = options && options.history;
    const count = history ? Number(history.count) || 0 : 0;
    const live = Boolean(options && options.running && options.live);
    if (!count && !live) return '';
    const runs = (history && Array.isArray(history.runs) ? history.runs : []).slice().reverse();
    const next = count + 1;
    const latest = runs[0];
    const liveLine = live
      ? `<p class="tc-cont-live"><i aria-hidden="true"></i><span class="tc-cont-shimmer">${count ? `Autopilot is working on follow-up ${next}` : 'Initializing autopilot fix'}…</span>${latest && latest.reason ? `<small>After: ${esc(latest.reason)}</small>` : ''}</p>`
      : '';
    const rows = runs.slice(0, SHOWN).map(run => `<li class="is-${tone(run.outcome)}"><i aria-hidden="true"></i><div><strong>${esc(words(run.outcome))}</strong><span>${esc(run.reason || 'no reason recorded')}</span>${run.run_id ? `<em>${esc(run.run_id)}</em>` : ''}</div>${when(run.ts) ? `<time>${esc(when(run.ts))}</time>` : ''}</li>`).join('');
    const more = runs.length > SHOWN ? `<li class="tc-cont-more">${esc(plural(runs.length - SHOWN, 'earlier follow-up', 'earlier follow-ups'))}</li>` : '';
    const sums = options && options.totals ? options.totals : null;
    const summary = !live && sums
      ? `<footer class="tc-cont-sum" aria-label="Summary of this task"><span><b>${count}</b> ${count === 1 ? 'follow-up' : 'follow-ups'}</span><span><b>${sums.files}</b> ${sums.files === 1 ? 'file' : 'files'} changed</span><span class="tc-cont-add">+${sums.added}</span><span class="tc-cont-del">−${sums.removed}</span></footer>`
      : '';
    return `<section class="tc-cont${live ? ' is-live' : ''}" data-cont-card aria-label="Autopilot"><header>${LOOP}<div><strong>Autopilot</strong><small>${live ? 'Working on its own' : `Kept going on its own, ${plural(count, 'time', 'times')}`}</small></div></header>${liveLine}<ol>${rows}${more}</ol>${summary}</section>`;
  }

  window.ThomasCodeContinuation = { html };
}());
