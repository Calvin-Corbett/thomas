import { buildRouteMetadata } from "@/lib/site-metadata";
import { SiteHomePage } from "@/components/site-home-page";

export const metadata = buildRouteMetadata("home", "en");

export default function HomePage() {
  return <SiteHomePage locale="en" />;
}
