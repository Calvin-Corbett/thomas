---
name: yeet
description: Stage, commit, push, and open a pull request in one deliberate GitHub CLI flow when the user explicitly requests that end-to-end action.
---

# Yeet

Use this skill only when the user explicitly asks Thomas to stage, commit, push, and open a PR in one flow.

## Workflow
1. Verify the intended change set and branch state before touching git.
2. Stage only the files that belong to the requested work.
3. Create a clear commit message and push the branch.
4. Open the PR with an accurate title and body.
5. Return the commit and PR references to the user.

## Rules
- Do not include unrelated dirty worktree changes.
- Only run this flow when the user explicitly requested the full git-and-PR action.
