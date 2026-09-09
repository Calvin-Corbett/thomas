import Link from "next/link";
import { StatusChip, type StatusType } from "@/components/status-chip";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { type SiteLocale, withSiteLocale } from "@/lib/site-locale";

type JourneyCopy = {
  title: string;
  roadmapVsJourney: string;
  roadmapTitle: string;
  roadmapText: string;
  roadmapLink: string;
  journeyTitle: string;
  journeyText: string;
  whyThomasExists: string;
  whyThomasLines: string[];
  principlesTitle: string;
  principles: string[];
  milestonesTitle: string;
  milestones: Array<{ date: string; title: string; status: StatusType; text: string }>;
  whatsNextTitle: string;
  nextSteps: string[];
  notPlannedLabel: string;
  notPlannedText: string;
  infiniteTitle: string;
  infiniteLines: string[];
  infiniteCards: Array<{ title: string; text: string }>;
};

function getStatusLabel(locale: SiteLocale, status: StatusType) {
  if (locale === "ja-JP") {
    if (status === "implemented") return "実装済み";
    if (status === "partial") return "一部対応";
    return "計画済み";
  }
  if (locale === "zh-CN") {
    if (status === "implemented") return "已实现";
    if (status === "partial") return "部分完成";
    return "已声明";
  }
  return undefined;
}

