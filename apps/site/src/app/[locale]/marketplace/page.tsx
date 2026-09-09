import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SiteMarketplacePage } from "@/components/site-marketplace-page";
import { buildRouteMetadata } from "@/lib/site-metadata";
import { isSupportedSiteLocale } from "@/lib/site-locale";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!isSupportedSiteLocale(locale) || locale === "en") {
    return {};
  }
  return buildRouteMetadata("marketplace", locale);
}

export default async function LocalizedMarketplacePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isSupportedSiteLocale(locale) || locale === "en") {
    notFound();
  }
  return <SiteMarketplacePage locale={locale} />;
}
