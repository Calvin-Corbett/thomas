import Link from "next/link";
import type { Metadata } from "next";
import { StatusChip } from "@/components/status-chip";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";

export const metadata: Metadata = {
  title: "The Journey So Far",
  description: "What changed, what's next, and why Thomas works the way it does.",
};

const architectureMilestones = [
  {
    date: "2026-02",
    title: "Execution boundary enforced",
    status: "implemented" as const,
    text: "Request parsing and approval gates now sit in front of every execution path.",
  },
  {
    date: "2026-02",
    title: "Command family contracts",
    status: "implemented" as const,
    text: "Each command family has depth markers and validation tied to releases.",
  },
  {
    date: "2026-02",
    title: "Release-linked observability",
    status: "partial" as const,
    text: "Download, artifact, and log metadata merged into one evidence trail.",
  },
  {
    date: "2026-03",
    title: "Gateway and CLI alignment",
    status: "partial" as const,
    text: "API routes and CLI commands now share the same validation surface.",
  },
];

const principles = [
  "No unbounded execution. Every action is tied to a command family and policy gate.",
  "Local-first operation, with remote integration explicit and bounded.",
  "We only ship claims backed by release artifacts and release notes.",
];

export default function JourneyPage() {
  return (
    <SystemPageShell
      title="The Journey So Far"
      versionLabel="v0.14.38"
    >
      <SystemSection title="Roadmap vs journey">
        <div className="system-metric-grid">
          <article className="system-metric-card">
            <p className="system-metric-title">Roadmap</p>
            <p className="system-metric-line">
              The roadmap is the forward-looking page: where Thomas is headed, what the three big phases are, and what each phase is trying to unlock.
            </p>
            <Link href="/roadmap" className="text-link">
              Open the roadmap
            </Link>
          </article>
          <article className="system-metric-card">
            <p className="system-metric-title">Journey</p>
            <p className="system-metric-line">
              This page stays practical. It tracks what has actually shipped, what changed in the architecture, and what
              constraints still define the product.
            </p>
          </article>
        </div>
      </SystemSection>

      <SystemSection title="Why Thomas exists">
        <p className="system-metric-line">
          Most AI tools let the AI do whatever it wants. Thomas makes every action go through an
          approval step first. Nothing runs without your OK.
        </p>
        <p className="system-metric-line">
          The goal: a local execution tool with explicit approvals and verifiable contracts for
          every command. You stay in control.
        </p>
      </SystemSection>

      <SystemSection title="What we won't compromise on">
        <ul className="system-bullets">
          {principles.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </SystemSection>

      <SystemSection title="Milestones">
        <div className="system-version-list">
          {architectureMilestones.map((milestone) => (
            <article
              key={milestone.title}
              className="system-version-card"
              style={{ padding: "0.8rem" }}
            >
              <div className="system-version-head">
                <div>
                  <p className="system-metric-title">{milestone.date}</p>
                  <p className="system-section-title">{milestone.title}</p>
                </div>
                <StatusChip status={milestone.status} />
              </div>
              <p className="system-metric-line" style={{ marginTop: "0.4rem" }}>{milestone.text}</p>
            </article>
          ))}
        </div>
      </SystemSection>

      <SystemSection title="What's next">
        <ul className="system-bullets">
          <li>Expand plugin sandbox and policy checks.</li>
          <li>Improve release reproducibility without adding complexity.</li>
          <li>Keep the control plane as a view over local execution, not a standalone agent.</li>
        </ul>
        <p className="system-metric-line" style={{ marginTop: "0.4rem" }}>
          <strong>What's not planned:</strong> letting the AI run anything without approval,
          adding features without contract-backed evidence, or skipping reproducibility checks.
        </p>
      </SystemSection>

      <SystemSection title="Thomas Infinite" id="infinite">
        <p className="system-metric-line">
          The mobile companion app for Thomas. Still in development.
        </p>
        <p className="system-metric-line">
          See what Thomas is doing from your phone. Queue commands, check results, approve actions.
          Everything still goes through Thomas for policy, validation, and audit â€” Infinite is a
          window, not a backdoor.
        </p>
        <div className="system-metric-grid" style={{ marginTop: "0.6rem" }}>
          <article className="system-metric-card">
            <p className="system-metric-title">What stays local</p>
            <p className="system-metric-line">Infinite is a UI surface, not a standalone runtime.</p>
          </article>
          <article className="system-metric-card">
            <p className="system-metric-title">What can be remote</p>
            <p className="system-metric-line">Tokened transport and pairing are supported; key rotation is still in progress.</p>
          </article>
          <article className="system-metric-card">
            <p className="system-metric-title">What it won't do</p>
            <p className="system-metric-line">Infinite never runs commands outside the Thomas core path.</p>
          </article>
        </div>
      </SystemSection>
    </SystemPageShell>
  );
}
