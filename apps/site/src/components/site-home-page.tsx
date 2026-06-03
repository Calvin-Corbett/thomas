import Link from "next/link";
import { DownloadButton } from "@/components/download-button";
import { MetricsStrip } from "@/components/metrics-strip";
import { PixelAgents } from "@/components/pixel-agents";
import { ReleaseFeed } from "@/components/release-feed";
import { SplineViewerLoader } from "@/components/spline-viewer-loader";
import { getSiteCopy } from "@/lib/site-copy";
import { withSiteLocale, type SiteLocale } from "@/lib/site-locale";

const heroSplineUrl = "https://prod.spline.design/6Wq1Q7YGyM-iab9i/scene.splinecode";

function getExampleLabel(locale: SiteLocale) {
  if (locale === "ja-JP") return "例";
  if (locale === "zh-CN") return "示例";
  return "Example";
}

export function SiteHomePage({ locale = "en" }: { locale?: SiteLocale }) {
  const copy = getSiteCopy(locale);
  const exampleLabel = getExampleLabel(locale);
  const deepDiveHref = withSiteLocale(locale, "/deep-dive");
  const updatesHref = withSiteLocale(locale, "/updates");
  const roadmapHref = withSiteLocale(locale, "/roadmap");
  const journeyHref = withSiteLocale(locale, "/journey");

  return (
    <>
      <SplineViewerLoader />

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
            <DownloadButton
              source="hero"
              className="cta-primary home-cta-primary"
              labelPrefix={copy.components.downloadButton}
              platformLabels={copy.download.platformLabels}
            />
            <Link className="cta-secondary home-cta-secondary" href={deepDiveHref}>
              {copy.home.heroSecondary}
            </Link>
          </div>
        </div>
      </section>

      <section className="home-landing">
        <section className="section-shell home-story-shell">
          <p className="eyebrow">{copy.home.howItWorks}</p>
          <h2>{copy.home.whyItMatters}</h2>

          <div className="deep-win-grid">
            {copy.home.corePromise.map((item, index) => (
              <article key={item.title} className="deep-metric" style={{ animationDelay: `${index * 75}ms` }}>
                <h3 className="deep-metric-title">{item.title}</h3>
                <p className="deep-metric-copy">{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <MetricsStrip labels={copy.components.metrics} />

        <section className="section-shell home-plain-shell">
          <div className="home-section-head">
            <h2>{copy.home.outcomesTitle}</h2>
            <p>{copy.home.outcomesIntro}</p>
          </div>
          <div className="human-grid">
            {copy.home.regularOutcomes.map((outcome) => (
              <article key={outcome.title} className="human-card">
                <p className="human-card-title">{outcome.title}</p>
                <p className="human-card-summary">{outcome.summary}</p>
                <p className="human-card-example">
                  <span>{exampleLabel}:</span> {outcome.example}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className="section-shell home-updates-shell">
          <div className="section-head">
            <h2>{copy.home.latestUpdates}</h2>
            <Link href={updatesHref}>{copy.home.fullChangelog}</Link>
          </div>
          <ReleaseFeed limit={4} labels={copy.components.releaseFeed} />
        </section>

        <section className="section-shell home-journey-shell">
          <div className="home-section-head">
            <p className="eyebrow">{copy.home.roadAhead}</p>
            <h2>{copy.home.roadAheadTitle}</h2>
            <p>{copy.home.roadAheadBody}</p>
          </div>
          <div className="home-roadmap-grid">
            <article className="home-roadmap-card home-roadmap-card-primary">
              <p className="home-roadmap-kicker">{copy.home.roadmapCardKicker}</p>
              <h3>{copy.home.roadmapCardTitle}</h3>
              <p>{copy.home.roadmapCardBody}</p>
              <div className="home-roadmap-actions">
                <Link href={roadmapHref} className="cta-primary">
                  {copy.home.roadmapPrimary}
                </Link>
                <Link href={journeyHref} className="cta-secondary">
                  {copy.home.roadmapSecondary}
                </Link>
              </div>
            </article>
            <div className="home-roadmap-stack">
              {copy.home.roadmapSteps.map((step) => (
                <article key={step.step} className="home-roadmap-card">
                  <p className="home-roadmap-step">{step.step}</p>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      </section>
    </>
  );
}
