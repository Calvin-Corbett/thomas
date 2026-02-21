import { DownloadButton } from "@/components/download-button";
import { getReleasesUrl } from "@/lib/site-config";

const platformCards = [
  { label: "Windows", href: "/api/download?platform=windows&channel=stable&source=download_page_windows" },
  { label: "Mac", href: "/api/download?platform=macos&channel=stable&source=download_page_mac" },
  { label: "Linux", href: "/api/download?platform=linux&channel=stable&source=download_page_linux" },
];

export default function DownloadPage() {
  const releasesUrl = getReleasesUrl();
  return (
    <section className="section-shell">
      <p className="eyebrow">Download Thomas</p>
      <h1 className="page-title">Pick your platform and start in minutes.</h1>
      <p className="page-intro">
        Normal install is one click. Advanced users can still access raw assets and checksums on GitHub Releases.
      </p>

      <div className="hero-cta">
        <DownloadButton source="download_page_auto" />
      </div>

      <div className="download-grid">
        {platformCards.map((platform) => (
          <article key={platform.label} className="download-card">
            <h2>{platform.label}</h2>
            <p>Recommended installer for {platform.label} users.</p>
            <a className="cta-secondary" href={platform.href}>
              Download {platform.label}
            </a>
          </article>
        ))}
      </div>

      <div className="advanced-box">
        <h2>For technical users</h2>
        {releasesUrl ? (
          <>
            <p>Prefer release assets directly, checksums, and raw notes?</p>
            <a className="text-link" href={releasesUrl} target="_blank" rel="noreferrer">
              Open GitHub Releases
            </a>
          </>
        ) : (
          <p>GitHub release view will be enabled after repo integration is connected.</p>
        )}
      </div>
    </section>
  );
}
