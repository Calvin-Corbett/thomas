export type LocalUpdate = {
  id: string;
  tag: string;
  name: string;
  prerelease: boolean;
  publishedAt: string;
  notes: string;
  htmlUrl: string;
  totalAssetDownloads: number;
};

export const localUpdates: LocalUpdate[] = [
  {
    id: "local-001",
    tag: "v0.11.39",
    name: "Thomas Website Launch",
    prerelease: false,
    publishedAt: "2026-02-21T00:00:00Z",
    notes:
      "Initial public website launch with one-click downloads, release feed support, and download tracking API.",
    htmlUrl: "/updates",
    totalAssetDownloads: 0,
  },
  {
    id: "local-002",
    tag: "v0.11.40-beta",
    name: "Beta Channel Prep",
    prerelease: true,
    publishedAt: "2026-02-21T00:00:00Z",
    notes: "Prepared beta channel flow and release ingestion path for future GitHub integration.",
    htmlUrl: "/updates",
    totalAssetDownloads: 0,
  },
];
