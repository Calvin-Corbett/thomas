import { RoadmapShell, type RoadmapChapter } from "@/components/roadmap-shell";
import { type SiteLocale, withSiteLocale } from "@/lib/site-locale";

type RoadmapContent = {
  shellCopy: {
    heroEyebrow: string;
    heroTitle: string;
    heroLead: string;
    journeyHref: string;
    journeyLabel: string;
    downloadHref: string;
    downloadLabel: string;
    currentBuildLabel: string;
    whereThingsStandLabel: string;
    phasesEyebrow: string;
    phasesTitle: string;
    phasesAriaLabel: string;
    openPhaseLabel: string;
    selectedPhaseEyebrow: string;
    whyThisPhaseMatters: string;
  };
  repoSnapshot: {
    release: string;
    stamp: string;
    signals: string[];
  };
  chapters: RoadmapChapter[];
};

function getEnglishRoadmapContent(): RoadmapContent {
  return {
    shellCopy: {
      heroEyebrow: "Roadmap",
      heroTitle: "Thomas Roadmap",
      heroLead:
        "Thomas is still pre-alpha. The job right now is to make the core trustworthy, turn that core into a private app network you can carry on your phone, and then push all of that into a real AI-native operating system.",
      journeyHref: "/journey",
      journeyLabel: "Read the journey",
      downloadHref: "/download",
      downloadLabel: "Download current build",
      currentBuildLabel: "Current build",
      whereThingsStandLabel: "Where things stand",
      phasesEyebrow: "Three phases",
      phasesTitle: "One route, one active phase at a time.",
      phasesAriaLabel: "Roadmap phases",
      openPhaseLabel: "Open",
      selectedPhaseEyebrow: "Selected phase",
      whyThisPhaseMatters: "Why this phase matters",
    },
    repoSnapshot: {
      release: "v0.14.38 / pre-alpha",
      stamp: "Current repo state across the March 17-18, 2026 shipping streak.",
      signals: [
        "Approval-gated execution is already live.",
        "Plugin surfaces, launchers, and control-plane pieces are already in the repo.",
        "Research and evolve loops are pushing Thomas beyond one-shot prompting.",
      ],
    },
    chapters: [
      {
        id: "thomas-core",
        phase: "Phase 01",
        status: "Current build / Pre-Alpha",
        title: "Thomas Core",
        horizon: "Shipping now",
        intro: "Make local execution trustworthy before the surface area gets much larger.",
        body: "Thomas already has approval gates, evidence-linked releases, plugin runtime surfaces, and local launchers. The next job is making that stack feel coherent and dependable.",
        outcome: "Thomas becomes a dependable local execution layer with enough trust and clarity to support everything that comes after it.",
        repoSignals: ["Startup router", "Approval gates", "Desktop plugins", "My Stuff launcher"],
        checkpoints: [
          {
            id: "core-boundary",
            title: "Trust boundary and execution contracts",
            status: "Live in repo",
            horizon: "Now",
            summary: "Keep the AI useful without letting it slip past approvals or route rules.",
            detail: "This is the center of the product: command families, explicit approvals, and release-linked evidence working together.",
            signals: ["Approval-gated execution", "Command family contracts", "Artifact-backed evidence"],
            tone: "live",
            featured: true,
          },
          {
            id: "core-surfaces",
            title: "Local workflow surfaces",
            status: "Live in repo",
            horizon: "Now",
            summary: "Turn capability into surfaces people can actually use.",
            detail: "Launchers, web surfaces, and desktop flows need to feel like one operator system instead of disconnected experiments.",
            signals: ["Local project launcher", "Web and desktop alignment", "Operator-first workflows"],
            tone: "live",
          },
          {
            id: "core-loops",
            title: "Research and evolve loops",
            status: "Building now",
            horizon: "Current branch",
            summary: "Thomas is starting to manage longer-running improvement loops.",
            detail: "Research programs, evolve flows, and presence monitoring push Thomas toward a system that can keep making progress without losing visibility.",
            signals: ["Tracked research artifacts", "Evolve workflow", "Presence monitor"],
            tone: "build",
            featured: true,
          },
        ],
      },
      {
        id: "thomas-infinite",
        phase: "Phase 02",
        status: "Next major milestone",
        title: "Thomas Infinite",
        horizon: "Private phone layer",
        intro: "Turn Thomas into a private app network you can carry around without giving up the local core.",
        body: "Infinite is the phase where Thomas can generate focused web surfaces, move them over private transport, and present them on a phone while the main Thomas runtime stays in charge.",
        outcome: "Thomas gains a private mobile layer for approvals, queues, and focused job surfaces.",
        repoSignals: ["Control plane patterns", "Tailscale target", "Journey placeholder"],
        checkpoints: [
          {
            id: "infinite-transport",
            title: "Private pairing and transport",
            status: "Next up",
            horizon: "Foundational",
            summary: "Use a private network layer so the phone feels direct, not fragile.",
            detail: "The important part is secure pairing, clean session handoff, and no bypass around the Thomas core.",
            signals: ["Private pairing", "Rekey story", "No public-cloud shortcut"],
            tone: "build",
            featured: true,
          },
          {
            id: "infinite-surfaces",
            title: "Headless app surfaces on demand",
            status: "Designing",
            horizon: "App factory layer",
            summary: "Thomas should generate focused interfaces instead of forcing everything through one chat window.",
            detail: "The phone experience matters most when each workflow can have its own surface, state, and controls.",
            signals: ["Workflow-specific surfaces", "Private delivery", "Runtime-linked interfaces"],
            tone: "build",
          },
          {
            id: "infinite-ops",
            title: "Approvals, queues, and live review",
            status: "Designing",
            horizon: "Operational layer",
            summary: "The phone layer should make Thomas more actionable, not just more visible.",
            detail: "Approvals, result review, and task queuing should all work on mobile while execution still lives in the main runtime.",
            signals: ["Mobile approvals", "Live run state", "Safe command handoff"],
            tone: "build",
          },
        ],
      },
      {
        id: "thomas-os",
        phase: "Phase 03",
        status: "Long-range bet",
        title: "Thomas OS",
        horizon: "AI-native Linux system",
        intro: "Stop bolting AI onto the computer and start building the computer around AI-native workflows from day one.",
        body: "Thomas OS is the idea that the shell, session model, trust system, and operator controls should all be designed together as one environment.",
        outcome: "Thomas becomes the operating environment itself: AI-native, operator-controlled, and built for real work.",
        repoSignals: ["Control-first philosophy", "Local-first runtime", "Recoverability obsession"],
        checkpoints: [
          {
            id: "os-session-model",
            title: "AI-native session and intent model",
            status: "Long bet",
            horizon: "Core systems layer",
            summary: "Tasks, intent, approvals, and delegated work should become native concepts.",
            detail: "This is where Thomas ideas stop living inside one app and start shaping the full computing environment.",
            signals: ["Intent-aware shell", "Native session memory", "Built-in task routing"],
            tone: "vision",
            featured: true,
          },
          {
            id: "os-surfaces",
            title: "Generated operating surfaces",
            status: "Long bet",
            horizon: "UI model",
            summary: "Interfaces should be generated as first-class parts of the system.",
            detail: "The system itself should be able to compose workspaces, automate flows, and surface mission-specific UI.",
            signals: ["Generated interfaces", "Mission switching", "Delegated UI state"],
            tone: "vision",
          },
          {
            id: "os-trust",
            title: "System-level policy and recovery",
            status: "Long bet",
            horizon: "Trust model",
            summary: "The trust story has to get stronger as the system gets bigger.",
            detail: "Approval, rollback, recoverability, and auditability cannot disappear as the operating surface expands.",
            signals: ["System-level rollback", "Recoverability", "Built-in safety posture"],
            tone: "vision",
          },
        ],
      },
    ],
  };
}

