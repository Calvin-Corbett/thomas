import type { Metadata } from "next";
import { CLI_COMPARISON_ROWS, type CLIComparisonRow } from "@/lib/featureComparisonData";
import { getRepoUrl } from "@/lib/site-config";
import { StatusChip, type StatusType } from "@/components/status-chip";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { CodeBlock } from "@/components/system-code-block";
import { CommandMatrix, type CommandMatrixRow } from "@/components/command-matrix";
import { CalloutBlock } from "@/components/system-callout";

export const metadata: Metadata = {
  title: "How Thomas Works",
  description: "Execution architecture, command contracts, and plugin boundaries for Thomas.",
};

const pipelineFlow = [
  "user request",
  "policy + trust gate",
  "plan generation",
  "tool execution + hook sequence",
  "result validation",
  "audit log",
  "response returned to caller",
].join(" -> ");

const sampleAuditLog = {
  requestId: "rq-2026-03-02-001",
  timestamp: "2026-03-02T01:09:04Z",
  route: "/v1/chat/completions",
  policy: "approved",
  commandFamily: "/status",
  result: "ok",
  elapsedMs: 214,
  hooks: ["before-model", "before-tool", "after-tool", "after-response"],
  trace: ["/api-gateway", "/planner", "/hooks", "/tool", "/validation", "/audit-log"],
  logFile: "/var/log/thomas/events.jsonl",
};

const sampleExecution = {
  userPrompt: "List repository status",
  plan: {
    family: "status",
    command: "status",
    policyGate: "ok",
    approvalState: "required",
  },
  execution: {
    output: {
      totalSteps: 6,
      exitCode: 0,
    },
    checks: {
      schemaValidation: true,
      policyGate: true,
      commandContract: true,
    },
  },
  artifacts: {
    auditId: "rq-2026-03-02-001",
    artifactPath: "/var/log/thomas/events.jsonl",
  },
};

const gatewayCurl = `curl -X POST https://127.0.0.1:8787/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer <local-token>" \\
  -d '{\\n  "model": "local-gpt",\\n  "messages": [{"role": "user", "content": "List repository status"}],\\n  "stream": false\\n}'`;

const gatewayStream = `event: response.started
data: {"id":"evt-01","type":"response.started","request_id":"rq-2026-03-02-001"}

event: tool.delta
data: {"id":"evt-01","type":"tool.delta","tool":"status","payload":{"phase":"running"}}

event: response.final
data: {"id":"evt-01","type":"response.final","status":"ok","request_id":"rq-2026-03-02-001"}`;

const gatewayResponse = `{
  "id": "cmp-102",
  "status": "ok",
  "model": "local-gpt",
  "request_id": "rq-2026-03-02-001",
  "usage": {
    "prompt_tokens": 14,
    "completion_tokens": 32
  }
}`;

const gatewayCLI = `thomas prompt "status"
thomas ask "List repository status"
thomas --help --json`;

const pluginArchitecture = `client
  |-- parser + policy gate
  |-- command planner
  |-- execution runtime
  \\-- audit sink
      |-- before-model hooks
      |-- before-tool hooks
      |-- tool.exec hooks
      |-- after-tool hooks
      \\-- after-response hooks`;

const pluginManifest = `{
  "name": "thomas-plugin-guard",
  "version": "0.1.0",
  "entry": "dist/index.js",
  "permissions": ["filesystem", "network:thomas-control"],
  "hooks": [
    "before-model",
    "before-tool",
    "after-tool",
    "after-response"
  ]
}`;

const pluginLifecycle = [
  "Install package",
  "Validate manifest and checksum",
  "Activate in registry",
  "Execute through protected path",
  "Deactivate + remove runtime state",
  "Uninstall package",
];

const pluginCommands = `thomas plugin install ./dist/thomas-plugin-guard.zip
thomas plugin validate thomas-plugin-guard
thomas plugin activate thomas-plugin-guard
thomas plugin run thomas-plugin-guard --diagnostic
thomas plugin deactivate thomas-plugin-guard
thomas plugin uninstall thomas-plugin-guard`;

const matrixSignals = [
  "Families with explicit command depth",
  "Coverage and evidence status per family",
  "Route/path traceability for execution artifacts",
];

