# The December 1 convergence: three questions, one page

Verified against `docs/ops/accepted_risks.json` and
`plans/thomas/tasks/PRAXIS-PHASE2-BATCH1/status.md` (both batch sections) on
2026-08-26. A fresh `incident_surfacing.py` run today shows `REOPEN DUE: 0` —
this document is about what happens when that stops being true, not a
problem that exists yet.

## The situation

Three "accepted risk" records sit in `docs/ops/accepted_risks.json`. Each one
is a dated, owned note that says "we know about this, we're choosing not to
fix it right now, and that choice expires on a specific day." All three of
them expire on the same day: **2026-11-30**.

- One record covers **9 incidents** — old task records whose work had
  already landed, closed in a batch, with no automated way yet to prove that
  landed-and-closed link on its own.
- One record covers **1 incident** — a fix that is genuinely done and
  permanently tested, but no automated gate is watching that particular
  class of fix, so there's no clean way to say "this is closed" other than
  this dated note.
- One record covers **1 incident** — a real, still-open bug (a file that can
  get written twice in the same instant under rare timing) whose actual fix
  is ready to apply but sits behind a file that requires your sign-off to
  touch.

That's **11 incidents** riding on the same expiry date. If nothing changes
before then, here is exactly what happens on 2026-12-01: every session-start
check (`incident_surfacing.py`) will print a `REOPEN DUE` line for each of
those 11, instead of the single quiet `REOPEN DUE: 0` it prints today. Two of
those lines will be long — one over a full screen line's width — because the
system quotes the record's full name so you can always see exactly which
promise expired and why.

**To be direct about what that alarm does and doesn't do:** nothing breaks,
no code changes, no work is lost, and nothing gets deleted or reverted nor
does any file flip automatically. It is a printed note at the top of a
session, telling whoever is working that day "these 11 things were only
looked away from for 90-some days, and that window is now up — go look
again." That's the system working as designed, not a malfunction. It is,
however, 11 lines of noise every session until someone reads this note and
makes a call — annoying, not dangerous.

Underneath the noise are exactly two real, separate questions. Answering
them now (or deciding not to) is what this document is for.

---

## Question 1 — the closure-vocabulary gap

*(covers 10 of the 11 incidents — the 9-record batch and the fixed-and-tested one)*

The system currently recognizes exactly three ways an incident can be
declared closed: a gate that watches for it forever, a permanent removal
record, or a dated risk acceptance like the ones above. Two real situations
kept not fitting any of the first two:

- Work that landed in a real commit, but no automated gate exists to watch
  that class of change going forward.
- A fix that is code plus a permanent, passing test — but no automated gate
  watches that test either.

Both times, the only honest option available was "write a dated risk note
and let it expire" — which is exactly what produced this convergence. There
are three ways to actually close this gap:

**(a) Add a new closure form for "fixed and tested."** A closure could point
at a specific test file instead of a gate — it resolves as long as that
named test exists and passes in CI.
- *In favor:* it's an honest match for the fixed-and-tested case — that
  incident really is just code plus a test, nothing more is needed to
  describe it accurately.
- *Against:* a test is a weaker promise than a gate. A gate is built to
  never silently stop enforcing; a plain test can be deleted, skipped, or
  quietly marked "expected to fail" and nobody would notice. To make this
  safe, the same watching that already exists for gates (something proves
  the gate still fails on a real violation) would need to be built for
  tests too — otherwise this closure form becomes the easiest way to make
  a fix disappear from view forever.

**(b) Add nothing. Let the risk records renew.** When a risk record expires,
someone reviews it again and writes a fresh one with a new expiry.
- *In favor:* the vocabulary stays exactly as strict as it is today — no
  new door is opened that something could later slip through.
- *Against:* a risk that gets renewed indefinitely stops meaning "we're
  choosing not to fix this today" and starts meaning "we've given up on
  ever deciding." The fix for that is cheap: print how many times a record
  has already been renewed, right where the surfacing note appears, so a
  record on its third or fourth renewal reads as a habit, not a decision.