function getJapaneseRoadmapContent(): RoadmapContent {
  return {
    shellCopy: {
      heroEyebrow: "ロードマップ",
      heroTitle: "Thomas ロードマップ",
      heroLead:
        "Thomas はまだ pre-alpha です。今やるべきことは、コアを信頼できるものにし、それをスマホに持ち運べるプライベートなアプリ網に広げ、さらに AI ネイティブな OS へ押し上げることです。",
      journeyHref: "/ja-JP/journey",
      journeyLabel: "ジャーニーを見る",
      downloadHref: "/ja-JP/download",
      downloadLabel: "現在のビルドをダウンロード",
      currentBuildLabel: "現在のビルド",
      whereThingsStandLabel: "今の位置",
      phasesEyebrow: "3つの段階",
      phasesTitle: "一本の流れを、一度に一つの段階ずつ進める。",
      phasesAriaLabel: "ロードマップの段階",
      openPhaseLabel: "開く",
      selectedPhaseEyebrow: "選択中の段階",
      whyThisPhaseMatters: "この段階が重要な理由",
    },
    repoSnapshot: {
      release: "v0.14.38 / pre-alpha",
      stamp: "2026年3月中旬の出荷ラッシュ時点のリポジトリ状態です。",
      signals: [
        "承認付き実行はすでに動いています。",
        "プラグイン面、起動面、制御面はすでにリポジトリ内にあります。",
        "調査と進化のループが、Thomas を単発応答の外へ押し出しています。",
      ],
    },
    chapters: [
      {
        id: "thomas-core",
        phase: "Phase 01",
        status: "現在のビルド / Pre-Alpha",
        title: "Thomas Core",
        horizon: "今まさに出荷中",
        intro: "表面積が広がる前に、ローカル実行を信頼できるものにします。",
        body: "Thomas にはすでに承認ゲート、証跡付きリリース、プラグイン実行面、ローカル起動面があります。次の仕事は、それらを一つの頼れる系にすることです。",
        outcome: "Thomas は、その先を支えられる信頼性と明快さを持つローカル実行レイヤーになります。",
        repoSignals: ["Startup router", "Approval gates", "Desktop plugins", "My Stuff launcher"],
        checkpoints: [
          {
            id: "core-boundary",
            title: "信頼境界と実行契約",
            status: "リポジトリで稼働中",
            horizon: "今",
            summary: "AI を有用に保ちつつ、承認やルート規則をすり抜けさせないこと。",
            detail: "コマンドファミリー、明示承認、リリース証跡が中心で連動する状態を、Thomas の基礎にします。",
            signals: ["承認付き実行", "コマンド契約", "証跡付き成果物"],
            tone: "live",
            featured: true,
          },
          {
            id: "core-surfaces",
            title: "使えるローカル作業面",
            status: "リポジトリで稼働中",
            horizon: "今",
            summary: "能力を、人が本当に使える面として出すこと。",
            detail: "起動面、Web 面、デスクトップ面が、ばらばらの試作ではなく一つの運用系に見える必要があります。",
            signals: ["ローカル起動面", "Web とデスクトップの整合", "オペレーター中心の流れ"],
            tone: "live",
          },
          {
            id: "core-loops",
            title: "調査と進化のループ",
            status: "現在構築中",
            horizon: "現行ブランチ",
            summary: "Thomas は長い改善ループを扱い始めています。",
            detail: "調査プログラム、evolve フロー、常駐監視が、Thomas を見えるまま前進できる系へ押し出しています。",
            signals: ["調査成果物", "Evolve フロー", "常駐監視"],
            tone: "build",
            featured: true,
          },
        ],
      },
      {
        id: "thomas-infinite",
        phase: "Phase 02",
        status: "次の大きな段階",
        title: "Thomas Infinite",
        horizon: "プライベートなスマホ層",
        intro: "ローカルコアを保ったまま、Thomas を持ち歩ける私的ネットワークにします。",
        body: "Infinite は、仕事ごとの Web 面を私的経路でスマホに運び、実行の中心は Thomas 本体に残す段階です。",
        outcome: "Thomas は、承認、キュー、特化 UI を扱える私的モバイル層を持ちます。",
        repoSignals: ["Control plane patterns", "Tailscale target", "Journey placeholder"],
        checkpoints: [
          {
            id: "infinite-transport",
            title: "私的なペアリングと輸送",
            status: "次に着手",
            horizon: "基盤",
            summary: "スマホ体験を、露出した遠隔 UI ではなく私的な延長にすること。",
            detail: "重要なのは、安全なペアリング、きれいな引き継ぎ、そして Thomas コアを回避しないことです。",
            signals: ["私的ペアリング", "再鍵交換", "コアの迂回なし"],
            tone: "build",
            featured: true,
          },
          {
            id: "infinite-surfaces",
            title: "必要に応じたアプリ面",
            status: "設計中",
            horizon: "アプリ工場層",
            summary: "一つのチャット画面ではなく、仕事ごとの UI を作ること。",
            detail: "スマホ体験の価値は、各ワークフローが専用の面と状態を持てる時に上がります。",
            signals: ["仕事別 UI", "私的配布", "実行状態と接続した面"],
            tone: "build",
          },
          {
            id: "infinite-ops",
            title: "承認、キュー、ライブ確認",
            status: "設計中",
            horizon: "運用層",
            summary: "スマホ層は、見えるだけでなく動かしやすくするべきです。",
            detail: "承認、結果確認、作業投入をモバイルから行えても、実行自体は本体に残すのが前提です。",
            signals: ["モバイル承認", "ライブ実行状態", "安全な引き渡し"],
            tone: "build",
          },
        ],
      },
      {
        id: "thomas-os",
        phase: "Phase 03",
        status: "長期の賭け",
        title: "Thomas OS",
        horizon: "AI ネイティブ Linux",
        intro: "AI をあと付けするのではなく、最初から AI ネイティブな計算環境を作ること。",
        body: "Thomas OS は、シェル、セッション、信頼系、オペレーター制御を一体設計するという考えです。",
        outcome: "Thomas は、AI ネイティブでオペレーター制御の実務環境そのものになります。",
        repoSignals: ["Control-first philosophy", "Local-first runtime", "Recoverability obsession"],
        checkpoints: [
          {
            id: "os-session-model",
            title: "AI ネイティブなセッション/意図モデル",
            status: "長期の賭け",
            horizon: "コアシステム層",
            summary: "タスク、意図、承認、委譲をネイティブ概念にすること。",
            detail: "Thomas の発想を一つのアプリの外に出し、計算環境全体の形にする段階です。",
            signals: ["意図を理解する shell", "ネイティブなセッション記憶", "組み込みのタスクルーティング"],
            tone: "vision",
            featured: true,
          },
          {
            id: "os-surfaces",
            title: "生成される操作面",
            status: "長期の賭け",
            horizon: "UI モデル",
            summary: "面そのものがシステムの一級機能になること。",
            detail: "環境自体がワークスペースを組み、流れを自動化し、仕事ごとの UI を表に出せるようにします。",
            signals: ["生成 UI", "ミッション切り替え", "委譲状態の表示"],
            tone: "vision",
          },
          {
            id: "os-trust",
            title: "システム層のポリシーと復旧",
            status: "長期の賭け",
            horizon: "信頼モデル",
            summary: "システムが大きくなるほど、信頼系は強くなる必要があります。",
            detail: "承認、ロールバック、復旧性、監査性は、表面が広がっても消えてはいけません。",
            signals: ["システムロールバック", "復旧性", "組み込み安全姿勢"],
            tone: "vision",
          },
        ],
      },
    ],
  };
}

