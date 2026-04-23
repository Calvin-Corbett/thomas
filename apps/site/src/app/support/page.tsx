import { SiteSupportPage } from "@/components/site-support-page";
import { buildRouteMetadata } from "@/lib/site-metadata";

export const metadata = buildRouteMetadata("support", "en");

export default function SupportPage() {
  return <SiteSupportPage locale="en" />;
}
