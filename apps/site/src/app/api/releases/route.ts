import { NextRequest, NextResponse } from "next/server";
import { localUpdates } from "@/content/local-updates";
import { fetchReleases, summarizeReleaseBody } from "@/lib/github";

export const runtime = "nodejs";

type ApiAsset = {
  name: string;
  download_count: number;
  size: number;
  digest?: string | null;
  browser_download_url: string;
};

type ApiRelease = {
  id: number;
  tag_name: string;
  name: string;
  prerelease: boolean;
  published_at: string;
  body?: string;
  html_url: string;
  assets?: ApiAsset[];
};

type ApiPayload = {
  ok: boolean;
  count: number;
  releases: Array<{
    id: number | string;
    tag: string;
    name: string;
    prerelease: boolean;
    publishedAt: string;
    notes: string;
    htmlUrl: string;
    assets: Array<{
      name: string;
      downloads: number;
      size: number;
      digest: string | null;
      url: string;
}>;
    totalAssetDownloads: number;
    source: "github" | "local";
  }>;
};

function normalizeReleaseAssets(release: ApiRelease) {
  return Array.isArray(release.assets) ? release.assets : [];
}

function toPayloadRelease(release: ApiRelease) {
  const assets = normalizeReleaseAssets(release);
  return {
    id: release.id,
    tag: release.tag_name,
    name: release.name || release.tag_name,
    prerelease: release.prerelease,
    publishedAt: release.published_at,
    notes: summarizeReleaseBody(release.body || "No release notes were published for this release."),
    htmlUrl: release.html_url,
    assets: assets.map((asset) => ({
      name: asset.name,
      downloads: asset.download_count,
      size: asset.size,
      digest: asset.digest ?? null,
      url: asset.browser_download_url,
    })),
    totalAssetDownloads: assets.reduce((total, asset) => total + asset.download_count, 0),
    source: "github" as const,
  };
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const limit = Math.max(1, Math.min(Number(params.get("limit") ?? "12"), 30));
  const includePrerelease = params.get("channel") === "beta";

  try {
    const releases = await fetchReleases(30);
    const filtered = includePrerelease ? releases : releases.filter((release) => !release.prerelease);
    const payloadReleases =
      filtered.length > 0
        ? filtered
            .slice(0, limit)
            .map((release) => toPayloadRelease(release as ApiRelease))
        : localUpdates
            .filter((update) => (includePrerelease ? true : !update.prerelease))
            .slice(0, limit)
            .map((update) => ({
              ...update,
              assets: [],
              source: "local" as const,
            }));

    const payload: ApiPayload = {
      ok: true,
      count: payloadReleases.length,
      releases: payloadReleases,
    };

    return NextResponse.json(
      payload,
      {
        headers: {
          "cache-control": "public, s-maxage=300, stale-while-revalidate=900",
        },
      },
    );
  } catch {
    const payload: ApiPayload = {
      ok: false,
      count: 0,
      releases: [],
    };
    return NextResponse.json(payload, { status: 200 });
  }
}
