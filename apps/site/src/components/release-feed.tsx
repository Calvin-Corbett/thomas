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

export function ReleaseFeed({ limit = 8 }: { limit?: number }) {
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
        <p>Release data will appear after `THOMAS_GITHUB_REPO` is configured.</p>
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
                ? "Local update note"
                : `${release.totalAssetDownloads.toLocaleString()} asset downloads`}
            </span>
            <a href={release.htmlUrl} target="_blank" rel="noreferrer">
              Full notes
            </a>
          </div>
        </article>
      ))}
    </div>
  );
}