**(c) Build a real "landed and provably closed" checker.** A tool or gate
that looks at an incident's stated scope, checks whether it actually landed
in the repository's history, and closes the record itself when it can prove
it — no human note needed at all.
- *In favor:* this is the only option that removes the underlying gap
  entirely rather than working around it. It is, in fact, exactly the
  missing capability the 9-record risk names in its own reason field.
- *Against:* by a wide margin, this is the biggest thing to build of the
  three. It has to correctly answer "what does landed even mean" for many
  different kinds of incidents, and get it right in both directions — never
  closing something that didn't really land, and never missing something
  that did.

**Recommendation: (a) for the fixed-and-tested case, (b)-with-a-renewal-counter
for the landed-scope case, and (c) deferred until the landed-scope gap shows
up often enough to earn the bigger build.**

Reasoning: the fixed-and-tested case (1 incident so far) is a narrow,
well-understood shape — a test that already exists and already passes —
and (a) can be built as a direct extension of the exact same
"watch-the-watcher" pattern that already keeps gates honest, so the new door
doesn't have to be a weaker one. The landed-scope case (9 incidents, all
from one historical cleanup) hasn't recurred since; spending the largest
build in this list on a shape that showed up once is premature. A cheap,
visible renewal counter keeps option (b) from becoming the silent
rubber-stamp it would otherwise risk being, and buys the time to see whether
(c) is actually worth building later.

**This is a vocabulary change to how the system decides what counts as
"closed," not a code fix.** It is written up here for your yes or no. Nothing
in this recommendation has been built or applied.

---

## Question 2 — the file-lock

*(covers 1 of the 11 incidents)*

The real, still-open bug behind the third risk record: a file that records
failures can be written by two processes at almost the same instant,
producing duplicate entries (this is exactly what happened — 40 duplicate
records, now understood and explained). The actual fix is small and
well-understood: make that write wait its turn instead of racing.

The only reason it isn't already fixed is that the file it lives in requires
your sign-off before it can be touched at all — a deliberate protection, not
an obstacle. The path for that already exists in this repository: a
reviewed, ready-to-apply change gets written up and checked in a document,
verified twice to actually apply cleanly and pass its own test, and then you
sign it with one Windows Hello tap and it lands. There's a real example of
exactly this pattern already sitting in the repo
(`plans/thomas/tasks/PRAXIS-REF-EXACTNESS-BREAKGLASS/batch.md`), prepared and
waiting the same way this fix would be.

**Recommendation: prepare this the same way — write the reviewed diff, verify
it applies and passes cleanly, and leave it ready for your tap.**

This one barely counts as a decision. It's a mechanical, well-scoped fix
with a proven landing path already in use elsewhere in the repo; the only
open question is whether you want it prepared now or later.

---

## The timeline

For 2026-12-01 to arrive quiet instead of with 11 lines of noise:

- **Decisions on both questions above by roughly mid-November** — the
  vocabulary choice in Question 1 needs to be made, and if Question 2's
  fix is going to be tapped in, it needs your sign-off.
- **About two weeks of implementation runway after that** — building
  whichever combination of (a)/(b)/(c) you choose, and applying the
  file-lock tap, comfortably before the 30th.
- **Or: explicitly choose to let the alarm fire and handle it that day.**
  This is a legitimate option, not a failure — the 11 lines are noise, not
  damage, and reviewing all three records fresh on 2026-12-01 costs you
  one session's attention instead of a decision made weeks early. If you
  pick this, no further action is needed before then.

---

## Three lines you can answer in one message each

1. **Question 1 (vocabulary):** approve "(a) + (b)-with-counter, defer (c)"
   — or name a different combination, or say "let it ride to Dec 1."
2. **Question 2 (file-lock):** prepare the reviewed-diff tap now — yes or no.
3. **Timeline:** commit to a decision date in mid-November — or explicitly
   accept the Dec 1 alarm and revisit it then.
