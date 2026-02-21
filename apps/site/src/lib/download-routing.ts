import type { DownloadPlatform, GitHubAsset } from "@/lib/types";

const WINDOWS_PATTERNS = [/windows/i, /win/i, /\.msi$/i, /\.exe$/i];
const MAC_PATTERNS = [/mac/i, /darwin/i, /\.dmg$/i, /\.pkg$/i, /osx/i];
const LINUX_PATTERNS = [/linux/i, /\.deb$/i, /\.rpm$/i, /\.appimage$/i, /\.tar\.gz$/i];

function scoreName(name: string, patterns: RegExp[]): number {
  return patterns.reduce((score, pattern) => (pattern.test(name) ? score + 1 : score), 0);
}

export function normalizePlatform(raw: string): DownloadPlatform {
  const value = raw.toLowerCase();
  if (value === "windows" || value === "win") return "windows";
  if (value === "mac" || value === "macos" || value === "darwin" || value === "osx") return "macos";
  return "linux";
}

export function normalizeArch(raw: string): string {
  const value = raw.toLowerCase();
  if (value.includes("arm64") || value.includes("aarch64")) return "arm64";
  if (value.includes("x64") || value.includes("amd64") || value.includes("x86_64")) return "x64";
  return "unknown";
}

export function pickAssetForPlatform(
  assets: GitHubAsset[],
  platform: DownloadPlatform,
  arch: string,
): GitHubAsset | null {
  const patterns =
    platform === "windows" ? WINDOWS_PATTERNS : platform === "macos" ? MAC_PATTERNS : LINUX_PATTERNS;
  const withScore = assets
    .map((asset) => {
      let score = scoreName(asset.name, patterns);
      if (arch !== "unknown" && asset.name.toLowerCase().includes(arch.toLowerCase())) {
        score += 2;
      }
      return { asset, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || b.asset.download_count - a.asset.download_count);

  return withScore.length > 0 ? withScore[0].asset : null;
}
