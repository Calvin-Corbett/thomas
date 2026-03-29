import { SiteMarketplacePage } from "@/components/site-marketplace-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("marketplace", "en");

export default function MarketplacePage() {
  return <SiteMarketplacePage locale="en" />;
}
