 "use client";

import { RouteErrorShell } from "@/components/system-route-state";

type UpdatesErrorProps = {
  error: Error;
};

export default function UpdatesError({ error }: UpdatesErrorProps) {
  return (
    <RouteErrorShell
      eyebrow="Release Notes"
      title="Versioned changes and release scope"
      intro="Release feed rendering is degraded."
      retryHref="/updates"
      error={error}
      versionLabel="Unavailable"
    />
  );
}
