"use client";

import { useEffect, useState } from "react";

type ReleaseItem = {
  id: number | string;
  tag: string;
  name: string;
  prerelease: boolean;
  publishedAt: string;
  notes: string;
  htmlUrl: string;
  totalAssetDownloads: number;
  source?: "github" | "local";
};

type ReleasesPayload = {
  ok: boolean;
  count: number;
  releases: ReleaseItem[];
};

type ReleaseFeedLabels = {
  empty: string;
  localNote: string;
  fullNotes: string;
  assetDownloadsSuffix: string;
};

export function ReleaseFeed({
  limit = 8,
  labels,
}: {
  limit?: number;
  labels: ReleaseFeedLabels;
}) {
  const [payload, setPayload] = useState<ReleasesPayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/releases?limit=${limit}`, { cache: "no-store" })
      .then((res) => res.json())
      .then((data: ReleasesPayload) => {
        if (!cancelled) setPayload(data);
      })
      .catch(() => {
        if (!cancelled) setPayload({ ok: false, count: 0, releases: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [limit]);

  if (!payload || payload.releases.length === 0) {
    return (
      <div className="empty-state">
        <p>{labels.empty}</p>
      </div>
    );
  }

  return (
    <div className="release-grid">
      {payload.releases.map((release) => (
        <article key={release.id} className="release-card">
          <div className="release-head">
            <p className="release-tag">{release.tag}</p>
            <p className="release-date">{new Date(release.publishedAt).toLocaleDateString()}</p>
          </div>
          <h3>{release.name}</h3>
          <p className="release-notes">{release.notes}</p>
          <div className="release-meta">
            <span>
              {release.source === "local"
                ? labels.localNote
                : `${release.totalAssetDownloads.toLocaleString()} ${labels.assetDownloadsSuffix}`}
            </span>
            <a href={release.htmlUrl} target="_blank" rel="noreferrer">
              {labels.fullNotes}
            </a>
          </div>
        </article>
      ))}
    </div>
  );
}
