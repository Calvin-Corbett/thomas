# Deployment And Scale Runbook

This website is designed for immediate public traffic with minimal ops burden.

## 1. Provision data layer

1. Create a managed Postgres database (Neon, Supabase, RDS, or equivalent).
2. Execute `apps/site/sql/001_download_events.sql`.
3. Save `DATABASE_URL`.

## 2. Configure GitHub release source

1. Set `THOMAS_GITHUB_REPO=owner/repo`.
2. Add `GITHUB_TOKEN` to avoid anonymous rate limits.

If you want website-first launch before GitHub integration, set:

- `THOMAS_DOWNLOAD_MODE=manual`
- `THOMAS_DOWNLOAD_URL_WINDOWS`
- `THOMAS_DOWNLOAD_URL_MACOS`
- `THOMAS_DOWNLOAD_URL_LINUX`

## 3. Configure hosting

### Vercel

1. Import this project with root directory `apps/site`.
2. Add environment variables from `.env.example`.
3. Deploy production.

### Cloudflare Pages (Next support)

1. Set project root to `apps/site`.
2. Configure build command `npm run build`.
3. Configure output mode according to Pages Next support.
4. Add environment variables from `.env.example`.

## 4. Domain and caching

1. Point `thomas.dev` (or your chosen domain) to hosting provider.
2. Set `SITE_URL` to production origin.
3. Keep CDN caching enabled:
   - `/api/releases`: 5 minute cache, stale-while-revalidate 15 minutes.
   - `/api/metrics/overview`: 2 minute cache, stale-while-revalidate 10 minutes.

## 5. Analytics and monitoring

1. Optional: set `POSTHOG_PROJECT_API_KEY` and `POSTHOG_HOST`.
2. Monitor:
   - API 5xx rate
   - redirect latency on `/api/download`
   - DB error rate in event logging
   - GitHub API throttling

## 6. Operational guardrails

1. Always publish installers via GitHub Releases before website rollout.
2. Use stable naming conventions for release assets so platform routing stays reliable.
3. Keep fallback manual links on `/download` for edge-case users.
