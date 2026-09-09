import { SiteRoadmapPage } from "@/components/site-roadmap-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("roadmap", "en");

export default function RoadmapPage() {
  return <SiteRoadmapPage locale="en" />;
}
