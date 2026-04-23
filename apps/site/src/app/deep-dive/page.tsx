import { SiteDeepDivePage } from "@/components/site-deep-dive-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("deep-dive", "en");

export default function DeepDivePage() {
  return <SiteDeepDivePage locale="en" />;
}
