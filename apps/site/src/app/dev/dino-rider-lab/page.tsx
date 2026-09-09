import type { Metadata } from "next";
import { CodeBlock } from "@/components/system-code-block";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Dino Rider Lab",
  description: "Developer utility for sprite and mount alignment checks",
  robots: {
    index: false,
    follow: false,
  },
};

const mountTargets = {
  saddleTop: 12,
  saddleLeft: 40,
  saddleWidth: 16,
  bodyTop: 17,
  bodyLeft: 22,
  bodyWidth: 42,
  bodyHeight: 19,
};

export default function DinoRiderLabPage() {
  return (
    <SystemPageShell
      eyebrow="Dev utilities"
      title="Dino Rider Lab"
      intro="This page is intentionally isolated for visual QA and mount geometry debugging."
      versionLabel="Dev-only"
    >
      <SystemSection title="Visual target values" intro="Keep these values in sync with footer and deploy checks.">
        <CodeBlock title="Mount constants" language="json">
          {JSON.stringify(mountTargets, null, 2)}
        </CodeBlock>
      </SystemSection>

      <SystemSection title="Sprite alignment workspace" intro="Use this preview to verify rider positioning before visual deploys.">
        <section className="dino-lab-shell">
          <header className="dino-lab-header">
            <p className="dino-lab-kicker">Dev only</p>
            <p className="system-page-title">Dino Rider Mount Lab</p>
            <p>
              Use this page to verify the robot is seated on the dino back before footer deployment.
            </p>
          </header>
          <div className="dino-lab-stage">
            <div className="dino-lab-grid" aria-hidden />
            <div className="dino-lab-canvas">
              <div className="dino-lab-target dino-lab-target-saddle" style={{ left: `${mountTargets.saddleLeft}px`, top: `${mountTargets.saddleTop}px`, width: `${mountTargets.saddleWidth}px` }}>
                saddle
              </div>
              <div className="dino-lab-target dino-lab-target-body" style={{ left: `${mountTargets.bodyLeft}px`, top: `${mountTargets.bodyTop}px`, width: `${mountTargets.bodyWidth}px`, height: `${mountTargets.bodyHeight}px` }}>
                body
              </div>
              <span className="dino-rider-sprite dino-lab-rider">
                <span className="trex-tail" />
                <span className="trex-body" />
                <span className="trex-belly" />
                <span className="trex-neck" />
                <span className="trex-head" />
                <span className="trex-jaw" />
                <span className="trex-eye" />
                <span className="trex-arm" />
                <span className="trex-leg trex-leg-back" />
                <span className="trex-leg trex-leg-front" />
                <span className="trex-saddle" />
                <span className="trex-saddle-strap" />
                <span className="dino-rider-robot-wrap">
                  <span className="pixel-agent pixel-agent-orange dino-rider-robot">
                    <span className="agent-head">
                      <span className="agent-eye agent-eye-left" />
                      <span className="agent-eye agent-eye-right" />
                    </span>
                    <span className="agent-body" />
                    <span className="agent-leg agent-leg-left" />
                    <span className="agent-leg agent-leg-right" />
                  </span>
                </span>
              </span>
            </div>
          </div>
        </section>
      </SystemSection>

      <SystemSection title="Navigation" intro="Return to the public pages once validation is complete.">
        <p className="system-metric-line">
          <Link className="text-link" href="/">
            Back to site
          </Link>
        </p>
      </SystemSection>
    </SystemPageShell>
  );
}
