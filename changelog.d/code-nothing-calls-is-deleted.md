### Removed

- You no longer carry 24 uncalled files under `thomas/`: unused Slack channel, user and file helpers; the Notion rich-text helper; the tray worktree scanner; an observability example and its setup note; the hotkey-only intake script; two server re-export shims; a stale live-repo change tracker; a restricted unpickler; a per-module chat preamble; a code-free plugins registry folder; the app-builder modules; and the empty approvals package and its shim. Three tests that only covered the app-builder modules are gone too.
- You chose to delete the app-builder and approvals modules; they remain in git history if you need them later. The Slack, marketplace and workflow docs now describe what remains, and a new regression test keeps the unused files from returning without a caller.
