import Link from "next/link";
import type { ReactNode } from "react";
import { CLI_COMPARISON_ROWS, CLIComparisonRow, COMPARISON_META } from "@/lib/featureComparisonData";

const openclawRepository = COMPARISON_META.openclawRepo;
const openclawCommit = COMPARISON_META.openclawCommit;
const openclawCommitShort = openclawCommit.slice(0, 7);

const sortedRows = [...CLI_COMPARISON_ROWS].sort((a, b) => a.feature.localeCompare(b.feature));
const totals = {
  total: sortedRows.length,
  thomasPresent: sortedRows.filter((row) => row.thomasPresent).length,
  openclawPresent: sortedRows.filter((row) => row.openclawPresent).length,
  shared: sortedRows.filter((row) => row.thomasPresent && row.openclawPresent).length,
  thomasOnly: sortedRows.filter((row) => row.thomasPresent && !row.openclawPresent).length,
  openclawOnly: sortedRows.filter((row) => row.openclawPresent && !row.thomasPresent).length,
};

const thomasOnlyRows = sortedRows.filter((row) => row.thomasPresent && !row.openclawPresent).map((row) => row.feature);
const openclawOnlyRows = sortedRows.filter((row) => row.openclawPresent && !row.thomasPresent).map((row) => row.feature);
const sharedRows = sortedRows.filter((row) => row.thomasPresent && row.openclawPresent).map((row) => row.feature);

function winnerLabel(row: CLIComparisonRow): { className: string; text: string } {
  if (row.thomasPresent && !row.openclawPresent) {
    return { className: "winner-chip winner-chip-thomas", text: "Thomas only" };
  }
  if (row.openclawPresent && !row.thomasPresent) {
    return { className: "winner-chip winner-chip-openclaw", text: "OpenClaw only" };
  }
  if (row.thomasDepth > row.openclawDepth) {
    return { className: "winner-chip winner-chip-thomas", text: "Thomas deeper" };
  }
  if (row.openclawDepth > row.thomasDepth) {
    return { className: "winner-chip winner-chip-openclaw", text: "OpenClaw deeper" };
  }
  return { className: "winner-chip winner-chip-tie", text: "Tie / parity" };
}

function statusLabel(present: boolean): string {
  return present ? "present" : "not present";
}

function compareDepth(row: CLIComparisonRow): string {
  if (!row.thomasPresent || !row.openclawPresent) {
    return "not comparable";
  }
  return `${row.thomasDepth} vs ${row.openclawDepth}`;
}

function showChildren(commands: string[]): string {
  if (commands.length === 0) {
    return "none";
  }
  return commands.slice(0, 12).join(", ");
}

function showChildrenLong(commands: string[]): ReactNode {
  if (commands.length === 0) {
    return <p className="feature-metric-line">no child commands</p>;
  }
  return (
    <ul className="owner-feature-list">
      {commands.map((item) => (
        <li key={item} className="owner-feature-item">
          <code>{item}</code>
        </li>
      ))}
    </ul>
  );
}

