"use client";

import { useMemo, useState } from "react";
import { SystemSection } from "@/components/system-section";
import type { SiteRelease } from "@/lib/site-release-data";
import { CalloutBlock } from "@/components/system-callout";

type UpdatesPageFeedProps = {
  releases: SiteRelease[];
  dataSourceLabel: string;
  showFailureNotice?: boolean;
  failureMessage?: string | null;
  labels: {
    releaseFeedUnavailable: string;
    noEntriesYet: string;
    noEntries: string;
    noEntriesBody: string;
    filters: string;
    version: string;
    allVersions: string;
    fromDate: string;
    toDate: string;
    releaseSource: string;
    noMatches: string;
    openArtifact: string;
    versionPrefix: string;
  };
};

function isInRange(dateIso: string, startDate: string, endDate: string) {
  const date = new Date(dateIso);
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  if (startDate && date < new Date(startDate)) {
    return false;
  }
  if (endDate && date > new Date(endDate)) {
    return false;
  }
  return true;
}

export function UpdatesPageFeed({
  releases,
  dataSourceLabel,
  showFailureNotice,
  failureMessage,
  labels,
}: UpdatesPageFeedProps) {
  const [versionFilter, setVersionFilter] = useState("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const versionOptions = useMemo(() => Array.from(new Set(releases.map((release) => release.tag))), [releases]);
  const filtered = useMemo(() => {
    return releases.filter((release) => {
      if (versionFilter !== "all" && release.tag !== versionFilter) {
        return false;
      }
      return isInRange(release.publishedAt, startDate, endDate);
    });
  }, [releases, versionFilter, startDate, endDate]);

  if (releases.length === 0) {
    if (failureMessage) {
      return (
        <>
          <CalloutBlock tone="warning" title={labels.releaseFeedUnavailable}>
            {failureMessage}
          </CalloutBlock>
          <p className="system-metric-line">{labels.noEntriesYet}</p>
        </>
      );
    }

    return (
      <>
        <CalloutBlock tone="warning" title={labels.noEntries}>
          {labels.noEntriesBody}
        </CalloutBlock>
      </>
    );
  }

  return (
    <>
      <SystemSection title={labels.filters}>
        <div className="system-metric-grid">
          <label className="system-metric-line">
            {labels.version}
            <select
              className="system-filter-select"
              value={versionFilter}
              onChange={(event) => setVersionFilter(event.target.value)}
            >
              <option value="all">{labels.allVersions}</option>
              {versionOptions.map((version) => (
                <option key={version} value={version}>
                  {version}
                </option>
              ))}
            </select>
          </label>
          <label className="system-metric-line">
            {labels.fromDate}
            <input
              className="system-filter-select"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </label>
          <label className="system-metric-line">
            {labels.toDate}
            <input
              className="system-filter-select"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </label>
        </div>
      </SystemSection>

      {showFailureNotice ? (
        <CalloutBlock tone="info" title={labels.releaseSource}>
          {dataSourceLabel}
        </CalloutBlock>
      ) : (
        <CalloutBlock tone="spec" title={labels.releaseSource}>
          {dataSourceLabel}
        </CalloutBlock>
      )}

      <div className="system-version-list">
        {filtered.length === 0 ? (
          <p className="system-metric-line">{labels.noMatches}</p>
        ) : (
          filtered.map((release) => (
            <details
              key={release.id}
              className="system-version-card"
              data-system-detail-id={`release-${release.id}`}
            >
              <summary className="system-version-head">
                <p className="system-section-title">{labels.versionPrefix} {release.tag}</p>
                <p className="system-metric-value">{new Date(release.publishedAt).toLocaleDateString()}</p>
              </summary>
              <div className="system-subsection">
                <p className="system-metric-line">{release.notes}</p>
                {release.htmlUrl ? (
                  <p className="system-metric-line">
                    <a className="text-link" href={release.htmlUrl} target="_blank" rel="noreferrer">
                      {labels.openArtifact}
                    </a>
                  </p>
                ) : null}
              </div>
            </details>
          ))
        )}
      </div>
    </>
  );
}
