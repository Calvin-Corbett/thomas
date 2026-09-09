# Thomas Skill Migration Inventory

First-party Thomas-native skills currently shipped:
- auto-skillify
- capcut-video-editor
- cloudflare-deploy
- davinci-video-editor
- develop-web-game
- doc
- figma
- figma-implement-design
- gh-address-comments
- gh-fix-ci
- higgsfield-video-director
- imagegen
- jupyter-notebook
- linear
- multipart-http-response-parser
- netlify-deploy
- notion-knowledge-capture
- notion-meeting-intelligence
- notion-research-documentation
- notion-spec-to-implementation
- openai-docs
- pdf
- partial-structuring-recovery
- playwright
- render-deploy
- screenshot
- security-best-practices
- security-ownership-map
- security-threat-model
- serializer-deserializer-feature-matrix
- sentry
- skill-authoring
- skill-distillation
- sora
- speech
- spreadsheet
- stream-clip-pipeline
- thomas-site-visual-proof
- transcribe
- ui-precision-guard
- vercel-deploy
- video-creation-director
- yeet

Not carried over as first-party Thomas skills:
- `.system/*` Codex-internal installer/creator helper bundles remain excluded on purpose.

Migration policy:
- Treat external skills as read-only references.
- Recreate Thomas-native bundles from scratch.
- Require review and no-copy validation before promoting distilled drafts.
