import { SiteJourneyPage } from "@/components/site-journey-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("journey", "en");

export default function JourneyPage() {
  return <SiteJourneyPage locale="en" />;
}
