import Link from "next/link";
import Script from "next/script";
import { DownloadButton } from "@/components/download-button";
import { MetricsStrip } from "@/components/metrics-strip";
import { PixelAgents } from "@/components/pixel-agents";
import { ReleaseFeed } from "@/components/release-feed";

const heroSplineUrl = "https://prod.spline.design/6Wq1Q7YGyM-iab9i/scene.splinecode";

const corePromise = [
  {
    title: "Single-click execution path",
    text: "The same intent input is routed through the same planning and safety layer every time, so behavior stays predictable under load and reuse.",
  },
  {
    title: "Deterministic guardrails",
    text: "Each workflow runs through explicit constraints, preflight checks, and explicit approval points before destructive actions can execute.",
  },
  {
    title: "No magic defaults",
    text: "When context is missing, Thomas asks for explicit operator input instead of fabricating assumptions in the workflow graph.",
  },
  {
    title: "Public implementation trail",
    text: "Release artifacts, technical notes, and changelog are kept in one place so each release decision can be reviewed quickly.",
  },
  {
    title: "Built for operators who ship",
    text: "The interface optimizes for fast correction, rollback visibility, and low-friction iteration rather than polished perfectionism.",
  },
];

const regularOutcomes = [
  {
    title: "For solo builders",
    summary: "Turn one request into a repeatable process without learning a long command list.",
    example: "\"Run my weekly report workflow and prep a clear summary before my Friday meeting.\"",
  },
  {
    title: "For support teams",
    summary: "Handle triage and repetitive follow-ups with less context switching and fewer manual handoffs.",
    example: "\"Pull open tickets, group blockers by owner, and draft next actions for each team.\"",
  },
  {
    title: "For non-technical operators",
    summary: "Use outcome-driven prompts in plain English, then inspect what happened before approving next steps.",
    example: "\"Set up my cleanup checklist, show me what changed, and ask before doing anything risky.\"",
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
          <h1 className="home-wordmark">THOMAS</h1>
          <div className="hero-cta home-hero-cta">
            <DownloadButton source="hero" className="cta-primary home-cta-primary" />
            <Link className="cta-secondary home-cta-secondary" href="/deep-dive">
              How It Works
            </Link>
          </div>
        </div>
      </section>

      <section className="home-landing">
        <section className="section-shell home-story-shell">
          <p className="eyebrow">How it works</p>
          <h2>Why this project matters</h2>

          <div className="deep-win-grid">
            {corePromise.map((item, index) => (
              <article key={item.title} className="deep-metric" style={{ animationDelay: `${index * 75}ms` }}>
                <h3 className="deep-metric-title">{item.title}</h3>
                <p className="deep-metric-copy">{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <MetricsStrip />

        <section className="section-shell home-plain-shell">
          <div className="home-section-head">
            <h2>No jargon, just outcomes</h2>
            <p>What Thomas changes for day-to-day work if you are not a career software engineer.</p>
          </div>
          <div className="human-grid">
            {regularOutcomes.map((outcome) => (
              <article key={outcome.title} className="human-card">
                <p className="human-card-title">{outcome.title}</p>
                <p className="human-card-summary">{outcome.summary}</p>
                <p className="human-card-example">
                  <span>Example:</span> {outcome.example}
                </p>
              </article>
            ))}
          </div>
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
            <p className="eyebrow">The Road Ahead</p>
            <h2>Thomas is not the final form yet.</h2>
            <p>
              The live build is the controlled core. The roadmap shows where this goes next: a private-network app layer
              on your phone, then an AI-native operating system built around Thomas from the ground up.
            </p>
          </div>
          <div className="home-roadmap-grid">
            <article className="home-roadmap-card home-roadmap-card-primary">
              <p className="home-roadmap-kicker">Roadmap</p>
              <h3>See where Thomas goes next.</h3>
              <p>
                See the three-stage plan: the current core, the Infinite phone layer, and the long-range Thomas OS vision. It is the clearest view of where the product is headed next.
              </p>
              <div className="home-roadmap-actions">
                <Link href="/roadmap" className="cta-primary">
                  Explore roadmap
                </Link>
                <Link href="/journey" className="cta-secondary">
                  See the journey
                </Link>
              </div>
            </article>
            <div className="home-roadmap-stack">
              <article className="home-roadmap-card">
                <p className="home-roadmap-step">01 / Thomas Core</p>
                <h3>Pre-alpha trust boundary</h3>
                <p>Local-first execution, explicit approvals, and reproducible behavior before anything bigger ships.</p>
              </article>
              <article className="home-roadmap-card">
                <p className="home-roadmap-step">02 / Thomas Infinite</p>
                <h3>Private phone app layer</h3>
                <p>Use Tailscale to push headless web experiences to your phone so Thomas can create app surfaces on demand.</p>
              </article>
              <article className="home-roadmap-card">
                <p className="home-roadmap-step">03 / Thomas OS</p>
                <h3>AI-native Linux system</h3>
                <p>The long bet: an operating system where AI is part of the stack itself, not bolted onto it later.</p>
              </article>
            </div>
          </div>
        </section>
      </section>
    </>
  );
}