export default function DeepDivePage() {
  return (
    <section className="section-shell home-plain-shell">
      <p className="eyebrow">Deep Dive</p>
      <h1 className="page-title">Thomas vs OpenClaw - Feature Comparison</h1>
      <p className="page-intro">
        This page is the nerdy part: a structured command-surface comparison with evidence pointers and per-feature detail.
        The homepage keeps the story simple; this section keeps the audit explicit.
      </p>
      <div className="alert-note alert-note-critical">
        Warning: Thomas was vibe-coded in a fast, 14-day build run by a builder without formal software engineering education.
        This is intentionally explicit source context, not a badge: it means the implementation deserves full testing and
        independent verification before mission-critical use.
      </div>

      <section className="section-shell home-plain-shell" id="overview">
        <div className="home-section-head">
          <p className="eyebrow">Provenance</p>
          <h2>What this was tested against</h2>
        </div>
        <p className="deep-metric-copy">
          OpenClaw reference snapshot for this compare: commit{" "}
          <a href={`${openclawRepository}/commit/${openclawCommit}`} target="_blank" rel="noreferrer">
            <code>{openclawCommitShort}</code>
          </a>{" "}
          from{" "}
          <a href={`${openclawRepository}/tree/main`} target="_blank" rel="noreferrer">
            openclaw/main
          </a>{" "}
          (snapshot date {COMPARISON_META.suiteDateUtc}).
        </p>
        <div className="deep-win-grid owner-columns">
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">Total top-level features</h3>
            <p className="feature-inventory-count">{totals.total}</p>
            <p className="feature-inventory-note">Total root command entries in this extracted comparison set.</p>
          </article>
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">In both systems</h3>
            <p className="feature-inventory-count">{totals.shared}</p>
            <p className="feature-inventory-note">Both expose this command at top-level.</p>
          </article>
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">Thomas-only</h3>
            <p className="feature-inventory-count">{totals.thomasOnly}</p>
            <p className="feature-inventory-note">Thomas has the command and OpenClaw does not.</p>
          </article>
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">OpenClaw-only</h3>
            <p className="feature-inventory-count">{totals.openclawOnly}</p>
            <p className="feature-inventory-note">OpenClaw has the command and Thomas does not.</p>
          </article>
        </div>
      </section>

      <section className="section-shell home-plain-shell" id="ownership">
        <div className="home-section-head">
          <p className="eyebrow">Ownership split</p>
          <h2>Who owns what</h2>
        </div>
        <div className="deep-win-matrix">
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">Shared command surface</h3>
            <ul className="owner-feature-list">
              {sharedRows.map((row) => (
                <li key={`shared-${row}`} className="owner-feature-item">
                  {row}
                </li>
              ))}
            </ul>
          </article>
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">Thomas-only</h3>
            <ul className="owner-feature-list">
              {thomasOnlyRows.map((row) => (
                <li key={`thomas-${row}`} className="owner-feature-item">
                  {row}
                </li>
              ))}
            </ul>
          </article>
          <article className="feature-inventory-card">
            <h3 className="feature-inventory-title">OpenClaw-only</h3>
            <ul className="owner-feature-list">
              {openclawOnlyRows.map((row) => (
                <li key={`openclaw-${row}`} className="owner-feature-item">
                  {row}
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      <section className="section-shell home-plain-shell" id="feature-matrix">
        <div className="home-section-head">
          <p className="eyebrow">Feature-by-feature</p>
          <h2>Complete matrix with raw depth values</h2>
          <p>
            Depth is measured as number of tracked subcommand leaves in the extracted schema. It is a structural breadth/depth
            signal, not a quality score.
          </p>
        </div>

        <div className="feature-comparison-wrap">
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Thomas</th>
                <th>OpenClaw</th>
                <th>Depth (Thomas vs OpenClaw)</th>
                <th>Winner</th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row) => {
                const winner = winnerLabel(row);
                return (
                  <tr key={row.feature}>
                    <th scope="row">
                      <p className="feature-title-row">
                        <span className="feature-id">{row.feature}</span>
                      </p>
                    </th>
                    <td>
                      <p className="feature-metric-line">
                        Status: <strong>{statusLabel(row.thomasPresent)}</strong>
                      </p>
                      <p className="feature-metric-line">Subcommands: {showChildren(row.thomasChildren)}</p>
                      <details>
                        <summary className="text-link">full Thomas command list</summary>
                        {showChildrenLong(row.thomasChildren)}
                      </details>
                    </td>
                    <td>
                      <p className="feature-metric-line">
                        Status: <strong>{statusLabel(row.openclawPresent)}</strong>
                      </p>
                      <p className="feature-metric-line">Subcommands: {showChildren(row.openclawChildren)}</p>
                      <details>
                        <summary className="text-link">full OpenClaw command list</summary>
                        {showChildrenLong(row.openclawChildren)}
                      </details>
                    </td>
                    <td>
                      <p className="feature-metric-line">{compareDepth(row)}</p>
                      <p className="feature-metric-line">
                        Thomas nodes: <code>{row.thomasDepth}</code>, OpenClaw nodes: <code>{row.openclawDepth}</code>
                      </p>
                    </td>
                    <td>
                      <p>
                        <span className={winner.className}>{winner.text}</span>
                      </p>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section-shell home-plain-shell" id="methodology">
        <div className="home-section-head">
          <p className="eyebrow">Method</p>
          <h2>How this comparison was built</h2>
        </div>
        <div className="deep-win-grid">
          <article className="deep-metric">
            <h3 className="deep-metric-title">Scope</h3>
            <p className="deep-metric-copy">
              This matrix compares command-surface coverage and subcommand shape from a fixed extract file. It is strong for
              feature breadth checks, weak for runtime quality assertions.
            </p>
          </article>
          <article className="deep-metric">
            <h3 className="deep-metric-title">What is not measured</h3>
            <p className="deep-metric-copy">
            This page does not claim runtime throughput, fault tolerance, or UX latency outcomes by itself. Those should come from
            benchmark and release evidence.
            </p>
          </article>
          <article className="deep-metric">
            <h3 className="deep-metric-title">How to use this</h3>
            <p className="deep-metric-copy">
              If a command appears in Thomas-only, inspect release notes for intent and safety behavior. If shared, compare
              implementation depth and child command list before assuming parity.
            </p>
          </article>
        </div>
      </section>

      <section className="section-shell home-plain-shell">
        <div className="deep-callout">
          <p className="deep-card-title">Audit-ready walk-through</p>
          <p className="deep-card-text">
            If you are reviewing this page, treat this as the verification path: baseline data, then winner labels, then raw child
            command lists, then changelog entries, then release artifacts. This keeps the comparison falsifiable instead of
            marketing-driven.
          </p>
        </div>
      </section>

      <section className="section-shell home-plain-shell">
        <div className="deep-callout">
          <h3 className="deep-card-title">Bottom line</h3>
          <p className="deep-card-text">
            Thomas is positioned as a more accessible workflow platform while OpenClaw remains a strong technical baseline.
            The difference is not just command count; it is how much of that command surface is surfaced for non-technical users
            as practical, persistent workflows.
          </p>
          <p className="deep-card-text">
            For people wanting a build trail, return to{" "}
            <Link href="/" className="text-link">
              homepage
            </Link>{" "}
            for concise outcomes, then use this page for implementation-level confirmation.
          </p>
        </div>
      </section>

      <section className="section-shell home-plain-shell">
        <div className="home-section-head">
          <p className="eyebrow">Links</p>
          <h2>Reference points</h2>
        </div>
        <div className="plain-comparison-grid">
          <article className="plain-comparison-card">
            <p className="plain-comparison-question">OpenClaw repository</p>
            <div className="plain-comparison-points">
              <p>
                <a href={openclawRepository} target="_blank" rel="noreferrer">
                  {openclawRepository}
                </a>
              </p>
              <p>
                Commit:{" "}
                <a href={`${openclawRepository}/commit/${openclawCommit}`} target="_blank" rel="noreferrer">
                  <code>{openclawCommitShort}</code>
                </a>
              </p>
            </div>
          </article>
          <article className="plain-comparison-card">
            <p className="plain-comparison-question">Source used here</p>
            <div className="plain-comparison-points">
              <p>
                <code>{COMPARISON_META.source}</code> (local project payload)
              </p>
              <p>Snapshot date: {COMPARISON_META.suiteDateUtc}</p>
              <p>
                Source file: <code>{COMPARISON_META.source}</code> in repository root
              </p>
            </div>
          </article>
        </div>
      </section>
    </section>
  );
}



