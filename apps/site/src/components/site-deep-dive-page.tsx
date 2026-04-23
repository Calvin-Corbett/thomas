import { CommandMatrix, type CommandMatrixRow } from "@/components/command-matrix";
import { CodeBlock } from "@/components/system-code-block";
import { CalloutBlock } from "@/components/system-callout";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { StatusChip, type StatusType } from "@/components/status-chip";
import { CLI_COMPARISON_ROWS, type CLIComparisonRow } from "@/lib/featureComparisonData";
import { getRepoUrl } from "@/lib/site-config";
import { type SiteLocale } from "@/lib/site-locale";

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
  plan: { family: "status", command: "status", policyGate: "ok", approvalState: "required" },
  execution: {
    output: { totalSteps: 6, exitCode: 0 },
    checks: { schemaValidation: true, policyGate: true, commandContract: true },
  },
  artifacts: { auditId: "rq-2026-03-02-001", artifactPath: "/var/log/thomas/events.jsonl" },
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

const pluginCommands = `thomas plugin install ./dist/thomas-plugin-guard.zip
thomas plugin validate thomas-plugin-guard
thomas plugin activate thomas-plugin-guard
thomas plugin run thomas-plugin-guard --diagnostic
thomas plugin deactivate thomas-plugin-guard
thomas plugin uninstall thomas-plugin-guard`;

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
    if (next !== raw) trimmed += 1;
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

type DeepDiveCopy = {
  eyebrow: string;
  title: string;
  howCommandsRun: string;
  executionModel: string;
  executionModelText: string;
  coverage: string;
  contractStatus: (summary: string, families: number) => string;
  lastValidated: string;
  whatWeTrack: string;
  matrixSignals: string[];
  executionPipeline: string;
  commandFamilyMatrix: string;
  commandMatrixIssue: string;
  sourceForCommandFamilies: string;
  releaseRepository: string;
  integrityEvidence: string;
  gatewayContracts: string;
  nonStreamRequest: string;
  streamingEventModel: string;
  nonStreamResponse: string;
  cliParityCheck: string;
  pluginExecutionBoundary: string;
  hookExecutionArchitecture: string;
  lifecycle: string;
  manifestExample: string;
  pluginLifecycleCommand: string;
  whatsNext: string;
  notPlanned: string;
  roadmap: Array<{ id: string; title: string; status: StatusType; text: string }>;
  nonGoals: string[];
  matrixLabels: Parameters<typeof CommandMatrix>[0]["labels"];
  pluginLifecycle: string[];
};

