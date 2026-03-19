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

function hasRealData(metrics: MetricsPayload): boolean {
  return (
    metrics.github.totalAssetDownloads > 0 ||
    metrics.web.trackedIntentLast30Days > 0 ||
    metrics.github.latestReleaseTag !== null
  );
}

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

  if (!metrics || !hasRealData(metrics)) {
    return null;
  }

  return (
    <section aria-label="Thomas website metrics">
      <div className="metrics-grid">
        <article className="metric-card">
          <p className="metric-label">Download Intents (30d)</p>
          <p className="metric-value">{metrics.web.trackedIntentLast30Days.toLocaleString()}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">GitHub Downloads (All Time)</p>
          <p className="metric-value">{metrics.github.totalAssetDownloads.toLocaleString()}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Latest Release</p>
          <p className="metric-value">{metrics.github.latestReleaseTag ?? "Unavailable"}</p>
        </article>
      </div>
    </section>
  );
}
