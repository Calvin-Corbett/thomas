export function createPresentationCases({ api, resetState, state, snapshots }) {
  async function proveARepeatedStepStillLooksRepeated() {
    // The filter that collapses a duplicated progress note exempts technical rows,
    // because -- its own words -- "collapsing them would hide real repetition rather
    // than noise". That argument does not stop being true for the notes the owner
    // reads. A run that announced "Running the test suite." five times looped five
    // times, and with the repeats dropped and nothing in their place it read as one
    // clean step. The clean step is the wrong story.
    const looped = Array.from({ length: 5 }, () => ({ type: 'say', kind: 'say', text: 'Running the test suite.' }));
    looped.push({ type: 'say', kind: 'say', text: 'All checks passed.' });
    const kept = api.progressEvents(looped, null);

    // Nothing is merged: every note is shown, in order, and none grows a counter.
    if (kept.length !== 6) throw new Error(`repeats were merged or dropped: ${kept.length} rows, expected 6`);
    if (kept.some(e => /×/.test(String(e.text || '')))) throw new Error('a repeated note was labelled with a count');

    // And the stored events must be untouched: this list is re-rendered on every
    // repaint, so annotating in place would multiply the counter each time.
    if (looped.some(e => /×/.test(String(e.text || '')))) {
      throw new Error('the counter was written onto the stored event, so it will compound on repaint');
    }
  }

  async function proveTheActionSurvivesTheReason() {
    // The mirror of the case above. That one recovered the *reason* when a wrapper
    // buried it; this one recovers the *action*, which errorText used to throw away
    // outright: it returned error.message whenever there was one, and a server error
    // almost always has one. Every "Could not open that Code task." the callers pass
    // in -- fourteen of them -- was written, handed over, and dropped on the floor.
    //
    // Taken from a real click: My Stuff's deep link to a task that no longer exists
    // rendered "not found", twice, and never once said what had not been found.
    const both = api.errorText(new Error('not found'), 'Could not open that Code task.');
    if (!/Could not open that Code task/.test(both)) throw new Error('the action was discarded: ' + both);
    if (!/not found/.test(both)) throw new Error('the reason was discarded: ' + both);

    // No usable reason -> the caller's sentence stands alone, unchanged.
    const bare = api.errorText(new Error(''), 'Could not steer the Code task.');
    if (bare !== 'Could not steer the Code task.') throw new Error('an empty reason mangled the fallback: ' + bare);
    const notAnError = api.errorText({ message: 'ignored' }, 'Could not stop the Code run.');
    if (notAnError !== 'Could not stop the Code run.') throw new Error('a non-Error was treated as a reason: ' + notAnError);

    // And it must not say the same thing twice.
    const same = api.errorText(new Error('Could not keep that change.'), 'Could not keep that change.');
    if (same !== 'Could not keep that change.') throw new Error('an identical reason was doubled: ' + same);
    const restated = api.errorText(
      new Error('Could not open that Code task: it was deleted'), 'Could not open that Code task.');
    if (restated.indexOf('Could not open that Code task') !== restated.lastIndexOf('Could not open that Code task')) {
      throw new Error('a reason that already named the action was doubled: ' + restated);
    }
  }

  async function proveTheRealReasonSurvivesTheExitWrapper() {
    // Errors arrive oldest-first and the last is almost always `agent loop
    // exited 1`, a wrapper that says nothing. The summary took `.at(-1)` and only
    // then asked whether it was usable, so it always inspected the wrapper,
    // rejected it, and fell back to "Thomas hit a technical problem ... open the
    // technical details for the raw error" -- while the plain-language cause sat
    // one entry earlier, already in hand.
    //
    // Taken from a real failed run: the owner asked for a calculator app, the
    // provider was overloaded, and Thomas told him to go dig for the reason.
    resetState();
    const overloaded = api.failureSummary({ ok: false }, [
      { type: 'error', text: 'Our servers are currently overloaded. Please try again later.' },
      { type: 'error', text: 'agent loop exited 1' },
    ]);
    if (/technical problem/i.test(overloaded)) throw new Error('the real reason was discarded in favour of the generic message');
    if (!/busy|again in a moment/i.test(overloaded)) throw new Error('an overloaded provider was not named as such');
    // "Our servers" reads as THOMAS's servers unless the message says whose.
    if (!/provider/i.test(overloaded)) throw new Error('the message did not say whose servers were busy');

    // A useful error that is NOT an overload must still be shown verbatim
    // instead of being swallowed by the trailing wrapper.
    const readOnly = api.failureSummary({ ok: false }, [
      { type: 'error', text: 'The project folder is read-only, so no files could be written.' },
      { type: 'error', text: 'agent loop exited 1' },
    ]);
    if (!readOnly.includes('read-only')) throw new Error('a usable earlier error was lost behind the exit wrapper');

    // And when every recorded error IS a wrapper there is genuinely nothing
    // worth showing, so the generic message is the honest answer.
    const wrappersOnly = api.failureSummary({ ok: false }, [
      { type: 'error', text: 'agent loop exited 1' },
      { type: 'error', text: 'exited 1' },
    ]);
    if (!/technical problem/i.test(wrappersOnly)) throw new Error('unusable errors should still fall back to the generic message');

    // A run that dies with NO error event still knows two things: how it ended,
    // and that nothing explained why. Measured on four consecutive runs of one
    // goal, each recording three events then exiting 1 with no error: every one
    // said only "The Code task stopped before it finished."
    const silentWithReason = api.failureSummary({ ok: false, reason: 'exited 1' }, []);
    if (!silentWithReason.includes('exited 1')) throw new Error('a silent failure hides how it ended');
    if (!/no error recorded/i.test(silentWithReason)) {
      throw new Error('a silent failure does not distinguish itself from a withheld reason');
    }
    // And with nothing to say, it must not invent anything.
    const silentNoReason = api.failureSummary({ ok: false }, []);
    if (/exited|no error recorded/i.test(silentNoReason)) throw new Error('a reason was invented where none existed');

    // No errors at all is a third, distinct case and must not borrow either.
    const silent = api.failureSummary({ ok: false }, []);
    if (/technical problem/i.test(silent)) throw new Error('a silent failure was reported as a surfaced error');

    // A run cut off by its pass budget did not fail its repair attempts -- it
    // never finished them. Both errors are present on a real truncated run, and
    // the ORDER of the branches is the whole fix: the verification branch used to
    // match first and sent the owner to inspect a check, while the sentence that
    // said what to do sat unread in a collapsed risk row.
    //
    // Taken from the study-planner run, whose recorded errors were exactly these
    // two, in this order.
    const truncated = api.failureSummary({ ok: false }, [
      {
        type: 'error',
        text: 'Pass budget exhausted after 10 passes while work was still active. The task is incomplete; continue it in the same conversation.',
      },
      { type: 'error', text: 'verification failed (exit 1) after fix attempts' },
    ]);
    if (/repair attempts|still failed/i.test(truncated)) {
      throw new Error('a truncated run was reported as one that failed its repair attempts');
    }
    if (!/unfinished|ran out of passes/i.test(truncated)) throw new Error('the run was not described as unfinished');
    if (!/continue/i.test(truncated)) throw new Error('the only useful action was not offered');

    // The verification message must still win when the run really did finish its
    // attempts, or this trades one wrong summary for another.
    const genuinelyFailed = api.failureSummary({ ok: false }, [
      { type: 'error', text: 'verification failed (exit 1) after fix attempts' },
    ]);
    if (!/repair attempts/i.test(genuinelyFailed)) {
      throw new Error('a genuine post-repair verification failure lost its own message');
    }
  }

  // A run can emit more than one `final`. `finalReplyEvent` recognises only the
  // LAST one, so an earlier `final` fell through into the narrative -- where it
  // repeated, word for word, the `say` that had just streamed the same text. On a
  // real failed run the two blocks carried byte-identical 476-character labels and
  // the reader was shown the same paragraph twice, once headed UPDATE and once
  // THOMAS.
  //
  // `ok: false` on purpose: with a passing turn the final event becomes the reply,
  // so the marker would legitimately appear again outside the narrative and this
  // could not tell the bug from correct behaviour.
  async function proveNarrativeNeverRepeatsItself() {
    resetState();
    const repeated = 'REPEATED-NARRATIVE-BLOCK';
    const lastFinal = 'DISTINCT-LAST-FINAL';
    const html = api.turnHtml({
      role: 'agent',
      ok: false,
      reason: 'verification failed after fix attempts',
      transcript: [
        JSON.stringify({ fc: 'say', text: repeated }),
        JSON.stringify({ fc: 'final', text: repeated }),
        JSON.stringify({ fc: 'final', text: lastFinal }),
      ].join('\n'),
    });

    const repeats = html.split(repeated).length - 1;
    if (repeats !== 1) throw new Error(`narrative rendered the same text ${repeats} times, expected once`);

    // The distinct text of a different event must not be collapsed away with it --
    // deduping is meant to drop a verbatim repeat, not unrelated content.
    const kept = api.turnHtml({
      role: 'agent',
      ok: false,
      reason: 'verification failed after fix attempts',
      transcript: [
        JSON.stringify({ fc: 'say', text: 'FIRST-DISTINCT-STEP' }),
        JSON.stringify({ fc: 'say', text: 'SECOND-DISTINCT-STEP' }),
        JSON.stringify({ fc: 'final', text: lastFinal }),
      ].join('\n'),
    });
    if (!kept.includes('FIRST-DISTINCT-STEP') || !kept.includes('SECOND-DISTINCT-STEP')) {
      throw new Error('deduping swallowed distinct narrative steps');
    }
  }

  // "What should we make?" and its four starter cards stayed on screen for the
  // WHOLE of a new conversation's first run -- measured at 76 seconds, every
  // sample -- sitting above the live turn, while the question the user had just
  // asked was nowhere on screen. The empty state was chosen by "are there saved
  // turns", the live turn by "is a run going", and on a brand-new conversation
  // both were true at once.
  //
  // Both are now decided by the same hoisted flag, so they cannot disagree.
  async function proveTheEmptyStateStandsDownForALiveRun() {
    resetState();
    Object.assign(state, {
      activeId: 'c1',
      projectRoot: '/repo',
      conversation: { id: 'c1', turns: [] },
      running: true,
      runStatus: 'working',
      liveEvents: [{ type: 'planning', text: 'Thomas is preparing the Code run…' }],
    });
    snapshots.length = 0;
    api.render();
    const during = snapshots.at(-1) || '';
    if (during.includes('tc-code-empty')) throw new Error('the empty state renders during a live run');
    if (!during.includes('data-code-live-turn')) throw new Error('no live turn rendered while running');

    // The control: with nothing running and nothing saved, the empty state is
    // exactly what should be there. A fix that simply deleted it would pass the
    // assertion above and break the surface it is meant to introduce.
    resetState();
    Object.assign(state, {
      activeId: 'c1', projectRoot: '/repo', conversation: { id: 'c1', turns: [] },
      running: false, liveEvents: [],
    });
    snapshots.length = 0;
    api.render();
    const idle = snapshots.at(-1) || '';
    if (!idle.includes('tc-code-empty')) throw new Error('the empty state is gone when it should be shown');
    if (!idle.includes('tc-code-starter')) throw new Error('the starter cards are gone');
  }

  // An empty file list has three different causes and used to name only one:
  // whatever the reason, it read "Choose a project beside Tools to browse its
  // files." Measured on a new task: for 45 seconds -- the whole run -- the drawer
  // header said "Code task 2026-07-30 1018" while the list directly beneath it
  // told you to choose a project. The header had always used `state.projectRoot`
  // for exactly this decision; the list simply did not ask.
  async function proveTheFileListNamesTheRealReasonItIsEmpty() {
    resetState();
    state.conversation = {
      turns: [], continuation_history: { count: 1, runs: [
        { outcome: 'failed', reason: 'worker exited 2 <unsafe>', run_id: 'run-1', ts: '2026-09-23' },
      ] },
    };
    api.render();
    const history = snapshots[snapshots.length - 1] || '';
    if (!history.includes('Kept going on its own, 1 time') || !history.includes('worker exited 2 &lt;unsafe&gt;')) {
      throw new Error('counted runs and their escaped ending reasons are not visible');
    }
    if (history.includes('<unsafe>')) throw new Error('a run reason injected HTML');
    if (!history.includes('run-1')) throw new Error('the counted run cannot be identified');
    const renderWith = (patch) => {
      resetState();
      Object.assign(state, {
        activeId: 'c1', conversation: { id: 'c1', turns: [] }, drawerOpen: true, ...patch,
      });
      snapshots.length = 0;
      api.render();
      return snapshots.at(-1) || '';
    };

    const noProject = renderWith({ projectRoot: '', tree: [], treeLoaded: false });
    if (!noProject.includes('Choose a project beside Tools')) {
      throw new Error('with no project chosen the list must still say to choose one');
    }

    const loading = renderWith({ projectRoot: '/repo', tree: [], treeLoaded: false });
    if (loading.includes('Choose a project beside Tools')) {
      throw new Error('told the reader to choose a project that is already chosen');
    }
    if (!loading.includes('Loading files')) throw new Error('a pending fetch is not reported as loading');

    const empty = renderWith({ projectRoot: '/repo', tree: [], treeLoaded: true });
    if (empty.includes('Choose a project beside Tools')) {
      throw new Error('an empty folder was blamed on not choosing a project');
    }
    if (!empty.includes('no files yet')) throw new Error('an empty folder is not reported as empty');
    if (empty.includes('Loading files')) throw new Error('a finished fetch still claims to be loading');

    // The control: with entries, the list shows them and no message at all.
    const filled = renderWith({
      projectRoot: '/repo', treeLoaded: true,
      tree: [{ kind: 'file', name: 'tally.html', path: 'tally.html' }],
    });
    if (!filled.includes('tally.html')) throw new Error('tree entries stopped rendering');
    if (filled.includes('no files yet') || filled.includes('Choose a project beside Tools')) {
      throw new Error('an empty-list message rendered beside real entries');
    }
  }
  return { proveARepeatedStepStillLooksRepeated, proveTheActionSurvivesTheReason, proveTheRealReasonSurvivesTheExitWrapper, proveNarrativeNeverRepeatsItself, proveTheEmptyStateStandsDownForALiveRun, proveTheFileListNamesTheRealReasonItIsEmpty };
}
