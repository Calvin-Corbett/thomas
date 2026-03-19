import { localUpdates } from "@/content/local-updates";
import { getDefaultChannel } from "@/lib/site-config";
import { fetchReleases, summarizeReleaseBody } from "@/lib/github";
import type { GitHubRelease } from "@/lib/types";
import { safeLoad } from "@/lib/safe-load";

export type SiteReleaseAsset = {
  name: string;
  downloads: number;
  size: number;
  digest: string | null;
  url: string;
};

export type SiteRelease = {
  id: string;
  tag: string;
  name: string;
  prerelease: boolean;
  publishedAt: string;
  notes: string;
  htmlUrl: string;
  totalAssetDownloads: number;
  source: "github" | "local";
  assets: SiteReleaseAsset[];
};

type ReleaseFeedOptions = {
  limit?: number;
  channel?: "stable" | "beta";
  includePrerelease?: boolean;
};

export type SiteReleaseFeedSource = "github" | "local" | "none";

export type SiteReleaseFeedState = {
  releases: SiteRelease[];
  source: SiteReleaseFeedSource;
  status: "loaded" | "cached" | "empty";
};

function fromGitHub(release: GitHubRelease): SiteRelease {
  const assets = Array.isArray(release.assets) ? release.assets : [];
  return {
    id: String(release.id),
    tag: release.tag_name || "unknown",
    name: release.name || release.tag_name || "Unknown release",
    prerelease: Boolean(release.prerelease),
    publishedAt: release.published_at || new Date().toISOString(),
    notes: summarizeReleaseBody(release.body || "No release notes were published for this release."),
    htmlUrl: release.html_url || "",
    totalAssetDownloads: assets.reduce((sum, asset) => sum + (asset?.download_count ?? 0), 0),
    source: "github",
    assets: assets.map((asset) => ({
      name: asset?.name || "unknown-asset",
      downloads: asset?.download_count ?? 0,
      size: asset?.size ?? 0,
      digest: asset?.digest ?? null,
      url: asset?.browser_download_url || "",
    })),
  };
}

function fromLocalRelease(release: (typeof localUpdates)[number]): SiteRelease {
  return {
    id: release.id,
    tag: release.tag,
    name: release.name,
    prerelease: release.prerelease,
    publishedAt: release.publishedAt,
    notes: release.notes,
    htmlUrl: release.htmlUrl,
    totalAssetDownloads: release.totalAssetDownloads,
    source: "local",
    assets: [],
  };
}

function filterChannel(releases: SiteRelease[], channel: "stable" | "beta") {
  if (channel === "beta") {
    return releases;
  }
  return releases.filter((release) => !release.prerelease);
}

function getLocalFeed(channel: "stable" | "beta", includePrerelease: boolean) {
  return localUpdates
    .map(fromLocalRelease)
    .filter((release) => (includePrerelease ? true : !release.prerelease))
    .filter((release) => channel === "beta" || !release.prerelease);
}

function getGithubFeed(
  releases: GitHubRelease[],
  includePrerelease: boolean,
  channel: "stable" | "beta",
) {
  return releases
    .map(fromGitHub)
    .filter((release) => (includePrerelease ? true : !release.prerelease))
    .sort((a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime())
    .filter((release) => channel === "beta" || !release.prerelease);
}

function normalizeFeedOptions(options: ReleaseFeedOptions) {
  return {
    channel: options.channel ?? getDefaultChannel(),
    limit: Math.max(1, Math.min(options.limit ?? 12, 30)),
    includePrerelease: Boolean(options.includePrerelease),
  };
}

export async function getSiteReleaseFeedWithState(options: ReleaseFeedOptions = {}): Promise<SiteReleaseFeedState> {
  const { channel, limit, includePrerelease } = normalizeFeedOptions(options);

  const githubResult = await safeLoad(() => fetchReleases(30));
  const githubReleases = githubResult.ok ? githubResult.data : [];
  if (!githubResult.ok && process.env.NODE_ENV !== "production") {
    console.warn(`Release feed fetch failed: ${githubResult.error}`);
  }

  const githubFeed = getGithubFeed(githubReleases, includePrerelease, channel);

  if (githubFeed.length > 0) {
    return {
      releases: githubFeed.slice(0, limit),
      source: "github",
      status: "loaded",
    };
  }

  const localFeed = getLocalFeed(channel, includePrerelease);
  if (localFeed.length > 0) {
    return {
      releases: filterChannel(localFeed, channel).slice(0, limit),
      source: "local",
      status: "cached",
    };
  }

  return {
    releases: [],
    source: "none",
    status: "empty",
  };
}

export async function getSiteReleaseFeed(options: ReleaseFeedOptions = {}): Promise<SiteRelease[]> {
  const { releases } = await getSiteReleaseFeedWithState(options);
  return releases;
}

export async function getLatestSiteRelease(channel: "stable" | "beta" = getDefaultChannel()): Promise<SiteRelease | null> {
  const releases = await getSiteReleaseFeed({ limit: 1, channel });
  return releases[0] ?? null;
}
