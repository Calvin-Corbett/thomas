# Thomas Verification Standard

How to PROVE a Thomas change works. Set by Calvin, 2026-06-28: "A screenshot of a
game does not prove it works — it could be a PDF photo of a game screen. You have to
ask: did it actually hit the criteria?"

This is the bar for any agent (Claude, Codex) claiming a chat/UI/deliverable change is
done. A claim without proof at this bar does not count.

## The non-negotiables

1. **Real browser, real input.** Verify in an actual browser driven by Playwright
   against Thomas's real instance (`python run_thomas_main_8906.py`, port 8906).
   Restart the server and hard-reload after every edit. Type and click as a user would
   — never fabricate the trigger with synthetic `dispatchEvent`/`element.value=`. (You
   may inspect internal state with `evaluate`, but the *action under test* must be real
   input.) Never test in Calvin's own Chrome.

2. **A screenshot is not proof.** A screenshot shows a frame; it cannot show behavior.
   It is allowed only as a *supplement* to functional evidence, never as the evidence.

3. **State the criteria first, then verify each one.** Before testing, write down what
   "works" means for this task as checkable criteria. Then produce an observation for
   each. "It looks right" is not a criterion.

## Proof by deliverable type — what actually counts

- **A file (doc, list, csv, script, etc.)** — fetch the SERVED file
  (`GET /deliverable/<exec-id>/<file>` → HTTP 200) AND assert its CONTENT satisfies the
  request: a recipe has ingredients + steps; a CSV has the asked-for columns and N rows
  that parse; a script has valid syntax / runs. The worker's `proof.artifacts` must list
  it. "state == completed" alone is NOT proof — workers can report done with no file.

- **A game or interactive app** — load it in the browser, drive it with REAL key/mouse
  input, and assert the STATE CHANGES correctly OVER TIME: e.g. the snake moves (canvas
  pixels differ across ≥3 frames), it responds to steering (turns when you press a key),
  the score increments when the win-criterion is met, and there are **0 console errors**.
  "It rendered" is not "it works." Drive it; watch it react.

- **A visual / canvas** — assert the canvas iframe holds real rendered elements that
  match the request (not blank, not frozen, not the shell only), and that it reached a
  finished state. Confirm it did NOT open for non-visual content.

- **A chat reply** — assert it is model-authored (not a canned string) and HONEST: every
  claim must match reality. If it says "saved a file," the file exists; if it says
  "handed off," a real task was dispatched; if it can't act, it offers instead of faking.

- **Chat history / sidebar / persistence** — perform the action (send a chat), then
  assert the state is REAL: the chat appears in Recent with the correct title and a real
  date; reload the page and assert it persists; the backing store actually has it.

- **Dispatch / routing** — assert the right surface was chosen (document → worker,
  visual → canvas), that concurrent tasks stay separate (distinct exec-ids, no crossing),
  and that steer/cancel actually changes the worker state (verify the side effect, e.g.
  `is_cancel_requested`, not just the chat wording).

## Distinguishing real from artifact

When a result looks wrong, find a probe that ONLY the real cause can produce. A task
state of "failed" can mean a cancel OR a worker self-failure — `is_cancel_requested`
tells them apart. An "empty reply" can be the model OR a malformed request — check the
raw stream. Always confirm the unambiguous side effect, not a proxy for it.

## The closing question

Before saying "done," answer in one line per criterion: *how did I prove this — what
did I observe that a fake could not have produced?* If you can't answer that, it isn't
verified yet.