function getJourneyCopy(locale: SiteLocale): JourneyCopy {
  if (locale === "ja-JP") {
    return {
      title: "これまでの道のり",
      roadmapVsJourney: "ロードマップとジャーニー",
      roadmapTitle: "ロードマップ",
      roadmapText:
        "ロードマップは前を見るページです。Thomas がどこへ向かうのか、3つの大きな段階が何を解放するのかを示します。",
      roadmapLink: "ロードマップを開く",
      journeyTitle: "ジャーニー",
      journeyText:
        "こちらは現実の進捗を追うページです。実際に何を出荷したのか、構造がどう変わったのか、今も製品を縛っている制約は何かを記録します。",
      whyThomasExists: "Thomas が存在する理由",
      whyThomasLines: [
        "多くの AI ツールは AI に好き勝手させます。Thomas はすべての操作の前に承認を通します。あなたの OK がない限り実行されません。",
        "目標は、明示的な承認と検証可能な契約を持つローカル実行ツールを作ることです。主導権は常にあなたにあります。",
      ],
      principlesTitle: "妥協しないこと",
      principles: [
        "無制限実行はしない。すべての操作はコマンドファミリーとポリシーゲートに結び付ける。",
        "ローカルファーストを基本にし、外部連携は明示的かつ制限付きにする。",
        "リリース成果物とリリースノートで裏付けられた主張だけを出す。",
      ],
      milestonesTitle: "マイルストーン",
      milestones: [
        {
          date: "2026-02",
          title: "実行境界を強制",
          status: "implemented",
          text: "リクエスト解析と承認ゲートが、すべての実行経路の前段に入るようになりました。",
        },
        {
          date: "2026-02",
          title: "コマンドファミリー契約",
          status: "implemented",
          text: "各コマンドファミリーに深さマーカーとリリース連動の検証が付きました。",
        },
        {
          date: "2026-02",
          title: "リリース連動の可観測性",
          status: "partial",
          text: "ダウンロード、成果物、ログの情報を一つの証跡にまとめ始めています。",
        },
        {
          date: "2026-03",
          title: "Gateway と CLI の整合",
          status: "partial",
          text: "API ルートと CLI コマンドが同じ検証面を共有するようになってきました。",
        },
      ],
      whatsNextTitle: "次に進めること",
      nextSteps: [
        "プラグインのサンドボックスとポリシーチェックを拡張する。",
        "複雑さを増やさずにリリース再現性を高める。",
        "コントロールプレーンを、ローカル実行の外側の別エージェントではなく、その上の可視ビューとして保つ。",
      ],
      notPlannedLabel: "予定していないこと",
      notPlannedText:
        "承認なしで AI に何でも実行させること、契約で裏付けられていない機能を追加すること、再現性チェックを飛ばすこと。",
      infiniteTitle: "Thomas Infinite",
      infiniteLines: [
        "Thomas のモバイルコンパニオンアプリです。まだ開発中です。",
        "スマホから Thomas の状態を見て、コマンドを並べ、結果を確認し、操作を承認できます。実行自体はすべて Thomas 本体が担当します。Infinite は裏口ではなく、ウィンドウです。",
      ],
      infiniteCards: [
        { title: "ローカルに残るもの", text: "Infinite は UI 面であり、単独ランタイムではありません。" },
        { title: "リモートにできるもの", text: "トークン付き転送とペアリングは想定済みで、鍵ローテーションは進行中です。" },
        { title: "やらないこと", text: "Infinite が Thomas 本体の外でコマンドを実行することはありません。" },
      ],
    };
  }

  if (locale === "zh-CN") {
    return {
      title: "到目前为止的历程",
      roadmapVsJourney: "路线图与历程",
      roadmapTitle: "路线图",
      roadmapText:
        "路线图是面向未来的页面，用来说明 Thomas 将去往哪里、三个阶段分别要解锁什么。",
      roadmapLink: "打开路线图",
      journeyTitle: "历程",
      journeyText:
        "这个页面更务实。它记录已经真正交付了什么、架构发生了什么变化，以及现在仍然约束产品的核心原则。",
      whyThomasExists: "Thomas 为什么存在",
      whyThomasLines: [
        "很多 AI 工具让 AI 想做什么就做什么。Thomas 要求每个动作先经过审批。没有你的同意，什么都不会运行。",
        "目标是做一个具备明确审批和可验证契约的本地执行工具。控制权始终在你手里。",
      ],
      principlesTitle: "我们不会妥协的事",
      principles: [
        "绝不允许无限制执行。每个动作都绑定到命令族和策略闸门。",
        "坚持本地优先，远程集成必须明确且有边界。",
        "只交付有发布产物和发布说明支撑的主张。",
      ],
      milestonesTitle: "里程碑",
      milestones: [
        {
          date: "2026-02",
          title: "执行边界已强制生效",
          status: "implemented",
          text: "请求解析和审批闸门现在位于所有执行路径之前。",
        },
        {
          date: "2026-02",
          title: "命令族契约",
          status: "implemented",
          text: "每个命令族都带有深度标记，并与发布验证绑定。",
        },
        {
          date: "2026-02",
          title: "与发布绑定的可观测性",
          status: "partial",
          text: "下载、产物和日志元数据正在合并成一条证据链。",
        },
        {
          date: "2026-03",
          title: "Gateway 与 CLI 对齐",
          status: "partial",
          text: "API 路由和 CLI 命令正在共享同一套验证表面。",
        },
      ],
      whatsNextTitle: "接下来要做什么",
      nextSteps: [
        "继续扩展插件沙箱和策略检查。",
        "在不增加复杂度的前提下提升发布可复现性。",
        "让控制平面始终只是本地执行的观察面，而不是另一个脱离边界的代理。",
      ],
      notPlannedLabel: "不打算做的事",
      notPlannedText:
        "让 AI 在没有审批的情况下随便执行、添加没有契约证据支撑的功能、跳过可复现性检查。",
      infiniteTitle: "Thomas Infinite",
      infiniteLines: [
        "这是 Thomas 的移动端伴侣应用，目前仍在开发中。",
        "你可以在手机上查看 Thomas 在做什么、排队命令、查看结果、审批操作。所有执行仍然通过 Thomas 主体完成。Infinite 是窗口，不是后门。",
      ],
      infiniteCards: [
        { title: "哪些内容保持本地", text: "Infinite 是一个界面层，不是独立运行时。" },
        { title: "哪些内容可以远程", text: "带令牌的传输和配对在计划内，密钥轮换仍在推进中。" },
        { title: "它不会做什么", text: "Infinite 不会绕开 Thomas 核心路径执行命令。" },
      ],
    };
  }

  return {
    title: "The Journey So Far",
    roadmapVsJourney: "Roadmap vs journey",
    roadmapTitle: "Roadmap",
    roadmapText:
      "The roadmap is the forward-looking page: where Thomas is headed, what the three big phases are, and what each phase is trying to unlock.",
    roadmapLink: "Open the roadmap",
    journeyTitle: "Journey",
    journeyText:
      "This page stays practical. It tracks what has actually shipped, what changed in the architecture, and what constraints still define the product.",
    whyThomasExists: "Why Thomas exists",
    whyThomasLines: [
      "Most AI tools let the AI do whatever it wants. Thomas makes every action go through an approval step first. Nothing runs without your OK.",
      "The goal: a local execution tool with explicit approvals and verifiable contracts for every command. You stay in control.",
    ],
    principlesTitle: "What we won't compromise on",
    principles: [
      "No unbounded execution. Every action is tied to a command family and policy gate.",
      "Local-first operation, with remote integration explicit and bounded.",
      "We only ship claims backed by release artifacts and release notes.",
    ],
    milestonesTitle: "Milestones",
    milestones: [
      {
        date: "2026-02",
        title: "Execution boundary enforced",
        status: "implemented",
        text: "Request parsing and approval gates now sit in front of every execution path.",
      },
      {
        date: "2026-02",
        title: "Command family contracts",
        status: "implemented",
        text: "Each command family has depth markers and validation tied to releases.",
      },
      {
        date: "2026-02",
        title: "Release-linked observability",
        status: "partial",
        text: "Download, artifact, and log metadata merged into one evidence trail.",
      },
      {
        date: "2026-03",
        title: "Gateway and CLI alignment",
        status: "partial",
        text: "API routes and CLI commands now share the same validation surface.",
      },
    ],
    whatsNextTitle: "What's next",
    nextSteps: [
      "Expand plugin sandbox and policy checks.",
      "Improve release reproducibility without adding complexity.",
      "Keep the control plane as a view over local execution, not a standalone agent.",
    ],
    notPlannedLabel: "What's not planned",
    notPlannedText:
      "Letting the AI run anything without approval, adding features without contract-backed evidence, or skipping reproducibility checks.",
    infiniteTitle: "Thomas Infinite",
    infiniteLines: [
      "The mobile companion app for Thomas. Still in development.",
      "See what Thomas is doing from your phone. Queue commands, check results, approve actions. Everything still goes through Thomas for policy, validation, and audit. Infinite is a window, not a backdoor.",
    ],
    infiniteCards: [
      { title: "What stays local", text: "Infinite is a UI surface, not a standalone runtime." },
      { title: "What can be remote", text: "Tokened transport and pairing are supported; key rotation is still in progress." },
      { title: "What it won't do", text: "Infinite never runs commands outside the Thomas core path." },
    ],
  };
}

