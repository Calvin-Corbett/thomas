import Link from "next/link";
import Script from "next/script";
import { DownloadButton } from "@/components/download-button";
import { MetricsStrip } from "@/components/metrics-strip";
import { PixelAgents } from "@/components/pixel-agents";
import { ReleaseFeed } from "@/components/release-feed";

const heroSplineUrl = "https://prod.spline.design/6Wq1Q7YGyM-iab9i/scene.splinecode";

const capabilities = [
  {
    title: "File And App Tasks",
    text: "Organize files, launch workflows, and handle everyday computer tasks with guided execution.",
  },
  {
    title: "Research And Writing",
    text: "Gather information, summarize sources, draft messages, and produce polished documents faster.",
  },
  {
    title: "Smart Automation",
    text: "Turn repetitive steps into reliable routines so work gets done with less manual effort.",
  },
  {
    title: "Planning And Execution",
    text: "Track goals, run tasks, and keep outcomes visible from first prompt to finished result.",
  },
  {
    title: "Troubleshooting Help",
    text: "Diagnose issues on your machine and walk through fixes clearly, step by step.",
  },
  {
    title: "Coding When Needed",
    text: "Build, debug, and ship software when you need it, without making coding the whole product.",
  },
];

export default function HomePage() {
  return (
    <>
      <Script
        src="https://unpkg.com/@splinetool/viewer@1.10.10/build/spline-viewer.js"
        type="module"
        strategy="afterInteractive"
      />

      <section className="home-hero">
        <div className="home-ambient home-ambient-a" />
        <div className="home-ambient home-ambient-b" />
        <div className="home-grid-overlay" />
        <div className="home-spline-layer" aria-hidden="true">
          <spline-viewer className="home-spline-viewer" loading-anim-type="none" url={heroSplineUrl} />
        </div>
        <PixelAgents />
        <div className="home-hero-center">
          <p className="home-kicker">EVERYTHING ASSISTANT</p>
          <h1 className="home-wordmark">THOMAS</h1>
          <p className="home-subline">
            Thomas helps you do anything on your computer: research, writing, planning, automation, troubleshooting,
            and coding.
          </p>
          <div className="hero-cta home-hero-cta">
            <DownloadButton source="hero" className="cta-primary home-cta-primary" />
            <Link className="cta-secondary home-cta-secondary" href="/updates">
              View Changelog
            </Link>
          </div>
        </div>
        <a className="home-scroll-cue" href="#landing">
          Explore
        </a>
      </section>

      <section id="landing" className="home-landing">
        <div className="home-section-head">
          <p className="eyebrow">Platform Overview</p>
          <h2>Built for real computer work, not just code.</h2>
          <p>
            Use one assistant across daily tasks on your computer, from quick questions to multi-step workflows, with
            clear progress and reliable outcomes.
          </p>
        </div>

        <MetricsStrip />

        <section className="feature-grid home-feature-grid" aria-label="Thomas capabilities">
          {capabilities.map((item, index) => (
            <article key={item.title} className="feature-card home-feature-card" style={{ animationDelay: `${index * 100}ms` }}>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </article>
          ))}
        </section>

        <section className="section-shell home-updates-shell">
          <div className="section-head">
            <h2>Latest Updates</h2>
            <Link href="/updates">Open full changelog</Link>
          </div>
          <ReleaseFeed limit={4} />
        </section>

        <section className="section-shell home-journey-shell">
          <div className="home-section-head">
            <p className="eyebrow">Build In Public</p>
            <h2>Roadmap, releases, and product journey.</h2>
            <p>Publish update videos and milestones so users can follow progress and understand what is shipping next.</p>
          </div>
          <div className="home-media-grid">
            <article className="home-media-card">
              <h3>Watch The Journey</h3>
              <p>Share roadmap videos, release walkthroughs, and product direction updates.</p>
              <Link href="/journey" className="text-link">
                Open journey page
              </Link>
            </article>
            <article className="home-media-card">
              <h3>Get The Latest Build</h3>
              <p>Direct users to the newest release with a clear path for non-technical installs.</p>
              <Link href="/download" className="text-link">
                Open download page
              </Link>
            </article>
          </div>
        </section>
      </section>
    </>
  );
}
