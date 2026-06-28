# AIO Sandbox Worker Isolation Threat Model

Date: 2026-06-27
Status: planning threat model for ranked Agentic AI item 13, "AIO Sandbox Unified Agent Workspace"
Scope: one Thomas coding-worker lifecycle that receives a workboard task, edits an isolated workspace, runs verification, submits evidence, and hands a reviewed change back to the live `dev` checkout.

## Source Evidence Checked

- `plans/thomas/AGENTIC_AI_FEATURE_RANKINGS.md` ranks AIO Sandbox Unified Agent Workspace at score 89 and calls for a sandbox threat model against Thomas worker isolation needs.
- `docs/CAGE_SETUP.md:5`, `docs/CAGE_SETUP.md:25`, and `docs/CAGE_SETUP.md:126` state the core residual: a same-OS-user shell can control local files unless a separate OS/sandbox boundary turns the worker into a proposer and keeps commit/sign/push with a host-side commit-master.
- `docs/CAGE_SETUP.md:140` through `docs/CAGE_SETUP.md:145` describe the desired Windows Sandbox posture: network disabled, only explicit Thomas paths mapped, disposable writes outside mapped folders, and host-side commit-master handling signing and push.
- `thomas/forge/anvil/native_orchestration.py:134` through `thomas/forge/anvil/native_orchestration.py:181` define worker records with recipe, lane, status, dedupe key, claim scope, runner hint, and model hint.
- `thomas/forge/anvil/native_orchestration.py:606` through `thomas/forge/anvil/native_orchestration.py:617` collect dirty paths, workboard rows, active-folder claims, stale/dead owners, evolve-loop status, and merge-ready lanes before dispatch.
- `thomas/forge/anvil/evolve_runtime_exec.py:17` through `thomas/forge/anvil/evolve_runtime_exec.py:41` deny high-risk tools for self-development, including shell, ssh, git, workflow execution, and green/blue promotion tools.
- `thomas/forge/anvil/evolve_runtime_exec.py:103` and `thomas/forge/anvil/evolve_runtime_exec.py:134` through `thomas/forge/anvil/evolve_runtime_exec.py:141` force shell off and merge the tool denylist into the child environment.
- `thomas/server/app_helpers.py:110` through `thomas/server/app_helpers.py:147` register filesystem, optional shell, git, code-search, ssh, investigation, and optional tools into the live tool registry.
- `thomas/tools/filesystem.py:25` through `thomas/tools/filesystem.py:44`, `thomas/tools/filesystem.py:410` through `thomas/tools/filesystem.py:426`, and `thomas/tools/filesystem.py:555` through `thomas/tools/filesystem.py:583` provide sandbox-root path checks and runtime-code write protection, but those are in-process controls rather than a process/container boundary.
- `scripts/crew/brief/commit.py:40` through `scripts/crew/brief/commit.py:109` run local gates for protected files, workboard inbox, active-folder guard, workboard claims, staged-scope enforcement, release updates, and other commit checks before scoped commits.

## System Model

The target lifecycle is:

1. Thomas selects a ranked or workboard task and creates a worker record with a narrow claim scope.
2. A sandbox workspace is provisioned from a clean repository baseline plus explicit task context.
3. The worker receives only the allowed tools, files, secrets, and network posture for that task.
4. The worker edits files inside the sandbox, runs approved verification, and emits evidence.
5. A host-side verifier/commit-master treats the worker output as data, re-derives the diff from a clean baseline, runs gates, and only then commits on `dev`.
6. Thomas records the final outcome, evidence, denied actions, cost/tool telemetry, and claim release.

The model assumes AIO-style sandboxing may provide browser, shell, filesystem, MCP services, VNC, VSCode Server, and agent APIs. Thomas must not treat those bundled services as trusted merely because they are inside one sandbox product.

## Trust Boundaries

| Boundary | Inbound side | Trusted side | Required control |
|---|---|---|---|
| User/workboard prompt -> worker prompt | Human text, queue metadata, prior run summaries | Worker task contract | Prompt/context allowlist, task id, claim scope, source provenance |
| Live checkout -> sandbox workspace | Dirty shared repo, local secrets, unrelated workers | Disposable worker workspace | Clean baseline copy, explicit mapped paths, no broad host profile mounts |
| Worker process -> host filesystem | Shell, browser downloads, MCP tools, VSCode server | Host repo and user files | OS/container path boundary, mapped-folder allowlist, read-only host mounts where possible |
| Worker tools -> network | Browser, shell, package managers, MCP servers | Internet and internal services | Default-deny egress, per-task allowlist, logged DNS/HTTP/MCP receipts |
| Worker output -> commit-master | Patch, logs, verification claims | Commit/sign/push authority | Treat output as untrusted data, rebuild in clean room, rerun gates, ignore self-approval |
| Sandbox telemetry -> Thomas audit store | Potentially attacker-influenced logs | Security evidence and worker scoring | Append-only host-side receipts, schema validation, signed action records |
| Secret broker -> worker | API tokens, repo credentials, user files | Task-scoped secret material | No ambient secrets, short-lived scoped credentials, no secret readback in logs |
| Worker-to-worker state -> dispatcher | Run state, active-folder claims, messages | Dedupe and routing decisions | Stale/dead-owner detection, claim-scope enforcement, no hidden heartbeat-only authority |

