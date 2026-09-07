# ALIVENESS — what would make Thomas act without being asked

**Status:** partly built. Items 1, 2 and 4 of §8 are in `thomas/core/aliveness*.py`;
the mouth is still not connected to anything that reaches you. Revised twice —
see *Amendments*.
**Field check:** `ALIVENESS_RESEARCH_LANDSCAPE_2026-08-27.md` — the design
holds; §5 of that doc changes how the wake decision should be built.

**Amendments landed in this revision:**
1. §5 replaced. The speak gate is no longer a global budget with a learned
   threshold; it is **per-topic permission that starts at zero** — your call,
   and a better one. The old approach is kept in §5 as the thing it replaced,
   because *why* it was wrong is the useful part.
2. §6 is new: **how this gets measured**, and why proactive features die of a
   measurement bug rather than a UX one. Two of its rules are architectural.
3. The Coherence drive is renamed **Freshness** (§4) — "coherence" is taken.
4. Build order (§8) gains the permission store and the judge.

**Learned while building (§5, §8):**
- **The contract needs a seed grant or it deadlocks.** Permission starting at
  zero for *everything* includes the topic Thomas would use to ask for
  permission, or to tell you a grant has decayed — so the contract could never
  grow or be corrected. `aliveness.system` is seeded at brief-always: the
  weakest thing that resolves it, pull-only, revocable like any other grant.
- **The drives hold back; they do not build up.** Asking upward from the floor
  left every ceiling above brief unreachable — a notify grant produced brief
  entries forever and the escalation levels were decoration. A granted topic now
  asks for its ceiling, and calm drives settle it for the quieter end.
- **Only a push may spend the push budget.** Held and brief-level messages
  feeding the budget drove it to its floor inside a simulated fortnight, which
  would have silently disabled every future interrupt.
**Date:** 2026-08-27
**Origin:** your note — *"Currently ai assistants have a heart beat thing. It's a gimmick. I say we copy the design of a human. We train Thomas to be alive. To act with out prompting."*

---

## 0. The finding that starts this

Thomas already has the loop you're describing, and it is switched off.

`thomas/core/initiative.py` is a 274-line Autonomous Initiative Engine. It polls
every 60 seconds, and when there has been no user message for 30 minutes and open
goals exist, it picks the highest-ROI goal and executes it without being asked.
That is the exact behaviour under discussion, already written.

In production it never runs. `EngineManager._start_initiative()` refuses to start
the daemon when no `executor_fn` is supplied, and the two production callers —
`app_core.start_all()` and `cli/agents_runtime.py` — both call `start_all()` with
no executor. The engine reports `running: False, error: "disabled: no executor"`.

Credit where it's due: that refusal is deliberate and the comment says so — it
declines to report `running: True` for a loop that can't act, because that would
be a false positive. So the code is honest. But the honest state is: **Thomas's
proactivity today is a clock wired to nothing.**

Which is your point about heartbeats, and it turns out to be literally true
inside this repo rather than just true of the industry.

---

## 1. Why a heartbeat is a gimmick

A heartbeat is a **clock**. Clocks answer *when*. Aliveness is a question about
*why*.

Every tick-driven design has exactly two failure modes and no third:

- **Tick with no body** → silence. The loop runs, nothing happens, the feature is
  a status light. (Thomas today.)
- **Tick with a body but no threshold** → noise. It fires because the timer said
  so, produces "just checking in!", and gets muted inside a week. (Every proactive
  assistant that has ever shipped.)

What is missing in both is a **reason to act that exists independently of the
clock**. Get that right and the tick rate stops mattering. Get it wrong and no
tick rate saves you.

---

## 2. What the Minecraft agent actually has that Thomas doesn't

The bots in that family — Voyager (MineDojo/NVIDIA), and the Mineflayer-based
ones like Mindcraft — feel alive, and it's worth being precise about why, because
the obvious answer is wrong.

It is not the loop. It is the **world**.

Minecraft runs whether the bot acts or not. Hunger falls. Night comes. Mobs
spawn. The furnace finishes. Rain starts. The world produces a continuous stream
of events the agent did not cause, and the agent only has to stay responsive to
them. Aliveness is emergent from *being embodied in something that moves on its
own*.

Thomas's world is a chat box. It is perfectly, absolutely still until you type
into it. There is no hunger. Nothing spawns. No amount of looping fixes that,
because there is nothing for the loop to be about.

**So the transfer is not "add a loop." It's "give Thomas a world with its own
clock."** He has one available and doesn't watch it:

| Thomas's world | Changes without him |
|---|---|
| the repo | commits land, branches go stale, dev moves |
| CI / gates | runs finish, go red |
| the workboard | tasks complete, fail, stall on a claim |
| your calendar & inbox | meetings, deadlines, threads |
| the machine | disk, long-running processes, the server up or down |
| his own goals | things you asked for that aren't done |
| his own promises | things he said he'd do |

