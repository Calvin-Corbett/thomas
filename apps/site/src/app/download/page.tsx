import { SiteDownloadPage } from "@/components/site-download-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("download", "en");

export default async function DownloadPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <SiteDownloadPage locale="en" searchParams={searchParams} />;
}
