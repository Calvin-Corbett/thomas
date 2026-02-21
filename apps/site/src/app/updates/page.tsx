import { ReleaseFeed } from "@/components/release-feed";

export default function UpdatesPage() {
  return (
    <section className="section-shell">
      <p className="eyebrow">Release Notes</p>
      <h1 className="page-title">Everything new in Thomas.</h1>
      <p className="page-intro">
        This page mirrors your GitHub releases and makes updates easy to understand for non-technical users.
      </p>
      <ReleaseFeed limit={12} />
    </section>
  );
}
