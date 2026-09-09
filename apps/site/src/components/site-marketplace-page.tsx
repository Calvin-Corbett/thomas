import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { buildMarketplaceCatalog } from "@/lib/marketplace-catalog";
import { type SiteLocale } from "@/lib/site-locale";

type MarketplaceCopy = {
  eyebrow: string;
  title: string;
  intro: string;
  modulesLabel: string;
  howItWorksTitle: string;
  howItWorksIntro: string;
  catalogEntries: string;
  officialInstallables: string;
  categories: string;
  catalogSyncPrefix: string;
  catalogSyncSuffix: string;
  officialInstallablesTitle: string;
  officialInstallablesIntro: string;
  statusLabel: string;
  openInThomas: string;
  downloadZip: string;
  catalogInventoryTitle: string;
  catalogInventoryIntro: string;
  noDescription: string;
  catalogOnlySuffix: string;
};

function getMarketplaceCopy(locale: SiteLocale): MarketplaceCopy {
  if (locale === "ja-JP") {
    return {
      eyebrow: "マーケットプレイス",
      title: "Thomas Marketplace",
      intro:
        "公式 Thomas モジュールの公開カタログです。Web で閲覧することも、デスクトップアプリ側から同じカタログを同期することもできます。",
      modulesLabel: "モジュール",
      howItWorksTitle: "仕組み",
      howItWorksIntro:
        "Thomas 本体にはコアランタイムだけを保持し、マーケットプレイスのモジュールはインストールされるまでここで配布されます。",
      catalogEntries: "カタログ項目",
      officialInstallables: "公式インストール可能数",
      categories: "カテゴリ",
      catalogSyncPrefix: "デスクトップ版 Thomas は ",
      catalogSyncSuffix:
        " からこのカタログを同期し、署名付きダウンロードトークンで公式バンドルを導入します。手動の ZIP 読み込みも使えますが、公式の基準はこのサイトです。",
      officialInstallablesTitle: "公式インストール可能モジュール",
      officialInstallablesIntro:
        "現在、ホストされたストアから Thomas に直接インストールできるバンドルです。",
      statusLabel: "状態",
      openInThomas: "Thomas で開く",
      downloadZip: "ZIP をダウンロード",
      catalogInventoryTitle: "カタログ在庫",
      catalogInventoryIntro:
        "catalog-only の行は実在するモジュール在庫ですが、まだ署名付きのワンクリック配布には昇格していません。",
      noDescription: "説明はまだ公開されていません。",
      catalogOnlySuffix: "このモジュールはワンクリック導入の前に、ホスト済みバンドル配線が必要です。",
    };
  }

  if (locale === "zh-CN") {
    return {
      eyebrow: "市场",
      title: "Thomas Marketplace",
      intro:
        "这里是官方 Thomas 模块的公开目录。你可以直接在网页查看，也可以在桌面应用里同步同一份目录。",
      modulesLabel: "模块",
      howItWorksTitle: "工作方式",
      howItWorksIntro:
        "Thomas 本地只保留核心运行时。Marketplace 模块会托管在这里，直到你真正安装它们。",
      catalogEntries: "目录条目",
      officialInstallables: "官方可安装项",
      categories: "分类",
      catalogSyncPrefix: "桌面版 Thomas 会从 ",
      catalogSyncSuffix:
        " 同步这个目录，并使用签名下载令牌安装官方包。手动导入 ZIP 仍然可用，但网站目录才是官方来源。",
      officialInstallablesTitle: "官方可安装模块",
      officialInstallablesIntro:
        "这些是目前可以从托管商店直接安装到 Thomas 里的模块。",
      statusLabel: "状态",
      openInThomas: "在 Thomas 中打开",
      downloadZip: "下载 ZIP",
      catalogInventoryTitle: "目录库存",
      catalogInventoryIntro:
        "catalog-only 项目代表真实存在的模块库存，但还没有升级为带签名托管的一键安装包。",
      noDescription: "暂时还没有公开说明。",
      catalogOnlySuffix: "这个模块在支持一键安装前，还需要补齐托管包分发链路。",
    };
  }

  return {
    eyebrow: "Marketplace",
    title: "Website-canonical Thomas Marketplace",
    intro:
      "The site is the source of truth for official Thomas modules. Browse here on the web or sync the same catalog from inside the desktop app.",
    modulesLabel: "modules",
    howItWorksTitle: "How it works",
    howItWorksIntro:
      "Thomas keeps only the core runtime locally. Marketplace modules stay hosted here until you install them.",
    catalogEntries: "catalog entries",
    officialInstallables: "official installables",
    categories: "categories",
    catalogSyncPrefix: "Desktop Thomas syncs this catalog from ",
    catalogSyncSuffix:
      " and installs official bundles with signed download tokens. Manual ZIP import still works, but the website feed is the canonical source.",
    officialInstallablesTitle: "Official installables",
    officialInstallablesIntro:
      "These are the bundles that can be installed directly into Thomas from the hosted store today.",
    statusLabel: "Status",
    openInThomas: "Open in Thomas",
    downloadZip: "Download ZIP",
    catalogInventoryTitle: "Catalog inventory",
    catalogInventoryIntro:
      "Catalog-only rows are real module inventory, but they are not yet promoted to signed hosted installables.",
    noDescription: "No description published yet.",
    catalogOnlySuffix: "This module needs hosted bundle plumbing before one-click install.",
  };
}

