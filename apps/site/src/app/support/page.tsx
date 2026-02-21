import { getReleasesUrl } from "@/lib/site-config";

export default function SupportPage() {
  const releasesUrl = getReleasesUrl();
  return (
    <section className="section-shell">
      <p className="eyebrow">Support</p>
      <h1 className="page-title">Need help with installation or updates?</h1>
      <p className="page-intro">Start with these common issues before opening a support thread.</p>

      <div className="faq-grid">
        <article className="faq-card">
          <h2>Installer did not launch</h2>
          <p>Download again from the download page and run with standard user permissions first.</p>
        </article>
        <article className="faq-card">
          <h2>Update did not apply</h2>
          <p>Check the latest release notes, restart Thomas, and confirm you are on the expected version.</p>
        </article>
        <article className="faq-card">
          <h2>Security warning from OS</h2>
          <p>Verify the installer hash from GitHub Releases and confirm the release tag before proceeding.</p>
        </article>
      </div>

      {releasesUrl ? (
        <p>
          For advanced diagnostics and raw release assets, use{" "}
          <a className="text-link" href={releasesUrl} target="_blank" rel="noreferrer">
            GitHub Releases
          </a>
          .
        </p>
      ) : (
        <p>Advanced GitHub release diagnostics will appear after GitHub integration is connected.</p>
      )}
    </section>
  );
}