function getDeepDiveCopy(locale: SiteLocale): DeepDiveCopy {
  if (locale === "ja-JP") {
    return {
      eyebrow: "技術",
      title: "Thomas の仕組み",
      howCommandsRun: "コマンドがどう流れるか",
      executionModel: "実行モデル",
      executionModelText: "すべてのリクエストは、実行前に計画、ポリシーゲート、監査証跡を通ります。",
      coverage: "カバレッジ",
      contractStatus: (summary, families) => `契約状態: ${summary}\n総コマンドファミリー数: ${families}`,
      lastValidated: "最終検証",
      whatWeTrack: "追跡しているもの",
      matrixSignals: [
        "明示的な深さを持つコマンドファミリー",
        "ファミリーごとのカバレッジと証跡状態",
        "実行成果物のルート/パス追跡性",
      ],
      executionPipeline: "実行パイプライン",
      commandFamilyMatrix: "コマンドファミリーマトリクス",
      commandMatrixIssue: "コマンドマトリクスのソースに問題があります",
      sourceForCommandFamilies: "コマンドファミリーの出典:",
      releaseRepository: "リリースリポジトリ",
      integrityEvidence: "整合性の証拠",
      gatewayContracts: "Gateway 契約と CLI 整合",
      nonStreamRequest: "非ストリーム要求例",
      streamingEventModel: "ストリーミングイベントモデル",
      nonStreamResponse: "非ストリーム応答形式",
      cliParityCheck: "CLI 整合チェック",
      pluginExecutionBoundary: "プラグイン実行境界",
      hookExecutionArchitecture: "フック実行アーキテクチャ",
      lifecycle: "ライフサイクル",
      manifestExample: "Manifest 例",
      pluginLifecycleCommand: "Install -> validate -> activate -> execute",
      whatsNext: "次に進めること",
      notPlanned: "予定していないこと",
      roadmap: [
        { id: "command-evidence-snapshots", title: "コマンド証跡スナップショット", status: "implemented", text: "ファミリー単位のカバレッジ情報がソース成果物に結び付いています。" },
        { id: "gateway-contract-coverage", title: "Gateway 契約カバレッジ", status: "implemented", text: "HTTP 契約と CLI 呼び出しは同じガード/検証面を共有しています。" },
        { id: "plugin-lifecycle-replay", title: "プラグインライフサイクル再現", status: "planned", text: "次は、完全な導入とポリシーフック再現をトレース付きで検証することです。" },
      ],
      nonGoals: [
        "無制限な自律実行。",
        "ルート証拠なしに API 全面対応を主張すること。",
        "ポリシーゲートなしの暗黙的信頼。",
      ],
      matrixLabels: {
        summaryLine: "{implemented} 実装済み / {declared} 宣言のみ",
        totalCommandCount: "総コマンド数: {count}",
        lastValidated: "最終検証スナップショット: {value}",
        showingFamilies: "{total} 件中 {visible} 件を表示中。",
        controlsTitle: "コマンドマトリクス操作",
        controlsSubtitle: "検索、絞り込み、表示モード",
        searchLabel: "ファミリー / コマンドを検索",
        searchPlaceholder: "status、family、command",
        searchAriaLabel: "コマンドファミリーとサブコマンドを検索",
        statusFilter: "状態フィルター",
        filterAll: "すべて",
        filterImplemented: "実装済み",
        filterDeclared: "宣言のみ",
        compactMode: "コンパクト表示",
        compactModeOn: "コンパクト表示: オン",
        collapseAll: "すべて閉じる",
        expandAll: "すべて開く",
        noFamilies: "この検索条件に一致するファミリーはありません。",
        coverageIndicator: "カバレッジ指標",
        routePath: "ルートパス",
        openRouteSource: "ルートソースを開く",
        subcommands: "サブコマンド",
        noSubcommands: "このスナップショットではサブコマンドが検出されませんでした。",
        coveragePlanned: "未検証（このスナップショットでは実装が存在しません）",
        coverageClean: "このスナップショットからパーサー面を検証済み",
        coverageWithIssues: "検証面に {count} 件のデータ整形シグナルがあります",
        depthMetric: "深さ {count}",
        commandMetric: "コマンド数 {count}",
        statusImplemented: "実装済み",
        statusPartial: "一部対応",
        statusPlanned: "宣言のみ",
      },
      pluginLifecycle: ["パッケージを導入", "Manifest とチェックサムを検証", "レジストリで有効化", "保護された経路で実行", "無効化して実行状態を削除", "パッケージを削除"],
    };
  }

  if (locale === "zh-CN") {
    return {
      eyebrow: "技术",
      title: "Thomas 的工作方式",
      howCommandsRun: "命令如何执行",
      executionModel: "执行模型",
      executionModelText: "所有请求在真正运行前都要经过规划、策略闸门和审计跟踪。",
      coverage: "覆盖情况",
      contractStatus: (summary, families) => `契约状态: ${summary}\n命令族总数: ${families}`,
      lastValidated: "最后验证",
      whatWeTrack: "我们跟踪什么",
      matrixSignals: ["具有明确深度的命令族", "每个命令族的覆盖与证据状态", "执行产物的路由/路径可追溯性"],
      executionPipeline: "执行流水线",
      commandFamilyMatrix: "命令族矩阵",
      commandMatrixIssue: "命令矩阵数据源存在问题",
      sourceForCommandFamilies: "命令族来源:",
      releaseRepository: "发布仓库",
      integrityEvidence: "完整性证据",
      gatewayContracts: "Gateway 契约与 CLI 一致性",
      nonStreamRequest: "非流式请求示例",
      streamingEventModel: "流式事件模型",
      nonStreamResponse: "非流式响应格式",
      cliParityCheck: "CLI 一致性检查",
      pluginExecutionBoundary: "插件执行边界",
      hookExecutionArchitecture: "Hook 执行架构",
      lifecycle: "生命周期",
      manifestExample: "Manifest 示例",
      pluginLifecycleCommand: "Install -> validate -> activate -> execute",
      whatsNext: "接下来要做什么",
      notPlanned: "不打算做的事",
      roadmap: [
        { id: "command-evidence-snapshots", title: "命令证据快照", status: "implemented", text: "命令族级别的覆盖元数据已经与源产物关联起来。" },
        { id: "gateway-contract-coverage", title: "Gateway 契约覆盖", status: "implemented", text: "HTTP 契约和 CLI 调用共享同一套防护与验证表面。" },
        { id: "plugin-lifecycle-replay", title: "插件生命周期回放", status: "planned", text: "下一步是带可回放跟踪的完整安装与策略 hook 验证。" },
      ],
      nonGoals: [
        "无限制的自主执行。",
        "在没有路由证据的情况下宣称全面 API 覆盖。",
        "没有策略闸门的隐式信任。",
      ],
      matrixLabels: {
        summaryLine: "{implemented} 已实现 / {declared} 已声明",
        totalCommandCount: "命令总数: {count}",
        lastValidated: "最后验证快照: {value}",
        showingFamilies: "当前显示 {visible} / {total} 个命令族。",
        controlsTitle: "命令矩阵控制",
        controlsSubtitle: "搜索、筛选与视图模式",
        searchLabel: "搜索命令族 / 命令",
        searchPlaceholder: "status、family、command",
        searchAriaLabel: "搜索命令族和子命令",
        statusFilter: "状态筛选",
        filterAll: "全部",
        filterImplemented: "已实现",
        filterDeclared: "已声明",
        compactMode: "紧凑模式",
        compactModeOn: "紧凑模式: 开",
        collapseAll: "全部收起",
        expandAll: "全部展开",
        noFamilies: "没有符合当前搜索和筛选条件的命令族。",
        coverageIndicator: "覆盖指标",
        routePath: "路由路径",
        openRouteSource: "打开路由源码",
        subcommands: "子命令",
        noSubcommands: "这个快照中没有检测到子命令。",
        coveragePlanned: "未验证（当前快照中不存在实现）",
        coverageClean: "已根据当前快照验证解析表面",
        coverageWithIssues: "验证表面包含 {count} 个数据清理信号",
        depthMetric: "深度 {count}",
        commandMetric: "命令数 {count}",
        statusImplemented: "已实现",
        statusPartial: "部分完成",
        statusPlanned: "已声明",
      },
      pluginLifecycle: ["安装包", "校验 Manifest 与校验和", "在注册表中激活", "通过受保护路径执行", "停用并移除运行时状态", "卸载包"],
    };
  }

  return {
    eyebrow: "Technical",
    title: "How Thomas Works",
    howCommandsRun: "How commands run",
    executionModel: "Execution model",
    executionModelText: "Every request goes through planning, policy gates, and audit tracing before anything runs.",
    coverage: "Coverage",
    contractStatus: (summary, families) => `Contract status: ${summary}\nTotal command families: ${families}`,
    lastValidated: "Last validated",
    whatWeTrack: "What we track",
    matrixSignals: [
      "Families with explicit command depth",
      "Coverage and evidence status per family",
      "Route/path traceability for execution artifacts",
    ],
    executionPipeline: "Execution pipeline",
    commandFamilyMatrix: "Command family matrix",
    commandMatrixIssue: "Command matrix source issue",
    sourceForCommandFamilies: "Source for command families:",
    releaseRepository: "release repository",
    integrityEvidence: "Integrity evidence",
    gatewayContracts: "Gateway contracts and CLI parity",
    nonStreamRequest: "Non-stream request example",
    streamingEventModel: "Streaming event model",
    nonStreamResponse: "Non-stream response format",
    cliParityCheck: "CLI parity check",
    pluginExecutionBoundary: "Plugin execution boundary",
    hookExecutionArchitecture: "Hook execution architecture",
    lifecycle: "Lifecycle",
    manifestExample: "Manifest example",
    pluginLifecycleCommand: "Install -> validate -> activate -> execute",
    whatsNext: "What's next",
    notPlanned: "Not planned",
    roadmap: [
      { id: "command-evidence-snapshots", title: "Command evidence snapshots", status: "implemented", text: "Row-level coverage metadata is present for families and linked to source artifacts." },
      { id: "gateway-contract-coverage", title: "Gateway contract coverage", status: "implemented", text: "HTTP contracts and CLI calls share the same guard and validation surface." },
      { id: "plugin-lifecycle-replay", title: "Plugin lifecycle replay", status: "planned", text: "Next up: full install + policy-hook replay with trace replayability." },
    ],
    nonGoals: [
      "Unbounded autonomous execution.",
      "Claims of universal API coverage without route evidence.",
      "Implicit trust without policy gates.",
    ],
    matrixLabels: undefined,
    pluginLifecycle: [
      "Install package",
      "Validate manifest and checksum",
      "Activate in registry",
      "Execute through protected path",
      "Deactivate + remove runtime state",
      "Uninstall package",
    ],
  };
}

