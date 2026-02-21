export type ReleaseChannel = "stable" | "beta";

export type DownloadPlatform = "windows" | "macos" | "linux";

export type DownloadEvent = {
  eventId: string;
  platform: DownloadPlatform;
  channel: ReleaseChannel;
  arch: string;
  source: string;
  referrer: string;
  userAgent: string;
  ipHash: string;
  releaseTag: string;
  assetName: string;
};

export type GitHubAsset = {
  name: string;
  browser_download_url: string;
  download_count: number;
  size: number;
  digest?: string;
};

export type GitHubRelease = {
  id: number;
  tag_name: string;
  name: string;
  prerelease: boolean;
  draft: boolean;
  body: string;
  published_at: string;
  created_at: string;
  html_url: string;
  assets: GitHubAsset[];
};
