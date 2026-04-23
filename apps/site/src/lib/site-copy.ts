import type { SiteLocale } from "@/lib/site-locale";

type NavKey = "home" | "download" | "docs" | "marketplace" | "roadmap" | "updates" | "journey" | "deep-dive" | "support";

type ShellCopy = {
  nav: Record<NavKey, string>;
  languageLabel: string;
  footerTitle: string;
  footerCopy: string;
  footerWarning: string;
  footerLinks: {
    download: string;
    roadmap: string;
    updates: string;
    journey: string;
    deepDive: string;
    support: string;
    github: string;
  };
};

type HomeCopy = {
  howItWorks: string;
  whyItMatters: string;
  heroSecondary: string;
  outcomesTitle: string;
  outcomesIntro: string;
  latestUpdates: string;
  fullChangelog: string;
  roadAhead: string;
  roadAheadTitle: string;
  roadAheadBody: string;
  roadmapCardKicker: string;
  roadmapCardTitle: string;
  roadmapCardBody: string;
  roadmapPrimary: string;
  roadmapSecondary: string;
  corePromise: Array<{ title: string; text: string }>;
  regularOutcomes: Array<{ title: string; summary: string; example: string }>;
  roadmapSteps: Array<{ step: string; title: string; text: string }>;
};

type DownloadCopy = {
  title: string;
  description: string;
  eyebrow: string;
  verifyTitle: string;
  digestsPublished: string;
  digestsMissing: string;
  checksumSuffix: string;
  digestReference: string;
  featurePluginsTitle: string;
  featurePluginsIntro: string;
  officialPlugin: string;
  openInThomas: string;
  downloadZip: string;
  installNotesTitle: string;
  systemRequirementsTitle: string;
  versionHistoryTitle: string;
  noHistory: string;
  fullNotes: string;
  statusManual: string;
  statusReleaseMissing: string;
  statusAssetMissing: string;
  pluginSubtitle: string;
  pluginDescription: string;
  platformLabels: { windows: string; macos: string; linux: string };
};

type SupportCopy = {
  title: string;
  description: string;
  intro: string;
  reportIssue: string;
  openIssue: string;
  githubUnavailable: string;
  whatToInclude: string;
  whatToIncludeIntro: string;
  issueTemplate: string;
  issueTemplateIntro: string;
  commonFixes: string;
  installerFix: string;
  commandBlocked: string;
  behaviorWrong: string;
  securityWarning: string;
  bullets: {
    command: string;
    error: string;
    os: string;
    repro: string;
  };
};

type UpdatesCopy = {
  title: string;
  description: string;
  liveData: string;
  cachedData: string;
  unavailableData: string;
  unavailableMessagePrefix: string;
  unavailableMessageSuffixLive: string;
  unavailableMessageSuffixCached: string;
  unavailableMessageSuffixUnavailable: string;
};

