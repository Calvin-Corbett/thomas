import { SiteUpdatesPage } from "@/components/site-updates-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("updates", "en");

export default async function UpdatesPage() {
  return <SiteUpdatesPage locale="en" />;
}
