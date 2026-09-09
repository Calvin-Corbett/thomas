import { RouteLoadingShell } from "@/components/system-route-state";

export default function InfiniteLoading() {
  return (
    <RouteLoadingShell
      eyebrow="Infinite"
      title="Thomas Infinite control plane"
      intro="Loading Infinite scope, controls, and deployment constraints."
      versionLabel="Loading"
    />
  );
}
