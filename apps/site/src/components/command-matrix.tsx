"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { CopyButton } from "@/components/copy-button";
import { StatusChip, type StatusType } from "@/components/status-chip";

export type CommandMatrixRow = {
  feature: string;
  depth: number;
  commandCount: number;
  status: StatusType;
  commands: string[];
  trimmed: number;
  malformed: number;
  duplicates: number;
  routeHint?: string;
};

type CommandMatrixProps = {
  rows: CommandMatrixRow[];
  lastValidatedAt: string;
  repoUrl?: string;
  labels?: Partial<MatrixLabels>;
};

type MatrixDetailsState = Record<string, boolean>;
type MatrixStatusFilter = "all" | "implemented" | "declared";

const matrixStatusFilters: Array<{ id: MatrixStatusFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "implemented", label: "Implemented" },
  { id: "declared", label: "Declared" },
];

type MatrixLabels = {
  summaryLine: string;
  totalCommandCount: string;
  lastValidated: string;
  showingFamilies: string;
  controlsTitle: string;
  controlsSubtitle: string;
  searchLabel: string;
  searchPlaceholder: string;
  searchAriaLabel: string;
  statusFilter: string;
  filterAll: string;
  filterImplemented: string;
  filterDeclared: string;
  compactMode: string;
  compactModeOn: string;
  collapseAll: string;
  expandAll: string;
  noFamilies: string;
  coverageIndicator: string;
  routePath: string;
  openRouteSource: string;
  subcommands: string;
  noSubcommands: string;
  coveragePlanned: string;
  coverageClean: string;
  coverageWithIssues: string;
  depthMetric: string;
  commandMetric: string;
  statusImplemented: string;
  statusPartial: string;
  statusPlanned: string;
};

const defaultLabels: MatrixLabels = {
  summaryLine: "{implemented} implemented / {declared} declared",
  totalCommandCount: "Total command count: {count}",
  lastValidated: "Last validated snapshot: {value}",
  showingFamilies: "Showing {visible} of {total} families.",
  controlsTitle: "Command matrix controls",
  controlsSubtitle: "Search, filter, and view mode",
  searchLabel: "Search families / commands",
  searchPlaceholder: "status, family, or command",
  searchAriaLabel: "Search command families and subcommands",
  statusFilter: "Status filter",
  filterAll: "All",
  filterImplemented: "Implemented",
  filterDeclared: "Declared",
  compactMode: "Compact mode",
  compactModeOn: "Compact mode: on",
  collapseAll: "Collapse all",
  expandAll: "Expand all",
  noFamilies: "No families match this search and filter.",
  coverageIndicator: "Coverage indicator",
  routePath: "Route path",
  openRouteSource: "Open route source",
  subcommands: "Subcommands",
  noSubcommands: "No subcommands detected in this snapshot.",
  coveragePlanned: "Not validated (implementation not present in this snapshot)",
  coverageClean: "Parser surface validated from snapshot",
  coverageWithIssues: "Validation surface contains {count} data-cleaning signals",
  depthMetric: "Depth {count}",
  commandMetric: "Commands {count}",
  statusImplemented: "Implemented",
  statusPartial: "Partial",
  statusPlanned: "Declared",
};

function formatLabel(template: string, values: Record<string, number | string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? ""));
}

function isDeclared(status: StatusType): boolean {
  return status !== "implemented";
}

function isRowMatch(row: CommandMatrixRow, normalizedQuery: string): boolean {
  if (!normalizedQuery) {
    return true;
  }
  const routePath = formatRoute(row.feature, row.routeHint);
  return (
    row.feature.toLowerCase().includes(normalizedQuery) ||
    routePath.toLowerCase().includes(normalizedQuery) ||
    row.commands.some((command) => `${row.feature} ${command}`.toLowerCase().includes(normalizedQuery))
  );
}

function formatRoute(feature: string, routeHint?: string) {
  return routeHint?.startsWith("/") ? routeHint : `/${feature}`;
}

function formatCommandCopy(feature: string, commands: string[]) {
  return commands.map((cmd) => `/thomas ${feature} ${cmd}`).join("\n");
}

