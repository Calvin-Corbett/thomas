import postgres from "postgres";
import type { DownloadEvent } from "@/lib/types";

const connectionString = process.env.DATABASE_URL;
const sql = connectionString
  ? postgres(connectionString, {
      max: 10,
      idle_timeout: 20,
      connect_timeout: 10,
    })
  : null;

export async function logDownloadEvent(event: DownloadEvent): Promise<void> {
  if (!sql) return;
  await sql`
    insert into download_events (
      event_id,
      platform,
      channel,
      arch,
      release_tag,
      asset_name,
      source,
      referrer,
      user_agent,
      ip_hash
    ) values (
      ${event.eventId},
      ${event.platform},
      ${event.channel},
      ${event.arch},
      ${event.releaseTag},
      ${event.assetName},
      ${event.source},
      ${event.referrer},
      ${event.userAgent},
      ${event.ipHash}
    )
    on conflict (event_id) do nothing
  `;
}

export async function getRecentEventSummary(days = 30): Promise<{
  total: number;
  byPlatform: Record<string, number>;
  byChannel: Record<string, number>;
}> {
  if (!sql) {
    return { total: 0, byPlatform: {}, byChannel: {} };
  }

  const totalRows = await sql<{ total: number }[]>`
    select count(*)::int as total
    from download_events
    where created_at >= now() - make_interval(days => ${days})
  `;

  const platformRows = await sql<{ platform: string; total: number }[]>`
    select platform, count(*)::int as total
    from download_events
    where created_at >= now() - make_interval(days => ${days})
    group by platform
  `;

  const channelRows = await sql<{ channel: string; total: number }[]>`
    select channel, count(*)::int as total
    from download_events
    where created_at >= now() - make_interval(days => ${days})
    group by channel
  `;

  const byPlatform: Record<string, number> = {};
  for (const row of platformRows) {
    byPlatform[row.platform] = row.total;
  }

  const byChannel: Record<string, number> = {};
  for (const row of channelRows) {
    byChannel[row.channel] = row.total;
  }

  return {
    total: totalRows[0]?.total ?? 0,
    byPlatform,
    byChannel,
  };
}