const roadmap = [
  {
    id: "command-evidence-snapshots",
    title: "Command evidence snapshots",
    status: "implemented" as const,
    text: "Row-level coverage metadata is present for families and linked to source artifacts.",
  },
  {
    id: "gateway-contract-coverage",
    title: "Gateway contract coverage",
    status: "implemented" as const,
    text: "HTTP contracts and CLI calls share the same guard and validation surface.",
  },
  {
    id: "plugin-lifecycle-replay",
    title: "Plugin lifecycle replay",
    status: "planned" as const,
    text: "Next up: full install + policy-hook replay with trace replayability.",
  },
];

const nonGoals = [
  "Unbounded autonomous execution.",
  "Claims of universal API coverage without route evidence.",
  "Implicit trust without policy gates.",
];

const integritySamples = [
  {
    id: "integrity-audit",
    title: "Audit log example",
    metadata: "23 events processed - 214ms total",
    content: JSON.stringify(sampleAuditLog, null, 2),
    language: "json" as const,
  },
  {
    id: "integrity-execution-json",
    title: "Execution JSON example",
    metadata: "6 steps with schema checks",
    content: JSON.stringify(sampleExecution, null, 2),
    language: "json" as const,
  },
  {
    id: "integrity-flow",
    title: "Flow artifact",
    metadata: "Execution artifact path and route path",
    content: pipelineFlow,
    language: "text" as const,
  },
  {
    id: "integrity-gateway-parity",
    title: "Gateway parity evidence",
    metadata: "HTTP and CLI route contract parity",
    content: gatewayCLI,
    language: "text" as const,
  },
];

function normalizeCommand(command: string): string {
  return command.trim().replace(/\s+/g, " ").replace(/[()]/g, "");
}

function isValidCommand(command: string): boolean {
  return /^[a-z0-9][a-z0-9._:-]*$/i.test(command);
}

function analyzeFamily(row: CLIComparisonRow) {
  const sanitized: string[] = [];
  let trimmed = 0;
  let malformed = 0;
  let duplicates = 0;
  const seen = new Set<string>();

  for (const raw of row.thomasChildren) {
    const next = normalizeCommand(raw);
    if (next !== raw) {
      trimmed += 1;
    }
    if (!isValidCommand(next)) {
      malformed += 1;
      continue;
    }
    if (seen.has(next)) {
      duplicates += 1;
      continue;
    }
    seen.add(next);
    sanitized.push(next);
  }

  let status: StatusType;
  if (row.thomasDepth === 0 || row.thomasChildren.length === 0) {
    status = "planned";
  } else if (malformed > 0 || duplicates > 0) {
    status = "partial";
  } else {
    status = "implemented";
  }

  return { sanitized, trimmed, malformed, duplicates, status };
}

function buildMatrixRows() {
  try {
    const rows: CommandMatrixRow[] = CLI_COMPARISON_ROWS.filter((row) => row.thomasPresent)
      .map((row) => {
        const { sanitized, trimmed, malformed, duplicates, status } = analyzeFamily(row);
        return {
          feature: row.feature,
          depth: row.thomasDepth,
          commandCount: sanitized.length,
          status,
          commands: sanitized,
          trimmed,
          malformed,
          duplicates,
          routeHint: `/${row.feature}`,
        };
      })
      .sort((a, b) => a.feature.localeCompare(b.feature));

    return { rows, error: null as string | null };
  } catch (error) {
    return {
      rows: [] as CommandMatrixRow[],
      error: error instanceof Error ? error.message : "Matrix data could not be loaded.",
    };
  }
}

const matrixRowsData = buildMatrixRows();
const matrixRows = matrixRowsData.rows;

const matrixStats = {
  implemented: matrixRows.filter((row) => row.status === "implemented").length,
  declared: matrixRows.filter((row) => row.status !== "implemented").length,
  totalCommands: matrixRows.reduce((total, row) => total + row.commandCount, 0),
};

function localFirstSummary() {
  return `${matrixStats.implemented} implemented / ${matrixStats.declared} declared`;
}

