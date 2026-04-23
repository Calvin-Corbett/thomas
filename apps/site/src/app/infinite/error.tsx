 "use client";

import { RouteErrorShell } from "@/components/system-route-state";

type InfiniteErrorProps = {
  error: Error;
};

export default function InfiniteError({ error }: InfiniteErrorProps) {
  return (
    <RouteErrorShell
      eyebrow="Infinite"
      title="Thomas Infinite control plane"
      intro="Infinite scope content could not be prepared."
      retryHref="/infinite"
      error={error}
      versionLabel="Unavailable"
    />
  );
}
