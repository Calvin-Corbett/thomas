import { createHash, randomUUID } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { captureDownloadIntent } from "@/lib/analytics";
import { logDownloadEvent } from "@/lib/db";
import { normalizeArch, normalizePlatform, pickAssetForPlatform } from "@/lib/download-routing";
import { fetchReleases, selectReleaseByChannel } from "@/lib/github";
import type { ReleaseChannel } from "@/lib/types";

export const runtime = "nodejs";

function normalizeChannel(raw: string): ReleaseChannel {
  return raw === "beta" ? "beta" : "stable";
}

function hashIp(ip: string): string {
  const salt = process.env.EVENT_HASH_SALT ?? "thomas-site";
  return createHash("sha256").update(`${salt}:${ip}`).digest("hex");
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const platform = normalizePlatform(params.get("platform") ?? "windows");
  const channel = normalizeChannel(params.get("channel") ?? "stable");
  const arch = normalizeArch(params.get("arch") ?? "unknown");
  const source = params.get("source") ?? "website";
  const referrer = req.headers.get("referer") ?? "";
  const userAgent = req.headers.get("user-agent") ?? "";
  const forwarded = req.headers.get("x-forwarded-for") ?? "";
  const ip = forwarded.split(",")[0]?.trim() || "unknown";

  const releases = await fetchReleases(30);
  const targetRelease = selectReleaseByChannel(releases, channel);
  if (!targetRelease) {
    return NextResponse.json(
      {
        ok: false,
        error: "release_not_found",
        hint: "Set THOMAS_GITHUB_REPO=owner/repo and ensure releases exist.",
      },
      { status: 404 },
    );
  }

  const asset = pickAssetForPlatform(targetRelease.assets, platform, arch);
  if (!asset) {
    return NextResponse.json(
      {
        ok: false,
        error: "asset_not_found",
        release: targetRelease.tag_name,
        platform,
        availableAssets: targetRelease.assets.map((item) => item.name),
      },
      { status: 404 },
    );
  }

  const eventId = randomUUID();
  const ipHash = hashIp(ip);

  await logDownloadEvent({
    eventId,
    platform,
    channel,
    arch,
    source,
    referrer,
    userAgent,
    ipHash,
    releaseTag: targetRelease.tag_name,
    assetName: asset.name,
  }).catch(() => {
    // Keep redirect path resilient even if storage fails.
  });

  await captureDownloadIntent({
    distinctId: ipHash.slice(0, 24),
    platform,
    channel,
    releaseTag: targetRelease.tag_name,
    assetName: asset.name,
    source,
  });

  const response = NextResponse.redirect(asset.browser_download_url, { status: 302 });
  response.headers.set("cache-control", "no-store");
  return response;
}
