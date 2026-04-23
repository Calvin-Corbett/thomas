import { RouteLoadingShell } from "@/components/system-route-state";

export default function DownloadLoading() {
  return (
    <RouteLoadingShell
      eyebrow="Download"
      title="Install Thomas for your platform"
      intro="Loading release metadata and download options."
      versionLabel="Loading"
    />
  );
}
