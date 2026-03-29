import type { Metadata } from "next";
import { getDocLocaleLinks, type ResolvedDocPage } from "@/lib/docs";
import { getCanonicalSiteUrl, siteConfig } from "@/lib/site-config";
import { SITE_LOCALES, type SiteLocale, withSiteLocale } from "@/lib/site-locale";

type RouteKey =
  | "home"
  | "download"
  | "docs"
  | "updates"
  | "journey"
  | "deep-dive"
  | "support"
  | "roadmap"
  | "marketplace"
  | "infinite";

type RouteCopy = {
  pathname: string;
  title: Record<SiteLocale, string>;
  description: Record<SiteLocale, string>;
};

const OPEN_GRAPH_LOCALE: Record<SiteLocale, string> = {
  en: "en_US",
  "ja-JP": "ja_JP",
  "zh-CN": "zh_CN",
};

const ROUTE_COPY: Record<RouteKey, RouteCopy> = {
  home: {
    pathname: "/",
    title: {
      en: siteConfig.name,
      "ja-JP": siteConfig.name,
      "zh-CN": siteConfig.name,
    },
    description: {
      en: siteConfig.description,
      "ja-JP": "Thomas は承認、再現性シグナル、監査証跡を備えたローカルファースト実行システムです。",
      "zh-CN": "Thomas 是一个具备审批、可复现信号和审计轨迹的本地优先执行系统。",
    },
  },
  download: {
    pathname: "/download",
    title: {
      en: "Download",
      "ja-JP": "ダウンロード",
      "zh-CN": "下载",
    },
    description: {
      en: "Download Thomas for Windows, Mac, or Linux.",
      "ja-JP": "Windows、Mac、Linux 向けに Thomas をダウンロードします。",
      "zh-CN": "下载适用于 Windows、Mac 或 Linux 的 Thomas。",
    },
  },
  docs: {
    pathname: "/docs",
    title: {
      en: "Documentation",
      "ja-JP": "ドキュメント",
      "zh-CN": "文档",
    },
    description: {
      en: "Public docs for installing, learning, and safely using Thomas.",
      "ja-JP": "Thomas の導入、学習、安全な利用のための公開ドキュメントです。",
      "zh-CN": "这是 Thomas 面向公开用户的安装、学习与安全使用文档。",
    },
  },
  updates: {
    pathname: "/updates",
    title: {
      en: "What's New",
      "ja-JP": "更新情報",
      "zh-CN": "更新",
    },
    description: {
      en: "Release notes and updates for Thomas.",
      "ja-JP": "Thomas のリリースノートと更新情報です。",
      "zh-CN": "Thomas 的发布说明与更新记录。",
    },
  },
  journey: {
    pathname: "/journey",
    title: {
      en: "The Journey So Far",
      "ja-JP": "これまでの歩み",
      "zh-CN": "一路走来",
    },
    description: {
      en: "What changed, what's next, and why Thomas works the way it does.",
      "ja-JP": "何が変わり、次に何を目指し、Thomas がなぜ今の形なのかを説明します。",
      "zh-CN": "说明已经发生的变化、接下来要做什么，以及 Thomas 为什么会是现在这样。",
    },
  },
  "deep-dive": {
    pathname: "/deep-dive",
    title: {
      en: "How Thomas Works",
      "ja-JP": "Thomas の仕組み",
      "zh-CN": "Thomas 的工作方式",
    },
    description: {
      en: "Execution architecture, command contracts, and plugin boundaries for Thomas.",
      "ja-JP": "Thomas の実行アーキテクチャ、コマンド契約、プラグイン境界を説明します。",
      "zh-CN": "介绍 Thomas 的执行架构、命令契约与插件边界。",
    },
  },
  support: {
    pathname: "/support",
    title: {
      en: "Support",
      "ja-JP": "サポート",
      "zh-CN": "支持",
    },
    description: {
      en: "Get help with Thomas or report an issue.",
      "ja-JP": "Thomas のサポートを受けるか、問題を報告します。",
      "zh-CN": "获取 Thomas 帮助或报告问题。",
    },
  },
  roadmap: {
    pathname: "/roadmap",
    title: {
      en: "Thomas Roadmap",
      "ja-JP": "Thomas ロードマップ",
      "zh-CN": "Thomas 路线图",
    },
    description: {
      en: "The current Thomas core, the Infinite phone layer, and the long-range Thomas OS plan.",
      "ja-JP": "現在の Thomas Core、Infinite の電話レイヤー、そして長期の Thomas OS 計画をまとめています。",
      "zh-CN": "概览当前的 Thomas Core、Infinite 手机层，以及长期的 Thomas OS 计划。",
    },
  },
  marketplace: {
    pathname: "/marketplace",
    title: {
      en: "Marketplace",
      "ja-JP": "マーケットプレイス",
      "zh-CN": "市场",
    },
    description: {
      en: "Browse the website-canonical Thomas marketplace catalog and install official modules into Thomas.",
      "ja-JP": "公式モジュールを見つけて Thomas に追加できる、Web 標準のマーケットプレイス一覧です。",
      "zh-CN": "浏览网站标准的 Thomas 市场目录，并将官方模块安装到 Thomas 中。",
    },
  },
  infinite: {
    pathname: "/infinite",
    title: {
      en: "Thomas Infinite",
      "ja-JP": "Thomas Infinite",
      "zh-CN": "Thomas Infinite",
    },
    description: {
      en: "The private phone-layer direction for Thomas.",
      "ja-JP": "Thomas のプライベートな電話レイヤー構想です。",
      "zh-CN": "Thomas 的私有手机层方向。",
    },
  },
};