## Assets

- Live `dev` checkout integrity, including `.git`, hooks, protected gate scripts, release metadata, and workboard state.
- User files and other local repositories outside the claimed Thomas workspace.
- Runtime secrets: model keys, GitHub credentials, signing keys, `.thomas` state, runtime protection keys, and any MCP credentials.
- Worker task inputs: prompts, attachments, claim scope, ranker context, and prior summaries.
- Worker outputs: patch, verification logs, screenshots, terminal output, artifacts, and final report.
- Audit evidence: denied actions, allowed high-risk actions, tool calls, network receipts, spend/cost, commit gate results, and claim release.
- Availability of worker orchestration: dispatcher, active-folder leases, message inbox, sandbox pool, and commit-master queue.

## Attacker Capabilities

In scope:

- Malicious or prompt-injected repository content read by the worker.
- A compromised or confused worker model trying to exceed its remit.
- A malicious dependency, webpage, MCP server, browser payload, or cloned project contacted from inside the sandbox.
- A worker with shell inside its sandbox trying to alter host state, forge verification, tamper with gates, exfiltrate secrets, or bypass claim scope.
- A stale worker or duplicate worker racing another claim.

Out of scope for this planning slice:

- Kernel or hypervisor escape from Windows Sandbox, Docker, or the host OS.
- A human intentionally approving a malicious commit after clear evidence.
- GitHub or model-provider platform compromise.

## Allowed And Denied Capabilities

Allowed by default for a coding-worker sandbox:

- Read the clean task workspace, claimed files, task brief, relevant docs, and focused tests.
- Write only within the disposable sandbox workspace and declared output/evidence directory.
- Run focused verification commands required by the task.
- Use browser or network only when the task explicitly requires it and an egress policy is attached.
- Submit a patch/evidence bundle to the host verifier.

Denied by default:

- Direct writes to the live checkout, `.git`, hooks, gate scripts, release metadata, workboard files outside claim, runtime keys, or user profile paths.
- Direct `git commit`, `git push`, signing, branch protection changes, or remote configuration edits from the worker.
- Ambient shell access to host paths outside mapped workspace.
- Read access to host secrets, tokens, SSH keys, browser profiles, or unrelated repositories.
- Unreviewed package install, clone, MCP server registration, or network egress.
- Worker self-approval, self-claimed verification, or marking its own dangerous action as accepted.

## Primary Threats

| Threat | Abuse path | Impact | Likelihood | Priority | Required mitigation |
|---|---|---:|---:|---:|---|
| Host checkout contamination | Worker shell or VSCode service writes directly to `C:\Users\corbe\Thomas` instead of a sandbox copy | High | Medium | High | No writable live checkout mount; clean-room patch handoff; commit-master reruns gates |
| Secret exfiltration | Browser/shell/MCP reads host token files or env vars and sends them over network | High | Medium | High | Empty/sanitized env, secret broker, default-deny egress, read-protected host paths |
| Gate tampering | Worker edits hooks, safety config, protected gate scripts, release metadata, or workboard to approve itself | High | Medium | High | Read-only/no-access protected paths, trusted manifest, host-side gate execution |
| Claim-scope bypass | Worker modifies unclaimed files or bundles unrelated dirty work into its patch | Medium | High | High | Workboard claim before launch, staged-scope gate, selected-path commit helper, diff allowlist |
| Network pivot | Worker uses browser/package manager/MCP to reach internal services or clone/exfiltrate | High | Medium | High | Disabled network by default; per-destination allowlist; signed egress receipts |
| Malicious tool server | MCP service lies about tool results, exposes extra tools, or mutates files outside declared API | Medium | Medium | Medium | Tool manifest pinning, per-tool policy, sidecar isolation, receipt validation |
| Verification forgery | Worker writes fake test logs, success markers, or screenshots without running checks | Medium | Medium | Medium | Host reruns deterministic checks; output treated as advisory; logs include command receipts |
| Duplicate worker race | Two workers edit the same claim or stale active-folder lease causes unsafe dispatch | Medium | Medium | Medium | Dedupe keys, active claim audit, stale/dead-owner cleanup before dispatch |
| Persistent sandbox residue | State from one worker influences a later worker through caches, browser profile, package state, or shared volumes | Medium | Low | Medium | Disposable workspace per lifecycle; cache partitions by task; teardown evidence |
| Audit poisoning | Worker injects misleading log fields or terminal output that corrupts dashboards or follow-up decisions | Medium | Medium | Medium | Structured event schema, escaping, append-only host-side audit, raw-log quarantine |

