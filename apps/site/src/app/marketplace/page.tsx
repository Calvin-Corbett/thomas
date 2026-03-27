import type { Metadata } from "next";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import { buildMarketplaceCatalog } from "@/lib/marketplace-catalog";

export const metadata: Metadata = {
  title: "Marketplace",
  description: "Browse the website-canonical Thomas marketplace catalog and install official modules into Thomas.",
};

export default function MarketplacePage() {
  const catalog = buildMarketplaceCatalog("stable");
  const featured = catalog.plugins.slice(0, 24);
  const hosted = featured.filter((plugin) => plugin.availability === "installable");
  const catalogOnly = featured.filter((plugin) => plugin.availability === "catalog_only");

  return (
    <SystemPageShell
      eyebrow="Marketplace"
      title="Website-canonical Thomas Marketplace"
      intro="The site is the source of truth for official Thomas modules. Browse here on the web or sync the same catalog from inside the desktop app."
      versionLabel={`${catalog.count} modules`}
    >
      <SystemSection
        title="How it works"
        intro="Thomas keeps only the core runtime locally. Marketplace modules stay hosted here until you install them."
      >
        <div className="system-metric-grid">
          <div className="system-metric-card">
            <span className="system-metric-value">{catalog.count}</span>
            <span className="system-metric-label">catalog entries</span>
          </div>
          <div className="system-metric-card">
            <span className="system-metric-value">{hosted.length}</span>
            <span className="system-metric-label">official installables</span>
          </div>
          <div className="system-metric-card">
            <span className="system-metric-value">{catalog.categories.length}</span>
            <span className="system-metric-label">categories</span>
          </div>
        </div>
        <p className="system-metric-line">
          Desktop Thomas syncs this catalog from <code>{catalog.store_url}</code> and installs official bundles with
          signed download tokens. Manual ZIP import still works, but the website feed is the canonical source.
        </p>
      </SystemSection>

      <SystemSection
        title="Official installables"
        intro="These are the bundles that can be installed directly into Thomas from the hosted store today."
      >
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
                <p className="system-metric-note">Status: {plugin.availability.replace(/_/g, " ")}</p>
              </div>
              <div className="plugin-store-actions">
                <a className="cta-primary" href={plugin.open_in_thomas_url}>
                  Open in Thomas
                </a>
                <a className="cta-secondary" href={plugin.manual_download_url}>
                  Download ZIP
                </a>
              </div>
            </article>
          ))}
        </div>
      </SystemSection>

      <SystemSection
        title="Catalog inventory"
        intro="Catalog-only rows are real module inventory, but they are not yet promoted to signed hosted installables."
      >
        <div className="system-version-list">
          {catalogOnly.map((plugin) => (
            <details key={plugin.id} className="system-version-card" data-system-detail-id={`marketplace-${plugin.id}`}>
              <summary>
                <p className="system-section-title">{plugin.display_name}</p>
              </summary>
              <p className="system-metric-line">
                {plugin.marketplace_type_label} / {plugin.category_label} / v{plugin.version}
              </p>
              <p className="system-metric-note">{plugin.description || "No description published yet."}</p>
              <p className="system-metric-note">
                Status: {plugin.availability.replace(/_/g, " ")}. This module needs hosted bundle plumbing before one-click install.
              </p>
            </details>
          ))}
        </div>
      </SystemSection>
    </SystemPageShell>
  );
}