function getAvailabilityLabel(locale: SiteLocale, value: string) {
  const normalized = value.replace(/_/g, " ");
  if (locale === "ja-JP") {
    if (value === "installable") return "インストール可能";
    if (value === "catalog_only") return "カタログのみ";
    if (value === "scaffold") return "ひな形";
    if (value === "hidden") return "非表示";
  }
  if (locale === "zh-CN") {
    if (value === "installable") return "可安装";
    if (value === "catalog_only") return "仅目录";
    if (value === "scaffold") return "脚手架";
    if (value === "hidden") return "隐藏";
  }
  return normalized;
}

export function SiteMarketplacePage({ locale = "en" }: { locale?: SiteLocale }) {
  const catalog = buildMarketplaceCatalog("stable");
  const featured = catalog.plugins.slice(0, 24);
  const hosted = featured.filter((plugin) => plugin.availability === "installable");
  const catalogOnly = featured.filter((plugin) => plugin.availability === "catalog_only");
  const copy = getMarketplaceCopy(locale);

  return (
    <SystemPageShell
      eyebrow={copy.eyebrow}
      title={copy.title}
      intro={copy.intro}
      versionLabel={`${catalog.count} ${copy.modulesLabel}`}
    >
      <SystemSection title={copy.howItWorksTitle} intro={copy.howItWorksIntro}>
        <div className="system-metric-grid">
          <div className="system-metric-card">
            <span className="system-metric-value">{catalog.count}</span>
            <span className="system-metric-label">{copy.catalogEntries}</span>
          </div>
          <div className="system-metric-card">
            <span className="system-metric-value">{hosted.length}</span>
            <span className="system-metric-label">{copy.officialInstallables}</span>
          </div>
          <div className="system-metric-card">
            <span className="system-metric-value">{catalog.categories.length}</span>
            <span className="system-metric-label">{copy.categories}</span>
          </div>
        </div>
        <p className="system-metric-line">
          {copy.catalogSyncPrefix}
          <code>{catalog.store_url}</code>
          {copy.catalogSyncSuffix}
        </p>
      </SystemSection>

      <SystemSection title={copy.officialInstallablesTitle} intro={copy.officialInstallablesIntro}>
        <div className="plugin-store-list">
          {hosted.map((plugin) => (
            <article key={plugin.id} className="plugin-store-card">
              <div>
                <p className="plugin-store-kicker">{plugin.marketplace_type_label}</p>
                <h3>{plugin.display_name}</h3>
                <p className="system-metric-line">{plugin.subtitle || plugin.description}</p>
                <p className="system-metric-note">
                  {plugin.category_label} / v{plugin.version} / {plugin.publisher_name}
                </p>
                <p className="system-metric-note">
                  {copy.statusLabel}: {getAvailabilityLabel(locale, plugin.availability)}
                </p>
              </div>
              <div className="plugin-store-actions">
                <a className="cta-primary" href={plugin.open_in_thomas_url}>
                  {copy.openInThomas}
                </a>
                <a className="cta-secondary" href={plugin.manual_download_url}>
                  {copy.downloadZip}
                </a>
              </div>
            </article>
          ))}
        </div>
      </SystemSection>

      <SystemSection title={copy.catalogInventoryTitle} intro={copy.catalogInventoryIntro}>
        <div className="system-version-list">
          {catalogOnly.map((plugin) => (
            <details key={plugin.id} className="system-version-card" data-system-detail-id={`marketplace-${plugin.id}`}>
              <summary>
                <p className="system-section-title">{plugin.display_name}</p>
              </summary>
              <p className="system-metric-line">
                {plugin.marketplace_type_label} / {plugin.category_label} / v{plugin.version}
              </p>
              <p className="system-metric-note">{plugin.description || copy.noDescription}</p>
              <p className="system-metric-note">
                {copy.statusLabel}: {getAvailabilityLabel(locale, plugin.availability)}. {copy.catalogOnlySuffix}
              </p>
            </details>
          ))}
        </div>
      </SystemSection>
    </SystemPageShell>
  );
}
