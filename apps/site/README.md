# Thomas Public Website

Production-grade website for non-technical users:

- one-click download
- update/changelog feed
- public journey/video page
- support page
- scalable download-intent tracking

## Stack

- Next.js App Router
- GitHub Releases as installer source of truth
- Local update feed fallback when GitHub is not connected yet
- Postgres for download-intent event logging
- Optional PostHog server-side capture

## Run locally

```bash
cd apps/site
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

## Required env

- One of these two setup paths:
  - website-first/manual: set `THOMAS_DOWNLOAD_URL_WINDOWS`, `THOMAS_DOWNLOAD_URL_MACOS`, `THOMAS_DOWNLOAD_URL_LINUX`
  - GitHub-driven: set `THOMAS_GITHUB_REPO=owner/repo`

## Optional env

- `GITHUB_TOKEN`: raises GitHub API rate limits
- `THOMAS_DOWNLOAD_MODE`: `auto` (default), `manual`, or `github`
- `THOMAS_DOWNLOAD_URL_WINDOWS_BETA`, `THOMAS_DOWNLOAD_URL_MACOS_BETA`, `THOMAS_DOWNLOAD_URL_LINUX_BETA`
- `THOMAS_MANUAL_RELEASE_TAG`: label used in tracked events when using manual URLs
- `DATABASE_URL`: enables download intent persistence in Postgres
- `EVENT_HASH_SALT`: salt for anonymized IP hashing
- `POSTHOG_PROJECT_API_KEY`: enables server-side event forwarding
- `POSTHOG_HOST`: defaults to `https://us.i.posthog.com`
- `SITE_URL`: canonical site URL for metadata

## Database setup

Run this migration on your Postgres instance:

- `apps/site/sql/001_download_events.sql`

Without `DATABASE_URL`, the site still works; it just skips event persistence.

## Download tracking flow

1. User clicks download button.
2. Website calls `GET /api/download`.
3. Route resolves manual URL or latest GitHub release asset (based on `THOMAS_DOWNLOAD_MODE`).
4. Route logs intent event (if DB configured).
5. Route redirects (`302`) to the resolved installer URL.

## Pages

- `/` home
- `/download` download and platform picker
- `/updates` changelog feed from GitHub releases
- `/journey` YouTube journey page
- `/support` FAQ/support

## Metrics endpoint

- `GET /api/metrics/overview`
  - GitHub asset download totals
  - tracked website download intents (30 days)

## Deployment

### Vercel

1. Import `apps/site` as the project root.
2. Set env vars in project settings.
3. Deploy.

### Cloudflare Pages

Use Next.js support and set build root to `apps/site`.
Set env vars in Pages project settings.

## Runbook

See `apps/site/DEPLOYMENT.md` for a production scaling checklist.

## Website-first mode (no GitHub yet)

1. Set `THOMAS_DOWNLOAD_MODE=manual`.
2. Set `THOMAS_DOWNLOAD_URL_WINDOWS`, `THOMAS_DOWNLOAD_URL_MACOS`, `THOMAS_DOWNLOAD_URL_LINUX`.
3. Launch. The updates page will use local fallback entries until GitHub is connected.