export function SiteJourneyPage({ locale = "en" }: { locale?: SiteLocale }) {
  const copy = getJourneyCopy(locale);
  const roadmapHref = withSiteLocale(locale, "/roadmap");

  return (
    <SystemPageShell title={copy.title} versionLabel="v0.14.38">
      <SystemSection title={copy.roadmapVsJourney}>
        <div className="system-metric-grid">
          <article className="system-metric-card">
            <p className="system-metric-title">{copy.roadmapTitle}</p>
            <p className="system-metric-line">{copy.roadmapText}</p>
            <Link href={roadmapHref} className="text-link">
              {copy.roadmapLink}
            </Link>
          </article>
          <article className="system-metric-card">
            <p className="system-metric-title">{copy.journeyTitle}</p>
            <p className="system-metric-line">{copy.journeyText}</p>
          </article>
        </div>
      </SystemSection>

      <SystemSection title={copy.whyThomasExists}>
        {copy.whyThomasLines.map((line) => (
          <p key={line} className="system-metric-line">
            {line}
          </p>
        ))}
      </SystemSection>

      <SystemSection title={copy.principlesTitle}>
        <ul className="system-bullets">
          {copy.principles.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </SystemSection>

      <SystemSection title={copy.milestonesTitle}>
        <div className="system-version-list">
          {copy.milestones.map((milestone) => (
            <article key={milestone.title} className="system-version-card" style={{ padding: "0.8rem" }}>
              <div className="system-version-head">
                <div>
                  <p className="system-metric-title">{milestone.date}</p>
                  <p className="system-section-title">{milestone.title}</p>
                </div>
                <StatusChip status={milestone.status} label={getStatusLabel(locale, milestone.status)} />
              </div>
              <p className="system-metric-line" style={{ marginTop: "0.4rem" }}>
                {milestone.text}
              </p>
            </article>
          ))}
        </div>
      </SystemSection>

      <SystemSection title={copy.whatsNextTitle}>
        <ul className="system-bullets">
          {copy.nextSteps.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="system-metric-line" style={{ marginTop: "0.4rem" }}>
          <strong>{copy.notPlannedLabel}:</strong> {copy.notPlannedText}
        </p>
      </SystemSection>

      <SystemSection title={copy.infiniteTitle} id="infinite">
        {copy.infiniteLines.map((line) => (
          <p key={line} className="system-metric-line">
            {line}
          </p>
        ))}
        <div className="system-metric-grid" style={{ marginTop: "0.6rem" }}>
          {copy.infiniteCards.map((card) => (
            <article key={card.title} className="system-metric-card">
              <p className="system-metric-title">{card.title}</p>
              <p className="system-metric-line">{card.text}</p>
            </article>
          ))}
        </div>
      </SystemSection>
    </SystemPageShell>
  );
}
