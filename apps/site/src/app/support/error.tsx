 "use client";

import { RouteErrorShell } from "@/components/system-route-state";

type SupportErrorProps = {
  error: Error;
};

export default function SupportError({ error }: SupportErrorProps) {
  return (
    <RouteErrorShell
      eyebrow="Support"
      title="Issue reporting and troubleshooting"
      intro="Support guidance failed to initialize."
      retryHref="/support"
      error={error}
      versionLabel="Unavailable"
    />
  );
}
