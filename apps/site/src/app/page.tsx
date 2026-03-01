import Link from "next/link";
import Script from "next/script";
import { DownloadButton } from "@/components/download-button";
import { MetricsStrip } from "@/components/metrics-strip";
import { PixelAgents } from "@/components/pixel-agents";
import { ReleaseFeed } from "@/components/release-feed";
import { COMPARISON_META } from "@/lib/featureComparisonData";

const heroSplineUrl = "https://prod.spline.design/6Wq1Q7YGyM-iab9i/scene.splinecode";
const openclawRepository = COMPARISON_META.openclawRepo;
const openclawCommit = COMPARISON_META.openclawCommit;
const openclawCommitShort = openclawCommit.slice(0, 7);
const openclawComparisonDate = COMPARISON_META.suiteDateUtc;

const corePromise = [
  {
    title: "Plain-language workflows",
    text: "You ask for outcomes in normal language. Thomas executes in the background and returns clear, auditable progress.",
  },
  {
    title: "Built for real people",
    text: "The default path is for non-technical operators: practical behavior, visible checkpoints, and explicit confirmations.",
  },
  {
    title: "Reliable execution",
    text: "Long tasks stay structured with checkpoints and status signals so you can recover and continue quickly.",
  },
  {
    title: "One stack, many jobs",
    text: "Planning, writing, automation, coding support, and operations flow through a single workflow interface.",
  },
  {
    title: "Publicly verifiable",
    text: "Release feed, deep-dive pages, and public links are there so anyone can inspect what was claimed.",
  },
];

const regularOutcomes = [
  {
    title: "For solo builders",
    summary: "Turn one request into a repeatable process instead of memorizing 20 tools.",
    example: "\"Draft a progress report every Friday and send it to my team channel.\"",
  },
  {
    title: "For support teams",
    summary: "Run routine checks and remediation loops with less manual switching and less context loss.",
    example: "\"Pull this ticket list, summarize blockers, and tag each owner.\"",
  },
  {
    title: "For people who dislike CLI-only tools",
    summary: "No need to learn all technical commands to complete day-to-day work.",
    example: "\"Create the full project cleanup flow and run it safely.\"",
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
          <p className="home-kicker">Everything Assistant</p>
          <h1 className="home-wordmark">THOMAS</h1>
          <p className="home-subline">
            Built in 14 days by a Navy veteran with no formal software-engineering background, Thomas is a workflow-first
            assistant for real work, not tool demos.
          </p>
          <div className="alert-note alert-note-critical home-hero-warning">
            Warning: this was started as a 14-day vibe-coded build by a Navy veteran without formal software engineering
            training. It is a real product direction, but it deserves full production-style validation before mission-critical use.
          </div>
          <div className="hero-cta home-hero-cta">
            <DownloadButton source="hero" className="cta-primary home-cta-primary" />
            <Link className="cta-secondary home-cta-secondary" href="/deep-dive">
              Open Deep Dive
            </Link>
          </div>
        </div>
      </section>

      <section className="home-landing">
        <section className="section-shell home-story-shell">
          <p className="eyebrow">Built, not guessed</p>
          <h2>What Thomas is for people</h2>
          <div className="home-section-head">
            <p>
              Home page keeps to outcomes everyone can verify. Technical feature-by-feature comparison is on the Deep Dive page.
            </p>
          </div>

          <div className="deep-win-grid">
            {corePromise.map((item, index) => (
              <article key={item.title} className="deep-metric" style={{ animationDelay: `${index * 75}ms` }}>
                <h3 className="deep-metric-title">{item.title}</h3>
                <p className="deep-metric-copy">{item.text}</p>
              </article>
            ))}
          </div>

          <div className="deep-callout deep-callout-top">
            <p>
              Comparison baseline used for this site launch: OpenClaw commit{" "}
              <a href={`${openclawRepository}/commit/${openclawCommit}`} target="_blank" rel="noreferrer">
                <code>{openclawCommitShort}</code>
              </a>{" "}
              (snapshot date {openclawComparisonDate}). The Deep Dive page uses the same baseline.
            </p>
            <p>
              Repo reference: <a href={openclawRepository}>{openclawRepository}</a>
            </p>
          </div>
        </section>

        <MetricsStrip />

        <section className="section-shell home-plain-shell">
          <div className="home-section-head">
            <p className="eyebrow">Regular people section</p>
            <h2>No jargon, just outcomes</h2>
            <p>How this system changes daily work across non-technical and mixed teams.</p>
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

        <section className="section-shell home-plain-shell" id="comparison">
          <div className="home-section-head">
            <p className="eyebrow">Technical proof lane</p>
            <h2>For engineers and evaluators</h2>
            <p>
              The Deep Dive has a full side-by-side feature matrix, raw command inventories, depth metrics, and provenance links.
            </p>
          </div>
          <div className="plain-comparison-grid">
            <article className="plain-comparison-card">
              <p className="plain-comparison-question">OpenClaw baseline provenance</p>
              <div className="plain-comparison-points">
                <p>
                  <span className="plain-comparison-label">Commit:</span>
                  <a href={`${openclawRepository}/commit/${openclawCommit}`} target="_blank" rel="noreferrer">
                    <code>{openclawCommitShort}</code>
                  </a>
                </p>
                <p>
                  <span className="plain-comparison-label">Online directory:</span>
                  <a href={`${openclawRepository}/tree/main`} target="_blank" rel="noreferrer">
                    openclaw/main
                  </a>
                </p>
              </div>
            </article>
            <article className="plain-comparison-card">
              <p className="plain-comparison-question">What to do next</p>
              <div className="plain-comparison-points">
                <p>Start with the Deep Dive page and drill by category.</p>
                <p>
                  <Link href="/deep-dive#feature-matrix">Go to technical matrix</Link>
                </p>
                <p>
                  <Link href="/deep-dive#methodology">Read methodology and limits</Link>
                </p>
              </div>
            </article>
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
            <p className="eyebrow">Build in Public</p>
            <h2>Roadmap, releases, and journey.</h2>
            <p>Use updates and journey for shipping pace and confidence checks, not marketing copy.</p>
          </div>
          <div className="home-media-grid">
            <article className="home-media-card">
              <h3>Watch The Journey</h3>
              <p>Release updates, milestones, and directional notes for product progress.</p>
              <Link href="/journey" className="text-link">
                Open journey page
              </Link>
            </article>
            <article className="home-media-card">
              <h3>Get the Latest Build</h3>
              <p>Direct links for direct installs and release assets.</p>
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
