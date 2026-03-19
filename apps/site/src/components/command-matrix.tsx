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
};

type MatrixDetailsState = Record<string, boolean>;
type MatrixStatusFilter = "all" | "implemented" | "declared";

const matrixStatusFilters: Array<{ id: MatrixStatusFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "implemented", label: "Implemented" },
  { id: "declared", label: "Declared" },
];

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

function coverageLine(row: CommandMatrixRow): string {
  if (row.status === "planned") {
    return "Not validated (implementation not present in this snapshot)";
  }
  const issueSignals = row.trimmed + row.malformed + row.duplicates;
  if (issueSignals === 0) {
    return "Parser surface validated from snapshot";
  }
  return `Validation surface contains ${issueSignals} data-cleaning signals`;
}

export function CommandMatrix({ rows, lastValidatedAt, repoUrl }: CommandMatrixProps) {
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
          {summary.implemented} implemented / {summary.declared} declared
        </p>
        <p className="matrix-summary-line">Total command count: {summary.totalCommands}</p>
        <p className="system-metric-line system-metric-note">
          Last validated snapshot: {new Date(lastValidatedAt).toLocaleString()}
        </p>
        <p className="system-metric-line">
          Showing {filteredRows.length} of {sortedRows.length} families.
        </p>
      </div>

      <details className="matrix-controls">
        <summary>
          <span>Command matrix controls</span>
          <span className="system-metric-line">Search, filter, and view mode</span>
        </summary>
        <div className="matrix-controls-body">
          <label className="matrix-search">
            <span className="matrix-search-label" id="deep-dive-matrix-search-label">
              Search families / commands
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
              placeholder="status, family, or command"
              aria-label="Search command families and subcommands"
              aria-labelledby="deep-dive-matrix-search-label"
            />
          </label>

          <label className="matrix-filter-label">
            Status filter
            <select
              className="matrix-filter-select"
              value={statusFilter}
              onChange={(event) =>
                startTransition(() => setStatusFilter(event.target.value as MatrixStatusFilter))
              }
            >
              {matrixStatusFilters.map((filter) => (
                <option key={filter.id} value={filter.id}>
                  {filter.label}
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
              {compactMode ? "Compact mode: on" : "Compact mode"}
            </button>
            <button
              type="button"
              className="matrix-sort-button"
              onClick={() => startTransition(() => setAllRowsOpen(false))}
            >
              Collapse all
            </button>
            <button
              type="button"
              className="matrix-sort-button"
              onClick={() => startTransition(() => setAllRowsOpen(true))}
            >
              Expand all
            </button>
          </div>
        </div>
      </details>

      <div className="matrix-list">
        {filteredRows.length === 0 ? (
          <p className="system-metric-line">No families match this search and filter.</p>
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
                    <StatusChip status={row.status} />
                  </div>
                  <div className="matrix-metrics">
                    <span className="matrix-metric">Depth {row.depth}</span>
                    <span className="matrix-metric">Commands {row.commandCount}</span>
                  </div>
                </summary>
                {detailsOpen ? (
                  <div className="matrix-card-body">
                    <p className="system-code-line">Coverage indicator: {coverageLine(row)}</p>
                    <div className="matrix-subcommand-block">
                      <p className="system-code-line">Route path</p>
                      <p className="system-code">{routePath}</p>
                      {routeEvidenceLink ? (
                        <p className="system-metric-line">
                          <a className="text-link" href={routeEvidenceLink} target="_blank" rel="noreferrer">
                            Open route source
                          </a>
                        </p>
                      ) : null}
                    </div>
                    <div className="matrix-subcommand-block">
                      <p className="system-code-line">Subcommands</p>
                      {row.commands.length === 0 ? (
                        <p className="system-metric-line">No subcommands detected in this snapshot.</p>
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
