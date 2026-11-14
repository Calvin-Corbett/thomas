/* What Thomas asks you while a Build run works (window.ThomasCodeQuestions).
 *
 * The lead's ask.user tool writes an `ask` frame and waits; you answer with a
 * click on an option or by typing in the composer, and POST
 * /api/evolve/agent/answer hands it over (evolve_agent_run_control_routes.py).
 * The run's `answered` frame -- or the poll of /api/evolve/agent/messages,
 * which unified_code_controls.js owns -- says when a question closed.
 *
 * The questions draw in their own slot of the live turn ([data-code-live-ask]),
 * never in the feed: the feed's ring holds 120 events, and helpers that keep
 * working while you decide would scroll an open question out of it. One card
 * per question, an answered one folded to "You chose: …".
 *
 * Split out of unified_code_controls.js, which creates one per page and hands
 * in the run's state, its POST and the slot patcher; this module owns only the
 * questions it has seen.
 */
(function () {
  'use strict';

  function create(deps) {
    const { state, esc } = deps;
    const asks = new Map();      // question_id -> the `ask` frame
    const answered = new Set();
    const answerOf = new Map();  // question_id -> {answer, note}: what was chosen, and how
    const cards = () => window.ThomasCodeCards;
    const input = () => (typeof document !== 'undefined' && document.getElementById ? document.getElementById('tc-input') : null);

    // A new run on screen: its questions start empty.
    function reset() {
      asks.clear();
      answered.clear();
      answerOf.clear();
    }

    // An `ask` or `answered` frame of the run on screen.
    function observe(kind, frame) {
      const id = String(frame.question_id || '');
      if (!id) return;
      if (kind === 'ask') asks.set(id, frame);
      else if (kind === 'answered') {
        // An expired question says so in the text ("No answer in 20m; going with …").
        answered.add(id);
        answerOf.set(id, { answer: frame.answer, note: frame.text && frame.text !== frame.answer ? frame.text : '' });
      }
      syncPlaceholder();
      patch();
    }

    // open, answered or expired: an `answered` frame or your answer first, then the poll.
    function askState(id) {
      if (answered.has(id)) return 'answered';
      const polled = state.questions.find(question => question && String(question.question_id) === id);
      return polled && polled.state && polled.state !== 'open' ? polled.state : 'open';
    }

    function openQuestion() {
      if (!deps.isLive()) return null;
      const fromFrames = [...asks.values()].reverse().find(frame => askState(String(frame.question_id)) === 'open');
      if (fromFrames) return { question_id: String(fromFrames.question_id), allow_free_text: fromFrames.allow_free_text !== false };
      const fromPoll = state.questions.filter(question => question && question.state === 'open' && !answered.has(String(question.question_id))).at(-1);
      return fromPoll ? { question_id: String(fromPoll.question_id), allow_free_text: fromPoll.allow_free_text !== false } : null;
    }

    // Every question this run asked, from its frames and the poll (a question
    // only the poll knows about is drawn while it is open).
    function html() {
      if (!cards()) return '';
      const known = new Map([...asks.values()].map(frame => [String(frame.question_id), {
        question: frame.question || frame.text, options: frame.options, allow_free_text: frame.allow_free_text, who: frame.agent_title,
      }]));
      state.questions.forEach(question => {
        const id = String((question && question.question_id) || '');
        if (id && !known.has(id) && question.state === 'open') known.set(id, { ...question, who: question.agent_title });
      });
      const othersWorking = Boolean(state.roster) && state.roster.agents().some(agent => agent.id !== 'lead' && agent.state === 'working');
      return [...known.entries()].map(([id, question]) => {
        const polled = state.questions.find(item => item && String(item.question_id) === id);
        const said = answerOf.get(id) || { answer: polled ? polled.answer : null, note: '' };
        // A run that ended is no longer waiting on anything you could click.
        const now = askState(id) === 'open' && !deps.isLive() ? 'expired' : askState(id);
        return cards().askHtml({
          esc, question: { ...question, question_id: id, state: now, answer: said.answer, note: said.note },
          busy: state.answerBusy === id, waitingOn: question.who || 'Thomas', othersWorking,
        });
      }).join('');
    }

    function patch() { deps.patchSlot('[data-code-live-ask]', html()); }

    function markAsk(questionId, busy) {
      const root = deps.surfaceRoot();
      if (!root) return;
      root.querySelectorAll('[data-code-ask-option]').forEach(button => {
        if (button.dataset.questionId === questionId) button.disabled = busy;
      });
    }

    async function answer(questionId, text) {
      const id = String(questionId || '');
      const value = String(text || '').trim();
      if (!id || !value || state.answerBusy || !state.runId) return false;
      state.answerBusy = id;
      markAsk(id, true);
      try {
        const { response, data } = await deps.postJson('/api/evolve/agent/answer', { run_id: state.runId, question_id: id, answer: value });
        if (!response.ok || !data.ok) throw new Error(data.error || `The answer was not delivered (${response.status})`);
        answered.add(id);
        answerOf.set(id, { answer: value, note: '' });
        state.questions = state.questions.map(question => (String(question.question_id) === id ? { ...question, state: 'answered', answer: value } : question));
        // The run has your answer: the card folds to "You chose: …" now rather
        // than when the lead next reports in (its own `answered` frame folds
        // into the same card, keyed by the question).
        if (state.roster) state.roster.feed({ kind: 'answered', question_id: id });
        deps.pushLiveEvent({ type: 'output', kind: 'answered', question_id: id, answer: value, text: value });
        deps.render();
        return true;
      } catch (error) {
        markAsk(id, false);
        deps.recordError(error, 'Your answer was not delivered.');
        return false;
      } finally {
        state.answerBusy = '';
        syncPlaceholder();
      }
    }

    // What you TYPE while Thomas is asking answers him (unified_code_mode.js
    // asks only for composer text). true: answered; false: no open question
    // takes typed words, so it is a send; 'failed': it was your answer and did
    // not arrive -- the words go back in the composer, never into the queue.
    async function answerTyped(message) {
      const question = openQuestion();
      if (!question || !question.allow_free_text || !String(message || '').trim()) return false;
      if (await answer(question.question_id, message)) return true;
      const box = input();
      if (box && !String(box.value || '').trim()) {
        box.value = String(message);
        if (typeof box.dispatchEvent === 'function' && typeof Event === 'function') box.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return 'failed';
    }

    function syncPlaceholder() {
      const box = input();
      if (!box || !box.dataset) return;
      const question = deps.isActive() ? openQuestion() : null;
      if (question && question.allow_free_text) {
        if (box.dataset.codeAskPlaceholder === undefined) box.dataset.codeAskPlaceholder = box.placeholder || '';
        box.placeholder = 'Type your own answer…';
      } else if (box.dataset.codeAskPlaceholder !== undefined) {
        box.placeholder = box.dataset.codeAskPlaceholder;
        delete box.dataset.codeAskPlaceholder;
      }
    }

    return { reset, observe, openQuestion, html, patch, answer, answerTyped, syncPlaceholder };
  }

  window.ThomasCodeQuestions = { create };
})();