export default function DeepDivePage() {
  const releasesUrl = getRepoUrl();
  const lastValidatedAt = "2026-03-02T01:09:04Z";

  return (
    <SystemPageShell
      eyebrow="Technical"
      title="How Thomas Works"
      versionLabel="v0.11.39"
      persistDetails={false}
    >
      <div className="system-content-narrow">
        <SystemSection title="How commands run">
          <div className="system-grid">
            <article className="system-metric-card">
              <p className="system-metric-title">Execution model</p>
              <p className="system-metric-note">
                Every request goes through planning, policy gates, and audit tracing before anything runs.
              </p>
            </article>
            <article className="system-metric-card">
              <p className="system-metric-title">Coverage</p>
              <p className="system-metric-note">
                Contract status: {localFirstSummary()}
                <br />
                Total command families: {matrixRows.length}
              </p>
              <p className="system-metric-line">Last validated: {new Date(lastValidatedAt).toLocaleString()}</p>
            </article>
            <article className="system-metric-card">
              <p className="system-metric-title">What we track</p>
              <ul className="system-bullets">
                {matrixSignals.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </article>
          </div>
          <details className="system-subsection" data-system-detail-id="execution-pipeline">
            <summary className="system-metric-title">Execution pipeline</summary>
            <CodeBlock title="pipeline" language="text">
              {pipelineFlow}
            </CodeBlock>
          </details>
        </SystemSection>

      <SystemSection title="Command family matrix" id="command-matrix">
        {matrixRowsData.error ? (
          <CalloutBlock tone="warning" title="Command matrix source issue">
            Command matrix entries could not be fully normalized: {matrixRowsData.error}
          </CalloutBlock>
        ) : null}
        <p className="system-metric-line">
          Source for command families:
          {releasesUrl ? (
            <a className="text-link" href={releasesUrl} target="_blank" rel="noreferrer">
                {" "}
                release repository
              </a>
            ) : null}
          </p>
          <CommandMatrix rows={matrixRows} lastValidatedAt={lastValidatedAt} repoUrl={releasesUrl || undefined} />
        </SystemSection>

        <SystemSection title="Integrity evidence" id="integrity">
          {integritySamples.map((sample) => (
            <details key={sample.id} className="system-subsection" data-system-detail-id={sample.id}>
              <summary className="system-metric-title">
                <span className="system-metric-title">{sample.title}</span>
                <span className="system-metric-line">{sample.metadata}</span>
              </summary>
              <CodeBlock title={sample.id} language={sample.language}>
                {sample.content}
              </CodeBlock>
            </details>
          ))}
        </SystemSection>

        <SystemSection title="Gateway contracts and CLI parity" id="gateway-contracts">
          <details className="system-subsection" data-system-detail-id="gateway-request">
            <summary className="system-metric-title">Non-stream request example</summary>
            <CodeBlock title="curl request" language="bash">
              {gatewayCurl}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="gateway-stream">
            <summary className="system-metric-title">Streaming event model</summary>
            <CodeBlock title="sse events" language="text">
              {gatewayStream}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="gateway-response">
            <summary className="system-metric-title">Non-stream response format</summary>
            <CodeBlock title="response.json" language="json">
              {gatewayResponse}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="gateway-cli">
            <summary className="system-metric-title">CLI parity check</summary>
            <CodeBlock title="CLI commands" language="bash">
              {gatewayCLI}
            </CodeBlock>
          </details>
        </SystemSection>

        <SystemSection title="Plugin execution boundary">
          <details className="system-subsection" data-system-detail-id="plugin-architecture">
            <summary className="system-metric-title">Hook execution architecture</summary>
            <CodeBlock title="plugin architecture" language="text">
              {pluginArchitecture}
            </CodeBlock>
          </details>
          <div className="system-subsection">
            <details className="system-subsection" data-system-detail-id="plugin-lifecycle">
              <summary className="system-metric-title">Lifecycle</summary>
              <div className="system-metric-grid">
                {pluginLifecycle.map((line) => (
                  <article key={line} className="system-metric-card">
                    <p className="system-metric-line">{line}</p>
                  </article>
                ))}
              </div>
            </details>
          </div>
          <details className="system-subsection" data-system-detail-id="plugin-manifest">
            <summary className="system-metric-title">Manifest example</summary>
            <CodeBlock title="plugin-manifest.json" language="json">
              {pluginManifest}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="plugin-commands">
            <summary className="system-metric-title">{"Install -> validate -> activate -> execute"}</summary>
            <CodeBlock title="plugin lifecycle commands" language="bash">
              {pluginCommands}
            </CodeBlock>
          </details>
        </SystemSection>

        <SystemSection title="What's next">
          <ul className="system-bullets">
            {nonGoals.map((item) => (
              <li key={item}><strong>Not planned:</strong> {item}</li>
            ))}
          </ul>
          <div className="system-version-list">
            {roadmap.map((item) => (
              <details key={item.id} className="system-version-card" data-system-detail-id={item.id}>
                <summary className="system-version-head">
                  <div>
                    <p className="system-metric-title">{item.title}</p>
                  </div>
                  <StatusChip status={item.status} />
                </summary>
                <p className="system-metric-line">{item.text}</p>
              </details>
            ))}
          </div>
        </SystemSection>
      </div>
    </SystemPageShell>
  );
}
