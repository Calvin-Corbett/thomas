"use client";

import { useEffect, useState } from "react";

type MetricsPayload = {
  ok: boolean;
  github: {
    releaseCount: number;
    totalAssetDownloads: number;
    latestReleaseTag: string | null;
    latestReleaseAssetDownloads: number;
  };
  web: {
    trackedIntentLast30Days: number;
  };
};

export function MetricsStrip() {
  const [metrics, setMetrics] = useState<MetricsPayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/metrics/overview", { cache: "no-store" })
      .then((res) => res.json())
      .then((payload: MetricsPayload) => {
        if (!cancelled) setMetrics(payload);
      })
      .catch(() => {
        if (!cancelled) setMetrics(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="metrics-grid" aria-label="Thomas website metrics">
      <article className="metric-card">
        <p className="metric-label">Tracked Download Intents (30d)</p>
        <p className="metric-value">{metrics?.web.trackedIntentLast30Days?.toLocaleString() ?? "..."}</p>
      </article>
      <article className="metric-card">
        <p className="metric-label">GitHub Asset Downloads (All Time)</p>
        <p className="metric-value">{metrics?.github.totalAssetDownloads?.toLocaleString() ?? "..."}</p>
      </article>
      <article className="metric-card">
        <p className="metric-label">Latest Release</p>
        <p className="metric-value">{metrics?.github.latestReleaseTag ?? "Not configured"}</p>
      </article>
    </section>
  );
}