## Isolation Controls

Minimum viable control set for one Thomas coding-worker lifecycle:

1. Provision a fresh workspace from a clean baseline, not the dirty shared checkout.
2. Mount only the sandbox workspace and a narrow inbox/outbox/evidence channel; never mount the whole user profile, drive root, or unrelated repo tree.
3. Run the worker as a non-privileged identity with no signing, push, host secret, or gate-write authority.
4. Disable network by default. If needed, require a task-specific egress policy that names allowed domains, protocols, and package sources.
5. Strip ambient environment variables before launch, including model keys not explicitly delegated, GitHub tokens, skip flags, and Thomas runtime override flags.
6. Deny commit/push/signing and high-risk local tools inside the worker. Existing self-development denylist patterns are the baseline, not the final sandbox policy.
7. Keep the host-side commit-master/verifier outside the sandbox. It must rebuild the patch from a clean baseline, rerun checks, and ignore worker self-approval.
8. Emit signed or host-stamped receipts for process launches, file writes, network attempts, MCP calls, denied actions, verification commands, and final artifact hashes.
9. Record claim scope, worker id, task id, baseline commit, sandbox image/config digest, allowed tools, egress policy, started/stopped timestamps, and teardown result.
10. Tear down the sandbox after the lifecycle and verify no unexpected host paths were written.

## Evidence Thomas Should Collect

For each worker run:

- `worker_id`, `task_id`, `claim_scope`, `dedupe_key`, `parent_agent`, model hint, runner hint, and baseline commit.
- Sandbox image/config digest, mapped paths, read/write mode per mount, network mode, and secret policy.
- Tool policy: allowed tools, denied tools, high-risk overrides, and denied action receipts.
- Files read and written at path level, with hashes for submitted artifacts.
- Commands run for verification, exit codes, stdout/stderr artifact hashes, and timeout/spend watchdog status.
- Network/MCP/browser receipts: destination, method/tool, bytes, decision, and reason.
- Patch summary generated by host diff, not worker narration.
- Host verifier result: exact gates run, selected commit paths, release/protected-file gate result, and commit SHA if accepted.
- Claim lifecycle: claim created, overlap check, release command, release result, and unresolved messages/blockers.

## Acceptance Checklist For Future Implementation

- [ ] Worker launch requires a workboard claim with exact file or directory scope before sandbox creation.
- [ ] Sandbox creation records baseline commit, image/config digest, mount list, network posture, secret posture, and allowed tools.
- [ ] The live checkout is not writable from inside the worker sandbox.
- [ ] The worker cannot read host secret files, signing keys, GitHub tokens, runtime protection keys, browser profiles, or unrelated repositories.
- [ ] Network is disabled unless a task-specific egress policy is present and receipts are recorded.
- [ ] Shell, browser, MCP, filesystem, git, and package-manager actions are mediated by policy with deny receipts.
- [ ] Worker output is accepted only through an inbox/evidence bundle; commit/sign/push remains host-side.
- [ ] Host verifier rebuilds the patch from clean baseline and reruns commit gates before any commit.
- [ ] Scoped commit gates reject files outside claim scope and preserve unrelated dirty checkout state.
- [ ] Verification evidence includes commands and artifacts the host can rerun or validate.
- [ ] Duplicate active workers and stale/dead-owner leases block launch or require explicit coordinator cleanup.
- [ ] Sandbox teardown verifies no unexpected mapped paths changed and no reusable worker state leaks into the next task.
- [ ] Final worker report includes commit SHA or blocker, changed files, verification results, claim release, and residual risks.

## Residual Risks And Open Questions

- The existing in-process filesystem and tool denylist controls are useful defense in depth but cannot replace an OS/container boundary for shell, browser, and MCP authority.
- Some worker tasks may require package installs or internet research. Those need a separate egress/package policy rather than a blanket allow.
- Browser/VNC/VSCode services inside an all-in-one sandbox expand the attack surface. Thomas should treat each service as separately policy-controlled and logged.
- The exact sandbox backend remains open: Windows Sandbox matches the current cage note for local containment, while Docker-style sandboxes may be more portable but require careful host mount and network defaults.
- A human can still approve a bad patch. The goal is to make that approval informed by host-derived evidence, not worker assertions.
