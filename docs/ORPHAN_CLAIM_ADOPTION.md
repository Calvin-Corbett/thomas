# Orphaned-claim adoption

**Problem this solves:** an agent (or a person) finishes work but leaves it
uncommitted, still *holding a claim* on those files. Later a different agent is
blocked from committing because the files are claimed by whoever walked away.
The work strands, and the blocked agent says "I can't, you have to." That is the
exact failure this feature removes.

## What an "orphan" is

A workboard claim whose line in `plans/thomas/WORKBOARD.md` has not been touched
in more than **48 hours** is an **orphan**. "Touched" is measured by git-blame
on the claim line — the same staleness signal `claim_cleanup` already uses. No
background job is required; orphan status is computed on demand, so it is always
current.

## The rules (non-negotiable)

| Situation | Allowed? |
|---|---|
| Work your **own** claim | Always, no ceremony |
| **Adopt** another agent's claim that is an **orphan** (>48h stale) | Yes — but **only with a human Windows Hello breakglass tap** |
| Take another agent's **active** claim (≤48h) | **Never.** Refused outright, even with breakglass — this would let an agent seize someone's in-flight work |

Adoption transfers the claim **and** its active task to the adopter, and writes
a tamper-evident row to `runtime/coordination/workboard_claim_adoption_audit.jsonl`
(from, to, scope, reason, the verified human actor, age).

## How an agent uses it

When the commit gate blocks you because staged files are held by someone else's
**orphaned** claim, it now tells you so and prints the adoption command. The flow:

```bash
# 1. See what's orphaned
python scripts/crew/workboard/claim_adopt.py list-orphans

# 2. Adopt the one covering the files you need (pops a Windows Hello prompt)
python scripts/crew/workboard/claim_adopt.py adopt \
    --agent <you> --scope <path> \
    --reason "previous owner stranded this; taking over to finish"
```

After the human taps, the claim is yours and you can commit normally.

## The intended agent behavior

If a user leaves work uncommitted and walks away, the right move is **not** to
stall. After 48h that claim is an orphan; an agent should say *"this was an
orphan claim — I can adopt it and finish what you were doing"*, ask for the
breakglass tap, adopt it, and continue. The agent never silently takes a live
claim; the 48h orphan window + the human tap are the guardrails.

## Relationship to `claim_cleanup`

`claim_cleanup` *releases* stale claims to "Up For Grabs" (a janitorial sweep).
Adoption is the *active* counterpart: a specific blocked agent **takes
ownership** of a specific orphan to finish its work, with a human in the loop.
Both read the same git-blame staleness signal.

Code: [`scripts/crew/workboard/claim_adopt.py`](../scripts/crew/workboard/claim_adopt.py),
tests: [`tests/test_claim_adopt.py`](../tests/test_claim_adopt.py), gate guidance
in [`scripts/forge/gates/workboard_agent_claim.py`](../scripts/forge/gates/workboard_agent_claim.py).
