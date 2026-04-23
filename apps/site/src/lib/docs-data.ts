export const DOC_LOCALES = ["en", "ja-JP", "zh-CN"] as const;

export type DocLocale = (typeof DOC_LOCALES)[number];

export type DocGroupKey = "start" | "product" | "help";
export type DocPageKey =
  | "home"
  | "getting-started"
  | "install"
  | "first-run"
  | "everyday-use"
  | "tasks-memory-automation"
  | "plugins"
  | "regional-access"
  | "faq"
  | "troubleshooting"
  | "privacy-security";

export type DocSection = {
  title: string;
  paragraphs?: string[];
  bullets?: string[];
  checklist?: string[];
  callout?: string;
};

export type LocalizedDocPage = {
  title: string;
  description: string;
  summary: string;
  eyebrow: string;
  sections: DocSection[];
};

export type LocaleContent = {
  localeLabel: string;
  docsLabel: string;
  docsIntro: string;
  languageSwitcherLabel: string;
  sectionLabel: string;
  navLabel: string;
  previousLabel: string;
  nextLabel: string;
  groups: Record<DocGroupKey, string>;
  pages: Record<DocPageKey, LocalizedDocPage>;
};

export type DocPageMeta = { key: DocPageKey; slug: string[]; group: DocGroupKey };

export const DOC_PAGE_ORDER: DocPageMeta[] = [
  { key: "home", slug: [], group: "start" },
  { key: "getting-started", slug: ["getting-started"], group: "start" },
  { key: "install", slug: ["install"], group: "start" },
  { key: "first-run", slug: ["first-run"], group: "start" },
  { key: "everyday-use", slug: ["everyday-use"], group: "product" },
  { key: "tasks-memory-automation", slug: ["tasks-memory-automation"], group: "product" },
  { key: "plugins", slug: ["plugins"], group: "product" },
  { key: "regional-access", slug: ["regional-access"], group: "help" },
  { key: "faq", slug: ["faq"], group: "help" },
  { key: "troubleshooting", slug: ["troubleshooting"], group: "help" },
  { key: "privacy-security", slug: ["privacy-security"], group: "help" },
];