function coverageLine(row: CommandMatrixRow, labels: MatrixLabels): string {
  if (row.status === "planned") {
    return labels.coveragePlanned;
  }
  const issueSignals = row.trimmed + row.malformed + row.duplicates;
  if (issueSignals === 0) {
    return labels.coverageClean;
  }
  return formatLabel(labels.coverageWithIssues, { count: issueSignals });
}

function getStatusLabel(status: StatusType, labels: MatrixLabels) {
  if (status === "implemented") {
    return labels.statusImplemented;
  }
  if (status === "partial") {
    return labels.statusPartial;
  }
  return labels.statusPlanned;
}

export function CommandMatrix({ rows, lastValidatedAt, repoUrl, labels: labelOverrides }: CommandMatrixProps) {
  const labels = { ...defaultLabels, ...labelOverrides };
  const [openRows, setOpenRows] = useState<MatrixDetailsState>({});
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<MatrixStatusFilter>("all");
  const [compactMode, setCompactMode] = useState(false);
  const [, startTransition] = useTransition();

  const sortedRows = useMemo(() => [...rows].sort((a, b) => a.feature.localeCompare(b.feature)), [rows]);
  const normalizedQuery = query.trim().toLowerCase();

  const filteredRows = useMemo(() => {
    return sortedRows.filter((row) => {
      if (statusFilter === "implemented" && row.status !== "implemented") {
        return false;
      }
      if (statusFilter === "declared" && row.status === "implemented") {
        return false;
      }
      return isRowMatch(row, normalizedQuery);
    });
  }, [normalizedQuery, sortedRows, statusFilter]);

  const summary = useMemo(() => {
    const implemented = rows.filter((row) => row.status === "implemented").length;
    const declared = rows.filter((row) => isDeclared(row.status)).length;
    const totalCommands = rows.reduce((total, row) => total + row.commandCount, 0);
    return {
      implemented,
      declared,
      totalCommands,
    };
  }, [rows]);

  const setAllRowsOpen = (open: boolean) => {
    if (!open) {
      setOpenRows({});
      return;
    }
    const next: MatrixDetailsState = {};
    for (const row of filteredRows) {
      next[row.feature] = true;
    }
    setOpenRows(next);
  };

  const setRowOpenState = (feature: string, open: boolean) => {
    setOpenRows((prev) => {
      const next = { ...prev };
      if (!open) {
        delete next[feature];
      } else {
        next[feature] = true;
      }
      return next;
    });
  };

  useEffect(() => {
    if (!compactMode) {
      return;
    }
    setOpenRows({});
  }, [compactMode]);

  return (
    <section className="matrix">
      <div className="matrix-summary">
        <p className="matrix-summary-line">
          {formatLabel(labels.summaryLine, {
            implemented: summary.implemented,
            declared: summary.declared,
          })}
        </p>
        <p className="matrix-summary-line">
          {formatLabel(labels.totalCommandCount, { count: summary.totalCommands })}
        </p>
        <p className="system-metric-line system-metric-note">
          {formatLabel(labels.lastValidated, {
            value: new Date(lastValidatedAt).toLocaleString(),
          })}
        </p>
        <p className="system-metric-line">
          {formatLabel(labels.showingFamilies, {
            visible: filteredRows.length,
            total: sortedRows.length,
          })}
        </p>
      </div>

      <details className="matrix-controls">
        <summary>
          <span>{labels.controlsTitle}</span>
          <span className="system-metric-line">{labels.controlsSubtitle}</span>
        </summary>
        <div className="matrix-controls-body">
          <label className="matrix-search">
            <span className="matrix-search-label" id="deep-dive-matrix-search-label">
              {labels.searchLabel}
            </span>
            <input
              id="deep-dive-matrix-search"
              type="text"
              className="matrix-search-input"
              value={query}
              onChange={(event) => {
                const next = event.currentTarget.value;
                startTransition(() => setQuery(next));
              }}
              placeholder={labels.searchPlaceholder}
              aria-label={labels.searchAriaLabel}
              aria-labelledby="deep-dive-matrix-search-label"
            />
          </label>

          <label className="matrix-filter-label">
            {labels.statusFilter}
            <select
              className="matrix-filter-select"
              value={statusFilter}
              onChange={(event) =>
                startTransition(() => setStatusFilter(event.target.value as MatrixStatusFilter))
              }
            >
              {matrixStatusFilters.map((filter) => (
                <option key={filter.id} value={filter.id}>
                  {filter.id === "all"
                    ? labels.filterAll
                    : filter.id === "implemented"
                      ? labels.filterImplemented
                      : labels.filterDeclared}
                </option>
              ))}
            </select>
          </label>

          <div className="matrix-button-group">
            <button
              type="button"
              className={`matrix-sort-button ${compactMode ? "active" : ""}`}
              onClick={() => startTransition(() => setCompactMode((current) => !current))}
            >
              {compactMode ? labels.compactModeOn : labels.compactMode}
            </button>
            <button
              type="button"
              className="matrix-sort-button"
              onClick={() => startTransition(() => setAllRowsOpen(false))}
            >
              {labels.collapseAll}
            </button>
            <button
              type="button"
              className="matrix-sort-button"
              onClick={() => startTransition(() => setAllRowsOpen(true))}
            >
              {labels.expandAll}
            </button>
          </div>
        </div>
      </details>

      <div className="matrix-list">
        {filteredRows.length === 0 ? (
          <p className="system-metric-line">{labels.noFamilies}</p>
        ) : (
          filteredRows.map((row) => {
            const routePath = formatRoute(row.feature, row.routeHint);
            const routeEvidenceLink = repoUrl
              ? `${repoUrl}/search?q=${encodeURIComponent(`\"${routePath}\" path:src`)}&type=code`
              : undefined;
            const copyText = formatCommandCopy(row.feature, row.commands);
            const isOpen = Boolean(openRows[row.feature]);
            const detailsOpen = isOpen && !compactMode;

            return (
              <details
                key={row.feature}
                className="matrix-card"
                open={detailsOpen}
                onToggle={(event) => {
                  const detail = event.currentTarget;
                  if (compactMode) {
                    detail.open = false;
                    setRowOpenState(row.feature, false);
                    return;
                  }
                  setRowOpenState(row.feature, detail.open);
                }}
              >
                <summary className="matrix-card-head">
                  <div className="matrix-card-title">
                    <p className="matrix-feature">/{row.feature}</p>
                    <StatusChip status={row.status} label={getStatusLabel(row.status, labels)} />
                  </div>
                  <div className="matrix-metrics">
                    <span className="matrix-metric">
                      {formatLabel(labels.depthMetric, { count: row.depth })}
                    </span>
                    <span className="matrix-metric">
                      {formatLabel(labels.commandMetric, { count: row.commandCount })}
                    </span>
                  </div>
                </summary>
                {detailsOpen ? (
                  <div className="matrix-card-body">
                    <p className="system-code-line">
                      {labels.coverageIndicator}: {coverageLine(row, labels)}
                    </p>
                    <div className="matrix-subcommand-block">
                      <p className="system-code-line">{labels.routePath}</p>
                      <p className="system-code">{routePath}</p>
                      {routeEvidenceLink ? (
                        <p className="system-metric-line">
                          <a className="text-link" href={routeEvidenceLink} target="_blank" rel="noreferrer">
                            {labels.openRouteSource}
                          </a>
                        </p>
                      ) : null}
                    </div>
                    <div className="matrix-subcommand-block">
                      <p className="system-code-line">{labels.subcommands}</p>
                      {row.commands.length === 0 ? (
                        <p className="system-metric-line">{labels.noSubcommands}</p>
                      ) : (
                        <>
                          <div className="matrix-subcommand-grid">
                            {row.commands.map((command) => (
                              <code key={`${row.feature}-${command}`} className="system-code">
                                /thomas {row.feature} {command}
                              </code>
                            ))}
                          </div>
                          <div className="matrix-copy-row">
                            <CopyButton text={copyText} />
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                ) : null}
              </details>
            );
          })
        )}
      </div>
    </section>
  );
}
