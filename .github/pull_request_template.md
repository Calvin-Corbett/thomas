## Summary

- TBD

## Area

- [ ] Install/setup/support
- [ ] Chat UI or model setup
- [ ] Memory/tools/automation
- [ ] Companion/Infinite
- [ ] Docs/GitHub/release
- [ ] Other

## Validation

- [ ] Focused tests:
- [ ] AI workflow contract: `python scripts\check_ai_workflow_contract.py`
- [ ] Public release surface tests:
- [ ] `python scripts\github_publish_preflight.py --json --strict --deep`
- [ ] `python scripts\check_repo_hygiene.py --require-clean-worktree --strict --json`

## AI Guardrails

- [ ] I followed `docs/AI_CONTRIBUTOR_GUARDRAILS.md`.
- [ ] This PR maps to a clear issue/task/scope.
- [ ] If this changes public release behavior, I ran or documented the public safety checks.

## Public Safety

- [ ] No secrets, local caches, personal notes, generated support bundles, or non-public release notes.
- [ ] No public claim was upgraded without tests/docs/evidence.
- [ ] README/docs were updated if user-facing behavior changed.
