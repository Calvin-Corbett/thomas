import { NextRequest, NextResponse } from "next/server";
import { fetchReleases, summarizeReleaseBody } from "@/lib/github";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;
  const limit = Number(params.get("limit") ?? "12");
  const includePrerelease = params.get("channel") === "beta";

  const releases = await fetchReleases(Math.max(1, Math.min(limit, 30)));
  const filtered = includePrerelease ? releases : releases.filter((release) => !release.prerelease);

  const payload = filtered.map((release) => ({
    id: release.id,
    tag: release.tag_name,
    name: release.name || release.tag_name,
    prerelease: release.prerelease,
    publishedAt: release.published_at,
    notes: summarizeReleaseBody(release.body || "No release notes were published for this release."),
    htmlUrl: release.html_url,
    assets: release.assets.map((asset) => ({
      name: asset.name,
      downloads: asset.download_count,
      size: asset.size,
      digest: asset.digest ?? null,
      url: asset.browser_download_url,
    })),
    totalAssetDownloads: release.assets.reduce((total, asset) => total + asset.download_count, 0),
  }));

  return NextResponse.json(
    {
      ok: true,
      count: payload.length,
      releases: payload,
    },
    {
      headers: {
        "cache-control": "public, s-maxage=300, stale-while-revalidate=900",
      },
    },
  );
}
