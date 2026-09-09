---
name: security-ownership-map
description: Map repository ownership and bus-factor risk for security-sensitive code using git history and structural hotspots.
---

# Security Ownership Map

Use this skill when the user wants a security-oriented ownership analysis grounded in repository history.

## Workflow
1. Identify the security-sensitive parts of the repo and the ownership question being asked.
2. Use git history and file topology to map maintainers and concentration risk.
3. Highlight orphaned or weakly owned security-sensitive surfaces.
4. Export or summarize the ownership data in a usable operational format.
5. Call out the biggest bus-factor and stewardship risks directly.

## Rules
- Do not confuse recent edit frequency with true expertise.
- Keep security sensitivity explicit when presenting ownership data.
