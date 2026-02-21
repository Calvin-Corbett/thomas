import Link from "next/link";
import { DownloadButton } from "@/components/download-button";
import { MetricsStrip } from "@/components/metrics-strip";
import { ReleaseFeed } from "@/components/release-feed";
import { siteConfig } from "@/lib/site-config";

const highlights = [
  {
    title: "One clear command center",
    text: "Thomas keeps your work in one place, so you do not have to juggle tools.",
  },
  {
    title: "Live execution visibility",
    text: "Follow what Thomas is doing in real time with action-by-action transparency.",
  },
  {
    title: "Reliable updates",
    text: "Every release includes clearer fixes, better control, and visible progress.",
  },
];

export default function HomePage() {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">{siteConfig.productLine}</p>
        <h1>Thomas for people who want results, not setup friction.</h1>
        <p className="hero-copy">
          Download Thomas, launch once, and get support for planning, execution, and follow-through from one assistant.
        </p>
        <div className="hero-cta">
          <DownloadButton source="hero" />
          <Link className="cta-secondary" href="/updates">
            See What&apos;s New
          </Link>
        </div>
      </section>

      <MetricsStrip />

      <section className="feature-grid" aria-label="Website highlights">
        {highlights.map((item, index) => (
          <article key={item.title} className="feature-card" style={{ animationDelay: `${index * 120}ms` }}>
            <h2>{item.title}</h2>
            <p>{item.text}</p>
          </article>
        ))}
      </section>

      <section className="section-shell">
        <div className="section-head">
          <h2>Latest Updates</h2>
          <Link href="/updates">Open full changelog</Link>
        </div>
        <ReleaseFeed limit={4} />
      </section>
    </>
  );
}