export const DOCS_COPY: Record<DocLocale, LocaleContent> = {
  en: {
    localeLabel: "English",
    docsLabel: "Documentation",
    docsIntro: "Public docs for installing, learning, and safely using Thomas.",
    languageSwitcherLabel: "Language",
    sectionLabel: "On this page",
    navLabel: "Documentation navigation",
    previousLabel: "Previous",
    nextLabel: "Next",
    groups: { start: "Start Here", product: "Using Thomas", help: "Help & Safety" },
    pages: {
      home: {
        title: "Thomas Documentation",
        description: "Public docs for Thomas.",
        summary: "Start here if you want the normal-user path instead of internal repo notes.",
        eyebrow: "Docs",
        sections: [
          {
            title: "What these docs cover",
            paragraphs: [
              "These pages explain Thomas in plain language. They are for setup, first-run success, normal usage, plugins, troubleshooting, and safety.",
            ],
            bullets: ["Install", "First run", "Everyday use", "Tasks and automation", "Plugins", "Troubleshooting", "Privacy and security"],
          },
          {
            title: "Best reading order",
            checklist: [
              "Read Getting Started.",
              "Read Install.",
              "Read First Run.",
              "Read Everyday Use after your first successful session.",
            ],
            callout: "Thomas is still early. Start with small, reviewable tasks before trusting bigger workflows.",
          },
        ],
      },
      "getting-started": {
        title: "Getting Started",
        description: "What Thomas is and how to approach it.",
        summary: "Thomas is a local-first execution system built around visibility, approvals, and repeatable work.",
        eyebrow: "Start Here",
        sections: [
          {
            title: "What Thomas is",
            paragraphs: [
              "Thomas helps turn plain-English requests into tracked work. It is meant to stay useful without hiding important actions from you.",
            ],
            bullets: ["Local-first direction", "Approval-aware behavior", "Designed to grow from simple use into automation"],
          },
          {
            title: "How to start safely",
            checklist: [
              "Pick one concrete task.",
              "Review the result closely.",
              "Only after that, try larger or repeatable workflows.",
            ],
          },
        ],
      },
      install: {
        title: "Install",
        description: "How to download and install Thomas.",
        summary: "The website download flow is the normal path. Regular users should not need GitHub.",
        eyebrow: "Start Here",
        sections: [
          {
            title: "Download path",
            paragraphs: ["Use the Thomas website to download the correct build for your platform."],
            checklist: [
              "Choose the right operating system.",
              "Run the installer or package from the account that will use Thomas.",
              "Launch Thomas after install and continue to First Run.",
            ],
          },
          {
            title: "Important note",
            bullets: [
              "Windows is the simplest install path today.",
              "macOS and Linux may depend on current published artifacts.",
              "Locked-down environments may require extra permission work.",
            ],
          },
        ],
      },
      "first-run": {
        title: "First Run",
        description: "How to get through initial setup.",
        summary: "Your first goal is simple: make Thomas open, connect, and complete one small request correctly.",
        eyebrow: "Start Here",
        sections: [
          {
            title: "First-run goal",
            paragraphs: ["Do not try to configure everything on day one. Get one working model path and one successful request first."],
          },
          {
            title: "Recommended sequence",
            checklist: [
              "Launch Thomas.",
              "Use guided or easy setup.",
              "Choose a working model path.",
              "Send one simple request.",
              "Only then explore tasks, memory, and automation.",
            ],
          },
        ],
      },
      "everyday-use": {
        title: "Everyday Use",
        description: "Normal daily usage patterns.",
        summary: "The normal pattern is: ask clearly, inspect the result, and approve risky steps when needed.",
        eyebrow: "Using Thomas",
        sections: [
          {
            title: "Good early uses",
            bullets: [
              "Turn a goal into a checklist",
              "Summarize work or conversations",
              "Prepare follow-up actions",
              "Test a safe workflow before automating it",
            ],
          },
          {
            title: "What to avoid at first",
            bullets: [
              "Approving actions you do not understand",
              "Jumping into high-risk automation immediately",
              "Assuming Thomas knows context you never gave it",
            ],
          },
        ],
      },
      "tasks-memory-automation": {
        title: "Tasks, Memory, and Automation",
        description: "Core Thomas concepts in plain language.",
        summary: "Tasks help track work, memory helps keep context, and automation helps repeat what already works.",
        eyebrow: "Using Thomas",
        sections: [
          {
            title: "Tasks and memory",
            paragraphs: ["Use tasks when work has multiple steps or needs to stay visible. Use memory to preserve only the important context, not every detail forever."],
          },
          {
            title: "Automation order",
            checklist: [
              "Do it manually once.",
              "Make it repeatable.",
              "Only then automate it.",
            ],
            callout: "Skipping straight to full automation is the fastest way to create avoidable mistakes.",
          },
        ],
      },
      plugins: {
        title: "Plugins",
        description: "How plugins fit into Thomas.",
        summary: "Plugins expand Thomas into focused capabilities, but trust and clarity matter more than quantity.",
        eyebrow: "Using Thomas",
        sections: [
          {
            title: "How to approach plugins",
            checklist: [
              "Start with trusted plugins.",
              "Understand the plugin before installing it.",
              "Add one plugin at a time if you are new.",
            ],
          },
          {
            title: "Marketplace expectation",
            bullets: [
              "Discovery should be easy.",
              "Install and uninstall should stay understandable.",
              "Permissions and trust should be visible.",
            ],
          },
        ],
      },
      "regional-access": {
        title: "Regional Access",
        description: "What international users should know before downloading or running Thomas.",
        summary: "Translated docs help people understand Thomas, but region support also depends on downloads, provider access, and network reliability.",
        eyebrow: "Help & Safety",
        sections: [
          {
            title: "Translation is not the whole problem",
            paragraphs: [
              "A translated website is only one part of international support. People still need a reliable download path, a working model or provider path, and predictable access to the services Thomas depends on.",
            ],
          },
          {
            title: "What to plan for by region",
            bullets: [
              "A website download path that does not depend only on GitHub",
              "Providers or local-model options that work in the target region",
              "A support path for slower networks or blocked third-party assets",
            ],
          },
          {
            title: "Special note for mainland China",
            paragraphs: [
              "If you want serious China support, you should assume GitHub, some CDNs, and some AI providers may be slow or blocked. Plan for mirrored downloads, fewer blocked frontend assets, and at least one model path that works reliably there.",
            ],
          },
        ],
      },
      faq: {
        title: "FAQ",
        description: "Common questions from new Thomas users.",
        summary: "Short answers to the questions people usually ask before they trust a new system like Thomas.",
        eyebrow: "Help & Safety",
        sections: [
          {
            title: "Do I need GitHub to use Thomas?",
            paragraphs: ["No. The website download flow should be the normal path for regular users."],
          },
          {
            title: "Do I need to be a programmer?",
            paragraphs: ["No. Thomas is intended to accept plain-English requests and reveal important actions before you approve them."],
          },
          {
            title: "Should I automate everything right away?",
            paragraphs: ["No. Start with one small workflow, review it, repeat it manually if needed, and only then automate it."],
          },
          {
            title: "What if my region has network restrictions?",
            paragraphs: ["Use the regional-access guidance and prefer download paths and model options that are stable in your region."],
          },
        ],
      },
      troubleshooting: {
        title: "Troubleshooting",
        description: "What to do when Thomas is not behaving correctly.",
        summary: "Simplify the situation first. Confirm install, confirm connection, then confirm one simple request works.",
        eyebrow: "Help & Safety",
        sections: [
          {
            title: "Fast recovery path",
            checklist: [
              "Restart Thomas.",
              "Use doctor or repair if available.",
              "Check the model path.",
              "Try one simple request.",
            ],
          },
          {
            title: "Common issues",
            bullets: [
              "Setup loops or reopens",
              "Model connection fails",
              "A task stalls",
              "Behavior changes after configuration edits",
            ],
          },
        ],
      },
      "privacy-security": {
        title: "Privacy & Security",
        description: "How to think about safe usage.",
        summary: "Thomas should stay useful without becoming reckless. You should be able to review actions, protect secrets, and understand your setup.",
        eyebrow: "Help & Safety",
        sections: [
          {
            title: "Safe usage basics",
            bullets: [
              "Use approvals for risky actions.",
              "Do not paste secrets into bug reports.",
              "Review plugin trust before installing.",
              "Understand your model path before using sensitive data.",
            ],
          },
          {
            title: "International usage",
            paragraphs: [
              "Language support and infrastructure support are different. Translated docs help people read the product, but downloads, provider access, and network reliability can still vary by region.",
            ],
          },
        ],
      },
    },
  },
  "ja-JP": {
    localeLabel: "日本語",
    docsLabel: "ドキュメント",
    docsIntro: "Thomas の導入、学習、安全な利用のための公開ドキュメントです。",
    languageSwitcherLabel: "言語",
    sectionLabel: "このページの内容",
    navLabel: "ドキュメントナビゲーション",
    previousLabel: "前へ",
    nextLabel: "次へ",
    groups: { start: "はじめに", product: "Thomas の使い方", help: "ヘルプと安全性" },
    pages: {
      home: {
        title: "Thomas ドキュメント",
        description: "Thomas の公開ドキュメントです。",
        summary: "内部の技術文書ではなく、一般利用者向けの入口です。",
        eyebrow: "ドキュメント",
        sections: [
          {
            title: "このドキュメントで扱う内容",
            paragraphs: ["導入、初回セットアップ、日常利用、プラグイン、トラブル対応、安全な使い方を平易に説明します。"],
            bullets: ["Install", "First Run", "Everyday Use", "Tasks and Automation", "Plugins", "Troubleshooting", "Privacy and Security"],
          },
          {
            title: "おすすめの読み順",
            checklist: ["Getting Started を読む", "Install を読む", "First Run を読む", "最初の成功後に Everyday Use を読む"],
            callout: "Thomas はまだ初期段階です。まずは小さく確認しやすい作業から始めてください。",
          },
        ],
      },
      "getting-started": {
        title: "Getting Started",
        description: "Thomas とは何か、どう始めるか。",
        summary: "Thomas は、可視性と承認を重視するローカルファーストの実行システムです。",
        eyebrow: "はじめに",
        sections: [
          {
            title: "Thomas とは",
            paragraphs: ["自然な言葉の依頼を、追跡しやすい仕事へ変えることを目指した製品です。重要な操作を見失わないことが前提です。"],
            bullets: ["ローカルファースト志向", "承認を前提にした挙動", "シンプルな利用から自動化へ拡張"],
          },
          {
            title: "安全な始め方",
            checklist: ["具体的な小さな作業を一つ選ぶ", "結果をよく確認する", "その後で大きな流れへ進む"],
          },
        ],
      },
      install: {
        title: "Install",
        description: "Thomas のダウンロードと導入方法。",
        summary: "通常の配布経路は Web サイトです。一般利用者は GitHub を使う必要はありません。",
        eyebrow: "はじめに",
        sections: [
          {
            title: "ダウンロード経路",
            paragraphs: ["自分のプラットフォームに合ったビルドを Web サイトから選んでください。"],
            checklist: ["正しい OS を選ぶ", "実際に使うアカウントで導入する", "導入後に Thomas を起動する"],
          },
          {
            title: "注意点",
            bullets: ["現在は Windows が最も簡単です。", "macOS と Linux は公開ビルド状況に左右されます。", "制限の強い環境では追加設定が必要です。"],
          },
        ],
      },
      "first-run": {
        title: "First Run",
        description: "初回セットアップの進め方。",
        summary: "最初の目標は、起動、接続、簡単な依頼の成功です。",
        eyebrow: "はじめに",
        sections: [
          {
            title: "初回の目標",
            paragraphs: ["一日目に全部を設定する必要はありません。まずは動く状態を一つ作ってください。"],
          },
          {
            title: "おすすめの順番",
            checklist: ["Thomas を起動する", "ガイド付きセットアップを進める", "動くモデル経路を選ぶ", "簡単な依頼を一つ送る", "その後に機能を広げる"],
          },
        ],
      },
      "everyday-use": {
        title: "Everyday Use",
        description: "日常的な使い方。",
        summary: "自然な言葉で依頼し、結果を確認し、必要なら承認して進めます。",
        eyebrow: "Thomas の使い方",
        sections: [
          {
            title: "最初に向いている使い方",
            bullets: ["目標からチェックリストを作る", "会話や作業を要約する", "次の行動を整理する", "安全な流れを一度試す"],
          },
          {
            title: "最初に避けたいこと",
            bullets: ["意味が分からない承認を通す", "高リスク自動化をいきなり任せる", "伝えていない文脈を当然だと思う"],
          },
        ],
      },
      "tasks-memory-automation": {
        title: "Tasks, Memory, and Automation",
        description: "Thomas の中心概念。",
        summary: "タスクは仕事を追跡し、メモリは文脈を保ち、オートメーションは再利用を助けます。",
        eyebrow: "Thomas の使い方",
        sections: [
          {
            title: "タスクとメモリ",
            paragraphs: ["手順が複数ある仕事はタスク化し、重要な文脈だけをメモリとして残すのが基本です。"],
          },
          {
            title: "自動化の順番",
            checklist: ["まず手動で一回やる", "次に繰り返し可能にする", "最後に自動化する"],
            callout: "いきなり全面自動化に進むと、避けられる失敗が増えます。",
          },
        ],
      },
      plugins: {
        title: "Plugins",
        description: "プラグインの考え方。",
        summary: "プラグインは Thomas を拡張しますが、数より信頼が重要です。",
        eyebrow: "Thomas の使い方",
        sections: [
          {
            title: "プラグインの使い方",
            checklist: ["信頼できるものから始める", "入れる前に役割を理解する", "最初は一つずつ追加する"],
          },
          {
            title: "マーケットプレイスで大事なこと",
            bullets: ["見つけやすさ", "分かりやすい導入と削除", "権限と信頼の可視化"],
          },
        ],
      },
      "regional-access": {
        title: "Regional Access",
        description: "海外利用者が知っておくべきこと。",
        summary: "翻訳だけでなく、配布経路、モデル経路、ネットワーク条件まで含めて地域対応を考える必要があります。",
        eyebrow: "ヘルプと安全性",
        sections: [
          {
            title: "翻訳だけでは十分ではない",
            paragraphs: ["その地域で安定してダウンロードできること、使えるモデル経路があること、そしてサイト自体が重い外部依存で壊れないことが必要です。"],
          },
          {
            title: "地域ごとの準備",
            bullets: [
              "GitHub だけに依存しない配布経路",
              "地域で利用可能なプロバイダまたはローカルモデル",
              "外部アセット依存を減らしたサイト設計",
            ],
          },
          {
            title: "中国本土向けの注意",
            paragraphs: ["中国本土を重視するなら、GitHub、一部 CDN、AI プロバイダが使いにくい前提で、ミラー配布や安定したモデル経路を用意してください。"],
          },
        ],
      },
      faq: {
        title: "FAQ",
        description: "よくある質問。",
        summary: "初めての利用者が気にする基本的な疑問への短い回答です。",
        eyebrow: "ヘルプと安全性",
        sections: [
          {
            title: "GitHub は必要ですか",
            paragraphs: ["いいえ。通常の利用者は Web サイトからダウンロードして使う想定です。"],
          },
          {
            title: "プログラマでなくても使えますか",
            paragraphs: ["はい。自然な言葉の依頼から始められるように作られています。"],
          },
          {
            title: "最初から全部自動化すべきですか",
            paragraphs: ["いいえ。小さな流れを手動で確認し、理解してから自動化するのが安全です。"],
          },
          {
            title: "地域にネットワーク制約がある場合はどうしますか",
            paragraphs: ["Regional Access の案内を確認し、その地域で安定する配布経路とモデル経路を選んでください。"],
          },
        ],
      },
      troubleshooting: {
        title: "Troubleshooting",
        description: "問題が起きた時の基本対応。",
        summary: "まず状況を単純化し、導入、接続、簡単な依頼の順に確認します。",
        eyebrow: "ヘルプと安全性",
        sections: [
          {
            title: "早い復旧手順",
            checklist: ["Thomas を再起動する", "doctor や repair を使う", "モデル接続を確認する", "簡単な依頼を試す"],
          },
          {
            title: "よくある問題",
            bullets: ["セットアップが繰り返される", "モデル接続が失敗する", "タスクが止まる", "設定変更後に挙動が変わる"],
          },
        ],
      },
      "privacy-security": {
        title: "Privacy & Security",
        description: "安全な使い方の考え方。",
        summary: "重要な操作は確認し、秘密情報は守り、利用環境を理解して使うことが大切です。",
        eyebrow: "ヘルプと安全性",
        sections: [
          {
            title: "安全利用の基本",
            bullets: ["危険な操作には承認を使う", "バグ報告に秘密情報を含めない", "プラグインの信頼性を確認する", "機密データの前にモデル経路を理解する"],
          },
          {
            title: "海外利用について",
            paragraphs: ["多言語対応とインフラ対応は別です。翻訳されていても、ダウンロードやネットワーク事情は地域ごとに異なります。"],
          },
        ],
      },
    },
  },
  "zh-CN": {
    localeLabel: "简体中文",
    docsLabel: "文档",
    docsIntro: "这是 Thomas 面向公开用户的安装、学习与安全使用文档。",
    languageSwitcherLabel: "语言",
    sectionLabel: "本页内容",
    navLabel: "文档导航",
    previousLabel: "上一页",
    nextLabel: "下一页",
    groups: { start: "开始使用", product: "使用 Thomas", help: "帮助与安全" },
    pages: {
      home: {
        title: "Thomas 文档",
        description: "Thomas 的公共文档。",
        summary: "这里是普通用户的入口，不是内部工程文档。",
        eyebrow: "文档",
        sections: [
          {
            title: "文档覆盖范围",
            paragraphs: ["这些页面会用更容易理解的方式说明安装、首次启动、日常使用、插件、故障排查以及安全使用。"],
            bullets: ["Install", "First Run", "Everyday Use", "Tasks and Automation", "Plugins", "Troubleshooting", "Privacy and Security"],
          },
          {
            title: "建议阅读顺序",
            checklist: ["先读 Getting Started", "再读 Install", "然后读 First Run", "第一次成功之后读 Everyday Use"],
            callout: "Thomas 仍然很早期。先从小而可检查的事情开始，不要一开始就上复杂自动化。",
          },
        ],
      },
      "getting-started": {
        title: "Getting Started",
        description: "Thomas 是什么，以及怎么开始。",
        summary: "Thomas 是一个强调可见性、审批和可重复工作的本地优先执行系统。",
        eyebrow: "开始使用",
        sections: [
          {
            title: "Thomas 是什么",
            paragraphs: ["它的目标是把自然语言请求转成更清晰、更可跟踪的工作，并尽量不把重要动作藏起来。"],
            bullets: ["本地优先方向", "重视审批", "从简单使用逐步走向自动化"],
          },
          {
            title: "安全开始的方法",
            checklist: ["先挑一件很具体的小事", "认真检查结果", "确认没问题后再扩展到更大的流程"],
          },
        ],
      },
      install: {
        title: "Install",
        description: "如何下载和安装 Thomas。",
        summary: "普通用户的正常入口是网站，不应该要求先去用 GitHub。",
        eyebrow: "开始使用",
        sections: [
          {
            title: "下载路径",
            paragraphs: ["请从网站选择与你的平台匹配的构建。"],
            checklist: ["选对操作系统", "用实际会运行 Thomas 的账户安装", "安装后启动 Thomas"],
          },
          {
            title: "注意事项",
            bullets: ["当前最简单的是 Windows 路径", "macOS 和 Linux 体验可能取决于当前发布工件", "受限环境可能需要额外权限配置"],
          },
        ],
      },
      "first-run": {
        title: "First Run",
        description: "首次启动配置。",
        summary: "第一次的目标很简单：打开、连接成功、完成一次小请求。",
        eyebrow: "开始使用",
        sections: [
          {
            title: "首次目标",
            paragraphs: ["第一天不需要把所有高级功能都配置完。先让一个基础路径跑通。"],
          },
          {
            title: "推荐顺序",
            checklist: ["启动 Thomas", "走引导或简单设置", "选一个可用的模型路径", "发一个简单请求", "然后再扩展功能"],
          },
        ],
      },
      "everyday-use": {
        title: "Everyday Use",
        description: "日常使用方式。",
        summary: "最正常的模式是：说清楚需求，检查结果，必要时批准风险动作。",
        eyebrow: "使用 Thomas",
        sections: [
          {
            title: "适合一开始做的事",
            bullets: ["把目标拆成清单", "整理对话或工作内容", "生成下一步行动", "先试一次安全流程再谈自动化"],
          },
          {
            title: "一开始不要做的事",
            bullets: ["批准自己没看懂的动作", "马上做高风险自动化", "默认 Thomas 已经知道你没说的背景"],
          },
        ],
      },
      "tasks-memory-automation": {
        title: "Tasks, Memory, and Automation",
        description: "Thomas 的核心概念。",
        summary: "任务用于跟踪工作，记忆用于保留上下文，自动化用于复用已经验证有效的流程。",
        eyebrow: "使用 Thomas",
        sections: [
          {
            title: "任务和记忆",
            paragraphs: ["多步骤工作用任务来保持可见性，记忆只保留真正重要的上下文，而不是保存一切。"],
          },
          {
            title: "自动化顺序",
            checklist: ["先手动做一遍", "再让它可重复", "最后再自动化"],
            callout: "还没理解流程就直接自动化，是最容易制造问题的方式之一。",
          },
        ],
      },
      plugins: {
        title: "Plugins",
        description: "插件在 Thomas 中的作用。",
        summary: "插件可以扩展 Thomas，但信任和清晰度比数量更重要。",
        eyebrow: "使用 Thomas",
        sections: [
          {
            title: "插件使用方式",
            checklist: ["从可信来源开始", "安装前先理解作用", "新用户建议一次一个"],
          },
          {
            title: "市场应该做到什么",
            bullets: ["容易发现", "容易安装和移除", "权限与信任可见"],
          },
        ],
      },
      "regional-access": {
        title: "Regional Access",
        description: "国际地区使用前需要知道的事。",
        summary: "翻译只是第一步，真正的地区支持还取决于下载路径、模型路径和网络可靠性。",
        eyebrow: "帮助与安全",
        sections: [
          {
            title: "翻译不是全部",
            paragraphs: ["要让国际用户真正用起来，除了语言，还需要稳定的下载路径、可用的模型方案，以及尽量少依赖被阻断的外部资源。"],
          },
          {
            title: "按地区应准备的内容",
            bullets: [
              "不只依赖 GitHub 的下载路径",
              "在该地区可访问的提供商或本地模型方案",
              "在网络受限环境下仍能工作的站点资源策略",
            ],
          },
          {
            title: "关于中国大陆",
            paragraphs: ["如果你想认真支持中国大陆用户，就应该假设 GitHub、部分 CDN 和部分 AI 提供商会变慢或不可用。需要准备镜像下载和稳定的模型路径。"],
          },
        ],
      },
      faq: {
        title: "FAQ",
        description: "常见问题。",
        summary: "新用户在信任 Thomas 之前最常问的几个问题。",
        eyebrow: "帮助与安全",
        sections: [
          {
            title: "使用 Thomas 需要 GitHub 吗",
            paragraphs: ["不需要。普通用户应该直接通过网站下载。"],
          },
          {
            title: "我不是程序员也能用吗",
            paragraphs: ["可以。Thomas 的目标就是让你先用自然语言完成工作，再逐步理解更深层能力。"],
          },
          {
            title: "应该一开始就做自动化吗",
            paragraphs: ["不应该。先手动验证一个小流程，再逐步做成可重复和自动化。"],
          },
          {
            title: "如果我所在地区网络受限怎么办",
            paragraphs: ["请先阅读 Regional Access，并优先选择在你所在地区稳定的下载和模型路径。"],
          },
        ],
      },
      troubleshooting: {
        title: "Troubleshooting",
        description: "出问题时先做什么。",
        summary: "先把情况简化，再确认安装、连接和一个简单请求是否正常。",
        eyebrow: "帮助与安全",
        sections: [
          {
            title: "快速恢复路径",
            checklist: ["重启 Thomas", "使用 doctor 或 repair", "确认模型路径", "试一个简单请求"],
          },
          {
            title: "常见问题",
            bullets: ["设置反复重开", "模型连接失败", "任务卡住", "改配置后行为异常"],
          },
        ],
      },
      "privacy-security": {
        title: "Privacy & Security",
        description: "如何安全地使用 Thomas。",
        summary: "重要动作要可检查，秘密信息要保护，使用前要理解自己的配置。",
        eyebrow: "帮助与安全",
        sections: [
          {
            title: "安全基础",
            bullets: ["风险操作使用审批", "不要在报错里放密钥", "安装前确认插件可信", "处理敏感数据前理解模型路径"],
          },
          {
            title: "国际地区使用",
            paragraphs: ["多语言支持不等于网络和基础设施支持。即使页面翻译好了，不同地区的下载、网络和提供商可用性仍然不同。"],
          },
        ],
      },
    },
  },
};