function getChineseRoadmapContent(): RoadmapContent {
  return {
    shellCopy: {
      heroEyebrow: "路线图",
      heroTitle: "Thomas 路线图",
      heroLead:
        "Thomas 仍处于 pre-alpha。现在的任务是先把核心做成可信系统，再把它扩展成你能随身携带的私有应用网络，最后推进成真正的 AI 原生操作系统。",
      journeyHref: "/zh-CN/journey",
      journeyLabel: "查看历程",
      downloadHref: "/zh-CN/download",
      downloadLabel: "下载当前构建",
      currentBuildLabel: "当前构建",
      whereThingsStandLabel: "当前位置",
      phasesEyebrow: "三个阶段",
      phasesTitle: "一条路线，一次只推进一个主阶段。",
      phasesAriaLabel: "路线图阶段",
      openPhaseLabel: "打开",
      selectedPhaseEyebrow: "当前阶段",
      whyThisPhaseMatters: "为什么这一阶段重要",
    },
    repoSnapshot: {
      release: "v0.14.38 / pre-alpha",
      stamp: "这是 2026 年 3 月中旬那轮密集发版期的仓库状态。",
      signals: [
        "带审批的执行已经在线。",
        "插件工作面、启动器和控制平面部件都已经在仓库里。",
        "研究与演化循环正在把 Thomas 推出一次性提示玩具的范围。",
      ],
    },
    chapters: [
      {
        id: "thomas-core",
        phase: "Phase 01",
        status: "当前构建 / Pre-Alpha",
        title: "Thomas Core",
        horizon: "正在交付",
        intro: "在表面继续扩大之前，先把本地执行做成可信系统。",
        body: "Thomas 已经有审批闸门、与发布绑定的证据链、插件运行面和本地启动面。接下来的任务是把这些东西收紧成一套可靠的主干。",
        outcome: "Thomas 会成为足够可信、足够清晰的本地执行层，为后面的所有阶段打底。",
        repoSignals: ["Startup router", "Approval gates", "Desktop plugins", "My Stuff launcher"],
        checkpoints: [
          {
            id: "core-boundary",
            title: "信任边界与执行契约",
            status: "仓库内已在线",
            horizon: "现在",
            summary: "让 AI 保持有用，但不能越过审批和路由规则。",
            detail: "命令族、明确审批和发布证据一起构成 Thomas 的核心边界。",
            signals: ["带审批的执行", "命令契约", "证据链产物"],
            tone: "live",
            featured: true,
          },
          {
            id: "core-surfaces",
            title: "真正可用的本地工作面",
            status: "仓库内已在线",
            horizon: "现在",
            summary: "把能力做成操作者真正能使用的界面。",
            detail: "启动器、网页工作面和桌面流程必须开始像一个系统，而不是几个分散的实验。",
            signals: ["本地启动面", "Web/桌面对齐", "操作者优先工作流"],
            tone: "live",
          },
          {
            id: "core-loops",
            title: "研究与演化循环",
            status: "正在构建",
            horizon: "当前分支",
            summary: "Thomas 开始管理更长周期的改进循环。",
            detail: "研究程序、evolve 流程和存在监控正在把 Thomas 推向可持续推进、又保持可见性的系统。",
            signals: ["研究产物", "Evolve 流程", "存在监控"],
            tone: "build",
            featured: true,
          },
        ],
      },
      {
        id: "thomas-infinite",
        phase: "Phase 02",
        status: "下一大阶段",
        title: "Thomas Infinite",
        horizon: "私有移动层",
        intro: "在不丢掉本地核心的前提下，把 Thomas 变成你能带着走的私有网络。",
        body: "Infinite 是这样一个阶段：Thomas 能把特定工作的 Web 工作面通过私有传输送到手机上，而执行控制仍然留在 Thomas 主运行时中。",
        outcome: "Thomas 会拥有一个能处理审批、队列和专用工作面的私有移动层。",
        repoSignals: ["Control plane patterns", "Tailscale target", "Journey placeholder"],
        checkpoints: [
          {
            id: "infinite-transport",
            title: "私有配对与传输",
            status: "接下来要做",
            horizon: "基础层",
            summary: "让手机体验成为直接的私有延伸，而不是脆弱的远程界面。",
            detail: "关键是安全配对、干净交接，以及绝不绕过 Thomas 核心。",
            signals: ["私有配对", "重置密钥机制", "不绕开核心"],
            tone: "build",
            featured: true,
          },
          {
            id: "infinite-surfaces",
            title: "按需生成的应用面",
            status: "设计中",
            horizon: "应用工厂层",
            summary: "每个工作流都应该能拥有自己的界面，而不是全塞进一个聊天窗。",
            detail: "当每个工作流都有专属状态和控件时，移动端价值才会真正显现。",
            signals: ["工作流专属界面", "私有分发", "与运行时联动"],
            tone: "build",
          },
          {
            id: "infinite-ops",
            title: "审批、队列与实时查看",
            status: "设计中",
            horizon: "操作层",
            summary: "移动层应该让 Thomas 更可操作，而不只是更可见。",
            detail: "审批、结果查看和任务排队都可以在手机上做，但执行必须仍然留在主运行时里。",
            signals: ["移动审批", "实时状态", "安全交接"],
            tone: "build",
          },
        ],
      },
      {
        id: "thomas-os",
        phase: "Phase 03",
        status: "长期押注",
        title: "Thomas OS",
        horizon: "AI 原生 Linux 系统",
        intro: "别再把 AI 当作后装补丁，而是从第一天起按 AI 原生工作流来设计整个环境。",
        body: "Thomas OS 的意思是把 shell、会话、信任系统和操作者控制一起设计成一个环境。",
        outcome: "Thomas 将成为 AI 原生、操作者可控、面向真实工作的操作环境本身。",
        repoSignals: ["Control-first philosophy", "Local-first runtime", "Recoverability obsession"],
        checkpoints: [
          {
            id: "os-session-model",
            title: "AI 原生会话与意图模型",
            status: "长期押注",
            horizon: "核心系统层",
            summary: "让任务、意图、审批和委派成为原生概念。",
            detail: "这一步意味着 Thomas 的想法不再局限于一个应用，而开始塑造整个计算环境。",
            signals: ["理解意图的 shell", "原生会话记忆", "内建任务路由"],
            tone: "vision",
            featured: true,
          },
          {
            id: "os-surfaces",
            title: "生成式操作面",
            status: "长期押注",
            horizon: "UI 模型",
            summary: "界面本身应该成为系统的一等能力。",
            detail: "系统应能自动组合工作面、自动化流程，并把任务相关 UI 直接暴露出来。",
            signals: ["生成界面", "任务切换", "委派状态可见"],
            tone: "vision",
          },
          {
            id: "os-trust",
            title: "系统级策略与恢复",
            status: "长期押注",
            horizon: "信任模型",
            summary: "系统越大，信任模型就必须越强。",
            detail: "审批、回滚、可恢复性和可审计性不能随着系统扩张而消失。",
            signals: ["系统级回滚", "可恢复性", "内建安全姿态"],
            tone: "vision",
          },
        ],
      },
    ],
  };
}

function getRoadmapContent(locale: SiteLocale): RoadmapContent {
  if (locale === "ja-JP") {
    return getJapaneseRoadmapContent();
  }
  if (locale === "zh-CN") {
    return getChineseRoadmapContent();
  }
  return getEnglishRoadmapContent();
}

export function SiteRoadmapPage({ locale = "en" }: { locale?: SiteLocale }) {
  const content = getRoadmapContent(locale);
  return <RoadmapShell chapters={content.chapters} repoSnapshot={content.repoSnapshot} copy={content.shellCopy} />;
}
