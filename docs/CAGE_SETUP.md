# The Praxis Cage — setup runbook

This is the finale of the *praxis-unbypassable* exercise. The Red/Blue loop
closed every locally-fixable gate bypass, but left one irreducible residual:
**a same-OS-user shell controls local files**, so the worker agent could forge
the success marker, delete hooks, reset the audit, or self-approve — because the
worker *was also* the committer.

The cage removes that by **splitting the worker's two roles apart**: the agent
becomes a *proposer* that can only drop a submission; a separate identity (the
*commit-master*) is the only thing that can commit/sign/push.

```
   WORKER (thomas-agent, non-admin)            COMMIT-MASTER (you, Win Hello key)
   ┌───────────────────────────┐               ┌────────────────────────────────┐
   │ edits files, runs tools   │   inbox/      │ 1. rebuild change in a clean    │
   │ CANNOT commit/push/sign   │ ───drop────►  │    room from pristine HEAD      │
   │ CANNOT read keys or gates │   (one-way)   │ 2. verify gate integrity        │
   │ CANNOT talk to the master │               │ 3. run gates (sanitized env)    │
   │                           │   outbox/     │ 4. sign + commit + push         │
   │ reads verdicts only       │ ◄──verdict──  │    (only it holds the key)      │
   └───────────────────────────┘   (one-way)   └────────────────────────────────┘
```

The agent's **only** channel to the repo is the inbox. The master treats each
submission as inert **data**: it never imports or executes it, ignores any
self-asserted approval in it, and re-derives everything from pristine `HEAD` +
the patch.

---

## The four parts and their status

| Part | What it does | Status |
|------|--------------|--------|
| 1. Separate OS user | Worker runs as non-admin `thomas-agent`, no access to your files | **Script ready** — you run it elevated once |
| 2. Ownership/ACLs | Gates, `agent_safety.toml`, keys, `.git` owned by you, read-only/no-access to the agent | **Script ready** — same elevated run |
| 3. Commit-master | The only committer; clean-room gate run; submissions are data | **Built + tested** (15 security tests; real-repo smoke green) |
| 4. Branch protection | Server-side backstop on `dev`/`main` | **`main` enforced**; `thomas-dev/dev` plan-blocked (see below) |

---

## One-time setup

### Step 1+2 — provision the OS boundary (elevated, ~2 min)

From an **Administrator** PowerShell:

```powershell
cd C:\Users\corbe\Thomas
.\scripts\cage\provision_cage.ps1 -AgentUser thomas-agent
```

This creates the non-admin `thomas-agent` account (printing a one-time password
to store in *your* vault), then locks the safety-critical paths:

- **read-only to the agent**: `scripts/forge/gates/`, `scripts/forge/commit_master.py`,
  `agent_safety.toml`, `.git/hooks`, `.git/config`
- **no agent access at all**: `runtime/.runtime_protection_key` (HMAC key → closes
  B16), `.git/thomas_skip_audit.jsonl` (breakglass audit → closes B17)
- **one-way channels** at `C:\ProgramData\ThomasCage`: `inbox` (agent writes),
  `outbox` (agent reads), `audit`/`work` (agent: none)

Verify anytime (read-only, no admin needed):

```powershell
.\scripts\cage\verify_cage.ps1
```

It prints PASS/FAIL per check. Before provisioning it cleanly reports
"cage not provisioned yet".

### Step 3 — run the two identities

Run the **worker agent** as `thomas-agent` (via `runas` or a scheduled task),
with the cage root in its environment:

```powershell
setx THOMAS_CAGE_ROOT "C:\ProgramData\ThomasCage"   # in the agent's profile
```

The worker's only repo-affecting command is to submit (it stages its change,
then):

```powershell
python scripts\forge\commit_master.py submit --agent claude --message "<commit message>" --branch <feature-branch> --remote dev-origin
```

Run the **commit-master** as **you** (you hold the signing key behind Windows
Hello), watching the inbox:

```powershell
python scripts\forge\commit_master.py --cage-root "C:\ProgramData\ThomasCage" watch
```

For each submission it rebuilds the change in a clean room, verifies gate
integrity, runs the gates with a sanitized environment, and — only if all pass —
signs + commits + pushes. Windows Hello pops on the signing step: **your tap is
the authorization.** A failing submission gets a verdict in the outbox and is
never committed.

### Step 4 — server-side backstop

```powershell
python scripts\cage\apply_branch_protection.py verify --target both   # see current state
python scripts\cage\apply_branch_protection.py apply  --target dev     # when unblocked
```

Public `Calvin-Corbett/thomas` `main` is already fully enforced
(`gates-required` + `signed-commits-check` + signed commits + admin-enforced).
The private `thomas-dev/dev` is **plan-blocked**: its free `User` plan returns
HTTP 403. To turn it on, pick one:

- **(a)** upgrade the owner of `thomas-dev` (`Calvin-Corbett`) to GitHub Pro/Team,
  *then* `apply --target dev`. (Protection keys off the **repo owner's** plan, not
  the account `gh` is logged in as.)
- **(b)** make `thomas-dev` public, then `apply --target dev`.
- **(c)** move the protected integration branch to the already-protected public
  `thomas` repo.

Until then, **Parts 1-3 are the enforcing layer** and Part 4 is on for public
`main` only.

---

## Containment: the Windows Sandbox wall (PROBLEM 1)

The OS-user + ACL layer (Part 1+2) stops the agent from touching *your* files,
but a non-admin same-host shell still has the **network** and can read other
repos. As the Praxis exercise concluded, no local gate stops a same-user shell
— only OS isolation does. On Windows 11 Pro the built-in **Windows Sandbox** is
that isolation: a disposable, kernel-isolated VM where nothing exists but what
you explicitly map in.

