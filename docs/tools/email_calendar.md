# Email + Calendar Integration (Feature 18)

This module provides Thomas tools for:
- Email: `email.read`, `email.get`, `email.send`, `email.reply`
- Calendar: `calendar.today`, `calendar.week`, `calendar.create_event`, `calendar.suggest_times`

It supports:
- **Gmail + Google Calendar** (OAuth refresh token)
- **Microsoft Graph** (OAuth refresh token)

## Config

Add to `thomas.toml`:

```toml
[tools.email]
provider = "gmail"        # or "microsoft"
client_id = "..."
client_secret = "..."
refresh_token = "..."

# Microsoft only:
tenant_id = "..."

# optional:
timezone = "America/Chicago"
http_timeout_s = 30
max_connections = 20
max_keepalive_connections = 10
gmail_fetch_concurrency = 6

# Microsoft delegated token refresh scopes (recommended)
microsoft_scopes = ["offline_access", "Mail.Read", "Mail.Send", "Calendars.Read", "Calendars.ReadWrite"]
```

Env overrides (optional):
- `THOMAS_TOML`
- `THOMAS_TOOLS_EMAIL_PROVIDER`
- `THOMAS_TOOLS_EMAIL_CLIENT_ID`
- `THOMAS_TOOLS_EMAIL_CLIENT_SECRET`
- `THOMAS_TOOLS_EMAIL_REFRESH_TOKEN`
- `THOMAS_TOOLS_EMAIL_TENANT_ID`
- `THOMAS_TOOLS_EMAIL_TIMEZONE`

## Notes

### Gmail filters
`email.read` passes your `filter` string straight into Gmail search, with a convenience shortcut:
- `filter="unread"` becomes `is:unread`

### Microsoft filters
`email.read` supports:
- `unread`
- `from:someone@domain.com`
- `to:someone@domain.com`
- `subject:keyword`
- otherwise uses Graph `$search` (requires `ConsistencyLevel: eventual` internally).

### Scheduling
`calendar.suggest_times`:
- checks **your** calendar for conflicts
- best-effort merges attendee free/busy when available:
  - Google freeBusy API (works when calendars are shared/accessible)
  - Microsoft `getSchedule` (best inside orgs)

### Conflict protection
`calendar.create_event` checks conflicts by default.
Set `check_conflicts=false` if you intentionally want overlaps.