Once that stream exists, a loop has something to be *about*, and everything else
in this document is plumbing.

Two other pieces of Voyager are worth naming while we're here:

- **The automatic curriculum** — it always has a next goal, which *it* chose,
  scaled to what it can currently do. Thomas has no such mechanism. Every goal
  he has ever had came from you.
- **The skill library** — successful procedures get stored as reusable code, so
  it gets better at the world it lives in. Thomas has this half-built
  (`tool_factory.py`), and it's already logged as a gap in the research queue
  (`SI-2026-06-28-013`, keyed to Voyager directly).

---

## 3. The steady state: right instinct, wrong rhythm

You said gamma waves. The instinct — *there has to be something always running
underneath* — is the correct one. The specific rhythm isn't the one you want, and
the reason why is useful.

Gamma (~30–100 Hz) is a **binding** rhythm. It's how regions firing at the same
time cohere into a single percept — how the colour, edges, and motion of one
object become one object. It is not a metronome that drives behaviour. Nothing in
a brain acts once per gamma cycle; you'd act 40 times a second.

What actually produces unprompted human behaviour is two other things:

**Homeostatic drives.** You don't eat because a timer fired. You eat because a
level fell below a setpoint and the error signal grew until it outcompeted
everything else. The clock is incidental. The *error* is causal. This is the
mechanism you actually want, and it's the one that makes the tick rate stop
mattering.

**The default mode network.** What runs when there is no task. Rest isn't idle —
it's consolidation, replay, and loose-ends chatter, and it's where "oh, I should
tell you about that thing" comes from three hours later. An assistant with no
resting state can only ever react.

So keep the steady state. Make it a **hierarchy of rates**, where only the
slowest one costs money:

| Band | Period | Cost | Job | May speak? |
|---|---|---|---|---|
| **Tick** | 1–5 s | free — pure Python, no model | sample the world, update drive levels | never |
| **Cycle** | 1–5 min | free | check thresholds; decide whether to wake the mind | never |
| **Deliberate** | only on a threshold crossing | one model call | choose one thing and do it | only through the gate |
| **Rest** | when idle and quiet | cheap batch | consolidate memory, replay open threads, generate next goals | never directly |

This is the steady state: always running, and 99% of it never calls a model.
That is not a cost optimisation bolted on afterwards — it's the same reason
biology does it. Most of being alive is cheap. A loop that thinks with an LLM
every 30 seconds is both unaffordable and, notably, *less* like a human than this.

---

## 4. Three drives

Each is a level with a setpoint, something that raises it, and something that
discharges it. This replaces the ROI-keyword scorer in `initiative.py`, which
scores goals by grepping for the word "crash".

**Freshness** — *does my picture of your world still match your world?*
(Renamed from Coherence: Sophia already uses "coherence" for plan-versus-execution
consistency, which is a different thing.)
Rises with elapsed time and with unobserved change. Discharged by **looking**.
This should run hottest, and it is silent by construction. An assistant that has
actually read the room before you say anything feels alive in a way that no
message ever does. Most of the value in this entire document is in this drive.

**Debt** — *what did I say I'd do that isn't done?*
Rises when a goal is opened, when a promise is made in conversation, when a task
fails quietly, when a branch goes stale. Discharged by **finishing**. This is the
job `initiative.py` already has; it needs a real ledger underneath it instead of
keyword scoring.

**Contact** — *how long has it been?*
Rises with silence. Discharged by **speaking**. It must be the weakest drive and
the most heavily gated, and it gets one hard rule: **contact alone is never
sufficient to speak.** A message whose only justification is "it's been a while"
is precisely the thing that makes a product feel needy. Contact may only lower
the bar for a message that already has content of its own.

---

## 5. The hard part is not acting. It's shutting up.

Acting unprompted is easy, and should be free, constant, and silent. **Speaking**
unprompted is the entire product risk, and it's where these things die.

The first version of this section proposed a global message budget with a
threshold that learns from your feedback. That was wrong, and the reason is worth
keeping on the record: **a learned global threshold has to be annoying in order to
learn.** It needs signal, signal comes from sending messages, so it experiments on
you during precisely the window when your patience is being set. Cold start isn't
an edge case there — it's the failure mode.

### Permission is per topic, and starts at zero

Thomas is silent about everything by default and earns permission to interrupt
**one topic at a time**. He may be as annoying as you've said he can be about the
things you've said he can be annoying about, and is mute everywhere else.

This is how it works between people. Nobody has a general interrupt tolerance;
they have standing instructions with specific people about specific things. *Wake
me if the site is down. Nothing else.*

Two properties a global budget cannot buy:

