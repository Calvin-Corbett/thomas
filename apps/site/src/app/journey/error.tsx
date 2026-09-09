 "use client";

import { RouteErrorShell } from "@/components/system-route-state";

type JourneyErrorProps = {
  error: Error;
};

export default function JourneyError({ error }: JourneyErrorProps) {
  return (
    <RouteErrorShell
      eyebrow="Journey"
      title="Architecture and production maturity"
      intro="The architecture timeline could not be loaded."
      retryHref="/journey"
      error={error}
      versionLabel="Unavailable"
    />
  );
}
