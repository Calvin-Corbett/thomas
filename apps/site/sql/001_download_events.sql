create table if not exists download_events (
  id bigserial primary key,
  event_id text not null unique,
  created_at timestamptz not null default now(),
  platform text not null,
  channel text not null,
  arch text,
  release_tag text,
  asset_name text,
  source text,
  referrer text,
  user_agent text,
  ip_hash text
);

create index if not exists idx_download_events_created_at on download_events (created_at desc);
create index if not exists idx_download_events_platform on download_events (platform);
create index if not exists idx_download_events_channel on download_events (channel);
