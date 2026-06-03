import { NextRequest, NextResponse } from "next/server";
import { getRecentEventSummary } from "@/lib/db";
import { fetchReleases } from "@/lib/github";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const rateLimit = checkRateLimit(request, {
    keyPrefix: "site-metrics-overview",
    limit: 60,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const [eventSummary, releases] = await Promise.all([getRecentEventSummary(30), fetchReleases(20)]);

  const releaseDownloads = releases.reduce((total, release) => {
    const sum = release.assets.reduce((assetTotal, asset) => assetTotal + asset.download_count, 0);
    return total + sum;
  }, 0);

  const latest = releases[0];
  const latestReleaseDownloads = latest
    ? latest.assets.reduce((total, asset) => total + asset.download_count, 0)
    : 0;

  return NextResponse.json(
    {
      ok: true,
      generatedAt: new Date().toISOString(),
      github: {
        releaseCount: releases.length,
        totalAssetDownloads: releaseDownloads,
        latestReleaseTag: latest?.tag_name ?? null,
        latestReleaseAssetDownloads: latestReleaseDownloads,
      },
      web: {
        trackedIntentLast30Days: eventSummary.total,
        byPlatformLast30Days: eventSummary.byPlatform,
        byChannelLast30Days: eventSummary.byChannel,
      },
    },
    {
      headers: {
        "cache-control": "public, s-maxage=120, stale-while-revalidate=600",
      },
    },
  );
}
