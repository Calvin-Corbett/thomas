# ALIVENESS — what everyone else is actually doing (Aug 2026)

**Companion to** `ALIVENESS_DESIGN_2026-08-27.md`.
**Purpose:** you asked to check the field before building. This is the check.
**Verdict up front:** the design holds, one part of it is now empirically proven
rather than argued by analogy, and three parts should change.

---

## 1. The idea has a name and a market

What we've been calling "alive" the field calls **ambient agents**, or the
**post-prompting era**: continuous rather than episodic, event-driven rather than
prompt-driven, responding to *context changes* instead of to a person typing.
Microsoft is publishing the pattern as **change-driven architecture**.

It is not theoretical and not cheap to enter. Healthcare is furthest along —
Commure raised $200M (June 2025) and Nabla $70M in the same month, specifically
to push ambient documentation into *proactive agents that act inside the EHR*.
The arc reactive → proactive → autonomous is the defining enterprise AI story of
2026.

So: the instinct is not early and not late. It is exactly on the current wave.

---

## 2. The "rest cycle" already shipped as a product

The design doc proposed a default-mode/rest cycle: consolidate while idle, surface
in the morning. That is **ChatGPT Pulse**, shipped September 2025. Each night it
synthesises memory, chat history, and connected apps (calendar) and delivers a
personalised brief the next day. Google is shipping the same shape — Gemini
**Proactive Assistance** (on-screen content, notifications, Gmail, Calendar,
processed on-device) plus **Gemini Spark**, a 24/7 agent across Workspace.

The form factor both of them converged on matters more than the fact they shipped:

> **Overnight batch → one surface in the morning.** Not pings through the day.

That is a real design signal and we should copy it rather than re-derive it.

---

## 3. Background coding agents are mainstream — and none of them are alive

The category is settled and crowded: Devin (late 2024), Codex Cloud and Cursor
Background Agents (2025), Claude Code Remote Tasks (March 2026). The lifecycle is
uniform: **ticket → cloud sandbox → autonomous edit → PR → human review.**

Two numbers worth holding onto:

- Even the best resolve only **30–50% of well-defined tickets** end-to-end
  without human intervention.
- **All of them still start from a human ticket.**

That second one is the finding. Nobody in this category has shipped an agent that
decides *on its own* what to work on. The whole industry is doing autonomy of
*execution*; nobody is doing autonomy of *selection*. That is precisely the gap
your idea walks into — and Thomas already has most of the machinery for it
(NIGHTSHIFT, the workboard, gates, the tap).

It is also the reason to be careful. There is no incumbent showing us the safe
version, because there is no incumbent.

---

## 4. Academia converged on this in the last ten months — on the same three problems

There is now a benchmark stack where eighteen months ago there was nothing:

| Work | What it establishes |
|---|---|
| **Proactive Agent / ProactiveBench** (2410.12361, thunlp) | 6,790 real events, human-labelled accept/reject; trained a reward model to judge proactivity |
| **ProactBench** (2605.09228), **ProAgentBench** (2602.04482) | precision = interruption cost, recall = need coverage; framed explicitly as alert fatigue |
| **Ask Now, Use Later** (2605.28108) | the "proactivity gap": agents fail to acquire information *before* it's needed |
| **Agentic Coding Needs Proactivity, Not Just Autonomy** (2605.06717) | coding-specific; treats **silence as a first-class action**; metrics for insight quality, context grounding, and learning from developer feedback |
| **Sophia** (2512.18202) | persistent agent, "System 3", narrative identity, self-generated goals, intrinsic drives |
| **ProAct** (2605.25971) | idle-time compute: predict upcoming needs while idle, prefetch the evidence |
| **Letta sleep-time compute** | background agent reorganises shared memory while the primary is idle |

Three of these deserve their numbers quoted, because they change decisions.

### 4a. We can judge proactivity far better than we can generate it

ProactiveBench's best fine-tuned model reaches **F1 66.5%** at deciding when to
offer help. The **reward model that judges whether an interruption was wanted
reaches 0.918 F1.**

That gap is the most useful fact in this entire document. It says: *building the
judge is a solved-ish problem; building the speaker is not.* Which is a direct
argument for the plan already proposed — run mute, log what it would have said —
except stronger than proposed. See §6.

### 4b. Sophia is your idea, published, with results

Sophia is a persistent-agent framework with a meta-cognitive layer over the usual
fast/slow stack, narrative identity, self-generated goals, and an intrinsic
motivation module combining **curiosity, mastery, and coherence** — explicitly to
stop the agent stalling during user inactivity. Reported: **80% fewer reasoning
steps on recurring operations**, and hard-task success from **20% → 60%** via
autonomous self-improvement.

