import type { ReactNode } from "react";
import { SystemPageShellClient } from "@/components/system-page-shell-client";

type SystemPageShellProps = {
  eyebrow?: string;
  title: string;
  intro?: string;
  versionLabel?: string;
  meta?: ReactNode;
  persistDetails?: boolean;
  children: ReactNode;
};

export function SystemPageShell({
  eyebrow,
  title,
  intro,
  versionLabel,
  persistDetails,
  meta,
  children,
}: SystemPageShellProps) {
  return (
    <SystemPageShellClient
      eyebrow={eyebrow}
      title={title}
      intro={intro}
      versionLabel={versionLabel}
      meta={meta}
      persistDetails={persistDetails}
    >
      {children}
    </SystemPageShellClient>
  );
}