`scripts/cage/build_sandbox_config.py` generates a `.wsb` whose posture gives
the three guarantees:

| Guarantee | How |
|---|---|
| cannot clone outside its box / reach the network | `<Networking>Disable</Networking>` — `git clone`/`push`/exfil have no network |
| cannot reach other repos | only the Thomas repo is mapped; every other host path is invisible |
| cannot escape allowed paths | disposable box; writes outside the mapped read-write folders evaporate on close |

The cage `inbox`/`outbox` are mapped folders, so the network-less worker drops
submissions and the HOST-side commit-master (run as you, outside the box) does
the signing + push. No network is needed for that handoff. A containment guard
in the generator refuses to map a drive root, the `Users` tree, a whole
profile, or a system tree (which would re-expose the host).

`scripts/forge/gates/cage_egress_guard.py` is an honest defense-in-depth
tripwire (NOT the wall): it flags clone/remote/submodule/`.git`/out-of-allowlist
signals in a submitted change so they are caught when the sandbox is not active.

> **CALVIN, ELEVATED, ONE-TIME (then reboot):** enable the feature
> `Enable-WindowsOptionalFeature -Online -FeatureName 'Containers-DisposableClientVM' -All`
> (needs Win 11 Pro/Enterprise + virtualization in BIOS). Verified currently
> OFF on this machine (`WindowsSandbox.exe` absent). After the reboot, launch
> the caged worker (no admin needed):
> `powershell -File scripts\cage\launch_sandbox.ps1`  (add `-ConfigOnly` to just
> generate + inspect the `.wsb`).

## Coordination: messages that cannot be missed (PROBLEM 2)

The workboard message lane is pull-only, so "don't touch X" directives pile up
unread and get missed. Delivery is now enforced at two layers:

- **Surfaced at session start** — `scripts/crew/brief/startup_router.py` prints
  this agent's unread messages inline (via `message.unread_messages`), so a
  directive is seen the moment a session begins.
- **Blocked at the commit/submit choke point** — two complementary gates share
  one definition of "unread for me" (`message.unread_messages`):
  - repo-wide **block-on-any**: `scripts/forge/gates/workboard_inbox.py` — any
    unread message blocks the next action until acked (wired into pre-commit).
  - cage submit **scope-aware** (Calvin-chosen 2026-06-02): the commit-master
    `submit` (`scripts/forge/commit_master.py`) refuses only on *relevant*
    unread — a must-read kind (blocker/scope_change) or a message whose subject
    paths overlap the files being submitted — so a caged worker can't drop a
    submission past a "don't touch X" directive, but isn't wedged by an
    unrelated FYI.

"until **read and acked**": acking a message
(`message.py --ack --msg-id <id> --by <agent>`) is the agent asserting it read
the directive; once acked it no longer blocks. Verified live with the codex
session: a `scripts/cage` submission by codex was blocked while a
`scope_change` was unread, and proceeded after the ack.

> **DESIGN DECISION (Calvin, 2026-06-02): scope-aware for the cage submit.**
> The repo-wide pre-commit gate (`workboard_inbox.py`) stays **block-on-any**
> (simple, strict); the cage submit is **scope-aware** (block only on a
> must-read kind or a message about the files being submitted) — the literal
> reading of "block commits to *claimed paths* until *relevant* messages are
> acked", which avoids wedging a focused worker or the coordinator on unrelated
> mail. Both layers share `message.unread_messages` as the one definition of
> "unread for me".
>
> **Wiring note (protected files):** any change to the repo-wide gate touches
> `.pre-commit-config.yaml`, `agent_safety.toml [protected] enforcement_scripts`,
> and `scripts/active_folders.py` — all protected, so they need Calvin's
> approval. The cage submit + startup surfacing enforce delivery without editing
> them.

---

## Why each part closes a residual

| Residual (from the exercise) | Closed by |
|---|---|
| B1' shell mints the success marker | Part 3 — master runs gates itself; there is no marker to forge |
| B6 delete hooks / redirect `core.hooksPath` | Part 2 (`.git` read-only) + Part 3 (master doesn't rely on the worker's hooks) |
| B12/B19 self-asserted approval trailers / deletion records | Part 3 — submissions are data; the master re-stamps its own trailers and ignores theirs |
| B16 forge `runtime/.runtime_protection_key` | Part 2 — key is no-access to the agent |
| B17 reset `.git/thomas_skip_audit.jsonl` | Part 2 — audit is no-access to the agent |
| env-var bypasses (B4/B5/R4) | Part 3 — the master strips `THOMAS_SKIP_*`, `*_DISABLE`, `GITHUB_ACTIONS`, `AGENT_ID`, the marker-key override, etc. before running any gate |
| a patch that neuters a gate (B3/B7) | Part 3 — the master hashes the clean-room gate files against a trusted manifest the worker cannot write, and rejects on mismatch |

## What is still trusted (honest residual)

The cage is "no bypass without a real human at a step that matters", not
"no bypass possible". It still trusts:

- **the OS** to enforce the ACLs (a kernel/privilege-escalation exploit is out of
  scope);
- **GitHub** for the server-side backstop;
- **you** at the Windows Hello prompt — that tap *is* the authorization, by
  design. If you approve a bad change, that's a human decision, not a bypass.

This matches `docs/SAFETY_ARCHITECTURE.md`: local controls are tamper-evident,
and the genuine enforcement is the privilege boundary (Parts 1-3) plus the
server-side layer (Part 4).