type ComponentCopy = {
  downloadButton: string;
  metrics: {
    downloadIntents: string;
    githubDownloads: string;
    latestRelease: string;
    unavailable: string;
  };
  releaseFeed: {
    empty: string;
    localNote: string;
    fullNotes: string;
    assetDownloadsSuffix: string;
  };
  updatesFeed: {
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

type SiteCopy = {
  shell: ShellCopy;
  home: HomeCopy;
  download: DownloadCopy;
  support: SupportCopy;
  updates: UpdatesCopy;
  components: ComponentCopy;
};

const SITE_COPY: Record<SiteLocale, SiteCopy> = {
  en: {
    shell: {
      nav: {
        home: "Home",
        download: "Download",
        docs: "Documentation",
        marketplace: "Marketplace",
        roadmap: "Roadmap",
        updates: "Updates",
        journey: "Journey",
        "deep-dive": "How It Works",
        support: "Support",
      },
      languageLabel: "Language",
      footerTitle: "Thomas",
      footerCopy: "Local-first execution system for verified desktop workflows.",
      footerWarning: "Use this with explicit command approval and AI-safe auditable release metadata.",
      footerLinks: {
        download: "Download",
        roadmap: "Roadmap",
        updates: "Updates",
        journey: "Journey",
        deepDive: "Deep Dive",
        support: "Support",
        github: "GitHub (Advanced)",
      },
    },
    home: {
      howItWorks: "How it works",
      whyItMatters: "Why this project matters",
      heroSecondary: "How It Works",
      outcomesTitle: "No jargon, just outcomes",
      outcomesIntro: "What Thomas changes for day-to-day work if you are not a career software engineer.",
      latestUpdates: "Latest Updates",
      fullChangelog: "Open full changelog",
      roadAhead: "The Road Ahead",
      roadAheadTitle: "Thomas is not the final form yet.",
      roadAheadBody:
        "The live build is the controlled core. The roadmap shows where this goes next: a private-network app layer on your phone, then an AI-native operating system built around Thomas from the ground up.",
      roadmapCardKicker: "Roadmap",
      roadmapCardTitle: "See where Thomas goes next.",
      roadmapCardBody:
        "See the three-stage plan: the current core, the Infinite phone layer, and the long-range Thomas OS vision. It is the clearest view of where the product is headed next.",
      roadmapPrimary: "Explore roadmap",
      roadmapSecondary: "See the journey",
      corePromise: [
        { title: "Single-click execution path", text: "The same intent input is routed through the same planning and safety layer every time, so behavior stays predictable under load and reuse." },
        { title: "Deterministic guardrails", text: "Each workflow runs through explicit constraints, preflight checks, and explicit approval points before destructive actions can execute." },
        { title: "No magic defaults", text: "When context is missing, Thomas asks for explicit operator input instead of fabricating assumptions in the workflow graph." },
        { title: "Public implementation trail", text: "Release artifacts, technical notes, and changelog are kept in one place so each release decision can be reviewed quickly." },
        { title: "Built for operators who ship", text: "The interface optimizes for fast correction, rollback visibility, and low-friction iteration rather than polished perfectionism." },
      ],
      regularOutcomes: [
        { title: "For solo builders", summary: "Turn one request into a repeatable process without learning a long command list.", example: "\"Run my weekly report workflow and prep a clear summary before my Friday meeting.\"" },
        { title: "For support teams", summary: "Handle triage and repetitive follow-ups with less context switching and fewer manual handoffs.", example: "\"Pull open tickets, group blockers by owner, and draft next actions for each team.\"" },
        { title: "For non-technical operators", summary: "Use outcome-driven prompts in plain English, then inspect what happened before approving next steps.", example: "\"Set up my cleanup checklist, show me what changed, and ask before doing anything risky.\"" },
      ],
      roadmapSteps: [
        { step: "01 / Thomas Core", title: "Pre-alpha trust boundary", text: "Local-first execution, explicit approvals, and reproducible behavior before anything bigger ships." },
        { step: "02 / Thomas Infinite", title: "Private phone app layer", text: "Use Tailscale to push headless web experiences to your phone so Thomas can create app surfaces on demand." },
        { step: "03 / Thomas OS", title: "AI-native Linux system", text: "The long bet: an operating system where AI is part of the stack itself, not bolted onto it later." },
      ],
    },
    download: {
      title: "Download Thomas",
      description: "Download Thomas for Windows, Mac, or Linux.",
      eyebrow: "Download",
      verifyTitle: "Verify your download",
      digestsPublished: "SHA-256 digests were published with this release.",
      digestsMissing: "SHA-256 digests will appear here when published.",
      checksumSuffix: "checksum command",
      digestReference: "Published digest reference",
      featurePluginsTitle: "Feature plugins",
      featurePluginsIntro: "Automatic install opens Thomas with a thomas:// deep link. If the protocol handler is unavailable, download the plugin ZIP and import it from Thomas Marketplace with Install From File.",
      officialPlugin: "Official plugin",
      openInThomas: "Open in Thomas",
      downloadZip: "Download ZIP",
      installNotesTitle: "Platform install notes",
      systemRequirementsTitle: "System Requirements",
      versionHistoryTitle: "Version history",
      noHistory: "No release history is available yet.",
      fullNotes: "View full release notes on GitHub",
      statusManual: "Downloads are not configured yet. Add THOMAS_DOWNLOAD_URL_* env vars in production.",
      statusReleaseMissing: "No public release is available yet. Publish a release or set manual URLs.",
      statusAssetMissing: "Release exists, but no installer matched that platform and channel.",
      pluginSubtitle: "Tasks, agenda, habits, and goals in one local-first plugin.",
      pluginDescription: "Installs as its own Thomas sidebar tab and keeps all state local to your active Thomas profile.",
      platformLabels: { windows: "Windows", macos: "Mac", linux: "Linux" },
    },
    support: {
      title: "Support",
      description: "Get help with Thomas or report an issue.",
      intro: "Found a bug or need help? Here's how to reach us.",
      reportIssue: "Report an issue",
      openIssue: "Open a GitHub Issue",
      githubUnavailable: "GitHub issue reporting will be available once repository integration is configured.",
      whatToInclude: "What to include",
      whatToIncludeIntro: "A good bug report helps us fix things fast. Tell us:",
      issueTemplate: "Issue template",
      issueTemplateIntro: "Copy and paste this into your GitHub issue:",
      commonFixes: "Common fixes",
      installerFix: "Installer won't run",
      commandBlocked: "Command blocked or denied",
      behaviorWrong: "Something isn't working right",
      securityWarning: "Please don't include API keys, tokens, or passwords in bug reports. Replace them with placeholders.",
      bullets: {
        command: "What command you ran (or what you clicked).",
        error: "The error message you saw.",
        os: "Your OS and Thomas version.",
        repro: "Steps to reproduce the issue, if possible.",
      },
    },
    updates: {
      title: "What's New",
      description: "Release notes and updates for Thomas.",
      liveData: "Release data: live GitHub feed.",
      cachedData: "Release data: local cache fallback.",
      unavailableData: "Release data: unavailable (no entries).",
      unavailableMessagePrefix: "Release feed is currently unavailable",
      unavailableMessageSuffixLive: "Showing live dataset.",
      unavailableMessageSuffixCached: "Showing cached dataset.",
      unavailableMessageSuffixUnavailable: "Showing unavailable dataset.",
    },
    components: {
      downloadButton: "Download for",
      metrics: {
        downloadIntents: "Download Intents (30d)",
        githubDownloads: "GitHub Downloads (All Time)",
        latestRelease: "Latest Release",
        unavailable: "Unavailable",
      },
      releaseFeed: {
        empty: "Release data will appear after THOMAS_GITHUB_REPO is configured.",
        localNote: "Local update note",
        fullNotes: "Full notes",
        assetDownloadsSuffix: "asset downloads",
      },
      updatesFeed: {
        releaseFeedUnavailable: "Release feed unavailable",
        noEntriesYet: "No release entries are available for this view yet.",
        noEntries: "No release entries",
        noEntriesBody: "No release data is available yet for this filter set.",
        filters: "Filters",
        version: "Version",
        allVersions: "All versions",
        fromDate: "From date",
        toDate: "To date",
        releaseSource: "Release data source",
        noMatches: "No release matches the selected filters.",
        openArtifact: "Open release artifact",
        versionPrefix: "Version",
      },
    },
  },
  "ja-JP": {
    shell: {
      nav: {
        home: "ホーム",
        download: "ダウンロード",
        docs: "ドキュメント",
        marketplace: "マーケットプレイス",
        roadmap: "ロードマップ",
        updates: "更新情報",
        journey: "ジャーニー",
        "deep-dive": "仕組み",
        support: "サポート",
      },
      languageLabel: "言語",
      footerTitle: "Thomas",
      footerCopy: "検証可能なデスクトップ作業のためのローカルファースト実行システム。",
      footerWarning: "明示的な承認と監査可能なリリース情報を前提に利用してください。",
      footerLinks: {
        download: "ダウンロード",
        roadmap: "ロードマップ",
        updates: "更新情報",
        journey: "ジャーニー",
        deepDive: "詳細",
        support: "サポート",
        github: "GitHub（上級者向け）",
      },
    },
    home: {
      howItWorks: "仕組み",
      whyItMatters: "このプロジェクトが重要な理由",
      heroSecondary: "仕組みを見る",
      outcomesTitle: "専門用語ではなく、結果で理解する",
      outcomesIntro: "キャリアのあるソフトウェアエンジニアでなくても、Thomas が日常の仕事をどう変えるかを示します。",
      latestUpdates: "最新アップデート",
      fullChangelog: "変更履歴を見る",
      roadAhead: "これから",
      roadAheadTitle: "Thomas はまだ完成形ではありません。",
      roadAheadBody: "今の公開版は信頼境界を固めたコアです。次は電話向けのプライベート層、その先に AI ネイティブな OS という流れがあります。",
      roadmapCardKicker: "ロードマップ",
      roadmapCardTitle: "Thomas の次を確認する。",
      roadmapCardBody: "現在のコア、Infinite の電話層、長期的な Thomas OS 構想までを一つの流れで確認できます。",
      roadmapPrimary: "ロードマップを見る",
      roadmapSecondary: "道のりを見る",
      corePromise: [
        { title: "一貫した実行経路", text: "同じ依頼は同じ計画・安全レイヤーを通るため、使い続けても挙動が読みやすくなります。" },
        { title: "決定的なガードレール", text: "危険な処理の前には制約、事前確認、明示的な承認点が入ります。" },
        { title: "勝手な補完をしない", text: "文脈が足りない時は、Thomas は都合のよい仮定ではなく確認を優先します。" },
        { title: "公開された実装の痕跡", text: "リリース成果物、技術メモ、変更履歴をまとめて見られるようにします。" },
        { title: "実務で動かす人のための設計", text: "完璧な見た目より、修正しやすさ、巻き戻しやすさ、反復しやすさを優先します。" },
      ],
      regularOutcomes: [
        { title: "個人の作り手向け", summary: "長いコマンドを覚えなくても、一つの依頼から繰り返し可能な流れに育てられます。", example: "\"毎週のレポートを回して、金曜会議の前に要点を整理して。\"" },
        { title: "サポートチーム向け", summary: "トリアージや定型フォローアップを、余計な切り替えなく進められます。", example: "\"未解決チケットを集めて、担当者ごとにブロッカーを整理して。\"" },
        { title: "非技術オペレーター向け", summary: "自然な言葉で依頼し、何が起きたかを確認してから次に進めます。", example: "\"片付けチェックリストを作って、変更点を見せて、危険なら聞いて。\"" },
      ],
      roadmapSteps: [
        { step: "01 / Thomas Core", title: "プレアルファの信頼境界", text: "より大きなことに進む前に、ローカルファースト、明示承認、再現性を固めます。" },
        { step: "02 / Thomas Infinite", title: "電話向けプライベート層", text: "Tailscale を使って、必要な体験を電話に安全に持っていきます。" },
        { step: "03 / Thomas OS", title: "AI ネイティブ Linux", text: "AI を後付けするのではなく、最初から AI 前提の環境を目指します。" },
      ],
    },
    download: {
      title: "Thomas をダウンロード",
      description: "Windows、Mac、Linux 向けの Thomas を入手します。",
      eyebrow: "ダウンロード",
      verifyTitle: "ダウンロードの検証",
      digestsPublished: "このリリースには SHA-256 ダイジェストが公開されています。",
      digestsMissing: "SHA-256 ダイジェストは公開され次第ここに表示されます。",
      checksumSuffix: "チェックサム確認コマンド",
      digestReference: "公開ダイジェスト一覧",
      featurePluginsTitle: "注目プラグイン",
      featurePluginsIntro: "自動インストールは thomas:// ディープリンクを開きます。利用できない場合は ZIP をダウンロードして、Thomas Marketplace の Install From File から読み込んでください。",
      officialPlugin: "公式プラグイン",
      openInThomas: "Thomas で開く",
      downloadZip: "ZIP をダウンロード",
      installNotesTitle: "プラットフォーム別メモ",
      systemRequirementsTitle: "動作要件",
      versionHistoryTitle: "バージョン履歴",
      noHistory: "利用できるリリース履歴はまだありません。",
      fullNotes: "GitHub で完全なリリースノートを見る",
      statusManual: "まだダウンロードは設定されていません。本番環境で THOMAS_DOWNLOAD_URL_* を設定してください。",
      statusReleaseMissing: "まだ公開リリースがありません。リリースを公開するか手動 URL を設定してください。",
      statusAssetMissing: "リリースはありますが、そのプラットフォームとチャネルに一致するインストーラが見つかりません。",
      pluginSubtitle: "タスク、予定、習慣、目標を一つにまとめるローカルファーストプラグイン。",
      pluginDescription: "Thomas のサイドバーに専用タブとして入り、状態はアクティブなプロフィール内に保持されます。",
      platformLabels: { windows: "Windows", macos: "Mac", linux: "Linux" },
    },
    support: {
      title: "サポート",
      description: "Thomas のヘルプや不具合報告。",
      intro: "不具合を見つけた場合や助けが必要な場合の案内です。",
      reportIssue: "問題を報告する",
      openIssue: "GitHub Issue を開く",
      githubUnavailable: "リポジトリ連携が設定されると GitHub Issue が使えるようになります。",
      whatToInclude: "含めてほしい情報",
      whatToIncludeIntro: "良い不具合報告ほど対応が早くなります。次の情報を含めてください。",
      issueTemplate: "Issue テンプレート",
      issueTemplateIntro: "この内容を GitHub Issue に貼り付けてください。",
      commonFixes: "よくある対処",
      installerFix: "インストーラが動かない",
      commandBlocked: "コマンドが拒否された",
      behaviorWrong: "期待と違う動作をする",
      securityWarning: "バグ報告には API キー、トークン、パスワードを含めないでください。置き換えて共有してください。",
      bullets: {
        command: "実行したコマンド、またはクリックした内容。",
        error: "表示されたエラーメッセージ。",
        os: "OS と Thomas のバージョン。",
        repro: "可能なら再現手順。",
      },
    },
    updates: {
      title: "更新情報",
      description: "Thomas のリリースノートと更新履歴。",
      liveData: "リリースデータ: GitHub のライブフィード。",
      cachedData: "リリースデータ: ローカルキャッシュのフォールバック。",
      unavailableData: "リリースデータ: 利用不可（エントリなし）。",
      unavailableMessagePrefix: "リリースフィードは現在利用できません",
      unavailableMessageSuffixLive: "ライブデータを表示中。",
      unavailableMessageSuffixCached: "キャッシュデータを表示中。",
      unavailableMessageSuffixUnavailable: "利用不可データセットを表示中。",
    },
    components: {
      downloadButton: "ダウンロード",
      metrics: {
        downloadIntents: "ダウンロード意図（30日）",
        githubDownloads: "GitHub ダウンロード（累計）",
        latestRelease: "最新リリース",
        unavailable: "利用不可",
      },
      releaseFeed: {
        empty: "THOMAS_GITHUB_REPO が設定されるとリリースデータが表示されます。",
        localNote: "ローカル更新メモ",
        fullNotes: "詳細",
        assetDownloadsSuffix: "ダウンロード",
      },
      updatesFeed: {
        releaseFeedUnavailable: "リリースフィードを取得できません",
        noEntriesYet: "この表示に利用できるリリース項目はまだありません。",
        noEntries: "リリース項目なし",
        noEntriesBody: "この条件ではリリースデータがまだありません。",
        filters: "フィルター",
        version: "バージョン",
        allVersions: "すべてのバージョン",
        fromDate: "開始日",
        toDate: "終了日",
        releaseSource: "リリースデータの取得元",
        noMatches: "選択した条件に一致するリリースはありません。",
        openArtifact: "リリース成果物を開く",
        versionPrefix: "バージョン",
      },
    },
  },
  "zh-CN": {
    shell: {
      nav: {
        home: "首页",
        download: "下载",
        docs: "文档",
        marketplace: "市场",
        roadmap: "路线图",
        updates: "更新",
        journey: "历程",
        "deep-dive": "工作方式",
        support: "支持",
      },
      languageLabel: "语言",
      footerTitle: "Thomas",
      footerCopy: "面向可验证桌面工作流的本地优先执行系统。",
      footerWarning: "请在明确审批和可审计发布元数据前提下使用。",
      footerLinks: {
        download: "下载",
        roadmap: "路线图",
        updates: "更新",
        journey: "历程",
        deepDive: "深度说明",
        support: "支持",
        github: "GitHub（高级）",
      },
    },
    home: {
      howItWorks: "工作方式",
      whyItMatters: "这个项目为什么重要",
      heroSecondary: "查看原理",
      outcomesTitle: "不用术语，直接看结果",
      outcomesIntro: "如果你不是职业软件工程师，Thomas 会怎样改变日常工作。",
      latestUpdates: "最新更新",
      fullChangelog: "查看完整更新记录",
      roadAhead: "接下来的方向",
      roadAheadTitle: "Thomas 还不是最终形态。",
      roadAheadBody: "当前版本是受控核心。接下来会走向手机上的私有层，再到以 Thomas 为中心构建的 AI 原生操作系统。",
      roadmapCardKicker: "路线图",
      roadmapCardTitle: "看看 Thomas 接下来会去哪里。",
      roadmapCardBody: "从当前核心，到 Infinite 手机层，再到长期的 Thomas OS 愿景，都可以在这里看到。",
      roadmapPrimary: "查看路线图",
      roadmapSecondary: "查看历程",
      corePromise: [
        { title: "单一路径执行", text: "同样的意图输入始终经过同样的规划和安全层，因此在复用和高负载下也更可预测。" },
        { title: "确定性的护栏", text: "每个工作流在执行破坏性动作前都要经过约束、预检和明确审批点。" },
        { title: "不靠神秘默认值", text: "当上下文不足时，Thomas 会要求明确输入，而不是自己编造假设。" },
        { title: "公开的实现痕迹", text: "发布产物、技术说明和更新记录集中展示，便于快速审查每次发布。" },
        { title: "为真正执行工作的人而造", text: "界面优先考虑修正速度、回滚可见性和低摩擦迭代，而不是只追求表面精致。" },
      ],
      regularOutcomes: [
        { title: "面向个人构建者", summary: "一个请求就能逐步变成可重复流程，不必先学会一长串命令。", example: "\"帮我跑每周报告，并在周五会议前整理出清晰摘要。\"" },
        { title: "面向支持团队", summary: "更少切换上下文，更少手动交接，完成分流和重复跟进。", example: "\"把未结单据拉出来，按负责人整理阻塞项，并给每队写下一步。\"" },
        { title: "面向非技术操作人员", summary: "用自然语言描述结果，再在批准下一步之前先看清楚发生了什么。", example: "\"帮我设一个清理清单，先给我看变化，再去做风险操作。\"" },
      ],
      roadmapSteps: [
        { step: "01 / Thomas Core", title: "Pre-alpha 信任边界", text: "在扩展之前，先把本地优先、明确审批和可复现行为打牢。" },
        { step: "02 / Thomas Infinite", title: "私有手机层", text: "通过 Tailscale 把按需生成的体验带到手机上。" },
        { step: "03 / Thomas OS", title: "AI 原生 Linux 系统", text: "长期目标是从系统层就围绕 AI 工作流设计，而不是后期外挂。" },
      ],
    },
    download: {
      title: "下载 Thomas",
      description: "下载适用于 Windows、Mac 或 Linux 的 Thomas。",
      eyebrow: "下载",
      verifyTitle: "校验你的下载",
      digestsPublished: "该版本已发布 SHA-256 摘要。",
      digestsMissing: "发布后这里会显示 SHA-256 摘要。",
      checksumSuffix: "校验命令",
      digestReference: "已发布摘要参考",
      featurePluginsTitle: "特色插件",
      featurePluginsIntro: "自动安装会打开 thomas:// 深链接。如果协议处理器不可用，请下载插件 ZIP，并在 Thomas Marketplace 中通过 Install From File 导入。",
      officialPlugin: "官方插件",
      openInThomas: "在 Thomas 中打开",
      downloadZip: "下载 ZIP",
      installNotesTitle: "平台安装说明",
      systemRequirementsTitle: "系统要求",
      versionHistoryTitle: "版本历史",
      noHistory: "目前还没有可用的发布历史。",
      fullNotes: "在 GitHub 上查看完整发布说明",
      statusManual: "下载尚未配置。请在生产环境中设置 THOMAS_DOWNLOAD_URL_* 环境变量。",
      statusReleaseMissing: "目前还没有公开版本。请发布版本或设置手动下载 URL。",
      statusAssetMissing: "版本存在，但没有找到匹配该平台和通道的安装包。",
      pluginSubtitle: "一个将任务、日程、习惯和目标集中到一起的本地优先插件。",
      pluginDescription: "它会作为单独的 Thomas 侧栏标签安装，并把状态保留在当前配置文件中。",
      platformLabels: { windows: "Windows", macos: "Mac", linux: "Linux" },
    },
    support: {
      title: "支持",
      description: "获取 Thomas 帮助或报告问题。",
      intro: "如果你遇到问题或需要帮助，可以从这里开始。",
      reportIssue: "报告问题",
      openIssue: "打开 GitHub Issue",
      githubUnavailable: "配置好仓库集成后，这里会提供 GitHub Issue 报告入口。",
      whatToInclude: "需要包含的信息",
      whatToIncludeIntro: "好的问题报告会让修复更快。请尽量说明：",
      issueTemplate: "Issue 模板",
      issueTemplateIntro: "把下面内容复制到 GitHub Issue 中：",
      commonFixes: "常见修复",
      installerFix: "安装器无法运行",
      commandBlocked: "命令被阻止或拒绝",
      behaviorWrong: "行为和预期不一致",
      securityWarning: "请不要在问题报告中包含 API 密钥、令牌或密码。请先做脱敏处理。",
      bullets: {
        command: "你运行了什么命令，或点击了什么。",
        error: "你看到的错误信息。",
        os: "你的操作系统和 Thomas 版本。",
        repro: "如果可能，请提供复现步骤。",
      },
    },
    updates: {
      title: "更新说明",
      description: "Thomas 的发布说明和更新记录。",
      liveData: "发布数据：GitHub 实时源。",
      cachedData: "发布数据：本地缓存回退。",
      unavailableData: "发布数据：不可用（没有条目）。",
      unavailableMessagePrefix: "发布源当前不可用",
      unavailableMessageSuffixLive: "当前显示实时数据集。",
      unavailableMessageSuffixCached: "当前显示缓存数据集。",
      unavailableMessageSuffixUnavailable: "当前显示不可用数据集。",
    },
    components: {
      downloadButton: "下载到",
      metrics: {
        downloadIntents: "下载意图（30天）",
        githubDownloads: "GitHub 下载（总计）",
        latestRelease: "最新版本",
        unavailable: "不可用",
      },
      releaseFeed: {
        empty: "配置 THOMAS_GITHUB_REPO 后，这里会显示发布数据。",
        localNote: "本地更新说明",
        fullNotes: "完整说明",
        assetDownloadsSuffix: "次资源下载",
      },
      updatesFeed: {
        releaseFeedUnavailable: "发布源不可用",
        noEntriesYet: "当前视图还没有可显示的发布条目。",
        noEntries: "没有发布条目",
        noEntriesBody: "当前筛选条件下还没有发布数据。",
        filters: "筛选",
        version: "版本",
        allVersions: "全部版本",
        fromDate: "起始日期",
        toDate: "结束日期",
        releaseSource: "发布数据来源",
        noMatches: "没有符合筛选条件的发布。",
        openArtifact: "打开发布产物",
        versionPrefix: "版本",
      },
    },
  },
};

export function getSiteCopy(locale: SiteLocale): SiteCopy {
  return SITE_COPY[locale];
}
