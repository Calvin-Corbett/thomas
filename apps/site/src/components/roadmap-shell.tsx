"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import styles from "./roadmap-shell.module.css";

export type RoadmapCheckpoint = {
  id: string;
  title: string;
  status: string;
  horizon: string;
  summary: string;
  detail: string;
  signals: string[];
  tone: "live" | "build" | "vision";
  featured?: boolean;
};

export type RoadmapChapter = {
  id: string;
  phase: string;
  status: string;
  title: string;
  horizon: string;
  intro: string;
  body: string;
  outcome: string;
  repoSignals: string[];
  checkpoints: RoadmapCheckpoint[];
};

type RepoSnapshot = {
  release: string;
  stamp: string;
  signals: string[];
};

type RoadmapShellCopy = {
  heroEyebrow: string;
  heroTitle: string;
  heroLead: string;
  journeyHref: string;
  journeyLabel: string;
  downloadHref: string;
  downloadLabel: string;
  currentBuildLabel: string;
  whereThingsStandLabel: string;
  phasesEyebrow: string;
  phasesTitle: string;
  phasesAriaLabel: string;
  openPhaseLabel: string;
  selectedPhaseEyebrow: string;
  whyThisPhaseMatters: string;
};

type RoadmapShellProps = {
  chapters: RoadmapChapter[];
  repoSnapshot: RepoSnapshot;
  copy?: Partial<RoadmapShellCopy>;
};

const STATION_LAYOUT = [
  { left: "14%", top: "68%" },
  { left: "50%", top: "26%" },
  { left: "84%", top: "66%" },
] as const;

const defaultCopy: RoadmapShellCopy = {
  heroEyebrow: "Roadmap",
  heroTitle: "Thomas Roadmap",
  heroLead:
    "Thomas is still pre-alpha. The job right now is to make the core trustworthy, turn that core into a private app network you can carry on your phone, and then push all of that into a real AI-native operating system.",
  journeyHref: "/journey",
  journeyLabel: "Read the journey",
  downloadHref: "/download",
  downloadLabel: "Download current build",
  currentBuildLabel: "Current build",
  whereThingsStandLabel: "Where things stand",
  phasesEyebrow: "Three phases",
  phasesTitle: "One route, one active phase at a time.",
  phasesAriaLabel: "Roadmap phases",
  openPhaseLabel: "Open",
  selectedPhaseEyebrow: "Selected phase",
  whyThisPhaseMatters: "Why this phase matters",
};