function absoluteUrl(pathname: string) {
  return new URL(pathname, getCanonicalSiteUrl()).toString();
}

function buildRouteLanguageAlternates(pathname: string) {
  const languages = Object.fromEntries(
    SITE_LOCALES.map((locale) => [locale, absoluteUrl(withSiteLocale(locale, pathname))]),
  ) as Record<string, string>;
  languages["x-default"] = absoluteUrl(pathname);
  return languages;
}

function buildBaseMetadata({
  locale,
  pathname,
  title,
  description,
  languages,
}: {
  locale: SiteLocale;
  pathname: string;
  title: string;
  description: string;
  languages: Record<string, string>;
}): Metadata {
  const url = absoluteUrl(withSiteLocale(locale, pathname));
  return {
    title: title === siteConfig.name ? { absolute: title } : title,
    description,
    alternates: {
      canonical: url,
      languages,
    },
    openGraph: {
      title,
      description,
      url,
      type: "website",
      siteName: siteConfig.name,
      locale: OPEN_GRAPH_LOCALE[locale],
      alternateLocale: SITE_LOCALES.filter((item) => item !== locale).map((item) => OPEN_GRAPH_LOCALE[item]),
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export function buildRouteMetadata(routeKey: RouteKey, locale: SiteLocale): Metadata {
  const route = ROUTE_COPY[routeKey];
  return buildBaseMetadata({
    locale,
    pathname: route.pathname,
    title: route.title[locale],
    description: route.description[locale],
    languages: buildRouteLanguageAlternates(route.pathname),
  });
}

export function buildDocMetadata(locale: SiteLocale, page: ResolvedDocPage): Metadata {
  const languages = Object.fromEntries(
    getDocLocaleLinks(page.key).map((item) => [item.locale, absoluteUrl(item.href)]),
  ) as Record<string, string>;
  languages["x-default"] = absoluteUrl(page.href);
  return buildBaseMetadata({
    locale,
    pathname: page.href,
    title: page.title,
    description: page.description,
    languages,
  });
}

export function getSitemapLanguageAlternates(pathname: string) {
  return buildRouteLanguageAlternates(pathname);
}
