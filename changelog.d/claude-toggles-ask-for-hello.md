### Security

- **Raising Thomas's own limits now asks at Windows Hello, and the server enforces
  it.** You said: "agents cant change stuff that important if they try its
  password protected so there is no worry." That held for Thomas's code,
  protected files and safety settings. It did not hold for the chat dials.
  Autonomy, file access and internet reach were guarded by a browser OK box
  that anything driving the page can click. Worse, the server honoured whatever
  level a request carried, so an agent could run itself at "Anywhere on my PC"
  without the page being involved at all.
  Now Full autonomy, Autopilot, "Anywhere on my PC" and Open internet each need
  your approval at a real Windows Hello or password prompt before the server
  honours them. Until then the request still runs, one level lower, rather than
  being refused.
  - **Who can raise a level.** Anything, an agent included, can bring up the
    prompt. Only you can answer it.
  - **Every place a level comes from is covered.** Chat, the older chat route,
    Build, a new Build conversation's saved settings, and Work jobs' stored
    settings all go through the check. So does a default autonomy saved in
    preferences, and so do per-group guardrail modes, which would otherwise
    override the preset outright.
  - **Saving a looser guardrail policy asks too.** A saved policy with any
    permissive group needs the same prompt as Open.
  - **Approvals are never reused.** Every approval is a fresh prompt. The shared
    Windows gate's five-minute session is not reused, so an earlier tap for
    something else cannot carry over.
  - **Declining protects you from repeat prompts.** A declined dial stays quiet
    for 30 seconds, and only one prompt is ever open at a time, so nothing can
    keep asking until you give in.
  - **Restarts reset approvals.** Approvals live only in the running server, so
    a restart forgets them. After one, the menu shows the level the server will
    actually use rather than a stale "Autopilot".
- **Build accepts Autopilot.** Build's settings allowed autonomy 1 through 4
  while the Chat menu offered 5, so with the dial on Autopilot every Build run
  stopped at a settings error.
- **Thomas can read his own issue list under every setting.** `self.issues`
  only reads the issue ledger, but it was missing from the tool catalog. So it
  was denied whenever any capability was switched off, which hid what was
  broken from the tool meant to report it.
