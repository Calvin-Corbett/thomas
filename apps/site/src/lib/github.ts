import { getRepoSlug } from "@/lib/site-config";
import type { GitHubRelease, ReleaseChannel } from "@/lib/types";

const GITHUB_API_BASE = "https://api.github.com";

function getRepoParts() {
  const slug = getRepoSlug();
  const [owner, repo] = slug.split("/");
  if (!owner || !repo) {
    return null;
  }
  return { owner, repo };
}

export async function fetchReleases(limit = 20): Promise<GitHubRelease[]> {
  const parts = getRepoParts();
  if (!parts) {
    return [];
  }

  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "User-Agent": "thomas-site",
  };

  if (process.env.GITHUB_TOKEN) {
    headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  }

  try {
    const res = await fetch(
      `${GITHUB_API_BASE}/repos/${parts.owner}/${parts.repo}/releases?per_page=${Math.min(limit, 100)}`,
      {
        headers,
        next: { revalidate: 300 },
      },
    );
    if (!res.ok) {
      return [];
    }

    const data = (await res.json()) as GitHubRelease[];
    if (!Array.isArray(data)) {
      return [];
    }
    return data.filter((release) => release && !release.draft);
  } catch {
    return [];
  }
}

export function selectReleaseByChannel(releases: GitHubRelease[], channel: ReleaseChannel): GitHubRelease | null {
  if (releases.length === 0) return null;

  if (channel === "beta") {
    const beta = releases.find((release) => release.prerelease);
    if (beta) return beta;
  }

  const stable = releases.find((release) => !release.prerelease);
  if (stable) return stable;

  return releases[0];
}

export function summarizeReleaseBody(body: string, maxChars = 340): string {
  const compact = body.replace(/\r/g, "").trim();
  if (compact.length <= maxChars) return compact;
  return `${compact.slice(0, maxChars - 1)}...`;
}

export function buildReleaseNotesUrl(tag: string): string {
  const parts = getRepoParts();
  if (!parts) return "";
  return `https://github.com/${parts.owner}/${parts.repo}/releases/tag/${tag}`;
}
