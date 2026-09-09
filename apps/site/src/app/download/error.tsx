 "use client";

import { RouteErrorShell } from "@/components/system-route-state";

type DownloadErrorProps = {
  error: Error;
};

export default function DownloadError({ error }: DownloadErrorProps) {
  return (
    <RouteErrorShell
      eyebrow="Download"
      title="Install Thomas for your platform"
      intro="The download page could not be prepared."
      retryHref="/download"
      error={error}
      versionLabel="Unavailable"
    />
  );
}