export function RoadmapShell({ chapters, repoSnapshot, copy: copyOverrides }: RoadmapShellProps) {
  const copy = { ...defaultCopy, ...copyOverrides };
  const [activeId, setActiveId] = useState(chapters[0]?.id ?? "");
  const [openCheckpoints, setOpenCheckpoints] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      chapters.flatMap((chapter) =>
        chapter.checkpoints.map((checkpoint) => [checkpoint.id, Boolean(checkpoint.featured)]),
      ),
    ),
  );

  const activeIndex = useMemo(() => {
    const index = chapters.findIndex((chapter) => chapter.id === activeId);
    return index >= 0 ? index : 0;
  }, [activeId, chapters]);

  const activeChapter = chapters[activeIndex] ?? chapters[0];

  function toggleCheckpoint(id: string) {
    setOpenCheckpoints((current) => ({
      ...current,
      [id]: !current[id],
    }));
  }

  return (
    <div className={styles.pageShell}>
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>{copy.heroEyebrow}</p>
          <h1 className={styles.heroTitle}>{copy.heroTitle}</h1>
          <p className={styles.heroLead}>{copy.heroLead}</p>
          <div className={styles.heroActions}>
            <Link href={copy.journeyHref} className="cta-secondary">
              {copy.journeyLabel}
            </Link>
            <Link href={copy.downloadHref} className="cta-primary">
              {copy.downloadLabel}
            </Link>
          </div>
        </div>

        <div className={styles.heroMeta}>
          <article className={styles.metaCard}>
            <p className={styles.metaLabel}>{copy.currentBuildLabel}</p>
            <p className={styles.metaValue}>{repoSnapshot.release}</p>
            <p className={styles.metaCopy}>{repoSnapshot.stamp}</p>
          </article>
          <article className={styles.metaCard}>
            <p className={styles.metaLabel}>{copy.whereThingsStandLabel}</p>
            <div className={styles.metaList}>
              {repoSnapshot.signals.map((signal) => (
                <p key={signal}>{signal}</p>
              ))}
            </div>
          </article>
        </div>
      </section>

      <section className={styles.board}>
        <div className={styles.boardHeader}>
          <div>
            <p className={styles.eyebrow}>{copy.phasesEyebrow}</p>
            <h2 className={styles.boardTitle}>{copy.phasesTitle}</h2>
          </div>
          <div className={styles.phaseTabs} role="tablist" aria-label={copy.phasesAriaLabel}>
            {chapters.map((chapter, index) => {
              const active = chapter.id === activeChapter.id;
              return (
                <button
                  key={chapter.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`${styles.phaseTab} ${active ? styles.phaseTabActive : ""}`}
                  onClick={() => setActiveId(chapter.id)}
                >
                  <span className={styles.phaseTabIndex}>{String(index + 1).padStart(2, "0")}</span>
                  <span className={styles.phaseTabText}>
                    <strong>{chapter.title}</strong>
                    <span>{chapter.horizon}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className={styles.boardBody}>
          <div className={styles.routeCanvas} aria-hidden="true">
            <svg viewBox="0 0 880 360" className={styles.routeSvg}>
              <path
                d="M 110 250 C 250 60 360 75 450 155 S 650 320 770 185"
                className={styles.routeTrack}
              />
              <path
                d="M 110 250 C 250 60 360 75 450 155 S 650 320 770 185"
                className={styles.routeGlow}
              />
            </svg>
            {chapters.map((chapter, index) => {
              const active = index === activeIndex;
              const complete = index < activeIndex;
              const layout = STATION_LAYOUT[index] ?? STATION_LAYOUT[STATION_LAYOUT.length - 1];
              return (
                <button
                  key={chapter.id}
                  type="button"
                  className={`${styles.station} ${active ? styles.stationActive : ""} ${complete ? styles.stationComplete : ""}`}
                  style={{ left: layout.left, top: layout.top }}
                  onClick={() => setActiveId(chapter.id)}
                  aria-pressed={active}
                  aria-label={`${copy.openPhaseLabel} ${chapter.title}`}
                >
                  <span className={styles.stationDot} />
                  <span className={styles.stationCard}>
                    <span className={styles.stationPhase}>{chapter.phase}</span>
                    <strong>{chapter.title}</strong>
                    <span className={styles.stationStatus}>{chapter.status}</span>
                  </span>
                </button>
              );
            })}
          </div>

          <article className={styles.activePanel}>
            <p className={styles.eyebrow}>{activeChapter.phase}</p>
            <div className={styles.activePanelHead}>
              <div>
                <h3 className={styles.activeTitle}>{activeChapter.title}</h3>
                <p className={styles.activeStatus}>{activeChapter.status}</p>
              </div>
              <span className={styles.horizonChip}>{activeChapter.horizon}</span>
            </div>
            <p className={styles.activeIntro}>{activeChapter.intro}</p>
            <p className={styles.activeBody}>{activeChapter.body}</p>
            <div className={styles.signalCloud}>
              {activeChapter.repoSignals.map((signal) => (
                <span key={signal} className={styles.signalChip}>
                  {signal}
                </span>
              ))}
            </div>
          </article>
        </div>
      </section>

      <section className={styles.detailsSection}>
        <div className={styles.detailsHeader}>
          <div>
            <p className={styles.eyebrow}>{copy.selectedPhaseEyebrow}</p>
            <h2 className={styles.detailsTitle}>{activeChapter.title}</h2>
            <p className={styles.detailsCopy}>{activeChapter.outcome}</p>
          </div>
          <article className={styles.outcomeCard}>
            <p className={styles.metaLabel}>{copy.whyThisPhaseMatters}</p>
            <p className={styles.outcomeText}>{activeChapter.body}</p>
          </article>
        </div>

        <div className={styles.checkpointGrid}>
          {activeChapter.checkpoints.map((checkpoint, checkpointIndex) => {
            const isOpen = Boolean(openCheckpoints[checkpoint.id]);
            return (
              <article key={checkpoint.id} className={`${styles.checkpointCard} ${isOpen ? styles.checkpointCardOpen : ""}`}>
                <button
                  type="button"
                  className={styles.checkpointButton}
                  onClick={() => toggleCheckpoint(checkpoint.id)}
                  aria-expanded={isOpen}
                  aria-controls={`${checkpoint.id}-panel`}
                >
                  <span className={styles.checkpointNumber}>
                    {String(activeIndex + 1).padStart(2, "0")}.{String(checkpointIndex + 1).padStart(2, "0")}
                  </span>
                  <span className={styles.checkpointMain}>
                    <span className={styles.checkpointTitle}>{checkpoint.title}</span>
                    <span className={styles.checkpointSummary}>{checkpoint.summary}</span>
                  </span>
                  <span className={styles.checkpointMeta}>
                    <span className={`${styles.statusChip} ${styles[`status${capitalize(checkpoint.tone)}`]}`}>{checkpoint.status}</span>
                    <span className={styles.checkpointHorizon}>{checkpoint.horizon}</span>
                    <span className={styles.checkpointToggle}>{isOpen ? "−" : "+"}</span>
                  </span>
                </button>
                {isOpen ? (
                  <div id={`${checkpoint.id}-panel`} className={styles.checkpointBody}>
                    <p className={styles.checkpointDetail}>{checkpoint.detail}</p>
                    <ul className={styles.signalList}>
                      {checkpoint.signals.map((signal) => (
                        <li key={signal}>{signal}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
