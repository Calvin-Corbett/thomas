# Thomas Architecture Overview

This is the short public architecture map. It is intentionally higher-level than
the code so agents and contributors can orient before editing.

## Install And First Run

```mermaid
flowchart TD
  A["GitHub Release"] --> B["ThomasSetup EXE"]
  B --> C["Install files and launch first-run wizard"]
  C --> D["Create local .venv and setup markers"]
  D --> E["Start local server on 127.0.0.1:8899"]
  E --> F["Open browser workspace"]
  F --> G["Easy Setup validates model/provider"]
  G --> H["Everyday chat path unlocks memory, tools, and automation"]
```

The installer and first-run path should be understandable to a non-engineer. If
the wizard fails, the support path is `support.cmd`, `repair.cmd`, `setup.cmd`,
and `bootdoctor.cmd`.

## Runtime Model

```mermaid
flowchart LR
  UI["Browser UI"] --> API["Aiohttp server"]
  CLI["CLI / REPL"] --> API
  API --> Chat["Chat and routing"]
  Chat --> Models["Model providers"]
  Chat --> Memory["Memory and library"]
  Chat --> Tools["Guarded tools"]
  Tools --> Policy["Policy and approvals"]
  API --> Jobs["Autonomy jobs and Mission Control"]
  Jobs --> Policy
  API --> Companion["Companion API"]
```

The public default is loopback-only. Remote or LAN use must be configured
intentionally and protected with the production controls documented in
`README.md`, `SECURITY.md`, and `docs/NETWORKING_AND_FIREWALL.md`.

## Guarded Execution

```mermaid
sequenceDiagram
  participant User
  participant UI
  participant Agent
  participant Policy
  participant Tool
  participant Audit
  User->>UI: Ask Thomas to do work
  UI->>Agent: Send task and context
  Agent->>Policy: Request tool/action approval
  Policy-->>Agent: Allow, deny, or require approval
  Agent->>Tool: Execute only if allowed
  Tool-->>Agent: Result or failure
  Agent->>Audit: Record run/tool event
  Agent-->>UI: Progress, blocker, or answer
```

Guardrails are executable checks in the runtime, not just written instructions.
Docs still matter because agents and contributors need to know which checks exist
and which workflow is safe.

## Infinite App Direction

```mermaid
flowchart LR
  Phone["Infinite mobile app"] <--> Tail["Private Tailscale path"]
  Tail <--> Thomas["Local Thomas runtime"]
  Thomas --> Apps["Thomas-built app surfaces"]
  Apps --> Phone
  Thomas --> Browser["Local/headless browser execution"]
  Browser --> Apps
  Thomas --> Policy["Policy, auth, audit, rollout"]
```

Infinite is planned as a mobile companion, not the Thomas runtime itself. Thomas
keeps execution, policy, and audit authority on the local host. Infinite renders
approved chat, approvals, dashboards, and app-like surfaces over a private
network path.

## Thomas OS Direction

Thomas OS is a long-horizon concept. It is not a current distribution, installer,
or supported runtime. The current concrete path is: make Thomas Core reliable,
build the Infinite companion app contract, then use that learning to define what
an OS-level environment should actually be.
