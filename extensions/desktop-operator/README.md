# Desktop Operator

Desktop Operator is the first-party Thomas desktop control capability for one approved workflow session at a time.

Desktop Operator Magic is designed for:
- local dedicated VM execution instead of the human's live desktop
- quiet guardrails with balanced approvals for high-risk steps
- allowlisted workflow profiles instead of fake universal pixel control
- semantic-first actions with bounded pointer fallback
- direct window capture, OCR/accessibility state reads, verification, recovery, and circuit breaking
- redacted replay by default for sensitive sessions
- browser session, Windows file dialog, and CapCut as the first polished workflows

Operator setup surfaces:
- `thomas desktop-operator status --json-output` for current VM/helper posture
- `thomas desktop-operator bootstrap --json-output` to generate the guest bootstrap package and bridge layout
- `scripts/desktop_operator/prepare_hyperv_host.ps1` for the one-time elevated Hyper-V host preflight/remediation

This bundle provides the catalog and Mission Control surface for the Thomas marketplace. The core helper/runtime lives in the Python package `thomas.desktop_operator`.
