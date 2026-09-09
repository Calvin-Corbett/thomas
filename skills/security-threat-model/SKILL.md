---
name: security-threat-model
description: Build concise repository-grounded threat models covering assets, boundaries, attacker capabilities, abuse paths, and mitigations.
---

# Security Threat Model

Use this skill when the user explicitly asks for threat modeling, abuse-path analysis, or AppSec-oriented design review.

## Workflow
1. Define the system boundary, assets, and trust assumptions.
2. Enumerate attacker capabilities and likely abuse paths grounded in the actual architecture.
3. Identify mitigations, detection gaps, and residual risk.
4. Write the model in a concise structure that can drive implementation decisions.
5. Separate confirmed architecture facts from assumptions that need validation.

## Rules
- Anchor the model in the real repo or system rather than abstract templates.
- Keep abuse paths concrete enough to be actionable.
