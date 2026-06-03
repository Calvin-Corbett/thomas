import { createHash, randomUUID } from "crypto";
import { NextRequest, NextResponse } from "next/server";
import { captureDownloadIntent } from "@/lib/analytics";
import { logDownloadEvent } from "@/lib/db";
import { normalizeArch, normalizePlatform, pickAssetForPlatform } from "@/lib/download-routing";
import { fetchReleases, selectReleaseByChannel } from "@/lib/github";
import { getDownloadMode, resolveManualDownload } from "@/lib/manual-downloads";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";
import type { ReleaseChannel } from "@/lib/types";

export const runtime = "nodejs";

function normalizeChannel(raw: string): ReleaseChannel {
  return raw === "beta" ? "beta" : "stable";
}

function hashIp(ip: string): string {
  const salt = process.env.EVENT_HASH_SALT ?? (process.env.NODE_ENV === "production" ? "" : "thomas-site");
  if (!salt || !ip || ip === "unknown") {
    return "";
  }
  return createHash("sha256").update(`${salt}:${ip}`).digest("hex");
}

function isLocalHttpDownload(parsed: URL): boolean {
  return parsed.protocol === "http:" && ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname);
}

function safeExternalDownloadUrl(rawUrl: string, origin: string): string | null {
  try {
    const parsed = new URL(rawUrl, origin);
    if (parsed.protocol === "https:" || isLocalHttpDownload(parsed)) {
      return parsed.toString();
    }
  } catch {
    // Invalid download URLs are handled by falling back to the download page.
  }
  return null;
}

export async function GET(req: NextRequest) {
  const rateLimit = checkRateLimit(req, {
    keyPrefix: "site-download",
    limit: 90,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const params = req.nextUrl.searchParams;
  const platform = normalizePlatform(params.get("platform") ?? "windows");
  const channel = normalizeChannel(params.get("channel") ?? "stable");
  const arch = normalizeArch(params.get("arch") ?? "unknown");
  const source = params.get("source") ?? "website";
  const referrer = req.headers.get("referer") ?? "";
  const userAgent = req.headers.get("user-agent") ?? "";
  const forwarded = req.headers.get("x-forwarded-for") ?? "";
  const ip = forwarded.split(",")[0]?.trim() || "unknown";
  const mode = getDownloadMode();
  const manual = mode !== "github" ? resolveManualDownload(platform, channel) : null;
  const eventId = randomUUID();
  const ipHash = hashIp(ip);

  const redirectWithTracking = async (url: string, releaseTag: string, assetName: string) => {
    const redirectUrl = safeExternalDownloadUrl(url, req.nextUrl.origin);
    if (!redirectUrl) {
      return redirectToDownload("invalid-download-url");
    }
    await logDownloadEvent({
      eventId,
      platform,
      channel,
      arch,
      source,
      referrer,
      userAgent,
      ipHash,
      releaseTag,
      assetName,
    }).catch(() => {
      // Keep redirect path resilient even if storage fails.
    });

    await captureDownloadIntent({
      distinctId: ipHash ? ipHash.slice(0, 24) : eventId,
      platform,
      channel,
      releaseTag,
      assetName,
      source,
    });

    const response = NextResponse.redirect(redirectUrl, { status: 302 });
    response.headers.set("cache-control", "no-store");
    return response;
  };

  const redirectToDownload = (status: string) => {
    const fallbackUrl = new URL("/download", req.nextUrl.origin);
    fallbackUrl.searchParams.set("status", status);
    fallbackUrl.searchParams.set("platform", platform);
    fallbackUrl.searchParams.set("channel", channel);
    const response = NextResponse.redirect(fallbackUrl, { status: 302 });
    response.headers.set("cache-control", "no-store");
    return response;
  };

  if (manual) {
    return redirectWithTracking(manual.url, manual.releaseTag, manual.assetName);
  }

  if (mode === "manual") {
    return redirectToDownload("manual-not-configured");
  }

  const releases = await fetchReleases(30);
  const targetRelease = selectReleaseByChannel(releases, channel);
  if (!targetRelease) {
    return redirectToDownload("release-not-found");
  }

  const asset = pickAssetForPlatform(targetRelease.assets, platform, arch);
  if (!asset) {
    return redirectToDownload("asset-not-found");
  }

  return redirectWithTracking(asset.browser_download_url, targetRelease.tag_name, asset.name);
}