function getStatusLabel(locale: SiteLocale, status: StatusType) {
  if (locale === "ja-JP") {
    if (status === "implemented") return "実装済み";
    if (status === "partial") return "一部対応";
    return "宣言のみ";
  }
  if (locale === "zh-CN") {
    if (status === "implemented") return "已实现";
    if (status === "partial") return "部分完成";
    return "已声明";
  }
  return undefined;
}

export function SiteDeepDivePage({ locale = "en" }: { locale?: SiteLocale }) {
  const copy = getDeepDiveCopy(locale);
  const releasesUrl = getRepoUrl();
  const lastValidatedAt = "2026-03-02T01:09:04Z";
  const matrixRowsData = buildMatrixRows();
  const matrixRows = matrixRowsData.rows;
  const matrixStats = {
    implemented: matrixRows.filter((row) => row.status === "implemented").length,
    declared: matrixRows.filter((row) => row.status !== "implemented").length,
  };
  const summary = `${matrixStats.implemented} implemented / ${matrixStats.declared} declared`;

  return (
    <SystemPageShell eyebrow={copy.eyebrow} title={copy.title} versionLabel="v0.11.39" persistDetails={false}>
      <div className="system-content-narrow">
        <SystemSection title={copy.howCommandsRun}>
          <div className="system-grid">
            <article className="system-metric-card">
              <p className="system-metric-title">{copy.executionModel}</p>
              <p className="system-metric-note">{copy.executionModelText}</p>
            </article>
            <article className="system-metric-card">
              <p className="system-metric-title">{copy.coverage}</p>
              <p className="system-metric-note">
                {copy.contractStatus(summary, matrixRows.length)}
              </p>
              <p className="system-metric-line">
                {copy.lastValidated}: {new Date(lastValidatedAt).toLocaleString(locale)}
              </p>
            </article>
            <article className="system-metric-card">
              <p className="system-metric-title">{copy.whatWeTrack}</p>
              <ul className="system-bullets">
                {copy.matrixSignals.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </article>
          </div>
          <details className="system-subsection" data-system-detail-id="execution-pipeline">
            <summary className="system-metric-title">{copy.executionPipeline}</summary>
            <CodeBlock title="pipeline" language="text">
              {pipelineFlow}
            </CodeBlock>
          </details>
        </SystemSection>

        <SystemSection title={copy.commandFamilyMatrix} id="command-matrix">
          {matrixRowsData.error ? (
            <CalloutBlock tone="warning" title={copy.commandMatrixIssue}>
              {matrixRowsData.error}
            </CalloutBlock>
          ) : null}
          <p className="system-metric-line">
            {copy.sourceForCommandFamilies}
            {releasesUrl ? (
              <a className="text-link" href={releasesUrl} target="_blank" rel="noreferrer">
                {" "}
                {copy.releaseRepository}
              </a>
            ) : null}
          </p>
          <CommandMatrix
            rows={matrixRows}
            lastValidatedAt={lastValidatedAt}
            repoUrl={releasesUrl || undefined}
            labels={copy.matrixLabels}
          />
        </SystemSection>

        <SystemSection title={copy.integrityEvidence} id="integrity">
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

        <SystemSection title={copy.gatewayContracts} id="gateway-contracts">
          <details className="system-subsection" data-system-detail-id="gateway-request">
            <summary className="system-metric-title">{copy.nonStreamRequest}</summary>
            <CodeBlock title="curl request" language="bash">
              {gatewayCurl}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="gateway-stream">
            <summary className="system-metric-title">{copy.streamingEventModel}</summary>
            <CodeBlock title="sse events" language="text">
              {gatewayStream}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="gateway-response">
            <summary className="system-metric-title">{copy.nonStreamResponse}</summary>
            <CodeBlock title="response.json" language="json">
              {gatewayResponse}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="gateway-cli">
            <summary className="system-metric-title">{copy.cliParityCheck}</summary>
            <CodeBlock title="CLI commands" language="bash">
              {gatewayCLI}
            </CodeBlock>
          </details>
        </SystemSection>

        <SystemSection title={copy.pluginExecutionBoundary}>
          <details className="system-subsection" data-system-detail-id="plugin-architecture">
            <summary className="system-metric-title">{copy.hookExecutionArchitecture}</summary>
            <CodeBlock title="plugin architecture" language="text">
              {pluginArchitecture}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="plugin-lifecycle">
            <summary className="system-metric-title">{copy.lifecycle}</summary>
            <div className="system-metric-grid">
              {copy.pluginLifecycle.map((line) => (
                <article key={line} className="system-metric-card">
                  <p className="system-metric-line">{line}</p>
                </article>
              ))}
            </div>
          </details>
          <details className="system-subsection" data-system-detail-id="plugin-manifest">
            <summary className="system-metric-title">{copy.manifestExample}</summary>
            <CodeBlock title="plugin-manifest.json" language="json">
              {pluginManifest}
            </CodeBlock>
          </details>
          <details className="system-subsection" data-system-detail-id="plugin-commands">
            <summary className="system-metric-title">{copy.pluginLifecycleCommand}</summary>
            <CodeBlock title="plugin lifecycle commands" language="bash">
              {pluginCommands}
            </CodeBlock>
          </details>
        </SystemSection>

        <SystemSection title={copy.whatsNext}>
          <ul className="system-bullets">
            {copy.nonGoals.map((item) => (
              <li key={item}>
                <strong>{copy.notPlanned}:</strong> {item}
              </li>
            ))}
          </ul>
          <div className="system-version-list">
            {copy.roadmap.map((item) => (
              <details key={item.id} className="system-version-card" data-system-detail-id={item.id}>
                <summary className="system-version-head">
                  <div>
                    <p className="system-metric-title">{item.title}</p>
                  </div>
                  <StatusChip status={item.status} label={getStatusLabel(locale, item.status)} />
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