Convergent evidence that drives-instead-of-a-clock is the right frame. Note the
naming collision: their *coherence* means plan-versus-execution consistency. Ours
meant world-model freshness. Ours should be renamed (see §6).

### 4c. Idle time is being treated as a resource, not a gap

ProAct predicts likely next needs during idle and resolves the knowledge gaps in
advance (ProActEval: 200 scenarios, 40 domains). Letta's sleep-time compute has
a background agent rewriting shared memory blocks while the primary sleeps —
**~5× less test-time compute for equal accuracy, 2.5× lower cost per query**
when amortised across related queries.

Idle-time work is not just about feeling alive. It is *cheaper* than doing the
same work at question time.

---

## 5. The one finding that changes the architecture

**"Do Proactive Agents Really Need an LLM to Decide When to Wake and What to
Anchor?"** — Microsoft Research + Purdue (2605.30152).

The default proactive agent calls an LLM **on every event** just to decide yes or
no. Their argument: the world's structure is a graph, rendering it as text and
asking an LLM to recover that structure is a round-trip you never had to take.
They replace it with a small temporal-graph-learning model — one forward pass
gives a per-event trigger probability and a per-entity routing score — and the
LLM is only invoked *after* the trigger fires, to turn a structured handoff into
a sentence.

Result: **+16.7 mean F1 across 14 backbones (up to +46.0)**, and the **most
stable deployed threshold** of any trigger architecture tested.

This matters because the design doc argued the cheap-tick / expensive-deliberation
hierarchy from biological analogy. It turns out not to need the analogy: the cheap
tier is *more accurate and more stable*, not merely cheaper. And the wake decision
should be a small **learned** model over an event stream, not the hand-tuned
thresholds the design doc sketched.

---

## 6. What changes in the plan

> **Landed.** All four amendments below are now folded into
> `ALIVENESS_DESIGN_2026-08-27.md`, along with one change that came out of the
> conversation rather than the literature and supersedes part of Change 1:
> **the speak gate is per-topic permission starting at zero, not a global budget
> with a learned threshold.** A learned global threshold has to be annoying in
> order to learn — it needs signal, and signal means sending messages. Per-topic
> permission never experiments on you. The global budget survives only as a
> backstop that should almost never bind. See design §5, and §6 there for the
> measurement rules that stop the retention trap in §7 below.

**Validated, keep as-is:** tiered rates; drives rather than a clock; the speak
gate; run mute first; ship the mouth last.

**Change 1 — the wake decision is a learned cheap model, not thresholds.**
Per §5. Hand-tuned thresholds are what everyone else is moving *away* from, and
the learned version is better on both axes. Thresholds are fine for the first
version; the design should expect to replace them.

**Change 2 — build the judge, not just the log.**
Per §4a. The mute-mode log stops being only a tuning aid and becomes **training
data for a reward model** that scores "would you have wanted this?" Judging is
the tractable half. This should be an explicit deliverable, not a side effect.

**Change 3 — the default channel is a morning brief, not a ping.**
Per §2 and §7. Pings are the exception reserved for genuinely urgent things;
the brief is where unprompted output normally lands.

**Change 4 — rename the Coherence drive.**
Collides with Sophia's established meaning. **Freshness** (or Attunement) for
"does my picture of your world still match your world."

**Unchanged and now better supported:** silence as a first-class action — the
coding-proactivity paper (2605.06717) independently arrived at exactly that,
along with interruption cost and learning from feedback as the other two pillars.

---

## 7. The attention ceiling — the real constraint, now quantified

This is the part that kills products, and the numbers are unkind:

- **3–5 notifications per user per day** is the hard ceiling. Teams that don't
  budget attention ship features whose launch metric inverts their retention
  metric within weeks.
- Recovery from a single interruption averages **~23 minutes**. Interruptions of
  **5 seconds triple error rates** in complex cognitive work.
- For developers specifically: **10–15 min** recovery for a bug fix, **30–60 min**
  for architecture or security work.
- CHI 2025, *Need Help? Designing Proactive AI Assistants for Programming*: the
  persistent-suggestion condition was **not preferred** — participants called it
  "distracting" and "annoying".

Implication for Thomas, stated plainly: the speak budget is **3–5 a day as an
absolute ceiling, and 1 as the sane default**, with the interruption price
rising sharply when you're deep in something. The design doc's budget mechanism
was right; the number it should be set to is smaller than instinct suggests.

