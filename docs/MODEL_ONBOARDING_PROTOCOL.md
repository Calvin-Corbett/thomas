# Model Onboarding Protocol

Use this protocol every time a new model profile is added or changed.  
Goal: never ship a profile that cannot call tools reliably.

## 1) Research and Capture

1. Collect provider/model release notes and migration notes.
2. Save findings to the Thomas library (`thomas library add ...`) before coding.
3. Record known caveats (for example deprecated params, unsupported prefill, tool syntax differences).

## 2) Add or Update the Profile

1. Edit `thomas.toml` profile config.
2. If the model is user-selectable in UI recommendations, update `thomas/server/web/models.json`.
3. Keep profile names stable and human-readable (`openai`, `anthropic`, `groq`, etc).

## 3) Run Validation Gate (Required)

Run the automated gate:

```bash
thomas models validate --model <profile> --strict
```

This runs:
- provider handshake (auth/connectivity/endpoint health)
- synthetic tool-call smoke test (model must emit a valid tool call)

Do not merge onboarding changes until this passes.

Then update:
- `docs/MODEL_ONBOARDING_LOG.md` with date/profile/research/validation evidence
- `CHANGELOG.md` with user-facing impact summary
- at least one research note under `library/entries/research-notes/`

## 4) Regression Safety

1. Add or update tests under `tests/` for any provider-specific behavior.
2. Run targeted tests for changed paths.
3. If behavior is user-facing, update `README.md` and `CHANGELOG.md`.

## 5) Rollout Rule

If validation fails:
- do not set the profile as default
- fix config/migrations first
- re-run `thomas models validate --strict` until green