- **No experimentation.** Thomas never sends a message to find out whether you
  wanted it. He speaks where you have already said yes. Learning happens *inside*
  a granted topic — how hard to push, when to batch — never on the question of
  whether to speak at all.
- **It is inspectable.** "What are you allowed to bug me about?" is a list you can
  read and edit, not a threshold you can only correct by being annoyed first.

### Escalation ceiling, per topic

Permission is not binary. Each topic carries a ceiling:

| Level | Behaviour |
|---|---|
| 0 | Silent. Never surfaced. |
| 1 | Appears in the brief if there's room. |
| 2 | Always in the brief. |
| 3 | Notify when it happens. |
| 4 | Notify, and repeat until acknowledged. Actual nagging. |
| 5 | Interrupt through quiet hours and deep work. |

Levels 4 and 5 are the point. A global budget can never safely offer them, because
it has to be conservative about everything at once. Per topic, level 5 on "prod is
down" is obviously correct and costs nothing anywhere else. The ceiling goes **up**
where it should and to **zero** everywhere else, instead of a mediocre middle
applied uniformly.

### How permission accrues

1. **Explicit grant.** You say "always tell me when CI goes red on dev." One
   sentence in chat, full grant. This is the primary path and it has to stay this
   cheap or it won't get used.
2. **Earned, then confirmed.** You asked about the deploy queue four times this
   week. That's evidence, and it raises the ceiling on *that topic only* — but it
   **proposes rather than assumes**: *"want me to just tell you when this
   changes?"* One question, then it's explicit. Earned permission that skips the
   question is how the contract quietly stops being inspectable.
3. **Inherited, weakly.** A novel failure inside a subsystem you already care
   about qualifies, at reduced volume. Without this you'd have to enumerate every
   topic in advance, and you won't.

### Decay

A grant made for a project you finished is a liability. Topics you stop acting on
fall back toward silent on their own, and **the fallback is announced, not
silent**: "I've stopped flagging X, nothing's touched it in a month" is itself a
cheap and useful brief-level line. Permission that only ever accumulates
re-creates the global-budget problem by a slower route.

### The four things this does not solve

1. **Unknown unknowns.** The most valuable unprompted message is about something
   you didn't know to ask for, and a strict allowlist structurally cannot deliver
   it. Escape hatch: **one discovery item per brief, pull-only, never a push.**
   Cheap because it cannot interrupt, it is the only place experimentation is
   allowed, and its hit rate is the evidence for widening or closing it.
2. **Topic identity.** "CI failures", "build is broken", and "tests red on dev"
   are one topic in your head and three strings in a database. Matched too
   narrowly, permission fragments — Thomas ends up holding permission for exactly
   the thing that already happened and nothing adjacent. This is where the
   per-entity routing score from the Microsoft/Purdue wake model earns its place:
   the cheap tier is not only a trigger, it decides **which permission bucket** an
   event falls into.
3. **Grant inflation.** In the moment you will say yes a lot. Fourteen
   individually reasonable grants are collectively intolerable, and you've
   re-derived the global budget through the back door. So the global ceiling stays
   — **as a backstop that should almost never bind.** When it binds, that's the
   signal to prune, and Thomas says so rather than silently dropping messages.
4. **Usefulness.** All of this makes Thomas safe to leave switched on. None of it
   makes what he says worth reading. That's the judge — §6.

### Hard mutes, above all of it

Regardless of permission or ceiling, below level 5: never mid-conversation, never
twice about the same thing, never to report that nothing happened.

---

## 6. How this gets measured — the retention trap

Proactive features die of a measurement bug, not a UX one. Two of the fixes below
are architectural rather than dashboard work, which is why they're here.

**The trap.** The launch metric and the retention metric are driven by the same
lever in opposite directions:

- Messages sent and opened go **up** when you send more, so week one reads as a
  win — and the win argues for shipping more of it.
- Attention is a fixed pool (~3–5 notifications a day, shared with every other
  app competing for it). You aren't spending your budget, you're spending yours.
- Trust is asymmetric. One bad message costs several good ones, because the damage
  isn't annoyance, it's **recalibration** — you update your prior on whether this
  thing is worth looking at, and after that the good messages stop getting opened
  too. You don't lose the bad messages, you lose the channel.
- The interruption cost (~23 minutes of recovery, 30–60 for architecture work)
  lands on you, invisibly, and never reaches Thomas's telemetry. The
  instrumentation can only see the benefit side of the ledger.
- Engagement moves in days, retention in weeks. The number stays green exactly
  long enough for you to build on top of it.

The end state isn't dramatic churn, it's a mute. For a single-user assistant a
mute is worse than an uninstall, because the eroded trust contaminates the
prompted path that already worked. And there is no cohort to detect it in — you'd
simply stop reading, and nothing would report it.

