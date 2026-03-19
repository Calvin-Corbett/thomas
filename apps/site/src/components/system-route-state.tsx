import type { ReactNode } from "react";
import Link from "next/link";
import { CalloutBlock } from "@/components/system-callout";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";

type RouteStateShellProps = {
  title: string;
  intro: string;
  eyebrow: string;
  versionLabel?: string;
  children?: ReactNode;
};

export function RouteLoadingShell({ title, intro, eyebrow, versionLabel, children }: RouteStateShellProps) {
  return (
    <SystemPageShell
      eyebrow={eyebrow}
      title={title}
      intro={intro}
      versionLabel={versionLabel}
      meta={<span className="status-chip status-chip-partial">Loading</span>}
    >
      <SystemSection title="Loading state">
        <CalloutBlock tone="info" title="Loading content">
          This route is collecting route-level data and rendering in a safe state.
        </CalloutBlock>
        {children ? <p className="system-metric-line">{children}</p> : null}
      </SystemSection>
    </SystemPageShell>
  );
}

type RouteErrorShellProps = {
  title: string;
  intro: string;
  eyebrow: string;
  versionLabel?: string;
  error: unknown;
  retryHref: string;
};

export function RouteErrorShell({
  title,
  intro,
  eyebrow,
  versionLabel,
  error,
  retryHref,
}: RouteErrorShellProps) {
  return (
    <SystemPageShell eyebrow={eyebrow} title={title} intro={intro} versionLabel={versionLabel}>
      <SystemSection title="Route currently unavailable">
        <CalloutBlock tone="warning" title="Temporary failure">
          {error instanceof Error ? error.message : "This route hit a non-fatal exception while loading optional page data."}
        </CalloutBlock>
        <p className="system-metric-line">The route shell is still available. Retry once or open a cached view.</p>
        <p className="system-metric-line">
          <Link href={retryHref}>Try again</Link>
        </p>
      </SystemSection>
    </SystemPageShell>
  );
}
