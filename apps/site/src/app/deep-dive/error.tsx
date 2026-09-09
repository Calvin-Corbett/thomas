 "use client";

import { RouteErrorShell } from "@/components/system-route-state";

type DeepDiveErrorProps = {
  error: Error;
};

export default function DeepDiveError({ error }: DeepDiveErrorProps) {
  return (
    <RouteErrorShell
      eyebrow="Engineering Deep Dive"
      title="Execution architecture and command contracts"
      intro="The deep-dive view could not be fully prepared."
      retryHref="/deep-dive"
      error={error}
      versionLabel="Unavailable"
    />
  );
}
