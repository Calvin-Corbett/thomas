import type { DownloadPlatform, ReleaseChannel } from "@/lib/types";

type DownloadMode = "auto" | "manual" | "github";

type ManualResolution = {
  url: string;
  releaseTag: string;
  assetName: string;
};

function normalizeMode(value: string | undefined): DownloadMode {
  if (value === "manual") return "manual";
  if (value === "github") return "github";
  return "auto";
}

function platformSuffix(platform: DownloadPlatform): string {
  if (platform === "windows") return "WINDOWS";
  if (platform === "macos") return "MACOS";
  return "LINUX";
}

function envKey(platform: DownloadPlatform, channel: ReleaseChannel): string {
  const suffix = platformSuffix(platform);
  if (channel === "beta") {
    return `THOMAS_DOWNLOAD_URL_${suffix}_BETA`;
  }
  return `THOMAS_DOWNLOAD_URL_${suffix}`;
}

function extractAssetName(url: string, platform: DownloadPlatform): string {
  try {
    const parsed = new URL(url);
    const name = parsed.pathname.split("/").filter(Boolean).pop();
    if (name) return name;
  } catch {
    // Ignore malformed URL parsing and fall back.
  }
  return `${platform}-download`;
}

export function getDownloadMode(): DownloadMode {
  return normalizeMode(process.env.THOMAS_DOWNLOAD_MODE);
}

export function resolveManualDownload(
  platform: DownloadPlatform,
  channel: ReleaseChannel,
): ManualResolution | null {
  const key = envKey(platform, channel);
  const url = process.env[key]?.trim();
  if (!url) return null;
  return {
    url,
    releaseTag: process.env.THOMAS_MANUAL_RELEASE_TAG ?? "manual",
    assetName: extractAssetName(url, platform),
  };
}