**The rules, in leverage order:**

1. **"Ignored" scores negative, never zero.** *This is the whole thing.* If
   silence is free, the expected value of sending is always positive and the
   system will reason its way into more messages forever. Silence has to be the
   profitable default in the arithmetic, not just in the prose.
2. **Pull is the default surface; push is the exception.** A page you choose to
   open has no interruption cost and spends no budget. An interrupt does. Anything
   that can be a brief entry should be one, and the budget then applies only to
   genuine pushes. This is the economics Pulse and Gemini landed on, not a style
   preference.
3. **Success is an attributable downstream action** — you replied, acted, or
   reprioritised inside a window. Never "sent", never "opened". Open rate is
   contaminated; people open things out of anxiety.
4. **The budget is closed-loop.** Messages that produced action refill it; ignored
   ones drain it faster; empty means auto-mute for a period. The system throttles
   itself before you have to.
5. **The leading indicator is action rate over the last N unprompted messages.**
   It decays weeks before you'd consciously notice you'd stopped reading. It's the
   one number worth a dashboard.
6. **Keep a control, even at N=1.** Some days the loop stays mute regardless.
   Without it you cannot distinguish "Thomas is helping" from "Thomas is present."

*Provenance note: the specific "launch metric inverts the retention metric within
weeks" framing comes from a source blocked by this session's egress proxy. The
interruption-cost and CHI figures underneath the mechanism are from accessible
sources; treat that one phrasing as directional.*

---

## 7. This inherits NIGHTSHIFT's safety spine, without exception

An always-on loop that acts, speaks, and improves itself is the same machine
NIGHTSHIFT already governs, so it gets the same three laws:

1. It never grades its own homework.
2. It never touches the machinery that judges it.
3. No claim without an artifact.

Plus one specific to this: **unprompted action is capped at the current autonomy
level** (`thomas/core/autonomy.py`) exactly as if you had asked for it. The loop
gets no privileges a prompt wouldn't get. Nothing lands without your tap.

---

## 8. What's actually missing, in build order

1. **A world model that ticks** — the sensor layer from §2. Does not exist.
   Everything else depends on it.
2. **An executor for `initiative.py`** — one function. This is the single
   smallest change with real effect: it's why the engine is dark today.
3. **Promise tracking** — Thomas doesn't record "I said I'd do X," so Debt can't
   be computed. Does not exist.
4. **The permission store** — topics, grants, ceilings, evidence, decay (§5).
   **Built** (`aliveness_permissions.py`, `aliveness_gate.py`): explicit grants,
   weak inheritance, proposals that ask rather than assume, decay with an
   announced fallback, a closed-loop push budget, and the hard mutes.
5. **The judge** — scores whether a message was wanted, trained on the mute-mode
   log (§6). Does not exist. Judging is the tractable half of this problem.
6. **A rest cycle** — consolidation and self-generated goals, i.e. Voyager's
   automatic curriculum. Does not exist.

**Known shape of the earned path:** a rare, critical topic cannot earn its own
permission — three fires in a fortnight is below any honest evidence bar, so
production-down has to be granted explicitly. That is the right trade rather than
a gap to close: interrupt rights should not be inferred from three samples.

**Recommended first slice: 1 + 2, silent.** Let it observe and act for two weeks
with the mouth disconnected, keeping a log of every message it *would* have sent —
recorded in a shape a judge can be trained on (§6), with an outcome field that
defaults to a negative.

Then read the log. Under the original design that log was threshold-tuning data.
Under §5 it is better than that: **it's the draft grant list.** You read two weeks
of "here's what I would have said", and the ones you'd have wanted become the
first explicit permissions. That is a far better bootstrap than tuning a number,
and it means the first message Thomas ever sends unprompted is one you already
approved the category of. **Ship the mouth last.**

---

## 9. What "alive" should feel like when it works

Not a thing that pings you.

It's that when you come back, Thomas has already read what happened while you
were gone, the thing you half-asked-for on Tuesday is done, and he says nothing
about any of it unless it matters.

Aliveness is measured in what it noticed, not what it said.

---

## Sources

- Voyager: <https://github.com/MineDojo/Voyager> · <https://voyager.minedojo.org/>
- Mindcraft (Mineflayer + LLM bots): <https://github.com/kolbytn/mindcraft>
- Existing Thomas surfaces: `thomas/core/initiative.py`,
  `thomas/core/engine_manager.py`, `thomas/core/autonomy.py`,
  `thomas/agent/checkin_policy.py`, `plans/thomas/evolve_auto/NIGHTSHIFT_DESIGN.md`,
  `plans/thomas/self_improvement/SELF_IMPROVEMENT_RESEARCH_QUEUE.md` (SI-2026-06-28-013)