---

## 8. Cost — why the free tick is not optional

- Agentic loops consume **5–30× the tokens** of a chat turn.
- A single multi-step task can spike from **2,000 to 120,000 tokens**; there is a
  reported **70× spread** between a linear call and a planning-heavy agent.
- **Background inference is the fastest-growing cost category** precisely because
  monitoring agents run against every event and every data update.

An always-on Thomas that calls a model on every tick is the exact anti-pattern
currently arriving on other people's bills. The hierarchy in the design doc —
free sensor tick, free threshold cycle, model only on a crossing — is the
difference between a feature and a subscription you'd cancel. §4c adds the
upside: work moved into idle time is *cheaper* than the same work at question
time, not just better timed.

---

## 9. The dissent, taken seriously

**Fully Autonomous AI Agents Should Not Be Developed** (2502.02649) argues risk
scales with autonomy: the more control ceded, the more safety and security risk,
and they find *no clear benefit* to full autonomy against many foreseeable harms.

It is a fair objection and it does not block this, for a reason worth stating
rather than assuming: what's proposed isn't full autonomy. Unprompted action stays
capped at the configured autonomy level, nothing lands without your tap, and the
NIGHTSHIFT laws hold. The paper's own framing — levels of autonomy, delegated
scope, authenticated action inside it — is an argument *for* building it this way,
not against building it. The version it warns about is the one where the loop can
also change the rules that govern the loop, and that is already forbidden.

---

## 10. Bottom line

The design survives contact with the field. Nothing here says don't build it;
several things say build it in a specific order.

1. The gap is real — **nobody's coding agent picks its own work.**
2. The consumer form factor is settled — **overnight batch, morning brief.**
3. The wake decision should be **cheap and learned**, and that is better, not
   just cheaper.
4. **Judging beats speaking** by a wide margin, so build the judge first and let
   mute-mode feed it.
5. The attention budget is **1–3 messages a day**, not the dozen it's tempting
   to allow.

Recommended first slice is unchanged from the design doc — sensor layer plus the
`initiative.py` executor, running mute — with one addition: **log in a shape that
can train a judge**, because that log is now the most valuable thing the first
two weeks produce.

---

## Sources

**Products**
- ChatGPT Pulse — <https://techcrunch.com/2025/09/25/openai-launches-chatgpt-pulse-to-proactively-write-you-morning-briefs/>
- Gemini Proactive Assistance — <https://www.androidauthority.com/google-gemini-proactive-assistance-3661314/>
- Background coding agents compared — <https://techsy.io/en/blog/background-coding-agents-compared>
- Letta sleep-time compute — <https://www.letta.com/blog/sleep-time-compute/>

**Research**
- Proactive Agent / ProactiveBench — <https://arxiv.org/abs/2410.12361> · <https://github.com/thunlp/ProactiveAgent>
- Do Proactive Agents Really Need an LLM to Decide When to Wake? (Microsoft/Purdue) — <https://arxiv.org/abs/2605.30152>
- Agentic Coding Needs Proactivity, Not Just Autonomy — <https://arxiv.org/pdf/2605.06717>
- Sophia: A Persistent Agent Framework of Artificial Life — <https://arxiv.org/abs/2512.18202>
- ProAct / idle-time compute — <https://arxiv.org/abs/2605.25971>
- Ask Now, Use Later — <https://arxiv.org/html/2605.28108>
- ProAgentBench — <https://arxiv.org/html/2602.04482>
- Fully Autonomous AI Agents Should Not be Developed — <https://arxiv.org/abs/2502.02649>
- Need Help? Designing Proactive AI Assistants for Programming (CHI 2025) — <https://dl.acm.org/doi/10.1145/3706598.3714002>

**Ambient agents / cost**
- Change-driven architecture (Microsoft) — <https://techcommunity.microsoft.com/blog/linuxandopensourceblog/beyond-the-chat-window-how-change-driven-architecture-enables-ambient-ai-agents/4475026>
- Notification budget & attention ceiling — <https://tianpan.co/blog/2026-05-13-background-agents-notification-budget-attention-economy>
- Agentic token burn — <https://leanopstech.com/blog/agentic-ai-cost-runaway-token-budget-2026/>

*Note: arxiv.org, huggingface.co, and alphaxiv.org are blocked by this session's
egress proxy. Paper details above come from search-result summaries and accessible
mirrors, not from reading the PDFs directly. Worth a second pass on the three
papers in §4a, §4b, and §5 from a machine that can reach arXiv before we commit
to their numbers.*
