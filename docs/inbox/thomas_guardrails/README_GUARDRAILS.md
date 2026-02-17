# Guardrails module drop-in

This zip is meant to be merged into the Thomas repo.

Key modules:
- thomas/policy/*            Policy + rule library + redaction + config
- thomas/agent/approval.py   ApprovalBroker (async futures)
- thomas/agent/guarded_tools.py  GuardedToolRunner (policy gate + approval + redaction + audit)
- thomas/server/audit_log.py AuditLog (sqlite3, async wrapper)
- thomas/server/guardrails_api.py  /api/approvals/* endpoints (localhost-only)
- thomas/server/static/guardrails.* UI modal handler

See PATCH_NOTES.md and INTEGRATION_GUIDE.md.
