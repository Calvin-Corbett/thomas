import { RouteLoadingShell } from "@/components/system-route-state";

export default function UpdatesLoading() {
  return (
    <RouteLoadingShell
      eyebrow="Release Notes"
      title="Versioned changes and release scope"
      intro="Versioned release entries are loading."
      versionLabel="Loading"
    />
  );
}
