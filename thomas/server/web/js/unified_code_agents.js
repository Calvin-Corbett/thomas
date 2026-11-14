/* Agent activity rows shared by the live Build stream and saved transcript.
 *
 * Since the 2026-10 redesign what you and Thomas say is bright, and a helper's
 * work is background: it lives in the Activity drawer, per agent, and stays out
 * of the main transcript. What still reaches the transcript from a team is
 * quiet: one dim line when a helper fails, one line per "integrated" notice,
 * and the team's running tally as a single line that updates in place (or
 * nothing, when the STEPS card already shows the plan). A lead that
 * disconnected during a restart keeps its recovered helpers' status lines --
 * it has nothing else to show. */
(function () {
  'use strict';

  const KINDS = new Set(['agent_spawned', 'agent_status', 'agent_event']);
  const STATES = new Set(['starting', 'queued', 'running', 'retrying', 'quota_wait', 'completed', 'failed', 'cancelled', 'stopped', 'interrupted']);
  // A question, a steer an agent read and a pause are yours or the run's, not
  // a helper's chatter, whoever they name.
  const CARD_KINDS = new Set(['plan', 'paused', 'resumed', 'steering', 'ask', 'answered']);

  function kindOf(event) {
    return String((event && (event.kind || event.fc || event.type)) || '').toLowerCase();
  }

  // A helper failing: its own error, a failed state, or the team's "X failed: …"
  // (build_agent_team.py turns a child's error into an is_error `meta`). A
  // failed tool call is a step it recovers from, not the helper failing.
  function isHelperError(event) {
    if (!event || !event.agent_id) return false;
    const kind = kindOf(event);
    return kind === 'error' || event.agent_state === 'failed' || (event.is_error === true && kind !== 'tool' && kind !== 'tool_result');
  }

  // "Team: 0/3 files integrated · queued 3 · …" (build_agent_scheduler.py).
  function isTeamProgress(event) {
    return Boolean(event) && kindOf(event) === 'planning' && (event.name === 'team-progress' || Boolean(event.team_progress));
  }

  // The team's note about one helper ("Home page helper: integrated (index.html)").
  function isTeamNotice(event) {
    return Boolean(event) && !event.agent_id && Boolean(event.team_id) && kindOf(event) === 'meta' && !event.receipt;
  }

  // Thomas's own bookkeeping that a card already shows: the plan.update and
  // ask.user calls (the STEPS card, the question card) and the team's model
  // roll call (the drawer names each agent's model).
  const CARD_TOOLS = new Set(['plan.update', 'ask.user']);
  function isBookkeeping(event) {
    const kind = kindOf(event);
    if ((kind === 'tool' || kind === 'tool_started' || kind === 'tool_result') && CARD_TOOLS.has(String(event.name || ''))) return true;
    return kind === 'planning' && /^Build team models\b/.test(String(event.text || '').trim());
  }

  // Drawn by render() below rather than as a work row.
  function isLine(event) {
    return Boolean(event && ((event.agent_id && KINDS.has(kindOf(event))) || isHelperError(event) || isTeamNotice(event)));
  }

  // "Contact page helper" from the team's "Contact page helper: failed (contact.html)".
  function noticeTitle(event) {
    const named = /^([^:\n]{1,80}):\s/.exec(String(event.text || '').trim());
    return named ? named[1] : '';
  }

  // The marks a shown failure leaves: its helper's id and its title, so the
  // team's own "Title: failed (path)" after it is not a second line.
  function erredMarks(event) {
    return [`id:${event.agent_id}`, `title:${String(event.agent_title || '').trim()}`];
  }

  // Whether the main transcript leaves this event to the drawer. `erred` holds
  // the helpers whose failure already has its line, so each fails once.
  function hides(event, erred) {
    if (!event || typeof event !== 'object') return false;
    if (CARD_KINDS.has(kindOf(event)) || event.praxis_recovered === true) return false;
    if (isTeamProgress(event) || isBookkeeping(event)) return true;
    if (isTeamNotice(event)) return event.is_error === true && erred.delete(`title:${noticeTitle(event)}`);
    if (!event.agent_id) return false;
    if (!isHelperError(event)) return true;
    if (erred.has(`id:${event.agent_id}`)) return true;
    erredMarks(event).forEach(mark => erred.add(mark));
    return false;
  }

  // A saved turn's events, or the live ones, as the transcript tells them.
  function forTranscript(events) {
    const erred = new Set();
    return (Array.isArray(events) ? events : []).filter(event => !hides(event, erred));
  }

  // One new live frame, given what the feed already holds.
  function hiddenLive(event, shown) {
    const erred = new Set((Array.isArray(shown) ? shown : []).filter(item => item !== event && isHelperError(item)).flatMap(erredMarks));
    return hides(event, erred);
  }

  function latestTeamProgress(events) {
    return (Array.isArray(events) ? events : []).filter(isTeamProgress).at(-1) || null;
  }

  // The tally as one quiet line; the newest one wins.
  function teamHtml(event, esc) {
    const text = String((event && event.text) || '').trim();
    if (!text) return '';
    return `<div class="tc-code-quietline is-team${event.is_error ? ' is-failed' : ''}" data-code-kind="team-progress">${esc(text)}</div>`;
  }

  function render(event, esc, saved) {
    const kind = kindOf(event);
    const savedAttr = saved ? ' data-saved="true"' : '';
    if (isTeamNotice(event)) {
      const text = String(event.text || '').trim();
      const named = /^([^:\n]{1,80}):\s+([\s\S]+)$/.exec(text);
      const tone = event.is_error === true ? ' is-failed' : '';
      return `<div class="tc-code-agentline is-team${tone}" data-code-kind="meta"${savedAttr}><span class="tc-code-agentline-name">${esc(named ? named[1] : 'Team')}</span><span class="tc-code-agentline-text">${esc(named ? named[2] : text)}</span></div>`;
    }
    if (!event.agent_id || !(KINDS.has(kind) || isHelperError(event))) return '';
    const title = String(event.agent_title || 'Agent');
    const state = STATES.has(event.agent_state) ? (event.agent_state === 'quota_wait' ? 'resuming' : event.agent_state) : '';
    const model = String(event.model || '').trim();
    const mode = String(event.agent_mode || '').trim();
    const description = [mode, model, state].filter(Boolean).join(' · ');
    // A team child's lines arrive prefixed "[Title] "; the name column already says who.
    const text = String(event.text || '').trim().replace(/^\[([^\]]*)\]\s*/, (whole, name) => (name === title ? '' : whole));
    const tone = state === 'failed' || isHelperError(event) ? ' is-failed' : '';
    return `<div class="tc-code-agentline${tone}" data-code-kind="${esc(kind)}" data-agent-id="${esc(String(event.agent_id))}"${savedAttr}><span class="tc-code-agentline-name">${esc(title)}</span><span class="tc-code-agentline-text">${esc(description)}${description && text ? ' · ' : ''}${esc(text)}</span></div>`;
  }

  window.ThomasCodeAgentRows = {
    render, isLine, isHelperError, isTeamProgress, isTeamNotice, forTranscript, hiddenLive, latestTeamProgress, teamHtml,
  };
})();
